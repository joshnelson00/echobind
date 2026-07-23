import json
import re
import httpx
import logging
from pathlib import Path
from pydantic import BaseModel, ValidationError
from api.app.config import OLLAMA_HOST, OLLAMA_MODEL, VAULT_PATH

# --- Chunking config -------------------------------------------------------
# qwen3:8b at Q4 is ~5-5.5GB on an 8GB card. We keep num_ctx modest per call
# so the whole thing stays GPU-resident (partial CPU offload is a major
# source of inconsistent output quality/speed). Rough token estimate below
# is chars/4, which is close enough for chunk-sizing purposes; it doesn't
# need to be exact.
CHARS_PER_TOKEN_ESTIMATE = 4
CHUNK_TOKEN_TARGET = 2200          # per-chunk transcript budget
CHUNK_CTX = 6144                   # num_ctx for the map (fact extraction) stage
REDUCE_CTX = 12288                 # num_ctx for the reduce (organize) stage — input is facts only, not raw transcript, so it's much smaller than the old single-call approach
DIAGRAM_CTX = 8192

# --- Prompts -----------------------------------------------------------
# Split into two focused stages instead of one prompt carrying 13 rules at
# once. Each stage now has a short, narrow instruction set, which an
# 8B model follows far more reliably than a long rule list combined with
# grammar-constrained JSON decoding.

EXTRACT_PROMPT = """
You extract raw facts from a transcript chunk. This is ONE piece of a
longer transcript — do not summarize, do not add structure, just pull out
what is actually said.

Rules:
1. Output ONLY JSON matching the schema.
2. Never fabricate. If something is unclear, say so explicitly rather than guessing.
3. Preserve concrete details: numbers, dates, names, percentages, commands, examples, comparisons.
4. Write facts in the order they appear.
5. Each fact is one plain-text sentence, max two. No markdown syntax anywhere.
6. List every technical term or acronym used in this chunk, even if only briefly mentioned.
7. List any deadlines, requirements, or action items mentioned in this chunk, with full detail (dates, conditions).
8. Do not skip details to save space. Do not editorialize.
"""

REDUCE_PROMPT = """
You organize a list of previously-extracted facts (already pulled from a
full transcript, in order) into structured study notes.

Rules:
1. Output ONLY JSON matching the schema.
2. Use only the facts provided — do not add new information.
3. Group facts into 4-8 categories representing major sections, in the order they occurred.
   - Each category should have 3-8 points.
   - Merge overlapping/duplicate categories rather than splitting similar content apart.
   - Avoid categories with only one point — merge them into a related category instead.
4. Each point is one plain-text sentence (max two), preserving numbers/dates/names given in the facts. No markdown syntax.
5. Deduplicate important_terms (same term from multiple chunks = one entry). Keep the most complete definition.
6. Deduplicate and merge action_items; keep all deadlines/requirements/dates.
7. Write a 4-6 sentence overview that orients someone who missed the whole thing: what topic/course/meeting this was and what subtopics were covered and how they connect.
8. Never output markdown anywhere in any field.
"""

DIAGRAM_PROMPT = """
You generate Mermaid diagrams from structured study notes.

Rules:

- Return ONLY JSON.
- Do not summarize.
- Use ONLY information present.
- If no diagram makes sense return:

{
    "has_diagram": false,
    "diagram_explanation": "",
    "diagram_mermaid": ""
}

Otherwise, only generate a diagram if one of these exists in the notes:

- workflow
- architecture
- process
- state machine
- request flow
- hierarchy
- dependency graph
- algorithm

Mermaid Rules:

- Only use flowchart TD.
- Never use graph LR.
- Never use sequenceDiagram unless dialogue actually occurs.
- Node text must not contain quotes.
- Node text should be short (<6 words).
- Every node must have an id.
- Never output markdown code fences (no ```mermaid).

Example:

flowchart TD

A[Client]
B[API]
C[Database]

A --> B
B --> C

Prefer flowchart TD.
Never invent relationships.
"""

