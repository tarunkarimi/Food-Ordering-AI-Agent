"""add durable checkout and cancellation operation records

Revision ID: 0014_order_operations
Revises: 0013_ai_memory
"""

from alembic import op
import sqlalchemy as sa

revision = "0014_order_operations"
down_revision = "0013_ai_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "order_operations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("operation_type", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("order_id", sa.String(255)),
        sa.Column("subdomain", sa.String(255), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("upstream_order_id", sa.String(255)),
        sa.Column("response_json", sa.Text()),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_order_operation_user_key"),
    )
    op.create_index("ix_order_operations_order_id", "order_operations", ["order_id"])
    op.create_index("ix_order_operations_status_updated", "order_operations", ["status", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_order_operations_status_updated", table_name="order_operations")
    op.drop_index("ix_order_operations_order_id", table_name="order_operations")
    op.drop_table("order_operations")
