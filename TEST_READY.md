# TEST_READY — SabiScore E2E Test Suite Specification & Readiness Report

## Status: READY

The Requirement-Driven Opaque-Box E2E Test Suite for SabiScore has been established in accordance with `PROJECT.md`, `ORIGINAL_REQUEST.md`, `AGENTS.md`, and `NEXUS.md`.

---

## 1. Test Suite Architecture & Summary

The E2E test track implements the full **4-Tier Methodology** covering all 13 features in the `PROJECT.md` Feature Inventory with zero-fabrication and fail-closed invariants:

| Tier | Test Suite File | Features Covered | Test Cases (per target) | Total Runs (Multi-Device) |
|---|---|---|---|---|
| **Tier 1: Feature Coverage** | `tests/e2e/tier1-feature-coverage.spec.ts` | Features 1–13 (Isolated) | 65 tests | 130 tests |
| **Tier 2: Boundaries & Corners** | `tests/e2e/tier2-boundary-corner-cases.spec.ts` | Features 1–13 (Stress & Edges) | 65 tests | 130 tests |
| **Tier 3: Pairwise Combinations** | `tests/e2e/tier3-cross-feature-combinations.spec.ts` | Cross-Subsystem Cascades | 10 suites | 20 tests |
| **Tier 4: Real-World Scenarios** | `tests/e2e/tier4-application-scenarios.spec.ts` | Complete User & Dev Journeys | 5 journeys | 10 tests |
| **Baseline Smoke & A11y Specs** | `tests/e2e/{accessibility,container-parity,full-analysis-decisions,intelligence,sabiscore}.spec.ts` | Web shell, a11y, layout parity | 19 specs | 38 tests |
| **TOTAL** | **9 Spec Files** | **All 13 Features** | **164 Unique Tests** | **328 Total Executions** |

---

## 2. Feature Inventory Coverage Matrix

| Feature # | Feature Name | Tier 1 (Isolated) | Tier 2 (Boundaries) | Tier 3 (Cross-Domain) | Tier 4 (Journeys) | Status |
|---|---|---|---|---|---|---|
| **F1** | Unified Provider Ingestion | 5 tests | 5 tests | Suite 3.7 | Journey 2, 4 | **COVERED** |
| **F2** | Candidate Model Shadow Validation | 5 tests | 5 tests | Suite 3.6 | Journey 3 | **COVERED** |
| **F3** | Enterprise Schema Lineage (Alembic 0011) | 5 tests | 5 tests | Suite 3.1, 3.2 | Journey 1, 5 | **COVERED** |
| **F4** | Anonymous-First User Identity & Auth | 5 tests | 5 tests | Suite 3.1, 3.5 | Journey 1, 5 | **COVERED** |
| **F5** | Consumer Personalization & Dashboard | 5 tests | 5 tests | Suite 3.1, 3.9 | Journey 1, 5 | **COVERED** |
| **F6** | Public Trust & Interactive Calibration | 5 tests | 5 tests | Suite 3.6 | Journey 3 | **COVERED** |
| **F7** | Developer Platform & Entitlements | 5 tests | 5 tests | Suite 3.2 | Journey 2 | **COVERED** |
| **F8** | First-Party Privacy Analytics | 5 tests | 5 tests | Suite 3.5 | Journey 1 | **COVERED** |
| **F9** | Timezone-Aware Match Notifications | 5 tests | 5 tests | Suite 3.3, 3.9 | Journey 3 | **COVERED** |
| **F10** | Dynamic Social Share & Viral Loop | 5 tests | 5 tests | Suite 3.4 | Journey 1, 4 | **COVERED** |
| **F11** | Programmatic SEO & Structured Data | 5 tests | 5 tests | Suite 3.8 | Journey 1 | **COVERED** |
| **F12** | Anti-Casino Polish & WCAG AA A11y | 5 tests | 5 tests | Suite 3.10 | Journey 1, 4 | **COVERED** |
| **F13** | Fail-Closed UX & Empty State Guards | 5 tests | 5 tests | Suite 3.7 | Journey 4 | **COVERED** |

---

## 3. How to Run the Test Suite

### Running All Tests
```bash
# Execute the full multi-tier suite (Desktop Chromium & Mobile Chrome)
pnpm test:e2e

# Interactive UI Mode
npx playwright test --ui
```

### Running Individual Tiers
```bash
# Run Tier 1 (Isolated Feature Coverage)
pnpm test:e2e:tier1

# Run Tier 2 (Boundary & Corner Cases)
pnpm test:e2e:tier2

# Run Tier 3 (Cross-Feature Combinations)
pnpm test:e2e:tier3

# Run Tier 4 (Real-World Application Scenarios)
pnpm test:e2e:tier4
```

### Filter by Device or Feature
```bash
# Run on Desktop Chromium only
npx playwright test --project=chromium

# Run on Mobile Chrome (Pixel 5 emulation)
npx playwright test --project=mobile-chrome

# Run specific feature tests
npx playwright test -g "Feature 7: Developer Platform"
npx playwright test -g "Journey 1: Consumer Discovery"
```

---

## 4. Documentation & Verification Assets
- Infrastructure & Philosophy: `TEST_INFRA.md`
- Test Fixtures & Shared Helpers: `tests/e2e/helpers/e2e-fixtures.ts`
- Playwright Configuration: `playwright.config.ts`
