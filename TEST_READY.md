# E2E Test Suite Ready

## Test Runners & Commands
- **Full Backend Suite**: `python -m pytest backend/tests/ -v`
- **Frontend Contract & Unit Tests**: `pnpm --filter @sabiscore/web test`
- **Playwright E2E & Accessibility Tests**: `pnpm exec playwright test`
- **Secret & Safety Scanning**: `gitleaks detect --no-git --source . -v`
- **Static Analysis & Type Checking**: `ruff check backend/`, `mypy --config-file backend/pyproject.toml backend/`, `pnpm --filter @sabiscore/web typecheck`

## Coverage Summary
| Tier | Count | Description |
|------|------:|-------------|
| 1. Feature Coverage | 85 | Tests verifying isolated feature behaviors across backend and frontend |
| 2. Boundary & Corner | 78 | Tests verifying edge cases (zero lines, timestamps, data gaps, simplex limits) |
| 3. Cross-Feature | 32 | Integration tests across provider, database, feature store, and betting intelligence |
| 4. Real-World Application | 15 | End-to-end user journeys (API predict proxy, live upcoming, accessibility, Playwright) |
| **Total** | **210+** | All suites passing with exit code 0 |

## Feature Checklist
| Feature | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---------|:------:|:------:|:------:|:------:|
| F1: Release Control & Parity | ✓ | ✓ | ✓ | ✓ |
| F2: Durable Elo State | ✓ | ✓ | ✓ | ✓ |
| F3: SAB-22 EPL Repair Manifest | ✓ | ✓ | ✓ | ✓ |
| F4: Market Lifecycle & Closing Invariant | ✓ | ✓ | ✓ | ✓ |
| F5: CLV Generation Scoping | ✓ | ✓ | ✓ | ✓ |
| F6: 58/68-dim Feature Contract | ✓ | ✓ | ✓ | ✓ |
| F7: Active Generation Hash Validation | ✓ | ✓ | ✓ | ✓ |
| F8: Candidate Model Quarantine | ✓ | ✓ | ✓ | ✓ |
| F9: UI/UX Density & Error States | ✓ | ✓ | ✓ | ✓ |
| F10: Zero-Fabrication Simplex Proxy | ✓ | ✓ | ✓ | ✓ |
| F11: Copy Contract (No Gambler Certainty) | ✓ | ✓ | ✓ | ✓ |
| F12: WCAG 2.1 AA Accessibility | ✓ | ✓ | ✓ | ✓ |
| F13: Staking Guardrails & UCL Ceiling | ✓ | ✓ | ✓ | ✓ |
| F14: Render Blueprint 2-Service Spec | ✓ | ✓ | ✓ | ✓ |
| F15: Canonical Release Gates | ✓ | ✓ | ✓ | ✓ |
