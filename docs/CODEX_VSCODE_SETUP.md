# OpenAI Codex + VS Code Setup for SabiScore

This guide installs the Codex IDE workflow without replacing the existing Claude
Code setup or duplicating the AI skill suite.

## 1. Final repository layout

Place the supplied files at the repository root so the resulting tree includes:

```text
sabiscore/
├── AGENTS.md
├── CLAUDE.md
├── NEXUS.md
├── .ai/
│   └── skills/
│       ├── nexus/SKILL.md
│       └── <existing-skill>/SKILL.md
├── .agents/
│   └── skills/
│       ├── nexus -> ../../.ai/skills/nexus
│       ├── <repository-skill> -> ../../.ai/skills/<repository-skill>
│       └── <external-skill>/SKILL.md
├── backend/AGENTS.md
├── apps/web/AGENTS.md
├── apps/scraper/AGENTS.md
├── models/AGENTS.md
├── docs/ai/CODEX_VERIFIED_STATE.md
└── scripts/
    ├── setup-codex-skills.sh
    ├── setup-codex-skills.ps1
    └── check-codex-skills.py
```

Why this layout:

- `.ai/skills` stays the single canonical skill source shared by tools.
- `.agents/skills` is the Codex-native discovery location.
- the per-skill overlay prevents canonical skills from drifting while preserving
  plugin-managed discovery entries.
- nested `AGENTS.md` files apply only to their subsystem.

## 2. Install and sign in

1. Install the official OpenAI Codex extension from the VS Code Marketplace.
2. Restart VS Code if the Codex icon does not appear.
3. Open the Codex sidebar and sign in with your ChatGPT account or configured API
   authentication.
4. Open the repository root, not only `apps/web` or `backend`, so Codex sees the root
   instructions and all root skills.

On Windows, use either Codex's native Windows support or open the repository through
WSL2 when the development toolchain is Linux-native. For this project, WSL2 is the
safer default when Docker, shell scripts, Python, and pnpm already run there.

## 3. Install the skill bridge

### Linux, macOS, or WSL2

From the repository root:

```bash
bash scripts/setup-codex-skills.sh
python scripts/check-codex-skills.py
```

This creates one link per canonical repository skill:

```text
.agents/skills/nexus -> ../../.ai/skills/nexus
.agents/skills/<repository-skill> -> ../../.ai/skills/<repository-skill>
```

### Native Windows PowerShell

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup-codex-skills.ps1
python scripts/check-codex-skills.py
```

The PowerShell script creates one directory junction per canonical skill. Both setup
scripts preserve external plugin-managed entries already present in `.agents/skills`
and fail closed when an external entry collides with a canonical skill name.

Do not copy canonical skill contents into `.agents/skills`. Canonical skill packages
remain editable only under `.ai/skills`; the overlay contains links plus external
plugin-managed packages.

## 4. Verify Codex discovery

Restart VS Code after creating the bridge if Codex was already open.

In the Codex chat:

1. run `/skills`;
2. confirm `nexus` and the domain skills are listed;
3. type `$nexus` and ask: `Summarize the active repository instructions and select
   the skills for a provider-gateway audit. Do not edit files.`

Expected behavior:

- Codex reads the root `AGENTS.md`;
- NEXUS classifies the request;
- only the provider, backend, observability, security, and testing skills needed for
  the audit are selected;
- the response begins with the NEXUS trace;
- no implementation occurs because the prompt requested analysis only.

Optional CLI verification:

```bash
codex --ask-for-approval never "Summarize the current instructions and list active instruction sources."
```

From a nested directory, verify override behavior:

```bash
codex --cd apps/web --ask-for-approval never \
  "List the active instruction files and summarize the frontend-only rules."
