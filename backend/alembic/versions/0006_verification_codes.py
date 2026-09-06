"""Create user verification codes table."""

from alembic import op
import sqlalchemy as sa


revision = "0006_verification_codes"
down_revision = "0005_optional_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_verification_codes",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "channel",
            sa.String(length=16),
            nullable=False,
        ),
        sa.Column(
            "purpose",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "code_hash",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_user_verification_codes_user_id",
        "user_verification_codes",
        ["user_id"],
        unique=False,
    )

    op.create_index(
        "ix_user_verification_codes_lookup",
        "user_verification_codes",
        ["user_id", "channel", "purpose"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_verification_codes_lookup",
        table_name="user_verification_codes",
    )

    op.drop_index(
        "ix_user_verification_codes_user_id",
        table_name="user_verification_codes",
    )

    op.drop_table("user_verification_codes")