# SabiScore Debt Ledger

## 38. The promotion gate is unsatisfiable by construction — no candidate can ever be promoted

**Tier:** `NEXT` — **the single hard blocker on Phase 4.** Not a serving
defect; nothing in production reads this gate. But it makes the entire
candidate-promotion path a no-op, so Phase 4 cannot complete regardless of how
good a candidate is.
**Found:** 2026-08-22, while transcribing the in-code certification thresholds
for a frozen policy artifact (APEX directive §9). Surfaced by asking "what
would a *passing* candidate look like?" rather than reading why the current
one failed.

`promotion_evidence._expected_gate()` returns `PASS` only when
`training_defaulted_slots`, `serving_schema_misaligned_slots` **and**
`always_data_gap_slots` are all zero.
`compare_candidate_vs_incumbent.py` then sets
`promotion_permitted = all(gate == "PASS")`.

`PHASE7_FEATURES_ALWAYS_DATA_GAP` holds four features — `shot_quality_diff`,
`elo_league_adjusted`, `key_passes_under_pressure_diff`, `set_piece_xg_diff` —
and **all four are present as slots in both `CANONICAL_FEATURES_68` and
`APEX_FEATURES_68`** (verified directly, not inferred). They are there
deliberately and permanently: `PHASE7_FEATURES_10`'s own comment records that
deleting the slots in June broke every artifact, and the certified model
served `model_version="fallback"` on every single inference for two months as
a result.

**So `always_data_gap_slots` is structurally 4 and can never be 0, and
`serving_feature_availability` can never be `PASS`, and `promotion_permitted`
can never be `true`.** A flawless candidate — zero silent defaults, zero
positional misalignment, trained on 10,000 rows — still fails. Pinned by
`backend/tests/unit/test_promotion_gate_satisfiability.py`, which isolates the
cause to exactly this one counter (zeroing only that term flips the same
summary to `PASS`).

**Two deliberate decisions collided.** Keeping the four slots was right.
Blocking on silent training defaults was right. But the gate conflates a
*declared, dispositioned, permanent* gap with a *silent, undeclared* default,
and only the second is disqualifying. The feature contract shipped in #68/#69
already draws exactly this distinction: `always_data_gap` features get the
`DEFER_UNTIL_DATA_EXISTS` disposition, which is an accepted state, not a
failure.

