import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from verify_ci_postgres import _github_actions_context_is_valid


def _set_approved_context(monkeypatch):
    values = {
        "GITHUB_ACTIONS": "true",
        "CI": "true",
        "RUNNER_OS": "Linux",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_RUN_ID": "12345",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REPOSITORY": "example/food-ordering",
        "GITHUB_WORKFLOW": "Full Stack CI",
        "GITHUB_JOB": "backend",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_approved_github_actions_job_context_is_recognized(monkeypatch):
    _set_approved_context(monkeypatch)

    assert _github_actions_context_is_valid()


def test_local_ci_environment_cannot_enable_identity_verification(monkeypatch):
    _set_approved_context(monkeypatch)
    monkeypatch.delenv("GITHUB_ACTIONS")

    assert not _github_actions_context_is_valid()


def test_unapproved_workflow_job_cannot_enable_identity_verification(monkeypatch):
    _set_approved_context(monkeypatch)
    monkeypatch.setenv("GITHUB_JOB", "unapproved-job")

    assert not _github_actions_context_is_valid()


def test_invalid_run_context_cannot_enable_identity_verification(monkeypatch):
    _set_approved_context(monkeypatch)
    monkeypatch.setenv("GITHUB_RUN_ID", "not-numeric")

    assert not _github_actions_context_is_valid()
