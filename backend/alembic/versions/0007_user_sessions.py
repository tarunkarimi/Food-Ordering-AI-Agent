"""Create user_sessions table."""

from alembic import op
import sqlalchemy as sa


revision = "0007_user_sessions"
down_revision = "0006_verification_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column(
            "id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "access_token_jti",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("access_token_jti"),
    )

    op.create_index(
        "ix_user_sessions_user_id",
        "user_sessions",
        ["user_id"],
    )

    op.create_index(
        "ix_user_sessions_access_token_jti",
        "user_sessions",
        ["access_token_jti"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_sessions_access_token_jti",
        table_name="user_sessions",
    )
    op.drop_index(
        "ix_user_sessions_user_id",
        table_name="user_sessions",
    )
    op.drop_table("user_sessions")
