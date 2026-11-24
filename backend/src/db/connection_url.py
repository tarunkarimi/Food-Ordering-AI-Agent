"""Database URL normalization for the backend's PostgreSQL driver."""

from sqlalchemy.engine import make_url


_SUPABASE_HOST_SUFFIXES = (".supabase.com", ".supabase.co")
_SECURE_SSL_MODES = {"require", "verify-ca", "verify-full"}


def normalize_database_url(url: str) -> str:
    """Select psycopg and require TLS for hosted Supabase PostgreSQL URLs."""
    parsed = make_url(url)
    if parsed.drivername in {"postgres", "postgresql"}:
        parsed = parsed.set(drivername="postgresql+psycopg")

    host = (parsed.host or "").casefold()
    if host.endswith(_SUPABASE_HOST_SUFFIXES):
        sslmode = str(parsed.query.get("sslmode", "")).casefold()
        if sslmode not in _SECURE_SSL_MODES:
            parsed = parsed.update_query_dict({"sslmode": "require"})

    return parsed.render_as_string(hide_password=False)
