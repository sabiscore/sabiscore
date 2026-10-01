"""Run one command in the repository's RSS guard (single lane)."""

from __future__ import annotations

import argparse
import subprocess
import sys

from backend.scripts._resource_guard import ResourceGuard


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not command:
        parser.error("a command after -- is required")
    with ResourceGuard():
        completed = subprocess.run(command, check=False)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
