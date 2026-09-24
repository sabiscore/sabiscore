# SabiScore — Production Executive Directive v8.0

### Resource-bounded quantitative platform: ingestion, serving, calibration, decision UX, agent orchestration

**Version:** 8.0 · **Date:** 2026-09-24 · **Baseline:** production `45e8a23` (backend and web agree)
**Relationship to v7.4:** supplements `docs/PRODUCTION_EXECUTIVE_DIRECTIVE.md` (v7.4). Every v7.4
invariant, operator gate and forbidden transition still applies. Where this document and v7.4
disagree, v7.4 wins until an operator amends it.
**Research branch this directive builds on:** `research/g18-market-residual-2026-09-24` (uncommitted
at time of writing — see §6 Phase 0).

---

## 0. Mandate, and what the evidence says today

The brief asks for a platform that finds market inefficiencies, shows +EV plays with fractional-Kelly
sizing, and keeps model probabilities sharper than the closing line. **That is the target, not the
current state.** Every number below was measured on 2026-09-24. Nothing here is carried forward.

| Fact | Value | Source |
| --- | --- | --- |
| Staking | `permitted: false`, `basis: NONE`, `UNVERIFIED`, `ACTIVE_FAIL_CLOSED` | live `GET /health` → `staking` |
| Served generation | `v5_phase7-20260922`, schema `apex_v1_68`, head `stacked_meta_model` | `backend/models/active_generation.json` |
| Live settled predictions | 88 (`/health` settlement); 80 in the `/model-performance` window | live endpoints |
| Live walk-forward RPS | 0.2326, bootstrap 95% CI [0.2038, 0.2667] | live `/health` → `settlement.walk_forward` |
| Live Brier (mean aggregation) | 0.2268 vs climatology 0.2206; **reliability 0.0433 > resolution 0.0397** | same |
| Live ECE (mean of classes) | **0.1658** against a policy ceiling of 0.03 | live `/api/v1/model-performance` |
| "CLV" diagnostic | n=35, mean +0.0056, positive rate 0.60 — **not closing-line value**, see §2.4 | same |
| Market benchmark, development folds | de-vigged opening 1X2, pooled RPS 0.19526 over 7,027 matches (2021/22–2024/25) | `backend/reports/research/g18-market-residual-development.json` |
| G18 market-residual research | **negative**: no candidate's pooled ΔRPS CI below zero; best R2 −0.00012 [−0.00029, +0.00007]; 2025/26 holdout left unread | same, protocol sha256 `57d17049…` |
| Item 142 calibration evidence | cross-fitted on 2024/25: stacked head without the served calibrator beats the served composition in 4/6 leagues, pooled ΔRPS −0.0077 [−0.0104, −0.0050]; the scale layer adds nothing | `backend/reports/research/item142-crossfit-selection-2425.md` |
| Promotion gate | `market_baseline` 0/6 (paired CI, item 62), `promotion_permitted: false` | `docs/DEBT.md` items 62, 64 |
| ESPN provider | `STALE`, last observation 2026-09-20T01:04Z (≈4.3 days) | live web `/api/health` |

**Read the live calibration numbers carefully.** The 88 settled rows are stamped with the bare suffix
`v5_phase7`, so they pool two generations. One of them is the superseded `-20260808`, which trained
on its own test season (item 81). The research branch separates the two (§6 Phase 0). Until it
lands, the live figures describe neither generation cleanly. They are not a verdict on
`-20260922`, and they are not evidence in its favour either.

### Three readiness tiers (use these words, and only these)

| Tier | Status 2026-09-24 | Blocking evidence |
| --- | --- | --- |
| `PLATFORM_READY` | **PARTIAL** | health and SHA parity are green and the backend had been up 9.4 h with no restart; but the memory headroom of the serving instance cannot be observed (§2.1), and ESPN is stale |
| `FORECAST_READY` | **NOT MET** | live ECE 0.166 against 0.03; live Brier is worse than climatology on a pooled, small sample |
| `ACTIONABLE_CERTIFIED` | **NOT MET** | 0/6 market baseline; G18 negative; permanent `MODEL_UNCERTAINTY_UNAVAILABLE` (item 42); `UNVERIFIED` |

