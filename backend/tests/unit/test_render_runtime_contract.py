"""Fail-closed regression checks for the Render API process lifecycle."""

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
_RENDER_BLUEPRINT = _REPO_ROOT / "render.yaml"


def _web_start_command() -> str:
    for line in _RENDER_BLUEPRINT.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if stripped.startswith("startCommand:"):
            return stripped.removeprefix("startCommand:").strip()
    raise AssertionError("render.yaml must define the API startCommand")


def test_single_uvicorn_worker_does_not_exit_after_a_request_count() -> None:
    """Render owns process restarts; a lone Uvicorn worker must not self-terminate.

    Render's readiness probe is regular HTTP traffic. With one standalone worker,
    ``--limit-max-requests`` makes Uvicorn terminate the only serving process when
    the counter is reached, creating a full cold-start outage before Render can
    replace it. Request-count recycling is safe only behind a process manager that
    retains the listening socket and replaces workers without dropping service.
    """

    command = _web_start_command()
    assert "--workers 1" in command
    assert "--limit-max-requests" not in command
