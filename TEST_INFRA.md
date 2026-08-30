# E2E Test Infra: SabiScore APEX Platform

## Test Philosophy
- Opaque-box, requirement-driven. Derived from `ORIGINAL_REQUEST.md`, `SabiScore APEX Directive`, and `NEXUS.md`.
- No dependency on internal implementation shortcuts; exercises API routes, contracts, and frontend proxy behaviour as an end user would.
- Methodology: Category-Partition + Boundary Value Analysis (BVA) + Pairwise Combinatorial Testing + Real-World Workload Testing.

## Feature Inventory Coverage
| # | Feature | Requirement Source | Tier 1 (Coverage) | Tier 2 (Boundaries) | Tier 3 (Cross-Feature) | Tier 4 (Workloads) |
|---|---------|-------------------|:-----------------:|:-------------------:|:---------------------:|:------------------:|
| 1 | Release Control & Parity | APEX §4 | 5 | 5 | ✓ | ✓ |
| 2 | Elo State & Recovery | APEX §5 | 5 | 5 | ✓ | ✓ |
| 3 | SAB-22 Identity & Repair Manifest | APEX §3, §5.2 | 5 | 5 | ✓ | ✓ |
| 4 | Market Lifecycle & Invariants | APEX §6 | 5 | 5 | ✓ | ✓ |
| 5 | CLV Evidence & Settlement Gate | APEX §6 | 5 | 5 | ✓ | ✓ |
| 6 | Feature Registry (58/68-dim) | APEX §7 | 5 | 5 | ✓ | ✓ |
| 7 | Active Generation Hash Guard | APEX §8 | 5 | 5 | ✓ | ✓ |
| 8 | Candidate Quarantine & Policy | APEX §9 | 5 | 5 | ✓ | ✓ |
| 9 | UI/UX Density & Error States | APEX §11, §14 | 5 | 5 | ✓ | ✓ |
| 10 | Zero-Fabrication Proxy Rules | APEX §12 | 5 | 5 | ✓ | ✓ |
| 11 | Prohibited Copy Contract | APEX §11 | 5 | 5 | ✓ | ✓ |
| 12 | WCAG 2.1 AA Accessibility | APEX §15 | 5 | 5 | ✓ | ✓ |
| 13 | Dual Engine Staking & UCL Cap | NEXUS / AGENTS | 5 | 5 | ✓ | ✓ |
| 14 | Render Blueprint (2 Services) | APEX §4.1 | 5 | 5 | ✓ | ✓ |
| 15 | Canonical Release Gates | APEX §21, §22 | 5 | 5 | ✓ | ✓ |

## Test Architecture
- **Backend Test Runner**: `pytest` (invoked via `python -m pytest backend/tests/ -v`)
- **Frontend Test Runner**: `vitest` (invoked via `pnpm --filter @sabiscore/web test`)
- **E2E / Browser Runner**: `playwright` (invoked via `pnpm exec playwright test`)
- **Security & Secret Scanner**: `gitleaks` (invoked via `gitleaks detect --no-git --source . -v`)
- **Linter & Typecheckers**: `ruff check`, `ruff format --check`, `mypy`, `pnpm --filter @sabiscore/web typecheck`

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Full Match Prediction & Simplex Verification | F6, F7, F9, F10, F13 | High |
| 2 | Market Closing Line Capture & CLV Generation Join | F4, F5, F7 | High |
| 3 | Team Identity Resolution Cascade & Historical Replay Safety | F2, F3 | High |
| 4 | Degraded Provider / Missing Evidence Fail-Closed Handling | F2, F9, F10 | Medium |
| 5 | Accessible UI Navigation & Copy Compliance Under Load | F9, F11, F12 | Medium |

## Coverage Thresholds
- Tier 1: ≥5 per feature (≥75 tests)
- Tier 2: ≥5 per feature (≥75 tests)
- Tier 3: Pairwise coverage across major system boundaries (≥15 interaction suites)
- Tier 4: ≥5 realistic end-to-end workload scenarios
- Total verified tests across backend, frontend, and e2e suites: >200 passing tests.
