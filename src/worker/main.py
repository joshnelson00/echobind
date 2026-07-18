import time
import logging
import socket
import json
from datetime import datetime

from common.database import SessionLocal
from common.models import Job
from api.app.config import UPLOAD_DIR, TRANSCRIPTS_DIR
from worker.transcriber import transcribe


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WORKER_ID = socket.gethostname()
POLL_INTERVAL = 5

def get_pending_job(db):
    """
    Find the next available job (read-only lookup, not a claim).
    """
    return db.query(Job).filter(Job.status == "pending").first()


def claim_job(db, job_id):
    """
    Atomically claim a job — only succeeds if it's still pending.
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
        return None  # another worker claimed it first 

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


def process_job(db, job):
    """
    audio -> whisper -> transcript + timestamp/dead-space analysis
    (Ollama summarization step comes later)
    """
    logger.info(f"Processing {job.stored_filename}")
 
    audio_path = UPLOAD_DIR / job.stored_filename
 
    result = transcribe(str(audio_path))
 
    base_name = job.stored_filename.rsplit(".", 1)[0]
 
    transcript_path = TRANSCRIPTS_DIR / f"{base_name}.txt"
    transcript_path.write_text(result["text"])
 
    job.transcript_path = str(transcript_path)
    db.commit()

def worker_loop():
    logger.info(f"Worker started: {WORKER_ID}")

    while True:
        db = SessionLocal()
        job = None

        try:
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