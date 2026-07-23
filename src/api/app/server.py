from fastapi import FastAPI, UploadFile, HTTPException, Depends, Form
from sqlalchemy.orm import Session

import aiofiles
import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from common.database import engine, get_db
from common.models import Base, Job
from api.app.crud import create_job
from common.schemas import UploadResponse, JobResponse
from api.app.config import UPLOAD_DIR


# Create database tables
Base.metadata.create_all(bind=engine)


logger = logging.getLogger("uvicorn.error")

app = FastAPI()

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a"}
ALLOWED_CONTENT_TYPES = {
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4"
}

LOCAL_TZ = ZoneInfo("America/Phoenix")

UPLOAD_GRACE = timedelta(minutes=15)
CLASS_SCHEDULE = [
    {
        "name": "STG-451",
        "weekdays": {0},
        "start": time(15, 0),
        "end": time(16, 45),
        "term_start": date(2026, 9, 8),
        "term_end": date(2026, 12, 20),
    },
    {
        "name": "ITT-305",
        "weekdays": {1, 3},
        "start": time(11, 0),
        "end": time(12, 45),
        "term_start": date(2026, 9, 8),
        "term_end": date(2026, 12, 20),
    },
    {
        "name": "STG-390HN",
        "weekdays": {1, 3},
        "start": time(9, 0),
        "end": time(10, 45),
        "term_start": date(2026, 9, 8),
        "term_end": date(2026, 12, 20),
    },
    {
        "name": "CST-435HN",
        "weekdays": {2, 4},
        "start": time(13, 0),
        "end": time(14, 45),
        "term_start": date(2026, 9, 8),
        "term_end": date(2026, 12, 20),
    },
]

def resolve_class_name(dt: datetime, schedule: list[dict] = CLASS_SCHEDULE) -> str:
    """
    Matches an upload timestamp (expected to be timezone-aware, in LOCAL_TZ)
    against a fixed weekly schedule to infer which class it belongs to.
    Also checks the entry's term_start/term_end so a slot doesn't keep
    matching after the semester ends. Falls back to "unclassified" if
    nothing matches, rather than raising — an upload should never be lost
    just because it doesn't fit the schedule.
    """
    upload_date = dt.date()
    weekday = dt.weekday()
    upload_time = dt.time()

    candidates = []
    for entry in schedule:
        if not (entry["term_start"] <= upload_date <= entry["term_end"]):
            continue
        if weekday not in entry["weekdays"]:
            continue

        window_start = entry["start"]
        window_end_dt = datetime.combine(upload_date, entry["end"]) + UPLOAD_GRACE
        window_end = window_end_dt.time() if window_end_dt.date() == upload_date else time(23, 59, 59)

        if window_start <= upload_time <= window_end:
            distance = abs(
                datetime.combine(upload_date, upload_time) - datetime.combine(upload_date, window_start)
            )
            candidates.append((distance, entry["name"]))

    if not candidates:
        return "unclassified"

    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]


@app.post(
    "/upload",
    response_model=UploadResponse,
    responses={500: {"description": "Something went wrong"}}
)
async def upload(
    file: UploadFile,
    class_name: str | None = Form(None), 
    db: Session = Depends(get_db)
):
    """
    Upload an MP3 file and create a transcription job.
    """

    # use LOCAL_TZ so filenames use the configured local timezone
    timestamp = datetime.now(LOCAL_TZ).strftime(
        "%Y%m%d_%H%M%S"
    )

    original_filename = file.filename

    extension = "." + original_filename.split(".")[-1].lower()

    # Perform file extension and content checks
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed types: {ALLOWED_EXTENSIONS}"
        )

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Invalid audio file"
        )

    stored_filename = (
        f"{timestamp}_{original_filename}"
    )

    filepath = UPLOAD_DIR / stored_filename

    try:
        async with aiofiles.open(filepath, "wb") as f:

            while chunk := await file.read(1024 * 1024):
                await f.write(chunk)


        job = create_job(
            db=db,
            original_filename=original_filename,
            stored_filename=stored_filename
        )


    except Exception:
        logger.exception("Upload failed")

        raise HTTPException(
            status_code=500,
            detail="Something went wrong"
        )


    return UploadResponse(
        job_id=job.id,
        filename=job.original_filename,
        status=job.status
    )

@app.get(
    "/jobs/{job_id}",
    response_model=JobResponse
)
def get_job(
    job_id: int,
    db: Session = Depends(get_db)
):

    job = db.query(Job).filter(
        Job.id == job_id
    ).first()

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )

    return job

@app.get(
    "/jobs",
    response_model=list[JobResponse]
)
def get_jobs(
    db: Session = Depends(get_db)
):

    jobs = db.query(Job).all()

    return jobs