# ADR 0007: Evidence authority and Apex artifact promotion

Status: Accepted for implementation; candidate promotion pending evidence.
Date: 2026-08-10.

## Context

External probability payloads could inherit optimistic certification metadata;
odds clients and snapshots were fragmented; missing analytical values were filled
with defaults; and generated artifacts were written over active v5 paths before a
qualifying promotion decision. The product also presented infrastructure readiness
as if it certified a prediction.

## Decision

FastAPI is the sole certification and staking authority. Caller probabilities are
external/unverified and non-executable. One injected provider registry and HTTP
client acquire one coherent request snapshot which is reused by every consumer.
Missing, stale, conflicting, malformed, or unmeasured values remain unavailable and
close the relevant gate. Projection failure skips inference.

Generated models are candidate-only until a manifest records chronological
training/evaluation windows, exact served-head metrics, per-competition baseline
comparisons, calibration and validation status, schema and library versions,
artifact hashes, and rollback identity. Promotion is an atomic manifest switch,
never an in-place overwrite.

The frontend consumes `/models/status` and full analysis. It does not infer model
quality from health, provider count, filename, or hardcoded copy.

## Consequences

- Reduced evidence produces explicit `No bet` and zero stake.
- Provider outages may leave a certified forecast visible, but absent coherent
  market evidence prevents an executable betting verdict.
- Old clients remain addressable, but unsafe legacy behavior fails closed.
- Candidate training can evolve independently from the active v5 contract.
- More states are nullable/unknown in public UI; this is intentional accuracy, not
  a degraded presentation bug.

## Verification

Authority, probability-simplex, coherent-market, redaction, dual-engine, full
analysis, model-status, contract, accessibility, and promotion-manifest tests are
release gates. Live provider quota is not consumed by default CI.
