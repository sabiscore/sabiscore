from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "check-codex-skills.py"
SPEC = importlib.util.spec_from_file_location("check_codex_skills", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DiscoveryOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=SCRIPT.parents[1])
        self.root = Path(self.temp_dir.name)
        self.canonical = self.root / ".ai" / "skills"
        self.bridge = self.root / ".agents" / "skills"
        self.canonical.mkdir(parents=True)
        self.bridge.mkdir(parents=True)
        for name in ("nexus", "testing"):
            skill = self.canonical / name
            skill.mkdir()
            (skill / "SKILL.md").write_text("---\nname: test\ndescription: test\n---\n")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @property
    def skill_files(self) -> list[Path]:
        return sorted(self.canonical.glob("*/SKILL.md"))

    def overlay_resolver(self, path: Path) -> Path:
        if path.parent == self.bridge and path.name in {"nexus", "testing"}:
            return (self.canonical / path.name).resolve()
        return path.resolve()

    def test_overlay_accepts_canonical_targets_and_external_entries(self) -> None:
        for name in ("nexus", "testing", "neon"):
            (self.bridge / name).mkdir()

        errors, mode, external = MODULE.validate_bridge(
            self.canonical,
            self.bridge,
            self.skill_files,
            resolver=self.overlay_resolver,
        )

        self.assertEqual(errors, [])
        self.assertEqual(mode, "overlay")
        self.assertEqual(external, ["neon"])

    def test_overlay_rejects_missing_canonical_skill(self) -> None:
        (self.bridge / "nexus").mkdir()

        errors, mode, external = MODULE.validate_bridge(
            self.canonical,
            self.bridge,
            self.skill_files,
            resolver=self.overlay_resolver,
        )

        self.assertEqual(mode, "overlay")
        self.assertEqual(external, [])
        self.assertEqual(
            errors,
            ["missing canonical skill from discovery overlay: testing"],
        )

    def test_overlay_rejects_name_collision(self) -> None:
        for name in ("nexus", "testing"):
            (self.bridge / name).mkdir()

        errors, _, _ = MODULE.validate_bridge(
            self.canonical,
            self.bridge,
            self.skill_files,
        )

        self.assertEqual(len(errors), 2)
        self.assertTrue(all("discovery collision" in error for error in errors))

    def test_legacy_root_link_remains_valid(self) -> None:
        def legacy_resolver(path: Path) -> Path:
            if path == self.bridge:
                return self.canonical.resolve()
            return path.resolve()

        errors, mode, external = MODULE.validate_bridge(
            self.canonical,
            self.bridge,
            self.skill_files,
            resolver=legacy_resolver,
        )

        self.assertEqual(errors, [])
        self.assertEqual(mode, "legacy-root-link")
        self.assertEqual(external, [])


if __name__ == "__main__":
    unittest.main()
