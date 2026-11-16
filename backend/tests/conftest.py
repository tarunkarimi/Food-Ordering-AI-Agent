import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def prevent_real_otp_delivery(monkeypatch):
    """Keep synthetic tests from sending email or SMS by default."""
    from src.api.routes import auth

    monkeypatch.setattr(
        auth,
        "deliver_verification_code",
        lambda **_kwargs: None,
    )
