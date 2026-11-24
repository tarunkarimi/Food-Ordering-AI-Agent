import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.db_test_safety import DatabaseSafetyConfigurationError


@pytest.fixture(autouse=True)
def prevent_real_otp_delivery(monkeypatch):
    """Keep synthetic tests from sending email or SMS by default."""
    try:
        from src.api.routes import auth
    except DatabaseSafetyConfigurationError:
        # Database-independent unit tests need not configure a real test DB.
        # Database-backed modules still fail closed when they import the DB.
        return

    monkeypatch.setattr(
        auth,
        "deliver_verification_code",
        lambda **_kwargs: None,
    )