Until `ACTIONABLE_CERTIFIED` is met, the correct output for every fixture is a no-action state
(§3.2). That is the product working as designed. It is not a defect to engineer around.

### Premises in the brief this directive corrects

| Premise | Correction | Evidence |
| --- | --- | --- |
| Node.js workers ingest real-time data | Real-time ingestion is Python, running inside the FastAPI process (fixture sync every 6 h, CLV capture every 5 min, settlement hourly). `apps/scraper` (Node/Crawlee) is batch-only, disabled in production, and scheduled twice weekly. | `backend/src/api/main.py:129-306`; `render.yaml` `SCRAPER_PRODUCTION_ENABLED: "false"`, schedule `0 3 * * 1,4` |
| 8 GB is the binding memory limit | For serving, the binding limit is the Render `free` instance with 1 uvicorn worker. The 8 GB machine binds only local training, tests and builds. | `render.yaml:6,10` |
| Data volume threatens 8 GB | The whole training corpus is about 11 MB of CSV (12,765 matches). Memory risk comes from process fan-out (`n_jobs=-1`) and from heavy jobs running concurrently, not from data size. | `backend/data/cache/fd_*.csv`; `train_on_real_matches.py:1458` |
| Model is sharper than the closing line | Measured answer today: no (table above). Treat this as a gate to pass (§2.4), not a premise. | — |
| "Obsidian Nocturne v2" design system | No such token set exists. The obsidian/mint-lime/cyan semantics live in `docs/SABISCORE_BRAND_IMPLEMENTATION.md`; §3.1 defines v2 as a semantic layer over the existing CSS variables. | `grep -ri nocturne` → no matches |

---

## 1. Resource-constrained data & feature engineering

### 1.1 Local 8 GB budget (Windows)

Measured locally (Windows, Python 3.14). The target is Linux, Python 3.11, so re-measure there before
relying on any of these:

| Component | RSS |
| --- | --- |
| Interpreter baseline | 41.6 MB |
| numpy + pandas + sklearn + xgboost + lightgbm imported | +135.2 MB |
| All six served artifacts loaded (the first unpickle includes +54.5 MB of one-time imports) | +92.8 MB |
| `import src.api.main` (whole app) | **455.5 MB total** |

Budget rule: **one heavy job at a time, 3 GB RSS ceiling per job including child processes.**

| Reservation | Budget |
| --- | --- |
| Windows + VS Code + tsserver (`maxTsServerMemory` ≤ 3072) | ~3.5 GB |
| One heavy job (training, full pytest, `next build`, HPO, bootstrap study) | ≤ 3.0 GB |
| Everything else (browser, Claude Code sessions, idle services) | ~1.5 GB |
| Docker Desktop | **never running alongside a heavy job.** Its VM reservation alone exceeds the heavy-job budget, and prior image builds already timed out (item 16). |

### 1.2 Work items — Python (training, backfills, research)

