from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class JobBase(BaseModel):
    original_filename: str


class JobCreate(JobBase):
    stored_filename: str


class JobResponse(BaseModel):
    id: int

    original_filename: str
    stored_filename: str

    status: str

    claimed_by: Optional[str] = None

    created_at: datetime

    claimed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    transcript_path: Optional[str] = None
    summary_path: Optional[str] = None

    error_message: Optional[str] = None

    model_config = ConfigDict(
        from_attributes=True
    )


class JobClaimResponse(BaseModel):
    id: int
    filename: str
    status: str


class UploadResponse(BaseModel):
    job_id: int
    filename: str
    status: str


class CompleteJobRequest(BaseModel):
    transcript_path: str
    summary_path: str


class FailJobRequest(BaseModel):
    error_message: str