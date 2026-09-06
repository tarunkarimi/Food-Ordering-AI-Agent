"""Create persistent user carts."""

from alembic import op
import sqlalchemy as sa


revision = "0008_persistent_carts"
down_revision = "0007_user_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "carts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("restaurant_name", sa.String(length=255), nullable=False),
        sa.Column("subdomain", sa.String(length=255), nullable=False),
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
        "ix_carts_user_id",
        "carts",
        ["user_id"],
        unique=True,
    )

    op.create_table(
        "cart_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cart_id", sa.Integer(), nullable=False),
        sa.Column("item_key", sa.String(length=512), nullable=False),
        sa.Column("item_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("variation_id", sa.String(length=255), nullable=True),
        sa.Column("variation_name", sa.String(length=500), nullable=True),
        sa.Column("variation_price", sa.Numeric(12, 2), nullable=True),
        sa.ForeignKeyConstraint(
            ["cart_id"],
            ["carts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "cart_id",
            "item_key",
            name="uq_cart_items_cart_item_key",
        ),
    )

    op.create_index(
        "ix_cart_items_cart_id",
        "cart_items",
        ["cart_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cart_items_cart_id",
        table_name="cart_items",
    )

    op.drop_table("cart_items")

    op.drop_index(
        "ix_carts_user_id",
        table_name="carts",
    )

    op.drop_table("carts")