| # | Change | File | Acceptance |
| --- | --- | --- | --- |
| D1 | `ResourceGuard` context manager: a sampler thread polls `psutil.Process().memory_info().rss` plus `children(recursive=True)` every 0.5 s, records the peak, and terminates the job at the ceiling (`SABISCORE_MAX_RSS_MB`, default 3072) with a structured error. Stdlib + psutil only; psutil is already a runtime dependency (`monitoring.py`). | new `backend/scripts/_resource_guard.py` | A test allocating past a 200 MB ceiling is terminated and reports its peak |
| D2 | Cap training parallelism: `_instantiate(n_jobs=...)` reads `SABISCORE_MAX_JOBS` (default 2 locally, `-1` only when explicitly set). `n_jobs=-1` starts one loky worker per core, and each worker holds its own copy of the design matrix. | `train_on_real_matches.py:1458`; `enhanced_training.py:187,204` | Training manifest records the `n_jobs` actually used |
| D3 | Record `peak_rss_mb`, `runtime_s` and `n_jobs` in the training manifest and the experiment registry. These fields read `UNDECLARED` today and must be measured, never back-filled. | `src/models/training_manifest.py`; `reports/research/experiment_registry.yaml` | `validate_experiment_registry.py` passes; new runs carry measured values |
| D4 | Train leagues sequentially in one process, with `del` and `gc.collect()` between leagues, **or** one process per league. Pick one per run, and record which in the manifest. | `train_on_real_matches.py` | Peak RSS of a six-league run ≤ 3 GB, measured by D1 |
| D5 | Stream the database backfills: settlement and Elo replay read with `execution_options(yield_per=500)` instead of materialising full result sets. Elo already processes `limit=500` per pass; keep that bound. | `settlement_service.py`, `elo_state_service.py` | RSS flat across a full replay pass |
| D6 | Chunking **trigger**, not a mandate: when a single input file exceeds 200 MB, switch `read_csv` to `chunksize=` with `usecols` and downcast dtypes (float32 features, `category` team ids). Below that size, chunking adds complexity with no benefit; the current corpus is about 11 MB. | loaders | — |

### 1.3 Work items — Node (`apps/scraper`)

The crawler already runs at `maxConcurrency: 1` and `maxRequestsPerCrawl: 1` (`http.mjs:43-45`).
Its memory risk is an unbounded V8 heap and buffered snapshots, not concurrency.

| # | Change | Acceptance |
| --- | --- | --- |
| N1 | Worker env: `NODE_OPTIONS=--max-old-space-size=384` (the hard heap cap) and `CRAWLEE_MEMORY_MBYTES=512`. Per the Crawlee docs, the second only limits how far the AutoscaledPool scales; it does **not** cap the heap, so both are needed. | `Dockerfile.worker` / `render.yaml` env; the worker process cannot exceed its cap |
| N2 | `summarizeResults()` (moved into `storage.mjs` under P10) gains `resource: { peak_rss_mb, peak_heap_used_mb }`, sampled from `process.memoryUsage()` at each request boundary. | Every manifest carries measured peaks; `storage.test.mjs` covers the field |
| N3 | Verify that raw snapshots are written as streams (`fs.createWriteStream` / `pipeline`) and not buffered as whole strings. If they are buffered, change them. | Heap stays flat across a large snapshot |
| N4 | Keep the scraper's authority boundary unchanged: no probabilities, verdicts, EV or Kelly (CLAUDE.md). Memory work must not move computation into Node. | Unchanged zero-hit scan |

### 1.4 Six-league pipeline — historical vs real-time

| League | Development seasons in corpus | Served model | Constraint |
| --- | --- | --- | --- |
| EPL, LA_LIGA, SERIE_A, BUNDESLIGA, LIGUE_1 | 2019/20–2024/25 (+2025/26 holdout) | per-league `*_ensemble_v5_phase7.pkl` | — |
| EREDIVISIE | **only 2025/26** | pooled all-league model | Cannot enter development folds. It is judged only in a holdout confirmation, never used for selection. |
| UCL | — | none | Capped below `HIGH_CONVICTION` and has no model. The UI must say so, not render an empty card. |

**Historical path:** `fd_*.csv` → `load_matches` → point-in-time features (Elo replayed
chronologically, form strictly before kickoff) → season-chronological splits
(`temporal_split` in the manifest). Physically exclude the holdout season: never copy the file into
the loader's input (the G18 script does this, and aborts if a holdout row appears).

**Real-time path:** provider gateway (single lifespan `httpx.AsyncClient`) → `fixture_sync` →
`market_snapshots` (opening and closing) → projector → inference → `match_prediction_logs`.

**Point-in-time defects that block `FORECAST_READY` (found on the research branch):**

