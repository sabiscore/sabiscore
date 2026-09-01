# Production Health Evidence

Generated 2026-09-01.

No live production health probe was executed during this documentation audit.
This report therefore makes no claim about current Render/Vercel SHA parity,
database latency, Redis latency, provider circuit state, migration head, or live
model availability.

## Code-level health contract

- `/health/live` is process liveness.
- `/health/ready` reports dependency readiness and prediction capability.
- `/health` exposes release identity and component state.
- `/metrics` exposes available operational counters.
- Model certification and per-fixture staking remain separate from platform
  readiness.

## Local evidence from this audit

| Check | Result |
| --- | --- |
| Web lint | Pass |
| Web typecheck | Pass |
| Web tests | 295/295 passed |
| Web production build | Exit 0, 49/49 pages |
| Backend Ruff | 0 issues |
| Backend mypy ceiling | 768<=784 |
| Backend full pytest | 2050 passed / 17 skipped / 2 xfailed |
| OpenAPI verifier | 106 paths verified |
| Model artifact verifier | 6/6 hash-locked pairs verified |
| Scraper validate + tests | 20/20 passed |
| Gitleaks (working tree + full history) | 2 pre-existing historical findings only (`docs/DEBT.md` item 16); zero new |
| Playwright (Chromium + Mobile Chrome) | **328/328 passed** |

## Required production evidence

Before a readiness conclusion, record responses from `/health`,
`/health/ready`, `/api/v1/providers/health`, `/models/status`, and one verified
fixture full-analysis flow; compare backend and frontend release SHAs; verify
migration `0011` on PostgreSQL; and complete Docker image/Compose validation.

Current decision from this report alone: `NOT SAFE FOR PRODUCTION` — not
because any local gate failed (all passed), but because no live deployment or
production health probe has been performed against this reviewed commit.