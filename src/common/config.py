import os
from pathlib import Path
from dotenv import load_dotenv

# Loads .env into the process environment. Safe to call even if .env
# doesn't exist (e.g. in prod where real env vars are set another way).
load_dotenv()

# === Storage ===
STORAGE_ROOT = Path(os.getenv("ECHOBIND_STORAGE_ROOT", "./src/storage"))
UPLOAD_DIR = STORAGE_ROOT / "uploads"
TRANSCRIPTS_DIR = STORAGE_ROOT / "transcripts"
SUMMARIES_DIR = STORAGE_ROOT / "summaries"

# Ensure these exist at import time so callers never have to check
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)

# === Database ===
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{STORAGE_ROOT / 'jobs.db'}")

# === Ollama ===
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")

# === Whisper ===
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda")

# === API ===
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

# === OBSIDIAN ===
VAULT_PATH = Path("/home/joshnelson/Documents/obsidian-vault/joshnelson-vault")