# --- Schemas -------------------------------------------------------------

FACTS_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Raw facts from this chunk, in order, one sentence each.",
        },
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "definition": {"type": "string"},
                },
                "required": ["term", "definition"],
            },
        },
        "action_items": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["facts", "terms", "action_items"],
}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {
            "type": "string",
            "description": (
                "4-6 sentences giving real context: what topic/course/meeting "
                "this is, what specific subtopics were covered, and how they "
                "connect. Should orient someone who missed this entirely — "
                "not just a one-line label like 'covers OS history.'"
            ),
        },
        "key_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": (
                            "Short label grouping related points, e.g. "
                            "'Course Logistics', 'Grading', 'OS History', "
                            "'Architecture'. Choose categories that fit the "
                            "actual content — do not force a fixed set."
                        ),
                    },
                    "points": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Points in this category, in the order discussed. "
                            "Each point is a single plain-text sentence, no markdown."
                        ),
                    },
                },
                "required": ["category", "points"],
            },
        },
        "important_terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "definition": {"type": "string"},
                },
                "required": ["term", "definition"],
            },
        },
        "action_items": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "overview",
        "key_points",
        "important_terms",
        "action_items",
    ],
}

DIAGRAM_SCHEMA = {
    "type": "object",
    "properties": {
        "has_diagram": {"type": "boolean"},
        "diagram_explanation": {"type": "string"},
        "diagram_mermaid": {"type": "string"},
    },
    "required": [
        "has_diagram",
        "diagram_explanation",
        "diagram_mermaid",
    ],
}

logger = logging.getLogger(__name__)

# --- Pydantic models used purely for validating the model's JSON before we
# trust it. If validation fails we retry the call rather than rendering
# malformed content. ---

class Term(BaseModel):
    term: str
    definition: str


class ChunkFacts(BaseModel):
    facts: list[str]
    terms: list[Term]
    action_items: list[str]


class KeyPointGroup(BaseModel):
    category: str
    points: list[str]


class Notes(BaseModel):
    overview: str
    key_points: list[KeyPointGroup]
    important_terms: list[Term]
    action_items: list[str]


class Diagram(BaseModel):
    has_diagram: bool
    diagram_explanation: str
    diagram_mermaid: str


