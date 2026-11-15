import pytest

from src.db_test_safety import (
    DatabaseSafetyConfigurationError,
    resolve_test_database_url,
)


def _resolve(
    *,
    url="postgres://test_user:synthetic-secret@127.0.0.1:55432/food_ordering_test",
    name="food_ordering_test",
    confirmation="I_ACKNOWLEDGE_TEST_DATABASE:food_ordering_test",
    application_url="postgresql://app_user:app-secret@127.0.0.1:5432/food_ordering",
    ci_environment=False,
):
    return resolve_test_database_url(
        test_database_url=url,
        test_database_name=name,
        confirmation=confirmation,
        application_database_url=application_url,
        ci_environment=ci_environment,
    )


@pytest.mark.parametrize(
    ("url", "name", "confirmation"),
    [
        (None, "food_ordering_test", "I_ACKNOWLEDGE_TEST_DATABASE:food_ordering_test"),
        ("postgresql://u:p@localhost/food_ordering_test", None, "I_ACKNOWLEDGE_TEST_DATABASE:food_ordering_test"),
    ],
)
def test_requires_explicit_test_url_and_database_name(url, name, confirmation):
    with pytest.raises(DatabaseSafetyConfigurationError):
        _resolve(url=url, name=name, confirmation=confirmation)


def test_requires_matching_confirmation():
    with pytest.raises(DatabaseSafetyConfigurationError, match="confirmation"):
        _resolve(confirmation="I_ACKNOWLEDGE_TEST_DATABASE:other_test")


def test_rejects_database_name_without_test_ci_or_e2e_segment():
    with pytest.raises(DatabaseSafetyConfigurationError, match="name segment"):
        _resolve(
            url="postgresql://u:p@localhost/food_ordering",
            name="food_ordering",
            confirmation="I_ACKNOWLEDGE_TEST_DATABASE:food_ordering",
        )


def test_rejects_url_whose_database_does_not_match_designated_name():
    with pytest.raises(DatabaseSafetyConfigurationError, match="identify the PostgreSQL database"):
        _resolve(url="postgresql://u:p@localhost/other_test")


def test_rejects_non_postgresql_database_urls():
    with pytest.raises(DatabaseSafetyConfigurationError, match="identify the PostgreSQL database"):
        _resolve(url="sqlite:///food_ordering_test")


def test_rejects_target_that_is_the_application_database():
    app_url = "postgresql://app_user:app-secret@127.0.0.1:5432/food_ordering_test"

    with pytest.raises(DatabaseSafetyConfigurationError, match="separate"):
        _resolve(
            url=app_url,
            name="food_ordering_test",
            confirmation="I_ACKNOWLEDGE_TEST_DATABASE:food_ordering_test",
            application_url=app_url,
        )


def test_allows_the_explicit_ci_service_database():
    ci_url = "postgresql://ci_user:ci-secret@127.0.0.1:5432/food_ordering_ci"

    assert _resolve(
        url=ci_url,
        name="food_ordering_ci",
        confirmation="I_ACKNOWLEDGE_TEST_DATABASE:food_ordering_ci",
        application_url=ci_url,
        ci_environment=True,
    ) == ci_url.replace("postgresql://", "postgresql+psycopg://", 1)


def test_invalid_url_error_does_not_echo_credentials():
    secret = "synthetic-never-log-this"

    with pytest.raises(DatabaseSafetyConfigurationError) as exc_info:
        _resolve(url=f"not-a-database-url://user:{secret}@host/food_ordering_test")

    assert secret not in str(exc_info.value)
    assert "user" not in str(exc_info.value)


def test_normalizes_postgres_scheme_without_opening_a_connection():
    target = _resolve()

    assert target == (
        "postgresql+psycopg://test_user:synthetic-secret@"
        "127.0.0.1:55432/food_ordering_test"
    )
