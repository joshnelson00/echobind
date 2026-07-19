import httpx

OLLAMA_HOST = "http://127.0.0.1:11434"
MODEL = "qwen2.5:7b"

SYSTEM_PROMPT = """You are an assistant that converts lecture and meeting transcripts \
into structured study notes. You identify key points, important terminology, and \
action items. You never fabricate information not present in the transcript."""


def load_transcript(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_prompt(transcript: str) -> str:
    return f"""Summarize the following transcript into structured notes.

Format your response as:
1. **Overview** (2-3 sentences)
2. **Key Points** (bulleted list)
3. **Important Terms** (term: definition, if any technical terms were defined)
4. **Action Items** (if any were mentioned, otherwise omit this section)

Transcript:
\"\"\"
{transcript}
\"\"\"
"""


async def summarize(transcript: str) -> str:
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_prompt(transcript)},
                ],
                "stream": False,
            },
        )
        response.raise_for_status()
        return response.json()["message"]["content"]