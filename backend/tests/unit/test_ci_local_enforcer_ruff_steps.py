"""`ci_local_enforcer.sh`'s ruff steps must actually reach zero-exit, and must
still catch the bug class they exist for.

⚠️ THE CLASS OF BUG THIS EXISTS FOR (docs/DEBT.md item 112)

The enforcer's two ruff steps ran a bare `ruff check src/` / `ruff check
scripts/` — no `--select`. `requirements-dev.txt` pins no ruff version, and an
unconfigured `ruff check` resolves to whatever that release's own default rule
set is. On the ruff release this repo last verified against (0.16.8, no
`pyproject.toml`/`ruff.toml` anywhere in the tree to override it — confirmed
with `--isolated`, which bypasses all config discovery and reproduces the
identical count), that default is far broader than the `E4,E7,E9,F` selection
CI actually gates on: 3900 findings on `src/`, 751 on `scripts/`,
overwhelmingly pyupgrade/isort modernization debt this codebase was never
cleaned against, not the correctness class CI cares about. `set -euo pipefail`
would abort the "MANDATORY, zero-exit" gate right there on a fresh install,
before a single test ran — exactly the class of inert-guard defect docs/DEBT.md
items 99/104/109/111 each found by actually executing a guard rather than
reading it (DID Rule 15).

The fix restricts both steps to the same `--select E4,E7,E9,F` CI uses for
`src/`, extended to `scripts/` (which CI never lints). F821 undefined-name is
an `F` code, so this still catches the exact historical bug (item 99's missing
`pathlib` import in `validate_deployment.py`) that justified linting
`scripts/` in the first place — proven below by injecting an equivalent
regression, not merely asserted.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"
ENFORCER = REPO_ROOT / "scripts" / "ci_local_enforcer.sh"


def _ruff_step_lines() -> list[str]:
    """The two `bash -c "... ruff check ..."` invocation lines, not comments."""
    text = ENFORCER.read_text(encoding="utf-8")
    return [
        line
        for line in text.splitlines()
        if re.search(r"-m ruff check", line) and line.lstrip().startswith("bash -c")
    ]


def test_no_step_runs_ruff_without_an_explicit_select() -> None:
    """Guard against reverting to a bare `ruff check` on either path."""
    lines = _ruff_step_lines()
    assert len(lines) == 2, (
        f"expected exactly 2 ruff invocations, found {len(lines)}:\n{lines}"
    )
    for line in lines:
        assert "--select E4,E7,E9,F" in line, (
            "a ruff step is missing the explicit CI-equivalent --select, which "
            "means it inherits whatever the installed ruff version's own "
            "default rule set is — see docs/DEBT.md item 112:\n" + line
        )


def test_the_real_ruff_steps_pass_on_this_tree() -> None:
    """Runs the actual selected commands, bringing the gate local.

    A failure here is either a real E4/E7/E9/F violation in the working tree,
    or the enforcer script's invocation drifting from what this test extracted
    — not a problem with this test.
    """
    for target in ("src", "scripts"):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                f"{target}/",
                "--select",
                "E4,E7,E9,F",
            ],
            cwd=BACKEND_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"ruff check {target}/ --select E4,E7,E9,F fails on this tree:\n"
            + result.stdout
            + result.stderr
        )


def test_the_ci_equivalent_selection_still_catches_an_undefined_name_regression(
    tmp_path: Path,
) -> None:
    """Rule 15: prove the narrower selection did not lose the safety property
    item 99 was built for — a scripts/ file referencing an unimported name.
    """
    regressed = BACKEND_ROOT / "scripts" / "_rule15_undefined_name_check.py"
    assert not regressed.exists(), "scratch file collides with a real one"
    regressed.write_text(
        "def broken():\n    return Path('x')  # Path is never imported -> F821\n",
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                str(regressed.relative_to(BACKEND_ROOT)),
                "--select",
                "E4,E7,E9,F",
            ],
            cwd=BACKEND_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, "the selected ruleset failed to catch F821"
        assert re.search(r"F821", result.stdout), (
            "expected an F821 undefined-name finding:\n" + result.stdout
        )
    finally:
        regressed.unlink()
