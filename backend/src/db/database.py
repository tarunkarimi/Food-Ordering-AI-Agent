"""SQLAlchemy engine and session infrastructure.

The application uses the Supabase PostgreSQL database through SQLAlchemy.
The connection URL is supplied through ``DATABASE_URL`` and is never hard-coded.
"""

from collections.abc import Generator
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.configs.config import config
from src.db_test_safety import resolve_test_database_url


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]

    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]

    return url


if "pytest" in sys.modules:
    DATABASE_URL = resolve_test_database_url(
        test_database_url=os.environ.get("TEST_DATABASE_URL"),
        test_database_name=os.environ.get("TEST_DATABASE_NAME"),
        confirmation=os.environ.get("TEST_DATABASE_CONFIRMATION"),
        application_database_url=config.DATABASE_URL,
        ci_environment=os.environ.get("CI", "").casefold() == "true",
    )
else:
    DATABASE_URL = _normalize_database_url(config.DATABASE_URL)


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=config.DB_POOL_SIZE,
    max_overflow=config.DB_MAX_OVERFLOW,
    pool_timeout=config.DB_POOL_TIMEOUT_SECONDS,
    pool_recycle=config.DB_POOL_RECYCLE_SECONDS,
)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
