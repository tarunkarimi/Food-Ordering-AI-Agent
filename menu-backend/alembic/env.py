import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from migration_config import configure_migration_context
from order_storage import OrderBase

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)


def _database_url() -> str:
    url = os.getenv("MENU_MIGRATION_DATABASE_URL") or os.getenv("MENU_DATABASE_URL", "")
    if not url:
        raise RuntimeError("MENU_DATABASE_URL is required for menu migrations.")
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


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
