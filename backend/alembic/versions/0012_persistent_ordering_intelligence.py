"""add persistent ordering intelligence tables

Revision ID: 0012_ordering_intelligence
Revises: 0011_login_attempts
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_ordering_intelligence"
down_revision = "0011_login_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_ordering_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "total_orders",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_items",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_spend",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "average_order_value",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_order_id", sa.String(100), nullable=True),
        sa.Column("last_order_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "weekday_counts_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "meal_period_counts_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
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
        "ix_user_ordering_profiles_user_id",
        "user_ordering_profiles",
        ["user_id"],
        unique=True,
    )

    op.create_table(
        "user_ordering_item_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("item_key", sa.String(255), nullable=False),
        sa.Column("item_title", sa.String(255), nullable=False),
        sa.Column("restaurant_name", sa.String(255), nullable=False),
        sa.Column(
            "order_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_quantity",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "last_ordered_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "item_key",
            "restaurant_name",
        ),
    )

    op.create_index(
        "ix_user_ordering_item_stats_user_id",
        "user_ordering_item_stats",
        ["user_id"],
    )

    op.create_table(
        "user_ordering_restaurant_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("restaurant_name", sa.String(255), nullable=False),
        sa.Column(
            "order_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_spend",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "last_ordered_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "restaurant_name",
        ),
    )

    op.create_index(
        "ix_user_ordering_restaurant_stats_user_id",
        "user_ordering_restaurant_stats",
        ["user_id"],
    )

    op.create_table(
        "user_ordering_processed_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.String(100), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "order_id",
        ),
    )

    op.create_index(
        "ix_user_ordering_processed_orders_user_id",
        "user_ordering_processed_orders",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_ordering_processed_orders_user_id",
        table_name="user_ordering_processed_orders",
    )
    op.drop_table("user_ordering_processed_orders")

    op.drop_index(
        "ix_user_ordering_restaurant_stats_user_id",
        table_name="user_ordering_restaurant_stats",
    )
    op.drop_table("user_ordering_restaurant_stats")

    op.drop_index(
        "ix_user_ordering_item_stats_user_id",
        table_name="user_ordering_item_stats",
    )
    op.drop_table("user_ordering_item_stats")

    op.drop_index(
        "ix_user_ordering_profiles_user_id",
        table_name="user_ordering_profiles",
    )
    op.drop_table("user_ordering_profiles")
