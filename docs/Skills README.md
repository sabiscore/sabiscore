# SabiScore Codex VS Code Integration Pack

This pack adapts the supplied Claude Code control system to OpenAI Codex while
preserving the existing NEXUS router and `.ai/skills` suite as the canonical source.

## Files

- `AGENTS.md` — production-grade Codex repository instructions.
- `.ai/skills/nexus/SKILL.md` — Codex-native NEXUS entry skill.
- `backend/AGENTS.md`, `apps/web/AGENTS.md`, `apps/scraper/AGENTS.md`,
  `models/AGENTS.md` — scoped subsystem rules.
- `docs/CODEX_VSCODE_SETUP.md` — full setup and usage guide.
- `scripts/setup-codex-skills.*` — non-duplicating discovery overlay setup that
  preserves plugin-managed skills.
- `scripts/check-codex-skills.py` — skill metadata/discovery validation.

Copy these paths into the matching locations in the SabiScore repository, then run
the setup and validation commands in `docs/CODEX_VSCODE_SETUP.md`.
