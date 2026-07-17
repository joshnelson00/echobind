from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from common.models import Job


def create_job(
    db: Session,
    original_filename: str,
    stored_filename: str
):
    """
    Creates a new transcription job.
    """

    job = Job(
        original_filename=original_filename,
        stored_filename=stored_filename,
        status="queued"
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    return job


def get_job(
    db: Session,
    job_id: int
):
    """
    Retrieve a job by ID.
    """

    return (
        db.query(Job)
        .filter(Job.id == job_id)
        .first()
    )


def get_queued_jobs(
    db: Session
):
    """
    Returns all queued jobs.
    """

    return (
        db.query(Job)
        .filter(Job.status == "queued")
        .order_by(Job.created_at)
        .all()
    )


def claim_next_job(
    db: Session,
    worker_name: str
):
    """
    Atomically claims the oldest queued job.
    """

    job = (
        db.query(Job)
        .filter(Job.status == "queued")
        .order_by(Job.created_at)
        .first()
    )

    if not job:
        return None

    job.status = "processing"
    job.claimed_by = worker_name
    job.claimed_at = datetime.now()
    job.heartbeat_at = datetime.now()

    db.commit()
    db.refresh(job)

    return job


def update_heartbeat(
    db: Session,
    job_id: int
):
    """
    Worker calls this periodically while processing.
    """

    job = get_job(db, job_id)

    if not job:
        return None

    job.heartbeat_at = datetime.now()

    db.commit()
    db.refresh(job)

    return job


def complete_job(
    db: Session,
    job_id: int,
    transcript_path: str,
    summary_path: str
):
    """
    Marks a job as successfully completed.
    """

    job = get_job(db, job_id)

    if not job:
        return None

    job.status = "completed"
    job.transcript_path = transcript_path
    job.summary_path = summary_path
    job.completed_at = datetime.now()

    db.commit()
    db.refresh(job)

    return job


def fail_job(
    db: Session,
    job_id: int,
    error_message: str
):
    """
    Marks a job as failed.
    """

    job = get_job(db, job_id)

    if not job:
        return None

    job.status = "failed"
    job.error_message = error_message

    db.commit()
    db.refresh(job)

    return job


def requeue_stale_jobs(
    db: Session,
    timeout_minutes: int = 30
):
    """
    Recovers jobs from workers that died.
    """

    timeout = datetime.now() - timedelta(
        minutes=timeout_minutes
    )

    stale_jobs = (
        db.query(Job)
        .filter(
            Job.status == "processing",
            Job.heartbeat_at < timeout
        )
        .all()
    )

    for job in stale_jobs:
        job.status = "queued"
        job.claimed_by = None
        job.claimed_at = None
        job.heartbeat_at = None

    db.commit()

    return stale_jobs