"""Add phone and verification fields to users."""

from alembic import op
import sqlalchemy as sa


revision = "0003_phone_verification"
down_revision = "0002_create_users_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "phone",
            sa.String(length=15),
            nullable=True,
        ),
    )

    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    op.add_column(
        "users",
        sa.Column(
            "phone_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_users_phone",
        "users",
        ["phone"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_phone", table_name="users")
    op.drop_column("users", "phone_verified")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "phone")