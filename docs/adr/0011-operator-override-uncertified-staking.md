# ADR-0011 — `OPERATOR_OVERRIDE_UNCERTIFIED`: staking without certification, on the record

**Status:** Accepted (mechanism). **NOT ACTIVATED** — no manifest in this
repository declares this state. **Date:** 2026-09-19.
**Supersedes:** nothing. **Relates to:** ADR-0007 (evidence authority &
APEX promotion), ADR-0009 (uncertainty certification), `docs/DEBT.md`
items 14, 25, 42, 50.

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

## Activation

This ADR ships the mechanism only. To activate, an operator sets
`certification_state` to `OPERATOR_OVERRIDE_UNCERTIFIED` in
`backend/models/active_generation.json` and adds:

```json
"operator_override": {
  "authorizing_identity": "name@example.com",
  "rationale": "why this risk is being accepted, specifically",
  "authorized_at": "2026-09-19T00:00:00Z",
  "acknowledged_failures": [
    "market_baseline",
    "no_league_regression",
    "primary_metric_improvement",
    "serving_feature_availability",
    "error_association"
  ]
}
```

That edit is a Class C operator action under DID §51.1 and is deliberately
left to a human. This repository ships it unactivated.
