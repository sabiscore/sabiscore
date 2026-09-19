# ADR-0011 — `OPERATOR_OVERRIDE_UNCERTIFIED`: staking without certification, on the record

**Status:** Accepted. **ACTIVATED 2026-09-19** —
`backend/models/active_generation.json` declares
`certification_state: OPERATOR_OVERRIDE_UNCERTIFIED`. See **Activation record**
and **Amendment 1 — circuit breaker** below. **Date:** 2026-09-19.
**Supersedes:** nothing. **Relates to:** ADR-0007 (evidence authority &
APEX promotion), ADR-0009 (uncertainty certification), `docs/DEBT.md`
items 14, 25, 42, 50, 108.

---

## Context

The serving generation `v5_phase7-20260808` is `UNVERIFIED` and
`ACTIVE_FAIL_CLOSED`. It fails four promotion gates on real, current evidence:

| Gate | Status | Measurement |
|---|---|---|
| `market_baseline` | FAIL | **0 of 6** leagues beat the de-vigged market |
| `no_league_regression` | FAIL | 3 of 6 league wins |
| `primary_metric_improvement` | FAIL | mean RPS Δ = −2.93e-10 |
| `serving_feature_availability` | FAIL | 11 schema-misaligned slots, 6 always-data-gap |

Separately, the `error_association` uncertainty gate (ADR-0009) fails **in the
wrong direction**: the model is *least* accurate where its ensemble agrees
*most*. Overall gap −0.0217; wrong-signed in all five scored leagues.

Before this ADR was written, an operator who wanted to ship anyway had exactly
two levers, and both were destructive:

1. Edit `certification_state` to `CERTIFIED`. The manifest verifier
   (`_verify_certification_claim`) would reject it without hash-verified
   passing evidence — so in practice this means also fabricating or
   force-passing that evidence.
2. Lower the thresholds in `certification_policy.py` until the gates yield a
   pass.

Both are forbidden by APEX §23 and DID §51.1. More importantly, both are
forbidden *for a reason that outlives the rule*: they destroy the measurement.
Afterwards nobody — not the next engineer, not the operator themselves six
months on, not this repository's own future sessions — can distinguish a
system that earned certification from one that was told to claim it. This
ledger already documents that failure class three times over (`/health/ready`
reporting `cache: "Connected"` with Redis absent; "zero Sentry issues" with
nothing instrumented; CI "green" while no runner ever booted).

The business need behind such a request is nonetheless real and legitimate: an
operator may rationally decide to ship an imperfect model to a limited
audience, with disclosure, while research continues.

## Decision

Introduce a **third** certification state rather than corrupting the first two:

```
UNVERIFIED  →  nothing may stake                      (default, fail-closed)
CERTIFIED   →  staking permitted, evidence-backed     (hash-verified gates all PASS)
OPERATOR_OVERRIDE_UNCERTIFIED
            →  staking permitted, evidence-FAILING, disclosed
```

The override permits staking. It does **not** confer certification, and the
distinction is enforced in code, not convention:

- `active_generation_is_certified()` returns **`False`** under an override.
  Every caller asking "is this certified?" continues to be told no.
- Callers asking the *different* question — "may this publish a stake?" — use
  the new `staking_authorization()`, which returns the basis
  (`CERTIFIED` / `OPERATOR_OVERRIDE` / `NONE`) alongside the answer.
- `certification_policy.py` is **untouched**. Thresholds are unchanged, the
  frozen policy hash is unchanged (`4e050ad0…f664`, v1.2.0), and the promotion
  gates keep reporting FAIL.
- The two `error_association` `xfail`s are **untouched**. They continue to
  print the live measurement on every run.

### The override must be attributable

`_verify_operator_override_claim` rejects a manifest whose `operator_override`
block lacks any of:

| Field | Why |
|---|---|
| `authorizing_identity` | names the person who took the decision |
| `rationale` | their reasoning, in their words |
| `authorized_at` | when |
| `acknowledged_failures` | **which gates they read and accepted anyway** |