def load_transcript(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

STORED_FILENAME_PATTERN = re.compile(
    r"^(?P<class_name>[^_]+)_(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{6})_(?P<original>.+)$"
)


LEGACY_FILENAME_PATTERN = re.compile(
    r"^(?P<date_compact>\d{8})_(?P<time>\d{6})_(?P<original>.+)$"
)


def parse_stored_filename(stored_filename: str) -> dict:
    """
    Recovers class_name/date/time from a filename produced by the /upload
    endpoint: {class_name}_{date}_{time}_{original_filename}.

    Falls back to the legacy {date}_{time}_{original} format (no class
    prefix) for jobs uploaded before the class-name change, tagging them
    "unclassified" rather than failing outright — a formatting mismatch
    shouldn't discard an already-completed transcription/summarization run.
    """
    stem = Path(stored_filename).name

    match = STORED_FILENAME_PATTERN.match(stem)
    if match:
        return match.groupdict()

    legacy_match = LEGACY_FILENAME_PATTERN.match(stem)
    if legacy_match:
        d = legacy_match.groupdict()
        date_str = f"{d['date_compact'][0:4]}-{d['date_compact'][4:6]}-{d['date_compact'][6:8]}"
        logger.warning(
            "stored_filename %r is in the legacy (no class prefix) format — "
            "tagging as 'unclassified'. Was this uploaded before the "
            "class_name change to server.py?",
            stored_filename,
        )
        return {"class_name": "unclassified", "date": date_str, "time": d["time"], "original": d["original"]}

    raise ValueError(f"Filename doesn't match expected pattern: {stored_filename!r}")


def write_to_obsidian(stored_filename: str, markdown_content: str, vault_path: Path = VAULT_PATH) -> Path:
    """
    Parses class_name/date out of stored_filename and writes the note into
    the vault. Filename is just the date (YYYY-MM-DD.md); if a note for
    that date already exists (e.g. a second class that day), appends a new
    section instead of overwriting the earlier one.
    """
    parsed = parse_stored_filename(stored_filename)
    class_name = parsed["class_name"]
    date_str = parsed["date"]

    vault_path.mkdir(parents=True, exist_ok=True)
    note_path = vault_path / f"{date_str}.md"

    section = f"# {class_name} — {date_str}\n\n{markdown_content}\n"

    if note_path.exists():
        with note_path.open("a", encoding="utf-8") as f:
            f.write("\n---\n\n" + section)
    else:
        note_path.write_text(section, encoding="utf-8")

    return note_path

def chunk_transcript(transcript: str, target_tokens: int = CHUNK_TOKEN_TARGET) -> list[str]:
    """
    Splits the transcript into sequential chunks, each under target_tokens
    (estimated by chars/4). Splits on paragraph/line boundaries so we don't
    cut mid-sentence. This exists because a full transcript sent in one
    call can silently exceed num_ctx — Ollama truncates rather than erroring,
    which was the most likely cause of missing/inconsistent content.
    """
    target_chars = target_tokens * CHARS_PER_TOKEN_ESTIMATE
    paragraphs = re.split(r"\n\s*\n", transcript.strip())

    chunks = []
    current = []
    current_len = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        para_len = len(para)

        # A single paragraph larger than the whole budget: hard-split it.
        if para_len > target_chars:
            if current:
                chunks.append("\n\n".join(current))
                current, current_len = [], 0
            for i in range(0, para_len, target_chars):
                chunks.append(para[i:i + target_chars])
            continue

        if current_len + para_len > target_chars and current:
            chunks.append("\n\n".join(current))
            current, current_len = [], 0

        current.append(para)
        current_len += para_len

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def build_extract_user_prompt(chunk: str, index: int, total: int) -> str:
    return f"""
This is chunk {index + 1} of {total} from a transcript, in order.

Transcript chunk:

{chunk}
"""


def build_reduce_user_prompt(all_facts: list[str], all_terms: list[dict], all_action_items: list[str]) -> str:
    return f"""
Organize the following extracted facts into structured study notes.
The facts are already in transcript order.

Facts:
{json.dumps(all_facts, indent=2)}

Terms mentioned (deduplicate, keep the most complete definition):
{json.dumps(all_terms, indent=2)}

Action items mentioned (deduplicate, keep all deadlines/requirements):
{json.dumps(all_action_items, indent=2)}
"""


def strip_think(raw: str) -> str:
    """
    qwen3 is a hybrid reasoning model — even when not explicitly asked to
    reason, it can emit <think>...</think> content before the actual answer.
    Ollama's grammar-constrained `format` decoding applies to the full
    output stream, so leaked think-tokens can break JSON parsing entirely
    or eat into num_predict before the real JSON starts. We strip defensively
    in addition to disabling thinking via the request's "think" flag below.
    """
    return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()


def sanitize_text(s: str) -> str:
    """
    Strips markdown syntax the model sneaks into individual string fields
    despite instructions not to, since the schema enforces JSON structure
    but not the content of each string.
    """
    if not isinstance(s, str):
        return s
    s = s.strip()
    s = re.sub(r"^[-*•]\s+", "", s)            # stray leading bullet marker
    s = re.sub(r"^#{1,6}\s+", "", s)            # stray leading header marker
    s = re.sub(r"\*\*(.*?)\*\*", r"\1", s)      # stray bold
    s = re.sub(r"(?<!\w)\*(.*?)\*(?!\w)", r"\1", s)  # stray italics
    s = re.sub(r"`([^`]*)`", r"\1", s)          # stray inline code
    s = re.sub(r"\s*\n+\s*", " ", s)            # collapse embedded newlines/nested bullets
    s = re.sub(r"\s{2,}", " ", s)               # collapse repeated whitespace
    return s.strip()


def sanitize_notes(data: dict) -> dict:
    data["overview"] = sanitize_text(data["overview"])
    for group in data["key_points"]:
        group["category"] = sanitize_text(group["category"])
        group["points"] = [sanitize_text(p) for p in group["points"] if sanitize_text(p)]
    for entry in data["important_terms"]:
        entry["term"] = sanitize_text(entry["term"])
        entry["definition"] = sanitize_text(entry["definition"])
    data["action_items"] = [sanitize_text(a) for a in data["action_items"] if sanitize_text(a)]
    # Drop any categories that ended up empty after sanitization.
    data["key_points"] = [g for g in data["key_points"] if g["points"]]
    return data


def dedupe_terms(terms: list[dict]) -> list[dict]:
    """
    Case-insensitive dedupe on term name, keeping the longest (most complete)
    definition seen. Chunk-level extraction will legitimately repeat terms
    across chunks, so this runs before the reduce call to keep its input
    smaller and cleaner.
    """
    best: dict[str, dict] = {}
    for t in terms:
        key = t["term"].strip().lower()
        if key not in best or len(t["definition"]) > len(best[key]["definition"]):
            best[key] = t
    return list(best.values())


def clean_mermaid(raw: str) -> str:
    """
    Strips any ```mermaid / ``` fences the model added despite instructions
    not to, since the schema only constrains structure, not string content.
    Also strips stray double quotes inside node labels, since Mermaid breaks
    on unescaped quotes and rule 'Node text must not contain quotes' is only
    a prompt instruction, not an enforced constraint.
    """
    raw = raw.strip()
    raw = re.sub(r"^```(?:mermaid)?\s*\n?", "", raw)
    raw = re.sub(r"\n?```\s*$", "", raw)
    raw = raw.replace('"', "")
    return raw.strip()


def _looks_truncated(raw: str, err: Exception) -> bool:
    """
    Distinguishes "ran out of num_predict mid-string/mid-object" from other
    JSON errors. Ollama stops generation at num_predict regardless of
    whether the grammar-constrained JSON is complete, so a dense chunk can
    legitimately need more output tokens than expected. Retrying with the
    same budget in that case just reproduces the same failure — we need to
    raise the ceiling, not just re-roll temperature.
    """
    msg = str(err)
    truncated_markers = ("EOF while parsing", "unexpected end of", "expected value")
    return any(m in msg for m in truncated_markers) and not raw.rstrip().endswith("}")


async def call_structured(client, system_prompt, user_content, schema, model_cls, num_ctx, num_predict=4096, retries=2):
    """
    Calls Ollama with a JSON schema constraint, validates the result against
    a pydantic model, and retries on malformed/invalid output instead of
    letting bad data flow downstream.

    "think": False disables qwen3's reasoning mode at the API level (Ollama
    supports this for hybrid-reasoning models). We don't want or need chain-
    of-thought for a structured extraction/organization task, and leaving it
    on burns num_predict budget and risks the JSON grammar constraint
    fighting with reasoning tokens.

    If a response is cut off mid-JSON (num_predict exhausted before the
    object closed), we raise num_predict for the next attempt instead of
    just retrying with the same budget — otherwise a content-dense chunk
    fails identically on every attempt.
    """
    last_err = None
    current_num_predict = num_predict
    for attempt in range(retries + 1):
        response = await client.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "stream": False,
                "format": schema,
                "think": False,
                "options": {
                    "temperature": 0.1 if attempt == 0 else 0,
                    "top_p": 0.9,
                    "repeat_penalty": 1.15,
                    "num_ctx": num_ctx,
                    "num_predict": current_num_predict,
                },
            },
        )
        if response.status_code >= 400:
            logger.error(
                "Ollama returned %s for model=%r host=%r: %s",
                response.status_code, OLLAMA_MODEL, OLLAMA_HOST, response.text,
            )
        response.raise_for_status()
        raw = response.json()["message"]["content"]
        raw = strip_think(raw)
        try:
            validated = model_cls.model_validate_json(raw)
            return validated.model_dump()
        except (ValidationError, json.JSONDecodeError) as e:
            last_err = e
            if _looks_truncated(raw, e):
                current_num_predict = min(current_num_predict * 2, 16384)
            continue
    raise RuntimeError(
        f"Model failed to produce valid structured output after {retries + 1} attempts "
        f"(final num_predict={current_num_predict})"
    ) from last_err


