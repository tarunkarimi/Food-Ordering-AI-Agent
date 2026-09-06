from sqlalchemy import inspect

from src.db.database import engine
from src.db.models import User


def test_user_model_table_name():
    assert User.__tablename__ == "users"


def test_users_table_exists():
    inspector = inspect(engine)

    assert "users" in inspector.get_table_names()


def test_users_table_has_expected_columns():
    inspector = inspect(engine)

    columns = {
        column["name"]: column
        for column in inspector.get_columns("users")
    }

    assert {
        "id",
        "email",
        "password_hash",
        "is_active",
        "created_at",
        "updated_at",
    } <= columns.keys()


def test_users_email_is_unique():
    inspector = inspect(engine)

    unique_constraints = inspector.get_unique_constraints("users")
    unique_indexes = inspector.get_indexes("users")

    constraint_columns = [
        column
        for constraint in unique_constraints
        for column in constraint.get("column_names", [])
    ]

    index_columns = [
        column
        for index in unique_indexes
        if index.get("unique")
        for column in index.get("column_names", [])
    ]

    assert "email" in constraint_columns or "email" in index_columns