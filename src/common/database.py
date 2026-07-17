from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///jobs.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def get_db():
    """
    FastAPI dependency that provides a database session.
    Automatically closes the session after the request finishes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()