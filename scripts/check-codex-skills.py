#!/usr/bin/env python3
"""Validate repository skill discovery and minimum SKILL.md metadata."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    canonical = root / ".ai" / "skills"
    bridge = root / ".agents" / "skills"

    errors = 0
    if not canonical.is_dir():
        fail(f"missing canonical directory: {canonical}")
        return 1
    if not bridge.exists():
        fail(f"missing Codex discovery bridge: {bridge}")
        errors += 1
    elif bridge.resolve() != canonical.resolve():
        fail(
            f"Codex discovery path must resolve to the canonical skill directory: "
            f"{bridge.relative_to(root)} -> {canonical.relative_to(root)}"
        )
        errors += 1

    names: dict[str, Path] = {}
    skill_files = sorted(canonical.glob("*/SKILL.md"))
    if not skill_files:
        fail(f"no SKILL.md files found under {canonical}")
        return 1

    if bridge.exists():
        canonical_names = {path.parent.name for path in skill_files}
        bridge_names = {path.parent.name for path in bridge.glob("*/SKILL.md")}
        if bridge_names != canonical_names:
            missing = sorted(canonical_names - bridge_names)
            extra = sorted(bridge_names - canonical_names)
            fail(f"Codex discovery mismatch: missing={missing}, extra={extra}")
            errors += 1

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
    print(f"Codex discovery path is available at {bridge.relative_to(root)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
