"""Database infrastructure for the Food Ordering AI Agent."""

__all__ = ["SessionLocal", "engine", "get_db"]

def __getattr__(name: str):
    """Load connection infrastructure only when a DB export is requested."""
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from src.db import database

    return getattr(database, name)
