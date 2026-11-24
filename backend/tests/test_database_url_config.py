from sqlalchemy.engine import make_url

from src.db.connection_url import normalize_database_url


def test_supabase_postgres_url_requires_ssl_and_psycopg():
    normalized = make_url(normalize_database_url(
        "postgresql://test_user:test_password@aws-0.pooler.supabase.com:5432/postgres"
    ))

    assert normalized.drivername == "postgresql+psycopg"
    assert normalized.query["sslmode"] == "require"


def test_supabase_url_preserves_stricter_ssl_mode():
    normalized = make_url(normalize_database_url(
        "postgres://test_user:test_password@db.example.supabase.co/postgres?sslmode=verify-full"
    ))

    assert normalized.query["sslmode"] == "verify-full"


def test_local_postgres_url_does_not_require_tls():
    normalized = make_url(normalize_database_url(
        "postgresql://test_user:test_password@localhost:5432/food_ordering_ci"
    ))

    assert normalized.drivername == "postgresql+psycopg"
    assert "sslmode" not in normalized.query


def test_supabase_url_does_not_allow_disabled_tls():
    normalized = make_url(normalize_database_url(
        "postgresql://test_user:test_password@aws-0.pooler.supabase.com/postgres?sslmode=disable"
    ))

    assert normalized.query["sslmode"] == "require"
