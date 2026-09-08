"""Create persistent authenticated order history."""

from alembic import op
import sqlalchemy as sa


revision = "0009_order_history"
down_revision = "0008_persistent_carts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "order_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.String(length=255), nullable=False),
        sa.Column("restaurant_name", sa.String(length=255), nullable=False),
        sa.Column("subdomain", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False),
        sa.Column("items_json", sa.Text(), nullable=False),
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
        sa.UniqueConstraint("order_id"),
    )

    op.create_index(
        "ix_order_history_user_id",
        "order_history",
        ["user_id"],
    )

    op.create_index(
        "ix_order_history_order_id",
        "order_history",
        ["order_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_order_history_order_id",
        table_name="order_history",
    )

    op.drop_index(
        "ix_order_history_user_id",
        table_name="order_history",
    )

    op.drop_table("order_history")
