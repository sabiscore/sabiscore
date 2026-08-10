# SabiScore Debt Ledger

Format per entry: **Tier** (`FIX-NOW` / `NEXT` — named trigger / `ARCH-DEBT` — needs an
ADR / `ACCEPTED` — rationale + review date), owner, blast radius, engineering cost,
user impact, priority. An entry without a trigger is not `NEXT`, it's `ACCEPTED` in
disguise — say so honestly.

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
formally `UNVERIFIED`; until it is certified, both betting engines must keep every
public stake at zero.

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

## 16. Release infrastructure and historical-secret gates remain closed

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
- Docker Compose configuration passes. Fresh backend and web image retries ran
  for more than five and three minutes respectively without producing a current
  image. The only `sabiscore-backend:verify` tag is dated 2026-07-15 and
  `sabiscore-web:verify` does not exist.
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

**What this does NOT fix** — see item 13. The model is now sound, but it is
trained on 31 of 68 features because that is all serving resolves. Market, h2h,
venue and Elo evidence remain unavailable at prediction time, and the artifact
holds those slots at registry defaults by design so it cannot lean on them.

---

## 13. Serving resolves 31 of 68 canonical features — market, h2h, venue and Elo are absent

**Tier:** `NEXT` — trigger: whichever of the four below is wanted first; each is
independently shippable and each would be followed by a retrain to let the model
use it.
**Owner:** unassigned.
**Found:** 2026-08-08, while establishing the retrain's feature set.

After the 2026-08-08 derivation fix (schedule, league one-hots, league rates and
combination features are now computed rather than defaulted), serving resolves
**31 of 68**. The model is trained on exactly that set, so there is no train/serve
skew — but four families of genuine football evidence are still missing:

| Family | Count | Why it is absent |
|---|---|---|
| Market prices / odds | 14 | `OddsService` fetches a board, but the canonical `market_prob_*` / `log_odds_*` / `ev_*` block is never projected onto the feature vector. Highest value of the four: it is the market consensus the edge calculation exists to beat. |
| Head-to-head | 5 | One DB query over prior meetings; nothing computes it. |
| Home venue record | 4 | Derivable from the same team history already queried, filtered to home fixtures. |
| Elo / tactical | 8 | Blocked on item 10 — the parquets are synthetically keyed. |

**Blast radius:** prediction quality. The model is honest and directionally sane
on 31 features, but it is pricing without ever seeing the market, the fixture's
own history, or venue effects.
**Cost:** market and h2h are each a contained piece of work (compute at serving,
add to the training builder's feature set, retrain, re-run the comparison).
Venue is smaller still. Elo depends on item 10.
**Impact:** moderate-to-high — this is the difference between a working model and
a competitive one.
**Priority:** highest open item. Take market prices first.

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

## 10. Offline Elo / StatsBomb artifacts are frozen at 2024-06-02 — and synthetically keyed

**Tier:** `FIX-NOW` (raised from `NEXT` on 2026-08-08) — the trigger this item was
waiting for is moot: the artifacts cannot join to real fixtures at all, so no amount
of elapsed season time makes them useful. Folded into item 12, which is the same
root problem seen from the model side.
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
(evidence below). WP-10.3 (the actual remap) is still **not done** — see below.

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

**Why WP-10.3 (wiring this remap into `upcoming_match_feature_service.py`) is still not
done:** it is explicitly R4 under INV-14 ("remapping `_get_team_stats()` output onto
canonical feature names is a feature-schema change... even though no new feature is
added — the meaning bound to each name changes") — proposal-only, approval required,
never execute-then-ask. Confidence the semantics above are correct is now high (cited to
the live training artifact, not assumed), but R4 gates on *evidence quality*, not
*confidence* — the operator must still sign off, because it changes what every live
model actually sees and requires the D8b prefix fix to land atomically (see above) plus
a `feature_defaulted_ratio` before/after capture per the campaign's own GATE-10 §3.

**Blast radius:** every live prediction, matchup and DB-fixture paths alike (unchanged
until WP-10.3 ships).
**Cost:** now low for WP-10.3 itself — the semantics research (the expensive, blind-risk
part) is done. Remaining cost is the approval round-trip + the D8b atomic fix + the
re-certification/`feature_defaulted_ratio` proof GATE-10 requires.
**Impact:** predictions are directionally usable but running on a small fraction of
trained signal — unchanged by WP-10.1 alone, as designed.
**Priority:** high value; ready for a go/no-go decision, no longer blocked on research.

---

## 2. Settlement-join infrastructure built and tested, wired to nothing that runs

**Tier:** `NEXT` → **shipped 2026-08-05** — a real caller now exists; entry kept
(annotate, don't remove, matching item 1's precedent) because a residual limitation
and a related risk (item 5) are still open.
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

`get_settled_predictions()` (`backend/src/repositories/fixtures.py:113-206`) and
`walk_forward_validate()` (`backend/src/models/model_registry.py:311`) are both correct
and unit-tested (`backend/tests/test_settled_predictions_join.py`,
`test_model_registry_walk_forward.py`) but have **zero production callers** — grepped,
confirmed. Nothing in the live process transitions `Match.status` to `"finished"` with
real scores: the only code that does
(`DataIngestionService._update_match_score`, `backend/src/services/data_ingestion.py`)
is reachable only via a standalone CLI (`cli/start_ingestion.py`) or via
`ProductionOrchestrator.start()`, which itself has zero callers anywhere in the
codebase.

**Blast radius:** `/model-performance` and any accuracy/RPS surface — currently stubs
honestly (`503 bet_history_aggregation_not_yet_integrated`) rather than lying, per
earlier session notes; this entry just consolidates why.
**Cost:** needs a decision on where a periodic job can run on a single free-tier Render
dyno (no separate worker/cron service exists today) before it's worth wiring the join.
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

**Tier:** `NEXT` — trigger: once `settled_join_rate` is real and being watched (item 2
shipped 2026-08-05), an unexplained gap between total predictions and joinable
predictions needs this fix.
**Owner:** unassigned.
**Found:** 2026-08-05, while wiring the settlement join (item 2).

`create_prediction()` (`backend/src/api/endpoints/predictions.py:106-110`) synthesizes
`match_id = f"{home}_{away}_{timestamp}"` when the caller doesn't supply a real one.
`get_settled_predictions()` joins `MatchPredictionLog.match_id` to `Match.id` — a
synthetic value can never equal a real `Match.id`, so such prediction rows are
permanently unjoinable no matter how correct the settlement pipeline is.

**Blast radius:** `settled_join_rate` (item 2's SLI) and `/model-performance`'s
`settled_predictions` count — both will read low even once matches are settling
correctly, if a meaningful share of predictions were logged via this path.
**Cost:** small — requires either always passing a real `Match.id` at the call site
that reaches `create_prediction()`, or rejecting the write when one isn't available,
rather than silently minting an unjoinable key.
**Impact:** unknown until measured — not yet confirmed how much of live traffic hits
this path vs. the DB-listed-fixture path (which already passes a real `match_id`).
**Priority:** low today (no settled data exists yet to expose the gap); revisit the
moment item 2's telemetry is live against real matches.

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

**Tier:** `ARCH-DEBT` — needs an ADR; do not change fail-closed semantics casually.
**Owner:** unassigned.
**Found:** 2026-08-05, diagnosing a production outage (see the operator note below).

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

**Blast radius:** in production it converts a recoverable dependency outage into an
un-diagnosable crash loop. `render.yaml`'s `startCommand` is
`alembic upgrade head && uvicorn …`; when the import raises, the `&&` short-circuits,
uvicorn never starts, the container exits, Render restarts it, and the only public
signal is the platform's own HTML 502. The service being down is *correct* (it cannot
serve without its database) — being unable to say why is not.
**Cost:** medium. Convert to a lazily-initialised engine plus an explicit
`verify_database_connection()` called from `lifespan()` and from Alembic's `run_
migrations_online()`, keeping the fallback gate exactly where it is.
**Impact:** developer friction today; diagnosability during an incident.
**Priority:** medium — raise it if a second outage is misdiagnosed because of this.

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
**Still worth confirming, operator-only:** that `sabiscore_db_v2` is on a plan
that won't hit the same 30-day free-tier expiry (if it's also `plan: free`,
this will recur).

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
