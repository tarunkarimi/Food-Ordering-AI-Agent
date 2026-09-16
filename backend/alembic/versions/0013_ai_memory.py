"""add advanced AI memory tables

Revision ID: 0013_ai_memory
Revises: 0012_ordering_intelligence
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_ai_memory"
down_revision = "0012_ordering_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_ai_memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("memory_type", sa.String(length=32), nullable=False),
        sa.Column("memory_key", sa.String(length=128), nullable=False),
        sa.Column("memory_value", sa.String(length=255), nullable=False),
        sa.Column("polarity", sa.String(length=16), nullable=False),
        sa.Column(
            "confidence",
            sa.Numeric(4, 3),
            nullable=False,
            server_default="0.800",
        ),
        sa.Column(
            "mention_count",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "memory_type",
            "memory_key",
            "memory_value",
            "polarity",
            name="uq_user_ai_memory",
        ),
    )

    op.create_index(
        "ix_user_ai_memories_user_id",
        "user_ai_memories",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_ai_memories_user_id",
        table_name="user_ai_memories",
    )
    op.drop_table("user_ai_memories")