async def extract_chunk_facts(client, chunk: str, index: int, total: int) -> dict:
    return await call_structured(
        client,
        EXTRACT_PROMPT,
        build_extract_user_prompt(chunk, index, total),
        FACTS_SCHEMA,
        ChunkFacts,
        num_ctx=CHUNK_CTX,
        num_predict=3072,  # bumped from 2048: dense chunks (many terms/facts) need more room; 2048 was truncating mid-JSON in practice
        retries=2,
    )


async def reduce_facts(client, all_facts: list[str], all_terms: list[dict], all_action_items: list[str]) -> dict:
    return await call_structured(
        client,
        REDUCE_PROMPT,
        build_reduce_user_prompt(all_facts, all_terms, all_action_items),
        RESPONSE_SCHEMA,
        Notes,
        num_ctx=REDUCE_CTX,
        num_predict=4096,
        retries=2,
    )


async def generate_diagram(client, notes: dict) -> dict:
    return await call_structured(
        client,
        DIAGRAM_PROMPT,
        json.dumps(notes),
        DIAGRAM_SCHEMA,
        Diagram,
        num_ctx=DIAGRAM_CTX,
        num_predict=2048,
        retries=2,
    )


def render_markdown(data: dict) -> str:
    """
    Deterministically builds Markdown from the model's JSON output.
    This is what actually guarantees consistent formatting — the model
    only has to fill in content, not remember formatting rules.
    """
    lines = []

    lines.append("## Overview")
    lines.append(data["overview"].strip())
    lines.append("")

    lines.append("## Key Points")
    for group in data["key_points"]:
        lines.append(f"**{group['category']}**")
        for point in group["points"]:
            lines.append(f"- {point}")
        lines.append("")

    if data["important_terms"]:
        lines.append("## Important Terms")
        lines.append("| Term | Definition |")
        lines.append("|---|---|")
        for entry in data["important_terms"]:
            term = entry["term"].replace("|", "\\|")
            definition = entry["definition"].replace("|", "\\|")
            lines.append(f"| {term} | {definition} |")
        lines.append("")

    if data["has_diagram"] and data["diagram_mermaid"].strip():
        lines.append("## Diagram")

        if data["diagram_explanation"].strip():
            lines.append(data["diagram_explanation"])

        lines.append("")
        lines.append("```mermaid")
        lines.append(clean_mermaid(data["diagram_mermaid"]))
        lines.append("```")
        lines.append("")

    if data["action_items"]:
        lines.append("## Action Items")
        for item in data["action_items"]:
            lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines).strip()


async def summarize(transcript: str) -> str:
    async with httpx.AsyncClient(timeout=180) as client:
        chunks = chunk_transcript(transcript)

        # Map stage: extract raw facts/terms/action-items per chunk.
        # Sequential rather than gather()'d concurrently on purpose — Ollama
        # serializes requests to a single loaded model anyway on one GPU,
        # so concurrent requests just queue and add overhead/timeout risk.
        all_facts: list[str] = []
        all_terms: list[dict] = []
        all_action_items: list[str] = []

        for i, chunk in enumerate(chunks):
            result = await extract_chunk_facts(client, chunk, i, len(chunks))
            all_facts.extend(result["facts"])
            all_terms.extend(result["terms"])
            all_action_items.extend(result["action_items"])

        all_terms = dedupe_terms(all_terms)

        # Reduce stage: organize accumulated facts into the final schema.
        notes = await reduce_facts(client, all_facts, all_terms, all_action_items)

        notes = sanitize_notes(notes)

        diagram = await generate_diagram(client, notes)

        notes.update(diagram)

        return render_markdown(notes)