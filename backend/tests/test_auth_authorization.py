from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.db.database import SessionLocal
from src.db.models import User, UserSession
from src.main import app


client = TestClient(app)


def unique_email() -> str:
    return f"ownership-{uuid4().hex}@example.com"


def signup_and_verify(email: str, password: str) -> int:
    response = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": password,
        },
    )

    assert response.status_code == 201

    user_id = response.json()["id"]

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.email_verified = True
        db.commit()

    return user_id


def login(email: str, password: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )

    assert response.status_code == 200
    return response.json()["access_token"]


def test_authenticated_user_can_list_only_own_sessions():
    password = "StrongPassword123!"

    user_a = unique_email()
    user_b = unique_email()

    user_a_id = signup_and_verify(user_a, password)
    user_b_id = signup_and_verify(user_b, password)

    token_a = login(user_a, password)
    login(user_a, password)
    login(user_b, password)

    response = client.get(
        "/api/auth/sessions",
        headers={"Authorization": f"Bearer {token_a}"},
    )

    assert response.status_code == 200

    sessions = response.json()

    assert len(sessions) == 2
    assert sum(session["is_current"] for session in sessions) == 1

    session_ids = {session["id"] for session in sessions}

    with SessionLocal() as db:
        user_a_sessions = set(
            db.scalars(
                select(UserSession.id).where(
                    UserSession.user_id == user_a_id
                )
            )
        )

        user_b_sessions = set(
            db.scalars(
                select(UserSession.id).where(
                    UserSession.user_id == user_b_id
                )
            )
        )

    assert session_ids == user_a_sessions
    assert session_ids.isdisjoint(user_b_sessions)


def test_unauthenticated_session_list_is_rejected():
    response = client.get("/api/auth/sessions")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required."


def test_user_can_revoke_own_other_session():
    password = "StrongPassword123!"
    email = unique_email()

    signup_and_verify(email, password)

    first_token = login(email, password)
    second_token = login(email, password)

    response = client.get(
        "/api/auth/sessions",
        headers={"Authorization": f"Bearer {first_token}"},
    )

    assert response.status_code == 200

    sessions = response.json()
    other_session = next(
        session
        for session in sessions
        if session["is_current"] is False
    )

    revoke_response = client.delete(
        f"/api/auth/sessions/{other_session['id']}",
        headers={"Authorization": f"Bearer {first_token}"},
    )

    assert revoke_response.status_code == 200
    assert revoke_response.json() == {
        "message": "Session revoked successfully."
    }

    second_me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {second_token}"},
    )

    assert second_me.status_code == 401
    assert second_me.json()["detail"] == (
        "Authenticated session has been revoked."
    )


def test_user_cannot_revoke_another_users_session():
    password = "StrongPassword123!"

    user_a = unique_email()
    user_b = unique_email()

    signup_and_verify(user_a, password)
    signup_and_verify(user_b, password)

    token_a = login(user_a, password)
    token_b = login(user_b, password)

    user_b_sessions_response = client.get(
        "/api/auth/sessions",
        headers={"Authorization": f"Bearer {token_b}"},
    )

    assert user_b_sessions_response.status_code == 200

    user_b_session_id = user_b_sessions_response.json()[0]["id"]

    response = client.delete(
        f"/api/auth/sessions/{user_b_session_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found."

    verify_response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token_b}"},
    )

    assert verify_response.status_code == 200


def test_revoke_nonexistent_session_returns_not_found():
    password = "StrongPassword123!"
    email = unique_email()

    signup_and_verify(email, password)
    token = login(email, password)

    response = client.delete(
        f"/api/auth/sessions/{uuid4().hex}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found."


def test_revoked_session_remains_visible_but_marked_revoked():
    password = "StrongPassword123!"
    email = unique_email()

    signup_and_verify(email, password)
    token = login(email, password)

    sessions_response = client.get(
        "/api/auth/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert sessions_response.status_code == 200
    session_id = sessions_response.json()[0]["id"]

    with SessionLocal() as db:
        session = db.get(UserSession, session_id)
        assert session is not None
        assert session.revoked_at is None

    revoke_response = client.delete(
        f"/api/auth/sessions/{session_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert revoke_response.status_code == 200

    # The revoked token can no longer authenticate, so use the
    # database to verify the ownership and lifecycle state.
    with SessionLocal() as db:
        session = db.get(UserSession, session_id)

        assert session is not None
        assert session.revoked_at is not None
        assert session.revoked_at <= datetime.now(timezone.utc)