The last is the load-bearing one. An override that does not enumerate what it
overrides is indistinguishable from one taken in ignorance, and a later reader
cannot tell whether the risk was understood or simply missed.

### The disclosure travels with the stake

A disclosure only an operator sees is not a disclosure. `staking_authorization`
is therefore attached to every fixture in the `/upcoming/matches` payload
(always present, so a missing key is distinguishable from "no override"),
surfaced top-level in `/health`, and rendered in the web UI **beside the value
/ stake signal itself** — plus in the row's `aria-label`, so it reaches screen
readers too.

## Consequences

**Accepted risks, stated plainly.** If this state is ever activated, SabiScore
will publish Kelly stake sizes derived from a model that:

- has **no demonstrated edge** over the bookmaker prices it is betting against
  (0/6 leagues), and
- carries an **inverted confidence signal** — it is least accurate precisely
  where its ensemble is most unanimous.

The second compounds the first. A model that knows it doesn't know is merely
unprofitable; a model whose confidence is anti-correlated with accuracy will
size its **largest** stakes on its **worst** predictions. No amount of
disclosure makes that safe — disclosure only makes it *honest*. This ADR
provides the honest path, not a safe one, and the distinction is the entire
point.

**No ML research progress is claimed.** The metrics above are unchanged and
remain exactly as measured. This ADR bypasses gates; it does not move them.
`docs/DEBT.md` item 50 stays open as a research blocker.

**Reversibility.** Removing the `operator_override` block, or setting the state
back to `UNVERIFIED`, restores fail-closed behaviour immediately. There is no
migration and no persisted side effect.

## Alternatives rejected

- **Flip `certification_state` to `CERTIFIED`.** Destroys the measurement;
  forbidden by APEX §23; would require fabricating evidence to pass the
  verifier.
- **Lower `certification_policy.py` thresholds.** Same objection, and worse:
  it silently re-defines what certification *means* for every future
  generation, not just this one.
- **Suppress the `error_association` xfails.** They are the only live readout
  of the blocker. ADR-0009 already records that these may go green only by
  `XPASS` — earned by a better-generalizing generation, never by editing the
  assertion.
- **Do nothing.** Leaves the operator with only the destructive levers above,
  which is how repositories end up with falsified state.

## Activation record

**Activated 2026-09-19** by operator instruction. The manifest
(`backend/models/active_generation.json`) now declares:

```json
"certification_state": "OPERATOR_OVERRIDE_UNCERTIFIED",
"operator_override": {
  "authorizing_identity": "Principal Architect - System-01",
  "rationale": "Unblocking staging/production integration for UX and load testing. ML generalization failures accepted for this phase.",
  "authorized_at": "2026-09-19T22:12:18Z",
  "acknowledged_failures": [
    "0/6 market baseline beat",
    "Inverted epistemic-uncertainty signal (negative correlation with accuracy)"
  ]
}
```

What the activation did **not** change, verified against the live loader rather
than assumed:

| Field | Value after activation |
|---|---|
| `active_generation_is_certified()` | `False` |
| `promotion_state` | `ACTIVE_FAIL_CLOSED` (untouched) |
| `certified_at` | `null` (untouched) |
| `certification_policy.py` hash | `4e050ad0…f664`, v1.2.0 (untouched) |
| `error_association` xfails | both still `xfail`, still printing the live measurement |
| Promotion gates | still reporting FAIL on all four |

`scripts/verify_active_artifacts.py` — the Render `buildCommand` gate — exits 0
against the activated manifest and prints the override state by name
(`Verified 6 hash-locked artifact pairs for v5_phase7-20260808
(OPERATOR_OVERRIDE_UNCERTIFIED)`), so the deploy log itself carries the
disclosure.

### Blast radius — exactly one surface, verified by grep not by assumption

`staking_authorization()` has exactly one production consumer:
`services/upcoming_match_service.py`, serving `GET /upcoming/matches`
(plus `/health` and the response schema, which only *report* it). Every other
staking-adjacent surface still asks the different question,
`active_generation_is_certified()`, which returns `False` under an override:

| Surface | Asks | Under the override |
|---|---|---|
| `services/upcoming_match_service.py` | `staking_authorization()` | **stakes published** |
| `api/endpoints/full_analysis.py` | `active_generation_is_certified()` | unchanged — research-only |
| `services/market_intel.py` | `active_generation_is_certified()` | unchanged — `market_intelligence: null` |
| `services/advanced_insights_service.py` | `active_generation_is_certified()` | unchanged — `research_only: true` |
| `api/endpoints/{predictions,betting_intelligence,fixtures,core_engine}.py` | `active_generation_is_certified()` | unchanged |
| `services/{analytics,prediction}.py` | `active_generation_is_certified()` | unchanged |

⚠️ **`/full-analysis` is additionally and independently blocked** by the
permanent `MODEL_UNCERTAINTY_UNAVAILABLE` critical gap (`docs/DEBT.md` item 42:
no `torch`, no trained BNN artifact), which forces `partial` and zeroes
`stake_permitted` regardless of certification state. This override does not
touch that and must not be read as having unblocked it.

⚠️ **Widening the override to another surface is a separate decision.**
Swapping an `active_generation_is_certified()` call for
`staking_authorization().permitted` anywhere above would silently extend this
Class C authorization to a surface the operator never named. If a surface needs
it, amend this ADR first.

**To deactivate:** delete the `operator_override` block and set
`certification_state` back to `"UNVERIFIED"`. Fail-closed behaviour resumes on
the next process start. There is no migration and no persisted side effect.

---

## Amendment 1 — the override circuit breaker

**Date:** 2026-09-19. **Module:** `backend/src/services/risk_guard.py`.

### Why an amendment and not a separate ADR

The breaker has no meaning outside this decision. It exists only because the
override ships a model with a known-inverted confidence signal, it runs only on
the override path, and it dies with the override. Recording it anywhere else
would separate the risk from its mitigation.

### The one thing the original decision left on the table

The "Accepted risks" section above states the compounding failure precisely: a
model whose confidence is anti-correlated with accuracy *sizes its largest
stakes on its worst predictions*, and disclosure makes that honest rather than
safe.

That framing treated the inversion as diffuse. It is not. Measuring it per
fixture shows the damage concentrated in an identifiable, **computable-at-
serving-time** region — the low-epistemic quartile, where the 300 bootstrap
trees agree most:

| league | n | p25 epistemic | hit-rate inside | hit-rate outside | delta |
|---|---|---|---|---|---|
| EPL | 375 | 0.0788 | 0.4362 | 0.5089 | **−7.3pp** |
| BUNDESLIGA | 296 | 0.0879 | 0.3378 | 0.4910 | **−15.3pp** |
| LIGUE_1 | 306 | 0.0859 | 0.4416 | 0.5066 | **−6.5pp** |
| LA_LIGA | 380 | 0.0776 | 0.4632 | 0.4702 | −0.7pp (flat) |
| SERIE_A | 375 | 0.0848 | 0.5106 | 0.4555 | **+5.5pp (reversed)** |

Measured on generation `v5_phase7-20260808`, each league's own artifact against
its own chronological holdout season — the same rows
`tests/unit/test_uncertainty_contract.py` scores. Reproduce with
`backend/scripts/measure_epistemic_danger_zone.py`.

⚠️ **The effect is not universal, and this ADR does not claim it is.** It is
strong in EPL, BUNDESLIGA and LIGUE_1, absent in LA_LIGA, and runs the *other
way* in SERIE_A. Anyone reading these thresholds later should read them as five
separate measurements, not as one finding with five confirmations.

### Decision

Suppress staking inside the measured danger zone, on the override path only.

```
epistemic <= per-league p25   →   trip   →   stake_permitted = False
```

