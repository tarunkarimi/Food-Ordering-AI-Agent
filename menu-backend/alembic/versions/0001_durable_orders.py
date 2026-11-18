"""Create menu-backend owned durable order tables."""

from alembic import op
import sqlalchemy as sa

revision = "0001_durable_orders"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS menu_backend")
    op.create_table(
        "orders",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("subdomain", sa.String(length=255), nullable=False),
        sa.Column("restaurant_name", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("cancellation_reason", sa.String(length=255)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "user_id", "subdomain", "idempotency_key",
            name="uq_menu_order_idempotency_scope",
        ),
        sa.CheckConstraint("status IN ('confirmed', 'cancelled')", name="ck_menu_order_status"),
        sa.CheckConstraint("subtotal >= 0", name="ck_menu_order_subtotal_nonnegative"),
        schema="menu_backend",
    )
    op.create_index("ix_menu_backend_orders_user_id", "orders", ["user_id"], schema="menu_backend")
    op.create_index("ix_menu_backend_orders_subdomain", "orders", ["subdomain"], schema="menu_backend")
    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.String(length=40), sa.ForeignKey("menu_backend.orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("variation_json", sa.Text()),
        sa.CheckConstraint("quantity > 0", name="ck_menu_order_item_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_menu_order_item_price_nonnegative"),
        sa.UniqueConstraint("order_id", "position", name="uq_menu_order_item_position"),
        schema="menu_backend",
    )
    op.create_index("ix_menu_backend_order_items_order_id", "order_items", ["order_id"], schema="menu_backend")


def downgrade() -> None:
    op.drop_index("ix_menu_backend_order_items_order_id", table_name="order_items", schema="menu_backend")
    op.drop_table("order_items", schema="menu_backend")
    op.drop_index("ix_menu_backend_orders_subdomain", table_name="orders", schema="menu_backend")
    op.drop_index("ix_menu_backend_orders_user_id", table_name="orders", schema="menu_backend")
    op.drop_table("orders", schema="menu_backend")
