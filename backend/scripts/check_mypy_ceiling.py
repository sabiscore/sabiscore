"""Run mypy and fail only when the explicit legacy-debt ceiling is exceeded."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ERROR_COUNT_PATTERN = re.compile(r"Found (?P<count>\d+) errors? in \d+ files?")


def parse_error_count(output: str) -> int | None:
    """Return mypy's reported error count, including a clean zero-result."""

    if "Success: no issues found" in output:
        return 0
    match = ERROR_COUNT_PATTERN.search(output)
    return int(match.group("count")) if match else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ceiling", type=int, default=784)
    parser.add_argument("--target", default="src")
    args = parser.parse_args()

    backend_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            args.target,
            "--no-pretty",
            "--no-color-output",
        ],
        cwd=backend_root,
        capture_output=True,
        text=True,
        check=False,
    )
    output = completed.stdout + completed.stderr
    sys.stdout.write(output)

    error_count = parse_error_count(output)
    if error_count is None or completed.returncode not in {0, 1}:
        print("mypy ceiling check failed: unable to establish a valid error count")
        return 2
    if error_count > args.ceiling:
        print(f"mypy ceiling exceeded: {error_count} > {args.ceiling}")
        return 1
    print(f"mypy ceiling satisfied: {error_count} <= {args.ceiling}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
