"""Fail-closed selection of explicitly designated test database targets."""

import re

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class DatabaseSafetyConfigurationError(RuntimeError):
    """Raised when a test-only database target is missing or unsafe."""


_TEST_DATABASE_NAME = re.compile(r"(?:^|[_-])(test|ci|e2e)(?:[_-]|$)", re.IGNORECASE)
_CI_DATABASE_NAME = re.compile(r"(?:^|[_-])ci(?:[_-]|$)", re.IGNORECASE)
_CONFIRMATION_PREFIX = "I_ACKNOWLEDGE_TEST_DATABASE:"


def resolve_test_database_url(
    *,
    test_database_url: str | None,
    test_database_name: str | None,
    confirmation: str | None,
    application_database_url: str | None,
    ci_environment: bool = False,
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

    try:
        parsed_url = make_url(test_database_url)
        application_url = make_url(application_database_url)
    except (ArgumentError, TypeError, ValueError) as exc:
        raise DatabaseSafetyConfigurationError(
            "A configured database URL is not valid."
        ) from exc

    if (
        parsed_url.get_backend_name() not in {"postgres", "postgresql"}
        or not parsed_url.host
        or not parsed_url.database
        or parsed_url.database != test_database_name
    ):
        raise DatabaseSafetyConfigurationError(
            "TEST_DATABASE_URL must identify the PostgreSQL database named by TEST_DATABASE_NAME."
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
        same_database = (
            parsed_url.host.casefold(),
            parsed_url.port or 5432,
            parsed_url.database,
        ) == (
            application_url.host.casefold(),
            application_url.port or 5432,
            application_url.database,
        )
    except ValueError as exc:
        raise DatabaseSafetyConfigurationError(
            "A configured database URL is not valid."
        ) from exc

    if same_database and not (ci_environment and _CI_DATABASE_NAME.search(test_database_name)):
        raise DatabaseSafetyConfigurationError(
            "The designated test database must be separate from the application database."
        )

    return parsed_url.set(drivername="postgresql+psycopg").render_as_string(
        hide_password=False
    )
