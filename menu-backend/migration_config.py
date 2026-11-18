"""Configuration shared by the menu service's Alembic migration paths."""

MENU_VERSION_TABLE = "menu_backend_alembic_version"


def configure_migration_context(alembic_context, **options) -> None:
    """Keep menu migration history separate from the AI backend's history."""
    options["version_table"] = MENU_VERSION_TABLE
    alembic_context.configure(**options)
