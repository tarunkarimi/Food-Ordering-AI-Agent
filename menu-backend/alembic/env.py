import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from migration_config import configure_migration_context
from order_storage import OrderBase, normalize_database_url

# The CLI migration path uses the menu service's ignored local .env just like
# the application, while explicit process/secret-manager values take priority.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)


def _database_url() -> str:
    url = os.getenv("MENU_MIGRATION_DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "MENU_MIGRATION_DATABASE_URL must be explicitly configured; migrations never use MENU_DATABASE_URL."
        )
    return normalize_database_url(url)


target_metadata = OrderBase.metadata


def run_migrations_offline() -> None:
    configure_migration_context(
        context,
        url=_database_url(), target_metadata=target_metadata,
        literal_binds=True, dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        configure_migration_context(
            context,
            connection=connection, target_metadata=target_metadata,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
