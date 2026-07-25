import time
import logging
import socket
import json
from datetime import datetime, timedelta
import asyncio

from common.database import SessionLocal
from common.models import Job
from common.config import (
    UPLOAD_DIR,
    TRANSCRIPTS_DIR,
    VAULT_PATH,
    WORKER_POLL_INTERVAL_SECONDS,
    WORKER_HEARTBEAT_INTERVAL_SECONDS,
    JOB_REQUEUE_TIMEOUT_MINUTES,
)
from worker.transcriber import transcribe
from worker.summarizer import load_transcript, summarize, write_to_obsidian
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WORKER_ID = socket.gethostname()
POLL_INTERVAL = WORKER_POLL_INTERVAL_SECONDS
HEARTBEAT_INTERVAL = WORKER_HEARTBEAT_INTERVAL_SECONDS
REQUEUE_TIMEOUT_MINUTES = JOB_REQUEUE_TIMEOUT_MINUTES


def get_pending_job(db):
    """
    Find the next available job (read-only lookup, not a claim).
    """
    return db.query(Job).filter(Job.status == "pending").first()


def claim_job(db, job_id):
    """
    Atomically claim the job — only succeeds if it's still pending.
    Returns the claimed Job, or None if another worker got it first.
    """
    result = db.query(Job).filter(
        Job.id == job_id,
        Job.status == "pending"
    ).update({
        "status": "processing",
        "claimed_by": WORKER_ID,
        "claimed_at": datetime.now(),
        "heartbeat_at": datetime.now(),
        "attempts": Job.attempts + 1,
    })
    db.commit()

    if result == 0:
        return None

    return db.query(Job).filter(Job.id == job_id).first()


def complete_job(db, job):
    """
    Mark job as completed and remove the source audio file.
    """
    job.status = "completed"
    job.completed_at = datetime.now()
    db.commit()

    audio_path = UPLOAD_DIR / job.stored_filename
    try:
        audio_path.unlink(missing_ok=True)
        logger.info(f"Deleted source audio: {audio_path}")
    except OSError:
        logger.exception(f"Failed to delete source audio: {audio_path}")


def fail_job(db, job, error):
    """
    Mark job as failed and store error details.
    """
    job.status = "failed"
    job.error_message = str(error)
    db.commit()


def heartbeat_job(db, job):
    if HEARTBEAT_INTERVAL <= 0:
        return

    job.heartbeat_at = datetime.now()
    db.commit()


def requeue_stale_jobs(db, timeout_minutes: int):
    timeout = datetime.now() - timedelta(minutes=timeout_minutes)

    stale_jobs = (
        db.query(Job)
        .filter(
            Job.status == "processing",
            Job.heartbeat_at < timeout,
        )
        .all()
    )

    for stale_job in stale_jobs:
        stale_job.status = "queued"
        stale_job.claimed_by = None
        stale_job.claimed_at = None
        stale_job.heartbeat_at = None

    if stale_jobs:
        db.commit()

    return stale_jobs


def process_job(db, job):
    logger.info(f"Processing {job.stored_filename}")
    audio_path = UPLOAD_DIR / job.stored_filename
    base_name = job.stored_filename.rsplit(".", 1)[0]

    heartbeat_job(db, job)

    # === Whisper transcription ===
    transcribe_start = time.time()
    result = transcribe(str(audio_path))
    transcribe_duration = time.time() - transcribe_start
    heartbeat_job(db, job)

    transcript_path = TRANSCRIPTS_DIR / f"{base_name}.txt"
    transcript_path.write_text(result["text"])
    job.transcript_path = str(transcript_path)
    db.commit()
    heartbeat_job(db, job)

    logger.info(
        f"Transcription done in {transcribe_duration:.2f}s "
        f"({len(result['text'])} chars) -> {transcript_path}"
    )

    # === Ollama summarization ===
    summarize_start = time.time()
    transcript = load_transcript(job.transcript_path)
    summary = asyncio.run(summarize(transcript))
    summarize_duration = time.time() - summarize_start
    heartbeat_job(db, job)

    note_path = write_to_obsidian(job.stored_filename, summary, VAULT_PATH)
    job.summary_path = str(note_path)
    db.commit()
    heartbeat_job(db, job)

    logger.info(
        f"Summarization done in {summarize_duration:.2f}s "
        f"({len(summary)} chars) -> {note_path}"
    )

    # === Write to Obsidian vault ===
    logger.info(f"Wrote note to Obsidian vault: {note_path}")

    total_duration = transcribe_duration + summarize_duration
    logger.info(
        f"Job {job.id} total pipeline time: {total_duration:.2f}s "
        f"(transcribe {transcribe_duration:.2f}s, summarize {summarize_duration:.2f}s)"
    )


def worker_loop():
    logger.info(f"Worker started: {WORKER_ID}")

    while True:
        db = SessionLocal()
        job = None

        try:
            requeue_stale_jobs(db, timeout_minutes=REQUEUE_TIMEOUT_MINUTES)
            pending = get_pending_job(db)

            if not pending:
                logger.info("No jobs available")
                time.sleep(POLL_INTERVAL)
                continue

            logger.info(f"Claiming job {pending.id}")
            job = claim_job(db, pending.id)

            if job is None:
                logger.info(f"Lost claim race for job {pending.id}, retrying")
                continue

            process_job(db, job)
            complete_job(db, job)

            logger.info(f"Completed job {job.id}")

        except Exception as error:
            logger.exception("Worker failure")
            if job:
                fail_job(db, job, error)

        finally:
            db.close()


if __name__ == "__main__":
    worker_loop()