⚠️ **NOT FIXED IN THIS SESSION, DELIBERATELY.** Relaxing a certification gate
after observing a failing result is what APEX §23 forbids ("lower
certification thresholds after seeing results") and §9 rules out ("do not
choose thresholds after seeing results"). That the change would be *correct*
does not make it safe to make autonomously, and the honest thing is to stop at
the boundary rather than reason my way across it.

**Weighing against that:** the fix would not promote anything today. The
current candidate independently fails `no_league_regression` (3/6 leagues) and
`market_baseline` (0/6 leagues beat the market RPS), and carries 11 misaligned
slots from item 37. So this is a deadlock repair, not threshold-shopping — but
it is still a threshold change, and it needs a human to say so.

**Exact next operation (requires authorization):** drop
`always_data_gap_slots` from the `blockers` tuple in
`promotion_evidence._expected_gate()` (`:117-123`), leaving
`training_defaulted_slots`, `serving_schema_misaligned_slots` and
`training_rows > 0`. Then invert the three tests in
`test_promotion_gate_satisfiability.py` from "pins the deadlock" to "pins the
repair", and record the count of declared gaps in the evidence summary so a
reviewer still sees `4` rather than losing the signal entirely.
**Trigger:** before any Phase 4 candidate can be promoted — i.e. now, but
under explicit authorization.

---

## 37. `train_on_real_matches.py`'s default market block does not match the shipped artifacts' own recorded one

**Tier:** `NEXT` — **blocks Phase 4 outright.** Not a live serving defect
(nothing retrains automatically), but a structural deadlock: the promotion
gate already refuses every candidate this script produces, and will keep
refusing until the schema disagreement is resolved. See the correction below.
**Found:** 2026-08-21, while deriving `training_source` for the feature
contract (item 36). Surfaced *because* the attribution work forced the
question "which code actually trained this slot?" for every feature.

`train_on_real_matches.py:main()` builds its `X` matrix from
`APEX_FEATURES_89 if include_phase8 else APEX_FEATURES_68` (`:782`), and
`build_dataset()` fills the market block with `derive_apex_market_features()`
(`:344`). Both are the Apex 14-field block.

But the shipped, certified `v5_phase7` artifacts record the **legacy**
`MARKET_FEATURES_14` block in their own `feature_columns` metadata — read
directly out of `backend/models/epl_ensemble_v5_phase7.pkl`, indices 17-30 are
`market_prob_home, market_prob_draw, market_prob_away, market_edge_home,
market_favorite, odds_ratio, log_odds_home, log_odds_draw, log_odds_away,
draw_probability, market_confidence, ev_home, ev_draw, ev_away`. That is
`CANONICAL_FEATURES_68`, not `APEX_FEATURES_68`.

**Seven of the fourteen names are identical between the two blocks**
(`market_prob_home/draw/away`, `log_odds_home/draw/away`, `odds_ratio`), so any
*name-keyed* check passes; only the positions differ, at 11 of the 68 slots.

⚠️ **CORRECTED 2026-08-22, same session, before the claim could mislead
anyone.** The first draft of this entry said the discrepancy "stayed
invisible" and framed it as an undetected danger. **That is wrong, and
checking it was the point.** `promotion_evidence._expected_gate()` already
blocks on exactly this: it counts
`candidate_position_matches_current_serving_schema` and reports
`serving_schema_misaligned_slots`. The live
`backend/models/candidate/comparison_report.json` reads **11**, and
`APEX_FEATURES_68` differs from `CANONICAL_FEATURES_68` at exactly **11**
positions (indices 20-30) — verified by direct comparison, not inferred. That
gate is `FAIL`, and it is one of the three reasons
`promotion_permitted: false`.

**The real consequence, restated accurately:** this is not a lurking danger,
it is a **structural deadlock**. While `train_on_real_matches.py` defaults to
the Apex block and `active_generation.json` declares `phase7_68`, every
candidate the script produces is auto-blocked by the availability gate on 11
misaligned slots. No amount of modelling improvement can clear it — the
schemas simply disagree. Someone must decide which block the next generation
uses.

What remains true from the original entry: `train_league()`'s width guard
(`:567`) genuinely does not fire, because both blocks are 14 wide; and the
seven shared names mean a name-keyed check passes. The positional gate is what
catches it, not the width guard.

**Why the contract does not paper over it:** `_training_source()` in
`models/feature_registry.py` returns `UNDECLARED` for the legacy market block
under `phase7_68`/`phase8_89` rather than naming `build_dataset()`. Claiming
the script as the training source for a block it does not currently emit at
those positions would be exactly the fabrication item 36 exists to prevent.
The apex schemas *do* get the attribution, because there the claim is true.

**Fix, in order:** (a) decide which block the next generation trains on — this
is a modelling decision, not a mechanical one, and `derive_apex_market_features`
is the better feature set (non-redundant, `ev_*` are algebraically identical
under the legacy formula, see its docstring); (b) if Apex wins, the candidate
must declare `feature_schema_version: apex_v1_68` (or `_89`) so the identity
gate from PR #67 catches any mislabel; (c) if legacy wins, `build_dataset()`
needs a `--market-block legacy` path calling `derive_market_features()`;
(d) either way add a training-vs-artifact assertion so a future retrain cannot
silently swap blocks. **Do not "fix" it by relabelling the existing artifacts.**
**Trigger:** before any Phase 4 candidate is trained.

---

## 36. Phase 3 feature contract — PARTIALLY RESOLVED 2026-08-21: one generated contract, per-pipeline source attribution, and a real train/serve vector-parity harness; the remaining unanswerable fields stay undeclared

**Tier:** `NEXT` — no fail-open risk remains at the manifest boundary, and the
three-way artifact split is closed. What remains is *populating* fields no code
can answer today, plus §7.3 vector parity.
**Found:** 2026-08-21, while implementing the Phase 3 identity gate.
**Partially resolved:** 2026-08-21, same day, by the generator described below.

### What shipped

`backend/src/models/feature_registry.py` gained `build_feature_contract()` +
`contract_sha256()`, written to `backend/models/feature_contract.json` by
`backend/scripts/generate_feature_contract.py`. This is now the single
authoritative contract for the *active* generation.

It derives only what real code can answer — `index`, `feature_name`, `dtype`,
`default_value`, `fallback_policy`, `required_or_optional`, `league_scope`,
`feature_group`, `always_data_gap`, `disposition`, `version` — and marks the 14
fields nothing in the repo can answer as the literal string `UNDECLARED`.

**Disposition is one explicit rule, not per-feature judgement:**
`always_data_gap` → `DEFER_UNTIL_DATA_EXISTS`; has a registered default and is
not an always-gap → `ALIGNED_OBSERVED`; neither → `UNDECLARED`. On the serving
`phase7_68` contract that yields 64 `ALIGNED_OBSERVED` + 4
`DEFER_UNTIL_DATA_EXISTS`; on `apex_v1_68` the 7-feature Apex market block
correctly lands on `UNDECLARED`, because it genuinely has no entry in
`DEFAULT_FEATURE_VALUES_68`. `REMOVE` / `REDESIGN` /
`REPLACE_WITH_OBSERVABLE_PROXY` are deliberately **not** auto-assigned — those
are product decisions, and a rule that guessed them would be exactly the
fabrication this item warns against.

**Staleness is now machine-enforced — at build time, not on every load.**
`active_generation.py`'s `verify_feature_contract_freshness()` regenerates
the contract and fails closed if the checked-in copy differs, but it is
called only from the Render build gate (`scripts/verify_active_artifacts.py`),
deliberately **not** from `load_active_generation()` itself (the startup and
settlement/staking path) — coupling a derived documentation file's freshness
check to the running-service path would let a stale or missing contract
crash-loop production over metadata instead of failing a deploy, the same
shape as the vΩ.47 incident. Verified by watching it fail: injecting a
fabricated `"unit": "goals"` into one record made both the build gate (exit 1)
and `test_committed_contract_matches_a_fresh_rebuild` fail, then pass again on
restore.

### What remains open

⚠️ **Updated 2026-08-21 (second pass).** Both items below moved; neither is closed.

1. **The UNDECLARED fields are now 11, not 14.** `training_source`,
   `serving_source` and `shadow_source` are resolved per feature by
   `_training_source()` / `_serving_source()` / `_shadow_source()` in
   `models/feature_registry.py`, each returning a real grep-verified code path
   or `UNDECLARED`. On `phase7_68`: 30/68 have a training source, 44/68 a
   serving source (raised from 28/68 by the §7.2 unification below); on
   `phase8_89` 15/89 additionally have a shadow source (the
   Pi/Berrar/EWMA block item 29 proved replayable — the 6 unresolved Phase 8
   fields correctly get none). `offline_backtest_source` stays in the blanket
   list and is expected to stay there permanently: `walk_forward_validate()`
   consumes pre-computed `{date, outcome, probs}` records and has no
   independent feature-computation step to cite, which is asserted rather than
   assumed by `test_backtest_has_no_independent_feature_computation_to_compare`.
   The remaining 11 (`semantic_definition`, `source`,
   `offline_backtest_source`, `availability_time`, `lookahead_risk`,
   `missingness_policy`, `normalization`, `expected_range`, `monitoring_rule`,
   `temporal_validity`, `unit`) are **still pinned as UNDECLARED** by
   `test_unanswerable_fields_are_literally_undeclared`. ⚠️ **Still do not
   hand-write them.** Verified by watching the guard fail: hand-writing
   `unit: "goals"` reddened 4 parametrizations; restore made them green.

   ⚠️ **A trap this attribution work walked into and had to fix:** seven names
   (`market_prob_home/draw/away`, `log_odds_home/draw/away`, `odds_ratio`)
   exist in **both** `MARKET_FEATURES_14` and `APEX_MARKET_FEATURES_14`.
   `_feature_group()` resolves most-specific-first and hits the legacy group
   first, so the first draft attributed the legacy `derive_market_features()`
   to apex slots it does not produce. Market attribution is therefore keyed on
   the **schema** (`_is_apex_schema`), never on the feature name. Any future
   per-feature attribution must ask the same question.

2. **§7.3 vector-hash parity — the harness now exists**
   (`backend/tests/unit/test_feature_vector_parity.py`), and the previously
   unverifiable claim is tested rather than asserted. It seeds one synthetic
   six-match-per-side history as `Match` rows for
   `UpcomingMatchFeatureProjector._get_team_stats()` **and** feeds the same
   results to `train_on_real_matches.TeamHistory`, then compares both the
   per-side stats dicts and a SHA-256 over an ordered 44-name sub-vector
   (`PARITY_SCOPE`). `TeamHistory.stats()`'s long-standing docstring claim —
   "Mirror `_get_team_stats()`" — is confirmed true for the first time.
   A `test_a_divergence_actually_breaks_the_hash` case perturbs one feature by
   1e-9 to prove the digest is load-bearing, and
   `test_parity_scope_matches_the_contract_s_own_attribution` fails if the
   harness ever claims parity for a feature the contract cannot attribute
   (watched failing on `shot_quality_diff` before being trusted).

   ✅ **§7.2 unification DONE 2026-08-22.**
   `FeatureTransformer._project_to_canonical_features()` — the *second*
   serving implementation, serving `insights/engine.py` — no longer carries
   inline copies of the temporal, league and combination arithmetic. It now
   calls the same `derive_temporal_features()` / `derive_league_features()` /
   `derive_combination_features()` the projector and the training script
   already used, so all three pipelines share one implementation per group.

   The tables were **proven** byte-identical before the change, not assumed:
   the league priors dict and its fallback triple compare equal; the one-hot
   logic agrees across all 12 league keys including unsupported ones; temporal
   agrees across five kickoffs (pandas `.dayofweek` and `datetime.weekday()`
   share Monday=0); the four combination formulas agree. The parity harness
   now runs the real `FeatureTransformer` and asserts agreement, and was
   watched failing on an injected divergence before being trusted.
   Consequence: `serving_source` on `phase7_68` resolves for 44 of 68
   features, up from 28.

   ⚠️ **The fail-closed guard deliberately did NOT move into the shared
   helper.** `derive_league_features()` falls back for a league with no
   measured priors, because `UpcomingMatchFeatureProjector` must keep serving
   Eredivisie and UCL — neither has a one-hot column. `FeatureTransformer` is
   the stricter caller and still raises `DataUnavailableError`, now via the
   new public `has_league_rate_priors()` predicate. Pinned by
   `test_unifying_did_not_remove_the_unsupported_league_guard`, which asserts
   the guard's *location*: moving it into the helper would keep that test
   green while silently breaking the projector.

   ✅ **`FeatureTransformer` test-coverage gap closed 2026-08-22 (same day,
   follow-up pass).** `_serving_source()` already attributed `FeatureTransformer`'s
   last-5-form and market-block calls to `derive_last5_form_features()` /
   `derive_market_features()` (both were unified earlier, under WP-18/WP-A,
   before §7.2's temporal/league/combination work) — but only the group tests
   added alongside §7.2 (`test_second_serving_implementation_matches_the_shared_
   league_helper` / `_temporal_helper` / `_combination_helper`) existed;
   last-5-form and market had zero regression coverage despite the shared
   implementation already being live. `test_second_serving_implementation_
   matches_the_shared_last5_form_helper` and `_market_helper` close that gap,
   both watched failing on an injected perturbation before being trusted. All
   five feature groups `FeatureTransformer` shares with the other pipelines
   are now individually parity-tested.

   **What remains uncovered:**
   - the 6 goals/gd fields are attributed but flagged as a **replicated direct
     assignment** across three pipelines rather than a shared function. The
     harness verifies they agree today; three copies can drift where one
     function cannot.
   - the fallback branches. Both pipelines are compared only where each has
     >=5 real results, because below that threshold they legitimately differ
     (serving substitutes documented defaults and raises a data gap; training
     returns `None` and drops the row). That divergence is by design, so the
     harness states the restriction rather than hiding it.
   - the 24 features with `serving_source: UNDECLARED` on `phase7_68`
     (`h2h_*`, `home_venue_*`, `home_advantage_strength`,
     `total_goals_expected`, the 4 agreement/combo fields, and all 10
     `PHASE7_FEATURES_10` elo/pressing/carry/shot-quality fields) — no shared
     implementation exists to attribute or parity-test them against. Extracting
     one for each remaining group is a materially larger effort, not attempted
     this session.

### Deliberately unchanged

- `backend/models/candidate/feature_availability_matrix.json` +
  `promotion_evidence.py` — a different job (candidate-vs-serving *promotion
  gate*, real tested producer/consumer pair). Its producer-drift note above
  still stands and is still a live trap: the checked-in file carries
  `serving_status` / `freshness_contract` that today's producer does not emit,
  so regenerating it would silently lose those fields.
- `docs/apex_feature_availability.{json,md}` — **retained, not deleted, on a
  reversed decision.** These were slated for deletion as "zero producers, zero
  consumers." Reading them first showed the `.md` carries per-league coverage
  *measurements* (EPL 14.3% market / Eredivisie 100% / Ligue 1 13.1%, 2026-08-10)
  that exist nowhere else and **cannot be regenerated — the generator does not
  exist in the repo**. Deleting them would destroy an unreproducible measurement
  record. They are superseded as a *contract* description by
  `feature_contract.json`; they survive as a historical coverage snapshot only.
  Note item 29's fix (c) says "regenerate `apex_feature_availability.md`" — that
  is not currently possible for the same reason; it is really "build a per-league
  availability generator", which does not exist yet.

**Trigger for the remainder:** before any `v6_phase8` candidate is evaluated for
promotion — that is the moment unstated dispositions and absent vector parity
become load-bearing.

---

## 35. `fixture_sync.identity_rebind_pending` has zero consumers — the drift it correctly detects just accumulates in warning logs

> ⚠️ **Correction (2026-08-21):** fix (a) below — "surface
> `identity_rebind_pending` in `/health` or `/metrics`" — **is already done and
> was when this item was filed.** `metrics_collector.increment()` writes to
> `_counters`, `get_summary()` returns `"counters": dict(self._counters)`, and
> `GET /metrics` returns that under `production.counters`. The grep that found
> "exactly one line" matched only `backend/src`, missing that the collector is a
> generic sink whose consumers are the endpoint, not the call site.
>
> **The underlying complaint still stands, restated accurately:** `MetricsCollector`
> is an in-process, in-memory counter that `reset()` clears and that starts at
> zero on every boot — and Render runs a single worker that restarts on every
> deploy. So it reports *rebind events observed since this process started*, not
> *how many matches are currently drifted*. A process-lifetime event counter
> cannot answer the backlog question, which is why the same 11 matches re-warn on
> every deploy forever with no visible total. Fix (a) should therefore be read as
> **"expose a durable backlog gauge"**, not "add a counter" — the counter exists.

**Tier:** `NEXT` — low urgency, no data-corruption risk (the guard fails
closed exactly as designed).
**Found:** 2026-08-21, incidentally, reading a Render deploy log for an
unrelated database-migration verification.

`fixture_sync_service.py` (`sync_upcoming_fixtures` / `_upsert_fixtures`,
~line 387) already does the right thing when re-syncing an unsettled match:
if the freshly-resolved team ids (`_resolve_upcoming_team_id`, the live
provider-identity path added in PR #39) disagree with the already-persisted
`match.home_team_id`/`away_team_id`, it logs a warning, increments
`fixture_sync.identity_rebind_pending`, and **leaves the row unchanged**
rather than guessing which id is correct — the same fail-closed instinct as
every other identity guard in this codebase. Observed live, one deploy,
9 distinct matches, all in the same shape:

```text
match_id=fd-560548 stored=(fd-team-epl:manchester_city_fc,fdco-team-epl-bournemouth)
                    verified=(fdco-team-epl-man_city,fdco-team-epl-bournemouth)
```

The pattern across all 9 is consistent: the **stored** side is the older
`fd-team-<league>:<slug>` convention (colon separator, full slug — predates
PR #39's live-identity bridge), the **verified** side is the current
`fdco-team-<league>-<slug>` convention `_resolve_upcoming_team_id` and
`historical_backfill_service._historical_team_id()` both use today. These
read like the same real-world clubs under two ID generations, not genuine
conflicts — but the guard is right not to assume that from inside a fixture
sync loop; confirming it needs the same kind of source-backed manifest this
session's item 34 already built for the semantic-identity case, not a
second ad hoc heuristic.

**The actual gap:** `grep -rn identity_rebind_pending backend/src` finds
exactly one line — the increment itself. No dashboard reads it, no alert
fires on it, nothing reconciles it. A backlog of "pending reconciliation"
matches can grow indefinitely with the only visible trace being scattered
WARNING log lines on whichever deploy happens to touch them.
**Blast radius:** low today — Elo/prediction features for a flagged match
keep serving from whichever id was already persisted, so nothing silently
breaks. It does mean the same match can be flagged repeatedly across
deploys/sync ticks without ever resolving, and the *count* of unresolved
identity drift in the system is currently invisible.
**Fix, in priority order:** (a) surface `identity_rebind_pending` in
`/health` or `/metrics` so the backlog size is at least visible; (b) decide
whether a source-backed reconciliation manifest (mirroring item 34's
`historical_identity_repair_manifest_service.py` pattern) is the right tool
for the *live* fixture-sync case too, or whether a lighter one-time backfill
of the 9 (and any others already accumulated) `fd-team-` rows to the
`fdco-team-` convention closes it outright.
**Trigger:** revisit once item 34's semantic-identity infrastructure is
actually exercised — the two problems are close enough in shape that
solving one well likely informs the other.

---

## 34. Semantic-identity repair manifest v3 is code-ready; live review and `--apply` remain operator-gated — NEXT

**Tier:** `NEXT`. The production v2 review on 2026-08-21 found 518 affected EPL
matches: 236 repair-ready and 282 blocked. The measured blockers are a missing
same-league West Ham Team identity plus exact/alias ambiguity for Man City and a
curated-alias miss for Ipswich. Manifest v3 resolves those cases in code without
broad fuzzy matching. It must still pass CI, deploy on one exact SHA, and produce
a complete live review before any Class-C authorization can be requested.

**Context.** `historical_identity_audit_service.py` (PR #40) already finds
semantic-identity drift beyond the simple self-play case closed in item 23 —
matches where a source team name was mis-resolved to the *wrong distinct*
team, not to itself. This session adds the two missing pieces to actually
repair it:

1. `historical_identity_repair_manifest_service.py` — for every audit
   finding, recovers the original football-data.co.uk row, checks
   league/date/score agreement against the persisted `Match`, and
   re-resolves both team names under today's league-scoped `TeamIndex`. An
   entry is `repair_ready` only when the source agrees and both teams
   resolve to two *distinct* ids or a schema-v3 deterministic Team creation.
   Each creation and its source evidence are hashed; every other case is a named blocker
   (`source_score_mismatch`, `target_home_unresolved`,
   `target_identity_collision`, …), never a guess. The whole manifest is
   canonicalized and SHA-256 hashed. Read-only — `SET TRANSACTION READ ONLY`,
   always rolled back.
2. `historical_identity_repair_service.py` — plans a **full path-dependent
   Elo rebuild**, not a spot fix. Elo is order-dependent: correcting only the
   directly-affected `Match` rows (or deleting only their own snapshots)
   would leave every later opponent's rating built on a wrong intermediate
   state. The plan replaces every `EloRatingSnapshot` from the start of the
   earliest affected UTC day forward, per league, replayed in deterministic
   `(match_date, id)` order — same idea as `replay_elo_from_db.py`, scoped to
   exactly the affected window.

**Why `--apply` is intentionally not runnable by copying a value in.**
`apply_semantic_identity_and_rebuild_elo()` re-derives both the manifest and
the replay-plan SHA-256 *inside* the transaction, under a PostgreSQL
`LOCK TABLE teams, matches, elo_rating_snapshots IN SHARE ROW EXCLUSIVE MODE`, and
aborts if either digest has moved since review — so a value copied from an
earlier review, or a manifest that drifted because new matches synced in the
meantime, cannot silently apply against a different reality than what was
reviewed. `scripts/repair_semantic_identity_and_rebuild_elo.py --apply`
additionally requires a non-empty `--authorization-id` and the literal
`--confirm APPLY_SEMANTIC_IDENTITY_AND_REBUILD_ELO` token. Extensive
postconditions run after the rebuild: exact match/snapshot population,
per-match team-id/league/timestamp integrity, and a final
`audit_historical_semantic_identity()` re-run that must return zero residual
findings.

**Trigger to close:** after the schema-v3 release reaches production, an operator runs
`python scripts/repair_semantic_identity_and_rebuild_elo.py --review`
against production, confirms `affected_matches: 518`, `repair_ready_matches:
518`, `blocked: false`, `complete: true`, the exact proposed Team creation and
participant replacements, and records the two printed SHA-256 digests. A later
separately-authorized run may use `--apply` with those digests plus
a real authorization id. Until then this is inert, reviewable code — no
production data has been touched by this item.

---

## 33. Public CLV and value-bet-scan trusted a persisted payload's own claims instead of the certified-generation authority — FIXED 2026-08-20

**Tier:** `RESOLVED 2026-08-20`.
**Found:** while wiring release-SHA parity, a read of `value_bet_scan`
(`GET /api/v1/value-bet-scan`) showed it gated candidates only on the
*persisted* `MatchPredictionLog.payload`'s own `verdict`/`stake_permitted`
fields — with no check against which model generation is actually
`CERTIFIED` today. A row written under a since-decertified or rolled-back
generation could still read `stake_permitted: true` and would have kept
surfacing on this public endpoint indefinitely. `/health`'s own
`_validated_generation()` already solved exactly this for readiness two
sessions ago (`models/active_generation.py`, hash-validated, `CERTIFIED`
state), but `performance.py` never adopted it.

**Fix:** new `_certified_value_generation()` (same `@lru_cache(maxsize=1)`
shape as `health.py`'s `_validated_generation()`, justified the same way —
the active generation is deployment-atomic) calls the existing
`load_active_generation()`/`CERTIFIED` authority. `value_bet_scan` now
returns a `RESEARCH_ONLY` response with a named `reason`
(`model_not_certified` / `active_generation_invalid` /
`active_generation_missing_version`) and **does not touch the database at
all** whenever certification isn't valid — confirmed live: today's real
active generation is `v5_phase7-20260808 (UNVERIFIED)`
(`verify_active_artifacts.py`), so this endpoint now correctly answers
`RESEARCH_ONLY` in production instead of a false `OK`. Both prediction-log
queries inside `value_bet_scan` are additionally scoped to
`MatchPredictionLog.model_version == <certified version>`, closing the
identical gap for CLV: `get_clv_records()`/`build_clv_records_query()` gain
an optional `model_version` filter, applied **both** inside the
latest-prediction subquery and on the outer select — filtering only outside
would let a newer foreign generation's row silently hide a valid older row
for the requested generation, so both predicates are load-bearing (pinned by
`test_clv_generation_scope.py`'s assertion that the filter string appears at
least twice in the compiled SQL). `GET /api/v1/model-performance` now passes
the walk-forward result's own `model_version` through to `get_clv_records`,
so a reported CLV figure can never silently pool two model generations'
predictions.

---

## 32. `backendCapability` was structurally always `null` in production; `replay_elo_from_db.py`'s SQLite-fallback debt closed — FIXED 2026-08-20

**Tier:** `RESOLVED 2026-08-20`.
**Found:** while adding exact release-SHA parity checks, a direct read of
`apps/web/src/app/api/health/route.ts` against the real
`backend/src/api/endpoints/health.py` showed a field-name mismatch:
`route.ts` read `data.capability` (singular) from `/health/ready`'s JSON
body, but `health.py`'s `readiness_check()` has only ever emitted
`"capabilities"` (plural) — confirmed by grepping the whole file for
`"capabilit` and finding exactly one match. **`backendCapability` in the
`/api/health` response has therefore been structurally `null` on every real
production request.** The existing Vitest coverage never caught this because
its own stubbed fixtures mocked the *wrong* shape too
(`capability: {status: "failed"}`), so the test suite and the bug agreed
with each other while both disagreed with the real backend.

**Fix:** `backendCapability` now reads
`data.capabilities ?? data.capability`, preferring the real plural key and
falling back to the singular one a caller might still send — backward
compatible, not a breaking rename. New regression test asserts the plural
key round-trips end to end. Also closes a debt callout from the previous
session's item 23 entry: `replay_elo_from_db.py` carried the identical
implicit-SQLite-fallback pattern (`os.environ.setdefault("DATABASE_URL",
"sqlite+aiosqlite:///...")` + `SABISCORE_ALLOW_INSECURE_FALLBACK=true`) that
`repair_self_play_matches.py` deliberately avoided, flagged there as "worth
the same treatment next time it is touched." Removed; the script now
resolves `DATABASE_URL` through the normal settings chain or an explicit
`--database-url`, echoes the redacted target, and fails loudly instead of
silently reporting `eligible=0` against an empty local database.

---

## 31. `database.py`'s Postgres connection failure replaced the driver's real error with an unactionable string — FIXED 2026-08-19

**Tier:** `RESOLVED 2026-08-19`.
**Found:** while an operator ran `scripts/repair_self_play_matches.py` against
production and got, in full:

```text
File "backend/src/core/database.py", line 113, in <module>
    raise Exception("PostgreSQL connection test failed")
Exception: PostgreSQL connection test failed
```

Nothing in that names a cause. `_test_connection(eng) -> bool` catches the
driver exception, logs it at `logger.warning`, and returns `False`; the caller
then raised a fresh generic `Exception` with no `__cause__`. Any caller that
has not configured logging — CLI scripts, alembic, a bare `python -c` import —
therefore sees the *only* diagnostic discarded. The real message in this case
was `FATAL: password authentication failed for user "sabiscore_db_v2_user"`,
which is entirely self-explaining.

**Fix:** the PostgreSQL branch now connects inline (`with engine.connect()`)
instead of routing through `_test_connection()`, so the driver's own exception
propagates untouched. `_test_connection()` is unchanged and still used by the
two SQLite paths, where a bool is the right shape and the warning is reachable.
`_db_available` semantics are unaffected — it defaults `True` and was never
assigned on the Postgres success path.

**Diagnostic value confirmed by reproduction**, not assumed: re-running the
same command with a deliberately wrong password now surfaces
`sqlalchemy.exc.OperationalError: ... FATAL: password authentication failed for
user "..."`. An SSL hypothesis was tested and **disproved** first — probing the
Render external host across `sslmode=prefer|disable|require` showed `prefer`
(psycopg's default) reaching authentication, so TLS and network were never the
problem. Recording that here because "Render external Postgres needs SSL" is a
plausible-sounding wrong answer that would have cost a cycle.

⚠️ **Render hostname gotcha, same incident:** `dpg-<id>-a` is Render's
*internal* hostname and does not resolve outside their network (verified:
`gaierror`). External access needs `dpg-<id>-a.<region>-postgres.render.com`
(here `oregon`), which resolves. Both forms appear in Render's dashboard; only
the external one works from a developer machine.

---


## 30. The full test suite makes a live network call and overwrites a committed data file

**Tier:** `RESOLVED 2026-08-19`. `test_download_season_data` and
`test_pinnacle_odds_extraction` (`backend/tests/test_scrapers.py`) now take a
`tmp_path` fixture and point `scraper.cache_dir` at it before calling
`download_season_data`, so a stale-cache miss fetches (or fails to fetch, both
fine — `download_season_data`'s own documented fallback is an empty
DataFrame) into an isolated temp directory instead of the committed
`data/cache/football_data/E0_2324.csv`. No new fixture, no env var, no
network-mocking framework — the scraper already exposed `cache_dir` as a
plain instance attribute.

**Original description (for context):** test-hygiene defect, no production
impact, but it silently dirties the working tree and depends on a
third-party host being up.
**Found:** 2026-08-18, incidentally — a routine `git status` after an unrelated
change showed `data/cache/football_data/E0_2324.csv` modified with 380 changed
rows that nothing in that change had touched.

`FootballDataEnhancedScraper` (`backend/src/data/scrapers/football_data_scraper.py:133`)
caches to `CACHE_DIR / "football_data" / f"{league_code}_{season}.csv"` with a
24-hour TTL (`_is_cache_valid`, `:166-172`). The committed
`E0_2324.csv` is far older than that, so a full `pytest tests` run finds the
cache stale, **fetches from football-data.co.uk over the network**, and
rewrites the committed file — in the observed case appending `source` and
`scraped_at` columns (`,football-data.co.uk,2026-08-18T19:13:31.479992`) to
every row, because the upstream schema has moved on since the file was
committed.

Three separate problems in one:
1. A test suite that reaches the public internet is non-hermetic — it fails
   offline, and its result depends on a third party's uptime and schema.
2. It mutates a **committed** file, so an unrelated change appears to touch
   380 rows of match data. Anyone running the suite before committing could
   sweep that into an unrelated commit without noticing.
3. The rewritten schema differs from the committed one, so the mutation is not
   even idempotent — it is a silent data-format change.

**Fix:** point the scraper's cache at a gitignored/temp directory under test,
or inject a fixture cache and assert no network access (the repo already has
the offline-provider discipline for this — `PROVIDER_LIVE_TESTS=false`). The
committed CSV should be treated as a read-only fixture, not a warm cache.
**Workaround until then:** `git restore data/cache/football_data/` after any
full-suite run; check `git status` before committing.
**Not fixed in the session that found it** — unrelated to that change's scope,
and picking the right isolation mechanism deserves its own decision.

---

## 29. Phase 8 has no training-time feature computation — a v6_phase8 retrain today would ship a false-confidence artifact

**Tier:** `PARTIALLY RESOLVED 2026-08-18` — 15 of the 21 columns now replay
real values; 6 remain structurally underivable and are explicitly declared as
such. Found 2026-08-18 via a dedicated train/serve parity audit (requested
before any Phase 8 activation work, specifically to avoid this class of
mistake), fixed the same session.

**What shipped (fix (a) below):** `backend/src/features/phase8_historical.py`
replays `PiRatingSystem`, `BerrarRatingSystem` and `weighted_form_features`
chronologically over the real `fd_*.csv` corpus, calling the *same* engine
classes serving calls rather than reimplementing their arithmetic. Wired into
`backend/scripts/train_on_real_matches.py` behind an opt-in `--include-phase8`
flag (68 → 89 features). Measured on the real EPL corpus (2,571 rows), the 15
replayed columns now carry **489–2,506 distinct values each** where every one
of the 21 was previously a single constant; the existing 68-feature path is
byte-identical, verified by asserting `X89[:, :68] == X68`. Artifacts are
written as `*_ensemble_v6_phase8.pkl`, never over the `v5_phase7` filenames,
because `prediction.py`'s `_wrap_artifact` infers provenance from artifact
shape and a mislabelled file would make shape and filename disagree.
`train_league` now also refuses to train when the matrix width and the supplied
feature-name list disagree, so an 89-wide vector cannot be labelled 68.
`model_metadata` records `phase8_features_replayed` / `phase8_features_defaulted`
so a future promotion review can see the 15/6 split without re-deriving it.
Covered by `backend/tests/unit/test_phase8_historical.py` (11 tests) — the
load-bearing ones assert genuine *variance* and no-leakage, because a
shape-only "21 columns present" assertion would have passed under the original
defect.

⚠️ **Finding surfaced by actually computing the values:** `pi_attack_diff` and
`pi_defense_diff` are **mathematically always identical**. The Pi update rule
moves each team's defense by the exact negative of its attack, so
`ad - hd ≡ ha - aa`. Two of the 21 Phase 8 features are therefore one feature.
This is an upstream property of `PiRatingSystem` that holds identically at
serving time — **do not "fix" it in the replay**, which would create the exact
train/serve divergence this work exists to prevent. It is a candidate for
`ENSEMBLE_CORRELATION_PRUNE_THRESHOLD` (0.92) to prune at promotion time, or
for a deliberate, both-sides change to the engine. Invisible until now
precisely because the column was constant.

**The serving side is real and reasonably close to ready**: all 5 Phase 8
feature families (Pi-ratings, Berrar ratings, EWMA form, market drift, match
importance — 21 fields, `PHASE8_FEATURES_21` in
`backend/src/models/feature_registry.py:284-330`) are genuinely computed from
live data in `_inject_phase8_features()`
(`backend/src/services/upcoming_match_feature_service.py:707-921`), point-in-time
correct (`Match.match_date < match_date`, strict inequality), gap- and
freshness-tracked. This part is closer to canary-ready than expected.

**The training side does not exist.** No script anywhere in the repo runs
`PiRatingSystem`/`BerrarRatingSystem`/`weighted_form_features`/
`compute_market_drift`/`compute_match_context` over historical rows.
`backend/scripts/retrain_with_expanded_features.py`'s `_inject_phase8_proxies`
(`:202-228`) fills all 21 Phase 8 columns with a **constant registry default**
wherever the column is absent — confirmed the checked-in
`backend/data/processed/epl_training.csv` has 0 of 236 columns matching any
Phase 8 field name. `backend/scripts/train_on_real_matches.py` (the pipeline
that actually produced the shipped `v5_phase7` artifacts) never touches
Phase 8 at all.

**Consequence:** running `retrain_with_expanded_features.py --feature-set
phase8` against the checked-in data today would produce a model whose 21
Phase 8 columns carry **zero variance during training** (tree learners cannot
split on a constant column — the model learns nothing from them) while at
serving time those same 21 slots would carry real, live, varying values. That
candidate would report `feature_count: 89` / `feature_schema_version:
phase8_89` in its metadata while being functionally no better than the
existing 68-feature model — a false-confidence artifact that could pass a
naive "89 features present" check while carrying none of the claimed signal.
**No test would catch this** — `grep -rln "phase8" backend/tests -i` and
`grep -rln "parity" backend/tests -i` have zero file overlap; the only
Phase8-named test file (`test_phase8_features_endpoint.py`) covers registry
invariants and endpoint response shape, not serving-vs-training equivalence.

**`docs/apex_feature_availability.md` is not evidence either way** — it's a
one-shot doc (single commit `e9b7ad6`, 2026-08-10, never regenerated) whose
generator imports the same 68-feature-only `train_on_real_matches.py`
pipeline. It contains 68 features per league, zero Phase 8 fields. Anyone
reading it for Phase 8 go/no-go is reading the wrong document — it isn't
stale, it never had Phase 8 in scope.

**Two more standing gaps, lower priority than the training pipeline:**
Pi-ratings and Berrar ratings' parquet artifacts
(`data/processed/pi_ratings.parquet`, `data/processed/berrar_ratings.parquet`)
don't exist on disk and nothing backfills them — those two families would
serve cold-start neutral state (Pi 0.0/0.0, Berrar 1500/1500) for every team
if activated today, not real fitted ratings. `PHASE8_CANARY_PCT` has zero
consumers anywhere in `backend/src` (reconfirmed) — flipping it does nothing;
the MD5-hash routing scheme its docstring promises was never written.
`PHASE8_ENRICHMENT_SHADOW` only guards 2 of the 5 families (market drift,
match importance) and is itself gated behind the master flag already being
on — there's no way to shadow-observe Pi/Berrar/EWMA before flipping
`USE_PHASE8_FEATURES`.

**Not an immediate production risk today** — `active_generation.json` pins
`feature_schema_version: "phase7_68"` and the shipped ensembles physically
have 68 input columns, so flipping `USE_PHASE8_FEATURES` on today only
changes the separate `/matches/upcoming/{id}/phase8-features` analytics-panel
endpoint response, not the live verdict/staking model. The landmine is
specifically in the *retraining* step, the moment someone trusts a
`v6_phase8` candidate's metadata without checking this.

**Fix, in priority order:** ~~(a) build a historical Phase 8
feature-engineering pass~~ **DONE 2026-08-18** (see above); (b) add a
train/serve parity test scoped to the 21 Phase 8 names — partially covered by
`test_phase8_historical.py`'s contract test, but a true parity test comparing a
serving vector against a training vector for the same fixture is still absent;
(c) produce per-league Phase 8 availability evidence against a pipeline that
includes the 89-feature schema — ⚠️ **corrected 2026-08-21: this is not a
"regenerate", it is a build.** `apex_feature_availability.md`'s generator does
not exist anywhere in the repo (see item 36), so the file cannot be
re-derived; the work is writing that generator, with the existing one-shot
`.md`/`.json` pair usable only as a Phase-7-era reference for the output shape; (d) backfill the Pi/Berrar parquet artifacts for *serving* — the
replay above is deliberately training-only (in-memory, `parquet_path=None`,
keyed by CSV team-name strings), so production serving still cold-starts both
engines at neutral. Closing (d) means replaying the same engines over the DB's
`Match` table keyed by canonical `Team.id` — near-identical to
`replay_elo_from_db.py`, and a natural follow-up now that the replay logic
exists.
**Trigger:** (b)/(c) before a `v6_phase8` candidate is promoted; (d) before
`USE_PHASE8_FEATURES` is flipped on in production, since without it the Pi and
Berrar families would serve neutral values for every team.

**Still true and unchanged:** market drift (5) and match importance (1) remain
underivable from the historical corpus (see the two bullets above), so a
`--include-phase8` artifact trains on 15 real + 6 constant Phase 8 columns.
That is honest and declared in the artifact's own metadata — but it does mean
those 6 still teach the model nothing, and a promotion review must not read
`feature_count: 89` as "89 informative features".

---

## 28. S3 evidence-storage 403 confirmed with real local credentials — narrows to a genuine IAM problem

**Tier:** `NEXT` (operator-only — AWS IAM console access required; not
agent-doable from here). Not new *scope*, but new *evidence*.

**Found 2026-08-18.** Ran `pnpm --filter @sabiscore/scraper storage:probe`
locally with `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` sourced silently from
the local `.env`/`backend/.env` files (values never read/displayed — sourced
into the subprocess environment only; the agent never saw them). Result:

```json
{ "ok": false, "error_code": "s3_authorization_failed", "http_status": 403 }
```

This is materially stronger evidence than the 2026-08-14 finding it confirms.
`storageFailureCode()` (`apps/scraper/src/storage.mjs:40-46`) only reaches
`s3_authorization_failed` *after* `SABISCORE_ARTIFACT_BUCKET` was present
(otherwise `probeImmutableStorage` throws `s3_bucket_not_configured` before
any network call — line 232) and a real `PutObject`/`HeadObject` call reached
AWS and got 403 back. So this run used a real bucket name and a real access
key/secret pair, and AWS itself rejected the request — this rules out "nobody
has tried with real credentials yet" as an explanation. The remaining
candidates are exactly what `docs/S3_EVIDENCE_STORAGE_RUNBOOK.md` already
names: the IAM policy on `sabiscore-render-evidence-writer` isn't actually
attached/correct, the account/region doesn't match the bucket
(`sabiscore-artifacts-prod-uswest2`, `us-west-2`), or `BucketOwnerEnforced`
object ownership is blocking this principal.

**Not agent-doable from here** — diagnosing which of those three it is
requires reading the real IAM policy document and bucket ownership settings in
the AWS console, which needs operator access this environment doesn't have.
**Do not** attempt to work around the 403 (e.g., relaxing `BucketOwnerEnforced`,
loosening the IAM policy scope, or switching to a different credential path)
without operator sign-off — the policy is deliberately least-privilege
(`infra/aws/evidence-storage.yaml:63-84`: only `GetObject`/`PutObject` scoped
to `raw/*`/`processed/*`/`manifests/*`, no `List`/`Delete`).

---

## 27. LazyMotion adoption — measured, not worth the rewrite right now

**Tier:** `ACCEPTED` (deferred, with a threshold). Not a defect; recorded so
the next session doesn't re-raise this as unmeasured.

**Background:** 16 files in `apps/web/src` import the full `motion` export
from `framer-motion` (`useReducedMotion`/`AnimatePresence`-only imports don't
count); 0 use `LazyMotion`/`domAnimation`. One component
(`insights-tease-strip.tsx`) briefly switched to `m`/`LazyMotion` and was
**deliberately reverted** back to `motion` for codebase consistency (see
`CHANGELOG.md`), not because it failed.

**Measured 2026-08-18** via the already-wired `ANALYZE=true pnpm --filter
@sabiscore/web build` (no prior session had actually run this before deciding
whether the migration was worth it). Current route table vs. the last logged
one (`CLAUDE.md` vΩ.25):

| Route | vΩ.25 | Now (2026-08-18) |
|---|---|---|
| shared baseline | 103 kB | 103 kB (unchanged) |
| `/match` | 207 kB | 210 kB |
| `/match/[id]` | 158 kB | 151 kB |
| `/monitoring` | 145 kB | **103 kB** — now equals the shared baseline |
| `/intelligence` | 142 kB | 152 kB |
| `/performance` | 127 kB | 128 kB |

`/monitoring` dropping to exactly the shared baseline shows the codebase's
established mitigation (route-level `next/dynamic({ ssr:false })`, already
used for `RollingAccuracyChart`/`MatchLoadingExperience`/etc. per vΩ.24-25)
is already doing real work on at least one previously-heavy route — without
touching `framer-motion` at all. Inspecting `.next/analyze/client.html`
confirms `framer-motion`'s modules are bundled **per-route**, not merged into
the 103 kB shared chunk, so each route only pays for it if that route's own
component tree imports it — the same effect `LazyMotion` would provide,
already happening via Next's route-based code splitting.
`experimental.optimizePackageImports` in `next.config.js:52` already includes
`framer-motion`, giving Next's own barrel-import tree-shaking without the
`m.`-prefix rewrite.

**Decision:** no route regressed materially since vΩ.25 (most held steady or
improved), the codebase already tried `LazyMotion` once and walked it back,
and the remaining per-route weight isn't cleanly attributable to
`framer-motion` alone (recharts and other data-viz deps are equally present on
the heaviest routes and already get the dynamic-import treatment separately).
A 16-file `motion`→`m` + provider-wrapper rewrite isn't justified by this
measurement. **Revisit only if** a future `ANALYZE=true` build shows a route's
First Load JS regress by ≥20 kB with `framer-motion` modules newly appearing
in the *shared* chunk (not per-route) — that would mean route splitting
stopped isolating it and `LazyMotion` would actually pay for itself.

---

## 25. Certification/staking phases are blocked by evidence volume, not by engineering

**Tier:** `ACCEPTED` — this is the system working. Recorded so the next session
does not re-derive it, and does not mistake "cheap to flip" for "ready".
**Found:** 2026-08-17, while attempting the certification → staking-activation
sequence end to end.

Certification, staking activation, retraining promotion, and shadow production
cannot legitimately start yet, and the blocker in every case is accumulated
real evidence, not missing code:

| Gate | Floor | Actual (2026-08-17) |
|---|---|---|
| `walk_forward_validate` | 10 records (`n_splits * 2`) | **3** for the active `v5_phase7` generation |
| `MIN_RECORDS_FOR_DECOMPOSITION` | 10 pooled | 3 |
| `_MIN_CLV_SAMPLE_SIZE` | 10 joined | 4 closing lines exist; 2 are post-kickoff and correctly excluded |
| `compare_candidate_vs_incumbent` | 7 gates PASS | 3 FAIL (`serving_feature_availability`, `no_league_regression`, `market_baseline`) |

⚠️ **The "8/9 settled predictions" figure previously visible on `/health` was a
cross-generation pooled count** — 7 `v5_phase7` + 6 `v6_phase8`. Scoped to the
generation actually serving, the real figure is **3**. Fixed this session; see
the entry below. Do not read the pre-fix number as progress toward the floor.

**Do not** attempt to unblock any of these by lowering a threshold, pooling
generations, widening a sample, or hand-editing `certification_state`. Each of
those is an explicit non-negotiable invariant. The only legitimate unblock is
elapsed season time producing real settled fixtures.

**Also confirmed absent and correctly so:** there is no shadow *model*
inference path (candidate ‖ incumbent, both logged). `PHASE8_ENRICHMENT_SHADOW`
is a genuine *feature* shadow; `PHASE9_SHADOW_ONLY` stamps metadata and gates
nothing; `PHASE8_CANARY_PCT` is declared in `config.py` and `render.yaml` with
**zero consumers** in `backend/src` — a dead flag whose docstring promises a
mirror of `PHASE7_CANARY_PCT` that was never written. Building shadow inference
before a candidate can pass its offline gates would be premature.

**Priority:** none — time-gated. Re-check when the active generation reaches 10
settled predictions.

---

## 26. `feature_availability_matrix.json` producer/consumer mismatch — RESOLVED (was already fixed when filed; ledger was stale)

**Tier:** `CLOSED`. **Filed 2026-08-17 05:53 (commit `c256852`) describing a real
bug that was already fixed 66 minutes later, 2026-08-17 06:59 (commit
`f985946`, "fix(promotion): make feature evidence deterministic (#24)"), which
never came back to close this entry.** Re-verified 2026-08-18: no code action
needed, only this write-up was stale.

Original claim: the committed generator (`generate_feature_availability_matrix.py`)
emitted a coarser schema than `compare_candidate_vs_incumbent.py:203` consumed,
so regenerating and comparing would `KeyError`. That mismatch no longer exists —
`f985946` deleted the old coarse-schema generator and rewired both the producer
(`backend/scripts/generate_feature_availability_matrix.py`) and the consumer
(`backend/scripts/compare_candidate_vs_incumbent.py:96-102,216-219`) through one
shared schema, `backend/src/models/promotion_evidence.py`
(`build_promotion_feature_evidence` / `validate_promotion_feature_evidence`).
Confirmed by re-reading the checked-in `backend/models/candidate/feature_availability_matrix.json`:
its top-level keys are exactly `schema, training_rows, selection, summary,
promotion_gate, features` — the shape the consumer expects, not the old coarse
one. Confirmed by rerunning the dedicated regression suite added in the same
commit: `backend/tests/unit/test_promotion_feature_evidence.py` — **6 passed**.

Item #25's own evidence table (filed the same day, after this fix) already
shows `compare_candidate_vs_incumbent` running and reporting real gate results
(`serving_feature_availability` genuinely `FAIL`, not a crash) — only possible
if this item was already fixed by the time #25 was written. That table is the
correct current signal for retraining-gate status, not this entry.

**Still open, smaller, unrelated:** `backend/models/candidate/candidate_manifest.json`
still has zero producers and zero consumers anywhere in `backend/` (reconfirmed
2026-08-18) — hand-maintained, referenced by nothing. Not blocking anything
today; revisit only if something starts depending on it.

**Lesson for next session:** re-verify a `docs/DEBT.md` claim against current
code before acting on it — a ledger entry can go stale within the same day it
was filed if a later, unrelated-looking commit happens to fix it.

---

## 24. Rescheduled fixtures wedged the whole fixture-sync tick; mitigation shipped, identity-hash root cause deferred

**Tier:** mitigation = `FIXED` this session. Root cause = `NEXT` — a
kickoff-independent canonical fixture identity key, not a one-line change.
**Found:** 2026-08-16, in a fresh Render deploy log: `fixture_sync: unhandled
error — continuing without fixture data`, traceback ending in
`canonical_identity_service.ensure_canonical_fixture` raising `ValueError:
provider event conflicts with an existing canonical fixture`.

**Root cause.** `ensure_canonical_fixture`'s `fixture_id` is
`_stable_id("fixture", competition_id, kickoff_utc.isoformat(), home_name,
away_name)` — a hash that includes the exact kickoff timestamp. A legitimate
reschedule (broadcaster/league moves the kickoff time, which happens
routinely) changes `kickoff_utc` on the next sync for the same
`provider_event_id`, recomputes a different `fixture_id`, and
`ensure_canonical_fixture` correctly refuses to silently repoint the
existing `ProviderEventMapping` to a new fixture. That refusal is right in
isolation, but `sync_upcoming_fixtures()` called it with no per-fixture
try/except inside its loop, and the loop's single `session.commit()` sits
after the loop — so the raised exception propagated out before commit,
losing every fixture in that tick's batch, not just the rescheduled one.
Same failure shape as item 23 (Elo self-play), found the same day.

**Mitigation shipped (`35ca7bb`):** `sync_upcoming_fixtures()` now catches
`ValueError` around the `ensure_canonical_fixture` call, logs a warning with
the `match_id`/team names, increments `fixture_sync.identity_conflicts`, and
continues to the next fixture. The conflicting fixture's raw `Match` row
(already flushed earlier in the same loop iteration) still commits — only
canonical-identity reconciliation is skipped for that one fixture. Regression
test: `test_canonical_identity_conflict_does_not_wedge_the_batch`
(`backend/tests/unit/test_fixture_sync.py`) — seeds a fixture, resyncs it
with a different kickoff time alongside an unrelated new fixture, and asserts
the second fixture still commits.

**Not done — deliberately deferred.** The identity hash still includes
`kickoff_utc`, so a rescheduled fixture's canonical identity stays
unreconciled indefinitely (not just once) until a kickoff-independent key is
adopted — most likely `(competition_id, season, home_name, away_name)`,
which stays stable across a reschedule for SabiScore's supported
competitions (each is round-robin — at most one home/away meeting per
season pair — so this remains disambiguating; UCL's occasional
same-pairing-twice edge case was judged too rare to design around here).
Changing the hash affects new canonical-identity generation broadly, not
just the conflict path, so it's out of scope for a same-session defensive
fix.

**Blast radius:** was every fixture in whichever sync tick happened to
include a rescheduled fixture (all of them, not just the reschedule) — now
scoped to just that one fixture's canonical-identity reconciliation staying
incomplete (its `Match` row and scheduling data are unaffected).
**Cost:** mitigation, done. Root-cause fix: change `_stable_id`'s inputs in
`canonical_identity_service.py`, re-verify no existing dependents assume
kickoff-derived IDs, size small-to-medium.
**Priority:** medium — reschedules are routine in football, so this will
recur regularly until the identity key changes, but the mitigation means it
no longer costs an entire sync tick's fixtures each time.

---

## 23. 26 matches record a team playing itself — wedged the Elo backfill; code mitigation shipped, root cause confirmed, repair executed — `RESOLVED 2026-08-19`

**Tier:** `RESOLVED 2026-08-19`. Mitigation = `FIXED`. Root cause =
`CONFIRMED`, **not a live code defect** — see below. Repair = **executed
against production**, verified.
**Found:** 2026-08-16, via a live `/health/ready` baseline check ahead of the
Elo Postgres backfill runbook in item 13 — `checks.elo` showed `rows: 0` and
`components.settlement` showed `outcome: "error"`, `last_success_at: null`,
hours after migration `0007_durable_elo_state` deployed.

**Root cause, confirmed via read-only production queries (updated 2026-08-19,
corrects the per-team count below).** 26 rows in `matches` have
`home_team_id == away_team_id` — a team recorded as playing itself. Three
clubs now show up, not two — `fd-team-ligue_1:paris_fc` (2 rows, both dated
2026, the newest and most recent occurrences) had not yet appeared when this
item was first written: `fd-team-serie_a:fc_internazionale_milano` (14 rows),
`fd-team-la_liga:rcd_espanyol_de_barcelona` (10 rows),
`fd-team-ligue_1:paris_fc` (2 rows). The exact failing insert:

```text
duplicate key value violates unique constraint "uq_elo_rating_match_team"
DETAIL: Key (match_id, team_id)=(fdco-3d01b70f3b802e7b, fd-team-serie_a:fc_internazionale_milano) already exists.
```

`sync_elo_from_finished_matches` processes matches oldest-first; the earliest
self-play row (Inter Milan, 2019-09-21) sits ahead of most of the corpus, so
every hourly settlement tick reached the same poison record, and
`apply_finished_match_to_elo`'s bulk insert of `[home_row, away_row]`
collided with itself on `(match_id, team_id)`. The failed flush aborted the
whole session — not just that one match — so `elo_rating_snapshots` stayed
at exactly 0 rows through every single tick since the migration deployed.
This is the "one poison record blocks the whole batch" failure class the
roadmap document's dead-letter-queue rationale names, and the same shape as
the 2026-08-08 fixture-sync 429-on-first-competition incident.

**Mitigation shipped (`291c06a`):** `apply_finished_match_to_elo` now checks
`home_team_id == away_team_id` before attempting the insert, logs a warning,
increments `elo.update.skipped_self_play`, and returns `False` instead of
crashing. `sync_elo_from_finished_matches` now returns a `skipped` count
alongside `processed`, surfaced through `settlement_service`'s existing
`/health` wiring with no new plumbing. Regression tests:
`test_self_play_match_is_skipped_not_crashed`,
`test_sync_skips_self_play_match_and_still_processes_the_rest`
(`backend/tests/unit/test_durable_elo_state.py`) — the second proves a good
match in the same batch as a self-play match still gets its snapshots
committed, i.e. the batch is no longer wedge-able by this bug.

**Root cause, confirmed 2026-08-19 — this is legacy corrupted data, not a
live bug.** Re-ran `historical_backfill_service.TeamIndex.resolve()` (today's
code, unchanged) against the *real* production `teams` rows for all three
colliding pairs (`AC Milan`/`FC Internazionale Milano`,
`FC Barcelona`/`RCD Espanyol de Barcelona`,
`Paris Saint-Germain FC`/`Paris FC`) and it resolves every one of the six
teams to its own, distinct id — no collision reproduces under today's
resolver. Confirmed further via `historical_match_id()` (which hashes the raw
CSV team-name strings, not any resolved id): recomputing it from the raw
`Milan`/`Inter`, `Espanol`/`Barcelona`, and `Paris SG`/`Paris FC` rows in the
already-committed `fd_I1_*.csv` / `fd_SP1_*.csv` / `fd_F1_*.csv` corpus
reproduces the exact corrupted `match_id`s (e.g. `fdco-3d01b70f3b802e7b`)
byte-for-byte. The resolver bug that originally mis-assigned these 26 rows
was fixed by an earlier session (`78c2272`, PR #25 — the alias table's
`"fc"`-as-noise-token stripping and curated aliases); it just never
retroactively corrected rows already committed under the older, buggier
version. Given the Paris FC rows are from the *current* (2025-26) season,
this pairing wasn't fully closed until recently and could plausibly recur —
worth a spot re-check next time `identity_conflicts_skipped` shows a nonzero
count in a fresh `backfill_historical_matches()` run.

**Repair script:** `backend/scripts/repair_self_play_matches.py`
(`--dry-run`/`--apply`/`--database-url`) — a thin
CLI wrapper; the actual logic lives in
`backend/src/services/self_play_repair_service.py` (same split as
`elo_state_service.py`/`replay_elo_from_db.py`, and for the identical
reason: the CLI script sets `os.environ.setdefault(...)` at import time,
which is fine standalone but pollutes the shared process env the moment a
test imports it — confirmed live when the first draft of this repair broke
`test_sqlite_fallback_requires_explicit_opt_in_outside_tests` by leaking
`SABISCORE_ALLOW_INSECURE_FALLBACK=true` process-wide). It also deliberately
does **not** copy `replay_elo_from_db.py`'s
`os.environ.setdefault("DATABASE_URL", "sqlite...")` bootstrap: that pattern
wins over `backend/.env` (env vars outrank dotenv in pydantic-settings), so a
data-repair tool run without an explicit target would silently point at an
empty local SQLite file and report `corrupted_rows_found=0` — indistinguishable
from a clean production database. Instead `--database-url` sets the target
explicitly (also sidestepping shell-specific env syntax: `VAR=x cmd` is
POSIX-only and fails in PowerShell), and the resolved target is echoed with the
password redacted. ⚠️ `replay_elo_from_db.py` still carries the original
unsafe bootstrap — worth the same treatment next time it is touched. Recovers each
corrupted row's original raw team names via `historical_match_id`
(name-keyed, so independent of any resolved id), re-resolves them through a
`TeamIndex` seeded from the live `teams` table, and only updates a row when
the new resolution yields two distinct ids — anything still ambiguous or
unrecoverable is skipped and reported, never guessed. Unit-tested
(`backend/tests/unit/test_repair_self_play_matches.py`, importing the service
module directly, not the script): repairs a known collision, dry-run reports
without mutating, skips a row with no matching CSV, skips a row that still
collides after re-resolution.

**Done — 2026-08-19.** `--apply` was run against the live production
database (`dpg-d9pfv3pt0dsc73djciog-a`, `sabiscore_db_v2`). Output matched
the dry-run exactly: `corrupted_rows_found=26 repaired=26 skipped=0`, all 26
per-row repairs matching this section's descriptions (SERIE_A 14 rows
Milan↔Inter, LA_LIGA 10 rows Espanyol↔Barcelona, LIGUE_1 2 rows Paris
SG↔Paris FC). Verified independently via a **separate, read-only** path
(Render's hosted-Postgres query tool, not the script that wrote the rows):
`SELECT count(*) FROM matches WHERE home_team_id = away_team_id` read `26`
immediately before the run and `0` immediately after. No separate Elo action
needed — `sync_elo_from_finished_matches` will pick the 26 corrected matches
up on its next hourly settlement tick.

⚠️ **Operational finding, same incident:** `backend/.env`'s `DATABASE_URL`
turned out to be stale — it named a Postgres instance id
(`dpg-d95kg3e7r5hc73eh7g6g-a`) that no longer resolves at all (DNS failure,
not the item-31 internal-vs-external-hostname case), and that doesn't match
the one live instance Render's API lists for this workspace
(`dpg-d9pfv3pt0dsc73djciog-a`, free tier, created 2026-08-05, expires
2026-09-04 — free-tier Render Postgres instances rotate). The correct
external connection string (`<instance-id>.oregon-postgres.render.com`, per
item 31's hostname convention) was obtained from Render's dashboard and
passed via `--database-url` rather than relying on `.env`. **Re-check
`backend/.env`'s `DATABASE_URL` against Render's dashboard before trusting
it for the next local operator script** — this is a free-tier database, so
this drift will recur on the next rotation.

**Blast radius:** was 100% of the durable-Elo backfill (item 13) — now
fully closed. Item 13's backfill was already complete (12,762/12,762
eligible, all integrity gates zero) before this repair; these 26 matches
were the only finished matches with no Elo history. Repairing them takes Elo
coverage to genuinely 100% of the corpus once the next hourly settlement
tick processes them.
**Cost:** mitigation, done. Root-cause investigation, done. Repair script,
done and tested. `--apply`, done and verified.
**Priority:** closed.

---

## 22. `the_odds_api` API key leaked in production logs (fixed) + confirmed invalid (401) — **key rotation now confirmed working, 2026-08-17**

**Tier:** log leak = `FIXED`. Key validity = `RESOLVED` — confirmed via live
production evidence, not just an operator report. CLV capture (item 6) is
unblocked and has real data.
**Found:** 2026-08-13/14, from an operator-supplied Render deploy log
(2026-08-13T23:22–23:26 UTC) pasted into a chat session.
**Resolved (confirmed 2026-08-17):** a live Render log query for
`srv-d95kkffaqgkc73f8003g` across 2026-08-14T00:00–2026-08-17T03:00 UTC found
**zero** `401`/`Unauthorized`/odds-error entries — the entire window the
2026-08-13/14 incident excerpt came from and everything since. Positive
evidence, not just absence of errors: a live `odds_service` log line
`Cache hit for live odds: LA_LIGA` (2026-08-16T23:10:13Z, only possible after
a prior successful fetch populated the cache), `GET /health` `components.
clv_capture.outcome` now reads `"ok"` (was the documented `"never_run"`), and
a direct read-only query against `market_snapshots` on the production DB
(`dpg-d9pfv3pt0dsc73djciog-a`) returned **4 real rows, all
`is_closing_line=true`**, captured 2026-08-16T10:06–17:05 UTC. The rotation
reported across several operator-supplied documents this week is therefore
independently confirmed, not just repeated. Still below `clv_service.py`'s
`_MIN_CLV_SAMPLE_SIZE=10` floor for a real CLV summary — that's a volume gate
working correctly, not a defect. Formal `status: VERIFIED` on the provider
still requires an explicit `providers doctor --provider the_odds_api
--validate-live` probe (unrun — needs the real key, which isn't accessible
from a read-only audit context); this evidence is operational, not the
formal probe result.

**Attempted 2026-08-18, still unrun against the real credential.** Ran
`providers doctor --provider the_odds_api --validate-live` locally
(`ALLOW_SQLITE_FALLBACK=true` to get past the CLI's DB-import boundary — the
local `DATABASE_URL` points at a Render-internal hostname unreachable outside
Render's network, an existing local-tooling gap, not new). Result: **HTTP 401**
against whatever `THE_ODDS_API_KEY`/`ODDS_API_KEY` is in local `backend/.env`.
**Does not contradict the resolution above.** The rotated key lives in Render's
environment; nothing establishes that local `backend/.env` was ever updated
with the same value after the 2026-08-17 rotation, and the production evidence
above (real cache hits, real `market_snapshots` rows, `clv_capture.outcome:
"ok"`) is all *later* than this session's local 401. The formal `VERIFIED`
probe still needs to run somewhere holding the real Render-configured key (a
Render shell, not a local checkout) — still not accessible from here.

Two findings from the same log excerpt:

**(a) Log leak, fixed.** Every `the_odds_api` request logged its full URL,
including `?apiKey=<key>` in cleartext, at INFO level:

```text
httpx - INFO - HTTP Request: GET https://api.the-odds-api.com/v4/sports/soccer_spain_la_liga/odds?apiKey=<redacted>&regions=uk%2Ceu&markets=h2h&oddsFormat=decimal "HTTP/1.1 401 Unauthorized"
```

Root cause: `backend/src/api/main.py`'s `logging.basicConfig(level=logging.INFO, ...)`
sets the root logger level with no per-logger override, so the third-party
`httpx` package's own request-line logger (which httpx never redacts)
propagates straight to stdout/Render logs on every call. `core/logging.py`'s
`configure_logging()` already suppresses `uvicorn.access` the identical way
but is never called by `main.py` (a separate, pre-existing duplication — not
fixed this session). Only `the_odds_api` was exposed: `api_football` and
`football_data_org` use header auth (`x-apisports-key` / `X-Auth-Token`),
which httpx's INFO log line never includes (method/url/status only, never
headers); ESPN is keyless. Fixed with one line in `main.py`:
`logging.getLogger("httpx").setLevel(logging.WARNING)`, mirroring the
existing `uvicorn.access` precedent.

**(b) Key confirmed invalid — first real evidence, not code-fixable.** Every
request in the same log excerpt returned `401 Unauthorized`. The auth
mechanism in `the_odds_api.py` is correct (query-param `apiKey` is
the-odds-api.com's only scheme; `config.py`'s `AliasChoices` accepts both
`THE_ODDS_API_KEY`/`ODDS_API_KEY`; no truncation or mis-naming anywhere in
the request path). CLAUDE.md's "5 of 5 [providers] enabled" /
`CONFIGURED_UNVERIFIED` framing (vΩ.43) only ever meant the enable flag was
on and a non-empty key string was present — `PROVIDER_LIVE_TESTS=false`
means it was never actually probed end-to-end. This is the first live
confirmation, and it's negative. This is why `clv_capture` reads
`outcome:"never_run"` (item 6) — a second, more specific blocker than the
previously-documented Blueprint-sync story.

**Operator action required:** rotate the key at the-odds-api.com's dashboard,
then update `THE_ODDS_API_KEY`/`ODDS_API_KEY` in Render's environment
variables and redeploy. Treat the value visible in the pre-fix logs as
compromised regardless of root cause — it was both in Render's log retention
and pasted into a chat session.

**Blast radius:** (a) none going forward — fixed; historical log lines
already written are unaffected by this fix. (b) CLV capture (item 6) and any
Phase I market-benchmark work stay blocked until the key is rotated.
**Cost:** (a) done. (b) a few minutes across two dashboards, operator-only.
**Priority:** (a) closed. (b) high — it's the only remaining DATA-FED
prerequisite for CLV/market-comparison work.

---

## 20. A Render service builds the monorepo at root and is not in `render.yaml`

**Tier:** `FIX-NOW` / P0 — it crash-loops on every push to master.
**Found:** 2026-08-12, from an operator-supplied Render deploy log for commit
`5de6228`.

A Render web service clones the repo **at root** (no `rootDir`), runs
`pnpm install --frozen-lockfile; pnpm run build` on Node 24.14.1, builds
`@sabiscore/web` + `@sabiscore/scraper` successfully — then dies:

```text
==> Running 'pnpm run start'
 ERR_PNPM_NO_SCRIPT_OR_SERVER  Missing script start or file server.js
==> Exited with status 1
==> No open ports detected, continuing to scan...
```

`render.yaml` declares only two services: `sabiscore-api`
(`rootDir: backend`, pip + `alembic upgrade head && uvicorn`) and the
`sabiscore-evidence-acquisition` cron. **Neither matches this log.** The
service is therefore dashboard-created and outside blueprint management —
the same drift class as the operator-managed `DATABASE_URL` recorded above,
and consistent with the Blueprint-sync approval that has been outstanding
since vΩ.12.

**Immediate half fixed (2026-08-12):** root `package.json` had no `start`
script at all (only `apps/web/package.json` did), so the service could never
boot regardless of configuration. Added
`"start": "pnpm --filter @sabiscore/web start"`. Verified locally that
`PORT=4123 pnpm run start` binds to `$PORT` and serves `GET /api/health` →
200, which is exactly the port-binding contract Render's "No open ports
detected" scan was failing.

**Operator decision still required — do not skip this.** Adding the script
stops the crash loop, but it does **not** answer whether this service should
exist. `CLAUDE.md`'s canonical production shape puts `apps/web` on **Vercel**
and only `backend/` on Render. A second, blueprint-invisible copy of the
frontend on Render is either:

1. an intentional migration off Vercel — in which case it belongs in
   `render.yaml` with an explicit `startCommand`, and the Vercel project's
   role must be restated; or
2. a stale experiment that should be deleted, because it rebuilds the whole
   monorepo on every master push and its failures look identical to a
   backend outage in the dashboard.

⚠️ **CORRECTED 2026-08-12, same session.** An earlier version of this entry
claimed the crash loop "also explains why `sabiscore-api-bav1.onrender.com`
still reports `sha: 229efbc`". **That was wrong.** The backend subsequently
reached `5de6228` — and stayed healthy — while still running code that did
*not* contain the root `start` script, proving the API service was never
blocked by it. The two services are independent: `sabiscore-api` was simply
slow (free-tier `pip install` of the full runtime set takes many minutes),
and I read a slow deploy as a failed one. The real lesson is narrower than
the one first written here: **before attributing a stale `sha` to a specific
cause, confirm the timeline — a Render free-tier deploy can legitimately take
10–15 minutes, so "not yet" and "failed" look identical for a long window.**
Check the deploy log for that service, not a sibling's.

**Update 2026-08-13 — new symptom, decision made.** An operator-supplied
Render deploy log shows the `384f9f4` root `start` script fix holds — the
service now binds `$PORT` and boots cleanly (`Ready in 3.3s`) — but it still
dies roughly 4 minutes later (`ELIFECYCLE Command failed`), with no further
detail captured in the log excerpt. This is a **different failure** from the
original "no start script" crash, and it was not investigated further this
session: `render.yaml` still declares only `sabiscore-api` (Python) and the
`sabiscore-evidence-acquisition` cron, and `apps/web` is confirmed live and
correct on Vercel (production alias `sabiscore.com`, `vercel --prod` output
this session shows `Aliased https://sabiscore.com`, and
`web-lac-theta-42.vercel.app/api/health` independently reports `sha` matching
current `master` HEAD). With Vercel already canonical and healthy, the
decision is **suspend → verify → delete**, not further diagnosis of the
Render copy's runtime crash.

**Operator checklist (dashboard-only — no code change can execute this):**

1. In the Render dashboard, find the web service that is **not**
   `sabiscore-api` and **not** the `sabiscore-evidence-acquisition` cron.
2. Confirm its build/deploy log matches the signature already captured here:
   `pnpm install --frozen-lockfile`, `pnpm run build` building
   `@sabiscore/web` + `@sabiscore/scraper`, then `pnpm run start` →
   `next start`.
3. Record (privately, values not needed) whether it carries any of
   `REDIS_URL`, `DATABASE_URL`, `API_FOOTBALL_API_KEY`,
   `UPSTASH_REDIS_URL` — if the exposed Redis Cloud credential (item 15) was
   ever pasted into this service specifically, note that before touching
   item 15's revocation step.
4. **Suspend** the service (not delete yet).
5. Re-check `https://sabiscore.com` and
   `https://web-lac-theta-42.vercel.app` both still serve normally — they
   should be completely unaffected, since neither depends on this service.
6. Only after confirming step 5, **delete** the service and remove it from
   the Render dashboard's service list.

This item stays open until an operator actually performs steps 1–6 above —
adding the start script only stopped the crash-on-boot symptom, it did not
answer whether the service should exist, and code cannot make a dashboard
deletion.

**Blast radius:** every push to master triggers a failing build; the live
backend silently stays on the previous commit.
**Cost:** small for the script (done); the architectural decision is made
(suspend/delete) — remaining cost is five minutes in the Render dashboard.
**Priority:** P0 for the decision — until it is made, no push to master
reliably reaches production.

Format per entry: **Tier** (`FIX-NOW` / `NEXT` — named trigger / `ARCH-DEBT` — needs an
ADR / `ACCEPTED` — rationale + review date), owner, blast radius, engineering cost,
user impact, priority. An entry without a trigger is not `NEXT`, it's `ACCEPTED` in
disguise — say so honestly.

---

## 21. Frontend residuals left deliberately after the 2026-08-13 truthfulness pass

**Tier:** `ACCEPTED` (a) / **CLOSED 2026-08-14** (c) / **CLOSED 2026-08-22** (b).
**Found:** 2026-08-13, while fixing the `LIVE`-badge, page-title, mobile-overflow
and selection-UI defects recorded in `CHANGELOG.md` for that date.

Three things were found and understood; (a) was deliberately left unchanged,
(b) and (c) were later fixed once each item's own named trigger fired.
Recording all three so a future session does not re-derive the context.

**(a) `BigMatchesCarousel` fetches while collapsed.** On the homepage the match
selector is wrapped in a native `<details>` (`app/page.tsx`, the
"Explore a manual matchup" accordion). React mounts `<MatchSelector />`
unconditionally and the browser merely hides it via the UA stylesheet, so the
carousel's `useQuery(["big-matches-carousel"])` issues its
`getUpcomingMatches()` request on every homepage load whether or not the user
ever expands the section. It is one bounded, cached (`staleTime` 5 min) request
that React Query dedupes, so the cost is small and it is **not** a correctness
or truthfulness issue — but it is avoidable. The fix is to gate the fetch on the
`<details>` open state (or lazy-mount the selector), which needs the accordion to
become a controlled component. Not worth the added state today.

**(b) `monitoring-dashboard.tsx` / `performance-dashboard.tsx` are orphaned —
CLOSED 2026-08-22.** Neither was imported anywhere in `apps/web/src` (repo-wide
grep), and `app/monitoring/page.tsx` is a pure `redirect("/performance")`. They
also fetched endpoint shapes (`/api/metrics`, `/api/drift`) that no longer
matched the `/api/model-performance*` surface `/performance` actually uses.
Deleted, along with `confidence-band-chart.tsx` (same directory, same
zero-importer status — not named in the original entry, found while confirming
these two, and dead independently of them). Also deleted `apps/web/pre-deploy-check.ps1`,
found in the same pass: an unwired PowerShell script (not referenced by any
`package.json` script, CI workflow, `Makefile`, or `render.yaml`/`vercel.json`
target) whose "critical files" checklist still named `src/lib/ml/tfjs-ensemble-engine.ts`
and `src/lib/betting/kelly-optimizer.ts` — both deliberately deleted in
prior sessions (TF.js browser inference and the frontend Kelly module) — so it
had been failing its own checklist, silently, unused, for months. `pnpm lint`
and `pnpm typecheck` both exit 0 after all four deletions.

**(c) `phase8-analytics-panel.tsx` still labels a tier `"Live"` — CLOSED
2026-08-14.** The named trigger fired: `Phase8AnalyticsSection` renders this
panel unconditionally as a full `<section>` on the primary `/match/[id]`
result page (no collapse/accordion gating it), which is exactly "promoted out
of diagnostics into a primary user surface." A separate audit the same session
also found a second live instance of the identical `edge_quality_score`
mislabeling class in `match-selector.tsx`/`insights-tease-strip.tsx` — three
occurrences total, matching this entry's own "or a third copy of this helper
appears" trigger. Fixed by renaming `freshnessLabel()`'s `"Live"` →
`"Fresh"` and `groupFreshnessChip()`'s `"LIVE"` → `"FRESH"` (pure string
rename, thresholds/colors unchanged) — **not** a cross-file helper extraction;
the three freshness implementations have different return shapes for
different purposes, and unifying them is a larger refactor than this
truthfulness fix required. Both helpers are now exported and pinned by
`phase8-analytics-panel.test.tsx`. See `CHANGELOG.md` (2026-08-14) for the
full three-file fix.

**Blast radius:** (a) one redundant request per homepage load; (b) none
remaining — dead code deleted; (c) none remaining — fixed.
**Cost:** (a) small but needs a controlled accordion; (b) done; (c) done.
**Priority:** low for (a); none remaining for (b)/(c).

---

## 17. Offline ML research environment is only partially installed

**Tier:** `NEXT` — trigger: reliable package-index access on a Python 3.11-3.13
host. **Verified:** 2026-08-10.

`backend/requirements-training.txt` now defines the isolated research stack and
`backend/scripts/verify_training_stack.py` distinguishes importability from model
certification. CatBoost 1.2.8 and SHAP 0.49.1 import in the local Python 3.12
environment. MLflow, Evidently, Great Expectations, XGBoost, LightGBM, and Optuna
did not complete installation within the bounded network attempts. The environment
was reconciled to the committed scikit-learn 1.5.2 pin and `pip check` reports no
broken requirements, but the full requirements set is not yet installed.

**Release impact:** none for the API runtime, which does not require or eagerly
import this stack. **Model impact:** candidate research, SHAP validation, drift
work, and MLflow experiment capture remain blocked locally. Installing these
packages does not permit model promotion; the real-settlement and active-generation
gates in item 14 still apply.

## 18. Scraper production cron is wired but intentionally inactive

**Tier:** `NEXT` — trigger: approved source-policy + storage credential
provisioning + retention controls documented in deployment record.
**Verified:** 2026-08-10.

`render.yaml` now defines `sabiscore-evidence-acquisition` (Docker cron) and
worker runtime assets exist in `apps/scraper/`, but
`SCRAPER_PRODUCTION_ENABLED=false` keeps execution fail-closed by default.
Code readiness exists; operational approval and secrets enablement do not.

**Release impact:** none for current API runtime while disabled.
**Risk if prematurely enabled:** unapproved source ingestion and uncontrolled
artifact retention/cost.

## 14. Apex candidate artifacts are quarantined and not certified

**Tier:** `FIX-NOW` before model promotion. **Found:** 2026-08-09.

Generated v5-named binaries were written over the active artifact paths before a
qualifying promotion decision. The active binaries have been restored and the
generated files moved to `backend/models/candidate/` with an explicit
`UNVERIFIED_CANDIDATE` manifest.

The required chronological run is now executed: training ends in 2023/24,
calibration is 2024/25, and the untouched evaluation season is 2025/26. The exact
stacked served head passed probability-simplex, input-responsiveness, coherent
price-perturbation, and positive mean RPS-improvement gates. Promotion still
fails three hard gates:

- RPS regressed in Bundesliga, EPL, and Ligue 1 (candidate won only 3/6 leagues);
- the candidate beat the coherent market baseline in 0/6 evaluated league rows;
- serving availability fails with 11 schema-misaligned positions and four
  always-data-gap slots; 24/68 training slots were defaulted/non-variable.

Evidence is versioned in `training_report_real.json`, `comparison_report.json`,
and `feature_availability_matrix.json`. Eredivisie remains pooled fallback; UCL
remains generic and capped at `ACTIONABLE`.

**Release rule:** candidate promotion is forbidden while
`promotion_permitted=false`. Do not rename or copy candidate files into the active
directory to make deployment pass. The active v5 generation is hash-locked but
formally `UNVERIFIED`; until it is certified, both verdict engines must keep every
public stake at zero and the distinct RL advisory integration must equivalently
abstain/zero its public recommendation.

## 15. Redis credential incident and Render configuration are operator-blocked

**Tier:** `FIX-NOW` / P0. **Found:** 2026-08-09. **Second call site found and
fixed:** 2026-08-10.

A supplied Render log contained a complete Redis URI. A later Render build log
shows `REDIS_URL` is not a valid `redis://`, `rediss://`, or `unix://` URL and the
deployed process exits during import. Central redaction and malformed-URL safe
degradation in `core/cache.py`'s tiered `RedisCache` were already in place, but a
live 2026-08-10T14:22 Render crash log traced a second, independent, unguarded
call site: `ModelOrchestrator.__init__` (`models/orchestrator.py`) called
`redis.from_url(redis_url, decode_responses=True)` directly, with no try/except.
Because `models/__init__.py` imports `ModelOrchestrator` eagerly, and
`ModelOrchestrator` is instantiated as a module-level singleton
(`orchestrator = ModelOrchestrator()`), any import of `src.models` — including
every request-path import of `models.feature_registry` — crashed the whole
process the instant `REDIS_URL` was invalid or unconfigured. Fixed the same way
as `cache.py`: the connection attempt is wrapped in
`(RedisError, ConnectionError, TimeoutError, ValueError)`, degrading to a minimal
`_InMemoryRedisAdapter` (get/setex/lpush/ltrim/llen/lrange — the only methods the
league models' prediction cache actually calls) instead of raising. Regression
tests in `backend/tests/unit/test_model_orchestrator_redis_fallback.py`. Code
cannot rotate the provider credential or modify the protected Render secret.

**Required operator sequence:** provision replacement Redis; set a complete
`rediss://` Render secret without printing it; prove TLS connectivity and external
cache readiness; revoke the exposed credential; redeploy; then prove current logs
remain redacted. Record provider-side replacement and revocation evidence privately.
Production remains blocked until every step is recorded.

**Update 2026-08-13 — verified runbook, migration not yet proven.** An
operator-supplied transcript worked through migrating to Upstash. Its
technical claims were checked against real code this session and hold:
`backend/src/core/config.py:174-175` does raise
`"production Redis requires a rediss:// URL"` when
`app_env == "production"` and the URL isn't `rediss://`, and
`backend/src/core/cache.py:189` does log
`"Redis (tier-1) connection established successfully"` only after a real
`PING` — the transcript's diagnostic advice is grounded, not guessed.
Superseding the freeform transcript with the corrected sequence:

1. Locally, clear the process env var by its **correct** name — `REDIS_URL`,
   not a mis-escaped `REDIS\_URL` (a real mistake caught mid-transcript;
   PowerShell doesn't need underscore escaping in a string).
2. Confirm which Render service is being edited before touching anything —
   it must be `sabiscore-api` (Python/FastAPI, `rootDir: backend`), **never**
   the undeclared Node service tracked in item 20. A pasted deploy log this
   session was from that other service and was initially misread as this
   one — see item 20's 2026-08-13 update.
3. Set the new Upstash `rediss://` URL as `sabiscore-api`'s `REDIS_URL` in
   the Render dashboard, keep `REDIS_ENABLED=true`, choose **Save and
   deploy** (not "Save only" — that only stores the value for a future
   deploy).
4. Watch the deploy log for the confirmed-real line
   `"Redis (tier-1) connection established successfully"`. Its absence, or
   `"production Redis requires a rediss:// URL"` appearing instead, means
   the guard rejected the value — fix the URL scheme, don't bypass the guard.
5. Re-run `/health/ready` and read `components.cache.metrics`' tier-1 flags
   specifically — **not** just the top-level `cache: "Connected"` string,
   which the 2026-08-12 CLAUDE.md ground-truth entry already documents as
   insufficient on its own (it read "Connected" once even while Redis was
   genuinely absent).
6. Only after step 5 confirms tier-1 is live, revoke the old Redis Cloud
   credential in its own console, then strip the stale `REDIS_URL` line from
   the local `backend/.env` (`Select-String` to confirm no match remains).
7. **Local re-test footgun:** `Settings.model_config.env_file` in
   `config.py` is `(project_root/.env, backend/.env)` — the second entry is
   cwd-relative, so `REDIS_URL` can resolve differently depending on whether
   a local script runs from the repo root or from `backend/`. Confirm from
   both cwds after editing, don't trust one.

Local Upstash connectivity (TLS, PING, write/read/delete) was reported PASS
in the transcript but is **not independently verified here** — this session
had no Upstash credential to test against. `sabiscore-api`'s `REDIS_URL` has
**not** been confirmed migrated as of this entry; a live probe
(2026-08-13, ~18:4x UTC) found `sabiscore-api-bav1.onrender.com` returning
`503` on `/health`, `/health/ready`, and `/api/v1/providers/health` alike —
consistent with either an in-progress redeploy from exactly this migration,
or an unrelated cold start/crash. Re-probe before concluding either way; see
the dated entry in CLAUDE.md for the exact snapshot.

A user-supplied screenshot of the Redis Cloud console (`cloud.redis.io`,
database `sabiscore-database`, ID `13753214` — the *old* provider being
migrated away from, not Upstash) confirms **Transport layer security (TLS)
is Off** and **CIDR allow list is Off** on that instance. This is exactly
why `sabiscore-api`'s production guard rejects it
(`config.py:174-175`, `"production Redis requires a rediss:// URL"` — a
non-TLS Redis Cloud endpoint is `redis://`, never `rediss://`). Confirms the
diagnosis; does not change the runbook above.

## 16. Release infrastructure and historical-secret gates remain partially closed

**Tier:** `FIX-NOW` / P0 before merge or deployment. **Verified:** 2026-08-10.

- Current-tree Gitleaks passes. Full-history Gitleaks still reports exactly two
  historical `backend/.env.example` fingerprints: `generic-api-key:17` at
  `d604c13` and `generic-api-key:10` at `67ed0ab`. Neither may be waived until
  the credential owner supplies dated revocation evidence for that exact value.
- Historical required-job runs still include `runner_id: 0` entries with the
  annotation `The job was not started because your account is locked due to a
  billing issue.` That dispatch blocker has now cleared: canonical Linux CI run
  `31437373215` (head `fe46d97`) completed with all five jobs green
  (Secret Scan, Backend Lint/Typecheck/Tests, Scraper Validate/Tests,
  Web Lint/Typecheck/Build, Playwright Smoke). Keep this item open only for the
  remaining infra/deploy proofs below.
- **Update 2026-08-14:** the current deployed SHA `e0f89ae` has genuine successful
  runs for canonical CI, backend, web, scraper, Playwright, Secret Scan, Gitleaks,
  model artifacts, and large-file checks on named runners with real steps. Billing
  dispatch is closed for this SHA. This does not prove CI for a new candidate SHA,
  nor revoke either historical credential.
- Docker Compose configuration passes. Fresh backend and web image retries ran
  for more than five and three minutes respectively without producing a current
  image. The only `sabiscore-backend:verify` tag is dated 2026-07-15 and
  `sabiscore-web:verify` does not exist.
- The backend production install surface is now trimmed to
  `backend/requirements.runtime.txt` in both `render.yaml` and the production
  Docker stage, removing optional research/browser/Kafka packages from the API
  boot path. This reduces build surface area but does **not** by itself prove a
  fresh backend/web image build; the image-proof gate remains open until new
  tags exist from the current release candidate.
- Alembic reports one head (`0006_canonical_league_ids`), but the production
  `upgrade head` connection attempt timed out after 120 seconds, so `check` and
  migration-head proof remain absent.
- The canonical `make verify` cannot execute faithfully on this Windows host
  because its recipe assumes POSIX shell syntax and `jq`. Use canonical Linux CI
  via `.github/workflows/ci.yml` (or `scripts/run-canonical-ci.ps1`) as the
  source of truth for merge/release gates.

**Release rule:** keep PR #5 unmerged and do not activate Render or promote a
Vercel deployment while any item above remains unproven.

## 12. Certified artifacts were trained on synthetic data — RESOLVED, with a residual

**Tier:** `ACCEPTED` — root cause fixed 2026-08-08 (retrain). Kept as the incident
record; the residual feature-coverage gap is tracked as item 13 below.
**Found:** 2026-08-08. **Resolved:** 2026-08-08, same day.

**Cause.** `backend/data/processed/*_training.csv` — the corpus behind every
committed `*_ensemble_v5_phase7.pkl` — is 500 rows of `np.random.randn()` noise
under 236 columns (`form_0`, `xg_7`, `fatigue_3`) that appear nowhere in the
canonical feature registry. The models therefore responded to only 4 of 68 inputs,
and the two enrichment parquets feeding those 4 are keyed by synthetic placeholder
team ids that never join to a real fixture — so every live fixture received a
byte-identical prediction (`0.4162 / 0.4155 / 0.1683`). Scored on real held-out
fixtures the incumbents landed at 0.20–0.41 accuracy, at or below always
predicting the home side. The "51% accuracy" in the artifact metadata was measured
against noise.

**Fix.** Retrained on the 12,765 real matches committed under
`backend/data/cache/fd_*.csv` via `backend/scripts/train_on_real_matches.py`,
computing only the features serving actually resolves (through the same shared
helpers, replicating `_get_team_stats`'s window semantics), with strictly forward
history accumulation and a most-recent-season temporal holdout. Candidate beat
incumbent on RPS in **5 of 5** leagues (mean +0.0453); responsive inputs
4/68 → 21–22/68. Eredivisie, which has one season and no holdout, uses a pooled
all-league model annotated as such. Reproducible via
`scripts/compare_candidate_vs_incumbent.py`. Pinned by
`tests/unit/test_model_differentiates_fixtures.py`.

**What this does NOT fix** — see item 13. The model is now sound, but several
canonical evidence families still remain unavailable at prediction time. The
previous note that market features were absent is stale: serving now fetches one
coherent 1X2 market, projects `derive_market_features(...)`, and marks
`MARKET_FEATURES_14` resolved. Head-to-head, venue, and Elo/tactical evidence
remain incomplete, so the artifact still holds those slots at registry defaults
by design and cannot lean on them yet.

---

## 13. Serving still has an unresolved canonical feature family — tactical remains; durable Elo code is ready for runtime backfill

**Tier:** Elo = `RESOLVED 2026-08-19` — backfill is **complete in production**, verified by read-only query: 12,762 of 12,762 eligible finished matches processed (100%), 25,524 snapshot rows (exactly 2 per match), 160 teams, cursor at 2026-08-17. All eight mandatory integrity gates read **zero** (`partial_one_row_matches`, `processed_not_exactly_two_rows`, `duplicate_match_team_pairs`, `orphan_snapshot_match_ids`, `orphan_snapshot_team_ids`, `snapshot_team_not_home_or_away`, `snapshot_match_date_mismatch`, `snapshot_league_mismatch`). Per-league: EPL 2,660 / LA_LIGA 2,655 / SERIE_A 2,646 / LIGUE_1 2,335 / BUNDESLIGA 2,142 / **EREDIVISIE 324** — Eredivisie was 0/324 at the 2026-08-17 audit and self-resolved exactly as the global-FIFO ordering predicted, confirming that entry's "do not special-case a league" call was right. The 26 self-play rows named here were repaired in production 2026-08-19 (item 23, now `RESOLVED`) and will reach 100% Elo coverage on the next hourly settlement tick. Head-to-head and home venue resolved 2026-08-11. Tactical/StatsBomb remains unresolved (`NEXT`).
**Owner:** unassigned.
**Found:** 2026-08-08, while establishing the retrain's feature set.

The prior version of this item claimed the 14 canonical market fields were still
absent and reused a stale served-feature count. That is no longer accurate.
`UpcomingMatchFeatureProjector.project_match_features()` now calls
`derive_market_features(...)` and marks `MARKET_FEATURES_14` resolved, with the
contract pinned by `backend/tests/test_staleness_and_market_wiring.py`,
`backend/tests/test_feature_gap_detection.py`, and
`backend/tests/unit/test_feature_registry.py`. Re-derive any exact
served-feature count from code before using this item in retrain planning.

**Update 2026-08-11:** head-to-head and home venue are also now resolved.
`UpcomingMatchFeatureProjector._get_h2h_stats()` and `._get_home_venue_stats()`
(`backend/src/services/upcoming_match_feature_service.py`) query `Match` history
directly and are wired into `project_match_features()`; formulas were cross-checked
against `backend/src/data/transformers.py` for train/serve parity. Covered by
value-asserting tests in `backend/tests/test_feature_gap_detection.py`
(`test_get_h2h_stats_returns_computed_values_for_seeded_meeting`,
`test_get_home_venue_stats_returns_computed_rates`, plus a none-with-no-history
guard for h2h). Four cross-signal features also resolve incidentally once their
inputs are available: `h2h_market_agreement`, `venue_market_combo`,
`form_market_agreement_home`, `form_market_disagreement`.

The remaining missing family of genuine football evidence is:

| Family | Count | Why it is absent |
|---|---|---|
| ~~Head-to-head~~ | ~~5~~ | **Resolved 2026-08-11** — see above. |
| ~~Home venue record~~ | ~~4~~ | **Resolved 2026-08-11** — see above. |
| Elo | 4 | **Code-fixed 2026-08-16** — live serving now reads durable real-`Team.id` snapshots from PostgreSQL; production migration/backfill is still an operator verification gate. |
| Tactical / StatsBomb | 4 | Still backed by the stale/synthetic offline cache; requires a separate corpus regeneration and point-in-time parity review. |

**2026-08-16 update:** production Elo no longer depends on the local Parquet as its
serving authority. Migration `0007_durable_elo_state` adds `elo_rating_snapshots`;
`elo_state_service.py` reads/writes ratings by real `Team.id`; settlement applies
newly finished matches idempotently and chronologically; and
`replay_elo_from_db.py` now requires explicit `--apply` (default `--dry-run`) for
historical backfill. The Parquet engine remains offline/backward-compatible tooling.

**2026-08-16 update (2):** the backfill wasn't merely awaiting verification —
it was permanently wedged at 0 rows by a data-integrity bug. See item 23 for
the full diagnosis and the shipped mitigation. With that fix in, the hourly
settlement-coupled trickle (`sync_elo_from_finished_matches`, 500/tick) can
make real forward progress against the ~12,760 good matches; full coverage
is expected in roughly a day of background operation, no operator `--apply`
required unless faster coverage is wanted. Re-check `checks.elo.rows` in
`/health/ready` before treating this item as resolved — it was still
unverified as of this update.

**Blast radius:** prediction quality. Once migration + backfill are verified in the
target DB, the four Elo features can resolve from durable real identity. Tactical /
StatsBomb remains the residual family.
**Cost:** production operator action: migrate, dry-run, apply backfill, then inspect
readiness/Elo resolution. StatsBomb regeneration is separate.
**Impact:** moderate until DATA_FED/VERIFIED in production; no fabrication because
unresolved Elo remains a data gap.
**Priority:** high for production backfill verification; medium/low for tactical
regeneration depending on measured incremental value.

---

## 0. Canonical league_id storage — `_LEAGUE_META` stored fd.org codes

**Tier:** `ACCEPTED` — fixed 2026-08-08 (WP-A). Kept as incident record per convention.
**Found:** 2026-08-08, live probe of Eredivisie (9 DB rows, all `LEAGUE_POLICY_UNAVAILABLE`).
**Fixed:** `fixture_sync_service.py:_LEAGUE_META` tuple[1] changed from fd.org code
(`"DED"`, `"PL"`, `"PD"`, `"BL1"`, `"SA"`, `"FL1"`, `"CL"`) to canonical SabiScore ID
(`"EREDIVISIE"`, `"EPL"`, `"LA_LIGA"`, `"BUNDESLIGA"`, `"SERIE_A"`, `"LIGUE_1"`, `"UCL"`).
Alembic migration `0006_canonical_league_ids` renames existing League rows in the live DB
and cascades to `teams.league_id`, `matches.league_id`, `league_standings.league`.
`clv_capture_service._fd_code_to_canonical()` updated to an identity map (was a translation;
now `_LEAGUE_META` already stores canonical IDs directly). Test: `test_synced_league_id_is_canonical`.
**Root effect:** Eredivisie capability probe now returns `unverified_no_fixtures` → `verified`
once `get_next_upcoming_fixture()` can match canonical IDs; EPL/La Liga unblocked as their
sync windows open. Blast radius was every prediction path via `get_league_policy()` and
`full_analysis.py`'s model artifact lookup.

---

## 10. Offline Elo / StatsBomb artifacts were frozen at 2024-06-02 and synthetically keyed

**Tier:** `NEXT` — **Elo code path fixed 2026-08-16; production migration/backfill not yet independently verified.** StatsBomb remains offline debt. The historical incident below is retained because the legacy Parquet files still exist for offline/backward-compatible tooling.
**Owner:** unassigned.
**Found:** 2026-08-08, tracing why STALE_REQUIRED_EVIDENCE fired on 100% of fixtures.

**⚠️ Correction (2026-08-08, later same day): staleness was never the main defect.**
Both parquets are keyed by **synthetic placeholder team ids** — `bundesliga_home_0`,
`bundesliga_team_3` — not real `Team.id` values. `EloEngine.get_context()` and
`StatsBombAggregator.get_team_features()` therefore find zero rows for every real
fixture and silently return the neutral 1500/1500 baseline. The 2024-06-02 end date
is real but secondary: even a perfectly fresh artifact with these ids would join to
nothing. A regeneration run must re-key by `Team.id`, not merely extend the dates.

Two related fixes landed the same day: `elo_parquet_path`/`statsbomb_cache_path` were
resolving relative to the CWD and so weren't loading **at all** locally (item 12), and
`EloContext` now carries `home_resolved`/`away_resolved` so an unresolved rating is
reported as a `data_gap` instead of publishing 1500/1500 as an observation
(`backend/tests/unit/test_elo_context_resolution.py`).

`data/processed/statsbomb_features_cache.parquet` (2,058 rows) and
`data/processed/elo_ratings.parquet` (4,116 rows) both end **2024-06-02** — the whole
offline artifact set was frozen at the end of the 2023/24 season. Consequences:

- StatsBomb supplies 2 of the 65 live features (`home_pressing_intensity`,
  `progressive_carry_diff`); both are additionally forced to DATA_GAP because
  `statsbomb_staleness_max_days` is exceeded. `shot_quality_diff` is a permanent
  DATA_GAP by design (`PHASE7_FEATURES_ALWAYS_DATA_GAP`), unrelated to this.
- The 4 Elo features come from `EloEngine`, which reads the parquet — so the Elo
  context card and `elo_difference` are computed against ratings ~2 years stale.

vΩ.44 stopped this from *blocking* every analysis (the staleness gate now
distinguishes enrichment age from model-input age — see CHANGELOG), so the impact is
now degraded enrichment rather than total abstention. But it is still real signal
loss on 6 of 65 features.

`EloEngine.update_after_match()` already exists and persists post-match updates, and
as of vΩ.44 there are 12,765 real completed matches in the database to replay — so
regenerating Elo is now a scripted replay rather than a data-sourcing problem.
Regenerating StatsBomb needs the open-data corpus re-cloned (offline, large).

**2026-08-16 durable-Elo correction:** live feature serving has been moved to the
PostgreSQL `elo_rating_snapshots` authority rather than relying on this Parquet.
Settlement now advances Elo from newly finished matches with match/team idempotency,
and the historical replay script persists the same real-ID state only when
`--apply` is explicitly supplied. This reaches **EXISTS/WIRED** in this snapshot;
production `alembic upgrade head`, replay, row coverage, and live fixture resolution
must still be observed before marking it DATA_FED/VERIFIED. The stale StatsBomb
portion of this item remains unchanged.

**2026-08-08 correction — blast radius was wider than "6 of 65 degraded" for one
path.** `GET /api/v1/upcoming/matches` (the endpoint behind the homepage fixture
list) built its feature vector via the bare `project_match_features()`, which by
design never calls `EloEngine`/`StatsBombAggregator` at all — so on that specific
path these 6 features (plus the whole Phase-8 block) weren't just stale, they were
completely absent *and* invisibly excluded from `data_gaps` (the bare method's own
`_CALLER_RESOLVED_FEATURES` exclusion assumes a caller-side merge that never ran).
Same-valued near-default feature vectors across different fixtures were the direct,
visible symptom (every homepage fixture card showing an identical edge figure).
Fixed by switching that call site to `build_live_feature_vector()`, the wrapper
every other prediction surface already used — the upcoming-fixtures path now
surfaces and honestly gaps Elo/StatsBomb exactly like `full_analysis.py` does. This
does not close this item: the underlying parquets are still frozen at 2024-06-02.

**Blast radius:** 6 of 65 features degraded; no fabrication — every affected feature
is honestly reported as a gap (previously true only off the upcoming-fixtures path;
now true everywhere, see correction above).
**Cost:** Elo replay is small now that history exists. StatsBomb is a separate,
larger offline job.
**Impact:** moderate — reduces evidence quality, does not block predictions.
**Priority:** medium for the Elo half (cheap, and history now exists); low for
StatsBomb.

---

## 11. Eleven upcoming fixtures still have no history — lower-division clubs in cup ties

**Tier:** `ACCEPTED` — correct fail-closed behaviour; recorded so it is not
re-diagnosed as a bug.
**Found:** 2026-08-08, measuring backfill coverage.

38 of 49 upcoming fixtures resolve real history on both sides. The other 11 involve
clubs genuinely absent from the six top-flight divisions the backfill covers —
Coventry City, Hull City (Championship), Málaga, Deportivo La Coruña, Racing
Santander (Segunda), ADO Den Haag, Cambuur, Willem II (Eerste Divisie), Le Mans
(Ligue 2). They appear in the fixture feed because football-data.org's competition
endpoints include cup ties.

Those fixtures correctly return reduced evidence rather than a prediction built on a
club the system has never seen. Loading second divisions would fix it but would put
matches outside the seven-competition closed set into `matches`, with no canonical
`league_id` to hold them — a deliberate boundary, not an oversight.

**Blast radius:** those fixtures show no prediction.
**Cost:** would require a decision on representing non-supported competitions.
**Impact:** low — correct behaviour, just not maximal coverage.
**Priority:** low.

---

## 1. Base-58 feature block is silently defaulted on every live prediction

**Tier:** `NEXT` → **CLOSED 2026-08-07 (WP-18)** — see below.
**Owner:** unassigned.
**Found:** 2026-08-04, verifying the WP-0/WP-1/WP-2 identity + gap-detection campaign.
**Updated:** 2026-08-05 — WP-10.1 shipped (caller wired), WP-10.2 semantics pinned
(evidence below). WP-10.3 was still open at that point; it later shipped as WP-18
on 2026-08-07, as recorded in the closure note below.

**Closed 2026-08-07 (WP-18).** The `R4/INV-14` approval gate this entry described
("operator go/no-go... approval required, not autonomous, never execute-then-ask")
referenced an external campaign document's own numbering — `docs/RISK_REGISTER.md`
is empty and `INV-14`/`R4`/`GATE-10` are not defined anywhere else in this repo
(confirmed via repo-wide grep), so no formal, enforced gate (CI check, populated
registry) existed to satisfy mechanically. The substantive requirement — a human
with repository authority explicitly signing off on this exact schema-semantics
change before it landed — **was** satisfied: the operator reviewed a written plan
naming this precise change ("fix the confirmed home/away collision... wire the
existing (already-live-elsewhere) canonical remap... prefer real scraped
wins/draws/losses over the cruder estimate where available") and explicitly
approved it before any code was touched, via this session's plan-review flow.
Implementation matches WP-10.1/WP-10.2's semantics exactly, plus the D8b prefix
fix landed atomically as this entry required, plus the `feature_defaulted_ratio`
before/after proof (regression-test-backed, not a one-off manual number). Full
detail in `CLAUDE.md`'s WP-18 ground-truth entry and `CHANGELOG.md` vΩ.41.

`_get_team_stats()` (`backend/src/services/upcoming_match_feature_service.py:705-805`)
computes ~12 stats (`home_form_5`, `home_win_rate_5`, `home_goals_per_match_5`, …) that
share no name with any `CANONICAL_FEATURES_58` entry
(`backend/src/models/feature_registry.py:6-65` — e.g. the canonical name is
`home_form_last5_home`). The WP-2 gap-detection fix already flags this honestly as an
advisory gap rather than fabricating a value (`data_gaps` computed via
`_CALLER_RESOLVED_FEATURES` set-membership, not a value check) — this is **not** a
zero-fabrication violation. It is a prediction-*quality* gap: the model receives real
signal for at most ~28 of 86 features (Elo/StatsBomb/Phase8 block) on every request.

**Second, independent bug in the same function**: `_get_team_stats()` hardcodes the
`"home_"` prefix on every key it returns, regardless of which team it's called for —
`project_match_features()` calls it once for the home team and once for the away team
with identical output-key shapes (`upcoming_match_feature_service.py:140-141`), so
`away_stats` silently overwrites `home_stats` under the same dict keys before
`features_dict.update(...)`. Currently inert (neither key is canonical, so the
collision has no live effect), but a real remap must add an `is_home`/prefix parameter
or it will trade "honestly defaulted" for "silently swapped between home and away."

**WP-10.1 shipped (2026-08-05):** `ScrapedTeamFormStore` (D12 — was a zero-caller class)
now has a real caller: `UpcomingMatchFeatureProjector._apply_scraped_fallback()`
consults it only when `_get_team_stats()` returns `None` (zero DB history for that
side), and only tags the result via `data_quality["scraped_fallback"]` — never folded
into `is_synthetic` (the zero-fab publish gate in
`upcoming_match_service.py:265`, `publishable = not is_fallback and not is_synthetic`;
flipping it on a fallback whose keys are still non-canonical would have re-opened
exactly the vΩ.32 fabrication class this campaign already closed once). Still fully
inert on the canonical feature vector, deliberately — that's WP-10.3, below. Tests:
`backend/tests/test_feature_gap_detection.py`
(`test_scraped_fallback_used_when_db_has_no_history_but_stays_inert`,
`test_scraped_fallback_absent_leaves_prior_behaviour_unchanged`).

**WP-10.2 semantics pinned (2026-08-05, no assumption):** the canonical remap this item
needs is not undiscovered — it already exists, live, in a *sibling* pipeline.
`backend/src/data/transformers.py`'s `FeatureTransformer.engineer_features()`
(lines 328–339) computes the exact canonical names from the *exact same* non-canonical
keys `_get_team_stats()`/`ScrapedTeamFormStore.to_projection_stats()` both already
produce:

```text
home_form_last5_home   = home_form_5 * 3.0                      # → points/game over last 5, 0–3 scale
away_form_last5_away   = away_form_5 * 3.0
home_wins_last5_home   = round(home_win_rate_5 * 5.0)            # win RATE → win COUNT (0–5)
away_wins_last5_away   = round(away_win_rate_5 * 5.0)
home_draws_last5_home  = max(0, 5 - wins - 2)                    # ⚠ algebraic estimate, NOT a
away_draws_last5_away  = max(0, 5 - wins - 2)                    #   real draw count — assumes a
home_losses_last5_home = max(0, 5 - wins - draws)                #   fixed "2 losses" baseline
away_losses_last5_away = max(0, 5 - wins - draws)
home_goals_for_avg     = home_goals_per_match_5   (direct passthrough)
away_goals_for_avg     = away_goals_per_match_5
home_goals_against_avg = home_goals_conceded_per_match_5
away_goals_against_avg = away_goals_conceded_per_match_5
```

This is confirmed as the *training-time* semantics, not a guess: `models/training.py`
and `models/enhanced_training.py` both import `FeatureTransformer` from this exact
module, and `backend/models/training_report.json` → `data.feature_names[0:5]` starts
`["home_form_last5_home", "home_wins_last5_home", "home_draws_last5_home",
"home_losses_last5_home", "away_form_last5_away", …]` — the real trained artifact's own
feature order. **The draws/losses estimate is itself a latent precision loss**:
`ScrapedTeamFormStore`'s `ScrapedTeamForm` already carries real `wins`/`draws`/`losses`
integers from the scraped CSV (`to_projection_stats()` currently discards them down to
the same lossy `home_`-prefixed shape as `_get_team_stats()`, matching its bug
intentionally) — a real remap has a strictly-better option than reproducing
`transformers.py`'s algebraic estimate when the scraped source is what's in play.

**Historical pre-closure rationale for WP-10.3 (wiring this remap into
`upcoming_match_feature_service.py`):** it was classified R4 under INV-14
("remapping `_get_team_stats()` output onto
canonical feature names is a feature-schema change... even though no new feature is
added — the meaning bound to each name changes") — proposal-only, approval required,
never execute-then-ask. Confidence in the semantics was high (cited to the live
training artifact, not assumed), but the operator still had to sign off because the
change altered what every live model saw and required the D8b prefix fix plus a
`feature_defaulted_ratio` before/after capture. That approval and atomic implementation
were completed by WP-18, as the 2026-08-07 closure note records.

**Historical blast radius:** every live prediction, matchup and DB-fixture path.
**Closure:** WP-18 completed the approval, D8b atomic fix, regression coverage, and
`feature_defaulted_ratio` proof. No go/no-go decision remains open for this item.

---

## 2. Settlement loop and production prediction capture shipped; real outcomes pending

**Tier:** `NEXT` → settlement loop **shipped 2026-08-05**; interactive capture fix
**DEPLOYED / VERIFIED 2026-08-14** on Apex v3.
Entry kept (annotate, don't remove, matching item 1's precedent) because production
is still DATA-FED at zero, a residual limitation and a related risk (item 5) remain.
**Owner:** unassigned.
**Updated:** 2026-08-05 — WP-10.4 shipped. New `services/settlement_service.py`
composes `sync_settled_results()` (new, `fixture_sync_service.py`) →
`get_settled_predictions()` → `walk_forward_validate()`, called hourly from a new
periodic `_background_settlement_sync()` task in `api/main.py`. `sync_settled_results`
settles matching `Match` rows via a new `FootballDataAPIClient.get_recent_results()`
provider method, looked up by the same deterministic `fd-{id}` scheme
`sync_upcoming_fixtures()` already writes — no identity re-resolution needed.
`/health` gains an informational `components.settlement` snapshot;
`/model-performance` and `/model-performance/summary` now run the real query instead
of an unconditional 503 (the still-503 `reason` also corrected from
`bet_history_aggregation_not_yet_integrated`, now false, to
`insufficient_settled_predictions`). See `docs/adr/0003-settlement-join-scheduling.md`
for the scheduling decision and rejected alternatives. **Residual, not fixed by this
change:** once a match hits `SETTLED_MATCH_STATUSES` its score is frozen — a
provider-side correction after settlement is never re-applied.

The older paragraph below the WP-10.4 closure was stale: the background settlement
caller and result sync do run. The production zero instead traced to the other side
of the join: fresh verified-fixture full analysis returned real model output without
writing `MatchPredictionLog`, so there was nothing for a later finished result to
join. The Apex v3 candidate adds one shared, transactional capture path used by full
analysis and the existing prediction writers. It accepts only finite real-model
simplexes for existing scheduled fixtures strictly before kickoff, records a
deterministic input hash/provenance and `interactive_full_analysis` trigger, and
deduplicates the same match/model/input snapshot without a migration. A seeded
end-to-end test now proves scheduled fixture → full analysis → prediction log →
finished result → settled join. Persistence failure is observable but does not turn
an analytical fail-closed response into an execution claim.

Settlement and CLV selection now choose the latest eligible prediction strictly
before kickoff or closing-line capture. Two production full-analysis calls for the
same scheduled fixture incremented the duplicate counter twice, proving the existing
immutable row and deployed deduplication without creating another row. Direct row
counts remain private-network-only. The path is **DEPLOYED / CALLED / VERIFIED** but
not DATA-FED or CERTIFIED until a naturally finished fixture joins.

**Blast radius:** `/model-performance`, accuracy/RPS, CLV, and every promotion gate
that requires settled outcomes. **Residual:** production remains honestly
`503 METRICS_UNAVAILABLE` with zero settled predictions until a deployed pre-kickoff
capture later joins a real finished result. Do not retrain or promote on one row;
existing sample-size and temporal gates still apply.
**Impact:** no real accuracy telemetry exists yet even though the season is about to
generate settleable matches (Eredivisie opens 2026-08-07, EPL 2026-08-21 — see
`backend/src/core/season_calendar.py` for the provider-verified table).
**Priority:** was high as the literal Phase-1→Phase-2 gate; the *caller* is no longer
the blocker. What remains is time: `/model-performance` needs ≥10 settled, logged
Eredivisie predictions (several matchdays into the season, not the first match) before
Phase 2 can honestly begin.

---

## 3. OTel telemetry entirely unregistered; fixture-sync failures are invisible

**Tier:** `ACCEPTED` — both halves shipped; kept only as the incident record + a
pointer to the residual gap named below.
**Owner:** unassigned.
**CLOSED 2026-08-06/07 — verified against code, not carried forward from a stale
note.** `docs/adr/0006-otel-activation.md` moved from Proposed to **Accepted**;
`core/telemetry.py::setup_telemetry()` registers a real `TracerProvider` +
`BatchSpanProcessor(OTLPSpanExporter(...))` and a `MeterProvider`, called from
`api/main.py:67`, with `FastAPIInstrumentor.instrument_app()` applied at
`api/main.py:342` — both gated on `settings.enable_tracing AND
settings.otel_exporter_otlp_endpoint` both being set, so this remains a true
no-op in every environment that hasn't configured an OTLP endpoint (safe-defaults
preserved). OTLP/HTTP was chosen over gRPC specifically to avoid the `grpcio`
native-extension cost on the free-tier dyno (ADR-0006 §Cost) — no new pin needed.
The fixture-sync half is also closed: `run_fixture_sync()`
(`backend/src/services/fixture_sync_service.py`) now calls
`metrics_collector.increment("fixture_sync.failures")` +
`.record_error(...)` on its swallow path, surfaced live via the already-wired
`GET /metrics` (`api/endpoints/monitoring.py:560`,
`metrics_collector.get_summary()`) — no new endpoint needed, this task was the
one swallow site without any tracking at all. `_background_settlement_sync` and
`_background_clv_capture` were checked and did **not** need the same fix — both
already track outcome/`consecutive_failures` in an in-memory `_last_result` dict
surfaced via `/health` `components.settlement`/`components.clv_capture`
(item 2's own delivery), predating this entry.

**Blast radius:** none remaining — was every request (no tracing) and fixture
ingestion (no failure signal); both now have a signal.
**Impact:** none remaining.
**Priority:** none — revisit only if a future OTel exporter change needs a fresh
ADR.

---

## 4. Duplicate season-string writer

**Tier:** `ACCEPTED` — fixed; kept as the incident record only.
**Owner:** unassigned.
**CLOSED — verified against code 2026-08-07** (this entry's "not yet fixed"
framing was stale; the fix was already live, undocumented here until now).
`backend/src/data/loaders/football_data.py:322` calls
`season=canonical_season(match_data["match_date"])`, deriving from the match's own
date rather than re-deriving `"YYYY/YYYY"` from the source filename — there is now
exactly one season-string writer (`backend/src/utils/season.py`), matching
`fixture_sync_service.py` and `upcoming_match_feature_service.py`.

**Blast radius:** none.
**Impact:** none.
**Priority:** none.

---

## 5. Predictions with a synthetic match_id can never settle

**Tier:** `ACCEPTED` — **CLOSED 2026-08-12**. Kept as the incident record.
**Owner:** unassigned.
**Found:** 2026-08-05, while wiring the settlement join (item 2).
**Fixed:** 2026-08-12, ahead of its own trigger — closed *before* real settled
data could expose the gap, rather than waiting for a depressed
`settled_join_rate` to prove it. Eredivisie's first settleable results land
within days, so fixing it after the fact would have meant permanently
unjoinable rows already written.

`create_prediction()` (`backend/src/api/endpoints/predictions.py`) synthesized
`match_id = f"{home}_{away}_{timestamp}"` when the caller didn't supply a real one.
`get_settled_predictions()` joins `MatchPredictionLog.match_id` to `Match.id` — a
synthetic value can never equal a real `Match.id`, so such prediction rows were
permanently unjoinable no matter how correct the settlement pipeline is.

**Resolution:** the endpoint now fails closed. When no `match_id` is supplied it
raises HTTP 422 with `error_code: "FIXTURE_IDENTITY_REQUIRED"`, directing the
caller to a real fixture id from `GET /api/v1/fixtures/upcoming`, instead of
fabricating an identity that silently corrupts the settlement SLI. This is the
"rejecting the write" option named in the original cost estimate below, chosen
over back-resolving the fixture by team name + kickoff: that lookup would itself
be an identity guess, and the codebase already has a canonical answer for
whether a matchup resolves (`reconcile_team`, the `FIXTURE_IDENTITY_UNVERIFIED`
path) rather than a second, weaker heuristic in an endpoint. The DB-fixture
path, which already passes a real `match_id`, is untouched. Regression guard:
`test_prediction_endpoint_never_mints_a_synthetic_match_id` in
`backend/tests/test_zero_fabrication_contract.py` — a source-level contract
assertion in the repo's established style for this invariant class, since
importing the endpoint requires a live DB (item 7).

**Blast radius:** `settled_join_rate` (item 2's SLI) and `/model-performance`'s
`settled_predictions` count — both would have read low even once matches settled
correctly, for any share of predictions logged via this path.
**Impact:** now none for new writes. ⚠️ **Residual:** any rows already written
under a synthetic key before this fix remain unjoinable. No backfill was
attempted — `MatchPredictionLog` currently holds no settled rows at all
(`settled_predictions_total: 0`), so there is nothing to repair yet; re-check
if `settled_join_rate` reads low once real volume exists.
**Priority:** none remaining for the write path.

## 6. CLV and ROI are structurally unavailable, not merely unimplemented

**Tier:** `ACCEPTED` — ROI half unchanged/out of scope by construction; CLV half now
computed. Kept as the incident record + the ROI rationale, matching item 2/3/4's
"update in place, don't delete" precedent.
**Owner:** unassigned.
**Found:** 2026-08-05, while wiring `/performance` to the settlement join (item 2).
**Updated:** 2026-08-06 — **the CLV capture half is now shipped**, not just
proposed. `docs/adr/0004-clv-capture.md` (Accepted) landed alongside migration
`0005_clv_capture_schema` and `services/clv_capture_service.py`: a periodic
background job (`_background_clv_capture`, 5-min interval, same
handle-stored/cancel-on-shutdown shape as settlement sync) enumerates fixtures
approaching kickoff, fetches the odds board per league via
`TheOddsAPIProvider.odds()`, computes a median consensus across coherent
bookmaker records, de-vigs it (`the_odds_api.devig_probabilities`), and writes
one `MarketSnapshot(is_closing_line=True)` row. `MatchPredictionLog` gained a
nullable `closing_market_snapshot_id` FK, always NULL for now — see the ADR's
2026-08-06 addendum for why (`canonical_fixture_id`, the originally-proposed
join key, is never populated for an ordinary upcoming fixture; the job keys on
the legacy `matches.id` instead). 8 new unit tests
(`tests/unit/test_clv_capture_service.py`); backend suite 1089 passed.
**Updated 2026-08-07 — the CLV computation half now ships too.**
`repositories/fixtures.py::get_clv_records()` joins the latest logged
prediction per match to its latest captured closing line **on `match_id`, not
`canonical_fixture_id`** — both `MatchPredictionLog` write sites and the
capture job itself hardcode `canonical_fixture_id=None`, so that FK was never
a real prerequisite despite how the 2026-08-06 addendum below reads;
`match_id` is populated and indexed on both tables today, so no
identity-resolution work was needed to unblock this. `services/clv_service.py
::compute_clv_summary()` computes a mean CLV
(`model_prob[argmax] - closing_implied_prob[argmax]`) plus a positive-rate,
gated on `n >= 10` joined records (reuses `model_registry.py`'s own
`MIN_RECORDS_FOR_DECOMPOSITION` threshold rather than inventing a second magic
number in the same response), surfaced as an independent `clv` field on
`GET /model-performance` — independent of the walk-forward floor already in
that response, since a season can have enough closing lines and too few
finished matches, or the reverse. **Two things this deliberately did NOT do:**
it does not touch `MatchActionability.clv_pct`
(`services/intelligence_synthesizer.py`, `full_analysis.py:448`, still
hardcoded `None` / "Sprint 5") — that field lives in the Kelly/verdict/abstain
advisory surface, the same category as `betting_intelligence.py`/
`core_engine.py` even though it isn't literally those files, and is a
different "CLV" concept (per-recommendation, not this diagnostic aggregate);
and it does not restore the `/performance` frontend CLV card — an explicit
user scope decision this session, not a technical blocker (the computation
prerequisite the guard below names is now satisfied). **ROI is unchanged and
stays unreachable by construction** — it needs a placed stake, which this
platform never places.

`/performance` used to carry "30d CLV" and "30d ROI" stat cards. They were removed
rather than left showing an em-dash, because an em-dash means "awaiting data" and
neither figure is awaiting anything:

- **CLV** (closing line value) needs the closing price recorded beside each prediction.
  `MatchPredictionLog` (`backend/src/db/models.py:227-251`) stores probabilities,
  confidence, `model_version`, `calibration_method`, `input_hash` and a nullable
  `payload` — **no odds column of any kind**. The CLV machinery itself does exist
  (`connectors/pinnacle.py::calculate_clv`, the `clv_*` features in
  `connectors/odds_market.py`), so this is a missing *join*, not a missing capability:
  nothing links a stored prediction to the market price at the time it was made.
- **ROI** needs a realised return on a placed stake. This platform never places one —
  verdicts terminate at `NO_BET`/`HOLD`, staking is shadow-evaluation only, and the
  `EXECUTE_BET` state was explicitly rejected as a product-identity decision. There is
  no execution record for ROI to be computed from, and adding one is out of scope by
  construction rather than by backlog position.

**Blast radius:** none today — removing the cards changed no computation. The risk this
entry guards against is someone re-adding the *ROI* card as a "coming soon"
placeholder, which would be an INV-01 fabrication surface of exactly the
vΩ.24/vΩ.28 kind (a neutral default rendered where a measurement belongs). The
CLV card's own prerequisite (a real computed number) is satisfied as of
2026-08-07 — restoring it is now a scope decision, not a fabrication risk.
**Cost to actually deliver CLV:** **done, 2026-08-07** — the schema/capture job
shipped 2026-08-06, computation shipped 2026-08-07 (above). Correcting a
citation error from the previous version of this entry: the "already does this
math" reference here previously named `connectors/odds_market.py::
market_movement_features` — that function does not exist in that module at
all (`market_movement_features` lives in `features/market.py` and has no
`model_probabilities` parameter, so it cannot compute CLV under any wiring).
The function that *does* compute CLV, `connectors/odds_market.py::
compute_market_features()`, was deliberately **not** called by the shipped
implementation either — it re-derives de-vig arithmetic from raw odds that
`MarketSnapshot.*_implied_prob_devigged` already stores precomputed, so
`clv_service.py` does a direct subtraction on those columns instead. Remaining
cost, if ever wanted: wiring the diagnostic `clv` field into the `/performance`
frontend (out of scope this pass) and, separately, deciding whether/how to
populate `MatchActionability.clv_pct` from the same joined data (a
verdict-adjacent surface, not touched here).
**Cost to deliver ROI:** not applicable; it requires reversing a deliberate product
decision, not writing code.
**Impact:** `GET /model-performance` now returns an independent `clv` field
(mean CLV + positive-rate, `n >= 10` floor) alongside the walk-forward harness
output; the `/performance` frontend page is unchanged and does not render it
yet.
**Priority:** none for CLV computation (done). Low for the `/performance` card
restoration, whenever that scope is picked up. ROI: never, absent an explicit
operator decision to change what the product is.

## 7. `core/database.py` opens a connection at import time, so every offline tool needs a live DB

**Tier:** `ACCEPTED` — **CLOSED 2026-08-22**, per `docs/adr/0008-lazy-database-engine-init.md`. Kept as the incident record.
**Owner:** unassigned.
**Found:** 2026-08-05, diagnosing a production outage (see the operator note below).

**Fixed 2026-08-22.** Engine creation + connection testing moved from module
import time into a lazily-initialised, memoized `get_engine()`, with an
explicit `verify_database_connection()` called first thing in `api/main.py`'s
`lifespan()` — preserving the exact fail-closed contract (unreachable
PostgreSQL with no explicit SQLite fallback still aborts startup) while
letting `Base`/model-class-only importers (Alembic, ~30 test files, scripts)
import cleanly without a live database. `SessionLocal` became a class using
`__new__` so its `SessionLocal()` call surface is unchanged for every
existing caller. The two direct consumers of the old module-level `engine`
object (`api/endpoints/monitoring.py`, `services/orchestrator.py`) now call
`get_engine()` — the one place laziness could have been silently defeated,
since `api/main.py` imports `monitoring.py`'s router at module scope, before
`lifespan` ever runs. Alembic's `env.py` needed no change: it already builds
its own independent engine via `engine_from_config()` and never touched
`core.database`'s engine or fallback state.

Verified, not assumed: `backend/tests/unit/test_lazy_database_engine.py`
runs real subprocesses against a genuinely unreachable address (not an
in-process mock) and proves both halves — import succeeds with no live DB
and no fallback allowed, and `get_engine()`/`SessionLocal()` still raise the
moment either is actually called. Full backend suite green (1636 passed, 0
failed) after fixing 3 pre-existing tests that patched the now-removed
`monitoring.engine` module attribute (`patch.object(monitoring, "engine",
...)` → `patch.object(monitoring, "get_engine", return_value=...)`). Side
benefit found while verifying: `backend/conftest.py` sets
`ALLOW_SQLITE_FALLBACK=true` for the whole test session, so the old eager
import created a throwaway `sabiscore_fallback.db` SQLite engine — and the
stray gitignored file it left behind — on every single pytest run, even for
tests that only needed `Base`/model classes and never touched a session.
That waste is gone.

**Original entry, 2026-08-05 (kept for the incident record):**

`backend/src/core/database.py` runs `_test_connection()` and raises at **module scope**
(`:110-117`), not inside a function. Anything that imports the module therefore
requires a reachable PostgreSQL, including tooling that has no business needing one:

- `alembic/env.py:11` does `from src.core.database import Base`, so **`alembic upgrade
  head`, `alembic check`, and `alembic revision --autogenerate` all fail with a
  connection error before Alembic runs its own logic** — the failure surfaces as a raw
  traceback from an import, not as a migration error.
- `src.api.main` cannot be imported for inspection, linting or an IDE language server
  without a database.
- `make verify` gate 4 and gate 14 both need a live local PostgreSQL purely to import.

**Why this is not simply "make it lazy":** the raise is load-bearing. It is what
enforces "PostgreSQL unavailable and SQLite fallback is not explicitly allowed" — the
`ALLOW_SQLITE_FALLBACK` invariant that must never activate silently. Deferring the
check must preserve that: the correct shape is a lazy engine whose *first use* raises
the same way, not a check that is dropped.

**Blast radius:** none remaining. In production it used to convert a recoverable
dependency outage into an un-diagnosable crash loop. `render.yaml`'s `startCommand`
is `alembic upgrade head && uvicorn …`; when the import raised, the `&&`
short-circuited, uvicorn never started, the container exited, Render restarted
it, and the only public signal was the platform's own HTML 502. The service
being down was *correct* (it cannot serve without its database) — being
unable to say why was not. `verify_database_connection()` now produces a
dedicated log line at the same point in startup instead of a bare import
traceback.
**Cost:** done.
**Impact:** none remaining — developer friction and incident diagnosability
both resolved.
**Priority:** none remaining.

---

## Operator action outstanding (not code — no code change can resolve it)

**RESOLVED 2026-08-06 — new PostgreSQL instance provisioned; render.yaml corrected
to match.** The expired `sabiscore-db` (below) was replaced with a standalone
instance (`sabiscore_db_v2`) created directly in the Render dashboard, outside
blueprint management. `render.yaml` still declared `DATABASE_URL` via
`fromDatabase: {name: sabiscore-db}` and still carried a `databases:` block for
the now-dead resource — live drift that would have risked a future Blueprint
sync (e.g. the one enabling the three disabled providers) silently rebinding
`DATABASE_URL` back to a dead or freshly-empty resource. Fixed: `DATABASE_URL`
is now `sync: false` (operator-managed, matching how the replacement was
actually provisioned) and the `databases:` block is removed. No data was lost
by this correction — the old instance was already unreachable (DNS failure)
before the replacement existed, so there was nothing live to migrate.
**⚠️ CONFIRMED 2026-08-21, and it recurs.** Queried live via the Render
Postgres API (`GET` on `dpg-d9pfv3pt0dsc73djciog-a`, no dashboard needed):
`"plan":"free"`, `"expiresAt":"2026-09-04T09:17:03Z"`. This is the *exact same
failure mode* that killed `sabiscore-db` on 2026-08-05, about to repeat on the
instance that replaced it — **14 days out from this update.** Free-tier
Render Postgres cannot be upgraded to a paid plan in place; the only paths
are (a) provision a new paid-plan instance and migrate data before the
deadline, or (b) let it expire and rebuild from `fixture_sync_service`'s
periodic re-sync + a fresh Elo replay — which would silently discard the
2026-08-19 self-play repair, the full 12,790-match/25,580-row Elo backfill
confirmed complete this same session, and any `elo_rating_snapshots` history
that took ~2 weeks of background settlement ticks to accumulate. **Trigger:
operator action before 2026-09-04.** Not agent-doable — plan changes need the
Render dashboard/billing, and provisioning a replacement is a real-money,
real-data decision that must not be made unilaterally.

**✅ RESOLVED 2026-08-21 — migrated to `sabiscore-db-v3`, cutover verified, no
data lost.** Provisioned `sabiscore-db-v3` (`dpg-da3p8qv10e5c738vls1g-a`,
plan `basic_256mb`, region `oregon`, PostgreSQL 18, **no expiry**) via the
Render API. Data moved with `docker run postgres:18 pg_dump --no-owner
--no-privileges --clean --if-exists | docker run -i postgres:18 psql
-v ON_ERROR_STOP=1` (no local `pg_dump`/`psql` install; no local Render CLI
either), piped directly between two containers so nothing touched disk or
PowerShell's text encoding. Run twice: the first pass overlapped with live
background writes on `v2` (`matches` grew 12,790 → 12,851 mid-migration —
the write-during-migration gap this entry warned about was real, not
theoretical), so the *exact same* idempotent command was re-run immediately
before cutover, closing the gap to zero.

**Verified independently, not assumed** — two problems surfaced during
verification and both were resolved before trusting the result: (1) Render's
own read-only query tool fails with `SSL/TLS required` against `v3`
specifically (consistent on retry; `v2` is unaffected) — worked around by
having the operator verify row counts directly via the same
`docker run postgres:18 psql` pattern instead. (2) Post-cutover, `matches`/
`elo_rating_snapshots`/`market_snapshots` read identically on both instances
by construction (the copy made them identical), so row counts alone can't
prove *which* instance is live — resolved with `get_metrics
active_connections` over the cutover window: `v3` held a steady 3–4
connections throughout (including before the deploy completed, plausibly a
warm pool from the health-checked new deploy), `v2` read `0` for the entire
window bar one incidental blip from this session's own diagnostic query.
Combined with the live `/health/ready` (`release_sha` matching the deploy
log's own build-identity line, `database: Connected`, `migrations: head
0009_quarantine_market_closings` applied cleanly, `elo.rows: 25580`) this is
conclusive: production is on `v3`.

**Not yet done, non-urgent:** `DATABASE_URL` on the `sabiscore-api` service
was set to `v3`'s *external* connection string (the one that also works from
outside Render, used for the migration itself) rather than the *internal*
one. Both work — the deploy log and live health checks confirm full
functionality either way — but internal stays inside Render's network
(lower latency, no public-internet hop, no egress transfer). Switch it via
the dashboard's "Internal Database URL" field on `v3` when convenient; no
functional urgency.

`sabiscore-db-v2` is confirmed idle (0 active connections) and safe to
delete once the operator is comfortable — recommended to leave it running a
few days as a free rollback path before removing it, well ahead of its own
2026-09-04 expiry.

**Original entry, 2026-08-05 (kept for the incident record):**
Render PostgreSQL `sabiscore-db` no longer resolved and the API was crash-looping.
Observed in the Render logs:

```text
failed to resolve host 'dpg-d95kg3e7r5hc73eh7g6g-a': [Errno -2] Name or service not known
PostgreSQL unavailable and SQLite fallback is not explicitly allowed
==> Instance srv-d95kkffaqgkc73f8003g-nvp7j restarted
```

`render.yaml:32` wired `DATABASE_URL` via `fromDatabase: sabiscore-db`. A DNS failure
on the instance hostname meant the database instance itself was gone, not that
credentials had drifted — Render's free PostgreSQL tier expires and is deleted after
30 days.

---

## 8. `monitoring/drift.py` still has zero production callers — reference baseline cannot exist yet

**Tier:** `NEXT` — trigger: ≥1,000 score-verified settled fixtures exist (the
generator's own `--minimum-sample` default; see below). Not sooner.
**Owner:** unassigned.
**Found:** 2026-08-06, scoping a "wire drift → Slack alerting" task before starting it.

`DriftMonitor` (`backend/src/monitoring/drift.py`) and `trigger_slack_drift_alert`
(`backend/src/services/alerting.py`) are both correct and unit-tested, and
`SLACK_DRIFT_WEBHOOK_URL` now has a `render.yaml` declaration (`sync: false`,
this session). None of that makes wiring a periodic caller today a good idea —
two independent blockers, both data, not code:

1. **No reference baseline exists, and none can be generated.**
   `backend/data/reference/` holds only a `README.md` and a
   `baseline_v1.manifest.template.json` — never `baseline_v1.parquet` itself.
   `scripts/generate_reference_baseline.py` → `ReferenceBaselineGenerator`
   selects only score-verified settled fixtures and refuses to write an
   artifact below `--minimum-sample` (default 1,000) — by design, it "never
   fabricates or zero-fills a baseline." Zero fixtures are settled as of
   2026-08-06 (Eredivisie's first ball hasn't been kicked). `DriftMonitor.__init__`
   raises `DriftConfigurationError` without this file; there is nothing to
   construct a monitor from yet.
2. **No live write path stores a reconstructable feature vector for a
   "current batch."** `MatchPredictionLog.payload` is written as `None` from
   `api/endpoints/predictions.py` and as the full `MatchAnalysisResult` (not a
   raw canonical feature row) from `services/analytics.py` — neither shape
   matches the reference schema's `ordered_features` that `evaluate_batch()`
   requires. Even once (1) is satisfied, sourcing `current_batch_df` is a
   second, separate piece of work.

Building periodic-task scaffolding around either blocker now would mean
guessing at a shape with nothing real to validate it against — the same
"stacked bug behind a broad except" class this codebase has hit before
(vΩ.32). Deferred deliberately, not overlooked.

**Blast radius:** none today — `drift.py` importing cleanly and its tests
passing is the full extent of current behavior.
**Cost:** the baseline half resolves itself once real settlement volume
exists (run the generator; it either succeeds past 1,000 rows or refuses).
The current-batch half needs a real decision: either widen a write path to
log the canonical feature vector `engineer_features()` already produces, or
source batches by re-deriving it from settled `MatchPredictionLog` rows —
worth deciding once there's real data to test against, not now.
**Impact:** none — advisory monitoring, not on any serving path.
**Priority:** low until item 2's settlement volume climbs toward four figures;
revisit alongside item 2/5's own settled-data gates.

---

## 9. Portfolio-exposure haircut curve and aggregate-cap multiplier are placeholders, not calibrated values

**Tier:** `NEXT` — trigger: ≥1 fully-settled same-league/same-matchday round
exists (Eredivisie's opening weekend, 2026-08-07 onward, is the earliest
candidate). Not sooner.
**Owner:** unassigned.
**Found:** 2026-08-06, implementing WP-17 (`docs/adr/0005-portfolio-exposure-policy.md`).

`backend/src/core/portfolio_exposure.py`'s `HAIRCUT_PER_ADDITIONAL_FIXTURE` (0.10),
`HAIRCUT_FLOOR_MULTIPLIER` (0.50), and `AGGREGATE_CAP_MULTIPLIER` (3.0) are reasoned
starting points, not derived from real same-matchday settlement outcomes — none exist
yet. ADR-0005's Reversal/Trigger clause names this same gap. Marked
`PORTFOLIO_POLICY_SOURCE = "DEFAULT_PENDING_CALIBRATION"`, mirroring
`LeaguePolicy.policy_source`'s own vocabulary. Policy (c)'s drawdown-pause threshold has
no placeholder at all — it's deferred entirely (no settled positions exist to compute a
real drawdown from), never a fabricated value.

Same session also found and fixed a genuine prerequisite bug while implementing this:
`PredictionEngine.calculate_value_bets` (`backend/src/models/prediction.py`) computed
Kelly stakes with no cap at all — a 4th, independent, uncapped implementation beyond
the 3 `MAX_KELLY_CAP=0.05` literals already known (`insights/engine.py`,
`betting_intelligence.py`, `core_engine.py`). Now clamped via
`min(get_league_policy(league).kelly_cap, MAX_KELLY_CAP)`, matching the established
pattern. This was a real, live-affecting fix, not part of the placeholder gap above.

**Blast radius:** none — advisory-only, flags/haircuts a display number never read as
a gate (`EXECUTE_BET` doesn't exist).
**Cost:** recalibrate once real settled outcomes exist for ≥1 same-league/matchday
group.
**Impact:** low today; the risk is the placeholder looking more authoritative than it
is if the marker is ever dropped.
**Priority:** low until Eredivisie's opening round settles.

---

## 19. `UpcomingMatch` / `UpcomingMatchesResponse` are declared twice in `apps/web`, bridged by an unchecked cast

**Tier:** `ACCEPTED` — **CLOSED 2026-08-12**, same day it was opened. Kept as
the incident record per this ledger's convention.
**Owner:** unassigned.
**Found:** 2026-08-12, while fixing the empty fixtures panel.

**Closed 2026-08-12.** The trigger named below ("the next time either shape
changes") fired immediately: the very next change to this response shape was
the league-filter fix in the same session. Resolution: `lib/api.ts` remains the
single authority and absorbed the three fields the panel legitimately needed
and the canonical copy lacked — `data_quality`, `competition_stage`, `portfolio`
on `UpcomingMatch`, plus `portfolio_exposure` on `UpcomingMatchesResponse`. The
panel's 65-line local redeclaration and the
`as Promise<UpcomingMatchesResponse>` cast are deleted; it now imports both
types from `@/lib/api`. The prediction sub-shape disagreement noted below
(`draw_prob`/`away_win_prob` vs `draw`/`away_win`) resolved on inspection —
the panel never read those keys, only `predictions?.confidence`, so the
divergence was dead surface area rather than a live mismatch. `pnpm typecheck`
exits 0 with the cast removed, which is the proof that matters: any future
field drift is now a compile error rather than a runtime `undefined`.

`apps/web/src/lib/api.ts` exports the canonical `UpcomingMatch` /
`UpcomingMatchesResponse` interfaces used by `getUpcomingMatches()`.
`apps/web/src/components/upcoming-matches-panel.tsx` independently redeclares
both with a **different** shape, then force-casts the real client's return
value (`getUpcomingMatches(...) as Promise<UpcomingMatchesResponse>`), so
TypeScript cannot catch a genuine mismatch between what the API returns and
what the panel assumes.

The drift is real in both directions: the panel's copy carries
`data_quality`, `competition_stage`, and `portfolio`; the canonical copy
carries `venue`, `value_bets`, `source`, `edge_quality_score`, `clv_pct`,
`data_gap`, `unavailable_reasons`, and `generated_at`. The prediction sub-shapes
disagree outright — the panel spells the keys `draw_prob`/`away_win_prob`,
the canonical copy `draw`/`away_win`.

**This is no longer theoretical.** Rendering an honest "backend failed" empty
state required `data_gap`, which exists on the canonical type and on the wire
but was absent from the panel's copy — a compile error that the cast would
have hidden entirely had the field been read through it rather than declared.
`data_gap?: boolean` was added to the local copy as the minimal unblock; the
duplication itself is untouched.

**Blast radius:** any field the backend adds, renames, or removes is invisible
to the panel until it fails at runtime.
**Cost:** small but not mechanical — the two shapes must first be reconciled
(they are not a superset/subset), then the cast removed and the panel's reads
re-typechecked.
**Impact:** moderate — this is a zero-fabrication surface, and a silently
`undefined` field here renders as a missing badge or a wrong empty state
rather than an error.
**Priority:** medium. Do it as part of the next change to this response shape,
not as a standalone refactor.