| # | Defect | Fix |
| --- | --- | --- |
| P1 | Market snapshot selection has no kickoff bound, so a post-kickoff price can feed a pre-match forecast. | Select `captured_at < kickoff_utc AND captured_at <= evaluation_at`; add a regression test with a post-kickoff snapshot present |
| P2 | Train/serve market mismatch: training uses opening B365-with-Pinnacle-fallback, proportionally de-vigged; serving uses whatever snapshot is newest. | Serving records which snapshot, bookmaker and timestamp it used (§2.4 C1). The feature contract documents the difference until training can reproduce serving |
| P3 | Placeholder market defaults (2.5 / 3.3 / 2.8) produced publishable forecasts. | **Fixed on branch:** `market_inputs_defaulted` now sets `is_synthetic`, so these forecasts are not published |
| P4 | `_resolve_is_apex` falls back to the legacy market block when the manifest cannot be read — item 141's failure mode, still live. | Fail closed: an unreadable manifest yields no inference, never a legacy vector |
| P5 | `_load_from_disk` loads unverified pickles for a league that has no manifest entry. | Refuse any artifact not hash-pinned in `active_generation.json` |

---

## 2. Model serving & the calibration loop

### 2.1 Serving architecture — keep it single-process

Six sklearn-family ensembles add about 40 MB of RSS once loaded (§1.1). A separate model server,
ONNX conversion or Redis model cache would add moving parts to save memory the models barely use.
**Keep in-process serving** and spend the effort where the memory actually goes: library imports and
concurrent background work.

| # | Change | File | Acceptance |
| --- | --- | --- | --- |
| S1 | **Make the real limit observable.** `/health` `resources` reports `psutil.virtual_memory()`, which is the *host* (91.6 GB available on 2026-09-24), not the instance. Report process RSS plus the cgroup's `memory.current` / `memory.max` (`/sys/fs/cgroup/`, cgroup v2; fall back to v1 paths), with `headroom_mb`. | `api/endpoints/monitoring.py:266,625` | `/health` shows the instance limit and current use; no host figures presented as instance figures |
| S2 | Measure the target: in `python:3.11-slim` on Linux, record RSS after `import src.api.main` and after the model cache warms, plus `python -X importtime` top-20 importers. | report under `backend/reports/infra/` | A dated number replaces the Windows estimate in §1.1 |
| S3 | **Heavy-job lane:** a single `asyncio.Semaphore(1)` shared by settlement's bootstrap, the calibration endpoint's cache miss and any future replay. They already run off the event loop via `asyncio.to_thread` (item 144); the lane stops two ~10,000-replicate jobs from overlapping and stacking their peak memory. | `performance.py`, `settlement_service.py` | Concurrent calls serialise; `/providers/health` latency is unaffected during a settlement pass |
| S4 | If S2 shows headroom under 100 MB: lazy-import SHAP and other explanation-only libraries at first use, not at startup. Do not drop anything from the serving path. | `models/explainer.py` and callers | RSS after startup drops by the measured amount |
| S5 | Land fail-closed artifact loading (P4, P5). | `models/prediction.py` | Tests: unreadable manifest → no inference; unlisted league → refused |

### 2.2 Served identity — every number attributable to exactly what served it

The research branch adds `served_identity(manifest) = "{generation}@{sha256[:16]}"` over
`generation, active_version, feature_schema_version, served_head, artifacts`. Certification fields are
excluded, so certifying a generation does not change its identity. The prediction log stamps it, and
every evidence reader scopes by it. Still to bind: training commit, dataset hash, calibrator hash,
uncertainty method, `evaluation_at`. `audit_release_identity.py` currently reports
`RELEASE_IDENTITY_INCOMPLETE`. **No calibration or CLV figure is valid across two served identities.**

### 2.3 Calibration — what is served, and who decides

The served composition is: base learners → 9 meta-features → temperature- or vector-scaled
softmax meta-model → sigmoid calibrator. That calibrator was fitted on the base-learner *average*,
not on the head it is applied to (item 142).

