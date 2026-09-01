# Repository Baseline

Captured from branch `chore/production-readiness-verification-20260831` on
2026-09-01 before the documentation/release commit.

## Source state

- Branch started nine commits ahead of local `master` at `a1141c1`.
- Existing tracked and untracked M8-M13 application/test work was preserved.
- Agent, skill, hook, and editor customization files are excluded from this
  release by request.

## Measured inventory

| Surface | Count | Command basis |
| --- | ---: | --- |
| FastAPI operation decorators | 97 | `rg` over `backend/src/api` |
| Next API route-handler files | 94 | PowerShell file enumeration |
| Next page files | 11 | PowerShell file enumeration |
| Web unit-test files | 50 | PowerShell file enumeration |
| Alembic 0011 tables | 7 | `op.create_table` count |
| Playwright tests | 164 unique / 328 project executions | `pnpm exec playwright test --list` |
| Tier 1-4 subset | 145 unique / 290 project executions | scoped Playwright `--list` |

## Focused verification completed

- Web lint: pass.
- Web typecheck: pass.
- Focused web tests: 9 passed, then OpenGraph contract test: 1 passed.
- Focused backend M8-M13 tests: 22 passed.
- OpenAPI verification: blocked by local production-mode/SQLite settings; the
  fail-closed configuration rejected that invalid combination before app import.

Counts above describe the inspected working tree, not production deployment.
The final release report supersedes this baseline with post-edit results.