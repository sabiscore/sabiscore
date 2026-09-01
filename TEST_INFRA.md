# SabiScore E2E Test Infrastructure & Specification

## 1. Test Philosophy & Core Principles

SabiScore's End-to-End (E2E) testing framework provides requirement-driven, opaque-box verification across the entire product surface. All tests adhere to the following principles:

1. **Requirement-Driven & Opaque-Box**: Tests validate externally observable behaviors, user interactions, and interface contracts specified in `PROJECT.md` and `ORIGINAL_REQUEST.md`. No test depends on internal implementation private details.
2. **Zero-Fabrication & Fail-Closed Assertions**: In line with ADR 0009 and SabiScore core invariants, tests strictly enforce that missing, stale, or conflicting data results in fail-closed states (`PARTIAL`, `HOLD`, `No bet`, `—` placeholders), and never synthetic probabilities, simulated accuracy, or fake consensus.
3. **Anti-Casino Terminology Compliance**: All user-facing surfaces and shared snippets are continuously scanned for prohibited gambling phrasing (`lock`, `banker`, `sure bet`, `free money`, `guaranteed`).
4. **Progressive Testability & Isolation**: Every test is self-contained, sets up its own deterministic state/mock routes, avoids inter-test coupling, and runs reliably in CI and local environments.
5. **Full Platform & Device Parity**: Tests run across desktop (`chromium`) and mobile (`mobile-chrome` / Pixel 5 emulation) viewports with strict WCAG AA accessibility validation.

---

## 2. 4-Tier Test Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│              Tier 4: Real-World Application Scenarios                    │
│      - 5 Complete Multi-Step End-to-End User & Developer Journeys        │
└────────────────────────────────────┬─────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼─────────────────────────────────────┐
│              Tier 3: Cross-Feature Pairwise Combinations                 │
│      - 10+ Cross-Domain State Cascades & Feature Boundary Handshakes     │
└────────────────────────────────────┬─────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼─────────────────────────────────────┐
│              Tier 2: Boundary & Corner Cases                             │
│      - >=5 Edge Tests per Feature (65+ tests): Empty, Malformed, Extreme │
└────────────────────────────────────┬─────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼─────────────────────────────────────┐
│              Tier 1: Feature Coverage (Isolated)                         │
│      - >=5 Tests per Feature (65+ tests): Primary Contracts & Shapes     │
└──────────────────────────────────────────────────────────────────────────┘
```

### Tier 1: Feature Coverage (Isolated)
- **Scope**: Covers all 13 features in `PROJECT.md` Feature Inventory in isolation.
- **Requirement**: >= 5 isolated test cases per feature (65+ test cases total).
- **Target**: Verifies primary contract shapes, API schemas, UI elements, and operational invariants for each feature independently.

### Tier 2: Boundary & Corner Cases
- **Scope**: Stress tests all 13 features under extreme, invalid, or degraded conditions.
- **Requirement**: >= 5 boundary test cases per feature (65+ test cases total).
- **Target**: Malformed payloads, 429 rate limit backoff, zero-variance inputs, SQLi/XSS prevention, 100% data gaps, conflicting odds snapshots, staleness timeouts, and extreme zoom/contrast.

### Tier 3: Cross-Feature Combinations
- **Scope**: Validates pairwise interactions and state transitions across subsystem boundaries.
- **Key Suites**:
  - `Anon Browsing + Registration Favorites Migration`
  - `Developer API Key Creation + Rate Limiting + Quota Usage Metering`
  - `Timezone Preferences + Match Notifications & Probability Delta Alerts`
  - `Match Analysis + Dynamic OG Share Card + Analytical Clipboard Export`
  - `Anonymous Navigation + Typed Analytics Batching + Credential Sanitization`
  - `Public Trust Calibration Reliability Curves + Fail-Closed Gating`
  - `Ingestion Provider Outage + Critical Gap Gating + Match Verdict Fallback`
  - `Programmatic SEO Dynamic Sitemap + Match Detail Routing + Schema.org JSON-LD`
  - `Consumer Team Favoriting + Proactive Next Fixture Alert Subscription`
  - `Multi-Surface Anti-Casino Terminology + WCAG AA Landmark Validation`

### Tier 4: Real-World Application Scenarios
- **Scope**: Complete, multi-step user and developer lifecycle journeys.
- **Journeys**:
  - `Journey 1`: Consumer Discovery to Social Advocate (Browse → Filter → Analyze → Save Match → Register → Verify Dashboard → Share Analysis).
  - `Journey 2`: Developer Onboarding & API Consumption Lifecycle (Explore Portal → Generate Key → Make Predictions → Hit 10 req/min Limit → Revoke Key).
  - `Journey 3`: Public Trust Audit & Timezone Notification Subscription (Explore `/performance` → Brier Decomposition → Timezone Adjustment → Subscribe & Receive Alert).
  - `Journey 4`: Off-Season & Low-Evidence Graceful Degradation (Select Off-season League → Match with Missing Lineups → PARTIAL / No Bet → Safe Share Card).
  - `Journey 5`: Multi-Device Anonymous Migration & Session Lifecycle (Device A Anonymous Favorites → Register → Device B Login → State Synchronization → Logout).

---

## 3. Feature Inventory & Coverage Mapping

| Feature # | Feature Name | Tier 1 (Isolated) | Tier 2 (Boundaries) | Tier 3 (Combinations) | Tier 4 (Journeys) | Spec Reference |
|---|---|---|---|---|---|---|
| **F1** | Unified Provider Ingestion | >=5 tests | >=5 tests | Suite 3.7 | Journey 2, 4 | `PROJECT.md` #1, R1 |
| **F2** | Candidate Model Shadow Validation | >=5 tests | >=5 tests | Suite 3.6 | Journey 3 | `PROJECT.md` #2, R1 |
| **F3** | Enterprise Schema Lineage (Alembic 0011) | >=5 tests | >=5 tests | Suite 3.1, 3.2 | Journey 1, 5 | `PROJECT.md` #3, R1/R2/R4 |
| **F4** | Anonymous-First User Identity & Auth | >=5 tests | >=5 tests | Suite 3.1, 3.5 | Journey 1, 5 | `PROJECT.md` #4, R2 |
| **F5** | Consumer Personalization & Dashboard | >=5 tests | >=5 tests | Suite 3.1, 3.9 | Journey 1, 5 | `PROJECT.md` #5, R2 |
| **F6** | Public Trust & Interactive Calibration | >=5 tests | >=5 tests | Suite 3.6 | Journey 3 | `PROJECT.md` #6, R2 |
| **F7** | Developer Platform & Entitlements | >=5 tests | >=5 tests | Suite 3.2 | Journey 2 | `PROJECT.md` #7, R4 |
| **F8** | First-Party Privacy Analytics | >=5 tests | >=5 tests | Suite 3.5 | Journey 1 | `PROJECT.md` #8, R2 |
| **F9** | Timezone-Aware Match Notifications | >=5 tests | >=5 tests | Suite 3.3, 3.9 | Journey 3 | `PROJECT.md` #9, R3 |
| **F10** | Dynamic Social Share & Viral Loop | >=5 tests | >=5 tests | Suite 3.4 | Journey 1, 4 | `PROJECT.md` #10, R3 |
| **F11** | Programmatic SEO & Structured Data | >=5 tests | >=5 tests | Suite 3.8 | Journey 1 | `PROJECT.md` #11, R3 |
| **F12** | Anti-Casino Polish & WCAG AA A11y | >=5 tests | >=5 tests | Suite 3.10 | Journey 1, 4 | `PROJECT.md` #12, R3/R5 |
| **F13** | Fail-Closed UX & Empty State Guards | >=5 tests | >=5 tests | Suite 3.7 | Journey 4 | `PROJECT.md` #13, R5 |

---

## 4. Test Suite File Structure

```text
tests/e2e/
├── helpers/
│   └── e2e-fixtures.ts                    # Shared types, mock factories, route helpers
├── tier1-feature-coverage.spec.ts         # Tier 1: 65+ Isolated feature tests across 13 features
├── tier2-boundary-corner-cases.spec.ts    # Tier 2: 65+ Boundary and edge case tests
├── tier3-cross-feature-combinations.spec.ts # Tier 3: 10+ Pairwise cross-feature combination suites
├── tier4-application-scenarios.spec.ts    # Tier 4: 5 Real-world end-to-end user journeys
├── accessibility.spec.ts                  # Automated axe-core WCAG AA audit
├── container-parity.spec.ts               # Layout container and shell parity tests
├── full-analysis-decisions.spec.ts        # Match analysis decision integrity tests
├── intelligence.spec.ts                   # Intelligence workspace chrome smoke tests
└── sabiscore.spec.ts                      # Baseline web workflow and proxy tests
```

---

## 5. Test Runner Commands

### Full E2E Suite Execution
```bash
# Run all E2E test suites (all tiers across desktop and mobile)
pnpm test:e2e