Cross-fitted evidence on 2024/25 (the holdout untouched):

| Candidate | Beats the served composition | Pooled ΔRPS |
| --- | --- | --- |
| C3 stacked head, no calibrator | 4/6 leagues | −0.0077 [−0.0104, −0.0050] |
| C4 stacked head + scale | 5/6 leagues | −0.0071 |

Changing what is served is a **Class C operator decision (item 142)**. This directive puts the
evidence in front of the operator and does not make the choice. Whatever is chosen ships as a new
generation through the promotion gate. It is never a hot swap of the live calibrator.

### 2.4 The continuous calibration loop

Principle: **production never refits itself from its own outcomes.** Online recalibration from
settled results is a feedback loop scored on its own training data. The loop below only *measures*.
Changes enter through a new generation, scored on data it never saw.

```
 capture ──► close ──► settle ──► measure ──► decide ──► (new generation) ──► promotion gate
 at forecast  closing   hourly    per served   pre-registered   trained offline,     v7.4 §32
 time         line      pass      identity     rule + operator  chronological split
```

| # | Stage | Change | Acceptance |
| --- | --- | --- | --- |
| C1 | Capture | Persist the recommendation-time market in the prediction log: `market_snapshot_id` (nullable FK to `market_snapshots`), bookmaker and captured timestamp, kickoff-bounded (P1). Alembic migration only. Today the log stores the model's probabilities but not the price available when they were published. | `alembic check` clean; the column is populated on new forecasts |
| C2 | Close | Existing `clv_capture_service` (`is_closing_line=True`, every 5 min). Also record `closing_captured_at − kickoff`. | Closing rows carry their capture lag |
| C3 | Measure: proper scores | Per served identity and per league: RPS, log loss, Brier decomposition, adaptive ECE, and **paired ΔRPS against the de-vigged closing market** on the same fixtures, with an ISO-week cluster bootstrap (the G18 instrument, reused). "Sharper than the close" means this CI lies entirely below zero. | Report exposed on `/api/v1/model-performance` alongside the existing fields |
| C4 | Measure: true CLV | For fixtures where a stake was **permitted**: `CLV = ln(o_taken / o_close)` for the recommended outcome, using C1's price. This is closing-line value in the betting sense. | Computed only where C1 exists; otherwise `skipped` with a reason |
| C5 | Relabel the current metric | `clv_service` computes `model_p[argmax] − close_p[argmax]`. Selecting the argmax biases this upward: a model equal to the market plus noise shows a positive mean. Rename the field to `model_close_gap_argmax` and describe it as a disagreement diagnostic, not CLV. **Do not delete it.** | UI and API no longer call it CLV; a test pins the new name |
| C6 | Decide | Evaluate at settled-count milestones **per served identity**: 200, 500, 1000. Each evaluation runs a pre-registered protocol (§4.3). No decision is taken between milestones. Drift monitoring (item 8) stays deferred until 1,000. | Milestone reports in `backend/reports/evaluation/` |

**Next market hypothesis (G18 v2, a new protocol, not a re-tune of v1).** v1 established that
Elo, form and a longshot correction add nothing measurable to the *opening* line. Any edge SabiScore
could have must come from information the market lacked *at the moment of comparison*, so v2 must
benchmark against the market snapshot at the forecast timestamp (C1), and use candidate features the
price could not yet reflect (confirmed lineups, late injuries). The corpus contains no point-in-time
lineup history, so v2 depends on **forward capture starting now**. Its earliest honest test date is
set by C6's first milestone, not by the calendar.

---

## 3. Quantitative UX (Next.js 15)

### 3.1 Obsidian Nocturne v2 — a semantic layer, not a new palette

Build v2 on the existing variables (`--surface-card: 222 35% 8%`, `--surface-elevated: 222 30% 11%`
in `app/globals.css`) and on the brand semantics already written down: obsidian field, mint-to-lime
signal, and cyan meaning **selected output, never confidence**.

| Token | Meaning | Rule |
| --- | --- | --- |
| `--signal-model` | model probability | always paired with a text value |
| `--signal-market-fair` | de-vigged market probability | — |
| `--signal-market-implied` | 1/odds including margin | rendered as a tick, never a filled mark |
| `--state-play` / `--state-pass` / `--state-withheld` | decision state | shape and text carry the state; colour is redundant (colour-blind safe) |
| `--risk-counter` | counter-case panel | muted amber; never the rose used for outages |

Charts use the installed `recharts@^2.15.4`, loaded with `next/dynamic({ ssr: false })` (the pattern
that took `/performance` from 232 kB to 127 kB). No new chart dependency.

### 3.2 Decision states — the backend decides, the UI projects

`apps/web` never computes EV, edge, Kelly or a verdict (CLAUDE.md). `EdgeDeltaBar` already documents
why: recomputing from `1/odds` produced a second, contradictory edge. The UI maps backend fields to
exactly three states:

| UI state | Condition (all from the backend payload) | Headline copy |
| --- | --- | --- |
| **PLAY** | `stake_permitted === true` AND verdict ∈ {`ACTIONABLE`, `HIGH_CONVICTION`} AND backend `expected_value > 0` AND `risk_guard` not tripped | "Qualifies · stake {k}% of bankroll" |
| **PASS** | evaluable (no critical gaps, `prediction_status === AVAILABLE`, generation certified) but EV ≤ 0 or the verdict is below `ACTIONABLE` | "No value at this price" |
| **WITHHELD** | any critical gap, non-`AVAILABLE` status, uncertified generation, missing market, or UCL above cap | "Not evaluable — {first critical reason}" |

PASS and WITHHELD must never be merged: "we looked and the price is wrong" is a different
statement from "we cannot tell". **On 2026-09-24 every fixture is WITHHELD** (uncertified
generation, staking `permitted: false`). Anything else would be a fabrication bug. `SPECULATIVE` is
never PLAY; it belongs on the watchlist only (CLAUDE.md).

### 3.3 The quantities, exactly

For outcome *k* with decimal price `o_k`, the backend supplies each value and the UI displays it
unchanged:

```
implied_k   = 1 / o_k                       (includes the bookmaker margin)
overround   = Σ_k 1 / o_k
fair_k      = implied_k / overround          (proportional de-vig; Shin as sensitivity)
edge_k      = p_k − fair_k                   (model vs fair market)
EV_k        = p_k · o_k − 1                  (per unit staked, against the price actually offered)
break_even  = implied_k                      (EV_k > 0  ⇔  p_k > 1/o_k)
kelly*_k    = (p_k · o_k − 1) / (o_k − 1)
stake_k     = min(0.25 · kelly*_k, league kelly_cap, 0.05)   if stake_permitted else 0
```

**Display rule:** a positive `edge_k` does not imply a positive `EV_k`, because edge is measured
against the fair price while EV is measured against the margin-inclusive price actually offered.
The card shows both, labelled, and the decision state follows EV only. Label EV as "expected return
per unit staked", never as profit or ROI without the word *expected*.

### 3.4 Component structure

```
app/match/[id]/page.tsx (RSC, force-dynamic, Cache-Control: no-store via proxy)
└─ <DecisionCard data={fullAnalysis}>            server component, no client math
   ├─ <DecisionHeader state verdict reason />     PLAY | PASS | WITHHELD, text + icon + shape
   ├─ <ProbabilityDumbbell outcomes />             client (dynamic): per outcome, model dot,
   │                                               fair-market dot, implied tick; interval
   │                                               whiskers only when the backend sends one
   ├─ <ValueBlock ev kelly stake cap />            renders "—" plus reason when not permitted
   ├─ <CounterCase />                              ALWAYS rendered, including for PLAY (§3.5)
   └─ <EvidencePassport />                         existing; provenance, freshness, gaps
```

Reuse the existing pieces (`OddsEdgeCard`, `EdgeDeltaBar`, `EvidenceStatusCard`,
`KellyTooltip`/`EdgeTooltip`, `StakingOverrideNotice`) rather than rewriting them. `DecisionCard`
composes them.

### 3.5 Counter-case — why this might fail

Always rendered, always from backend fields, in this order:

1. **Loss probability** `1 − p_k`, and the break-even probability `1/o_k`, so the reader sees how
   thin the margin is.
2. **This model's live calibration for this league:** ECE and n under the current served identity
   (C3). If n < 200: "too few settled forecasts to judge calibration".
3. **Uncertainty state:** the interval if one exists; otherwise "model uncertainty unavailable"
   (item 42), stated plainly.
4. **Backend `known_risks`, `caveats`, and critical and advisory gaps**, via
   `describeEvidenceCode()`. The web never writes its own risks.
5. **Market context:** how the line moved from opening to now, when snapshots exist.

The copy contract (`copy-contract.test.ts`) and the CI copy scan apply unchanged.

### 3.6 Guards to add

| Guard | Pattern |
| --- | --- |
| `apps/web/src/lib/no-client-ev-contract.test.ts` | Repo scan in the style of `copy-contract.test.ts`: no `* odds - 1`, `1 / odds`, or Kelly arithmetic outside test files. Watch it fail on an injected line before trusting it. |
| `decision-state.test.ts` | Pure mapping from payload to PLAY/PASS/WITHHELD. Every WITHHELD reason covered; PASS and WITHHELD never collapse into one state. |
| Counter-case presence | Rendered for PLAY; its first line is the loss probability. |

---

## 4. NEXUS agent orchestration

### 4.1 The boundary

**LLM agents never run inside the production calibration, settlement, CLV or backfill loops.** Those
are deterministic, idempotent, scheduled code in `backend/src/api/main.py`. Agents operate the
*research and engineering* loop around them: they write protocols, run bounded jobs, check outputs
against pre-registered rules, and draft decisions for the operator.

### 4.2 Supervisor–worker hierarchy (maps to `.claude/agents/`)

```
Supervisor (lead session, NEXUS routing, owns the decision rule)
├─ Planner      = architect      read-only; writes protocol.json, freezes and hashes it
├─ Generator    = implementer    writes code and tests; runs light commands only
├─ Runner       = the supervisor itself (Bash, run_in_background) — heavy jobs are never delegated
└─ Evaluator    = qa-verifier    applies the frozen decision rule mechanically; runs tests;
                                 never edits the protocol or the code under test
   (debugger    only on the evaluator's escalation)
```

| Limit | Value | Why |
| --- | --- | --- |
| Heavy jobs at once | **1**, under `ResourceGuard` (D1) | the 3 GB budget in §1.1 |
| Subagents at once | ≤ 2, and **0 while a heavy job runs** | each session is a separate process; measure it, don't assume its size |
| Who runs heavy jobs | the supervisor only | a subagent that crashes loses its job and its memory accounting |

### 4.3 Handoff protocol — files, hashes, resumable

Each experiment lives in `backend/reports/research/<exp-id>/`:

| File | Written by | Contents |
| --- | --- | --- |
| `protocol.json` + its sha256 | Planner | hypothesis, data, candidates, folds, metrics, decision rule, `no_retuning` clause; frozen **before** any run (the G18 v1 protocol is the template) |
| `run_manifest.json` | Runner | git SHA, dataset hash, protocol sha, `peak_rss_mb`, `runtime_s`, `n_jobs`, seed |
| `results.json` / `results.md` | Runner | numbers only, no interpretation |
| `decision.md` | Evaluator | the rule applied to results; PROMISING / NEGATIVE / INCONCLUSIVE; operator questions |

Rules:

- **Idempotent resume.** A runner that finds `results.json` carrying the same protocol sha and
  dataset hash does not re-run. Earlier this session, agents stopped mid-task on rate limits and on a
  process exit; with this rule a restart costs nothing.