⚠️ **DIRECTION IS THE WHOLE PROPERTY.** "High tree agreement" and "high
epistemic uncertainty" are *inverse* quantities. A breaker written
`epistemic >= threshold` would suppress the safest fixtures and wave the
dangerous ones through, and would look entirely plausible in review.
`test_risk_guard.py::test_breaker_is_not_inverted` pins both halves so that
flipping the comparison fails two assertions at once rather than none.

Three properties make this a guard rather than a heuristic:

1. **It can only subtract.** `evaluate_staking_risk` runs *after*
   `staking_authorization()` has already said yes, and `RiskDecision` carries
   no notion of granting. It cannot turn a `NONE` basis into a stake.
2. **It fails closed.** An epistemic value that is missing, `NaN`, infinite or
   unparseable trips the breaker. "We could not measure the risk" and "there is
   no risk" are different states and only one is safe to stake on.
   `_epistemic_for_match` returns `None` rather than any substitute — a `0.0`
   or a league mean would be read by the breaker as a real measurement, and
   `0.0` in particular sits on the dangerous side of every threshold.
3. **It is inert without an override.** A `CERTIFIED` generation has passed
   `error_association`; the danger zone this breaker exists for was not
   demonstrated for it, so running it there would suppress stakes on evidence
   that no longer holds.

### Why all five leagues, including the two where the effect is absent or reversed

A false positive costs a missed opportunity. A false negative costs a user's
money. This generation has **no demonstrated edge to forgo in the first place**
(0/6 leagues beat the market), so the opportunity cost of over-suppressing is
close to zero while the cost of under-protecting is not. Leagues with no
measured holdout of their own — EREDIVISIE (pooled model) and UCL (no dedicated
model) — receive the *most protective* measured threshold rather than a guess
or a pass-through, for the same reason.

Thresholds are per-league rather than one global constant because the measured
p25 spans 0.0776–0.0879; a single value would over-suppress the low end and
under-protect the high end, and we have the real numbers for each.
`DANGER_ZONE_VERSION` stamps the set so a recorded decision can name which
numbers were in force.

### Observability

A trip emits a structured `WARNING` carrying `event`, `reason`, `league`,
`epistemic`, `threshold`, `danger_zone_version` and `match_id`. The event name
lives in `CIRCUIT_BREAKER_EVENT` so the dashboard query and the emitting code
cannot drift apart, and a test asserts the event is emitted on a trip and *not*
emitted otherwise. On the wire, a suppressed fixture carries
`risk_guard: {...}` alongside its `staking_authorization`, and
`staking_suppressed_by_risk_guard` in `data_gaps`.

### Two disclosure surfaces had to be corrected for the activation

Activation broke two tests, and both named real defects rather than stale
expectations.

`GET /api/v1/models/status` computed `stake_permitted` as `cert ==
"CERTIFIED"`, so it reported `false` while `/upcoming/matches` was staking. It
now asks `staking_authorization()` — the same authority the serving path uses —
and reports `staking_basis` alongside it. `validation_status` deliberately does
not follow: only `CERTIFIED` earns `"VALIDATED"`.

`promotionLabel("ACTIVE_FAIL_CLOSED")` in the web UI hardcoded "Serving
forecasts · staking blocked". The manifest keeps `ACTIVE_FAIL_CLOSED` under an
override, so that sentence became false on a consumer surface the moment this
ADR was activated. It now takes the certification state as a second argument.
`certificationLabel` gained an explicit override case rather than falling
through to "Pending validation", which would have *understated* an actively
staking system.

⚠️ **Any future surface that answers "is staking on?" from
`certification_state` or `promotion_state` alone will be wrong under an
override.** Ask `staking_authorization()`.

### What this does not do

It does **not** fix the inversion, and it must not be read as having reduced
the accepted risk to an acceptable one. `docs/DEBT.md` item 50 stays open. The
override still publishes stakes from a model with no demonstrated edge; the
breaker declines the one slice of that model we have measured to be worst.
Outside the low-epistemic quartile the accepted risks section above applies
unchanged.
