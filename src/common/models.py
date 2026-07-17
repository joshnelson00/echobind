from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from common.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)

    # Original uploaded filename
    original_filename = Column(String, nullable=False)

    # Filename stored on disk
    stored_filename = Column(String, nullable=False)

    # queued | processing | completed | failed
    status = Column(String, nullable=False, default="queued")

    # Which worker claimed this job
    claimed_by = Column(String, nullable=True)

    # Last heartbeat from the worker
    heartbeat_at = Column(DateTime, nullable=True)

    # Processing timestamps
    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )

    claimed_at = Column(
        DateTime,
        nullable=True
    )

    completed_at = Column(
        DateTime,
        nullable=True
    )

    # Output files
    transcript_path = Column(String, nullable=True)

    summary_path = Column(String, nullable=True)

    # Optional error message if processing fails
    error_message = Column(Text, nullable=True)