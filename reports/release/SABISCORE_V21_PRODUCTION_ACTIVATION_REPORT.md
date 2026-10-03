# SabiScore V21 Production Activation Report

Generated: 2026-10-03T16:06:09.906283+00:00
Base HEAD: 845c3ff754efbb473930b601ebe052a4103f0d03
Branch: fix/v21.2-evidence-truth
Release Posture: ACTIVE_FAIL_CLOSED

## Five-Truth State Table

| Dimension | Measured Value | Evidenced State | Gate Verdict |
| :--- | :--- | :--- | :--- |
| **Engineering Integration** | Not measured by this generator: it reads repository files only. Merge, CI, and deployment state must be read from GitHub and the live services. | UNVERIFIED | NOT MEASURED |
| **Model Quality** | Candidate-M out-of-sample test set (2025/26 holdout season); active generation `v5_phase7-20260922` | UNVERIFIED / CERTIFICATION_BLOCKED | BLOCKED |
| **Market Relative Alpha** | Candidate-M RPS 0.2059 vs closing market 0.1975 on 2058 holdout fixtures; delta 98.33% CI [+0.0041, +0.0126] (research measurement, closing-quote cohort only). | MEASURED_RESEARCH_ONLY | FAIL |
| **Live C6 Milestone** | Live database sample count `live_n` < 200 settled pre-kickoff predictions; zero historical replay credit | INSUFFICIENT_SAMPLE / UNVERIFIED | FAIL / BLOCKED |
| **Production Runtime Parity** | Not measured by this generator: it makes no network requests. Compare `/health` `sha` (Render) and `/api/health` `sha`/`backendSha` (Vercel) against the merged master SHA. | UNVERIFIED | NOT MEASURED |

## Engineering Status

Candidate feature integration: **BLOCKED**. The active generation remains `v5_phase7-20260922` with state `ACTIVE_FAIL_CLOSED`. The 89-feature semantic contract currently has 89 feature(s) with undeclared required meaning, units, or serving source.
- Single canonical prediction route: `/api/v1/matches/upcoming/{id}/full-analysis` (the `/predict/match` endpoint is removed from this branch; whether it is gone from production depends on the deployed SHA).
- Understat xG/xA match telemetry: Alembic migration `0016_match_telem_pit`, strict PIT rolling average (`kickoff < T_prediction`), and provenance hashing.
- Candidate-M / Candidate-MA separation: `assert_candidate_m_purity()` rejects market-named columns in the Candidate-M schema at import time (a name check, not an empirical leakage test).
- Frontend truth mapping: `lib/prediction-truth.ts` maps the backend contract to display states; no client-side EV/Kelly arithmetic.

## Model Quality

**NOT CERTIFIED.** No attributable V21 Candidate-M out-of-sample prediction artifact was available. Calibration and regime reports are marked not run. Incumbent model `v5_phase7-20260922` is retained in `ACTIVE_FAIL_CLOSED`.

## Market Relative Performance

**FAIL.** Candidate-M RPS 0.2059 vs closing market 0.1975 on 2058 holdout fixtures; delta 98.33% CI [+0.0041, +0.0126] (research measurement, closing-quote cohort only). The protocol hash is `43d334cd81e7214c491c0863daa6f33dd753f50d5faf71b5b60f03cbc00e7b6c`.

## Live C6 Certification

**UNVERIFIED CURRENT DATABASE COUNT.** The V20 report last recorded N=0; this generator did not query the production database. Historical replay contributes zero to live C6 by contract. Live threshold target: N >= 200 settled pre-kickoff predictions.

## Production Runtime Parity

**NOT MEASURED.** This generator makes no network requests, so it cannot attest what production serves. Probe the live services after each merge:
- Render: `https://sabiscore-api-bav1.onrender.com/health` → `sha`
- Vercel: `https://sabiscore.vercel.app/api/health` → `sha` and `backendSha`
Parity holds only when both equal the merged master SHA (Render may legitimately lag after a web-only commit; check `git diff --name-only <sha>..HEAD -- backend/`).

## Production Readiness

**CERTIFICATION_BLOCKED.** Retain the incumbent in `ACTIVE_FAIL_CLOSED`. Do not activate Candidate-M until the V21 protocol evaluation passes and the registered live C6 milestone passes using persisted live observations. Current production activation: **NOT AUTHORIZED BY EVIDENCE**.
