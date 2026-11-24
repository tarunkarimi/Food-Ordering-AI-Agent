"""Verify the identity of a job-local GitHub Actions PostgreSQL service."""

import os
from pathlib import Path
import re
import sys

from sqlalchemy import create_engine, text

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_WORKFLOW_JOBS = {
    ("Full Stack CI", "backend"),
    ("Full Stack CI", "menu-backend"),
    ("AI Agent Evaluation", "ai-agent-evaluation"),
}
ALLOWED_URL_VARIABLES = {"MIGRATION_DATABASE_URL", "MENU_MIGRATION_DATABASE_URL"}


def _github_actions_context_is_valid() -> bool:
    if os.environ.get("GITHUB_ACTIONS", "").casefold() != "true":
        return False
    if os.environ.get("CI", "").casefold() != "true":
        return False
    if os.environ.get("RUNNER_OS") != "Linux":
        return False
    if os.environ.get("GITHUB_EVENT_NAME") not in {"push", "pull_request"}:
        return False
    if not re.fullmatch(r"\d+", os.environ.get("GITHUB_RUN_ID", "")):
        return False
    if not re.fullmatch(r"\d+", os.environ.get("GITHUB_RUN_ATTEMPT", "")):
        return False
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        return False
    return (
        os.environ.get("GITHUB_WORKFLOW", ""),
        os.environ.get("GITHUB_JOB", ""),
    ) in ALLOWED_WORKFLOW_JOBS


def verify_ci_postgres(url_variable: str) -> None:
    if url_variable not in ALLOWED_URL_VARIABLES:
        raise RuntimeError("The CI database URL variable is not approved.")
    if not _github_actions_context_is_valid():
        raise RuntimeError("This verification is limited to the configured GitHub Actions jobs.")
    if (REPOSITORY_ROOT / "backend" / ".env").exists() or (
        REPOSITORY_ROOT / "menu-backend" / ".env"
    ).exists():
        raise RuntimeError("Developer environment files are not permitted in CI.")

    sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))
    connection_url = os.environ.get(url_variable, "")
    from src.db_test_safety import validate_ci_database_url

    target = validate_ci_database_url(connection_url)
    engine = create_engine(target, pool_pre_ping=True, hide_parameters=True)
    try:
        with engine.connect() as connection:
            database_name, database_user, server_version = connection.execute(
                text("SELECT current_database(), current_user, current_setting('server_version_num')")
            ).one()
        if (
            database_name != "food_ordering_ci"
            or database_user != "postgres"
            or not str(server_version).startswith("16")
        ):
            raise RuntimeError("The connected PostgreSQL service identity is not approved.")
    finally:
        engine.dispose()


def main() -> int:
    if len(sys.argv) != 2:
        print("CI PostgreSQL verification requires one approved URL variable name.")
        return 2
    try:
        verify_ci_postgres(sys.argv[1])
    except Exception:
        print("Disposable CI PostgreSQL identity verification failed; connection details suppressed.")
        return 1
    print("Disposable CI PostgreSQL identity verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
