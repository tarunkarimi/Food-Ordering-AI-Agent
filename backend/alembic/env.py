"""Alembic environment configuration."""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the backend directory importable when Alembic is executed directly.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.configs.config import config as app_config
from src.db.base import Base
from src.db.database import DATABASE_URL
from src.db.base import Base
from src.db.database import DATABASE_URL
from src.db.models import User

# Import models here as they are introduced in later phases so Alembic can
# discover their metadata. #25.1 intentionally has no application tables yet.

target_metadata = Base.metadata

alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)


def run_migrations_offline() -> None:
    """Run migrations without creating a database connection."""

    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using a live database connection."""

    configuration = alembic_config.get_section(
        alembic_config.config_ini_section,
        {},
    )
    configuration["sqlalchemy.url"] = DATABASE_URL

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()