"""Allow full E.164 phone number length."""

from alembic import op
import sqlalchemy as sa


revision = "0004_phone_length"
down_revision = "0003_phone_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "phone",
        existing_type=sa.String(length=15),
        type_=sa.String(length=16),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "phone",
        existing_type=sa.String(length=16),
        type_=sa.String(length=15),
        existing_nullable=True,
    )