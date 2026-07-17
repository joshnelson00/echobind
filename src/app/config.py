import os
from pathlib import Path


# Base project directory
BASE_DIR = Path(__file__).resolve().parent.parent


# Storage directories
UPLOAD_DIR = BASE_DIR / "uploads"
TRANSCRIPT_DIR = BASE_DIR / "transcripts"
SUMMARY_DIR = BASE_DIR / "summaries"


# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///jobs.db"
)


# Worker configuration
WORKER_NAME = os.getenv(
    "WORKER_NAME",
    "local-worker"
)

HEARTBEAT_INTERVAL = int(
    os.getenv(
        "HEARTBEAT_INTERVAL",
        "30"
    )
)


# Create directories if they don't exist
UPLOAD_DIR.mkdir(
    exist_ok=True
)

TRANSCRIPT_DIR.mkdir(
    exist_ok=True
)

SUMMARY_DIR.mkdir(
    exist_ok=True
)