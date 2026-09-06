"""Allow users to sign up with phone instead of email."""

from alembic import op
import sqlalchemy as sa


revision = "0005_optional_email"
down_revision = "0004_phone_length"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "email",
        existing_type=sa.String(length=320),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "email",
        existing_type=sa.String(length=320),
        nullable=False,
    )