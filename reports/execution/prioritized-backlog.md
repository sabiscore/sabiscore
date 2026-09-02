# Prioritized Backlog

Verified against the working tree on 2026-09-01.

| Priority | Item | State | Exit evidence |
| --- | --- | --- | --- |
| P0 | PostgreSQL migration 0011 validation | Pending | Fresh upgrade, downgrade/upgrade, and `alembic check` on PostgreSQL — no PostgreSQL server was reachable in this session |
| P0 | Full secret scan | **Done** | Gitleaks clean except 2 pre-existing historical fingerprints already tracked in `docs/DEBT.md` item 16; zero new findings |
| P0 | Complete backend and web gates | **Done** | Ruff 0, mypy ceiling 768<=784, pytest 2050 passed/17 skipped/2 xfailed, Vitest 295 passed, production build exit 0, OpenAPI 106 paths, artifact verifier 6/6 |
| P1 | Tier 1-4 and baseline browser suites | **Done** | 328/328 executions pass in Chromium and Mobile Chrome (2026-09-01 full run) |
| P1 | Notification delivery worker | **Done** | Scheduled kickoff-reminder + probability-swing IN_APP dispatch wired into lifespan; idempotent (log-based dedupe); 8 focused unit tests + 1 service test pass; ruff 0; mypy ceiling 766<=784 |
| P1 | Live fixture sitemap discovery | Not implemented | Canonical fixture URLs, bounded fetch/cache policy, fail-closed test |
| P1 | Production deployment proof | Pending | Render/Vercel reviewed SHA parity and smoke evidence |
| P2 | Docker image proof | Pending | Backend/web images build and Compose validates — skipped this session |
| P2 | Full WCAG browser audit | **Done** | `accessibility.spec.ts` (axe-core) and keyboard-navigation Tier 1/2 cases pass |
| Blocked | Model certification and public staking | Gate closed | Existing policy passes on sufficient real evidence; no threshold relaxation |
| Deferred | Billing, paywalls, automated bet execution | Prohibited | Remain absent |

Implemented work is not repeated as backlog. Auth/user state, dashboard,
calibration UI, developer portal, analytics client/API, notification CRUD/in-app
UI, share UI, evidence-safe OG route, sitemap baseline, and JSON-LD are in the
working tree and have now passed their focused unit, lint, typecheck, build,
and full E2E gates; production deployment verification is the remaining step.