```

## 5. Recommended VS Code operating modes

### Chat

Use for architecture discussion, investigation, review planning, and prompts where no
file change should occur.

Example:

```text
$nexus Analyze the provider gateway for quota and schema-drift risks. Read-only.
Return P0/P1/P2 findings with file evidence and proposed tests.
```

### Agent

Use for normal repository changes. Codex may inspect, edit, and run commands inside
the workspace, while sensitive actions remain approval-gated.

Example:

```text
$nexus Fix the failing provider normalization tests. Preserve the existing gateway
architecture, add regression coverage, run the targeted backend suite, and show the
final diff summary. Do not commit or push.
```

### Agent (Full Access)

Use only for a trusted repository and a task that genuinely requires unrestricted
network or filesystem access. Review commands and diffs carefully. It should not be
the everyday default.

## 6. How to invoke skills

### Preferred: explicit NEXUS orchestration

Start complex work with `$nexus`:

```text
$nexus Thoroughly audit the /intelligence frontend for accessibility, hydration,
bundle, and contract issues. Implement only evidence-backed fixes and run the
relevant checks.
```

NEXUS should choose a minimal graph such as:

```text
frontend-product-design-architect
→ accessibility-system-architect
→ nextjs-performance-architect
→ component-quality-gate
→ testing-strategy-architect
```

### Explicit specialist invocation

Use a specific skill when the task is already narrow:

```text
$security-hardening-auditor Review only the changed authentication middleware.
Do not modify files; return exploitable issues first.
```

### Implicit activation

Codex can match skills from their `description`, but explicit `$nexus` is preferred
for cross-cutting work because it makes routing and ordering visible.

## 7. Prompt patterns

### Read-only audit

```text
$nexus Inspect the current branch and audit the SabiScore prediction path from
provider evidence to frontend display. Do not edit. Cite exact files and tests,
separate confirmed defects from stale documentation, and prioritize P0–P3.
```

### Surgical implementation

```text
$nexus Implement the smallest production-safe fix for <problem>. Preserve public
contracts and unrelated changes. Add regression tests, run targeted checks first,
then broader checks that are available. Do not commit or push.
```

### Release certification

```text
$nexus Certify the current exact HEAD. Inspect Git status, run the canonical release
gates without suppressions, document unrun gates and blockers, and return exactly
one release decision: PRODUCTION READY, READY WITH DOCUMENTED LIMITATIONS, or NOT
SAFE FOR PRODUCTION. Do not deploy or merge.
```

### Skill creation

```text
$elite-skill-forge Create a Codex-compatible skill for <domain>. Include precise
trigger boundaries, SKILL.md frontmatter, optional references/scripts, and a
validation checklist. Do not modify NEXUS until the skill passes review.
```

## 8. Adding or updating a skill

1. Create or edit `.ai/skills/<skill-name>/SKILL.md`.
2. Include valid frontmatter:

```yaml
---
name: skill-name
description: State exactly when this skill should and should not trigger.
---
```

3. Keep the description concise and front-load trigger terms.
4. Put large reference material in `references/` and reusable automation in
   `scripts/` within the skill folder.
5. Run:

```bash
python scripts/check-codex-skills.py
```

6. Update `NEXUS.md` only when routing, conflict priority, or the registry changes.
7. Restart Codex if the skill does not appear automatically.

## 9. Maintaining Claude and Codex together

- `CLAUDE.md`: Claude Code-specific control surface.
- `AGENTS.md`: Codex instruction surface.
- `.ai/skills`: shared canonical skill packages.
- `.claude/skills`: Claude slash-command wrappers, where needed.
- `.agents/skills`: Codex discovery bridge.
- `NEXUS.md`: shared routing registry.

Stable business and safety contracts should remain semantically aligned across
`CLAUDE.md` and `AGENTS.md`. Tool-specific commands and discovery behavior should not
be copied blindly between them.

## 10. Troubleshooting

### Skills do not appear

- confirm the workspace is opened at the Git repository root;
- run `python scripts/check-codex-skills.py`;
- inspect `.agents/skills` and confirm every canonical entry resolves to the matching
  `.ai/skills/<name>` directory;
- ensure every skill has `SKILL.md` with `name` and `description` frontmatter;
- restart VS Code/Codex;
- check for duplicate skill names.

### Root instructions are ignored

- confirm the file is named exactly `AGENTS.md`;
- open the repository root rather than a disconnected subfolder;
- ask Codex to list active instruction sources;
- inspect for a closer `AGENTS.override.md` that intentionally replaces local rules.

### Codex edits too broadly

- use Chat mode for investigation;
- narrow the prompt to explicit directories and acceptance criteria;
- request targeted tests before the full release gate;
- improve the nearest nested `AGENTS.md` or specialist skill when the same mistake
  repeats.

### Windows link problems

Use the PowerShell junction script or work inside WSL2. Avoid manually duplicating
all skills as a workaround.
