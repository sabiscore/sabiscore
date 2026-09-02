# 🔍 Session Retrospective: Scheduled in-app notification dispatch worker

- **Date:** 2026-09-02
- **Target Branch:** `feat/notification-dispatch-worker-20260901`
- **Primary P0 Fixed:** M9's notification-subscription CRUD (merged in PR #127) had
  no generator behind it — `UserNotificationSubscription` rows were created and
  read, but nothing ever produced a `UserNotificationLog` entry. `docs/DEBT.md`
  item 51 tracked this as the gap; this branch closes it with
  `backend/src/services/notification_dispatch_service.py`.
- **Session Status:** Success — no incident, no rollback, no design deviation.

---

### 1. 🧬 Root Cause & Pattern Analysis
- **Core Defect:** A feature was shipped in two halves across PRs (#127: CRUD/UI,
  this branch: the dispatch loop that actually fires notifications) with a gap
  between them that was tracked in `docs/DEBT.md` rather than left silent.
- **Underlying Pattern:** Not a bug pattern — this repo's established convention
  (settlement sync, CLV capture, fixture sync) is exactly "background loop
  registered on the FastAPI lifespan, feature-flagged, fail-closed on
  exception, informational `/health` component." The dispatch worker follows
  that convention precisely (`_background_notification_dispatch()` mirrors
  `_background_settlement_sync`/`_background_clv_capture` in `api/main.py`).
- **Prevention Rule:** None needed for this instance — the debt item existed,
  was tracked, and was closed same-band. Worth restating for future two-PR
  feature splits: file the DEBT item at the *first* PR, not after the fact,
  so the gap is visible before someone hits it in production.

### 2. ⚡ Resource & Memory Audit (8GB RAM Constraint)
- **Local Environment Impact:** Not applicable this session — no local
  test/build runs were executed; the branch's own commits (d681518, 5f9f4b7)
  already carried their verification (targeted pytest, ruff, mypy ceiling, and
  a SonarCloud coverage fix taking `notification_dispatch_service.py` from
  64.4% to 93% new-code coverage per PR #129).
- **Bottlenecks Identified:** None surfaced.
- **Mitigation Applied:** None needed.

### 3. 📑 Tech Debt & Architectural Log
- **Debt Introduced:** None new. Two scoped, previously-documented gaps remain
  explicitly open (not silently deferred): `WEB_PUSH`/`EMAIL` channels are
  persisted but not dispatched (only `IN_APP` fires), and there is no
  re-alerting window for repeated probability swings after the first
  notification per subscription (deliberate anti-storm choice).
- **Debt Items Logged:** `docs/DEBT.md` item 51 — `RESOLVED` for the scope
  built (kickoff reminders + probability-swing alerts, `IN_APP` only); the two
  gaps above are named there as follow-up scope, not hidden.

### 4. 🛠️ Agent & Prompt Execution Feedback
- **Workflow Friction:** `.github/pull_request_template.md` was, until this
  session, the raw text of an LLM's *proposal* for how to build a PR template
  ("Step 1: Create a new file...") rather than the template itself — every PR
  opened against this repo would have inherited that meta-commentary as its
  default description. Fixed in this session by extracting just the real
  template content.
- **Prompt Refinement Note:** When a governance/template file is added via a
  pasted LLM response, verify the file contains only the artifact, not the
  response that produced it — the same class of mistake as leaving scaffolding
  comments in shipped code.
