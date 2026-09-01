# SabiScore Production Readiness — Verification Report

**Generated:** 2026-09-01
**Branch:** `chore/production-readiness-verification-20260831`
**Scope:** Documentation reconciliation for the M8-M13 identity, notification,
analytics, and developer-platform surfaces, plus every release gate that could
be executed locally in this session.

This supersedes the prior draft of this file, which predated the unstaged
frontend/API work in the branch, mislabeled several runnable checks as
unavailable, and cited stale route/test counts. Every result below was
produced by a command actually run in this session; nothing here is copied
forward from an earlier report or inferred from source alone.

---

## 1. Web

| Command | Result |
| --- | --- |
| `pnpm --filter @sabiscore/web lint` | Exit 0, 0 warnings |
| `pnpm --filter @sabiscore/web typecheck` | Exit 0 |
| `pnpm --filter @sabiscore/web test` | **51 test files / 295 tests passed** |
| `NODE_ENV=production pnpm --filter @sabiscore/web build` | Exit 0, 49/49 pages |

## 2. Backend

Run through the repository `.venv` (`Python 3.14.6`) with an isolated
fail-closed test configuration (`APP_ENV=test`, `ALLOW_SQLITE_FALLBACK=true`,
a scratch SQLite database, `PROVIDER_LIVE_TESTS=false`).

| Command | Result |
| --- | --- |
| `ruff check src` | All checks passed |
| `scripts/check_mypy_ceiling.py --ceiling 784` | 768 <= 784 (satisfied; ceiling not raised) |
| `scripts/verify_openapi.py` | 106 paths verified |
| `scripts/verify_active_artifacts.py` | 6/6 hash-locked artifact pairs verified for `v5_phase7-20260808` (`UNVERIFIED` certification, correctly fail-closed) |
| `python -m pytest tests -q` | **2050 passed, 17 skipped, 2 xfailed** |

The 2 xfails are the pre-existing, intentionally marked `error_association`
reversal (documented certification research; unrelated to this session's
changes and not a regression).

## 3. Scraper

| Command | Result |
| --- | --- |
| `pnpm --filter @sabiscore/scraper validate` | `{"ok": true}` |
| `pnpm --filter @sabiscore/scraper test` | **20/20 passed** |

## 4. Secrets

`gitleaks detect --redact --verbose` (working tree + full git history, 478
commits, ~29.4 MB scanned): exactly the two pre-existing historical
`.env.example` fingerprints already tracked in `docs/DEBT.md` item 16
(commits `d604c13`, `67ed0ab`). Zero new findings in this session's changes.

## 5. End-to-end (Playwright)

| Command | Result |
| --- | --- |
| `pnpm exec playwright test --project=chromium --project=mobile-chrome` | **328 passed, 0 failed** (3.2 minutes) |

This is a full, real execution of all 164 unique tests across both projects
(328 total), not a `--list` discovery count. Getting to green required three
categories of fix, recorded in full in `CHANGELOG.md`:

1. One real production defect (`/team/[slug]` crashed on every request due to
   a relative-URL fetch from a Node-runtime server component) — fixed by
   extracting a server-only fetch module, mirroring the established pattern
   already used for the match-analysis insights panel.
2. One zero-fabrication defect (the match Open Graph image route accepted
   query-supplied probabilities/verdicts and an unconditional "verified"
   claim) — fixed by rendering only fixture identity and neutral copy.
3. Test-harness/assertion defects (an unseeded consent/age-gate modal
   blocking unrelated product-flow tests; two specs asserting against
   optional/absent DOM elements or a fixture payload that failed the
   frontend's own Zod contract) — fixed in the test files, not the
   application.

## 6. Not run this session

| Check | Reason |
| --- | --- |
| Docker Compose config validation / image builds | Skipped by operator choice this session |
| Alembic upgrade/check against a live PostgreSQL instance | No PostgreSQL server reachable in this environment; the isolated SQLite path was used for pytest instead, per this repository's established convention for local verification without a database server |
| Live provider/deployment smoke (`/health`, `/health/ready`, a real fixture full-analysis flow) | No deployment performed in this session; this report covers repository-state verification only |

## 7. Release decision

**READY WITH DOCUMENTED LIMITATIONS.**

Every gate that can run without a live PostgreSQL instance, a Docker daemon,
or an actual deployment passes, including the full 328-test browser suite and
the complete backend test suite. The remaining limitations are infrastructure
gaps in this local environment, not known code defects:

1. Alembic migration `0011_user_identity_dev_platform` must still be applied
   and checked against a real PostgreSQL instance before this branch is
   deployed — its revision id is deliberately kept within Alembic's 32-
   character `version_num` column limit (see `CHANGELOG.md`), but that
   constraint is unenforced by SQLite and was not exercised here.
2. Docker image builds and Compose validation remain unverified this session.
3. No live deployment or production health probe was performed; SHA parity
   and a real fixture's full-analysis flow must be confirmed after deploy,
   per `docs/DEPLOYMENT_GUIDE.md`.
