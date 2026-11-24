"""Fail-closed selection of explicitly designated test database targets."""

import ipaddress
import re

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class DatabaseSafetyConfigurationError(RuntimeError):
    """Raised when a test-only database target is missing or unsafe."""


_TEST_DATABASE_NAME = re.compile(r"(?:^|[_-])(test|ci|e2e)(?:[_-]|$)", re.IGNORECASE)
_PRODUCTION_DATABASE_NAME = re.compile(r"(?:^|[_-])(prod|production|live)(?:[_-]|$)", re.IGNORECASE)
_CONFIRMATION_PREFIX = "I_ACKNOWLEDGE_TEST_DATABASE:"


def resolve_test_database_url(
    *,
    test_database_url: str | None,
    test_database_name: str | None,
    confirmation: str | None,
    application_database_url: str | None,
) -> str:
    """Validate explicit test-target settings without opening a connection.

    Credentials are required by SQLAlchemy but are never included in errors.
    The returned URL is only suitable for an explicitly opted-in test or
    provisioning operation; callers must not fall back to ``DATABASE_URL``.
    """

    if not test_database_url or not test_database_name or not application_database_url:
        raise DatabaseSafetyConfigurationError(
            "Test database URL, name, and application database configuration are required."
        )

    expected_confirmation = f"{_CONFIRMATION_PREFIX}{test_database_name}"
    if confirmation != expected_confirmation:
        raise DatabaseSafetyConfigurationError(
            "Test database confirmation is missing or does not match TEST_DATABASE_NAME."
        )

    if not _TEST_DATABASE_NAME.search(test_database_name):
        raise DatabaseSafetyConfigurationError(
            "TEST_DATABASE_NAME must contain a test, ci, or e2e name segment."
        )
    if _PRODUCTION_DATABASE_NAME.search(test_database_name):
        raise DatabaseSafetyConfigurationError(
            "Production or live database names cannot be used for tests."
        )

    try:
        parsed_url = make_url(test_database_url)
        application_url = make_url(application_database_url)
    except (ArgumentError, TypeError, ValueError):
        raise DatabaseSafetyConfigurationError(
            "A configured database URL is not valid."
        ) from None

    if (
        parsed_url.get_backend_name() not in {"postgres", "postgresql"}
        or not parsed_url.host
        or not parsed_url.database
        or parsed_url.database != test_database_name
    ):
        raise DatabaseSafetyConfigurationError(
            "TEST_DATABASE_URL must identify the PostgreSQL database named by TEST_DATABASE_NAME."
        )

    if not _is_loopback_host(parsed_url.host):
        raise DatabaseSafetyConfigurationError(
            "TEST_DATABASE_URL must use localhost or a loopback IP address."
        )

    if (
        application_url.get_backend_name() not in {"postgres", "postgresql"}
        or not application_url.host
        or not application_url.database
    ):
        raise DatabaseSafetyConfigurationError(
            "DATABASE_URL must identify the configured application database."
        )

    try:
        test_port = parsed_url.port
        application_port = application_url.port
    except ValueError:
        raise DatabaseSafetyConfigurationError(
            "A configured database URL is not valid."
        ) from None

    if test_port is not None and not 1 <= test_port <= 65535:
        raise DatabaseSafetyConfigurationError(
            "A configured database URL is not valid."
        )

    if application_port is not None and not 1 <= application_port <= 65535:
        raise DatabaseSafetyConfigurationError(
            "A configured database URL is not valid."
        )

    test_host = _host_identity(parsed_url.host)
    application_host = _host_identity(application_url.host)
    try:
        same_database = (
            test_host,
            test_port or 5432,
            parsed_url.database,
        ) == (
            application_host,
            application_port or 5432,
            application_url.database,
        )
    except ValueError:
        raise DatabaseSafetyConfigurationError(
            "A configured database URL is not valid."
        ) from None

    same_host = test_host == application_host
    if same_database or same_host:
        raise DatabaseSafetyConfigurationError(
            "The designated test database must use a separate host from the application database."
        )

    return parsed_url.set(drivername="postgresql+psycopg").render_as_string(
        hide_password=False
    )


def _is_loopback_host(host: str) -> bool:
    """Accept explicit local names and loopback IP literals without DNS lookup."""
    normalized = host.casefold()
    if normalized == "localhost":
        return True
    # Interface-scoped IPv6 literals are unnecessary for a loopback target and
    # add parsing ambiguity, so only canonical unscoped IP literals are allowed.
    if "%" in normalized:
        return False
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _host_identity(host: str) -> str:
    """Treat IPv4/IPv6 loopback literals and localhost as the same local host."""
    return "<loopback>" if _is_loopback_host(host) else host.casefold()


def validate_ci_database_url(database_url: str):
    """Validate the one PostgreSQL target allowed by the GitHub Actions jobs."""
    try:
        parsed = make_url(database_url)
        port = parsed.port
    except (ArgumentError, TypeError, ValueError):
        raise DatabaseSafetyConfigurationError(
            "The designated CI database URL is not valid."
        ) from None

    if (
        parsed.get_backend_name() not in {"postgres", "postgresql"}
        or (parsed.host or "").casefold() != "localhost"
        or port != 5432
        or parsed.database != "food_ordering_ci"
        or parsed.username != "postgres"
    ):
        raise DatabaseSafetyConfigurationError(
            "The designated CI database URL must identify the local ephemeral PostgreSQL service."
        )
    return parsed