# Run with Playwright UI for interactive debugging
npx playwright test --ui

# Run in headed mode
npx playwright test --headed
```

### Running Specific Tiers
```bash
# Tier 1: Feature Coverage
pnpm test:e2e:tier1
# or: npx playwright test tests/e2e/tier1-feature-coverage.spec.ts

# Tier 2: Boundary & Corner Cases
pnpm test:e2e:tier2
# or: npx playwright test tests/e2e/tier2-boundary-corner-cases.spec.ts

# Tier 3: Cross-Feature Combinations
pnpm test:e2e:tier3
# or: npx playwright test tests/e2e/tier3-cross-feature-combinations.spec.ts

# Tier 4: Real-World Application Scenarios
pnpm test:e2e:tier4
# or: npx playwright test tests/e2e/tier4-application-scenarios.spec.ts
```

### Targeted Feature & Project Execution
```bash
# Run only on Desktop Chromium
npx playwright test --project=chromium

# Run only on Mobile Chrome (Pixel 5)
npx playwright test --project=mobile-chrome

# Filter by feature or test name
npx playwright test -g "Feature 6: Public Trust"
npx playwright test -g "Journey 2: Developer Onboard"
```

---

## 6. Coverage Thresholds & Quality Gates

- **Feature Completeness**: 100% of features in `PROJECT.md` have >=5 Tier 1 tests and >=5 Tier 2 tests.
- **Fail-Closed Verification**: Zero unverified mock fallbacks permitted in production paths.
- **Accessibility Standards**: Zero automatically detectable WCAG 2.1 Level A / AA violations via `axe-core`.
- **Security & Privacy**: Zero raw JWT/secret tokens stored in `localStorage`; 100% PII/credential sanitization on analytics payloads.
- **Terminology Invariant**: 0 occurrences of prohibited gambling terms across all user-facing copy and export payloads.
