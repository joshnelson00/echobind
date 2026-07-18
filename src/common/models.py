from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from common.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)

    # Original uploaded filename
    original_filename = Column(String, nullable=False)

    # Filename stored on disk
    stored_filename = Column(String, nullable=False)

    # pending | processing | completed | failed
    status = Column(String, nullable=False, default="pending")

    # Which worker claimed this job
    claimed_by = Column(String, nullable=True)

    # Last heartbeat from the worker
    heartbeat_at = Column(DateTime, nullable=True)

    attempts = Column(
        Integer,
        default=0,
        nullable=False
    )

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

    transcript_path = Column(String, nullable=True)

    summary_path = Column(String, nullable=True)

    error_message = Column(Text, nullable=True)