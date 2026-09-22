"""`verify_remote_ci.sh` must use live required-status contexts from rulesets.

This test suite executes the real script with a mocked `gh` binary so we can
assert behavior deterministically without network/API dependencies.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "verify_remote_ci.sh"

# Matches GitHub Actions' `shell: bash` invocation style.
_BASH_FLAGS = ["--noprofile", "--norc", "-eo", "pipefail"]


def _candidate_bash_executables() -> list[str]:
    """Return likely bash executables, preferring explicit executables.

    On Windows, `bash` can resolve to a WSL launcher shim that exists but cannot
    actually run scripts. We try explicit Git Bash paths as fallbacks.
    """

    candidates: list[str] = []
    env_bash = os.environ.get("BASH_EXE")
    if env_bash:
        candidates.append(env_bash)

    discovered = shutil.which("bash")
    if discovered:
        candidates.append(discovered)

    candidates.extend(
        [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\usr\bin\bash.exe",
        ]
    )

    # Preserve order while deduplicating.
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _find_working_bash() -> str | None:
    """Return a usable bash executable path, or None if none work."""

    for candidate in _candidate_bash_executables():
        try:
            result = subprocess.run(
                [candidate, *_BASH_FLAGS, "-c", "true"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return candidate

    return None


BASH_EXE = _find_working_bash()
GHA_BASH = [BASH_EXE or "bash", *_BASH_FLAGS]


requires_bash = pytest.mark.skipif(
    BASH_EXE is None,
    reason=(
        "no working bash executable found (for example, a broken WSL launcher "
        "shadowing Git Bash)"
    ),
)


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_uses_branch_ruleset_required_status_checks_contexts() -> None:
    script = _script_text()
    assert "collect_required_contexts()" in script
    assert "required_status_checks" in script
    assert "repos/$REPO/rules/branches/$BRANCH" in script


def test_uses_commit_check_runs_not_hardcoded_workflow_names() -> None:
    script = _script_text()
    assert "collect_check_runs()" in script
    assert "repos/$REPO/commits/$SHA/check-runs?per_page=100" in script
    assert "REQUIRED_WORKFLOWS=(" not in script


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _fake_gh_script(*, include_required_rule: bool, all_checks_success: bool) -> str:
    required_contexts = (
        "Backend Lint, Typecheck, Tests\nWeb Lint, Typecheck, Build\n"
        if include_required_rule
        else ""
    )

    checks_success = (
        "Backend Lint, Typecheck, Tests\tcompleted\tsuccess\t2\n"
        "Web Lint, Typecheck, Build\tcompleted\tsuccess\t3\n"
    )
    checks_failure = (
        "Backend Lint, Typecheck, Tests\tcompleted\tfailure\t2\n"
        "Web Lint, Typecheck, Build\tcompleted\tsuccess\t3\n"
    )

    checks = checks_success if all_checks_success else checks_failure

    # One completed job with non-empty runner_name + 1 step proves lock is clear.
    jobs = "CI - Canonical Platform\tcompleted\tsuccess\tGitHub Actions 1\t1\n"

    return textwrap.dedent(
        f"""#!/usr/bin/env bash
set -euo pipefail

if [ "$1" = "auth" ] && [ "$2" = "status" ]; then
  exit 0
fi

if [ "$1" = "repo" ] && [ "$2" = "view" ]; then
  echo "sabiscore/sabiscore"
  exit 0
fi

if [ "$1" = "api" ]; then
    url=""
    for arg in "$@"; do
        case "$arg" in
            repos/*)
                url="$arg"
                break
                ;;
        esac
    done

    if [ -z "$url" ]; then
        exit 0
    fi

  if [[ "$url" == repos/sabiscore/sabiscore/rules/branches/master ]]; then
    if [[ "$@" == *required_status_checks* ]]; then
      printf '{required_contexts}'
      exit 0
    fi
    exit 0
  fi

  if [[ "$url" == repos/sabiscore/sabiscore/actions/runs/101/jobs ]]; then
    printf '{jobs}'
    exit 0
  fi

  if [[ "$url" == repos/sabiscore/sabiscore/commits/*/check-runs* ]]; then
    printf '{checks}'
    exit 0
  fi

    if [[ "$url" == repos/sabiscore/sabiscore/actions/runs* ]]; then
        echo "101"
        exit 0
    fi
fi

exit 0
"""
    )


def _run_with_fake_gh(
    tmp_path: Path, *, include_required_rule: bool, all_checks_success: bool
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_gh = bin_dir / "gh"
    _write_executable(
        fake_gh,
        _fake_gh_script(
            include_required_rule=include_required_rule,
            all_checks_success=all_checks_success,
        ),
    )

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"

    return subprocess.run(
        [
            *GHA_BASH,
            str(SCRIPT),
            "--branch",
            "master",
            "--sha",
            "0123456789abcdef0123456789abcdef01234567",
            "--once",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@requires_bash
def test_fails_when_no_required_status_checks_rule(tmp_path: Path) -> None:
    result = _run_with_fake_gh(
        tmp_path,
        include_required_rule=False,
        all_checks_success=True,
    )

    assert result.returncode != 0
    assert "has no required_status_checks rule" in (result.stdout + result.stderr)


@requires_bash
def test_passes_when_runner_booted_and_required_checks_green(tmp_path: Path) -> None:
    result = _run_with_fake_gh(
        tmp_path,
        include_required_rule=True,
        all_checks_success=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "RUNNER BOOTED: yes" in result.stdout
    assert "PASS: remote CI is green" in result.stdout


@requires_bash
def test_fails_when_a_required_check_is_red_even_if_runner_booted(
    tmp_path: Path,
) -> None:
    result = _run_with_fake_gh(
        tmp_path,
        include_required_rule=True,
        all_checks_success=False,
    )

    assert result.returncode != 0
    assert "RUNNER BOOTED: yes" in result.stdout
    assert "required::Backend Lint, Typecheck, Tests :: failure" in result.stdout
