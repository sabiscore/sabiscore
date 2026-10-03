# SabiScore V21 Production Activation Report

Generated: 2026-10-03T09:41:56.140397+00:00
Base HEAD: 23dbd976754e3a79eacc8bb3b20dd3c0c6454d52
Branch: feat/v21.1-evidence-lock
Release Posture: ACTIVE_FAIL_CLOSED

## Five-Truth State Table

| Dimension | Measured Value | Evidenced State | Gate Verdict |
| :--- | :--- | :--- | :--- |
| **Engineering Integration** | Understat PIT xG telemetry, Alembic 0016 schema, Candidate-M purity, unified `/full-analysis` single path, zero synthetic data in production paths | LIVE-INTEGRATED | PASS |
| **Model Quality** | Candidate-M out-of-sample test set (2025/26 holdout season); active generation `v5_phase7-20260922` | UNVERIFIED / CERTIFICATION_BLOCKED | BLOCKED |
| **Market Relative Alpha** | Gate 7 benchmark comparison against opening market RPS (historical FAIL; protocol SHA `43d334cd81e7214c491c0863daa6f33dd753f50d5faf71b5b60f03cbc00e7b6c`) | EMPIRICALLY UNVALIDATED | FAIL / BLOCKED |
| **Live C6 Milestone** | Live database sample count `live_n` < 200 settled pre-kickoff predictions; zero historical replay credit | INSUFFICIENT_SAMPLE / UNVERIFIED | FAIL / BLOCKED |
| **Production Runtime Parity** | Render backend SHA `23dbd97` (200 OK), Vercel production alias `23dbd976754e3a79eacc8bb3b20dd3c0c6454d52` (200 OK) | LIVE-VERIFIED PARITY | PASS (Runtime) |

## Engineering Status

Candidate feature integration: **BLOCKED**. The active generation remains `v5_phase7-20260922` with state `ACTIVE_FAIL_CLOSED`. The 89-feature semantic contract currently has 89 feature(s) with undeclared required meaning, units, or serving source.
- Single canonical prediction route: `/api/v1/matches/upcoming/{id}/full-analysis` (legacy endpoints `/predict/match` and `/predict_live` permanently retired).
- Understat xG/xA match telemetry: Alembic migration `0016_match_telemetry_pit_provenance`, strict PIT rolling average (`kickoff < T_prediction`), and provenance hashing.
- Candidate-M / Candidate-MA separation: Candidate-M verified 100% market-independent with zero market leakage.
- Frontend truth mapping: Pure consumer-truth representation with zero client-side EV/Kelly math and zero synthetic data substitution.

## Model Quality

**NOT CERTIFIED.** No attributable V21 Candidate-M out-of-sample prediction artifact was available. Calibration and regime reports are marked not run. Incumbent model `v5_phase7-20260922` is retained in `ACTIVE_FAIL_CLOSED`.

## Market Relative Performance

**BLOCKED.** The V20 report recorded Gate 7 as `FAIL`; its aggregate values are retained as unverified historical claims. V21 paired cohort evaluation did not run, and the protocol hash is `43d334cd81e7214c491c0863daa6f33dd753f50d5faf71b5b60f03cbc00e7b6c`.

## Live C6 Certification

**UNVERIFIED CURRENT DATABASE COUNT.** The V20 report last recorded N=0; this generator did not query the production database. Historical replay contributes zero to live C6 by contract. Live threshold target: N >= 200 settled pre-kickoff predictions.

## Production Runtime Parity

- **Render Backend**: `https://sabiscore-api-bav1.onrender.com/health` returns HTTP 200 with SHA `23dbd97`, matching git HEAD.
- **Vercel Frontend**: `https://sabiscore.vercel.app/api/health` returns HTTP 200 with `vercelSha: 23dbd976754e3a79eacc8bb3b20dd3c0c6454d52`, matching git HEAD.
- **Serving Parity**: CONFIRMED between Render and Vercel.

## Production Readiness

**CERTIFICATION_BLOCKED.** Retain the incumbent in `ACTIVE_FAIL_CLOSED`. Do not activate Candidate-M until the V21 protocol evaluation passes and the registered live C6 milestone passes using persisted live observations. Current production activation: **NOT AUTHORIZED BY EVIDENCE**.
