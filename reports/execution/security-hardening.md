# Security Hardening Evidence

Verified against the working tree on 2026-09-01.

## Implemented controls

- Per-request CSP nonce with `strict-dynamic`; production CSP does not permit
  `unsafe-eval`.
- Provider and application secrets remain server-side; no provider credential
  uses a `NEXT_PUBLIC_*` name.
- Browser authentication uses `HttpOnly` session/anonymous cookies through the
  shared Next.js server proxy.
- Developer API keys are returned once and stored as SHA-256 hashes.
- Analytics properties are recursively scrubbed in both client and backend
  paths; analytics failures do not affect prediction workflows.
- Evidence and decision proxies use `Cache-Control: no-store`.
- No billing, checkout, payment integration, or automated bet execution route
  was found. User-facing copy may truthfully say that billing is absent.
- Dynamic match OG cards no longer accept query-supplied probabilities/verdicts
  or claim verified evidence without backend proof.

## Verification performed

- Web lint, typecheck, full test suite (295/295), and production build passed.
- Backend Ruff, mypy ceiling, full pytest suite (2050 passed / 17 skipped / 2
  xfailed), OpenAPI verifier, and model-artifact verifier all passed.
- Scraper registry validation and full test suite (20/20) passed.
- Gitleaks against the working tree and full git history (478 commits): zero
  new findings; only the two pre-existing historical fingerprints already
  tracked in `docs/DEBT.md` item 16.
- Full Playwright suite (328/328, Chromium + Mobile Chrome), including auth
  cookie/localStorage invariants, JWT tampering, SQL injection/XSS
  neutralization, rate limiting, and WCAG AA accessibility scenarios.

## Open gates

- Verify migration 0011 constraints and ownership behavior on a real
  PostgreSQL instance.
- Confirm developer rate limits under Redis and concurrent requests in a live
  environment (this session's rate-limit tests used the in-memory fallback).
- Validate Docker Compose and build production images.
- Perform live log/trace redaction review against a deployed instance without
  printing credentials.

Security conclusion: no new critical issue was found, and every locally
runnable gate — including the full backend/web test suites and the full
Playwright suite — passes. The release remains gated on the four open items
above, all of which require a live PostgreSQL instance, Docker, or a
deployed environment unavailable in this session.
the release remains unapproved until the open gates pass.