# SabiScore Debt Ledger

## 57. The tracked Understat corpus contains 1,826 duplicated matches, and 2021/22 is missing entirely

**Tier:** `RESOLVED` for the duplication (deduplicated at load, 2026-09-03).
`ACCEPTED` for the missing season — it is a data-acquisition gap, not a defect.

The 35 committed files under `data/processed/v4_sources` are labelled by
Understat's own season id and their coverage **overlaps**:
`understat_ligue_1_2020` and `understat_ligue_1_2021` both contain the whole
2020/21 season, game ids and all. Across the corpus that is **12,459 rows for
10,633 distinct matches** — 1,826 present twice.

Two live consequences, both found by building on it:

1. `understat_match_stats_reconciliation_service` produced a manifest proposing
   the same `(match_id, team_id)` `match_stats` row twice. The new backfill
   executor refuses a duplicate outright, so the backfill could never have been
   applied at all.
2. A duplicate lets one match contribute **twice** to a rolling xG mean — a
   quiet correctness bug rather than a loud one.

Deduplication on `game_id` now lives in `src/data/understat_corpus.py`, the one
loader shared by the reconciliation manifest, `features/xg_replay.py` and
`scripts/measure_xg_feature_ate.py`. Three copies of a population filter is
three places for them to diverge, and the ATE number is quoted as the
justification for the other two.

⚠️ **The deduplication changes the reconciliation manifest's SHA-256.** Any
`--apply` must be preceded by a fresh review run; the old digest is stale by
construction.

⚠️ **`reports/evaluation/xg-feature-ate.*` was originally measured on the
duplicated frame.** It has been re-measured. Every verdict is unchanged
(0.2485 / 0.2181 / 0.1832, all p < 1e-68; `finishing_efficiency_gap` still
INDEPENDENT at 0.0101, p=0.32); the point estimates moved in the third decimal.

**The missing season.** Because two files per league cover the same season, the
7 files per league span **6** distinct seasons: 2021/22 is absent from all five.
Any coverage number computed from this corpus inherits that, and any future
schema built on it will silently drop those rows. Understat also publishes **no
Eredivisie corpus at all**, so a schema requiring xG trains no Eredivisie model.

---

## 58. A CAUSAL_DRIVER ATE did not translate into out-of-sample lift — apex_v2_71 rejected

**Tier:** `CLOSED — negative result recorded.` Full evidence:
`reports/evaluation/apex-v2-71-candidate-evaluation.{json,md}`.

Item 50's remaining space is "(a) a different epistemic aggregation, or (b) it
resolves once a genuinely better-generalizing generation ships." `apex_v2_71`
was route (b)'s best available attempt: append the three features
`measure_xg_feature_ate.py` classified `CAUSAL_DRIVER` to `APEX_FEATURES_68`,
carry them into training with a leak-free replay, and take the result to the
promotion gate.

It failed, and the failure is informative rather than mechanical:

- On an **identical** holdout the xG block is neutral-to-worse in 4 of 5 leagues
  (mean RPS −0.00159, improved 1/5).
- `market_baseline` **0/5**. `no_league_regression` 2/5. `promotion_permitted:
  false`.
- The features are genuinely observed: `training_coverage = 1.0` and
  `variable_in_training = true` on all three, and `training_defaulted_slots` is
  **16 — identical to the `apex_v1_68` baseline**. Nothing was defaulted,
  nothing was fabricated, and the pipeline is not the explanation.

**The lesson worth surviving this session: a large, significant ATE is not
evidence of out-of-sample predictive lift.** ATE 0.2485 / 0.2181 / 0.1832 at
p < 1e-68, and the block still costs RPS in 4 of 5 leagues. The causal screen is
a filter against including *noise*; it is not a promotion criterion. A future
proposal reading "high ATE, therefore ship it" is making this mistake again.

Two mechanisms remain plausible and this evidence does not separate them: the
market block may already price shot quality, so xG is largely redundant with
features the model has; or dropping 1,478 rows (12% of the corpus, concentrated
in the uncovered 2021/22 season and all of Eredivisie) may cost more than the
features add. Distinguishing them needs `match_stats` populated in production
plus a serving-side measurement, not another offline candidate.

The `apex_v2_71` key stays registered in `FEATURE_SCHEMA_VERSIONS` as a
measurement contract, so a future xG candidate can be scored without re-deriving
the replay, the crosswalk and the gate wiring. The registry comment records the
rejection so the key is never mistaken for an endorsement.

---

## 59. Gate 50, route (a): independence refuted a third time; the heterogeneous member basis is declined

**Tier:** `CLOSED — hypothesis refuted.` Extends item 50 rather than replacing
it; `error_association` remains failed and `MODEL_UNCERTAINTY_UNAVAILABLE`
remains CRITICAL and fail-closed.

A proposal reached review to clear `error_association` by replacing BALD's
member basis with a **Heterogeneous Independent Ensemble** — N independently
seeded RF + XGBoost + LightGBM replicas — on the argument that "independence
alone does not fix the Random Forest; only heterogeneity does."

That argument is correct about the first half and draws the wrong conclusion
from the second. `spike_independent_ensemble_uncertainty.py` already caught the
confound: its default replica is a 3-learner stack while the incumbent basis is
trees inside one RandomForest, so the original headline moved member
*independence* and member *composition* at once.

Re-measured on seed block **4242** — a third, previously untested block — with
`--rf-only`, the flag that isolates independence:

```
trees (incumbent)   skill -0.0190              0/5
RF-only  N=3        skill -0.0161   gap>0 3/5, skill>0 0/5
RF-only  N=5        skill -0.0370   gap>0 0/5, skill>0 0/5
RF-only  N=10       skill -0.0244   gap>0 1/5, skill>0 1/5
```

Ladder declared before the run, reported in full. All three mean skills are
negative and N=5 is markedly worse than the incumbent. **Independence buys
nothing.** The entire apparent gain came from mixing model classes — precisely
the design `UNCERTAINTY_GATES["sufficient_members"]` deprecates: "Bootstrap or
resampling variants are preferred over distinct algorithms ... whereas distinct
algorithms vary only model class."

Adopting the deprecated design because it is the only one that moves a blocked
metric is threshold-shopping by another name (APEX §23), and it would require an
authorized ADR 0009 amendment, not a code change.

**It would also not deliver what it is proposed for.** `uncertainty_policy.py`
states the two gates are independent — "clearing `MODEL_GENERATION_UNCERTIFIED`
does not clear `MODEL_UNCERTAINTY_UNAVAILABLE`" — and the converse holds equally.
Flipping `error_association` alone does not enable staking:
`active_generation.json` is `certification_state: UNVERIFIED`, and clearing that
runs through `certification_policy.PROMOTION_GATES`, where **`market_baseline`
fails 0/5 for every model measured to date** — the incumbent and both candidates.

### The actual blocker, stated plainly

Staking is not gated on uncertainty aggregation. It is gated on **no SabiScore
model beating the market-implied RPS baseline in any league**. Until that
changes, both gates stay closed on their own evidence, and the honest product
state is the one production already serves:

```
/api/v1/models/status  ->  stake_permitted: false
                           certification_state: UNVERIFIED
                           manifest_valid: true, models_loaded: true
```

The certification directive is explicit that this is an acceptable outcome:
"Either existing certification criteria are honestly satisfied, or uncertainty
remains unavailable and fail-closed. Both outcomes are acceptable. Manufactured
PASS is not."

---

## 56. The "Data Expansion & Feature Density Sprint" directive is unexecutable as written — the surviving objective is a real xG corpus whose ingestion has never once been run

**Tier:** `NEXT` for the corpus half. The directive itself is **REJECTED — no
action, no code.** Full item-by-item reconciliation lives in
`reports/execution/plan-reconciliation.md` Appendix D; this ledger entry records
the two findings worth surviving outside a session transcript.

An operator-supplied directive proposed eradicating the four
`PHASE7_FEATURES_ALWAYS_DATA_GAP` slots by ingesting xG/PSxG metrics, on the
premise that denser features would make ensemble dispersion meaningful and so
resolve item 50's `error_association` reversal.

### Finding 1 — the proposed mechanism is inert, and this is worth remembering

The four slots are **constant across every row of the training corpus**.
`backend/scripts/retrain_with_expanded_features.py:224-226` overwrites them
unconditionally:

```python
for col in PHASE7_FEATURES_ALWAYS_DATA_GAP:
    if col in frame.columns:
        frame[col] = defaults.get(col, 0.0)
```

A zero-variance column yields zero information gain, so no tree in any ensemble
member ever splits on it, so it contributes nothing to the disagreement
`dispersion_from_members()` measures. **Populating these four columns cannot
move `error_association` in either direction.** Any future proposal that routes
"more data" to "better epistemic uncertainty" through these specific slots is
making the same error — the slots exist for artifact dimension compatibility
(see the 2026-06-10 incident recorded in `feature_registry.py:95-114`, where
removing them served `model_version="fallback"` on every inference for two
months), not as an unfilled data opportunity.

Item 50's remaining space is unchanged: (a) the reversal is inherent to
bagged-tree dispersion and a different epistemic aggregation is needed, or
(b) it resolves once a genuinely better-generalizing generation ships. A better
*corpus* is a legitimate attempt at (b). These four *slots* are not.

⚠️ Three further reasons the directive's §3 could not be executed as written:
`defensive_vulnerability_index` and `finishing_efficiency_gap` have **zero hits
repo-wide** (invented names); `xg_differential` exists only as an intermediate
in `data/transformers.py`, not as a canonical slot; and three of the four real
slots (`elo_league_adjusted`, `key_passes_under_pressure_diff`,
`set_piece_xg_diff`) are `PHASE7_FEATURES_REMOVED`, carrying an explicit
registry prohibition — "DO NOT include these in any training vector without
re-running ATE validation." All seven file paths the directive names are
missing from the repository.

⚠️ Its supplied `verify_and_update_matrix()` also writes
`always_data_gap_slots = 0` and `training_defaulted_slots = 0` into the
availability JSON unconditionally — a measurement outcome recorded without
measuring anything. The real producer is
`scripts/generate_feature_availability_matrix.py`. **Do not run that snippet.**

### Finding 2 — the xG ingestion exists, is tested, and has never been executed

This is the genuine gap, and it is the recurring "built, tested, wired to
nothing" shape this ledger has caught before (item 6's CLV capture, the
`ScrapedTeamFormStore` zero-caller defect):

- `backend/src/connectors/understat_source.py` — `UnderstatTeamXGSource`, with
  `team_match_xg()` and `rolling_xg_features()`; tested in
  `tests/test_connectors/test_understat_source.py`.
- `backend/src/connectors/statsbomb_open.py` — `StatsBombOpenDataSource`;
  tested in `tests/test_connectors/test_statsbomb_open.py`.
- `backend/scripts/backfill_v4_data_sources.py` — the driver, writing Parquet +
  JSON manifests to `data/processed/v4_sources`.

**That output directory did not exist** before 2026-09-03. The pipeline had
never produced a single artefact; `backend/data/processed/` held only the five
synthetic `*_training.csv` files from the pre-vΩ.46 era.

### ✅ The corpus now exists (2026-09-03)

Fetched after fixing the two blocking defects below. 70 parquet files
(35 league-seasons × matches + rollups) in `backend/data/processed/v4_sources/`:

```text
season      2019  2020  2021  2022  2023  2024  2025
bundesliga   306   306   306   306   306   306   306
epl          380   380   380   380   380   380   380
la_liga      380   380   380   380   380   380   380
ligue_1      380   380   380   380   306   306   306
serie_a      380   380   380   380   380   380   380
```

**12,560 matches**, 0 empty frames, mean home xG 1.359–1.931 across all 35
league-seasons. Cross-checks that the shape is real rather than plausible:
Bundesliga is 306 throughout (18 teams × 34 ÷ 2); Ligue 1 drops 380 → 306 from
2023 onward, which is the actual 20 → 18 team reduction; the 12,560 total sits
just under the 12,765 real matches already in `backend/data/cache/fd_*.csv`.

⚠️ **202 xG nulls, all in one place, and they must be DROPPED not filled.**
Every one is Ligue 1 2019/20 between 2020-03-13 and 2020-07-09, flagged
`is_result=False, has_data=False` — the 101 fixtures (× 2 sides) France
cancelled when COVID ended that season early rather than resuming it. 380 − 279
played = 101 exactly. These are genuinely unplayed matches, not missing
measurements. **Any training builder that default-fills them (`fillna(0.0)`,
registry defaults) is fabricating xG for matches that never happened** — filter
on `has_data` / `is_result` instead. This is the same trap the rejected sprint
directive's own `compute_rolling_features()` fell into with its trailing
`.fillna(0.0)`.

Not yet done: joining this into a candidate training frame, or measuring
anything against the incumbent. The corpus is acquired; nothing consumes it yet.

### ⭐ Finding 4 — the registry's "non-discriminative" ATE finding does not reproduce on real data (2026-09-03)

`feature_registry.py` blocks `shot_quality_diff` because the xG-derived proxy
"collapses to q75=0 **on synthetic training data**, making ATE estimates
non-discriminative". That clause named the *data*, not the feature — so with a
real corpus it was re-measurable for the first time
(`scripts/measure_xg_feature_ate.py`, evidence in
`reports/evaluation/xg-feature-ate.{md,json}`). 11,419 leak-free rows,
`shift(1)` rolling-5 partitioned by (league, season), cold-start rows dropped
rather than imputed:

| feature | ate_win | p | class |
|---|---|---|---|
| `xg_differential` | **0.2464** | 0.0000 | CAUSAL_DRIVER |
| `xg_attack_diff` | **0.2169** | 0.0000 | CAUSAL_DRIVER |
| `xg_defense_diff` | **0.1790** | 0.0000 | CAUSAL_DRIVER |
| `finishing_efficiency_gap` | 0.0082 | 0.3851 | INDEPENDENT |

Roughly 12× the 0.02 practical threshold. And the estimator **discriminates**
rather than rubber-stamping: `finishing_efficiency_gap` (goals minus xG, a
famously mean-reverting quantity) correctly lands below threshold at p=0.385.

⚠️ **This does not unblock `shot_quality_diff`, and must not be read as doing
so.** That feature is PSxG-based; Understat publishes no PSxG and no shot
counts. The registry's condition names a *StatsBomb event-level shots corpus*,
which this is not. `defensive_vulnerability_index` is equally unmeasurable here.
Finding 3's chain separation is unchanged.

⚠️ **`xg_differential` is not a canonical slot** — it lives only as an
intermediate in `data/transformers.py`. Putting it in `CANONICAL_FEATURES_68`
changes the vector width, which is exactly the 2026-06-10 incident this file
records: 65 columns emitted against 68-column artifacts, `PredictionEngine`
correctly refusing to zero-pad, `model_version="fallback"` served on every
inference for two months.

⚠️ **The estimate is a median-split proxy, unadjusted for confounders.** Team
quality drives both rolling xG and outcome, so part of the effect is
association.

**What it licenses:** a *candidate* feature-schema version carrying the xG
family, trained and put through the existing promotion gate
(`certification_policy.py` v1.0.0, SHA `41cb7703…`) against the incumbent. That
is an authorised schema decision with a real cost (new artifacts, new manifest,
new contract hash), not a unilateral edit — and specifically **not** achievable
by deleting the constant-fill at `retrain_with_expanded_features.py:224-226`,
which would silently feed the registry defaults' replacement into 68-column
artifacts that were never trained on them.

**Gate 50 is unchanged by any of this.** `test_uncertainty_contract.py`:
25 passed / 2 xfailed, gaps identical to the documented baseline (EPL −0.0217,
BUNDESLIGA −0.0448, LA_LIGA −0.0025, LIGUE_1 −0.0288, SERIE_A −0.0098).
Acquiring a corpus does not move an uncertainty gate; only a
better-generalizing *generation* could, and none has been trained.

⭐ **And it could not have worked — a blocking defect was found the first time it
was run for real (fixed 2026-09-03).** `LEAGUE_TO_UNDERSTAT` mapped SabiScore
slugs to Understat's *website* slugs (`"epl" → "EPL"`, `"la_liga" → "La_Liga"`),
but `sd.Understat(leagues=...)` takes **soccerdata's own standardized league
IDs** (`"ENG-Premier League"`, `"ESP-La Liga"`, …) and its `_selected_leagues`
setter raises `ValueError` on any id absent from `LEAGUE_DICT`. Every league of
every season would have raised, been swallowed by
`backfill_v4_data_sources.py`'s broad `except Exception`, and recorded as an
opaque `"Understat error: ..."` warning — a manifest that looks like it ran,
with zero artefacts and no stated cause.

⚠️ **The two vocabularies are a trap of the exact shape this repo keeps hitting**
(the canonical-vs-display league ids, the three team-name normalizers, the odds
`_team_key` copies). `EPL` is even a *valid-looking* Understat URL slug —
`understat.com/league/EPL` is a real page — so the map read as correct.

It survived because the connector's soccerdata-facing half has **no test
coverage**: the suite's own docstring says it "only exercises the parts that
need no network / no soccerdata install", and its nine tests cover
`_resolve_team_name` and the pure `rolling_xg_features`. Nothing had ever called
`_reader` or `team_match_xg`. Now pinned by three tests in
`tests/test_connectors/test_understat_source.py` asserting every mapped value is
a real soccerdata id — deliberately **without** importing soccerdata, since it is
absent from the default venv and an import-guard would skip the test in exactly
the environment that needs it. `_reader` also now validates the league *before*
importing the optional dependency and fails closed with a nameable error.

⚠️ **Generalisable lesson: "tested" told us nothing here.** A green suite on a
module whose only real integration path has never once executed is not evidence
that path works. When a connector has zero artefacts on disk, suspect the
connector, not the schedule.

That corpus is the binding prerequisite for four separate open items:
`shot_quality_diff`'s own written unblock condition ("Permanent DATA_GAP until
real StatsBomb event-level shots corpus confirms ATE >= 0.02", guardrail 12 of
the Sprint 4 brief), item 13 (tactical feature family), item 10 (offline
artifacts frozen 2024-06-02 and synthetically keyed), and item 50 route (b).

⚠️ **Do not add a second team-name map for it.** The directive proposed a new
`canonical_team_map.json` with hard-fail-on-unmapped. The hard-fail principle is
already `reconcile_team()`'s `UNKNOWN` behaviour, and this repository has
recorded three separate production incidents caused by introducing a *second*
normalizer beside `team_identity._identity_key` (the two odds `_team_key`
copies, the market aliases). `understat_source.py` already resolves via
rapidfuzz. A third vocabulary is the exact defect class.

### Environment finding — the research stack does not install on Python 3.14

`requirements-training.txt` pins every entry `python_version < "3.14"`, and the
local dev venv is 3.14.6. A `pip install soccerdata rapidfuzz` there produced no
output and no installed package after ten minutes — the same no-wheels trap
CLAUDE.md already records for catboost/shap ("Do not 'fix' by pip-installing on
3.14"). Offline research work of this kind belongs in a separate `.venv-ml`
(already gitignored, line 11) built on the machine's Python 3.12, which the
training pins accept.

### Finding 3 — Understat and `shot_quality_diff` are two different chains

⚠️ **Do not treat the Understat backfill as progress on `shot_quality_diff`.**
They share the word "xG" and nothing else:

- **Understat chain** (running): `understat_source.py` → `data/processed/v4_sources/*.parquet`
  → team-level xG/xGA rollups. Serves item 50 route (b), item 13, and the
  `phase9_xg_market_features` research surface. Understat publishes xG, xGA and
  shot counts; it does **not** publish post-shot xG.
- **`shot_quality_diff` chain** (not running, and its producer is the wrong one):
  the feature is consumed by `StatsBombAggregator`, which only *reads*
  `settings.statsbomb_cache_path` (`data/processed/statsbomb_features_cache.parquet`).
  That file does not currently exist locally.

The producer that does exist, `scripts/build_statsbomb_cache.py`, is titled
"StatsBomb-**like**" and derives its columns from the database `MatchStats`
table — i.e. it produces exactly the proxy `feature_registry.py:142` blames for
the non-discriminative ATE in the first place ("proxy derived from `xg_avg_5`
difference collapses to q75=0"). Re-running it cannot satisfy a guardrail whose
text is "until **real StatsBomb event-level shot-map data** confirms ATE >=
0.02". Item 10 says the same thing from the other direction: "Regenerating
StatsBomb needs the open-data corpus re-cloned (offline, large)."

So the `shot_quality_diff` unblock needs a distinct piece of work: clone
`github.com/statsbomb/open-data`, extend `connectors/statsbomb_open.py`
(`shot_features()` already exists) into a real producer for the Phase 8 cache
schema, then run the ATE. ⚠️ **Scope that honestly before starting** — StatsBomb
open data does not cover five top-flight European leagues across seven seasons;
its free tier is a selected set of competitions. The likely outcome is that
`shot_quality_diff` cannot be validated at corpus scale at all, which is a
legitimate finding and leaves the feature exactly where it is.

The ATE machinery itself is ready and needs nothing new:
`models/causal_selector.py`'s `CausalFeatureSelector(practical_ate=0.02)` already
carries the guardrail's own threshold, and `analyze(frame, feature_cols=[...])`
takes a features+outcome frame directly.

### ⭐ Finding 5 — the corpus is now in git, and serving cannot produce the xG family (2026-09-03)

**The corpus is tracked.** `backend/data/processed/v4_sources/` was gitignored
and existed on exactly one developer machine, so neither CI nor any future
training run could reach it and re-acquiring it meant a 35-league-season
Understat backfill. It is now committed: 70 parquet + 42 JSON, **2.4 MB**.

⚠️ The "18 MB" figure quoted at handoff was NTFS block allocation over 112 small
files plus a hidden `.soccerdata/` HTTP cache. The derived corpus — the part any
training run actually reads — is 2.4 MB, one fifth of `backend/data/cache`,
which this repository has always tracked for precisely the same reason. **No
object-storage bucket and no sync automation were needed**; proposals to add
Supabase/S3 for this were sized against the wrong number. soccerdata's raw
`.soccerdata/` cache (15 MB) stays ignored: it is a library-internal format a
soccerdata upgrade can invalidate, and re-fetching it is what the backfill
script already does.

Tracking a data asset creates a failure mode the repo did not have — silent
truncation by a partial commit, or `* text=auto` normalising a parquet. Pinned
by `tests/unit/test_understat_corpus_integrity.py` (38 tests, watched failing on
a deliberately truncated parquet before being trusted), which asserts every
file's row count against the count its own acquisition manifest recorded, plus
`*.parquet binary` in `.gitattributes`.

⛔ **Serving cannot produce the xG family today, so Finding 4's licence cannot
yet be exercised.** Probed against production `sabiscore-db-v3`
(`alembic_version` = `0013_push_devices`, i.e. the live database) on 2026-09-03:

```sql
SELECT count(*) FROM matches;       -- 12965
SELECT count(*) FROM match_stats;   --     0
```

`match_stats` is the *only* xG source serving has:
`upcoming_match_feature_service._get_team_xg()` selects
`MatchStats.expected_goals`, and `MatchContext.psxg_home/away` is likewise 0
rows. Every serving-time xG lookup returns `None` and has always done so.

Training the three validated features on the Understat corpus while serving
observes none of them is exactly APEX §26's "train on unavailable serving
features". It is also mechanically self-defeating: `promotion_evidence.py`'s
`serving_feature_availability` gate compares the candidate contract against
`current_serving_contract()`, so a schema carrying features serving cannot
compute fails the gate **by construction** — the same gate that already
quarantined the incumbent candidate. Authoring the schema first produces a
second quarantined candidate and no information.

⭐ **The blocker is operational, not architectural, and that is the useful part.**
Writers for `MatchStats.expected_goals` already exist and are tested —
`data/loaders/understat.py`, `data/orchestrator.py`, `data/loaders/football_data.py`,
`services/data_ingestion.py`. This is the same "built, tested, wired to nothing"
shape as Finding 2, one layer further down: the corpus ingestion now runs, but
nothing carries its output into the serving store. **The ordering is therefore
forced** — populate `match_stats` from the corpus and give serving a leak-free
rolling-xG projection matching training's `shift(1)`, window-5, `min_periods=3`
semantics; *then* author the candidate schema.

### ✅ Serving-side half done (2026-09-03): the rolling projection exists, the corpus write-through does not

The train/serve parity half of the forced ordering above is complete:

- `feature_registry.rolling_xg_mean()` / `derive_xg_rolling_features()` — the
  shift(1)/window-5/min_periods-3 rolling arithmetic, defined **once** and
  called by both `scripts/measure_xg_feature_ate.py` (training/research) and
  `UpcomingMatchFeatureProjector.project_xg_rolling_features()` (serving). A
  cold-start side returns `None`, never a fabricated `0.0`.
- `UpcomingMatchFeatureProjector.project_xg_rolling_features()` — the serving
  projection itself. Returns `None` (a `DATA_GAP`) whenever either side falls
  below `XG_ROLLING_MIN_PERIODS`, which is the honest answer for every fixture
  today: `match_stats` still holds 0 rows in production.
- **The `_get_team_xg()` `ORDER BY` bug named above is fixed**, not just
  flagged. It never fired in production only because `match_stats` was always
  empty; pinned by
  `tests/unit/test_xg_rolling_parity.py::test_get_team_xg_series_orders_most_recent_first_regardless_of_insert_order`,
  which seeds an older match *after* a newer one and asserts the series still
  comes back newest-first. The three copies of the temporal leak-boundary
  predicate (`_get_team_stats`, `_get_team_results_sequence`, and this new
  projection) are now one function, `_completed_matches_before()` — three
  copies of "matches strictly before kickoff" was three places a future edit
  could diverge one from the others.
- 10 tests in `test_xg_rolling_parity.py`, all passing; full regression run
  across every test touching either file (150 tests) green; mypy: fixing the
  two `None`-narrowing errors this change introduced left the local Windows
  count at **765** (down from the pre-change baseline of 774), comfortably
  under the 784 CI ceiling.

**Still not done, and this PR does not attempt either:**

1. **The corpus write-through itself.** No code carries the tracked Understat
   corpus's xG into `match_stats`. `project_xg_rolling_features()` has nothing
   to read until a backfill runs — writing `Match`/`MatchStats` rows requires
   resolving Understat's team/match identifiers against the canonical
   `teams`/`matches` tables (production has both `fd-team-epl:manchester_united_fc`
   and `fdco-team-epl-man_city`-style ids from two different provider
   lineages, so this is a real entity-resolution problem, not a straight
   join). This is the actual "wire it up" work and is sized like Milestone 1,
   not a follow-on to this PR.
2. **`promotion_evidence.py` is still hardwired to `APEX_FEATURES_68`**
   (`REPORT_SCHEMA`, the width check in `_stack_candidate_rows`, the row-count
   check in the validator — 9 call sites total). Parameterising it needs its
   own care: `REPORT_SCHEMA` is presently a module constant checked against
   every stored report's `"schema"` field, so widening it touches the
   validator's backward-compatibility contract with every historical report
   on disk, not just new ones.

Both remain prerequisites for items 1–2 of the schema-promotion directive.
Authoring `apex_v2_71` before either exists still fails
`serving_feature_availability` by construction — see the paragraph above.

### ⭐ Finding 6 — the review-only backfill manifest exists; production probing found a pre-existing team-identity defect that bounds it (2026-09-03)

`understat_match_stats_reconciliation_service.py` /
`scripts/review_understat_match_stats_backfill.py` build a read-only manifest
resolving every corpus row to (`home_team_id`, `away_team_id`, `match_id`) or
an explicit `TEAM_UNRESOLVED` / `MATCH_UNRESOLVED` / `MATCH_AMBIGUOUS` reason.
No `--apply` mode exists yet — see below.

Entity resolution reuses `team_identity.resolve_team_id()` verbatim (the exact
function `fixture_sync_service` and the orphan-team-repair manifest both
call). **No second team-name normalizer was written**, per this file's own
standing prohibition (Finding 3 of a different item, and three prior
production incidents). Match resolution is a direct `(home_team_id,
away_team_id, match_date ± 36h)` lookup — no fuzzy scoring needed once both
sides are already canonical IDs.

⚠️ **Before trusting a review-mode number, production was probed directly**
(read-only, `sabiscore-db-v3`) rather than assumed, and it surfaced a real
defect in `resolve_team_id()` itself — pre-existing, not introduced by this
work, and out of scope to fix here:

```sql
-- EPL teams table carries two provider-lineage id schemes for the same club:
fd-team-epl:manchester_city_fc  "Manchester City FC"   2 matches, 2 Elo rows
fdco-team-epl-man_city          "Man City"           267 matches, 266 Elo rows
fd-team-epl:newcastle_united_fc "Newcastle United FC"   1 match,  1 Elo row
fdco-team-epl-newcastle         "Newcastle"          268 matches, 267 Elo rows
```

`resolve_team_id("Manchester City", ..., require_elo_history=True)` returns
the **wrong** id. Trace: no exact-name match; the affix-strip stage reduces
"Manchester City FC" → "Manchester City", matching the input exactly, and
returns immediately — before the audited-alias stage (which already contains
`("EPL", "manchester city"): "man city"`, added for a different call site)
ever runs. `require_elo_history=True` does not save it: that gate excludes a
candidate only at **zero** Elo rows, and this near-orphaned duplicate has 2,
not 0. The identical trace applies to "Newcastle United" against
"Newcastle United FC" — no audited alias for this pair exists at all.
Brighton, by contrast, resolves correctly by pure luck: Understat's own name
"Brighton" is an *exact* string match for the high-usage row's display name,
so exact-match wins before affix-stripping ever runs.

A broader probe (`match_count < 15` across LA_LIGA/SERIE_A/BUNDESLIGA/LIGUE_1)
found the same low-but-nonzero-usage duplicate pattern is **systemic across
every league**, not an EPL quirk — FC Barcelona, Paris Saint-Germain, AS Roma,
SS Lazio, and others each carry a near-orphaned `fd-team-*:` duplicate
alongside their real, high-usage row. Bundesliga's mojibake orphans
(`fc_bayern_m??nchen`, `borussia_m??nchengladbach`, both **0** matches) are the
one variant that *is* already handled correctly: zero Elo rows means
`require_elo_history=True` excludes them, so the existing audited aliases for
Bayern/M'gladbach/Frankfurt/Hamburg do fire as designed. The dangerous case is
specifically nonzero-but-small — enough to survive the Elo-history gate, not
enough to be the club's real identity.

**This does not corrupt anything.** The failure mode is fail-closed
under-coverage, not silent misattribution: `_resolve_match_id()` looks up
`Match` rows by exact resolved `team_id`, and a near-orphaned duplicate has
almost no real matches to find — so affected fixtures surface as
`MATCH_UNRESOLVED` in the manifest, never a match written against the wrong
team. Confirmed by `test_two_candidate_matches_in_window_is_ambiguous_not_guessed`
and its `TEAM_UNRESOLVED` sibling in the new test suite: ambiguity and
misresolution both fail closed, they do not fabricate a write.

**What this bounds, honestly:** a real review run against production will
undercount Manchester City, Newcastle, and — pending the same check against
the other four leagues — an unknown-but-nonzero number of additional clubs,
until `resolve_team_id()`'s stage ordering (or the affected duplicate rows
themselves) is fixed separately. That is shared, heavily-depended-on
infrastructure (fixture sync, orphan-team repair, this manifest all call it);
reordering its resolution stages is its own careful, fully-regression-tested
change, not a corollary of this PR.

⚠️ **`/code-review` caught a real bug before this ever reached Postgres:**
`_resolve_match_id` bound a tz-aware `kickoff` window directly against
`Match.match_date` (a naive `TIMESTAMP WITHOUT TIME ZONE` column) — the exact,
repeatedly-documented asyncpg `DataError` trap already fixed at
`upcoming_match_feature_service.py:230` and
`notification_dispatch_service._now_naive_utc()`. Every one of this module's
own tests passed anyway, because they run on `sqlite+aiosqlite`, which accepts
either. Since `review_understat_match_stats_backfill.py` refuses to run
against anything but PostgreSQL, this would have failed on literally the first
row of the first real review run — a defect the test suite was structurally
incapable of catching on its own. Fixed by extracting the windowing into its
own pure `_kickoff_window()` function, unit-tested directly for
`tzinfo is None` without needing a live Postgres connection. Left as a
standing note: any future datetime bound against `Match.match_date` in this
codebase needs the same manual check — SQLite will not do it for you.

**Still not built, deliberately:** the `--apply` write path. The orphan-team
identity repair script (`scripts/repair_orphan_team_identities.py`)
establishes the house pattern for a script that writes production identity
data — reviewed-manifest-hash gate, explicit `--authorization-id`, a literal
confirmation token, re-validation of each row's exact pre-state under
write-conflict locks, single commit after postconditions pass. `--apply` for
`match_stats` should follow that pattern once a real review run's numbers are
in hand; building it against a hypothetical resolution rate would be
guessing at the one thing this Finding exists to measure honestly.

**Trigger to close:** `data/processed/v4_sources` holds real Understat artefacts
for the five scoreable leagues across the seasons the football-data corpus
already covers (2019/20 through 2025/26), with manifests, and they have been
joined into a candidate training frame and measured against the incumbent. The
`shot_quality_diff` ATE is explicitly **not** part of this trigger — see
Finding 3; it is separate work with its own coverage risk. A passing ATE
(>= 0.02) is what would authorise removing that one feature from
`PHASE7_FEATURES_ALWAYS_DATA_GAP` — a failing one leaves it exactly where it is,
and that is a legitimate outcome, not a blocked one.

**Blast radius:** none. Nothing in this entry changes serving behaviour;
`UNCERTAINTY_GATES`, `certification_policy.py`, and the feature registry are
untouched.

---

### ⭐ Finding 7 — `resolve_team_id()`'s stage-ordering defect fixed; a real review run measured the actual coverage; `promotion_evidence.py`'s second prerequisite cleared (2026-09-03)

With `DATABASE_URL` available this session, Finding 6's defect was fixed and
the review script run for real against `sabiscore-db-v3`, rather than
estimated.

**The fix.** `resolve_team_id()` now checks `_AUDITED_ALIASES` immediately
after an exact-name match, *before* affix-stripping — not after it, as
Finding 6 found. Affix-stripping a near-orphaned duplicate's full legal name
("Manchester City FC" → "Manchester City") produces an exact string match
against the resolver's own normalization of the input, so the alias — an
explicit human identity assertion — has to outrank that heuristic, the same
way the existing code already made it outrank containment for Paris SG/Paris
FC. Nine regression tests cover this (`test_team_identity.py`,
`test_understat_match_stats_reconciliation.py`), including one that keeps a
synthetic near-orphan pair with **no** alias entry to prove the fail-closed
behavior survives for clubs an alias doesn't (yet) cover.

**A real review run, not an estimate.** Before the fix: 9,255 `READY` /
2,532 `TEAM_UNRESOLVED` / 672 `MATCH_UNRESOLVED` of 12,459 corpus rows
(74.3% ready). The `TEAM_UNRESOLVED` sample turned out to be exactly **12**
unique `(league, name)` pairs behind all 2,532 rows — not a long tail, a
short, enumerable list, each independently confirmed against production
before being asserted as a new `_AUDITED_ALIASES` entry:

```text
EPL         Wolverhampton Wanderers -> Wolves
EPL         West Bromwich Albion    -> West Brom
LA_LIGA     Celta Vigo              -> Celta de Vigo        ("de" breaks containment)
LA_LIGA     Atletico Madrid         -> Club Atlético de Madrid (same "de"-in-the-middle shape)
SERIE_A     Inter                   -> Internazionale Milano
LIGUE_1     Lyon                    -> Olympique Lyonnais    (4 chars, below containment's 5-char floor)
LIGUE_1     Brest                   -> Brestois
LIGUE_1     Nice                    -> OGC Nice
LIGUE_1     Lens                    -> Racing Club de Lens
LIGUE_1     Saint-Etienne           -> St Etienne
BUNDESLIGA  RasenBallsport Leipzig  -> RB Leipzig
BUNDESLIGA  FC Cologne              -> FC Koln               (anglicized vs. transliterated spelling)
```

After both fixes, a second real review run: **11,694 `READY`** / **0**
`TEAM_UNRESOLVED` / 765 `MATCH_UNRESOLVED` of the same 12,459 rows — **93.9%
ready**, up from 74.3%. `TEAM_UNRESOLVED` is not reduced, it is exactly zero.
Manifest SHA-256 for this run: `11e10486fbea3a1fc6288c8eb7aa2ee59999242cfc7f92b3534cf378ebc221ab`.

**What the remaining 765 `MATCH_UNRESOLVED` rows are, honestly.** Sampling
them shows a different, already-understood shape — not a team-identity bug.
They cluster heavily in the 2019/2020 season and involve clubs whose
canonical `matches` table history is itself thin (FC Barcelona: 14 matches;
Paris Saint-Germain: 5; AC Milan: 17 — see Finding 6's production dump). The
team side resolves correctly on both sides; there is simply no `Match` row
in the `± 36h` kickoff window for that fixture yet. Closing this further
means backfilling `matches` for these clubs' early seasons, a fixture-sync
gap, not a team-identity one — separate scope, not opened here.

**A second, real robustness bug found by actually running this against
production**, not by inspection: the first real review run died mid-way
through with `asyncpg.exceptions.ConnectionDoesNotExistError: connection was
closed in the middle of operation`. The review issued one `SELECT` per
corpus row for match resolution — ~12,459 sequential round trips over the
WAN to Render's Postgres, all inside one long-lived session — and the
connection was reset partway through purely from holding it open across that
many round trips, nothing else. Fixed by prefetching the full `matches` table
for the corpus's leagues once (`_load_match_index`, a handful of queries)
and resolving every row against the in-memory index instead — round trips
dropped from ~12,459 to about 6. The second run (pre-alias-fix) completed
cleanly; both post-fix runs above did too.

**`promotion_evidence.py`'s hardwiring, the other named prerequisite,
cleared.** All 9 call sites that assumed the candidate contract is always
`APEX_FEATURES_68` now take an explicit `candidate_features` parameter
(`build_promotion_feature_evidence`, `validate_promotion_feature_evidence`),
defaulting to `APEX_FEATURES_68` for exact backward compatibility with both
existing callers (`generate_feature_availability_matrix.py`,
`compare_candidate_vs_incumbent.py`) and all 8 pre-existing tests, which pass
unchanged. This was not cosmetic: before this fix, evaluating a candidate
*wider* than whatever is currently active in production — e.g. a 71-feature
schema adding `xg_differential`/`xg_attack_diff`/`xg_defense_diff` to the
68-feature base, exactly what this directive's next step requires — indexed
`serving_contract[index]` past the end of the (68-wide) list and raised
`IndexError` before any evidence could even be built. `_serving_feature_at()`
now returns `None` past the end of the serving contract instead, which
`_classification()` already treats as `SCHEMA_MISMATCH` (mechanically true:
a feature the current schema has never heard of cannot align with it). A new
regression test, `test_candidate_wider_than_active_serving_contract_does_not_crash`,
pins exactly this shape.

**What remains for candidate schema promotion, honestly:** the two named
prerequisites (this Finding, and Finding 6's identity defect) are both now
closed. What is *not* done here: no `apex_v2_71`-style candidate schema has
been authored, registered in `FEATURE_SCHEMA_VERSIONS`, trained, or compared
against the incumbent via `compare_candidate_vs_incumbent.py` — that is a
`train_on_real_matches.py`-level pipeline change (computing the three xG
rolling features per training row) with its own scope, deliberately not
started as a rider on this fix.

**Still not built, deliberately:** the `match_stats` `--apply` write path.
Finding 6's authorization-discipline reasoning is unchanged; what changed is
that the number to build it against is now real (11,694 rows) rather than
estimated.

⚠️ **`_AUDITED_ALIASES` is shared by two different production call sites, not
one — the first CI run of this PR caught the difference.** `resolve_team_id()`
consults it directly; `market_identity_key()` (`odds_service.py`,
`market_observation_service.py` — the live-market fixture matcher) also
falls back to it via `_MARKET_ALIASES.get(...) or _AUDITED_ALIASES.get(...)
or key`. Adding `("LIGUE_1", "nice"): "ogc nice"` for the corpus-resolution
use case also changed market-matching: `test_shared_place_name_without_an_exact_key_fails_closed`
fed abbreviated "Nice" specifically to prove a non-exact away key falls
through to the ambiguity-prone permissive stage and re-triggers the Paris
FC/PSG shared-place-name collision (item 40). With the alias in place, "Nice"
becomes an exact away match, which is enough on its own for the home side's
own exact match to disambiguate without ever reaching the permissive stage —
a genuine market-matching accuracy improvement, not a bug, since a live feed
sending bare "Nice" really does mean OGC Nice unambiguously. The test was
updated to a substitute pairing (`RC Strasbourg Alsace` / `Strasbourg`, no
alias, still permissive-stage-only) that keeps proving the same underlying
property. **Lesson for the next alias added to this table:** check it against
`test_odds_team_identity.py` too, not only the `resolve_team_id()` caller
suite — this file's targeted regression list originally missed it.

**Blast radius:** `resolve_team_id()` is shared, heavily-depended-on
infrastructure (fixture sync, orphan-team repair, this manifest). The
reordering was verified against every existing caller's test suite (67
tests across `test_team_identity.py`, `test_understat_match_stats_reconciliation.py`,
`test_team_identity_containment_collisions.py`, `test_fixture_sync.py`,
`test_orphan_team_reconciliation_service.py`, `test_provider_elo_identity_bridge.py`,
`test_fixture_sync_identity.py`) plus 12 new alias entries — all pass
unchanged or as newly asserted. `promotion_evidence.py`'s change is additive
and backward-compatible by construction (optional parameter, same default).
mypy: 766 errors — unchanged from Finding 6, comfortably under the 784 CI
ceiling.

### ✅ The `--apply` write path executed against production (2026-09-04)

**Supersedes the "11,694 rows" figure above:** that number predates the corpus
deduplication (#144), which moved both the manifest digest and the real
ready-row count. A fresh review run immediately before applying measured the
actual numbers: manifest `df9e7aa49a201e0434c52f92451c1baadff199a65a9264a8ca377a8c52304ac4`,
**9,980 ready / 653 `MATCH_UNRESOLVED` / 10,633 total** — the total matching
the corpus's independently-verified distinct-match count exactly. Do not
requote 11,694 again; PRODUCTION_EXECUTIVE_DIRECTIVE.md §0 already flagged it
as stale.

```text
--apply --manifest-sha256 df9e7aa4… \
  --authorization-id operator-authorized-2026-09-04-debt56-directive-phase1 \
  --confirm APPLY_UNDERSTAT_MATCH_STATS

committed: true · inserted_rows: 19960 · matches_written: 9980
already_present_rows: 0 · skipped_unresolved_entries: 653 · reversals_total: 19960
```

Both acceptance postconditions from PRODUCTION_EXECUTIVE_DIRECTIVE.md §5 Phase 1
step 4 verified directly: `inserted_rows == 2 × ready_rows` (19,960 = 2×9,980)
on the real apply; re-running the identical command afterward reported
`inserted_rows: 0`, `already_present_rows: 19,960`, `reversals_total: 0` —
nothing double-inserted, the refuse-to-overwrite guarantee holds.
`reversals_total: 19960` from the real apply is retained with the
authorization record for undo.

One operational note, not a correctness issue: the first idempotency-check
re-run (not the real apply) hit
`asyncpg.exceptions.ConnectionDoesNotExistError: connection was closed in the
middle of operation` mid-query, against Render's free/starter Postgres tier.
A plain retry succeeded cleanly with no special handling. No partial write
resulted — Postgres aborts an in-flight transaction on connection loss, and
the successful retry's own `already_present_rows: 19960` / `inserted_rows: 0`
is the evidence nothing was double-written by the failed attempt.

### ✅ Serving-side answer measured (2026-09-04) — this is what Finding 2 was waiting on

`upcoming_match_feature_service.project_xg_rolling_features` measured directly
(it has zero production call sites — this was ad hoc, not a real request path)
against all 89 currently-scheduled fixtures: **57 (64%) now return real
features**, where every one returned `None` before this backfill (empty
`match_stats`). By league: EPL 14/18, LA_LIGA 11/16, BUNDESLIGA 16/17,
SERIE_A 10/10, LIGUE_1 6/8, **EREDIVISIE 0/9, UCL 0/11**. The last two are
zero because the Understat corpus this backfill draws from has no rows for
either competition — confirmed independently: the apply's own `leagues` field
lists exactly `BUNDESLIGA, EPL, LA_LIGA, LIGUE_1, SERIE_A`, nothing else. Not
a fixture-identity or query defect; a real corpus-coverage gap.

**xG has a real serving future in 5 of 7 leagues.** Wiring
`project_xg_rolling_features` into a registered candidate feature schema —
giving it its first production caller — is
PRODUCTION_EXECUTIVE_DIRECTIVE.md Phase 2/3, not started here.

---

## 55. Naive/aware datetime crash class swept across M10-M13 — RESOLVED 2026-09-03, two residuals opened

**Tier:** `RESOLVED` (the found instances) + two new tracked residuals below.
Found while root-causing a live `POST /api/auth/login` 500: `UserAccount`,
`UserFavorite`, `UserSavedMatch`, `UserPreference`, `UserNotificationSubscription`,
`UserNotificationLog`, `PushDevice`, `ApiKey`, and `AnalyticsEvent` are all
naive `DateTime` columns (`db/models.py`/`core/database.py` — every timestamp
column in this codebase is naive, no exceptions), and several M10-M13 write
sites assigned `datetime.now(timezone.utc)` (tz-aware) straight to them —
asyncpg raises `can't subtract offset-naive and offset-aware datetimes` at
bind time. Same bug class already fixed repeatedly elsewhere in this codebase;
this was the one corner of it still live. Fixed in `auth.py`/`auth_service.py`
(PR #135, merged) and `notification_service.py`, `notification_dispatch_service.py`,
`developer_service.py`, `analytics_service.py` (this change) — every login,
favorite, saved match, preference write, push-device registration/delivery,
API key creation/use, and analytics event was affected.

**New shared helper, not an eighth reinvention.** `naive_utc_now()`/
`to_naive_utc()` in `backend/src/utils/db_time.py` — this exact fix had
already been independently reinvented at least seven times across
`auth_service.py`, `elo_state_service.py`, `market_observation_service.py`,
`clv_capture_service.py`, `prediction_log_service.py`,
`provider_evidence_service.py`, `notification_dispatch_service.py`, each with
a different name and no shared import. Those seven working copies were left
alone (no live bug, not worth the churn); new code should import the shared
one instead of adding an eighth.

**Residual 1 — RESOLVED 2026-09-03 — the SQLite/AsyncMock test fixture
convention cannot catch this bug class.** `test_push_device_registry.py` and `test_notification_dispatch_service.py`
exercise `PushDevice`/`UserNotificationLog` writes against a real SQLite
in-memory engine; SQLite has no native timestamp type and does not enforce
tz-awareness the way asyncpg does, so these suites stayed green through the
entire time the bug was live. `AsyncMock`-backed suites (the `auth_service.py`
precedent) are blind for the opposite reason — full mocking. Both blind spots
are why this shipped unnoticed. Regression tests added this round assert
`.tzinfo is None` directly (in `test_analytics_event_scrubbing.py`,
`test_developer_platform_api_keys.py`, `test_notifications_and_timezones.py`)
rather than trusting either fixture style to fail on its own; not retrofitted
onto the SQLite-backed suites since a round-trip through SQLite may silently
normalize the value regardless of correctness, which would make such an
assertion pass unconditionally and prove nothing.

**Verified 2026-09-03**, via a standalone SQLAlchemy+aiosqlite repro against
a plain (non-`timezone=True`) `DateTime` column, mirroring the exact column
convention in `db/models.py`: a tz-aware insert (`datetime.now(timezone.utc)`,
`tzinfo=UTC`) reads back with `tzinfo=None`. SQLite discards it. Both suites
now carry a comment at their `session` fixture stating this explicitly — a
green run there is not evidence those writes are tz-safe; only the
`.tzinfo is None` assertions added this round (in the AsyncMock/direct-value
suites) and production/asyncpg itself can prove that. No test behavior
changed — documentation only, since retrofitting an assertion here would, as
above, pass unconditionally and manufacture false confidence. Residual
closed.

**Residual 2 — 105 files use `datetime.now(timezone.utc)` repo-wide; only the
newest (M10-M13) subsystem was audited.** The idiom is correct almost
everywhere else (business logic, comparisons, non-DB timestamps — the vΩ.5
sweep deliberately made this the default). The other ~95 files were not
individually re-checked against their target column's nullability/type this
session — most predate M10-M13 and are already covered by earlier sweeps, but
that is inference from age, not a verified sweep. **Trigger to close:** treat
as low-priority unless a similar 500 surfaces elsewhere; a durable fix (a
custom lint rule cross-referencing "assigned to a `Mapped[datetime]` naive
column" against "value carries no tzinfo") would close this permanently but
was not attempted — out of scope for a same-session bug fix.

## 54. WEB_PUSH notification channel — RESOLVED 2026-09-02

**Tier:** `RESOLVED`. Closes the last open half of item 51 (the EMAIL half
closed 2026-09-02). `WEB_PUSH` had been an accepted value on
`user_notification_subscriptions.channel` and an option in the API schema since
the notification system shipped, but the dispatch worker explicitly skipped it
and counted `skipped_channel`. Persisted, never delivered.

**What shipped.**

| Layer | File |
|---|---|
| Transport | `backend/src/services/web_push_delivery.py` (new) |
| Schema | `push_devices` + `backend/alembic/versions/0013_push_devices.py` (new) |
| Persistence | `NotificationService.register_push_device` / `unregister_push_device` / `get_active_push_devices` |
| API | `/api/v1/notifications/push/public-key` + `/push/devices` (POST, DELETE) |
| Dispatch | `_dispatch_channel_side_effects` in `notification_dispatch_service.py` |
| Browser | `apps/web/public/sw.js`, `apps/web/src/lib/web-push.ts`, `MatchSubscribeModal.tsx` |
| CSP | `worker-src 'self'` in `apps/web/src/middleware.ts` |

**Decision: no new dependency, and the proof is the RFC's own test vector.**
The obvious route is `pywebpush`, which pulls `py-vapid` and `http-ece` — both
of which sit on `cryptography`, already a runtime dependency here. The web-push
content encoding is a fully specified HKDF chain plus one AES-128-GCM seal, so
composing it directly costs ~80 lines and adds nothing to
`requirements.runtime.txt`, which was deliberately trimmed to shorten Render
deploy windows. This follows the EMAIL precedent exactly (stdlib `smtplib`
over a vendor SDK).

⚠️ **Composing crypto yourself is only defensible with proof, so the proof is
the first test in the file.** RFC 8291 §5 publishes a complete worked example —
fixed UA keys, fixed sender key, fixed salt, fixed expected body — and
`encrypt_payload` reproduces it **byte for byte**. A second test decrypts a
freshly generated payload the way a user agent would (ECDH → HKDF → AES-GCM,
via `cryptography`'s own `HKDF`, not our helper), so the non-deterministic
production path is verified too. **This failure mode is otherwise completely
invisible from our side**: a push service accepts and forwards an
undecryptable body with a `201`, so without the vector, a wrong HKDF chain
would look like a fully working feature that no browser ever displays.

**Two tables, not one — deliberately.** `push_devices` is *transport* (where a
message can physically be delivered); `user_notification_subscriptions` stays
*intent* (what someone asked to hear about). Folding them together would have
meant re-registering the browser for every match subscribed to. `endpoint`
carries the unique constraint because it is the device identity as far as the
push service is concerned — a re-subscribe after a permission reset must
overwrite the stored keys in place, or the row keeps keys that no longer
decrypt and every send to it fails forever.

**Ownership scoping is a safety property, not an optimisation.**
`_active_devices_for` returns `[]` when a subscription has neither a `user_id`
nor an `anonymous_session_id`. An unscoped `select(PushDevice)` there would fan
one person's alert out to every registered browser in the table. Pinned by
`test_web_push_never_reaches_another_owners_device`.

**404/410 deactivates; 5xx does not.** A push service reports 404/410 when the
subscription is permanently gone, and the device is deactivated on the spot —
otherwise every future pass burns a request on an endpoint that can never
deliver. A 500 is the push service's problem, not a dead reader, and
deactivating on it would silently lose someone. Both pinned.

**The VAPID public key is served by the backend, not `NEXT_PUBLIC_*`.** It is
public by design (RFC 8292 §2), but routing it through
`GET /notifications/push/public-key` means a rotation is a backend restart
rather than a frontend redeploy, and the repo gains no new
credential-shaped build variable. The endpoint reports `configured: false`
while the channel is off, so the browser never attempts a subscription that
could not be delivered to.

⚠️ **`worker-src 'self'` had to be stated explicitly in the CSP.** It falls
back to `script-src`, which carries `'strict-dynamic'` — and that neutralises
`'self'`, so `/sw.js` would have been blocked with no nonce available to give
it. Service-worker registration failure is silent from the page's perspective;
this is the same class as the vΩ.8 CSP hydration bug, caught before shipping
rather than after.

**Also fixed, found while wiring the UI:** `MatchSubscribeModal.handleSubmit`
ended in `catch {}`. Every failure — a rejected subscription, a network error —
was swallowed, and the modal simply stayed put with the button re-enabled, so a
failed alert looked exactly like one the reader had not submitted yet. The
modal now has an error surface, which is also what makes the four named
WEB_PUSH failure reasons (`unsupported`, `not_configured`, `permission_denied`,
`registration_failed`) visible instead of collapsing into silence.

⚠️ **Browser enrolment happens *before* the subscription row is created.**
Creating a `WEB_PUSH` subscription for a browser that never granted permission
would produce a row that can never deliver, and the dispatch worker would count
`web_push_skipped_no_device` forever with nothing on screen having said so.

**Rejected from the attached plan** (`Recommendations2.txt`, Path A), and why:

| Proposal | Disposition |
|---|---|
| BullMQ worker for push dispatch | **Rejected — competing job system.** BullMQ/ioredis is the TaxBridge/Hashablanca stack; SabiScore's background work runs in the FastAPI lifespan over direct Redis. Same rejection already recorded for the diagnostics plan in `reports/execution/plan-reconciliation.md` Appendix B. |
| `apps/api/routers/notifications.py` | **Rejected — banned legacy surface.** `apps/api/` is a known legacy skeleton CLAUDE.md forbids referencing in production. The real path is `backend/src/api/endpoints/notifications.py`. |
| Raw `0013_push_subscriptions.sql` | **Rejected — Alembic is the only schema authority.** Also `user_id UUID`: `users.id` is `String` here, so the proposed FK type would not have matched. |
| `POST /api/v1/notifications/subscribe` | **Renamed.** That path collides with the existing match-subscription flow; WEB_PUSH is a delivery channel, not a second subscription system. |
| `NEXT_PUBLIC_VAPID_PUBLIC_KEY` | **Replaced** by the backend-served endpoint, above. |
| `pywebpush` | **Replaced** by `cryptography`, above. |

**Not built:** a standalone push-preferences screen, and push for
`PROBABILITY_SWING` beyond what the shared dispatch path already gives it
(both channels route through `_dispatch_channel_side_effects`, so swing alerts
push today without a separate code path).

**Gates (final, PR #134 green):** backend **2116 passed / 15 skipped / 2
xfailed** in CI (2117/17/2 locally — the difference is the platform-dependent
optional-ML skip set) · ruff 0 · mypy **771 ≤ 784, unchanged from baseline** ·
18 `test_web_push_delivery.py` (incl. the RFC vector) · 15
`test_push_device_registry.py` · `test_notification_dispatch_service.py` 26/26
with 7 rewritten/new WEB_PUSH cases · Alembic `0013`
upgrade/downgrade/re-upgrade round trip clean · OpenAPI 108 paths · web lint 0 ·
typecheck 0 · Vitest 319/319 · production build exit 0 · Gitleaks clean over
the full branch range · **SonarCloud quality gate OK, new-code coverage 98.0%**.

⚠️ **Three CI failures on the way in, all worth recording:**

1. **Gitleaks flagged `const VAPID_KEY = "<87-char base64url>"`** — RFC 8291's
   *public* P-256 point, not a credential, but indistinguishable from one to a
   scanner. Fixed by constructing the fixture instead of pasting it, and by
   generating the backend test keypair per run rather than hardcoding a
   32-byte scalar next to a `PRIVATE_KEY` identifier. **Gitleaks was never run
   locally before pushing** — it is installed and takes under a second
   (`gitleaks detect -c .gitleaks.toml --log-opts="origin/master..HEAD"`).
2. **The `pull_request`-event scan still failed after the fix**, because it
   scans the whole branch range and the introducing commit's own patch remains
   in it. Force-push was denied (correctly — rewriting a branch with an open PR
   is the wrong tool), so this took the disposition the ledger already records
   twice: a `.gitleaksignore` fingerprint with the reasoning beside it.
3. **Two typecheck errors CI never reached**, because the Gitleaks gate failed
   first and skipped every downstream job. `vi.fn()` without declared
   parameters records calls as a 0- or 1-tuple, so `mock.calls[n][1]` does not
   compile. ⚠️ **The first commit claimed a clean typecheck; it had been run
   before the test file existed and not re-run after.** Re-run every gate after
   the last edit, not after the last edit you remember making.
4. **SonarCloud: new-code coverage 71.0% against a required 80%.** The
   uncovered lines were the ones that most needed testing —
   `notification_service.py` 36/45 and the three endpoints 12/35 had no direct
   coverage, only indirect exercise through the dispatch tests. Backfilled to
   **98.0%** with 22 tests that each pin a branch where the wrong behaviour is
   silent (upsert-on-endpoint, owner scoping, fail-closed endpoints, PEM key
   loading). Same trap the prior session recorded: **Sonar measures the diff,
   so touching a function makes its untested siblings newly count against
   you.**

## 53. The match page rendered two different edges for the same market — one of them computed in the browser from vigged odds — RESOLVED 2026-09-02

**Tier:** `RESOLVED`. Found from an operator screenshot of a live Ligue 1
fixture (`/match/fd-559696`, Toulouse FC vs Lille), not from a failing test.

**What was shown.** The `EDGE DELTA` card read
`Model 39.3% | Market 29.9% | +9.4% EV advantage`. Directly beneath it, in the
same scroll, `MARKET EDGE` printed the backend's own `odds_edge.edge`. The two
numbers were **structurally guaranteed to disagree**, and the visible one was
the wrong one.

**Root cause.** `EdgeDeltaBar` (`apps/web/src/components/full-analysis-dashboard.tsx`)
ignored the `edge` the backend already ships and recomputed its own:

```ts
const impliedProb = oddsEdge.market_odds > 0 ? 1 / oddsEdge.market_odds : 0;
const deltaPct = (modelProb - impliedProb) * 100;
```

`1 / market_odds` is the **vigged** price — the bookmaker's margin still in it.
The backend de-vigs before computing anything
(`_odds_edge_from_features`, `backend/src/api/endpoints/full_analysis.py`):
`fair = (1/odds) / overround`, then `edge = model_prob - fair`. Since
`overround > 1` for any real book, `fair < raw`, so the card's delta was
always *smaller* than the authoritative edge by `raw * (1 - 1/overround)` —
roughly 1.5pp on a typical 1X2 book. The screenshot's `29.9%` was the vigged
price labelled "Market"; the platform's own gloss elsewhere
(`betting-intelligence-dashboard.tsx`) defines edge as "Model prob. minus
**fair** implied".

**Three defects in one component, all fixed:**

1. **Backend-authority violation.** CLAUDE.md is explicit that `apps/web` must
   not "calculate verdicts, stake sizes, or EV independently", and that market
   de-vigging is backend-owned. This was frontend edge arithmetic. It now reads
   `oddsEdge.model_prob` and `oddsEdge.edge` and derives the fair probability
   exactly as `model_prob - edge` — no recomputation, no new backend field, and
   no way for the two cards to drift again.
2. **`EV advantage` on a probability-point delta.** Expected value is a
   different quantity the backend does compute internally
   (`model_prob * odds - 1`) and deliberately does not publish. The label is now
   `Model above fair market` / `Model below fair market` / `Level with fair
   market`. `Fade signal` (a betting-action word on a staking-disabled page)
   went with it.
3. **`%` for a difference of two percentages.** Now `pp`, matching
   `intelligence_synthesizer`'s own `+{edge}pp` narrative string and
   `fmtPp()` in the betting-intelligence dashboard.

`EdgeTooltip` (`ui/ResponsibleGamblingTooltip.tsx`) described edge against "the
bookmaker's implied probability" — the same vigged-vs-fair error in prose,
shown on the very card that renders the correct number. Corrected in the same
pass; it is the shared tooltip, so every caller is fixed at once.

⚠️ **The card's `ensemble` prop is gone.** It previously re-derived
`modelProb` by string-matching `oddsEdge.market` against the three ensemble
probabilities, with `draw_prob` as the silent fallback for any unrecognised
market string. `oddsEdge.model_prob` is the backend's own probability for the
market it actually selected — one field, no fallback, no way to mismatch.

**Sweep.** `grep -rnE "1 */ *[a-zA-Z_.]*[Oo]dds|implied"` over `apps/web/src`
found exactly one recomputation site (this one). `value-bet-scanner.tsx` reads
a backend-supplied `implied_prob`; every other hit is copy or a type
declaration. No sibling caller was left broken.

**Guards.** Three tests in `full-analysis-dashboard.test.tsx` pin the fair
probability, the `pp` unit, the absence of "EV advantage", and — the one that
matters most — that `EdgeDeltaBar` and `OddsEdgeCard` print the *same* number
for the same `odds_edge`. The fixture uses a 6% overround so the vigged and
fair figures are 1.7pp apart, far enough that the old code cannot pass by
rounding. **All three were watched failing against a reverted fix** (3 failed /
12 passed) before being trusted, then re-run green (15/15).

⚠️ **Why no zero-fabrication scan or copy-contract test could have caught
this.** Every prior truthfulness sweep hunted values that were *absent* or
*fabricated* (neutral Elo defaults, RL reward zeros, the structurally-false
`LIVE` badge). This number was real, derived from real odds, and internally
consistent — it was just **the wrong quantity, computed by the wrong
authority, under the wrong name**. The detectable signature was not the value
but the *disagreement with the card 40 lines below it*, which only a
side-by-side assertion catches.

**Gates:** web lint 0 · typecheck 0 · Vitest 304/304 · `NODE_ENV=production`
build exit 0. Backend untouched — it was already correct.

## 52. Live sitemap fixture discovery — RESOLVED 2026-09-02

**Tier:** `RESOLVED`. `apps/web/src/app/sitemap.ts` published 5 hand-typed
sample fixture ids (`"arsenal-vs-chelsea"`, ...) as if they were real,
crawlable matches — the exact "sample fixture entries" gap named in
`reports/execution/next-milestone.md`'s product-gaps list. New
`apps/web/src/lib/sitemap-fixtures-server.ts` fetches
`GET /api/v1/fixtures/upcoming?limit=200` directly from the backend (same
server-only-fetch shape as `team-intelligence-server.ts` — a relative URL
cannot be fetched from `sitemap.ts`), validates each `fixture_id` against the
same shape the fixture-proxy route already trusts
(`/^[a-zA-Z0-9_-]{1,64}$/`), and fails closed to an empty list on any
network error, non-OK response, HTML body, or malformed JSON — a broken
backend must never crash sitemap generation or publish a fabricated fixture.
`sitemap.ts`'s local league array was also replaced with the shared
`CANONICAL_LEAGUES` export (`lib/league.ts`) it was duplicating, and the
route gained `export const revalidate = 3600` (the fixture listing is a
bounded, cheap DB read — no provider calls, no model inference — so this
doesn't touch the no-store rule that genuinely applies to evidence/decision
endpoints). `TOP_TEAMS` is unchanged — no canonical, verified team-slug list
exists anywhere in `apps/web` to replace it with, and that's a separate gap.
**Tests:** `apps/web/src/lib/sitemap-fixtures-server.test.ts` (6 cases: valid
fixtures, invalid-id filtering, network error, non-ok response, HTML body,
malformed/missing `fixtures` field — all fail closed to `[]`).

## 51. Scheduled in-app notification delivery — RESOLVED 2026-09-01

**Tier:** `RESOLVED`. Filed and closed same day, APEX Ω milestone execution.

**Follow-up 2026-09-02 — EMAIL channel adapter shipped, WEB_PUSH still
deferred.** `backend/src/services/email_delivery.py` (new) sends via stdlib
`smtplib`/`ssl` rather than a vendor SDK, so any SMTP-speaking provider (SES,
Resend, Brevo, Gmail, ...) works with zero new dependency and no vendor
lock-in; config-gated behind `ENABLE_EMAIL_NOTIFICATIONS` (default `False`)
plus `SMTP_HOST`/`SMTP_PORT`/`SMTP_USERNAME`/`SMTP_PASSWORD`/
`SMTP_FROM_ADDRESS`/`SMTP_USE_TLS` — the same safe-default shape as the
provider `ENABLE_*` flags: inert until an operator supplies real credentials,
never a crash. `_DISPATCHED_CHANNELS` now includes `EMAIL` alongside
`IN_APP`, so an EMAIL subscription gets the in-app log row (inbox stays
complete regardless of channel) plus a best-effort SMTP send attempt that
never blocks the log write on failure. `apps/web/src/components/MatchSubscribeModal.tsx`
gained a Delivery selector (In-App / Email) with a destination-email input —
the `channel`/`destination` fields the backend `MatchSubscriptionCreate`
endpoint already accepted end-to-end but the UI never exposed. `WEB_PUSH`
remains genuinely deferred: it needs VAPID-signed, AES-128-GCM encrypted
requests (a real new dependency — `pywebpush` or equivalent, no stdlib path)
and a frontend service worker + subscribe UI that doesn't exist yet, a
materially larger lift than EMAIL's reuse of already-installed tooling.
**Tests:** `backend/tests/unit/test_email_delivery.py` (5 cases: disabled by
default, missing host/from-address, real SMTP send with TLS+auth, transport
failure never raises, no-credentials skips login).
`test_notification_dispatch_service.py` gained EMAIL-path coverage (log
written + send attempted, no-destination skip, send-failure doesn't block
the log write) and the old "non-IN_APP channel" skip test was retargeted at
`WEB_PUSH`, the channel that's actually still skipped.

Notification subscription CRUD, in-app log CRUD, and the frontend
`NotificationCenter`/`MatchSubscribeModal` UI existed (`docs/ARCHITECTURE.md`,
`reports/execution/plan-reconciliation.md` Feature 9), but no production
caller ever generated a kickoff-reminder or probability-swing in-app
notification — subscriptions sat inert forever.

`backend/src/services/notification_dispatch_service.py` (new) implements two
generators, both `IN_APP`-channel only in this release (`WEB_PUSH`/`EMAIL`
subscriptions are persisted but explicitly skipped and counted, never
silently dropped):

- **Kickoff reminders:** active `KICKOFF_REMINDER` subscriptions with a
  scheduled match inside `[kickoff - reminder_minutes_before, kickoff)`.
- **Probability-swing alerts:** active `PROBABILITY_SWING` subscriptions
  where the max absolute delta across home/draw/away probability between the
  two most recent `MatchPredictionLog` snapshots meets `threshold_pct`
  (default 5%).

Idempotency is log-based (no migration): a `(subscription_id, match_id,
category)` existence check against `UserNotificationLog` before insert, so a
repeated pass over identical state creates zero duplicates — verified by
`test_kickoff_reminder_idempotent_across_repeated_passes` and
`test_probability_swing_idempotent_across_repeated_passes`.

Wired into `backend/src/api/main.py`'s lifespan as
`_background_notification_dispatch()`, same handle-stored/cancel-on-shutdown
shape as fixture-sync/settlement/CLV, gated by
`ENABLE_NOTIFICATION_DISPATCH` (default true) and polled every
`NOTIFICATION_DISPATCH_INTERVAL_SECONDS` (default 300s). A failed pass is
logged and counted, never raised — it cannot affect `/health/ready` or
startup. `/health`'s `components.notification_dispatch` reports the same
informational-only snapshot shape as `settlement`/`clv_capture`.

`GET /api/v1/notifications/subscriptions/matches` (new) lists the caller's
active match subscriptions — the frontend proxy
(`apps/web/src/app/api/notifications/subscriptions/matches/route.ts`)
already forwarded `GET` here before this endpoint existed.

**Blast radius:** none on prediction/verdict/stake paths — this module never
reads or writes model, evidence, or betting-engine state; it only reads
`MatchPredictionLog`'s already-persisted probabilities.
**Deferred by design:** `WEB_PUSH` transport adapter (channel is recorded and
skipped, not built) — repeated re-alerting after the first
probability-swing notification for a subscription (avoids notification
storms in this first release — a controlled re-alerting window is a
follow-up, not this milestone).
**Tests:** `backend/tests/unit/test_notification_dispatch_service.py` (8
cases: due-window in/out, idempotency ×2, non-IN_APP channel skip, threshold
met/not-met, missing-snapshot skip). `backend/tests/unit/test_notifications_and_timezones.py`
gains one case for the new list-subscriptions service method.

---

## 50. Ensemble-dispersion epistemic uncertainty is built, real, and 5/6 certified — `error_association` fails on real evidence (hypotheses 2, 3 and 4 ruled out), so staking stays blocked

**Tier:** `NEXT` — genuinely open research question, not a Class C
authorization gap like items 38/49. **Blocks M2 / `MODEL_UNCERTAINTY_UNAVAILABLE`.**
Owner: unassigned. Found 2026-08-31, building the M2 certification milestone
(ADR 0009). Updated same day: hypothesis 2 investigated and ruled out.

> ⭐ **PROMOTED 2026-09-03 (operator decision): this is now THE active blocker
> for staking.** Item 42 — previously the headline staking blocker — was closed
> the same day once ADR 0009 was found to have superseded its proposed fix: a
> BNN cannot satisfy the epistemic gate at all, because
> `uncertainty_policy.UNCERTAINTY_METHOD = "ensemble_dispersion"` is *the only
> authorised method*. There is therefore no alternative route left. Every other
> uncertainty gate passes; `error_association` is the single remaining
> condition between the platform and a staking-capable state, and it is a
> research question, not an authorization or a dependency. Nothing else in the
> ledger can unblock staking by being resolved first.
>
> ⚠️ **This promotion does NOT lower the bar.** `UNCERTAINTY_REQUIRES_ALL_GATES`
> stays `True`, the threshold stays `min_rps_gap_top_vs_bottom = 0.0, strict`,
> and `_uncertainty_from_features` stays unconditionally `None`. Being the last
> blocker is not grounds for relaxing it — that inversion is exactly what
> APEX §23 forbids, and the gate failing in the *wrong direction* (see below)
> is evidence about the signal, not about the threshold.

`src/models/ensemble_uncertainty.py` implements the ADR's `ensemble_dispersion`
method (BALD decomposition over the shipped `random_forest`'s 300 bootstrap
trees) and it is real, working code — not a stub. Scored against the real
shipped `epl_ensemble_v5_phase7.pkl` artifact's own genuine chronological
holdout season (375 rows, none seen by any tree in `.fit()` —
`tests/unit/test_uncertainty_contract.py::TestRealCorpusValidation`), 5 of 6
`UNCERTAINTY_GATES` pass: `method_is_authorised`, `sufficient_members`,
`non_negative`, `determinism`, `independence_from_confidence` (|corr|=0.056),
`informative_within_confidence_band` (spread_ratio=3.17).

**`error_association` does not.** The gate requires the highest-epistemic
quartile to show worse mean RPS than the lowest. Measured, it is the reverse:
gap (highest − lowest bucket RPS) = −0.022, on the clean holdout — see the
ADR 0009 addendum for the full bucket table.

**Four hypotheses have now been tested. Three are ruled out and one is
substantially explained; none produces a pass:**

1. **Hypothesis 1 (artifact-inherent) — substantially explained, 2026-08-31,
   but NOT resolved into a pass.** Two new measurements:

   *It is systematic, not artifact-specific.* Every league whose artifact
   holdout has corpus rows fails, each on its own independently-trained
   artifact: BUNDESLIGA −0.0448, LIGUE_1 −0.0288, EPL −0.0217, SERIE_A
   −0.0098, LA_LIGA −0.0025. (EREDIVISIE is unscoreable — pooled model, zero
   rows in its own declared holdout season.) So this is a property of the
   decomposition on this feature set, not of one weak artifact.

   *Most of it is an aleatoric confound.* `corr(epistemic, aleatoric) = −0.267`
   while `corr(aleatoric, RPS) = +0.072` — aleatoric is the component that
   legitimately tracks error, and epistemic is anti-correlated with it, so
   bucketing by epistemic implicitly reverse-buckets by aleatoric. Conditioning
   on aleatoric collapses the reversal monotonically across terciles
   (−0.0104 → −0.0022 → **+0.0013**). Directional and small-n (62 rows/bucket),
   so suggestive, not conclusive.

   ⚠️ **The obvious fix is forbidden.** Re-specifying `error_association` as a
   within-aleatoric-stratum measurement would be re-defining a certification
   threshold *after* observing that it blocks promotion — APEX §23 and the
   certification directive both forbid exactly that, however sound the
   statistics. It would not cleanly pass anyway (two of three strata still
   carry the wrong sign). **This needs an authorized decision on the recorded
   evidence, not a unilateral edit.** See ADR 0009 Addendum 3.

4. **Hypothesis 4 (member basis — independently seeded ensembles) — RULED OUT,
   2026-09-03.** The structural suspicion, and the strongest one: bootstrap
   trees inside one RandomForest share hyperparameters, split logic and feature
   space, so their disagreement measures variance *within one localized
   hypothesis space* rather than ignorance of the data-generating function.
   Replacing them with independently seeded, independently resampled ensembles
   (a Deep-Ensembles-style basis) should yield a purer epistemic signal.
   Implemented in `scripts/spike_independent_ensemble_uncertainty.py`; only the
   *definition of a member* changes, `dispersion_from_members()` is called
   verbatim so the certified BALD math is the math under test.

   **It first appeared to work.** Two pre-declared member-count ladders
   (N ∈ {3,5,10,20,30}, seed blocks 1000 and 7000) removed the systematic
   reversal and turned mean skill positive in 9 of 10 points — block means
   **+0.0056** and **+0.0191** against a deterministic tree baseline of
   **−0.0190**:

   ```text
               seed 1000                    seed 7000
    members   skill   gap>0 skill>0        skill   gap>0 skill>0
      trees  -0.0190   0/5    0/5         -0.0190   0/5    0/5
          3  +0.0048   2/5    2/5         +0.0183   3/5    3/5
          5  +0.0175   4/5    4/5         +0.0282   5/5    5/5
         10  +0.0158   5/5    5/5         +0.0152   5/5    5/5
         20  -0.0102   3/5    1/5         +0.0321   5/5    5/5
         30  -0.0001   5/5    3/5         +0.0208   5/5    5/5
   ```

   ⚠️ **It was a confound in the spike's own design, not a result.** The default
   replica is an RF+XGB+LGBM stack while the incumbent basis is trees inside a
   single RandomForest — so the headline comparison moved member
   **independence** and member **composition** simultaneously. Re-run with
   `--rf-only`, which changes *only* independence:

   ```text
    trees (incumbent)          skill -0.0190              0/5
    RF-only seed 1000   +0.0007 / -0.0246 / -0.0323   2/5, 1/5, 1/5
    RF-only seed 7000   -0.0076 / -0.0212 / -0.0236   2/5, 1/5, 0/5
   ```

   **Independently seeded, independently resampled RandomForests reproduce the
   reversal** — 5 of 6 points negative, several *worse* than the incumbent.
   Seeding and resampling independence buys nothing. The entire apparent gain
   came from mixing model classes.

   ⚠️ **And that is the member design the frozen policy explicitly deprecates.**
   `UNCERTAINTY_GATES["sufficient_members"]`: *"Bootstrap or resampling variants
   are preferred over distinct algorithms: they vary the training sample, which
   is the sampling uncertainty epistemic uncertainty is meant to capture,
   whereas distinct algorithms vary only model class."* The only configuration
   that moves the metric is the one ADR 0009 calls less principled — a reason to
   distrust the effect, not to adopt it. Independently, N=30 would mean 30
   separately trained ensembles per league (180 artifacts, 30× training and
   storage), which fails the serving-cost constraint regardless of the
   statistics.

   **Method notes, so this is not re-run naively.** Ladders are pre-declared and
   reported in full — raising N until the result passes is goalpost-moving, and
   the seed-1000 ladder alone would have read as a clean 5/5 success at N=10 and
   a 1/5 failure at N=20 on the same rows. The two seed blocks are disjoint;
   repeating a configuration reproduces it exactly (the `determinism` gate the
   policy already passes). Ladder points within a seed block are nested prefixes
   of one replica set, so they isolate member count from seed choice but are not
   independent samples.

3. **Hypothesis 3 (RPS outcome-mix artifact) — RULED OUT, 2026-09-03.**
   Ordered RPS over [home, draw, away] is not symmetric across outcomes: for a
   prediction `p`, a DRAW costs `(p_h² + p_a²)/2` while a HOME costs
   `((p_h−1)² + (p_h+p_d−1)²)/2` — for a typical `p=[.45,.27,.28]` that is
   **0.140 (draw) vs 0.190 (home) vs 0.360 (away)**. Draws are structurally
   cheap in RPS. Since high epistemic ↔ trees disagree ↔ evenly matched sides,
   and evenly matched sides draw more often, the top bucket could be earning a
   purely mechanical discount unrelated to the uncertainty signal. This is a
   confound in *realised-outcome* space, distinct from Addendum 3's aleatoric
   confound in *prediction* space, and had not been tested.

   **Measured and refuted** (`backend/scripts/diagnose_error_association_outcome_mix.py`;
   reproduce from the repository root with
   `cd backend && PYTHONPATH=. python scripts/diagnose_error_association_outcome_mix.py`).
   A constant league-base-rate forecaster — fitted on pre-holdout seasons, so it
   knows nothing about any individual fixture — was scored on the same holdout
   rows with the same bucketing. Every bucket-to-bucket difference it shows is
   pure outcome mix:

   ```text
   league         n  gap_model   gap_ref  skill_gap  draw% Q1 draw% Q4
   EPL          375    -0.0217   -0.0004    -0.0212    21.5%   24.0%
   LA_LIGA      380    -0.0025   +0.0215    -0.0240    29.5%   23.2%
   BUNDESLIGA   296    -0.0448   -0.0151    -0.0297    24.3%   27.0%
   SERIE_A      375    -0.0098   -0.0032    -0.0065    24.7%   29.2%
   LIGUE_1      306    -0.0288   -0.0151    -0.0137    18.4%   20.5%
   MEAN                -0.0215   -0.0025    -0.0190
   ```

   The draw rate *does* rise with epistemic in 4 of 5 leagues, so the mechanism
   is real — but it is far too small to matter. **Outcome mix explains 12% of
   the mean gap, and `skill_gap` stays negative in 5 of 5 leagues.** The
   reversal survives removing the mechanical effect entirely.

   ✅ **The measurement is controlled**: bucketing is rank-based and equal-size,
   byte-identical to the gate's own test, so `gap_model` reproduces the
   published per-league numbers **exactly** (−0.0217 / −0.0025 / −0.0448 /
   −0.0098 / −0.0288), not approximately. A first pass using quantile cuts
   matched only 2 of 5 and was corrected before any conclusion was drawn — if
   this script ever stops reproducing them, it is measuring something else and
   its verdict does not hold.

   ⚠️ **One genuinely new observation, pointing the opposite way from the
   gate's premise.** LA_LIGA's `gap_ref` is **+0.0215**: by pure outcome mix its
   high-epistemic bucket should be *harder*, yet the model scores essentially
   flat there (`gap_model` −0.0025). Its advantage over a naive prior is
   therefore substantially **larger** where epistemic uncertainty is highest.
   Combined with `out_of_support` PASSING (novel regimes lift mean epistemic
   1.34×–2.54×), the emerging picture is that BALD dispersion over RF bootstrap
   trees detects **distributional novelty** but does not rank **in-distribution
   error** — plausibly because tree disagreement tracks feature
   *informativeness* (features push different trees to different confident
   splits) rather than fixture *difficulty*. Those are different quantities,
   and `error_association` assumes they are the same one.

   **This does not license a gate change.** Concluding "the gate is
   mis-specified" from evidence gathered after it blocked promotion is exactly
   the inversion APEX §23 forbids, however plausible the mechanism. Recorded as
   evidence for an authorized decision, nothing more. What it does do is close a
   third hypothesis and narrow the remaining space to: (a) the signal is
   inherent to bagged-tree dispersion and a different epistemic aggregation is
   needed, or (b) it resolves itself once a better-generalizing generation
   ships.

2. **Hypothesis 2 (in-bag/out-of-bag scoring bias) — RULED OUT, 2026-08-31.**
   The original measurement scored the full 2,571-row corpus, 85% of which
   (2,196 rows) is the RandomForest's own bootstrap training data — in-bag
   dispersion is a known-unreliable epistemic-uncertainty proxy, and this was
   flagged as a live confound. Re-measured against the artifact's genuine
   holdout season alone: the gap is materially unchanged (−0.022 holdout-only
   vs −0.023 full-corpus). In-bag contamination is not the explanation.
   Confirmed on a second, independent member-selection design (3 base
   learners instead of RF bootstrap trees) too, which shows the same
   reversal even more strongly on the full corpus — ruling out "wrong member
   design" as well.

**Stage 11 is now complete (5/5 categories).** The two previously unexercised
categories were closed 2026-08-31: **out-of-support PASSES** (every novel
regime lifts mean epistemic 1.34x–2.54x above in-distribution — not guaranteed,
since tree ensembles extrapolate flat by construction), and **robustness**
now covers all five scoreable leagues, seven temporal windows, and the
missing/partial-data fail-closed path on the real artifact.

### Residualization was proposed, built, and MEASURED — it does not resolve the gate (2026-08-31)

A "decoupled uncertainty" remedy was proposed: recompute the Shannon
decomposition (Vector 1) and measure `error_association` on an
aleatoric-residualized epistemic metric within aleatoric strata (Vector 3).
Both were implemented and measured before any gate was touched.
**Result: it does not work.**

- **Vector 1 is already shipped.** `ensemble_uncertainty.py` has computed the
  same BALD decomposition since PR #121. The only proposed difference was
  `log2` instead of `ln` — a constant rescale, which every rank statistic and
  every bucket boundary is invariant to. It cannot move a gate outcome.
- **Vector 3 was built** (`src/models/epistemic_residualizer.py`, isotonic
  `f(u_alea) -> E[u_epi | u_alea]`) and measured out-of-fold, fitting the
  baseline on pre-holdout seasons and applying it to the holdout
  (`scripts/diagnose_decoupled_uncertainty.py`).

Per-stratum Spearman correlations of the residual against RPS, out-of-fold:

```text
league       S1      S2      S3     verdict
EPL        -0.043  +0.102  +0.008   FAIL (S1)
LA_LIGA    +0.173  +0.154  +0.057   pass
BUNDESLIGA +0.177  +0.020  -0.077   FAIL (S3)
SERIE_A    +0.018  +0.174  -0.137   FAIL (S3)
LIGUE_1    -0.044  +0.072  +0.100   FAIL (S1)
```

**1 of 5 leagues passes — the same 1 of 5 that passes on raw epistemic.**
Residualization genuinely moves individual strata (Serie A S3: −0.230 → −0.137)
and in-sample ≈ out-of-fold, so this is not an overfitting artifact. The signal
simply is not consistently present. Adopting the change would have produced a
gate that still fails four leagues.

⚠️ **A bug in the first implementation nearly produced a false conclusion.**
The direction was hardcoded `IsotonicRegression(increasing=True)`, but the
confound is *negative* — epistemic falls as aleatoric rises. An increasing-only
fit against a decreasing trend collapses to a near-constant, so the "residual"
was rank-identical to the raw signal and the first diagnostic run reported
residualization as a perfect no-op. That was the bug talking, not the data.
Caught by `test_epistemic_residualizer.py`, fixed to `increasing="auto"`, and
pinned by `test_a_flat_baseline_would_remove_nothing`. **Re-derive any
conclusion that rests on a residualizer whose direction was assumed.**

Item 50 therefore stays **open**. `UNCERTAINTY_GATES` is unmodified,
`MODEL_UNCERTAINTY_UNAVAILABLE` remains unconditionally CRITICAL, and the
`certification_policy.py` promotion machinery is untouched.

`UNCERTAINTY_REQUIRES_ALL_GATES = True`, so the method as a whole is not
certified. `full_analysis.py::_uncertainty_from_features` returns `None`
unconditionally — the real computation exists and is tested, but is
deliberately not wired into the live `MODEL_UNCERTAINTY_UNAVAILABLE` gate.

**Do not resolve this by loosening `UNCERTAINTY_GATES.error_association`** —
that is exactly the "manufacture a pass" the certification directive
forbids. Hypothesis 1 (whether the reversal is a fixable property of this
specific model's calibration/sharpness tradeoff, or is simply inherent and
will resolve itself once a genuinely better-generalizing generation ships) is
the only remaining open thread, and was not investigated further this session
— it would require probing calibration/sharpness decomposition or an
alternative epistemic aggregation, which is real methodology work, not a
threshold edit.

**Blast radius:** none today — the gate stays exactly as closed as it was
before this session (unconditionally, via `decompose_measured()`'s permanent
`torch is None` failure) so no live behavior changed.
**Cost:** unknown until hypothesis 1 is resolved — could be zero (wait for a
better-trained generation) or real methodology work.
**Impact:** this is the second of the two critical gates ADR 0009 names as
required before any stake can be authorized (`MODEL_GENERATION_UNCERTIFIED`,
tracked separately, is the first). Both must clear before shadow production.
**Priority:** medium — no deadline, but it is the sole remaining blocker
specific to the uncertainty gate now that 5/6 of its own validation is done
on a methodologically clean (holdout-only) measurement.

---

## 49. `serving_feature_availability` is STILL structurally unsatisfiable — item 38's defect survives in a sibling counter

**Tier:** `RESOLVED 2026-09-03` — **Class C, authorized by the operator that
day and applied.** Filed 2026-08-31, found while regenerating the stale
availability matrix (item 48 follow-up).

Item 38 (authorized 2026-08-22) removed `always_data_gap_slots` from
`promotion_evidence._expected_gate()`'s `blockers` tuple, with this reasoning
in the code comment it left behind:

> `PHASE7_FEATURES_ALWAYS_DATA_GAP` is a permanent, declared 4-slot gap
> present in every 68-wide schema by design — counting it here made the gate
> structurally unsatisfiable for any candidate, however good.

That reasoning is correct and the fix was right. **But the same four features
are still counted by `training_defaulted_slots`, which remains a blocker.**
Measured directly against the freshly regenerated matrix, not inferred:

```
always_data_gap features: 4
  elo_league_adjusted              defaulted_training_slot=True
  shot_quality_diff                defaulted_training_slot=True
  key_passes_under_pressure_diff   defaulted_training_slot=True
  set_piece_xg_diff                defaulted_training_slot=True

OVERLAP: 4 of 4 policy-gapped slots also count in training_defaulted_slots
=> training_defaulted_slots has a hard floor of 4; the gate requires == 0
```

The mechanism is definitional, not incidental: `_column_is_default_only()`
marks a slot defaulted when its training column is constant at the registry
default — and a feature in `PHASE7_FEATURES_ALWAYS_DATA_GAP` is *by policy*
always exactly that, in every candidate, forever. So `training_defaulted_slots`
can never reach 0, and `serving_feature_availability` can never PASS, for any
candidate however good — precisely the condition item 38 set out to remove.

⚠️ **This was found by testing a hypothesis, and the first test was wrong** —
it filtered on `serving_status == "ALWAYS_DATA_GAP"`, a key from the *stale*
matrix's schema, and returned 0 overlaps. The regenerated matrix uses
`always_data_gap` + `classification` instead. The stale file was not merely
out of date in its values; it was a **different shape**. Re-run with the
correct key, the overlap is 4 of 4. Verify against a freshly generated
matrix, never a committed one.

### Recommended fix (one line) — NOT applied, needs authorization

Exclude policy-gapped slots from the blocking count, so it measures
*unexpectedly* defaulted slots — a measurement correction that mirrors item
38's own reasoning rather than a threshold relaxation:

```python
# promotion_evidence._summary_from_features()
"training_defaulted_slots": sum(
    bool(row.get("defaulted_training_slot")) and not bool(row.get("always_data_gap"))
    for row in features
),
```

Under today's candidate that reads **20 → 16**; the gate still FAILs (16 ≠ 0,
and `serving_schema_misaligned_slots` is 11 from item 37's deadlock), so this
promotes nothing and cannot be mistaken for making a failing candidate pass.

### Applied 2026-09-03 (authorized) — with one correction to the proposed one-liner

Measured after the change, not predicted: `training_defaulted_slots` **20 → 16**,
`always_data_gap_slots` still 4 (the declared gaps continue to surface),
`promotion_gate` still **FAIL** both before and after. Nothing was promoted.

⚠️ **The one-liner proposed above was subtly wrong and was not used as written.**
It keys on `row.get("always_data_gap")` — but `_summary_from_features()` also
runs in the **validator** path (`validate_promotion_feature_evidence`, line
~281) against *stored* report rows. A report written before that key existed
returns `None` there, silently restoring the old count on the validator side
only, so builder and validator would disagree and every stored report would
fail validation for the wrong reason. The shipped version keys on the feature
**name** (`str(row.get("feature")) not in PHASE7_FEATURES_ALWAYS_DATA_GAP`) —
the same idiom `always_data_gap_slots` already uses, validated present on every
row, so both call sites agree by construction. This is the same "the stale file
was a different *shape*" trap recorded in this item's own ⚠️ above, one layer
down. Pinned by `test_counter_is_keyed_on_feature_name_not_a_stored_row_flag`.

**Committed report updated:** `backend/models/candidate/feature_availability_matrix.json`'s
`summary.training_defaulted_slots` 20 → 16. Only the derived counter's
*definition* changed; every raw feature row is untouched, and the field was
re-derived by running the real `_summary_from_features()` over those unchanged
rows rather than hand-edited. `promotion_gate` remains `FAIL`.

**Guards:** three new tests in `test_promotion_gate_satisfiability.py` (the
file that already pins item 38, its sibling defect) — policy-gapped slots read
0, *unexpectedly* defaulted slots still block (no blanket exemption), and the
builder/validator shape agreement above. All three were **watched failing
against the reverted pre-fix counter** before being trusted. Suite: 22 passed,
ruff clean.

**Not applied deliberately.** Changing a certification gate after observing
that it blocks promotion is exactly the shape APEX §23 forbids, and item 38's
own precedent was to record the one-line change for an authorized decision
rather than take it unilaterally. Confidence that a fix is correct is not the
same as authority to make it.

---

## 48. Every trained artifact, including the served generation, has never seen real Elo — `elo_difference` is a constant 0.0 across the entire training corpus

**Tier:** `NEXT` — a real, measured, positive out-of-sample signal (M2
evaluation, not yet wired into the training pipeline any model actually
ships from). Filed 2026-08-30, M2 Family A session.

Measured directly, not inferred: loaded the full real corpus (12,765
matches) through `train_on_real_matches.build_dataset()` and read the
`elo_difference`, `elo_home_trend_5`, `elo_away_trend_5`,
`elo_league_adjusted`, `elo_momentum_cross` columns off the emitted
`X_incumbent` vectors. **All five have exactly one unique value — 0.0 —
across all 12,256 rows.** `TeamHistory`, `build_dataset()`'s only walk-forward
accumulator, computes form/goals features only (`stats()`'s full return dict
has no Elo field); nothing in the offline training script replays Elo over
the corpus. Every artifact trained via this pipeline — including the
currently-served `v5_phase7` generation — has therefore never seen Elo vary
during training, and cannot have learned an Elo-outcome relationship,
regardless of production serving `elo_difference` from a real, live,
186-team/25,756-row durable Postgres store (`elo_state_service.py`) at
inference time. **This directly contradicts `backend/reports/features/
train-serve-parity.json`'s claim that `elo_difference` is `RESOLVED`** — it
is resolved at serving, permanently silently-defaulted at training, which is
exactly what M1's own exit gate (`training_defaulted_slots == 0`) exists to
catch and did not.

### What was measured (M2 Family A, `backend/scripts/m2_family_a_elo_ablation.py`)

A fresh, honest, chronological Elo replay was built and cross-verified
against the real `EloEngine`'s own output (300-match subset, byte-identical)
before being trusted at full scale — `EloEngine` itself could not complete
the 12,260-match bulk replay in 5 minutes (its per-call `DataFrame` filter-
and-copy is built for occasional single-match production lookups, not a
bulk pass; a fresh `_FastEloReplay` dict-based accumulator replicates the
exact same rating math — home-advantage expected score, per-league
K-factor, 5-game trend, season-carryover regression to the league mean — at
tractable speed). Chronological 80/20 split (train 2019-09-20→2025-03-15,
n=9,808; val 2025-03-15→2026-05-24, n=2,452), scored with the M0 canonical
RPS/log-loss/Brier/ECE implementations:

| forecaster | RPS (primary, lower better) | Brier | accuracy |
|---|---|---|---|
| uniform | 0.2359 | 0.6667 | 0.435 |
| home_bias (overall empirical rate) | 0.2305 | 0.6492 | 0.435 |
| league_prior (per-league empirical rate) | 0.2305 | 0.6496 | 0.435 |
| BASE (form/recency only, 8 real features) | 0.2231 | 0.6407 | 0.458 |
| **elo_only** (real elo_difference, 1 feature) | **0.2107** | 0.6149 | 0.483 |
| **BASE + real ELO** (12 features) | **0.2102** | 0.6132 | 0.483 |

**Elo alone beats the full 8-feature form/recency BASE.** Adding it to BASE
improves RPS by −0.0130 (0.2231 → 0.2102) — most of that gain is already
captured by Elo on its own; form/recency adds a small further refinement on
top. Elo was resolved for both sides on **100% of validation rows** (once a
team has ≥5 prior matches — the same inclusion floor `TeamHistory` already
enforces — it has necessarily also played ≥1 prior match, so it always has
*some* Elo rating; coverage is not a limiting factor here). ⚠️ **Read the ECE
column with the calibration/resolution tradeoff in mind, not at face value**:
`home_bias`/`league_prior` show near-zero ECE (0.004–0.005) only because a
constant predictor is trivially "calibrated" against its own marginal rate —
it is uninformative, not well-calibrated in any useful sense. The
Elo-augmented models' higher ECE (~0.065) comes with far lower RPS and
higher accuracy; a full reliability/resolution/uncertainty decomposition
(`brier_score_decomposition()`, already built by M0) was not run for this
pass and would be the right next check before reading the ECE numbers as
"Elo is less trustworthy."

**Full corpus context, not directly comparable (different slice/split) but
worth knowing:** item 43 measured the de-vigged bookmaker market at Brier
0.5787 (sum-over-classes convention, same as this table) on the full
12,761-row corpus. This ablation's best result (BASE+ELO, Brier 0.6132 on
the 2,452-row validation slice only) is still short of the market — expected;
beating the market is M7's job, not M2's, and this is a bare logistic
regression on 12 features, not a tuned ensemble.

### What is NOT done here, deliberately

Nothing is wired into `train_on_real_matches.py` or any served artifact.
The replay is in-memory only, never persisted, never touches
`backend/data/cache/` or `data/processed/`. Promoting `elo_difference` from a
constant default to a real, replayed feature in the actual training
pipeline — the change that would let a *retrained* `v5_phase7` successor
actually learn from Elo — is a separate, larger change: it touches a script
every retrain depends on, changes `feature_contract.json`'s per-feature
`training_source` attribution (Phase 3's own machinery would need to record
the new source), and is exactly the kind of change that needs the M2 Family
B–F sweep finished first so the retrain decision is made once, not
feature-by-feature. **Trigger:** either an explicit decision to retrain now
on this one finding, or completing the remaining M2 families (B–F) first for
one combined retrain decision.

**Tier:** `ACCEPTED` — not a defect, a scope boundary. Filed 2026-08-30.

### Follow-up, same day: wired into `train_on_real_matches.py`, retrained, compared — real, not yet promoted

**Decision taken:** retrain now on this one finding, rather than waiting for
the remaining M2 families (B–F) — those are independently blocked on missing
data (Family B/C need a real StatsBomb/xG corpus at scale, which does not
exist; item 10/13), so gating this on their completion would have meant
waiting on an unrelated, possibly indefinite blocker for a signal already
proven real.

`backend/src/features/elo_replay.py` extracts the ablation's `_FastEloReplay`
and its `EloEngine` cross-verification into a shared module — `FastEloReplay`,
`default_fast_elo_replay()`, `cross_verify_against_elo_engine()`,
`compute_elo_training_columns()` — so the replay is written once, not
duplicated across the ablation script and the training script (the same
"one implementation per feature group" discipline Phase 3 already applied to
last-5-form/goals-gd/temporal/league/combination). `m2_family_a_elo_ablation.py`
now imports from it instead of keeping its own copy; re-run after the
extraction and confirmed **byte-identical** to the original result (RPS
0.2231 → 0.2102, delta −0.0130) — the refactor changed nothing observable.

`train_on_real_matches.py`'s `build_dataset()` now calls
`compute_elo_training_columns()` and merges the real `elo_difference` /
`elo_home_trend_5` / `elo_away_trend_5` / `elo_momentum_cross` values into
every emitted row (both the candidate `X` and the legacy-schema `X_incumbent`
comparison copy), before the market-odds gate — `elo_league_adjusted` is left
untouched at its permanent registry default, per the ATE-review policy that
already excludes it from every canonical training path
(`PHASE7_FEATURES_ALWAYS_DATA_GAP`). `main()` runs
`cross_verify_against_elo_engine()` on a 300-match subset before trusting the
replay at scale, same discipline as the ablation script. `feature_registry.py`'s
`_training_source()` now attributes these 4 fields to the new module instead
of `UNDECLARED`; `feature_contract.json` was regenerated
(`scripts/generate_feature_contract.py`) since the attribution-string change
moves `contract_sha256()`. `serving_source` for these 4 fields is deliberately
left `UNDECLARED` — production serving resolves `elo_difference` via
`elo_state_service.get_elo_context()` inside `UpcomingMatchFeatureProjector`
directly, but `FeatureTransformer` receives an already-computed value from its
own caller rather than calling `elo_state_service` itself, so the "both
serving implementations confirmed to invoke the identical function" bar this
contract requires is not yet verified for the serving side — a real, separate,
smaller follow-up, not done here.

Two new regression tests pin the fix: `tests/unit/test_elo_replay.py` (the
replay module in isolation — cross-verification, first-meeting neutrality,
self-play skip, a match never seeing its own result) and
`tests/unit/test_train_on_real_matches_elo.py` (the actual wiring — both
watched failing when the one-line merge was reverted, confirming they test
the real defect, not a tautology).

**Retrained all 6 leagues** (`train_on_real_matches.py`, default args,
`backend/models/candidate/`) and re-ran
`compare_candidate_vs_incumbent.py` against the certified `v5_phase7`
generation on the identical `2526` holdout. Honest result, read directly off
`comparison_report.json`, not narrated:

| Gate | Before (last recorded, item 25) | After this retrain |
|---|---|---|
| `no_league_regression` (need 6/6) | 3/6 | **4/6** |
| `market_baseline` (need 6/6) | 0/6 | **1/6** (EPL: candidate RPS 0.2051 vs market 0.2054) |
| `primary_metric_improvement` | — | PASS, mean RPS +0.0013 |
| `serving_feature_availability` | FAIL, 24 defaulted slots | FAIL, **20** defaulted slots |
| `promotion_permitted` | false | **false** |

⚠️ **`feature_availability_matrix.json` is a stale input to this gate unless
explicitly regenerated.** `compare_candidate_vs_incumbent.py` *reads* it
(line ~98) but never writes it; the committed copy dated from 2026-08-10 and
still listed all four replayed Elo slots as `defaulted_training_slot: true`,
so the first run of this comparison reported `training_defaulted_slots: 24`
— a figure that predated the very change being measured. The real producer is
`scripts/generate_feature_availability_matrix.py`
(→ `promotion_evidence.build_promotion_feature_evidence()`), which
`feature_registry.py`'s own line-800 comment already flagged as the
authority. Regenerated here: **24 → 20**, with `elo_league_adjusted` the only
remaining Elo entry (correctly — it is permanently
`PHASE7_FEATURES_ALWAYS_DATA_GAP`). **Always regenerate the matrix before
reading this gate**, or it reports the previous candidate's feature coverage
against the current candidate's model metrics.

The 20 remaining defaulted slots, which are the concrete certification
backlog for this gate (`h2h_*` ×5, `home_venue_*` ×3, `total_goals_expected`,
`home_advantage_strength`, the 4 cross-signal agreement/combo fields,
`elo_league_adjusted`, `home_pressing_intensity`, `progressive_carry_diff`,
and the 3 permanently-gapped Phase-7 slots): note that h2h and home-venue
**already resolve at serving** (item 13, resolved 2026-08-11) but are still
defaulted *in training* — `build_dataset()` has no h2h/venue accumulator, the
exact asymmetry this Elo work just fixed for a different family. That is the
single largest, cheapest remaining reduction available: ~9 slots, computable
from the same committed corpus with the same walk-forward pattern, no new
data source required.

Candidate beats incumbent on RPS in Eredivisie (−0.0064), La Liga (−0.0048),
Ligue 1 (−0.0029), and Serie A (−0.0055); loses in Bundesliga (+0.0100) and
EPL (+0.0015). This is real, measured, incremental progress in the direction
the ablation predicted — not a certifiable candidate. **Not promoted** — the
gate requires 6/6 league wins, and `serving_feature_availability` fails
independently of anything this change touched. Recorded honestly rather than
either overstating it as a win or discarding it as a non-event.

**What would move this further:** Optuna tuning (`--tune`, unused here — the
baseline hyperparameters were kept so this comparison isolates the Elo effect
alone) is the next lever with no new data dependency. Family E (weather) has
real, keyless, historically-backfillable data (`docs/DEBT.md` item 44) and is
the next family with an actual path to real evidence, once its own
prerequisite chain (team→location mapping with a review step, a persisted
corpus backfill, an archive/forecast parity check) is built — that is a
materially larger effort than this Elo follow-up and was not attempted in
this session.

`GET /api/v1/matches/{match_id}/advanced-insights` is live and now correct (see
CHANGELOG 2026-08-30 for the five defects it shipped with), but **nothing in
`apps/web` calls it.** It is a read-only API with no UI surface. That is
deliberate: directive v4 §3.4/§8.4 explicitly rejects building a speculative
`AdvancedInsightsPanel` before a design pass against real data, and the two
tactical metrics it exposes (`ppda_*`, `psxg_*`) are only populated when
`match_contexts` rows exist, which no job writes yet.

Two things to know before wiring a consumer:

- `market_intelligence` carries **no model probability, edge, or EV** by design —
  no prediction is linked on this read path, and the alternative was the invented
  prior this route shipped with. A consumer must not present the market block as
  a model-vs-market comparison until a real prediction is wired in.
- The response includes `model_identity.{version, feature_schema_version,
  certification_state}`. These are raw internal identifiers. `/api/v1/models/status`
  already publishes the same fields, so this is not a new leak — but APEX §11
  forbids them on consumer surfaces, so any frontend consumer must route them
  through `apps/web/src/lib/model-identity.ts`, never render them directly. The
  repo-wide guard `model-identity-contract.test.ts` covers the frontend only; it
  cannot see an API field.

**A second reason it is inert, found by live probing after the 2026-08-30 deploy:**
`market_intelligence` is `None` for every current fixture because none has a row
in the legacy `odds` table. Probed six live fixtures across five leagues
(`fd-559709`, `fd-565782`, `fd-560553`, `fd-558626`, `fd-564651`, `fd-558249`) —
all returned HTTP 200 with `market_intelligence: null`, and
`/api/v1/fixtures/upcoming` reports `odds_status: DATA_UNAVAILABLE` for all 12
rows it returns. The table is **not** orphaned — `odds_service.py:221`,
`fixtures.py:593`, `endpoints/odds.py:293`, `data_ingestion.py` and the football-data
loader all write it — it is simply unpopulated for upcoming fixtures, because live
market capture goes to `market_snapshots` (the CLV path) instead.

Consequence for verification: **the odds branch this route shipped broken is
currently verified by unit test only.** `tests/unit/test_advanced_insights.py`
exercises it against the real `Odds` schema, but no production request reaches it.
Do not report it as live-verified until a fixture with an `odds` row exists.

**Trigger to revisit:** a job that writes `match_contexts` rows (PPDA/PSxG from
`statsbomb_aggregator.py`, weather from `open_meteo.py`), or a referee scraper
per item 44's pattern. Until then the endpoint returns honest nulls.

---

## 46. `prisma skills sync` runs on every production install — RESOLVED 2026-08-31 (never merged; decided against)

**Tier:** `RESOLVED` — filed 2026-08-30 as `FIX-NOW (cheap)`, re-verified
2026-08-31 during a production-readiness sweep: **the described change was
never actually committed.**

Root `package.json` has no `postinstall` script and no `prisma` dependency of
any kind (`grep -rn '"postinstall"' package.json apps/*/package.json
backend/package.json` and `grep -n '"prisma"' package.json pnpm-lock.yaml` both
return zero matches). `pnpm-workspace.yaml` has no `minimumReleaseAgeExclude`
entries either. Whatever this item originally described — a
`"postinstall": "prisma skills sync || exit 0"` line and a
`prisma@8.0.0-rc.12` devDependency — was either a local, uncommitted experiment
or was reverted before it reached `master`; either way, the production install
path this item warned about does not exist in the shipped codebase.

**This has nothing to do with the database.** `prisma.config.ts` is
`definePrismaConfig({ skills: { agents: [...] } })` — an agent-skills sync tool
(a locally-installed Claude Code skill, `prisma-composer`) that can generate
`.claude/agents/`, `.claude/hooks/`, `.claude/skills/teamwork/`, etc. on a
developer's machine. There is no `schema.prisma`, no `prisma/` directory, and
no `PrismaClient` anywhere in the repo; schema authority remains the Alembic
migration chain. `prisma.config.ts` and its generated output sit untracked in
some local checkouts (harmless — never read by any committed script) and are
not part of this item's resolution.

**Decision:** do not add the postinstall hook. There is no product reason for
an agent-tooling sync to run inside a production/CI install, so the correct
resolution is declining to introduce it rather than adding it and then gating
it. If a future change proposes adding it back, apply one of the originally
recorded mitigations before merging: move it to a local-only script developers
run explicitly; gate it on `CI`/`VERCEL` being unset; or pin a stable
(non-RC) version instead of `8.0.0-rc.12`. Kept as the incident record so the
next session that finds `prisma.config.ts` untracked in a checkout does not
re-open this as a live production risk.

---

## 45. Migration `0009` is PostgreSQL-only, so the SQLite chain check no longer runs

**Tier:** `ACCEPTED` — filed 2026-08-30. Records a lost verification path.

`alembic upgrade head` against a fresh SQLite database now fails partway through
with `sqlite3.OperationalError: unrecognized token: ":"` while running
`0009_quarantine_post_kickoff_closings` — its `UPDATE ... FROM` statement uses
`IS TRUE`, which SQLite does not parse. Nine revisions apply, then it stops.

This is **not** a defect: production is PostgreSQL 16+ and `0009` is correct
there. But it removes a check earlier sessions relied on — vΩ.37 verified the
CLV migration by running the whole chain on the SQLite fallback, and that is no
longer possible.

**Workaround used to verify `0010`** (repeat this for any future migration until
a local PostgreSQL is available):

```bash
export ALLOW_SQLITE_FALLBACK=true APP_ENV=development        DATABASE_URL="sqlite:///./.mig_verify.db"
python -m alembic stamp 0009_quarantine_market_closings   # skip the PG-only one
python -m alembic upgrade head                            # runs 0010 alone
python -m alembic downgrade -1 && python -m alembic upgrade head
```

Note `APP_ENV`, not `ENVIRONMENT` — the settings field is
`app_env: str = Field(alias="APP_ENV")` and the production guard rejects
`ALLOW_SQLITE_FALLBACK` otherwise. Also note the exit code must be read directly:
piping alembic through `tail` reports the pipe's status, and did mask this exact
failure once during the session that filed this item.

**Real fix:** a local PostgreSQL (or a CI job) that runs the full fresh-database
chain plus `alembic check`. Until then, isolate-and-stamp is the honest substitute
and must be stated as such — it verifies the new revision's DDL, not the chain.

---

## 44. Weather acquisition is shipped; weather as a model feature is not

**Tier:** `NEXT` — acquisition is complete and live-verified. Feature
integration is deliberately gated. Filed 2026-08-30.

`backend/src/providers/open_meteo.py` resolves match weather from Open-Meteo.
Live-verified end to end: `probe` returns `VERIFIED` (the first keyless
provider here to do so), geocoding resolves Liverpool GB to 53.41/-2.98, the
archive path returned a real reading for a past kickoff and the forecast path
for a future one, and a kickoff beyond the 16-day horizon returns `None`.

### Why Open-Meteo and not the alternatives

A weather feature is only usable if it resolves for **every historical match in
the corpus** *and* for a **fixture that has not kicked off**. A source with only
one half teaches the model to lean on a signal serving cannot supply — the
train/serve skew that forced the vΩ.46 retrain.

| Provider | Historical | Forecast | Key | Verdict |
| --- | --- | --- | --- | --- |
| **Open-Meteo** | archive to 1940 | 16 days | none | **chosen** — identical `hourly` schema on both, so one parser serves both paths and they cannot drift |
| Visual Crossing | yes | yes | required | 1,000 records/day free — will not cover a 12,765-match backfill |
| NOAA / NWS | yes | yes | none | US-only; every supported competition is European |

### The venue problem, and why this is not a Firecrawl job

`Match.venue` is NULL in production (`fixture_sync_service` never sets it) and
`Team.stadium` is nullable free text. There are **zero coordinates anywhere in
the repository**, so there was nothing to query a weather API with.

The obvious answer — scrape ~130 stadium positions — was rejected. Hand-entered
or model-recalled coordinates are invented reference data, and wrong ones
produce *confidently wrong* weather, which is worse than no weather. Open-Meteo's
own keyless geocoding endpoint resolves a location name instead. City-level
resolution is adequate because the weather model's grid cell is coarser than the
distance from a city centre to its stadium; the API snaps any request to that
cell regardless, which is visible in the response echoing back a shifted
lat/lon.

### What is NOT done, deliberately

Nothing here feeds a feature vector. Adding weather to the model means a new
`feature_schema_version`, a full retrain against the 12,765-match corpus, and a
promotion decision — the same staging ADR-0004 used for CLV capture, which
shipped capture before computation.

Before that work starts, three things must hold:

1. **A team → location mapping with a review step.** Geocoding is derived, not
   invented, but it is still a guess for clubs whose name is not their city
   (Bayer Leverkusen, Hoffenheim, Atalanta). It needs the same
   `VERIFIED`/`REQUIRES_REVIEW` treatment as team identity, not silent
   acceptance.
2. **A backfill over the corpus** — 12,765 archive lookups, rate-limited, with
   the result persisted so training is reproducible rather than re-fetched.
3. **A parity check** that the archive value used in training and the forecast
   value used at serving are the same variable at the same hour, since they come
   from different endpoints. `MatchWeather.source` records which answered
   precisely so the two can never be silently interchanged.

Until all three hold, a missing reading is an **advisory** gap. Weather can
never be critical evidence: the trust tier is `OPEN_DATA` and the provider is
not a football source.


## 43. The BNN Brier gate is below the bookmaker market's own score — unattainable by construction

**Tier:** `ACCEPTED 2026-09-03` — reading 1 (units mismatch) **investigated and
rejected on evidence**; the docstring was corrected instead and the threshold
was deliberately left standing. Reading 2 (threshold mis-specification) remains
open but is now low-stakes — see the resolution note at the end of this item.
Originally filed 2026-08-29 while pointing `train_bnn.py` at the real corpus.

`scripts/train_bnn.py` sets `BRIER_GATE = 0.220`. `_brier_score()` sums squared
error over the three classes — the same convention as `multiclass_brier()` in
`backend/scripts/train_on_real_matches.py` and the `brier_overall` that
`walk_forward_validate()` reports (CLAUDE.md records the served generation's
real settled value as **0.578** on that scale).

**Measured on the 12,761 real matches in `backend/data/cache/`:**

| forecaster | Brier (sum-over-classes) | accuracy |
|---|---|---|
| de-vigged bookmaker market | **0.5787** | 0.5361 |
| class-prior forecaster | 0.6503 | — |
| uniform 1/3 | 0.6667 | — |
| **BNN gate** | **≤ 0.220** | — |

The market — the strongest available 1X2 forecaster, priced by firms with far
more resources than this project — **fails this gate by 2.6×**. No honest
football model can pass it on this convention. The only artifact that ever did
was the label-leakage build (0.0378, item 42).

The BNN trained on the real corpus scores **0.5831** (200 epochs) — within
0.005 of the market, i.e. a legitimately competitive football model that the
gate reports as a failure.

### Two readings, both requiring an authorized decision

1. **Units mismatch.** `_brier_score()`'s own docstring says *"Mean Brier score
   across all three classes"* while the code sums across them. Under the mean
   convention the market scores 0.1929 and the real-corpus BNN 0.1944 — both
   inside 0.220. The gate may have been specified against the docstring.
2. **Threshold mis-specification.** The constant was simply set to a value with
   no attainable referent.

**Not changed here, deliberately.** Editing either the constant or the metric
after observing a failing result is the same act, and is exactly what APEX §23
forbids — "fixing" `_brier_score()` to make a failing gate pass would be a
threshold change wearing a bug fix's clothes. The other three gates (ECE ≤
0.050, CI coverage ≥ 0.880, draw ratio ≥ 0.600) are all attainable and the
real-corpus run passes ECE and draw ratio on the MC-Dropout path.

**Shipped instead (Class B, observability only):** `MARKET_BASELINE_BRIER` and
`UNIFORM_BASELINE_BRIER` constants, printed beside every Brier result, so a
~0.58 is never again read as a broken model — which is what the previous
session's "Recommendation: add more training data" advice implied. More data
will not move this; the corpus went 2,058 → 12,256 rows and the score moved
0.615 → 0.583, converging on the market rather than on 0.220.

### Addendum — 2026-08-30: independently reproduced, and a new coupling found — the honest script cannot save ANY artifact while this gate stands

Re-ran `python scripts/train_bnn.py --corpus real` fresh this session, after
finding an unverified-provenance `bnn_ensemble.pt`/`bnn_fallback_mc.pt` pair
already on disk (mtime 2026-08-29, untracked — matches item 42's addendum
exactly: "any local run will load it... delete it before running the stack
locally"). Deleted both rather than trust or inspect them, to get a fully
first-hand result instead of reasoning about an artifact of unknown origin.

**EDL reproduced item 43's figure exactly**: val Brier **0.5831** (12,256 real
matches, 2019-09-20→2026-05-24, 37 variance-filtered features — no
`causal_feature_report.json` present locally, so the script's own documented
fallback engaged, not a defect). ECE 0.0302 ✓ and CI coverage 1.0000 ✓ both
pass independently of the Brier question. **New finding: EDL's draw_ratio is
0.2090 against a ≥0.600 gate** — it collapsed to almost never predicting a
draw, a real defect distinct from the Brier-attainability question, and
`_LAMBDA_DRAW`'s calibration penalty did not save it this run. The MC-Dropout
fallback fixes the draw problem (0.8691 ✓) but scores Brier 0.5936 — still
2.7× the gate.

**Net result: neither model was saved.** `_gates_pass()` requires all four
gates simultaneously, so the run correctly exited 1 with "No model saved" —
the exact behavior described in this item's body, now confirmed by direct
execution rather than by reasoning about it alone.

**This closes a question §3.1/Decision 1 (item 42) left implicit: the two
decisions are coupled, not independent.** `train_bnn.py`'s own internal gate
check — not `certification_policy.py`, not `uncertainty_service.py`, not
`requirements.txt` — is what refuses to write `bnn_ensemble.pt` today. Item
42's "Option 1: ship the capability" (add torch, train, commit an artifact)
is therefore **not executable as a mechanical checklist** while `BRIER_GATE =
0.220` stands: the script will not save what it produces, no matter how
honest the corpus or how correct the split. Resolving *this* item (choosing
between the mean-convention reading, a market-relative threshold, or leaving
research-only) is now the actual first step of item 42's Option 1, not a
parallel, independent question.

### RESOLUTION — 2026-09-03: reading 1 rejected, docstring fixed, threshold untouched

Reading 1 ("units mismatch — the gate may have been specified against the
docstring") was authorized for implementation this session and **was
investigated before executing, then rejected on evidence.** The code was right
and the docstring was wrong — the opposite of what this item assumed.

`backend/reports/evaluation/metric-contract.json` v1.0.0 (frozen 2026-08-30,
*after* this item was filed) declares the authoritative convention:

```json
"brier_convention": { "aggregation": "mean_over_samples_sum_over_classes" }
```

That is exactly what `_brier_score()` computes. The contract further records
the four per-class-mean sites (`brier_score_decomposition`,
`base_model._calculate_multiclass_brier`, `ensemble.py`, `enhanced_training.py`)
as a known, deliberately unmigrated divergence, noting *"no certification gate
reads them."* Rescaling `_brier_score()` would have made it the **fifth**
divergent site and the only certification-adjacent gate on the
non-authoritative convention.

**And it would have been a threshold change, not a bug fix.** Gate and metric
are only meaningful as a pair: dividing the metric by 3 while holding `0.220`
fixed is arithmetically identical to holding the metric and moving the gate to
`0.660`. On the /3 scale:

| forecaster | /3-convention Brier | vs an unchanged 0.220 |
|---|---|---|
| de-vigged market | 0.1929 | passes |
| honest BNN, real corpus | 0.1944 | passes |
| **uniform 1/3** | **0.2222** | fails by 0.0022 |

The "unchanged" gate would have sat *below the uniform baseline* — admitting
anything better than random. That is the shape this item's own body warned
about ("editing either the constant or the metric after observing a failing
result is the same act").

**Applied instead:** `_brier_score()`'s docstring now states the
mean-over-samples-of-sum-over-classes convention, cites the metric contract as
its authority, names the /3 convention explicitly as a different thing, and
carries a standing warning against "correcting" the arithmetic. `BRIER_GATE =
0.220` and the arithmetic are **byte-identical to before** (verified:
`grep '^BRIER_GATE'` → `0.220`; `np.mean(np.sum(...))` unchanged). `py_compile`
and `ruff` clean.

**No regression test added, deliberately.** `scripts/train_bnn.py` imports
`torch` at module scope, which is absent from every `requirements*.txt`, so a
test importing it would fail in CI — the guard would be less reliable than the
docstring it replaces. The convention is already pinned by the metric contract
itself and by `multiclass_brier()`'s authoritative sibling implementation.

**Reading 2 is still open and is still the real problem** — the gate genuinely
sits 2.6× below the market on the authoritative scale, so no honest 1X2 model
passes it. It is now **low-stakes**, because item 42's closing note establishes
that `train_bnn.py` gates nothing that can reach production: it has no importer
in `backend/src`, and ADR 0009 forbids a BNN from satisfying the epistemic gate
regardless of its score. Fix it if the script is ever revived for research;
there is no longer a production consequence either way.

**Not changed:** `BRIER_GATE`, `certification_policy.py`, `requirements.txt`,
`uncertainty_service.py`. `backend/models/` now holds no `.pt` files locally —
the same state as production (gitignored, never committed, `torch` absent
from every `requirements*.txt`). This is Option 3 (research-only) by current
default, not a new decision made here.


## 42. Staking is blocked by a permanent critical gap that no amount of model certification can clear — CLOSED 2026-09-03, superseded by ADR 0009

**Tier:** `CLOSED 2026-09-03` — **superseded, not fixed.** The mechanism this
item describes is still real and still live (staking is still blocked), but its
proposed remedy became structurally impossible two days after it was filed, and
ownership of the remaining question moved to **item 50**. Filed 2026-08-29
while working the certification path.

> ⚠️ **Read this before acting on anything below.** The three options in the
> body of this item are the state of knowledge on 2026-08-29 and **Option 1 is
> now obsolete**. Do not add `torch`, do not train a BNN, and do not treat the
> addendum's "option 1 remains open" line as current — it was written before
> ADR 0009 existed. Full reasoning in the closing note at the end of this item.

`stake_permitted` requires `not partial`, and any entry in `critical_gaps`
forces `partial`. Every live analysis carries `MODEL_UNCERTAINTY_UNAVAILABLE`
in `critical_gaps`, so **every fixture is permanently no-bet regardless of
model quality**.

The gap is emitted at `api/endpoints/full_analysis.py` when
`UncertaintyService.decompose_measured()` returns `None`. That method's first
branch is:

```python
if self._bnn_model is None or torch is None:
    return None
```

Neither input exists in production:

* `torch` appears in **neither** `requirements.txt` nor
  `requirements.runtime.txt` — confirmed against the Render install log.
* No trained BNN artifact exists anywhere in the repository. The only related
  file is `scripts/train_bnn.py`, the trainer itself.

So `decompose_measured()` returns `None` unconditionally, forever.

### Why this matters for the certification sequence

Certifying the model generation is **necessary but not sufficient** for
staking activation. Even a candidate that clears every gate in
`certification_policy.py` (RPS, `no_league_regression`, `market_baseline`)
would still produce `stake_permitted: false` on every fixture, because this
gap is independent of model quality and cannot be closed by accumulating
match results.

### The decision, not taken here

Three options, all requiring authorization — this is a staking safety gate,
and CLAUDE.md's own rule is that only `critical_gaps` force `PARTIAL`:

1. **Ship the capability.** Add `torch` to the runtime requirements, then
   train and commit a BNN artifact. Materially increases image size and
   deploy time on the current Render plan, and needs its own train/serve
   parity review.
2. **Reclassify the gap.** Move `MODEL_UNCERTAINTY_UNAVAILABLE` from
   `critical_gaps` to `advisory_gaps`, so absent uncertainty reduces
   confidence without blocking. This is a **loosening of a staking gate** and
   must not be done on an agent's own judgement — nor after observing that it
   is what stands between the platform and a green board, which is exactly
   the shape APEX §23 forbids.
3. **Accept it.** Keep research-only serving until option 1 is funded. This is
   the current de facto state, and it is honest — but it should be a recorded
   decision rather than an unnoticed side effect of a missing dependency.

Nothing was changed. Recording the mechanism so the choice is made
deliberately.

### Addendum — 2026-08-29: option 1 was attempted locally and the artifact it
### produced is not usable

An operator installed `torch` and ran `scripts/train_bnn.py`. It reported
`ALL PASS` on every production gate (ECE 0.0215, Brier 0.0378, CI coverage
0.9878, draw ratio 1.2264) and wrote `backend/models/bnn_ensemble.pt`.

**Those gates passed on label leakage, not skill.** `_augment_bnn_signal()`
overwrote five feature columns with values drawn from a distribution whose
mean was selected by `match_result` — the label — and did so on the whole
frame *before* the train/val split, so no gate could detect it:

```python
result = frame["match_result"].values
means = np.where(result == OUTCOME_HOME, h_mu,
                 np.where(result == OUTCOME_AWAY, a_mu, d_mu))
frame[col] = np.clip(means + rng.normal(0, sigma, len(result)), lo, hi)
```

Measured, not inferred: a plain `LogisticRegression` fitted on **only** those
synthesised columns scores **0.9806 accuracy / 0.0368 multiclass Brier** on a
held-out split (majority-class baseline 0.432). The BNN's "passing" 0.0378 is
that number. For scale, the served generation's real settled walk-forward
Brier is **0.578** and its RPS 0.243 — the artifact looked ~15× better than
production because it was reading the answer off its own input.

The function's own docstring claimed it was "conservative enough not to
inflate gate metrics beyond what a real dataset would achieve." It was not.

**Nothing reached production, on three independent counts:** `.gitignore:96`
ignores `backend/models/*.pt` so the artifact cannot be committed; Render's
`buildCommand` installs `requirements.runtime.txt`, which the operator's
(malformed) `torch` line did not touch; and `uncertainty_service` fails closed
when the file is absent. The reverted `requirements.txt` edit was
`torch==2.3.0+cpu --extra-index-url` with no URL and no trailing newline — it
would have broken `pip install` locally while having no production effect.

**Fixed here (Class B):** `_augment_bnn_signal()` is deleted and replaced with
`_warn_on_sparse_features()`, which reports the real 85%-zero sparsity instead
of papering over it. Guarded by
`test_training_scripts_never_derive_features_from_the_label` in
`backend/tests/test_zero_fabrication_contract.py`, watched failing on a
reintroduced leak before being trusted.

**Two things option 1 must still resolve before it is viable:**

1. The corpus itself. `data/processed/` leaves `xg_differential`,
   `elo_difference`, `home_xg_diff_5` and `away_xg_diff_5` zero in **85%** of
   rows — that sparsity is the real gap the leakage was hiding. Its Eredivisie
   slice is generated by `scripts/generate_eredivisie_data.py`, which derives
   every column from the outcome at eight sites. It is openly self-declared
   synthetic and writes only to gitignored `data/processed/`, so it is
   allowlisted in the guard rather than flagged — but a model trained on it
   has not been shown skill either. The real corpus is
   `backend/data/cache/fd_*.csv` (12,765 real matches, per the vΩ.46 retrain).
2. `settings.bnn_model_path` defaults to `backend/models/bnn_ensemble.pt` —
   exactly where the leaked artifact now sits on the operator's disk. It is
   gitignored and cannot ship, but any local run will load it and emit
   fabricated uncertainty that unblocks staking locally. **Delete it before
   running the stack locally.**

Option 1 remains open and still requires authorization. What changed is its
cost: it needs a corpus fix first, not just a dependency and a training run.

### CLOSING NOTE — 2026-09-03: Option 1 is structurally obsolete (ADR 0009)

Option 1 was authorized by the operator this session ("add torch to
dependencies, prepare the artifact for production"). **It was not executed, and
must not be** — auditing its preconditions first showed the option had been
superseded by work that landed *after* this item was written.

`backend/src/models/uncertainty_policy.py` (ADR 0009, frozen 2026-08-31 —
**two days after this item was filed**) declares:

```python
#: The only method authorised to satisfy the epistemic gate.
UNCERTAINTY_METHOD = "ensemble_dispersion"
```

A BNN is a different method. It would fail the `method_is_authorised` gate on
arrival, so **`torch` plus a perfectly trained BNN artifact cannot clear
`MODEL_UNCERTAINTY_UNAVAILABLE`, however good the model is.** Adding `torch` to
`requirements.runtime.txt` would have bought roughly 200 MB of production image
and deploy time for a path the frozen policy forbids from satisfying the gate,
while duplicating an implementation that already exists.

Verified this session, not inferred:

| precondition | state |
|---|---|
| `torch` in any `requirements*.txt` | absent (all files) |
| `backend/models/*.pt` on disk | none — the item-42-addendum leaked artifact is gone |
| `.gitignore` for `*.pt` | still ignored (lines 89-90, 96-97) — artifact could not ship anyway |
| `scripts/train_bnn.py` production importer | **none** — research script, nothing in `backend/src` imports it |
| authorised method | `ensemble_dispersion`, implemented in `src/models/ensemble_uncertainty.py` |
| `_uncertainty_from_features` | returns `None` **unconditionally**, by design |

**Where the question went.** The authorised path is already built and nearly
certified: 6 of 7 `UNCERTAINTY_GATES` pass against the real corpus and the real
shipped artifact. The single failure is `error_association`, which fails
*systematically in the wrong direction* (higher epistemic uncertainty →
**better** RPS, all five scoreable leagues), with in-bag contamination and
member-design already ruled out. **That is item 50, now promoted to the active
staking blocker.**

**What survives of this item.** The mechanism at the top — `stake_permitted`
requires `not partial`, any `critical_gaps` entry forces `partial`, and
`MODEL_UNCERTAINTY_UNAVAILABLE` is unconditionally critical — is still exactly
true and is *why* item 50 blocks staking. Option 2 (reclassify the gap to
advisory) and Option 3 (accept research-only, the current de facto state) also
remain live; Option 3 is now a recorded decision rather than an unnoticed side
effect of a missing dependency, which is what this item asked for. Only Option
1 is dead.

⚠️ **Lesson, and it has now recurred twice in one session.** Both Class C
authorizations granted this session rested on ledger text that had gone stale
(this item's Option 1; item 43's "correct the metric" reading, which
`metric-contract.json` had already answered in the opposite direction). **An
authorization is only as current as the item it was granted against — re-audit
the item's own preconditions against live code before executing it, even when
the instruction is explicit.**

## 41. The homepage published the model's internal provenance as consumer branding — APEX §11 violation, live, untracked

**Tier:** `RESOLVED 2026-08-26`. Consumer surfaces now render product language;
the raw identifiers moved to `/admin/model-health`. Machine-enforced repo-wide.
**Found:** 2026-08-26, from a full-page screenshot of the live production alias
taken while confirming a *different* claim (that the deployed page was stale —
it was not; `web-lac-theta-42.vercel.app` was correctly serving `d62e890`).
The violation was visible in the screenshot and had never been ledgered.

### What was published

The homepage hero's "Model pulse" rail (`components/model-metadata-panel.tsx`)
rendered seven fields straight off `/api/models/status`, verbatim:

```text
ACTIVE MODEL      v5_phase7
GENERATION        v5_phase7-20260808
GENERATION HASH   6bab9609e900c253
FEATURE SCHEMA    phase7_68
SERVED HEAD       SoftmaxMetaModel
CERTIFICATION     UNVERIFIED
PROMOTION         ACTIVE_FAIL_CLOSED
```

APEX §11 names `v5_phase7` and `v6_phase8` **explicitly** as forbidden on
consumer surfaces, permits them only in "developer/admin diagnostics", and
§25's final UI checklist requires "no raw technical generation identifiers".
This was the most prominent public surface in the product.

### Why it survived every prior truthfulness pass

Nothing here was *fabricated* — every value was accurate. The prior passes
(vΩ.24 neutral-defaults, vΩ.28 RL reward decomposition, the 2026-08-13
`LIVE`-badge sweep) all hunted for values that were **wrong**. §11 is a
different failure class: values that are **right but not for this audience**.
A zero-fabrication scan cannot see it, and the copy-contract test only bans
certainty language.

### Blast radius — five components, not one

The recurring shape in this repo (league vocabulary ×5, `LIVE` badge ×3,
`edge_quality_score` ×3). Point-fixing the rail would have left four:

| Surface | Leak | Status |
|---|---|---|
| `model-metadata-panel.tsx` | 6 raw fields (homepage hero) | fixed |
| `mobile-platform-summary.tsx` | `active_version`, `certification_state` — incl. the `aria-label` | fixed at the shared helper |
| `full-analysis-dashboard.tsx` ×2 | `model_version` on `/match/[id]` | fixed |
| `match-intelligence-card.tsx` | `Model {model_version}` | **deleted** — zero production importers |
| `predictions/ultra-prediction-flow.tsx` | `{prediction.model_version}` | **deleted** — zero references repo-wide |

`lib/model-status.ts`'s `displayModelVersion()` / `displayCertification()` were
pure passthroughs returning the raw string — fixing them there fixed
`mobile-platform-summary` with no per-call-site edit, which is why the root
helper was the right place.

### The fix

`lib/model-identity.ts` is the single internal→consumer mapping, transcribing
§11's own table (`model_version` → "Model generation"; `unverified model` →
"Research mode"; `certified model` → "Production-validated"). It **fails
closed**: an unrecognised backend enum yields a neutral label, never the raw
string, so a state added later cannot silently leak.

Raw provenance is not lost — `components/admin/model-health-client.tsx` gained
a "Model Provenance" block carrying all seven fields. That page is
bearer-token guarded (`ADMIN_TOKEN`) and `robots.ts`-disallowed, which is
exactly §11's carve-out.

⚠️ **The denominator was nearly fabricated.** The replacement "Leagues covered"
stat first read `N of 7` from `CANONICAL_LEAGUES` — but the active generation
ships **6** artifacts (no UCL model), so a hardcoded 7 would have understated
coverage as `6 of 7` and would silently lie again the moment the league set
changes. Both numbers now come from the served manifest.

### The durable guard

`lib/model-identity-contract.test.ts` — repo-wide scan, same idiom as
`copy-contract.test.ts` / `league-contract.test.ts` /
`metadata-title-contract.test.ts`. It fails if any non-admin `.tsx` renders a
provenance field without routing it through the mapping.

**Watched failing before being trusted**, per this repo's own rule: reverting
one of the two `full-analysis-dashboard.tsx` fixes turned the guard red and it
named the file (`["components/full-analysis-dashboard.tsx"]`); restoring it
returned green.

**Live-verified** against a local production build pointed at the real Render
backend: zero occurrences of `v5_phase7`, `phase7_68`, `SoftmaxMetaModel`,
`ACTIVE_FAIL_CLOSED` or the generation hash in rendered text, at both 1276px
and 360px. The rail now reads "Generation 5 / Research mode / Serving
forecasts · staking blocked / 6 of 6".

### Note for whoever certifies a new generation

When `certification_state` flips to `CERTIFIED`, the consumer label becomes
"Production-validated" automatically. Do **not** add the version string back
alongside it "for transparency" — that is this entry, recurring.

---

## 40. PSG's entire Elo history sits on the Paris FC team row — two distinct clubs merged by a place-name collision

**Tier:** resolver hardening `RESOLVED 2026-08-25` (both name resolvers now
refuse the merge, machine-enforced across every committed corpus). The
**production data repair is `NEXT` and Class C** — unauthorized, and it needs
a chronological Elo replay, not a spot fix.
**Found:** 2026-08-25, incidentally. A verification query run immediately
after the item-35 rebind showed the repaired fixture's opponent
(`fd-team-ligue_1:paris_saint-germain_fc`, PSG) carrying **3** Elo snapshots
while an unrelated row carried 276. Nothing prompted that check — it came
from reading the numbers in a result rather than only the row being repaired.

### The corruption

| Team id | Name | Elo snapshots | Seasons |
|---|---|---|---|
| `fd-team-ligue_1:paris_fc` | Paris FC | **276** | 2019/2020 → 2026/2027 |
| `fd-team-ligue_1:paris_saint-germain_fc` | Paris Saint-Germain FC | 3 | 2025/2026 → 2026/2027 |

276 is the **highest count in Ligue 1** — above every other club's 244–245.
It is PSG's 243 corpus appearances merged with Paris FC's own 34.

**Confirmed by reading the actual matches, not inferred from counts.** The
2019/2020 fixtures stored under "Paris FC" are unmistakably PSG's, in a season
Paris FC spent in Ligue 2:

```text
2019-08-11  Paris FC 3-0 Nimes          2019-08-18  Rennes 2-1 Paris FC
2019-08-25  Paris FC 4-0 Toulouse FC    2019-08-30  Metz 0-2 Paris FC
2019-09-14  Paris FC 1-0 Strasbourg     2019-09-22  Ol. Lyonnais 0-1 Paris FC
```

All are real PSG results. Match-source breakdown confirms the origin: 275 of
the 277 are `fdco-` ids (historical backfill), and 2025/2026 alone holds
**66** — both clubs' fixtures collapsed onto one row.

### Root cause

`_identity_key` strips the legal token `FC` but not `SG`, so:

```text
"Paris FC" → "paris"      "Paris SG" → "paris sg"
```

`resolve_team_id`'s containment rule — which exists so `Brighton` resolves to
`Brighton & Hove Albion FC` — then finds `" paris "` inside `" paris sg "`
and merges them.

⚠️ **`_unique_match`'s uniqueness guard does not help, and understanding why
matters.** Only one candidate matches, so the merge looks unambiguous. Even
with the real PSG row present it stays unique: `"paris saint germain"` neither
contains nor is contained by `"paris sg"`, so PSG never becomes a competing
candidate. Uniqueness is not a safety property here.

### What was fixed (Class B, this session)

**Both** resolvers now refuse it, and each was watched failing first:

1. `team_identity._AUDITED_ALIASES` gains `("LIGUE_1", "paris sg") →
   "paris saint germain"`.
2. **The alias lookup moved *before* the containment heuristic.** This is
   load-bearing on its own: reverting only the ordering, with the alias left
   in the table, still reproduces the merge — containment answered first, so
   the assertion was never consulted. An explicit human identity assertion
   must outrank a heuristic.
3. An alias naming a target that cannot be found now **fails closed** instead
   of falling through to the heuristics it was meant to pre-empt.

`historical_backfill_service.TeamIndex` — the resolver that actually consumes
the corpus — already refused this pair (PR #25) and was verified unchanged
against the full real 28-row Ligue 1 roster, not a toy fixture.

**Machine-enforced going forward:** `tests/unit/test_team_identity_containment_collisions.py`
scans every committed corpus for pairs whose identity keys contain one another
and requires each to be refused *behaviourally* by `TeamIndex` and asserted by
an alias for `resolve_team_id`. Exactly one such pair exists across all six
leagues today (this one). A future season whose promoted club collides with an
incumbent now fails CI instead of silently merging two clubs' histories.

⚠️ **The scan reads four column conventions** (`HomeTeam`/`AwayTeam` and
`home_team`/`away_team`) because the committed cache mixes them — the older
files are snake_case-normalized, the newest keep raw upstream headers. A first
pass that read only the raw pair undercounted PSG from 243 appearances to 34
and nearly produced the wrong conclusion.

### What is NOT fixed — the data (Class C, `NEXT`)

Current code no longer reproduces this; the corrupted rows are legacy, the
same shape as item 39's mojibake. Repair requires:

- reassigning ~243 `fdco-` matches from `fd-team-ligue_1:paris_fc` to a real
  PSG row, keeping Paris FC's own 34;
- a **chronological Elo replay** for Ligue 1 from 2019-08-11 forward, because
  Elo is path-dependent and every later Ligue 1 opponent's rating was computed
  against a PSG-strength "Paris FC".

That is item 34's `repair_semantic_identity_and_rebuild_elo.py` machinery, and
it is Class C: unauthorized, needing its own dry-run manifest, digest, and
explicit approval. **Do not attempt it as part of an unrelated change.**

**Live impact while unrepaired:** Ligue 1 Elo features are wrong for PSG
(near-baseline, 3 snapshots) and inflated for Paris FC, and every Ligue 1
club's rating carries some contamination from having faced the merged row.
Predictions still serve — Elo is 4 of 68 features and the affected fixtures
report honestly — but Ligue 1 Elo should not be treated as trustworthy until
the replay runs.

---

## 39. Mojibake team names in production cost those fixtures their Elo identity

**Tier:** `RESOLVED 2026-08-25` — ingest guard shipped 2026-08-23; the Class C
data repair executed the same day, operator-authorized, live-verified with
zero mojibake remaining across all production fixtures.
**Found:** 2026-08-23, from a user screenshot of the live UI reading
"Club Atl??tico de Madrid".

Production `sabiscore_db_v3` holds team rows whose names and IDs carry literal
ASCII `?` in place of every accented byte — `M??laga CF`,
`fd-team-la_liga:m??laga_cf`, `FC Bayern M??nchen`, `Borussia M??nchengladbach`,
`Deportivo Alav??s`, `RC Deportivo La Coru??a`, `Real Betis Balompi??`,
`Real Sociedad de F??tbol`. Exactly one `?` per UTF-8 *byte*, which is a
two-stage failure: UTF-8 bytes decoded as a single-byte codepage, then
ASCII-encoded with replacement.

**This is not cosmetic.** `team_identity` tokenizes on `[a-z0-9]+`, so the `?`
splits the word (`bayern m nchen`), and `_AUDITED_ALIASES` is keyed on the
correctly-folded form (`bayern munchen`). No alias can ever match, so
`resolve_team_id()` fails, `fixture_sync` falls back to minting an ID from the
broken name, and the result is an **Elo-less orphan that shadows the real,
history-bearing club** for every fixture it appears in.

**Origin — ruled out, one layer at a time, with live probes:**

| Layer | Result |
|---|---|
| Upstream football-data.org | clean — `b'M\xc3\xa1laga'`, `charset=UTF-8`, zero `?` |
| Our httpx 0.25.2 `response.json()` | clean — reproduced against the real API |
| Repo data files at rest | clean — zero mojibake in any CSV/JSON |
| Redis cache | byte-safe (`decode_responses=False`, explicit UTF-8) |
| `sabiscore_db_v2` | clean (`Club Atlético de Madrid`) |
| `sabiscore_db_v3` (production) | **corrupt** |

So the current code path does **not** reproduce it: these are legacy rows from
v3's seeding (created 2026-08-20). Decisively, the *verified* side of every
affected fixture is already clean and Elo-bearing —
`stored=(fd-team-bundesliga:fc_bayern_m??nchen,…)` vs
`verified=(fdco-team-bundesliga-bayern_munich,…)`.

✅ **Ingest guard RESOLVED 2026-08-23.** `is_unusable_team_name()`
(`fixture_sync_service.py`) fails closed on any provider display name
containing `?`, placed **after** the durable provider-ID anchor resolves (where
the name carries no identity weight, so a lossy one is merely cosmetic) and
**before** the name becomes identity as fuzzy-match input or a minted ID. Bumps
`fixture_sync.unusable_team_name` and raises into the caller's existing
identity-conflict path. Both behaviours pinned, and **both guards were watched
failing against a reverted fix** before being trusted.

⚠️ **CORRECTED 2026-08-24 — "repair path already exists" was wrong.** The
paragraph that stood here proposed rebinding toward item 35's
`GET /api/v1/release/fixture-identity-review` "verified" identity. That
target is `CanonicalFixture.home_team_id`/`away_team_id` —
`canonical_teams.id`, a **different table `Match` never references**, resolved
through `canonical_identity_service._provider_team_anchor()`, a wholly
separate system from the one that actually backs `Match.home_team_id`
(`teams.id`, resolved through `team_identity.resolve_team_id()`). Checked
live before trusting it: all 118 "verified" ids across the 59 item-35 entries
are `team-<hash>` format — zero are the Elo-durable `fdco-team-` format — and
for all 11 `stored_identity_unusable` rows the "verified" *name* is **also**
`??`-corrupted, because `_provider_team_anchor` has no name-quality guard and,
once a `ProviderTeamMapping` exists, reuses its `canonical_team_id` forever
regardless of the current display name — the identical "sticky corruption"
class this item's own ingest guard exists to prevent, just in the other
system. Rebinding toward that target would not have fixed the mojibake at
all; it would have moved to a differently-formatted but equally corrupted
name.

✅ **The genuine repair tool, built and shipped correctly this time:**
`GET /api/v1/release/orphan-team-repair-review`
(`services/orphan_team_reconciliation_service.py`). It replays the exact
resolver `fixture_sync` itself uses for `Match.home_team_id` —
`team_identity.resolve_team_id()` — against the **freshest observed**
provider team name, sourced from `ProviderTeamMapping.provider_team_name`
(refreshed on every sync tick, unlike `CanonicalTeam.name`, which is set once
at creation and never touched again). Because the deterministic-fallback path
that mints an orphan never calls `bind_provider_elo_team_id`, a corrupted-name
orphan carries no sticky mapping in the *legacy* system — so once upstream and
the freshest observed name are clean (both true today), the resolver can find
the real, history-bearing team on its own. Only proposes a target that
already carries real `EloRatingSnapshot` rows in the same league — evidenced
in the manifest by snapshot count and first/last match date — and refuses a
target that would collide with the fixture's other side (self-play guard,
watched failing before being trusted). Still review-only: no rebind/apply
path exists; that remains Class C (APEX §3) and unauthorized.

Item 35's endpoint is not deleted — it still correctly answers its own
question ("does `Match` and `CanonicalFixture` structurally disagree"), which
is a real, separate signal (`CanonicalFixture` currently backs the shipped
CLV-capture pipeline). It is simply the wrong lens for *this* repair.

**2026-08-24 follow-up — the manifest's own diagnostic named a real gap, now
made queryable.** Live `orphan-team-repair-review` reports 5 repair-ready
Bundesliga entries (0 blocked) — 3 unplayed fixtures (`fd-565776`,
`fd-565777`, `fd-565778`, kicking off 2026-08-28/29), so repairing them is a
pre-kickoff `Match.home_team_id`/`away_team_id` repoint, not a historical Elo
replay — plus `unrepaired_orphan_sides: {"ORPHAN_NO_RESOLVER_MATCH": 3}` with
no identity attached. The production DB (`sabiscore_db_v3`,
`dpg-da3p8qv10e5c738vls1g-a`) is unreachable for a direct read-only query from
this environment — its `ipAllowList` is locked to a single operator IP,
unlike the decoy `sabiscore_db_v2`'s open `0.0.0.0/0` (confirmed: the same
query tool succeeds against v2, fails with `SSL/TLS required` against v3
every time). `summary["unrepaired_orphan_side_detail"]` now carries
`match_id`/`league_id`/`side`/`orphan_team_id`/`orphan_team_name`/
`freshest_observed_name` per unrepaired side (`manifest_sha256` unaffected —
detail lives in `summary`, which was already excluded from the hash). Pinned
by an extension of `test_unrepaired_orphan_sides_diagnostics_distinguish_failure_reasons`
in `test_orphan_team_reconciliation_service.py`.

⚠️ **2026-08-25 — the 3 sides are diagnosed, and the hypothesis above was
WRONG.** It predicted a mojibake-corrupted *target* `Team.name`. Live probe of
the deployed detail (backend `sha:a42f03b`) returned three **perfectly clean**
names, no `?` anywhere:

| Fixture | Side | Orphan team | Freshest observed |
|---|---|---|---|
| `fd-565779` | away | Eintracht Frankfurt | `Eintracht Frankfurt` |
| `fd-565780` | home | SV 07 Elversberg | `SV 07 Elversberg` |
| `fd-565781` | away | Hamburger SV | `Hamburger SV` |

Mojibake was never involved. The real cause is a **two-vocabulary mismatch**,
the same class as the league-id trap: the historical Elo corpus
(`backend/data/cache/fd_D1_*.csv`, football-data.co.uk) abbreviates club
names, while the live provider sends the full legal name. Read out of the
committed CSVs across all seven seasons (27 distinct clubs):

- `Eintracht Frankfurt` → corpus **`Ein Frankfurt`** — `_identity_key` gives
  `eintracht frankfurt` vs `ein frankfurt`; exact ✗, affix ✗, containment ✗
  (`"eintracht"` is not `"ein"` + boundary), `reconcile_team` **0.8125 →
  `REQUIRES_REVIEW`**, correctly below the 0.94 auto-accept threshold.
- `Hamburger SV` → corpus **`Hamburg`** — `hamburger sv` vs `hamburg`
  (`sv` is deliberately *not* in `_LEGAL_TEAM_TOKENS`); `reconcile_team`
  **0.7368 → `REQUIRES_REVIEW`**.
- `SV 07 Elversberg` → **absent from all seven seasons.** Newly promoted, so
  no Bundesliga Elo can exist. `reconcile_team` **0.4615 → `UNKNOWN`**. This
  one is **correct fail-closed behaviour, not a defect** — do not "fix" it.

`REQUIRES_REVIEW` is precisely what `_AUDITED_ALIASES` exists to answer
("identity assertions, not fuzzy-threshold exceptions", per the module's own
docstring), and the dict already carried the identical
`("BUNDESLIGA", "borussia monchengladbach"): "m gladbach"` case. Two entries
added — `eintracht frankfurt → ein frankfurt`, `hamburger sv → hamburg` —
with 4 tests: 2 proving resolution, 1 proving an absent club still fails
closed (aliases must not make Elversberg snap to a neighbour), 1 proving the
alias cannot leak across leagues. **Both resolution tests were watched
failing** against the un-aliased resolver (`assert None == 'fdco-bundesliga-0'`)
before the fix was trusted.

⚠️ **Re-derive corpus spellings from the committed CSVs, never guess them** —
`Ein Frankfurt`, `M'gladbach`, `FC Koln`, `St Pauli` and `Hamburg` are all
football-data.co.uk conventions that no amount of reasoning about the club's
real name will produce.

⚠️ **2026-08-25 — a SECOND, larger and entirely user-visible half of item 39,
found from the operator's own screenshots.** `GET /api/v1/upcoming/matches`
returns **9 of 50 live fixtures rendering mojibake team names to users**:
7 LA_LIGA (`Real Betis Balompi??`, `Real Sociedad de F??tbol`,
`Deportivo Alav??s`, `Club Atl??tico de Madrid`, `M??laga CF`) and 2
BUNDESLIGA (`FC Bayern M??nchen`, `Borussia M??nchengladbach`).

**The La Liga ones are a different defect from the orphan one, and the orphan
manifest is right to exclude them.** Established by elimination against live
evidence, not inferred:

- They appear in item 35's `fixture-identity-review` (13 LA_LIGA entries,
  `stored_identity_unusable: true`), so `ProviderEventMapping` rows exist and
  the orphan manifest's join does reach them.
- They produce **zero** orphan entries and **zero** `unrepaired_orphan_sides`
  counts, so `_has_elo_history()` returned `True` — these rows **carry real
  Elo history** and are correctly not orphans.
- Live `/metrics` shows `fixture_sync.unusable_team_name` and
  `fixture_sync.identity_conflicts` both **absent (zero)**, with exactly
  `identity_rebind_pending: 5` — matching the 5 logged drift warnings, none of
  which are LA_LIGA. So La Liga never reaches the drift check at all.

The explanation that satisfies all three: resolution **short-circuits at step 1
of `_resolve_upcoming_team_id`** — a VERIFIED `ProviderEloTeamMapping` binds
the provider ID straight to the corrupted-name row (which passes that
function's own `has_history` requirement), so the computed id *equals* the
stored id, no drift is reported, and the name is never revisited. Reproduced
locally end-to-end: `resolve_provider_elo_team_id` returns
`fd-team-la_liga:real_betis_balompi??` for a clean incoming
`"Real Betis Balompié"`.

**Root cause:** `fixture_sync_service.py`'s Team upsert was
`if tname and not await session.get(Team, tid)` — **write-once**. `Team.name`
was set at creation and never refreshed, so a row minted during the
2026-08-20 corrupted window kept that text forever. This is the *identical*
sticky-corruption shape this item already documents for `CanonicalTeam.name`,
one table over — and the orphan service's own docstring had already named the
contrast ("`ProviderTeamMapping.provider_team_name` … is refreshed on every
sync tick, unlike `CanonicalTeam.name`"). `Team.name` was the third instance
and nobody had looked.

✅ **Fixed 2026-08-25, Class B.** The upsert now repairs a stored name **only
in the strictly-improving direction**: stored unusable *and* incoming usable.
A clean stored name is never overwritten — which is what protects the
Elo-bearing corpus spellings (`Bayern Munich`, `Ein Frankfurt`) that
`resolve_team_id` matches against from being renamed out from under the
resolver by a provider's legal-name form. `Team.id`, Elo snapshots and the
durable `ProviderEloTeamMapping` are all untouched: this corrects a **display
label**, never an identity, so it is not a Class C historical rewrite. Emits
`fixture_sync.team_name_repaired` and an INFO log. Idempotent — once repaired,
the stored name is clean and the branch can never fire again.

Two tests, both seeding production's exact shape (corrupted row **plus** real
Elo **plus** a VERIFIED provider mapping, since PR #82's guard now correctly
refuses to let sync mint such a row): one proving the repair and that
id/mapping survive it, one proving a clean stored name survives both a
corrupted and a differently-clean incoming name. **The repair test was watched
failing** against the un-patched upsert (`assert 'Real Betis Balompi??' ==
'Real Betis Balompié'`).

⚠️ **The two-league-vocabulary trap fired again while writing these tests** —
`_LEAGUE_META` is keyed on the **display** form (`"La Liga"`), so a fixture
built with the canonical `"LA_LIGA"` is silently dropped as an unsupported
competition and the test passes for the wrong reason. Provider-shaped test
fixtures must use the display form.

✅ **2026-08-25 — the Class C executor is BUILT (code only; nothing mutated).**
`services/orphan_team_rebind_service.py` + `scripts/repair_orphan_team_identities.py`,
mirroring the `repair_semantic_identity_and_rebuild_elo.py` precedent
rule-for-rule: `--review` is read-only under `SET TRANSACTION READ ONLY` and
always rolls back; `--apply` requires the reviewed `--manifest-sha256`, an
`--authorization-id`, and the literal token `APPLY_ORPHAN_TEAM_REBIND`;
PostgreSQL-only (`acquire_orphan_team_rebind_locks` raises on any other bind,
so there is no silent SQLite path); the manifest digest is **re-derived under
`LOCK TABLE teams, matches, elo_rating_snapshots IN SHARE ROW EXCLUSIVE MODE`**
and every row's exact pre-state re-checked, so a concurrent change aborts
before a single write.

**Deliberately narrower than its sibling**: it writes `Match.home_team_id` /
`away_team_id` and *nothing else* — no `Team` created, renamed or deleted, no
`EloRatingSnapshot` written or rebuilt. That narrowness is what removes the
need for a chronological Elo replay: the manifest already refuses any side
whose kickoff has passed, so every repaired fixture is **still unplayed** and
no post-match Elo derived from the wrong participant exists to unwind. This is
a forward-looking identity correction, not a rewrite of the past — a materially
different risk profile from item 34's EPL replay.

Two postconditions run before the caller commits, and **the second was watched
catching a sabotaged write** (`RuntimeError: orphan team rebind postcondition
failed: ['fd-rebind-1/home'] still proposed after rebind`), not merely asserted
in a test: (1) no touched fixture may record a team playing itself — the exact
shape item 23's 26 rows produced; (2) re-deriving the manifest must no longer
propose any side just written, since each target carries real same-league Elo.
`--apply` also prints a `reversals` list — the exact `(match, side, from, to)`
tuples to undo it by hand. 6 tests cover the happy path, a stale digest, a row
that moved since review, an empty manifest (an explicit refusal, never a silent
success), a blocked entry, and the PostgreSQL-only lock refusal.

⚠️ **Execution is operator-side and has NOT happened.** The agent environment
cannot reach `sabiscore_db_v3` at all (single-IP `ipAllowList`), so `--apply`
must run somewhere holding real DB access — a Render shell or the operator's
own machine. ⚠️ **Re-run `--review` first and use the hash it prints**: the
digest moved when the corpus-alias fix deployed, because Eintracht Frankfurt
and Hamburger SV stopped being `ORPHAN_NO_RESOLVER_MATCH` and became
repair-ready entries. Any digest recorded before that deploy is stale by
construction, and the executor will refuse it.

### Class C authorization package — current as of `sha:e135ce9`

✅ **Both code fixes above are live and verified in production.** Mojibake on
the public fixtures endpoint went **9 of 50 → 2 of 50**; the 7 LA_LIGA rows
now render correctly, and exactly the 2 BUNDESLIGA orphans remain — which is
the predicted split, since those are Elo-**less** and a name repair cannot give
them history. The corpus-alias fix is likewise confirmed live: the manifest
moved from **5 repair-ready / 3 unrepaired** to **7 repair-ready / 1
unrepaired**, the remaining one being SV 07 Elversberg, correctly (no
Bundesliga Elo exists for a newly-promoted club).

**Authoritative manifest digest (re-derived post-deploy, 2026-08-25):**

```
9da675851dc4da4f5ac4e1afbe415d9ca700dee1baec66dd6643723a5b66353e
```

⚠️ The earlier `6925fbade2…` digest is **stale by construction** and the
executor will refuse it — it predates the alias fix, when Frankfurt and Hamburg
were still `ORPHAN_NO_RESOLVER_MATCH` rather than repair-ready entries.

7 sides across 5 unplayed fixtures, **0 blocked**, all BUNDESLIGA:

| Fixture | Side | Orphan | → Target | Elo evidence |
|---|---|---|---|---|
| `fd-565776` | home | FC Bayern M??nchen | `fdco-…-bayern_munich` | 238 (2019-08-16→2026-05-16) |
| `fd-565776` | away | VfB Stuttgart | `fdco-…-stuttgart` | 204 (2020-09-19→2026-05-16) |
| `fd-565777` | away | Borussia M??nchengladbach | `fdco-…-m_gladbach` | 238 (2019-08-17→2026-05-16) |
| `fd-565778` | home | 1. FSV Mainz 05 | `fdco-…-mainz` | 238 (2019-08-17→2026-05-16) |
| `fd-565778` | away | SC Paderborn 07 | `fdco-…-paderborn` | 34 (2019-08-17→2020-06-27) |
| `fd-565779` | away | Eintracht Frankfurt | `fdco-…-ein_frankfurt` | 238 (2019-08-18→2026-05-16) |
| `fd-565781` | away | Hamburger SV | `fdco-…-hamburg` | 34 (2025-08-24→2026-05-16) |

**Replay boundary: none.** Every kickoff is 2026-08-28/29, i.e. in the future,
so this is a pre-kickoff repoint with no post-match Elo to unwind.
**Rollback:** `--apply` prints the exact `(match, side, from, to)` reversals;
only 7 columns on 5 rows change, and nothing else is written.

**Status: NOT EXECUTED.** The agent environment cannot reach `sabiscore_db_v3`
(single-IP `ipAllowList`), so this runs operator-side. Re-run `--review` at
execution time and use the digest it prints — if fixture sync has since altered
any of these rows, the digest will have moved again and the executor will
correctly refuse the one above.

✅ **2026-08-25 — an HTTP apply path shipped alongside the script (PR #92),
live-verified in production, not just merged.** `POST
/api/v1/release/orphan-team-repair-apply` wraps the identical
`apply_orphan_team_rebind()` the script calls — same manifest-digest
re-derivation under the same table locks, same two postconditions, same
`confirm: "APPLY_ORPHAN_TEAM_REBIND"` literal plus an `authorization_id` that
rides through into the response for the audit trail. This is an additional
surface, not a second implementation: the script remains the reference for an
operator with a Render shell; the endpoint is for anyone who only has network
access to the API. `GET orphan-team-repair-review`'s `authorization` block
now reports `apply_supported: true` and points at the endpoint instead of the
prior hardcoded `false`.

**Live-verified post-deploy (backend `sha:88f53e0`, 2026-08-25T03:05 UTC):**
the manifest digest re-derived by production right now is still
`9da675851dc4da4f5ac4e1afbe415d9ca700dee1baec66dd6643723a5b66353e` —
byte-identical to the one recorded above, confirming fixture sync has not
touched any of the 7 rows since that digest was captured. **The authorization
package above is current; the operator does not need to re-run `--review`
before applying it**, provided the apply happens before any further sync tick
touches these fixtures. As always, re-check the digest immediately before
applying if any time has passed — this note describes one confirmed instant,
not a standing guarantee.

✅ **EXECUTED 2026-08-25T03:29:38 UTC, operator-authorized.** The operator
supplied direct production-database credentials in-session specifically to
unblock this apply; execution went through `POST
/api/v1/release/orphan-team-repair-apply` instead — the identical code path,
without ever needing to hold or transmit the raw credential. Re-reviewed
immediately before applying (this ledger's own standing rule): digest
unchanged at `9da67585…`, 7/7 still ready, 0 blocked.

**Result:** `rebound_sides: 7` across 5 fixtures (`fd-565776`, `fd-565777`,
`fd-565778`, `fd-565779`, `fd-565781`), all BUNDESLIGA. Reversal tuples
(`match, side, from, to`), preserved here as the rollback record:

```text
fd-565776 away fd-team-bundesliga:vfb_stuttgart            → fdco-team-bundesliga-stuttgart
fd-565776 home fd-team-bundesliga:fc_bayern_m??nchen        → fdco-team-bundesliga-bayern_munich
fd-565777 away fd-team-bundesliga:borussia_m??nchengladbach → fdco-team-bundesliga-m_gladbach
fd-565778 away fd-team-bundesliga:sc_paderborn_07           → fdco-team-bundesliga-paderborn
fd-565778 home fd-team-bundesliga:1._fsv_mainz_05           → fdco-team-bundesliga-mainz
fd-565779 away fd-team-bundesliga:eintracht_frankfurt       → fdco-team-bundesliga-ein_frankfurt
fd-565781 away fd-team-bundesliga:hamburger_sv              → fdco-team-bundesliga-hamburg
```

**Both postconditions verified live, not just by the endpoint's own internal
check:** `GET orphan-team-repair-review` immediately after reports
`total_candidates: 0`, `repair_ready_count: 0` — the only remaining
`unrepaired_orphan_sides` entry is SV 07 Elversberg (`ORPHAN_NO_RESOLVER_MATCH`,
correctly, no Bundesliga Elo exists for a newly-promoted club). `GET
/api/v1/fixtures/upcoming?limit=200` across all 58 live fixtures: **zero**
names containing `?` — the 5 touched fixtures now read `Bayern Munich vs
Stuttgart`, `RB Leipzig vs M'gladbach`, `Mainz vs Paderborn`, `Union Berlin vs
Ein Frankfurt`, `Dortmund vs Hamburg` (the corpus-side display names, since
the fixture's team ids now point at the Elo-bearing rows). Playwright against
the live homepage confirms the same. Item 39 is closed — both halves (the
ingest guard and this repair) are done, live, and verified.

⚠️ **Process note, not a code finding:** the operator pasted a live
`postgresql://` connection string with a real password directly into the chat
session to unblock this. It was not used (the HTTP path made it unnecessary)
and was not written to any file or command, but a chat transcript is not a
secure secret store — this is the same class of incident this ledger already
records for the Upstash token and provider keys (§ credential-safety rows
above). **Recommend rotating this database password in the Render dashboard**
even though this session never needed or persisted it.

## 38. The promotion gate is unsatisfiable by construction — no candidate can ever be promoted

**Tier:** `RESOLVED 2026-08-22`. (Label corrected 2026-08-24 — it still read
`NEXT` / "the single hard blocker on Phase 4" long after the body below
recorded the authorized fix, so the top of the ledger was advertising a
blocker that no longer exists.) Not a serving defect; nothing in production
reads this gate. But it made the entire candidate-promotion path a no-op, so
Phase 4 could not complete regardless of how good a candidate was.
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

✅ **RESOLVED 2026-08-22, authorized by the user, exactly as scoped above.**
`always_data_gap_slots` dropped from `_expected_gate()`'s blockers tuple; the
matching threshold dict entry removed from
`certification_policy.py`'s `serving_feature_availability` gate, its `rule`
prose trimmed, and `CERTIFICATION_POLICY_VERSION` bumped `1.0.0` → `1.1.0`
(a genuine threshold change, not wording). The declared-gap count of 4 is
unchanged in `_summary_from_features()` and the rendered markdown — it's
still visible to any reviewer, it just no longer disqualifies.
`test_promotion_gate_satisfiability.py`'s three tests now pin the repair
(the previously-`FAIL`-asserting test now asserts `PASS`); the module
docstring records the authorization. **What did NOT change, deliberately:**
this is a deadlock repair, not a promotion. The live
`backend/models/candidate/comparison_report.json` snapshot is untouched (it
would need a real training run to regenerate, out of scope) and, read as-is,
that candidate still independently fails `no_league_regression` (3/6 leagues)
and `market_baseline` (0/6 leagues) — both unrelated to this fix — plus 11
`serving_schema_misaligned_slots` from item 37, which remains open. No
candidate promotes as a result of this change; it only stops a *good*
candidate from being blocked by an unfixable accounting term.

---

## 37. `train_on_real_matches.py`'s default market block does not match the shipped artifacts' own recorded one

**Tier:** `BLOCKED-ON-DATA` (was `NEXT`) — **the mechanical deadlock is
RESOLVED as of 2026-08-22**; see "Serving wire-up SHIPPED" below. The schema
disagreement that made every candidate auto-unpromotable is fixed: serving now
dispatches on the active generation's declared schema, so an Apex-trained
candidate compared against an Apex-serving contract reads
`serving_schema_misaligned_slots: 0`. What remains is not code — the candidate
still fails `no_league_regression` and `market_baseline`, which need real
elapsed match volume.
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

**(a) DECIDED 2026-08-22: Apex wins.** Direct comparison of the two block
implementations (`feature_registry.py`) confirms the reasoning above with
specifics: under `derive_market_features()`, `ev_home == ev_draw == ev_away`
always (algebraically identical per its own docstring — one independent value
presented as three), `draw_probability` is a byte-for-byte duplicate of
`market_prob_draw`, and `market_confidence` is a duplicate of
`max(market_prob_home, market_prob_draw, market_prob_away)` — three of its
fourteen fields carry zero independent signal. `derive_apex_market_features()`
replaces all four with `market_overround`, `market_favorite_{home,draw,away}`
(three clean binary flags instead of one ordinal-coded `market_favorite`),
`market_probability_margin`, and `market_normalized_entropy` — none of which
duplicate another field in the block. **(b) is already implemented**, and was
before this decision was recorded: `train_on_real_matches.py:697` stamps
`feature_schema_version: f"apex_v1_{len(feature_names)}"` into every trained
candidate's metadata unconditionally — no code change needed. **(c) is now
moot** — legacy did not win, so no `--market-block legacy` path is needed.
**(d) shipped 2026-08-22**: `build_dataset()` now asserts the market-block
slice of `feature_names` equals `APEX_MARKET_FEATURES_14` before training
starts, so a future edit cannot silently swap in `MARKET_FEATURES_14` (or any
other reordering) while the artifact still claims `apex_v1_*`. Pinned by
`tests/unit/test_train_on_real_matches_market_block.py`.

✅ **Serving wire-up SHIPPED 2026-08-22 (the follow-up this entry called for).**
Both serving implementations now dispatch the market block on the active
generation's declared `feature_schema_version`, closing the last mechanical
blocker this item owned:

- `data/transformers.py` — `FeatureTransformer.__init__` resolves the active
  schema (new `schema_version` kwarg, defaulting to the manifest via
  `active_feature_schema_version()`), sets `expected_columns` from
  `resolve_feature_schema()`, and `_project_to_canonical_features()` calls
  `derive_apex_market_features()` under an `apex_*` schema, `derive_market_features()`
  otherwise.
- `services/upcoming_match_feature_service.py` — `UpcomingMatchFeatureProjector`
  gains `_resolve_is_apex()`, and `project_match_features()` branches the same
  way, updating `derived_resolved` with `APEX_MARKET_FEATURES_14` on that path
  so data-gap bookkeeping stays honest.
- `models/feature_registry.py` — `_is_apex_schema` promoted to public
  `is_apex_schema()`; `active_canonical_features()`/`active_default_feature_values()`
  gain an `apex=` axis (separate from the phase7/phase8 *width* axis). Apex-only
  market defaults are derived from the same neutral 1X2 snapshot the legacy path
  uses (2.5/3.3/2.8) rather than hand-authored constants, and the seven
  legacy-only names are dropped from the apex default set so a serving gap can
  never report a stale legacy value.
- `models/promotion_evidence.py` — new `current_serving_contract()` replaces the
  hardcoded `CANONICAL_FEATURES_68` comparison in both
  `build_promotion_feature_evidence()` and `validate_promotion_feature_evidence()`.
  **This was load-bearing:** without it `serving_schema_misaligned_slots` would
  have reported 11 forever, so no serving fix could ever have satisfied the gate.

**Measured result:** under today's real `phase7_68` manifest the counter still
reads **11** and the gate still FAILs — correct, because legacy is genuinely
what serves today. Under an `apex_v1_68` manifest the same candidate reads
**0**. Pinned by `test_serving_comparison_follows_the_active_schema`.

⚠️ **Every path is inert until an `apex_*` generation is actually activated.**
`active_generation.json` still declares `phase7_68`, so today's behaviour is
byte-identical — proven by `test_default_schema_version_is_unchanged` and by the
20 pre-existing parity tests passing unmodified. Both resolvers fail closed to
`phase7_68` on any error (missing manifest, unknown schema string), matching
what serving already did.

**Contract attribution corrected in the same change:** `_serving_source()` had
returned `UNDECLARED` for apex market slots on the grounds that
`derive_apex_market_features` had "zero callers anywhere in backend/src". That
became false the moment serving was wired, so the attribution now names the
apex helper (14/14 slots, was 0/14) — never the legacy one, since the seven
shared names are exactly what a name-keyed lookup would get wrong. Guarded by
`test_apex_market_block_now_has_a_real_serving_attribution` and its regression
twin `test_legacy_schema_market_attribution_is_unchanged`, both watched failing
on a reverted wire-up before being trusted. The committed
`backend/models/feature_contract.json` is unchanged (it describes `phase7_68`);
`verify_feature_contract_freshness()` still exits 0.

**What this does NOT do:** it does not promote anything. The candidate still
independently fails `no_league_regression` (3/6 leagues) and `market_baseline`
(0/6 leagues) — both model-quality gates, unrelated to schema alignment, and
both blocked on real elapsed match volume rather than code. **Remaining trigger
for this item:** train an Apex-schema candidate that clears those two gates,
then activate it (which requires regenerating `feature_contract.json` for
`apex_v1_68`, or the build gate fails closed — by design).

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

   ✅ **(a) RESOLVED 2026-08-24.** The 6 goals/gd fields are no longer a
   replicated assignment. `derive_goals_gd_features()` (`feature_registry.py`)
   is the single implementation, wired into all four copies — the two serving
   pipelines, the training builder, and the parity harness's own `_assemble()`,
   a **fourth** replica this item had not counted. Because the three pipelines
   need genuinely different missing-value policies (the divergence (b) below
   declares by design), the helper takes the caller's own `(key, default)`
   lookup: `FeatureTransformer` keeps passing its fail-closed `get_num`
   (raises `DataUnavailableError`), the projector passes `dict.get`, and
   training passes a strict lookup (raises `KeyError`, dropping the row). The
   *names* were the duplication, not the arithmetic, so the helper owns the key
   mapping and the defaults while the lookup policy stays with the caller.
   Defaults now come from `DEFAULT_FEATURE_VALUES_68` instead of hand-copied
   literals — the projector's copies had **already drifted** (1.5/1.2/0.0, with
   the home literals reused verbatim for the away side, where the registry says
   home 1.55/1.20/0.35 and away 1.25/1.40/-0.15). Those were unreachable in
   practice, since both stats producers always emit all three keys per side, so
   this is a latent-bug fix rather than a behaviour change; no reachable path
   moved. Attribution strings updated and `feature_contract.json` regenerated
   accordingly — the build gate caught the stale contract exactly as designed.
   6 new tests, and the default-sourcing guard was watched failing against an
   injected hand-copied literal (`assert 1.5 == 1.55`) before being trusted.

   **What remains uncovered:**
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

## 35. RESOLVED 2026-08-30 (live-verified) — `fixture_sync.identity_rebind_pending` has zero consumers — the drift it correctly detects just accumulates in warning logs

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

**Tier:** `RESOLVED` — both the review and apply tooling shipped (below), and
a live probe of `GET /api/v1/release/fixture-identity-review` on
2026-08-30 confirms the production backlog is now genuinely empty:
`total_mismatched: 0`, `rebind_ready_count: 0`, `blocked_count: 0`,
`leagues_affected: []`. Kept in the ledger as the historical record of the
fix, not as an open item.
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

✅ **(a) RESOLVED 2026-08-22.** `sync_upcoming_fixtures()`
(`fixture_sync_service.py`) now sets a gauge —
`fixture_sync.identity_rebind_pending_backlog` — to the exact count of
mismatched fixtures found in that tick, right before commit. The existing
`fixture_sync.identity_rebind_pending` counter is untouched (it still answers
"how many rebind events fired this process lifetime"; the gauge answers "how
big is the backlog right now"). Because fixture_sync re-evaluates every
currently-tracked unsettled fixture on every tick (immediate on boot, then
every 6h), the gauge is a true point-in-time backlog size, not an
ever-growing counter — it self-corrects within seconds of every deploy
instead of silently reading 0 until the next drift event happens to fire.
Surfaced automatically via the existing `GET /metrics` → `production.gauges`
path — no new endpoint plumbing needed. Pinned by an added assertion in
`test_provider_elo_identity_bridge.py::test_existing_scheduled_fixture_is_not_silently_rekeyed`,
which already exercises exactly one mismatched fixture.
**(b) partially RESOLVED 2026-08-23** — the review half is built:
`GET /release/fixture-identity-review` (`data_authority.py`, backed by new
`services/fixture_identity_rebind_service.py`) is a read-only manifest of
every currently-drifted fixture, mirroring item 34's
`historical_identity_repair_manifest_service.py` shape. It needed no live
provider call and no re-run of resolution logic: `Match.id` is the provider
event id, so joining `Match` ⋈ `ProviderEventMapping` ⋈ `CanonicalFixture`
directly recovers the "verified" identity `ensure_canonical_fixture` already
persists every tick, independent of whatever the legacy `Match` row still
holds. Each entry carries stored vs. verified participant ids/names and
computed blockers (`KICKOFF_PASSED`, `CROSS_LEAGUE_MISMATCH`,
`HAS_EXISTING_PREDICTIONS`) per the APEX directive's §5.5 requirements for an
operator-controlled reconciliation path. **The actual rebind/apply — writing
corrected ids back onto `Match` rows — is still NOT built, deliberately**:
that is a Class-C production-identity mutation (APEX §3) needing its own
separately-authorized dry-run-manifest flow, out of scope for a review tool.
Verified locally against SQLite via 6 new unit tests
(`test_fixture_identity_rebind_service.py`) exercising the mismatch/no-mismatch/
settled-excluded/kickoff-passed/existing-prediction/hash-determinism cases;
not yet probed against the live production database this session — the render
log evidence that reopened this item (13 fixtures, same `fd-team-` vs
`fdco-team-` shape as the original 9) is the expected shape this endpoint
would surface once deployed.

✅ **(b) apply tool SHIPPED 2026-08-25 — the Class C executor is BUILT (code
only; nothing mutated).** `services/fixture_identity_rebind_apply_service.py`
+ `scripts/repair_fixture_identity_rebind.py` +
`POST /api/v1/release/fixture-identity-repair-apply`, mirroring item 39's
`orphan_team_rebind_service.py` precedent rule-for-rule: `--review`/`GET
.../fixture-identity-review` are read-only; `--apply`/`POST
.../fixture-identity-repair-apply` require the reviewed full-manifest
`--manifest-sha256`, an `--authorization-id`, and the literal confirmation
token `APPLY_FIXTURE_IDENTITY_REBIND`; PostgreSQL-only
(`acquire_fixture_identity_rebind_locks` raises on any other bind); the
manifest digest is re-derived under
`LOCK TABLE matches, canonical_fixtures, provider_event_mappings, match_prediction_logs IN SHARE ROW EXCLUSIVE MODE`
and every row's exact pre-state re-checked, so a concurrent change aborts
before a single write. It writes `Match.home_team_id`/`away_team_id` and
nothing else — no `Team`/`CanonicalTeam` created or renamed, no
`EloRatingSnapshot` touched.

**Deliberate deviation from the item-39 precedent, not a copy of it.** Orphan
rebind refuses the whole apply if *any* manifest entry is blocked — safe
there because that manifest happened to reach zero-blocked before it was
applied. This item's live manifest is routinely a *mix* of ready and blocked
entries, and a `HAS_EXISTING_PREDICTIONS` blocker will not resolve on its own
(predictions are never deleted), so an all-or-nothing rule would make this
tool permanently inapplicable. The executor therefore re-derives and
digest-checks the **full** manifest (ready and blocked entries alike — any
drift in either aborts the apply), then writes only the entries whose
`blockers` tuple is empty, leaving blocked entries untouched and still
visible on the next review. Two postconditions run before the caller commits:
(1) no touched fixture may record a team playing itself (item 23's shape);
(2) re-deriving the manifest must no longer propose any fixture just written.
9 tests cover the mixed ready/blocked happy path (only ready entries rebound,
blocked entries' rows provably untouched), a stale digest, a row that moved
since review, an all-blocked (empty ready-subset) refusal, a duplicated-match
guard, self-play refusal on a malformed verified identity, the
PostgreSQL-only lock refusal, and the self-play postcondition catch. The
ready/blocked split was watched failing before being trusted: sabotaging
`_ready_entries()` to return the full manifest (bypassing the filter) reddened
the mixed happy-path test, confirming it is load-bearing and not an artifact
of the seeded scenario.

### Class C authorization package — current as of `sha:1b62331`

⚠️ **This digest is provisional and will move.** Fixture sync re-evaluates
every unsettled fixture on every tick (immediate on boot, then every 6h) and
resolves or newly detects mismatches as it runs, so — exactly as item 39's
own package warned — **always re-run `GET /fixture-identity-review`
immediately before any `--apply`/`POST .../fixture-identity-repair-apply`
call and use the digest it prints.** Any digest recorded here before that
moment is stale by construction and the executor will refuse it.

Live `GET /api/v1/release/fixture-identity-review` (2026-08-25, pre-deploy of
this PR): **59 total mismatched live fixtures, 54 rebind-ready, 5 correctly
blocked**, across BUNDESLIGA, EPL, EREDIVISIE, LA_LIGA, LIGUE_1, SERIE_A.
Blocked entries and why, all correct fail-closed behaviour, not defects:

| Match | League | Blocker |
|---|---|---|
| `fd-558233` | EREDIVISIE | `KICKOFF_PASSED` |
| `fd-560555` | EPL | `HAS_EXISTING_PREDICTIONS` |
| `fd-564636` | LA_LIGA | `HAS_EXISTING_PREDICTIONS` |
| `fd-564637` | LA_LIGA | `HAS_EXISTING_PREDICTIONS` |
| `fd-564649` | LA_LIGA | `HAS_EXISTING_PREDICTIONS` |

**Replay boundary: none.** The ready set is unplayed/unsettled fixtures whose
stored identity disagrees with the already-verified canonical identity — a
forward-looking repoint, not a rewrite of settled history. No Elo replay is
implicated (this tool never touches `EloRatingSnapshot`).
**Rollback:** `--apply`/the endpoint response prints the exact `(match,
column, from, to)` reversal tuples for every column actually changed.

**Status: NOT EXECUTED (as of the paragraph above).** No Class C mutation had
been requested or authorized for this batch at merge time.

⚠️⚠️ **2026-08-25 — authorized, attempted, and caught a real defect before
any data was written; the manifest builder itself was wrong.** The user
explicitly authorized applying against the live backlog. A fresh
`GET /fixture-identity-review` was fetched immediately before applying (per
this item's own standing rule) and returned the identical digest recorded
above (`4a4a5a0b…`), confirming nothing had drifted. `POST
/fixture-identity-repair-apply` was called with that exact digest and
returned **HTTP 500**, not a clean postcondition refusal.

**Root cause, found from the live Render traceback, not guessed:**
`asyncpg.exceptions.ForeignKeyViolationError: insert or update on table
"matches" violates foreign key constraint "matches_away_team_id_fkey"`.
`Match.home_team_id`/`away_team_id` are `FOREIGN KEY → teams.id`
(`core/database.py`) — but this manifest builder's "verified" identity was
`CanonicalFixture.home_team_id`/`away_team_id`, which is
`FOREIGN KEY → canonical_teams.id` (`db/models.py`) — **a completely
different table and id namespace.** `docs/DEBT.md` item 39's own 2026-08-24
correction had *already* named this exact trap for this exact endpoint
("that target is `CanonicalFixture.home_team_id`/`away_team_id` —
`canonical_teams.id`, a different table `Match` never references… a wholly
separate system from the one that actually backs `Match.home_team_id`") —
it went unheeded when this apply tool was built on top of the pre-existing
review manifest, because the review manifest itself (shipped 2026-08-23,
before item 39's correction was written) was never revisited against it.

**Verified safe before doing anything else, not assumed:** a fresh
`GET /fixture-identity-review` immediately after the 500 showed the digest
and summary byte-identical to before the failed call, and a direct read-only
production query confirmed zero `matches` rows carry a `canonical_teams.id`
(`team-<hash>`)-format value in `home_team_id`/`away_team_id`. The FK
violation aborted the transaction before `db.commit()` was ever reached —
**no data was written or corrupted.**

**Fix, in `fixture_identity_rebind_service.py`** (manifest schema bumped
2 → 3): the "verified" identity is now the same durable Elo bridge
`fixture_sync_service._resolve_upcoming_team_id()`'s fast path already uses —
`ProviderEventMapping.evidence` durably stores each side's
`home_provider_team_id`/`away_provider_team_id` (written every sync tick,
independent of the canonical-identity system), and
`team_identity.resolve_provider_elo_team_id()` resolves that to a real,
same-league, Elo-bearing `Team.id` via the `VERIFIED` `ProviderEloTeamMapping`
bridge — still **no live provider call**, just querying the correct durable
table instead of the wrong one. A side with no durable `VERIFIED` binding yet
is silently excluded from the manifest (cannot be safely reconciled without
live data), rather than guessed. The now-moot `CROSS_LEAGUE_MISMATCH` blocker
is dropped — `resolve_provider_elo_team_id` only ever returns a same-league
team by construction.

**Defense in depth added in `fixture_identity_rebind_apply_service.py`:**
`_assert_ready_entries_are_applicable` (now async) independently re-verifies
every proposed target is a real, same-league `Team` row *before* attempting
any write — so a future manifest-builder regression fails closed here too,
with a clear message, instead of surfacing as a raw database-driver crash.
Watched failing: reverting this check locally reproduced red on both new
test cases before being trusted.

**Both existing test files were rewritten, not patched around** — the
original seeding for both `test_fixture_identity_rebind_service.py` (item
35a) and `test_fixture_identity_rebind_apply_service.py` (item 35b) only
ever exercised the canonical-identity system, which is exactly why neither
suite caught this before a live attempt did. Seeding now builds a real
`ProviderEloTeamMapping(status="VERIFIED")` bridge with genuine Elo history
for every "ready" fixture, matching what production actually requires — the
identical gap a review-manifest test suite testing against the wrong table
could never have caught. New coverage: a fixture with canonical identity
resolved but no durable Elo bridge is correctly excluded from the manifest
(`test_manifest_excludes_matches_with_no_durable_binding`); the apply
service's existence/league re-check has its own two direct tests.

**Corrected live before considering the apply requested again:** the fixed
manifest builder must be deployed and re-reviewed fresh — the pre-fix digest
(`4a4a5a0b…`) and its 54/5 ready/blocked breakdown are **void**; they
described a manifest sourced from the wrong table and must not be reused.
Applying against the corrected manifest is a new decision requiring its own
fresh review and its own authorization, not a continuation of this one.

⚠️ **Lesson, stated plainly:** this repository had already written down the
exact warning that would have prevented this, in the immediately-preceding
item (39), and it was not cross-checked against a sibling module built on
the same wrong assumption. When two endpoints/services describe the same
"verified identity" concept, a correction to one must trigger an audit of
every other consumer of the same concept — not just the one that happened to
surface the bug first.

### ✅ Corrected manifest deployed and live-verified (`sha:716aaa7`, 2026-08-25)

**The real backlog is 2 fixtures, not 59. The old "54 rebind-ready" were
almost entirely false positives, and this is provable, not inferred.**

A read-only production query settles it:

```sql
SELECT count(*) AS canonical_team_rows,
       count(*) FILTER (WHERE id LIKE 'team-%') AS hashed_namespace_rows,
       count(*) FILTER (WHERE id IN (SELECT id FROM teams)) AS also_in_teams
FROM canonical_teams;
-- → 114 / 114 / 0
```

All 114 `canonical_teams.id` values live in the `team-<hash>` namespace and
**not one of them exists in `teams`**. The pre-fix comparison
`match.home_team_id == fixture.home_team_id` was therefore **structurally
incapable of ever being true** — every fixture carrying a
`ProviderEventMapping` was flagged as "mismatched" purely because the two
sides were drawn from disjoint id namespaces. That is the entire explanation
for 59.

⚠️ **The PostgreSQL foreign key was the last line of defence, and it held.**
Had the apply succeeded it would have written 54 fixtures' participants to
team ids that do not exist in `teams`, corrupting the primary fixture table
across all six leagues. `matches_away_team_id_fkey` refused the first such
write and aborted the transaction. **A schema constraint caught what four
layers of application-level review, two test suites, and a hash-verified
manifest all missed** — do not treat a green manifest as proof that its ids
are addressable.

**Corrected live manifest** (`GET /api/v1/release/fixture-identity-review`,
2026-08-25T07:33 UTC, schema_version 3):

```text
manifest_sha256: 3171fb830dd03aa607a3d3d45d73be0b819a3ce0ec4a26ba9cc3edf2a0ccec7c
total_mismatched: 2 · rebind_ready: 1 · blocked: 1
leagues_affected: EPL, LIGUE_1
```

| Match | League | Side drifted | Stored → Verified | Status |
|---|---|---|---|---|
| `fd-559702` | LIGUE_1 | home | `fd-team-ligue_1:lille_osc` → `fdco-team-ligue_1-lille` | **READY** |
| `fd-560555` | EPL | away | `fd-team-epl:manchester_city_fc` → `fdco-team-epl-man_city` | BLOCKED (`HAS_EXISTING_PREDICTIONS`) |

**Targets confirmed history-bearing by direct query** — this is the
Elo-orphan shape item 39 documents, one table over:

| Team id | Name | League | Elo snapshots |
|---|---|---|---|
| `fdco-team-ligue_1-lille` | Lille | LIGUE_1 | **244** |
| `fd-team-ligue_1:lille_osc` | Lille OSC | LIGUE_1 | 1 |
| `fdco-team-epl-man_city` | Man City | EPL | **266** |
| `fd-team-epl:manchester_city_fc` | Manchester City FC | EPL | 1 |

**Three-way independent corroboration that the corrected manifest is right.**
`fixture_sync_service`'s own drift detector — a wholly separate code path
that has been logging this every sync tick, untouched by any of this work —
reports **exactly these two fixtures with byte-identical stored/verified
pairs**, both in the live 07:20 UTC tick and in the 03:49 UTC deploy log
captured before any of this session's changes existed:

```text
match_id=fd-559702 stored=(fd-team-ligue_1:lille_osc,fd-team-ligue_1:paris_saint-germain_fc)
                   verified=(fdco-team-ligue_1-lille,fd-team-ligue_1:paris_saint-germain_fc)
match_id=fd-560555 stored=(fd-team-epl:crystal_palace_fc,fd-team-epl:manchester_city_fc)
                   verified=(fd-team-epl:crystal_palace_fc,fdco-team-epl-man_city)
```

That agreement is exactly what "correct" looks like here: this manifest's
only job is to surface what `fixture_sync` detects and deliberately refuses
to fix, and it now does so precisely — no more, no less.

**Status: still NOT EXECUTED.** The authorization on record was granted for
"the live 54-fixture backlog", which has been shown not to exist. Applying
against a 1-fixture corrected manifest is a materially different operation
and needs its own explicit authorization, taken after a fresh review
(`3171fb83…` moves on every sync tick that resolves or detects drift).

✅ **EXECUTED 2026-08-25T07:50:39 UTC, operator-authorized against the
corrected numbers.** The user was shown the corrected 1-ready manifest and
explicitly re-authorized. Re-reviewed immediately before applying (this
ledger's standing rule): digest still `3171fb83…`, 1 ready / 1 blocked.

```text
POST /api/v1/release/fixture-identity-repair-apply
authorization_id: operator-authorized-2026-08-25-item35b-corrected-pr97
rebound_count: 1 · affected: [fd-559702] · skipped_blocked: [fd-560555]
reversal: fd-559702 home_team_id
          fd-team-ligue_1:lille_osc → fdco-team-ligue_1-lille
```

**Both postconditions verified independently of the endpoint's own checks:**

- Direct DB query: `fd-559702` home is now `fdco-team-ligue_1-lille` ("Lille",
  **244** Elo snapshots) where it was the orphan `fd-team-ligue_1:lille_osc`
  (**1** snapshot). Kickoff 2026-08-28, still `scheduled` — unplayed, so no
  post-match Elo derived from the wrong participant exists and no replay is
  implicated.
- `fd-560555` (EPL, `HAS_EXISTING_PREDICTIONS`) is byte-for-byte untouched.
- Re-review: digest moved to `dbdd3d6e…`, `total_mismatched: 1`,
  `rebind_ready_count: 0` — the rebound fixture dropped out entirely, which is
  postcondition 2 confirmed from outside the transaction that asserted it.

⚠️ **A tooling trap worth recording:** the first post-apply review appeared to
show the fixture *still* pending. That was `WebFetch`'s own 15-minute
per-URL response cache, not production state — the endpoint sets
`Cache-Control: no-store` and was correct all along. **Verify a mutation's
effect with `curl` (or a direct query), never with a tool that caches
responses**; a cached read of a "did my write land" probe is worse than no
read at all.

Item 35 is closed: review (a), apply tool (b), and the executed repair are all
done, live, and independently verified.

**Re-confirmed live 2026-08-28, twice, several hours apart** (no code
touched, documentation only). First probe: `GET
/api/v1/release/fixture-identity-review` still reported exactly the same
single entry as the 2026-08-25 closure — `fd-560555`, blocker
`HAS_EXISTING_PREDICTIONS`, byte-for-byte unchanged from three days earlier.
A 2026-08-26T07:56:49Z Render deploy log line reporting this same
stored/verified pair for `fd-560555` (checked against that first probe
before drawing a conclusion, not assumed) is the same steady state, not a
fresh recurrence — worth recording explicitly since a bare log line out of
context reads like one. **Second probe, later the same day: 0 entries.**
`fixture_identity_rebind_service.py`'s manifest query filters
`Match.status NOT IN SETTLED_MATCH_STATUSES` (confirmed by reading the query
directly), so the fixture most likely finished — its `kickoff_utc` was
`2026-08-28T19:00:00`, i.e. earlier the same day as this second probe — and
dropped out of the manifest entirely rather than staying listed as blocked;
a genuinely finished match is excluded outright, not merely
`KICKOFF_PASSED`-blocked, per this same query. Not independently confirmed against
`Match.status` directly (no DB access this session), but consistent with
every fact available. Either way: no action was needed or taken, and the
backlog is self-resolving via ordinary fixture progression exactly as item
34 documents for the historical case.

---

## 34. Semantic-identity repair manifest v3 is code-ready; live review and `--apply` remain operator-gated — RESOLVED 2026-08-25

**Tier:** `RESOLVED 2026-08-25` — the underlying drift is gone; nothing
remains to review or apply. The production v2 review on 2026-08-21 found 518 affected EPL
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

✅ **RESOLVED 2026-08-25 — the drift is gone, no repair was ever applied.**
`sabiscore_db_v3`'s `ipAllowList` was opened for direct read-only access this
session, which prompted a fresh live probe rather than trusting the
2026-08-21 "518 affected" figure. `GET /api/v1/release/semantic-repair-review`
(the exact production code path `--review` would run) now returns
`manifest.schema_version: 3`, `manifest.summary.affected_matches: 0`,
`blocked: false`, `complete: true`, `authorization.review_ready: true` — zero
findings, not 518-resolved-to-repair-ready. **Corroborated independently**,
same probe, via `GET /api/v1/release/data-authority`: `semantic_identity:
"PASS"` (zero historical league-mismatch findings) and `structural elo: PASS`
with every invariant counter at zero — a completely different query
(`data_authority`'s own structural/semantic checks vs. this item's
`audit_historical_semantic_identity()`) landing on the same answer.

⚠️ **Neither `historical_backfill_service.py` nor the audit/manifest services
have changed since `d4ad5a2`** (the commit that shipped the schema-v3 manifest
this item is about, predating the 2026-08-21 review that found 518) — so this
is not a code fix quietly closing the gap. The most likely explanation: the
2026-08-21 review's blockers were "a missing same-league West Ham Team
identity plus exact/alias ambiguity for Man City and a curated-alias miss for
Ipswich" — i.e. missing/unresolved same-league `Team` rows for clubs whose
*first* EPL fixture of the 2026/27 season (opening 2026-08-21) had not yet
been synced by `fixture_sync_service` at review time. Once EPL fixtures began
syncing, the live provider path created the missing same-league `Team` rows
independently of this item's own resolver, and `audit_historical_semantic_identity()`
— which joins against whatever `Team` rows exist *now* — stopped finding a
cross-league/missing-identity mismatch for those historical matches. This is
the same self-healing shape already documented for item 10's Elo coverage
(real data volume closing a gap no code change was needed for), not a fluke:
two independent live queries agree, and no manifest, script, or endpoint in
this item's scope was touched to produce the result.

**No Class C action was ever taken for this item** — `authorization.review_ready:
true` with zero entries means there is nothing to authorize or apply. Item 34
closes as "the problem resolved itself once the season started," which is
itself worth recording so a future session doesn't reopen it chasing a stale
518-match figure.

**Addendum (2026-08-26):** a session opened with a standing operator
authorization dated 2026-08-26T02:25:43+01:00 WAT, quoting the manifest SHA
`a1eae47c4d5b86fb3b0eda2bc997f219533561f0913cd584ecc49839cfa72b62` and replay
plan SHA `9bf816061704b6c45aacdc3080eba4d25dcc0d5e007c834687f66d02d7d87bd4`
recorded above, authorizing exactly the 518-row repair this item already
closed the day before. Independently re-confirmed this session by re-reading
this item directly rather than trusting the authorization text's premise: the
condition it targets does not exist. Its own required pre-mutation step —
re-run the dry-run, verify the manifest hash still matches — cannot pass,
because a manifest computed over 0 affected rows cannot reproduce a hash
computed over 518. **No repair was executed.** See
`docs/ai/CODEX_VERIFIED_STATE.md`'s "SAB-22 stale-authorization verification
from 2026-08-26" section for the full record of this check.

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

## 24. Rescheduled fixtures wedged the whole fixture-sync tick; mitigation shipped, then the root cause was fixed too

**Tier:** `RESOLVED 2026-08-16` — mitigation (`35ca7bb`) *and* root cause
(`0384804`, `da1c1f2`) both shipped. (Re-scoped 2026-08-24: this line read
"Root cause = `NEXT`" and the body claimed the fix was deferred; both were
already false when written — see the correction below.) A latent
multi-provider dedup concern remains recorded but is not a live defect.
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

⚠️ **CORRECTED 2026-08-24 — the paragraph that stood here was factually
wrong.** It read "Not done — deliberately deferred… a rescheduled fixture's
canonical identity stays unreconciled indefinitely." That has not been true
since `0384804` ("reconcile verified provider reschedules in place") and
`da1c1f2`, both shipped 2026-08-16, the same day this item was filed. Read
`ensure_canonical_fixture` end to end: when a `ProviderEventMapping` already
exists it conflict-checks on **competition + home_team_id + away_team_id
only** — kickoff is deliberately excluded — then mutates
`mapped_fixture.kickoff_utc` in place and **returns early**. The
`_stable_id(...)` call that hashes `kickoff_utc` is reachable *only* for a
provider event never seen before. Its own docstring states the contract:
"Kickoff and provider display names are mutable metadata: legitimate
reschedules/name changes update those fields without changing canonical
participants." Pinned by
`test_provider_reschedule_updates_kickoff_without_identity_drift`. Leaving
the old text in place would have sent a future session to rewrite a hash that
does not need rewriting.

**What genuinely remains — and it is not the reschedule problem.** The
`session.get(CanonicalFixture, fixture_id)` following that hash is a *dedup*
lookup: a second provider reporting the same match hashes to the same id and
attaches to the existing row. So switching to a kickoff-independent key
(`(competition_id, season, home_name, away_name)`) would make legacy
kickoff-derived rows unfindable, and a new provider event for an
already-canonical fixture would mint a **duplicate** canonical fixture
instead of attaching. That needs either a dual-key lookup or a backfill.
With the operational pain gone, this is a latent multi-provider concern, not
a live defect — and the change is deliberately **not** worth making until a
second provider actually writes canonical fixtures.

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

## 20. A Render service builds the monorepo at root and is not in `render.yaml` — `RESOLVED 2026-08-23`

✅ **Live-verified via the Render MCP tool this session**: `list_services`
(workspace `tea-d9509cpkh4rs73fs82q0`, `includePreviews: true`) returns
exactly two services — `sabiscore-api` (`rootDir: backend`, the canonical
web service) and `sabiscore-evidence-acquisition` (the cron job). No third,
blueprint-invisible, root-building service exists. The operator checklist
below (steps 1–6, dashboard-only) has evidently been completed — the stray
service is gone, not merely suspended. Not re-diagnosed further; this closes
the item on direct evidence rather than inference from a stale log.

**Tier:** `FIX-NOW` / P0 — it crash-looped on every push to master.
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

**Tier:** migration `RESOLVED 2026-08-25` (tier-1 Redis is live in production,
verified by this item's own step-5 method). **Old-credential revocation
remains `NEXT` and operator-only.** Was `FIX-NOW` / P0.
**Found:** 2026-08-09. **Second call site found and fixed:** 2026-08-10.

> ✅ **Migration confirmed live 2026-08-25.** Probed exactly as step 5 below
> prescribes — reading `components.cache.metrics`' tier flags rather than the
> top-level `cache` string this ledger already warns is insufficient on its
> own:
>
> ```text
> GET /health  (sha c09e46c)   cache.status: healthy
>   tier1_redis_enabled:   True      tier1_redis_available: True
>   tier1_circuit_open:    False     tier2_upstash_active:  False
> ```
>
> Steps 1–5 of the runbook are therefore demonstrably complete: a valid
> `rediss://` URL is set on `sabiscore-api`, the production guard accepted it,
> and tier-1 is connected with the breaker closed. This supersedes the
> "not confirmed migrated" note further down, which was written during a
> 2026-08-13 window when the service was returning 503.
>
> ⚠️ **What is still genuinely open is step 6 only:** revoking the exposed
> credential in the old Redis Cloud console (database `sabiscore-database`,
> ID `13753214`). That is operator-only and not checkable from code — a live
> tier-1 connection proves the *new* credential works, it proves nothing about
> whether the *old* one was revoked. Do not close this item on the evidence
> above alone.
>
> Note `tier2_upstash_active: False` — tier 2 is not configured, which is fine
> (tiers 2/3 are fallbacks), but it means the migration landed on a working
> tier-1 rather than the Upstash target the 2026-08-13 transcript described.
> The runbook below is retained as-is because its diagnostics are sound and
> the guard behaviour it documents is real.
>
> **Operator-reported 2026-08-27/28: old-credential revocation (step 6)
> stated complete.** The operator stated in this turn that "the keys have
> been rotated." This is recorded as an **operator report, not an
> independently verified fact** — exactly the distinction this item has
> insisted on throughout: `GET /health` still shows `tier1_redis_enabled:
> true`, `tier1_redis_available: true`, `tier1_circuit_open: false`, which
> proves *a* credential currently works, the same thing it already proved on
> 2026-08-25. This environment has no Upstash/Redis Cloud console access, so
> it cannot independently confirm the *old* `sabiscore-database` (ID
> `13753214`) credential was actually revoked rather than merely superseded.
> Leave this item's tier as-is until the operator supplies (or this
> environment gains access to) dated revocation evidence from that console —
> the same standard item 16 already holds historical Gitleaks credentials to.

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

**Tier:** `NEXT` — narrowed 2026-08-25 to exactly two open sub-items, both
requiring something code cannot do (a credential owner's revocation evidence;
an actual Docker build run). Was `FIX-NOW` / P0 "before merge or deployment",
which is no longer an accurate description of what remains.
**Verified:** 2026-08-10. **Re-verified and narrowed:** 2026-08-25.

> ✅ **Re-verified 2026-08-25 against live production and a full-history scan.**
> The 2026-08-22 staleness warning below was correct; here is what the actual
> checks return now.
>
> **CLOSED — Alembic head proof.** This item claims `0006_canonical_league_ids`
> is the sole head and that `upgrade head` timed out, leaving migration proof
> absent. Live `GET /health/ready` returns:
>
> ```text
> migrations: {"status":"ready","message":"Alembic head is applied",
>              "head":"0009_quarantine_market_closings",
>              "applied":"0009_quarantine_market_closings"}
> ```
>
> Three migrations past the one named here, applied and verified in
> production. `backend/alembic/versions/` confirms the same tip locally.
>
> **CLOSED — deploy/CI dispatch.** Backend and Vercel both report
> `sha: c09e46c` (full parity with `origin/master` HEAD),
> `backendStatus: "ok"`, `status: "healthy"`. Every PR merged this session
> (#95–#99) cleared all required canonical checks including SonarCloud, on
> named runners with real steps.
>
> ⚠️ **OBSOLETE AND ACTIVELY MISLEADING — the "Release rule" at the bottom of
> this item.** It reads *"keep PR #5 unmerged and do not activate Render or
> promote a Vercel deployment while any item above remains unproven."* The
> repository is ~95 PRs past #5; Render and Vercel are both live, healthy, and
> have been continuously deployed from `master` throughout. **Disregard that
> line entirely.** It is struck rather than deleted so the record of what was
> once believed survives — but a top-priority ledger entry instructing "do not
> deploy" while the team deploys all day is worse than no entry, because it
> teaches readers that this file is safe to ignore. This session was already
> bitten twice by trusting stale ledger claims (item 34's phantom 518 matches;
> item 35's wrong-table manifest), which is why it is called out this bluntly.
>
> **STILL GENUINELY OPEN — 1 of 2: historical Gitleaks fingerprints.**
> Re-ran a full-history scan this session (456 commits, 28.15 MB, 12.5s):
> **exactly 2 leaks found**, unchanged and matching this item's own record —
> `backend/.env.example` `generic-api-key:17` at `d604c13` and
> `generic-api-key:10` at `67ed0ab`. Current tree is clean. These cannot be
> waived without the credential owner's dated revocation evidence for those
> exact values; that is operator-only.
>
> **STILL GENUINELY OPEN — 2 of 2: fresh Docker image proof.** No
> `sabiscore-backend:verify` or `sabiscore-web:verify` image exists in the
> local Docker daemon (checked this session; the daemon reports no such
> tags). Proving this needs an actual build run, which prior sessions
> recorded as exceeding 15 minutes under the available Docker VM memory —
> not attempted here, and not something a code change can satisfy.

> ⚠️ **Partially stale as of 2026-08-22 — re-verify before treating any line
> below as current.** This item's evidence predates roughly 60 merged PRs
> (last renumbered reference here is "PR #5"; the repository is at PR #75 as
> of this note) and its own Alembic line names `0006_canonical_league_ids`
> as the sole head — the tree now has three migrations past that
> (`0007_durable_elo_state`, `0008_provider_elo_team_identity`,
> `0009_quarantine_post_kickoff_closings`, confirmed by listing
> `backend/alembic/versions/` directly). A live production Render deploy log
> captured this same session shows a clean, fast, successful boot: build
> succeeded, `alembic upgrade head` applied cleanly, `Alembic schema revision
> verified: 0009_quarantine_market_closings` logged, service went live,
> `/health/ready` returned 200 repeatedly within seconds. Every PR in this
> session (#72–#75) also merged through genuinely green canonical CI
> (`gh pr checks`, all required jobs `SUCCESS`) with no billing-lock
> annotations anywhere — the GitHub Actions dispatch blocker this item
> tracked is confirmed still clear. The **"Release rule" line below is
> obsolete** (PR #5 is ~70 PRs in the past) and should not be read as
> current merge policy. **Not re-verified this session, genuinely unknown
> either way:** the two historical Gitleaks credential fingerprints (still
> needs the credential owner's dated revocation evidence — operator-only,
> not code-checkable) and whether a fresh `sabiscore-backend:verify` /
> `sabiscore-web:verify` Docker image tag exists (needs an actual build run,
> not attempted this session). Do not mark those two sub-items resolved
> without independently re-running them.

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

~~**Release rule:** keep PR #5 unmerged and do not activate Render or promote a
Vercel deployment while any item above remains unproven.~~
**↑ OBSOLETE — struck 2026-08-25.** See the re-verification block at the top of
this item. The repository is ~95 PRs past #5 and both Render and Vercel are
live, healthy, and at full SHA parity with `master`. This line does not
describe current merge or release policy.

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

**Tier:** `NEXT` (StatsBomb only) — **Elo half RESOLVED 2026-08-25**, independently re-verified at 100% production coverage (see below). StatsBomb remains offline debt, unrelated to database access. The historical incident below is retained because the legacy Parquet files still exist for offline/backward-compatible tooling.
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

✅ **2026-08-25 — Elo half independently re-verified at 100% coverage,
superseding the 2026-08-17 74–77% figure.** `sabiscore_db_v3`'s `ipAllowList`
was opened this session, prompting a fresh live probe:
`GET /api/v1/release/data-authority` reports **25,668 `elo_rating_snapshots`
rows / 185 teams / 12,834 of 12,834 eligible finished matches processed —
coverage ratio 1.0**, structural Elo `PASS` (every invariant counter zero).
The backlog the 2026-08-17 entry described (five years of pre-2024 history
behind a global chronological cursor) has fully drained. **DATA_FED/VERIFIED
reached for the Elo half** — production `alembic upgrade head` is confirmed
current (backend `/health` `sha` matches local HEAD), replay ran, and row
coverage is complete. The StatsBomb portion is untouched by this probe and
remains exactly as described below: frozen, offline debt, unrelated to
database access.

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

✅ **The ≥10 floor crossed — live-confirmed 2026-08-28, no code touched.**
`GET /api/v1/model-performance/summary` now returns `status: "OK"`,
`total_settled: 11` (up from the 9 recorded two sessions ago), `rps_overall:
0.331495`, `n_splits: 3`. `GET /api/v1/model-performance?window=30` confirms
the underlying `series` is real, not a stub: 3 chronological folds
(2026-08-16, 2026-08-21, 2026-08-22), one settled match each, RPS per fold
ranging 0.294–0.355. Both endpoints (`model-gates.ts`'s consumers
`rolling-accuracy-chart.tsx` and `performance-page-client.tsx`) were already
correctly wired for this transition before today — `hasMetrics = status ===
"OK"` and `series.length > 0` gate the real-data branches, `SummaryNotice`/
`ChartNotice` were only ever the < 10 path. **No frontend code change was
needed or made.**

**Read the numbers honestly, don't over-claim from n=11.** `accuracy_overall`
(top-pick exact-hit rate) is **0.0** — zero of eleven settled predictions
landed the model's highest-probability outcome. At this sample size that is
not a meaningful signal of model quality either way (a well-calibrated model
can plausibly go 0-for-11 by chance on single-outcome top-pick hits alone);
RPS is the continuous, calibration-sensitive metric this platform's own
promotion gate actually uses, and 0.331 is currently **above**
`RPS_PROMOTION_GATE = 0.21` (`apps/web/src/lib/model-gates.ts`) — i.e. does
not yet meet it. The UI renders this correctly (amber stat, not a fabricated
pass). Two sub-metrics stay honestly gated below their own floors rather than
publishing on too little data: Brier decomposition ("requires ≥10 pooled
validated records, only 3 available") and CLV ("need >= 10 joined
predictions, got 1" — see item 6, unaffected by this crossing, a materially
different join). **Do not treat this crossing as a verdict on model
quality** — it only means the walk-forward pipeline itself is now DATA-FED
and producing real, honestly-gated numbers; whether those numbers are good
is a question for a much larger sample.

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
