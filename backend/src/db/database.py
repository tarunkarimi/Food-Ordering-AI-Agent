"""SQLAlchemy engine and session infrastructure.

The application uses the Supabase PostgreSQL database through SQLAlchemy.
The connection URL is supplied through ``DATABASE_URL`` and is never hard-coded.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.configs.config import config


def _normalize_database_url(url: str) -> str:
    """Normalize common PostgreSQL URL variants for SQLAlchemy + psycopg."""

    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]

    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]

    return url


DATABASE_URL = _normalize_database_url(config.DATABASE_URL)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Provide a database session for FastAPI dependencies."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()