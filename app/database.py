from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

engine = create_engine(settings.database_url)

SessionLocal = sessionmaker(  # pylint: disable=invalid-name
    autocommit=False, autoflush=False, bind=engine,
)

Base = declarative_base()


def get_db():
    """
    FastAPI dependency that provides a database session.

    The session is automatically closed when the request finishes,
    even if an error occurs.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
