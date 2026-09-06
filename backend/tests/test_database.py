from sqlalchemy import text

from src.db.database import DATABASE_URL, engine


def test_database_url_is_configured():
    assert DATABASE_URL
    assert DATABASE_URL.startswith("postgresql+psycopg://")


def test_database_engine_can_connect():
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1