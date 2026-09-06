"""Establish the initial Alembic migration baseline.

Revision 0001 intentionally creates no application tables. Feature tables are
introduced by their own migrations in later roadmap phases.
"""

from alembic import op


revision = "0001_database_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass