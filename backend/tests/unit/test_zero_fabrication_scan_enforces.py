"""The CI zero-fabrication scan must be able to fail, and it must run locally.

⚠️ THE CLASS OF BUG THIS EXISTS FOR

Every check in `.github/workflows/ci.yml`'s "Zero-fabrication scan" step was
written as `! grep ...`, and **none of them could fail the step**. POSIX exempts
a command whose return value is inverted with `!` from `set -e`, so a positive
match did not abort; the step's exit code was only ever the last line's. Eight
of the nine checks were inert from the day they were written, including the
`datetime.utcnow` one, which had a real live violation in
`src/services/social_auth_models.py` sitting in `master` while the gate
reported green.

Measured under `bash --noprofile --norc -eo pipefail` (exactly what
`shell: bash` runs), on the identical seeded violation:

    old `! grep` form  -> exit 0   (violation ignored)
    current form       -> exit 1

⚠️ The first replacement written for it was ALSO inert, in a different way:
`out="$(grep ...)"; rc=$?` takes the substitution's exit status, so under
`set -e` a *clean* grep (exit 1, no match) aborted the step before `rc=$?` ran.
That was caught only by executing the script, not by reading it. Hence the
behavioural tests below rather than a pattern check alone.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
STEP_NAME = "Zero-fabrication scan"

#: What GitHub Actions actually invokes for `shell: bash`.
GHA_BASH = ["bash", "--noprofile", "--norc", "-eo", "pipefail"]


def _bash_works() -> bool:
    """`shutil.which("bash")` only proves *a* ``bash.exe`` exists on PATH.

    On Windows there can be several — Git Bash, a WSL launcher stub in
    System32, a WindowsApps execution alias — and which one
    ``subprocess.run(["bash", ...])`` actually resolves is not guaranteed to
    match ``which``'s answer, or to be a working interpreter at all. A broken
    WSL install surfaces exactly this way: ``which`` finds *something*, but
    every invocation exits non-zero with a WSL config error before running
    any script. Run it and check, the same way the DB-dependent tests below
    check connectivity rather than trusting a URL is merely set.
    """
    if shutil.which("bash") is None:
        return False
    try:
        result = subprocess.run(
            [*GHA_BASH, "-c", "true"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


requires_bash = pytest.mark.skipif(
    not _bash_works(),
    reason="bash on PATH does not run cleanly (e.g. Windows with a broken WSL install shadowing Git Bash)",
)


def _scan_step() -> dict:
    workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    for step in workflow["jobs"]["backend-quality"]["steps"]:
        if step.get("name") == STEP_NAME:
            return step
    raise AssertionError(f"no {STEP_NAME!r} step in backend-quality")


def test_the_scan_step_still_exists_and_runs_from_backend() -> None:
    """Guard the guard: every assertion below is vacuous without this."""
    step = _scan_step()
    assert step["shell"] == "bash"
    assert step["working-directory"] == "backend"
    assert step["run"].strip(), "scan step has an empty script"


def test_no_inverted_command_guards_in_the_scan() -> None:
    """`! cmd` cannot fail the step - that is the whole defect."""
    offenders = [
        line.rstrip()
        for line in _scan_step()["run"].splitlines()
        if re.match(r"\s*!\s+\S", line)
    ]
    assert not offenders, (
        "These lines invert a command's exit status with `!`, which POSIX "
        "exempts from `set -e`, so a positive match CANNOT fail the step:\n"
        + "\n".join(f"  {line}" for line in offenders)
        + "\n\nUse the `forbid` helper, which records a violation instead."
    )


def test_the_scan_ends_in_an_explicit_failing_exit() -> None:
    """Recording violations is useless if nothing acts on the tally."""
    script = _scan_step()["run"]
    assert "exit 1" in script, "the scan never exits non-zero on a violation"
    assert re.search(r'violations["\s]*-ne 0|violations["\s]*!= 0', script), (
        "the scan does not test its own violation tally before exiting"
    )


@requires_bash
def test_forbid_fails_on_a_match_and_on_an_unrunnable_check(tmp_path: Path) -> None:
    """The mechanism itself, isolated from this repository's contents.

    Covers both branches that a naive implementation gets wrong: a match must
    fail, and a `grep` that cannot run (bad path) must NOT read as clean.
    """
    forbid = _extract_forbid(_scan_step()["run"])
    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "dirty.py").write_text("FORBIDDEN_TOKEN = 1\n", encoding="utf-8")

    def run(body: str) -> subprocess.CompletedProcess:
        script = f'violations=0\n{forbid}\n{body}\nexit "$violations"\n'
        return subprocess.run(
            [*GHA_BASH, "-c", script], cwd=tmp_path, capture_output=True, text=True
        )

    clean = run('forbid "nothing here" "ABSENT_TOKEN" clean.py')
    assert clean.returncode == 0, (
        f"a clean check must pass:\n{clean.stdout}{clean.stderr}"
    )

    matched = run('forbid "seeded" "FORBIDDEN_TOKEN" dirty.py')
    assert matched.returncode != 0, "a matching check must fail the step"
    assert "seeded" in matched.stdout

    broken = run('forbid "bad path" "ANY" no_such_file.py')
    assert broken.returncode != 0, (
        "a grep that cannot run must not be reported as clean - that is how a "
        "typo'd path silently disables a check"
    )
    assert "could not run" in broken.stdout


@requires_bash
def test_the_real_scan_passes_on_this_tree() -> None:
    """Runs the actual CI script, bringing the gate local rather than trusting CI.

    A failure here is a real zero-fabrication violation in the working tree, not
    a problem with this test.
    """
    result = subprocess.run(
        [*GHA_BASH, "-c", _scan_step()["run"]],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "the zero-fabrication scan fails on this tree:\n"
        + textwrap.indent(result.stdout + result.stderr, "  ")
    )


def _extract_forbid(script: str) -> str:
    """The `forbid () { ... }` definition, lifted out of the step's script."""
    match = re.search(r"^\s*forbid\(\)\s*\{.*?^\s*\}\s*$", script, re.S | re.M)
    assert match, "could not find the `forbid` helper in the scan step"
    return textwrap.dedent(match.group(0))
