#!/usr/bin/env python3
"""Validate repository skill metadata and the Codex discovery overlay."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

PathResolver = Callable[[Path], Path]


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)


def resolve_path(path: Path) -> Path:
    return path.resolve()


def validate_bridge(
    canonical: Path,
    bridge: Path,
    skill_files: Sequence[Path],
    *,
    resolver: PathResolver = resolve_path,
) -> tuple[list[str], str, list[str]]:
    """Return bridge errors, bridge mode, and external discovery entries."""
    if not bridge.exists():
        return [f"missing Codex discovery bridge: {bridge}"], "missing", []

    canonical_resolved = resolver(canonical)
    if resolver(bridge) == canonical_resolved:
        return [], "legacy-root-link", []

    if not bridge.is_dir():
        return [f"Codex discovery bridge is not a directory: {bridge}"], "invalid", []

    errors: list[str] = []
    canonical_names = {path.parent.name for path in skill_files}
    for name in sorted(canonical_names):
        discovered = bridge / name
        expected = canonical / name
        if not discovered.is_dir():
            errors.append(f"missing canonical skill from discovery overlay: {name}")
            continue
        if resolver(discovered) != resolver(expected):
            errors.append(
                f"discovery collision for '{name}': {discovered} does not resolve to {expected}"
            )

    external = sorted(
        path.name
        for path in bridge.iterdir()
        if path.is_dir() and path.name not in canonical_names
    )
    return errors, "overlay", external


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        help="repository root (defaults to the parent of this script directory)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = (args.root or Path(__file__).resolve().parents[1]).resolve()
    canonical = root / ".ai" / "skills"
    bridge = root / ".agents" / "skills"

    errors = 0
    if not canonical.is_dir():
        fail(f"missing canonical directory: {canonical}")
        return 1

    skill_files = sorted(canonical.glob("*/SKILL.md"))
    if not skill_files:
        fail(f"no SKILL.md files found under {canonical}")
        return 1

    bridge_errors, bridge_mode, external = validate_bridge(
        canonical, bridge, skill_files
    )
    for message in bridge_errors:
        fail(message)
        errors += 1

    names: dict[str, Path] = {}
    frontmatter_re = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
    name_re = re.compile(r"^name:\s*(\S.*?)\s*$", re.MULTILINE)
    description_re = re.compile(r"^description:\s*(\S.*?)\s*$", re.MULTILINE)

    for path in skill_files:
        text = path.read_text(encoding="utf-8")
        match = frontmatter_re.search(text)
        if not match:
            fail(f"{path.relative_to(root)}: missing YAML frontmatter")
            errors += 1
            continue
        meta = match.group(1)
        name_match = name_re.search(meta)
        desc_match = description_re.search(meta)
        if not name_match:
            fail(f"{path.relative_to(root)}: missing 'name'")
            errors += 1
            continue
        if not desc_match:
            fail(f"{path.relative_to(root)}: missing 'description'")
            errors += 1
        name = name_match.group(1).strip().strip('"\'')
        if name in names:
            fail(
                f"duplicate skill name '{name}': "
                f"{names[name].relative_to(root)} and {path.relative_to(root)}"
            )
            errors += 1
        else:
            names[name] = path

    if errors:
        print(f"Validation failed with {errors} error(s).", file=sys.stderr)
        return 1

    print(f"Validated {len(skill_files)} skills in {canonical.relative_to(root)}.")
    print(
        f"Codex discovery path is available at {bridge.relative_to(root)} "
        f"({bridge_mode})."
    )
    if external:
        print(f"Preserved external discovery entries: {', '.join(external)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