- **No shared in-memory state** between agents. Everything that crosses a boundary is a file with a
  hash.
- **Registration:** every experiment gets a row in `reports/research/experiment_registry.yaml`
  (schema §38 of the data directive), including negative results. A negative result is a
  deliverable, not a failure to report.
- **Holdout discipline:** the holdout season is physically absent from the runner's inputs until the
  decision rule, applied to development folds, selects a candidate. G18 v1 never opened 2025/26.

### 4.4 The two automations

| Automation | Trigger | Steps | Output |
| --- | --- | --- | --- |
| Calibration cycle | settled count for the current served identity crosses 200 / 500 / 1000 (read from `/health`) | Planner freezes the C3/C4 protocol → Runner scores → Evaluator applies the rule | milestone report + operator decision request if any gate changes state |
| Backfill verification | after any deploy touching Elo, settlement or market capture | probe the `/health` and `/metrics` counters (Elo rows, settled total, `market.lifecycle.*`); confirm they rise, and that the rise comes from real data rather than data being silently discarded | a verification note, or a `docs/DEBT.md` entry |

A cloud routine (`schedule` skill) may run the milestone probe weekly against live endpoints. It
cannot reach the local machine, so it only reports and never trains.

---

## 5. Out of scope, deliberately

- A model server, ONNX export or GPU path: the models are about 40 MB (§2.1).
- Chunked ingestion of the current 11 MB corpus (D6 sets the trigger instead).
- Online or self-refitting calibration (§2.4).
- Any UI state reading "Play" without a backend `stake_permitted: true`.
- Loosening a certification threshold after observing a result (v7.4, APEX §23).
- Enabling staking, changing `certification_state`, or resolving item 142. All three are operator
  decisions.

---

## 6. Execution order and exit gates

| Phase | Work | Exit gate |
| --- | --- | --- |
| **0 — Land what is measured** | Commit the research branch: served identity; synthetic-market gate; G18 v1 protocol and negative result; item-142 cross-fit evidence. File `docs/DEBT.md` entries for P1, P2, P4, P5, S1, C5 and the invalid `market_residual_superiority.md`; banner that report as invalid. Full backend suite; mypy against the Linux-CI ceiling (784, about +9 over local); open a PR. | CI green on the PR; the operator approves the merge |
| **1 — See the real limit** | S1, S2, S3; D1, D2, D3; N1, N2 | `/health` reports instance RSS and limit; a dated Linux measurement exists |
| **2 — Evidence plumbing** | P1, P4, P5 (fail closed), C1, C2, C5, then C3/C4 on the endpoint | Paired ΔRPS vs the close is reported per served identity; nothing labelled CLV that is not CLV |
| **3 — Decision UX** | §3 tokens, `DecisionCard`, `ProbabilityDumbbell`, `CounterCase`, guards from §3.6 | All fixtures render WITHHELD today; lint, typecheck, Vitest, production build and Playwright desktop + mobile pass |
| **4 — Research cycle** | Operator decides item 142; item 50 Track A (forecast-error model, served-path parity); G18 v2 protocol frozen, forward lineup capture running | First C6 milestone (200 settled under one served identity) evaluated under a frozen protocol |

### Operator decisions required (none can be made by an agent)

1. **Item 142:** which composition a future generation serves (evidence in §2.3).
2. **C1 migration:** approval to add the recommendation-time market columns.
3. **G18 v2:** approval of the forward-capture scope (which providers, what quota).
4. **Merge of Phase 0.**

---

## 7. Standard of evidence for every completed item

Report each item as **CLAIM / EVIDENCE / FILE / COMMAND / RESULT / FAILURE MODE / CONFIDENCE /
BLOCKER**. A guard counts only after it has been watched failing on an injected regression, in the
configuration CI runs. A number is reported only from a fresh measurement, with its date and source.
"Production ready", "accurate", "market beating" and "certified" appear only when the corresponding
gate in §0 has passed.
