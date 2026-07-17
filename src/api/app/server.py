from fastapi import FastAPI, UploadFile, HTTPException, Depends
from sqlalchemy.orm import Session

import aiofiles
import logging
from datetime import datetime

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

@app.post(
    "/upload",
    response_model=UploadResponse,
    responses={500: {"description": "Something went wrong"}}
)
async def upload(
    file: UploadFile,
    db: Session = Depends(get_db)
):
    """
    Upload an MP3 file and create a transcription job.
    """

    timestamp = datetime.now().strftime(
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