import pytest
from sqlalchemy.engine import make_url

from src.db_test_safety import (
    DatabaseSafetyConfigurationError,
    resolve_test_database_url,
    validate_ci_database_url,
)


def _resolve(
    *,
    url="postgres://test_user:synthetic-secret@127.0.0.1:55432/food_ordering_test",
    name="food_ordering_test",
    confirmation="I_ACKNOWLEDGE_TEST_DATABASE:food_ordering_test",
    application_url="postgresql://app_user:app-secret@app.example.test:5432/food_ordering",
):
    return resolve_test_database_url(
        test_database_url=url,
        test_database_name=name,
        confirmation=confirmation,
        application_database_url=application_url,
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


def test_never_falls_back_to_application_database_when_test_url_is_missing():
    with pytest.raises(DatabaseSafetyConfigurationError, match="Test database URL"):
        _resolve(url=None)


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


def test_rejects_test_database_on_same_application_host_even_with_different_name():
    with pytest.raises(DatabaseSafetyConfigurationError, match="separate host"):
        _resolve(
            url="postgresql://test_user:secret@127.0.0.1:5432/food_ordering_test",
            application_url="postgresql://app_user:secret@127.0.0.1:5432/food_ordering_prod",
        )


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://test_user:synthetic@localhost:55432/food_ordering_test",
        "postgresql://test_user:synthetic@127.0.0.1:55432/food_ordering_test",
        "postgresql://test_user:synthetic@[::1]:55432/food_ordering_test",
    ],
)
def test_allows_explicit_localhost_and_loopback_ip_targets(url):
    target = make_url(_resolve(url=url))
    assert target.get_backend_name() == "postgresql"
    assert target.host in {"localhost", "127.0.0.1", "::1"}
    assert target.port == 55432
    assert target.database == "food_ordering_test"


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://test_user:synthetic@db.example.test:55432/food_ordering_test",
        "postgresql://test_user:synthetic@aws-0.pooler.supabase.com:55432/food_ordering_test",
        "postgresql://test_user:synthetic@198.51.100.23:55432/food_ordering_test",
        "postgresql://test_user:synthetic@localhost.example.test:55432/food_ordering_test",
    ],
)
def test_rejects_remote_hostname_supabase_and_ip_targets(url):
    with pytest.raises(DatabaseSafetyConfigurationError, match="localhost or a loopback IP"):
        _resolve(url=url)


def test_remote_hostname_is_rejected_without_dns_resolution(monkeypatch):
    import socket

    def unexpected_dns_lookup(*_args, **_kwargs):
        raise AssertionError("Database safety must not perform DNS lookups.")

    monkeypatch.setattr(socket, "getaddrinfo", unexpected_dns_lookup)
    with pytest.raises(DatabaseSafetyConfigurationError, match="localhost or a loopback IP"):
        _resolve(url="postgresql://test_user:synthetic@loopback-alias.example.test/food_ordering_test")


def test_rejects_malformed_port_without_echoing_url_or_credentials():
    malformed = "postgresql://synthetic-user:synthetic-password@127.0.0.1:not-a-port/food_ordering_test"
    with pytest.raises(DatabaseSafetyConfigurationError, match="not valid") as raised:
        _resolve(url=malformed)
    message = str(raised.value)
    if malformed in message or "synthetic-password" in message or "synthetic-user" in message:
        pytest.fail("Malformed database URL diagnostics exposed sensitive URL data.")


@pytest.mark.parametrize("name", ["food_ordering_prod_test", "food_ordering_live_ci"])
def test_rejects_production_or_live_database_names(name):
    with pytest.raises(DatabaseSafetyConfigurationError, match="Production or live"):
        _resolve(
            url=f"postgresql://test_user:secret@127.0.0.1:55432/{name}",
            name=name,
            confirmation=f"I_ACKNOWLEDGE_TEST_DATABASE:{name}",
        )


def test_allows_the_local_ci_service_when_application_url_is_only_a_placeholder():
    ci_url = "postgresql://ci_user:ci-secret@127.0.0.1:5432/food_ordering_ci"

    target = make_url(_resolve(
        url=ci_url,
        name="food_ordering_ci",
        confirmation="I_ACKNOWLEDGE_TEST_DATABASE:food_ordering_ci",
    ))
    assert target.drivername == "postgresql+psycopg"
    assert target.host == "127.0.0.1"
    assert target.port == 5432
    assert target.database == "food_ordering_ci"


def test_ci_name_does_not_allow_reusing_the_application_database():
    with pytest.raises(DatabaseSafetyConfigurationError, match="localhost or a loopback IP"):
        _resolve(
            url="postgresql://ci_user:secret@db.example.test/food_ordering_ci",
            name="food_ordering_ci",
            confirmation="I_ACKNOWLEDGE_TEST_DATABASE:food_ordering_ci",
        )


def test_ci_name_cannot_bypass_same_application_host_protection():
    ci_url = "postgresql://ci_user:ci-secret@127.0.0.1:5432/food_ordering_ci"
    with pytest.raises(DatabaseSafetyConfigurationError, match="separate host"):
        _resolve(
            url=ci_url,
            name="food_ordering_ci",
            confirmation="I_ACKNOWLEDGE_TEST_DATABASE:food_ordering_ci",
            application_url=ci_url,
        )


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres:synthetic@localhost:5432/food_ordering_ci",
        "postgresql+psycopg://postgres:synthetic@localhost:5432/food_ordering_ci",
    ],
)
def test_ci_identity_url_accepts_only_declared_local_postgres_service(url):
    target = validate_ci_database_url(url)
    assert target.host == "localhost"
    assert target.port == 5432
    assert target.database == "food_ordering_ci"
    assert target.username == "postgres"


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://ci_user:synthetic@postgres:5432/food_ordering_ci",
        "postgresql://ci_user:synthetic@db.example.test:5432/food_ordering_ci",
        "postgresql://ci_user:synthetic@aws-0.pooler.supabase.com:5432/food_ordering_ci",
        "postgresql://ci_user:synthetic@198.51.100.8:5432/food_ordering_ci",
        "postgresql://ci_user:synthetic@localhost:55432/food_ordering_ci",
        "postgresql://ci_user:synthetic@localhost:5432/food_ordering_test",
    ],
)
def test_ci_identity_url_rejects_unapproved_hosts_or_service_configuration(url):
    with pytest.raises(DatabaseSafetyConfigurationError):
        validate_ci_database_url(url)


def test_ci_identity_url_errors_do_not_echo_credentials_or_url():
    url = "postgresql://synthetic-user:synthetic-password@remote.example.test:5432/food_ordering_ci"
    with pytest.raises(DatabaseSafetyConfigurationError) as raised:
        validate_ci_database_url(url)
    message = str(raised.value)
    if url in message or "synthetic-password" in message or "synthetic-user" in message:
        pytest.fail("CI database diagnostics exposed sensitive URL data.")


def test_invalid_url_error_does_not_echo_credentials():
    secret = "synthetic-never-log-this"

    with pytest.raises(DatabaseSafetyConfigurationError) as exc_info:
        _resolve(url=f"not-a-database-url://user:{secret}@host/food_ordering_test")

    message = str(exc_info.value)
    if secret in message or "user" in message:
        pytest.fail("Invalid database URL diagnostics exposed credential data.")


def test_normalizes_postgres_scheme_without_opening_a_connection():
    target = make_url(_resolve())
    assert target.drivername == "postgresql+psycopg"
    assert target.host == "127.0.0.1"
    assert target.port == 55432
    assert target.database == "food_ordering_test"
