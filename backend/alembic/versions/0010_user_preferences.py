"""Create user preferences table.

Revision ID: 0010_user_preferences
Revises: 0009_order_history
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_user_preferences"
down_revision = "0009_order_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "cuisine_preference",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "spice_level",
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column(
            "dietary_preference",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "meal_preference",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "notes",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    op.create_index(
        "ix_user_preferences_user_id",
        "user_preferences",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_preferences_user_id",
        table_name="user_preferences",
    )
    op.drop_table("user_preferences")
