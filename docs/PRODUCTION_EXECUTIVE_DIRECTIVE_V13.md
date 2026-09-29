# SabiScore — Production Executive Directive V13.0

**Author**: Multi-Agent Engineering Council (Architecture, Quantitative Modeling, Frontend Systems, Orchestration)  
**Date**: 2026-09-29  
**Status**: ACTIVE / MANDATORY PRODUCTION DIRECTIVE  
**Supersedes**: Directive V12.0 (`docs/PRODUCTION_EXECUTIVE_DIRECTIVE_V12.md`) and all predecessor directives.  
**Ground Truth Authorities**: `docs/DEBT.md` (Items 1–163), `backend/src/api/main.py`, `backend/models/active_generation.json`, `apps/web/src/`, `NEXUS.md`, `AGENTS.md`.

---

## Executive Summary & Core Mandate

This directive establishes the authoritative operational, quantitative, and architectural governance for the SabiScore platform. SabiScore is a football intelligence and predictive modeling engine operating under a strict positive expected value (+EV) and capital preservation philosophy. 

All systems, agents, and engineers must strictly adhere to four non-negotiable architectural realities:
1. **Physical Resource Boundaries**: The production backend operates in a **512 MB cgroup v2 Linux container** on Render's free tier (`working_set` = 337–442 MB, leaving 69–174 MB operational headroom). Developer workstations and CI runners operate under an **8,192 MB (8 GB) local memory budget**, where heavy execution (training, full test suites, production builds) is serialized behind a single-process 3.0 GB ceiling enforced by `ResourceGuard`.
2. **In-Process Python Ingestion**: Real-time acquisition is driven entirely by asynchronous Python lifespan loops in `backend/src/api/main.py`. The Node.js crawler in `apps/scraper/` is exclusively an offline, batch-oriented data acquisition tool, currently deactivated (`SCRAPER_PRODUCTION_ENABLED="false"`) and constrained by `--max-old-space-size=384`.
3. **Rigorous Model Calibration & Market Superiority**: Predictions for the 6 canonical domestic leagues (EPL, La Liga, Bundesliga, Serie A, Ligue 1, Eredivisie) are served by `PredictionEngine` using stacked ensemble models (Random Forest, XGBoost, LightGBM, and Logistic Regression meta-models) consuming only 11 MB of disk storage. Model sharpness is evaluated against Pinnacle closing lines via the pre-registered, frozen C6 Protocol using paired $\Delta RPS$ with ISO-week cluster bootstrapping (10,000 replicates, $\alpha = 0.05/3 = 0.016667$) at sample milestones of 200, 500, and 1,000 settled forecasts.
4. **Deterministic UX & Zero-Fabrication Philosophy**: The Next.js 15.5.6 + React 18.3.1 frontend is strictly a projection layer. The browser is mathematically prohibited from computing odds arithmetic, implied probabilities, Expected Value, or Kelly stake sizing (`no-client-ev-contract.test.ts`). Every forecast must display the true vs. fair vs. implied probability dumbbell, a distinct tri-state verdict (`PLAY`, `PASS`, or `WITHHELD`), and a mandatory counter-case panel ("Why this might fail") disclosing loss probability ($1 - p_k$), price movement, uncertainty bounds, and non-blocking advisory gaps.

---

# Section 1: Resource-Constrained Data & Architecture (Architecture & Memory Constraints)

### 1.1 Ingestion Reality: Python Asyncio vs. Dormant Node.js Scraper

A fundamental misconception addressed in `docs/DEBT.md` (Item 18, 160) is that Node.js workers ingest real-time production data. In SabiScore, **no Node.js worker or crawler runs in the live ingestion loop**. 

Production ingestion is executed entirely in-process by the FastAPI application runtime (`backend/src/api/main.py`) via async lifespan background tasks initialized during server startup (lines 250–350):

```
FastAPI Application Lifespan (Python 3.11, Single Uvicorn Worker)
│
├── _background_fixture_sync() ────────── Every 21,600s (6 Hours)
│   ├── [Boot Tick Only] run_historical_backfill() (Offline CSV parsing)
│   └── run_fixture_sync() (football-data.org, 14-day lookahead, 50-cap)
│       └── Guarded by Redis lease lock: "sabiscore:job:fixture_sync:lease" (TTL 600s)
│
├── _background_clv_capture() ─────────── Every 300s (5 Minutes)
│   ├── run_clv_capture_pass() (The Odds API, Pinnacle closing line, t <= 10m to kickoff)
│   └── run_prediction_capture_pass() (Pre-kickoff predictions in [now+15m, now+3h])
│
├── _background_settlement_sync() ──────── Every 3,600s (1 Hour)
│   ├── run_settlement_pass() (football-data.org match scores, Brier/RPS scoring)
│   └── run_provider_evidence_retention() (Prunes evidence tables to newest 128 rows)
│
└── _background_notification_dispatch() ── Every 300s (Advisory kickoff/swing alerts)
```

#### Network & Concurrency Invariants
- **Lifespan HTTP Client**: All provider egress traffic shares a single application-lifespan `httpx.AsyncClient` with strictly configured connection pooling:
  $$\text{Limits}(\text{max\_connections} = 20, \, \text{max\_keepalive\_connections} = 10), \quad \text{timeout} = 8.0\text{s}$$
- **Distributed Lease Locking**: During rolling deployments on Render, two container instances temporarily overlap. To prevent concurrent executions from double-billing paid API quotas (The Odds API, football-data.org) or triggering HTTP 429 rate limits, `fixture_sync_service.py` acquires an atomic distributed lease key in Redis (`sabiscore:job:fixture_sync:lease`, TTL 600s) using a Lua script before initiating synchronization.

---

### 1.2 Mathematical Allocation of 8GB Local Workstation Memory

Local engineering environments (Windows 11 / Linux developer workstations, CI runners) are strictly budgeted within an **8,192 MB (8.0 GB)** physical RAM ceiling. Developers must run local databases, backend services, web applications, and language servers without inducing OS page swapping or out-of-memory thrashing.

#### Local Workstation Memory Budget Table (8,192 MB Total)

| Subsystem / Process | Target Allocation | Peak Ceiling | Accounting & Operational Rules |
| :--- | :---: | :---: | :--- |
| **Host OS & Desktop Environment** | **3,500 MB** | 3,800 MB | Windows 11 / Linux desktop manager, kernel, background services, shell terminals, VS Code, and `tsserver` (`typescript.tsserver.maxTsServerMemory <= 3072`). |
| **Local PostgreSQL 16** | **350 MB** | 512 MB | Native or lightweight container: `shared_buffers = 128MB`, `work_mem = 4MB`, `max_connections = 50`. |
| **Local Redis 7** | **150 MB** | 256 MB | In-memory key-value store: `--maxmemory 256mb`, `--maxmemory-policy allkeys-lru`. |
| **FastAPI Backend Runtime** | **455 MB** | 650 MB | Python 3.11 runtime (42 MB) + Scientific ML stack (135 MB) + 6 unpickled league ensembles (93 MB heap) + DB/Redis connection pools (15 MB). |
| **Next.js 15 Web Application** | **350 MB** | 600 MB | Node.js production runner (`NODE_ENV=production next start`). For `next dev`, V8 heap is capped at 1,024 MB. |
| **Idle System Slack & Browser Tabs** | **377 MB** | 500 MB | Web browser inspecting local endpoints, Git index, and OS file cache. |
| **Dedicated Heavy Job Reservation** | **3,000 MB** | **3,072 MB** | **Strictly reserved for exactly ONE active heavy job** (Model training, `pytest` suite, `next build`, or bootstrap evaluation). |
| **TOTAL LOCAL ALLOCATION** | **8,182 MB** | **8,192 MB** | **Completely accounted within 8,192 MB physical boundary.** |

#### Enforcing the 3.0 GB Heavy Job Ceiling via `ResourceGuard`
In `backend/scripts/_resource_guard.py`, SabiScore implements an active memory watchdog enforced via Python context management:
- A background polling thread samples total process resident memory plus all child processes recursively (`_tree_rss_mb()`) every 0.5 seconds:
  $$\text{RSS}_{\text{tree}} = \text{RSS}_{\text{parent}} + \sum_{k} \text{RSS}_{\text{child}_k}$$
- The ceiling is pinned by `SABISCORE_MAX_RSS_MB` (default: **3,072 MB = 3.0 GB**).
- If $\text{RSS}_{\text{tree}} > 3,072\text{ MB}$, the watchdog immediately executes:
  1. Recursive termination (`SIGKILL`) of all spawned worker processes (e.g. loky/joblib workers).
  2. Emits structured diagnostic JSON to `stderr`:
     `{"error": "rss_ceiling_exceeded", "peak_rss_mb": ..., "rss_ceiling_mb": 3072.0}`
  3. Halts the process abruptly via `os._exit(137)` to protect the host operating system from swap lockup.
- **Parallelism Clamping (`SABISCORE_MAX_JOBS`)**: Scikit-learn defaults to `n_jobs=-1`, which spawns one worker process per CPU core, duplicating memory. In `enhanced_training.py` (lines 187, 204), `n_jobs` is clamped to `SABISCORE_MAX_JOBS` (default: **2** locally).
- **Sequential League Training (Directive D4)**: Training across the 6 leagues executes sequentially with explicit `del model` and `gc.collect()` between leagues, guaranteeing peak RSS remains under 3.0 GB.
- **Docker Desktop Prohibition**: Docker Desktop's WSL2 VM reservation consumes 2.5–4.0 GB of RAM. Running Docker Desktop concurrently with heavy model training or `next build` violates the 8 GB budget. Heavy training must execute natively in the local Python virtual environment.

---

### 1.3 Mathematical Allocation of 512MB Production Cgroup Container Memory

In production on Render's free tier, the backend web service runs inside a Linux container governed by **cgroup v2** with a hard physical limit:
$$\text{cgroup\_limit} = 512\text{ MB} = 536,870,912\text{ bytes}$$

#### Cgroup v2 Kernel Accounting & Working Set Mechanics
Linux cgroup v2 tracks container memory in `/sys/fs/cgroup/memory.current` and `/sys/fs/cgroup/memory.stat`. In `backend/src/core/instance_memory.py` (lines 65–100), SabiScore parses these exact kernel files:

$$\text{cgroup\_current} = \text{anon} + \text{file} + \text{kernel}$$
$$\text{working\_set} = \max(0, \, \text{memory.current} - \text{inactive\_file}) = \text{anon} + \text{active\_file} + \text{kernel}$$
$$\text{headroom} = \text{cgroup\_limit} - \text{working\_set}$$

#### The Crucial Empirical Discovery from DEBT Item 152 & 163
Raw `cgroup_current` includes reclaimable OS page cache (`inactive_file`). Under steady-state operations, dynamic shared library reads cause `cgroup_current` to climb to 480–507 MB out of 512 MB. However, when anonymous memory expands, the Linux kernel reclaims inactive file pages instantaneously without terminating the process. 
Judging instance health against raw `cgroup_current` creates false alarms. SabiScore computes health and headroom strictly against **working set**.

#### Production Container Memory Breakdown Table (Python 3.11.9 on Render)

| Memory Layer | Allocator / Component | Typical Size | Cumulative Total | Kernel Accounting Category |
| :--- | :--- | :---: | :---: | :--- |
| **Layer 0** | Linux Kernel & Process Page Tables | 15 MB | 15 MB | `kernel` |
| **Layer 1** | Python 3.11 Base Runtime | 42 MB | 57 MB | `anon` (process heap) |
| **Layer 2** | Web Framework (FastAPI, Uvicorn, Pydantic v2, SQLAlchemy) | 80 MB | 137 MB | `anon` |
| **Layer 3** | Core Scientific ML Stack (NumPy, SciPy, Pandas, Scikit-Learn, XGBoost, LightGBM) | 135 MB | 272 MB | `anon` |
| **Layer 4** | 6 Unpickled League Ensemble Models (`PredictionEngine`) | 55 MB | 327 MB | `anon` (resident object graph) |
| **Layer 5** | Database & Redis Client Connection Pools (SQLAlchemy + Redis) | 12 MB | 339 MB | `anon` |
| **Layer 6** | Active Mapped File Cache (Shared `.so` libs: `libxgboost.so`, `libgomp.so`, Python bytecode) | 28 MB | **367 MB** | `active_file` (mmapped pages) |
| **WORKING SET**| **Typical Baseline Container Working Set** | — | **~367 MB** | **`working_set`** |
| **HEADROOM** | **Operational Safety Headroom to Cgroup Ceiling** | **145 MB** | **512 MB** | **`headroom_mb`** |
| **Layer 7** | Inactive File Page Cache (Reclaimed automatically by kernel) | ~30–100 MB | Overlaps headroom | `inactive_file` |

#### Live Telemetry Ranges Observed in Production
Across `docs/DEBT.md` (Items 152, 159, 160, 163):
- **Process RSS**: 325 MB – 400 MB
- **Anonymous Memory (`cgroup_anon_mb`)**: 289 MB – 304 MB
- **Active File Cache (`cgroup_active_file_mb`)**: 14 MB – 117 MB
- **Working Set (`cgroup_working_set_mb`)**: 327 MB – 442 MB
- **Measured Operational Headroom (`headroom_mb`)**: 69 MB – 174 MB
- **Degraded Status Threshold**: Triggered when headroom is less than 15% of 512 MB ($512 \times 0.15 = 76.8\text{ MB} \approx 77\text{ MB}$).

#### Architectural Protections for the 512 MB Container Limit
1. **Single-Process Serving**: Stacking a separate model server (Triton/TorchServe) or running multiple Uvicorn workers (`--workers 2`) would duplicate the ~300 MB anonymous heap, causing an immediate container OOM (exit code 137). Serving is strictly single-process (`uvicorn --workers 1`).
2. **Heavy Job Mutual Exclusion (`core.heavy_jobs.run_heavy`)**: 10,000-replicate bootstraps and settlement scoring passes are offloaded from the event loop via `asyncio.to_thread` and serialized behind a single `threading.Lock()` lane, eliminating parallel bootstrap allocation spikes.
3. **Lazy SDK Loading**: Bulky cloud SDKs like `boto3` consume ~20 MB of resident memory at import. In `backend/src/core/model_fetcher.py`, `boto3` is loaded lazily inside the artifact download path only, verified by `test_boto3_is_not_imported_at_startup`.
4. **Connection Pool Bounds**: In `backend/src/core/config.py`:
   - `database_pool_size = 20`, `database_max_overflow = 30`
   - `redis_max_connections = 50`
   During Render rolling deploys, two container instances overlap. Total DB connections are bounded to $2 \times 50 = 100$, well within PostgreSQL's default `max_connections = 200`.

---

### 1.4 Node.js Worker & Scraper Memory Profiling

The scraper in `apps/scraper/` is packaged via `Dockerfile.worker` and scheduled as a bi-weekly cron job (`"0 3 * * 1,4"` in `render.yaml`). It is strictly gated by `SCRAPER_PRODUCTION_ENABLED="false"`. If enabled by operator approval (OG-04), it must adhere to strict profiling and execution constraints:

#### Mandatory Memory Configuration Flags
```yaml
# render.yaml lines 221-226
- key: NODE_OPTIONS
  value: "--max-old-space-size=384 --heapsnapshot-near-heap-limit=1"
- key: CRAWLEE_MEMORY_MBYTES
  value: "512"
```

#### Rationale for Configuration
1. `CRAWLEE_MEMORY_MBYTES=512`: Instructs Crawlee's `AutoscaledPool` of the host container limit so it can throttle internal request queues. Crawlee does not enforce V8 heap limits.
2. `--max-old-space-size=384`: Hard-caps the V8 JavaScript heap at 384 MB. This guarantees $512\text{ MB} - 384\text{ MB} = 128\text{ MB}$ of container headroom for native C++ bindings, libuv thread pools, OpenSSL buffers, and OS page cache. Without this flag, 64-bit Node.js defaults to a 1.4 GB heap, causing an instant cgroup SIGKILL.
3. `--heapsnapshot-near-heap-limit=1`: Directs V8 to write an emergency heap snapshot file to disk immediately prior to an out-of-memory crash, enabling offline post-mortem analysis in Chrome DevTools.
4. **Single Concurrency & Zero Session Pool**: In `apps/scraper/src/http.mjs` (lines 43–56), `PublicHttpClient` constrains Crawlee to:
   - `minConcurrency: 1`, `maxConcurrency: 1`, `maxRequestsPerCrawl: 1`
   - `sameDomainDelaySecs: 3`, `maxRequestsPerMinute: 6`, `maxRequestRetries: 2`
   - `useSessionPool: false` (eliminates session pool memory overhead)
5. **In-Process Request Boundary Sampling (`sampleHeap`)**: In `apps/scraper/src/storage.mjs` (lines 389–425), `sampleHeap()` samples `process.memoryUsage().heapUsed` across request lifecycle hooks. Every generated manifest records measured `peak_rss_mb` and `peak_heap_used_mb`.
6. **Sampling Heap Profiles**: Prior to scheduling any new crawl source, operators must execute `node --heap-prof src/cli.mjs scrape` to generate a `.heapprofile` verifying zero heap growth across crawl iterations.

---

### 1.5 Data Chunking and Streaming Architecture

#### The 200 MB File Chunking Trigger Rule (Directive D6 & DEBT Item 88)
A recurring anti-pattern is mandating complex chunked streaming for tiny datasets. SabiScore's entire 6-league historical training corpus (`backend/data/cache/fd_*.csv`) comprises 36 CSV files totaling **10.9 MB on disk** (12,765 matches across seasons 2019/20 through 2024/25). Peak traced RAM during evaluation is under 1.0 MB (0.617 MB).

In `docs/DEBT.md` (Item 88), a proposal to chunk the walk-forward evaluation pipeline was officially rejected as `NOT_JUSTIFIED`. Chunking adds generator complexity and boundary bugs without saving meaningful memory on an 11 MB corpus.

**The Directive Rule**:
- **Chunking is a trigger, not a universal mandate.**
- If an individual dataset file exceeds **200 MB**, loaders must switch `pandas.read_csv` to `chunksize=...` with explicit `usecols` and downcasted types (`float32` for features, `category` for team identifiers).
- Datasets below 200 MB must be loaded in a single vector operation.

#### Database Streaming (Directive D5)
When querying historical match archives or Elo state histories, SQLAlchemy async streaming must use:
```python
query = select(Match).execution_options(yield_per=500)
async for partition in (await session.stream(query)).partitions():
    for match in partition:
        process_match(match)
```
This bounds ORM identity map resident memory to 500 instances at a time.

#### File Streaming (Directive N3)
In `apps/scraper/src/storage.mjs`, all raw snapshots and manifests are written atomically using streaming buffers and temporary file renames (`atomicWrite`), ensuring strings are never concatenated unboundedly in V8 heap memory.

---

### 1.6 The 6 Canonical Target Leagues and UCL Structural Cap

SabiScore predicts and models exactly **6 domestic leagues**. In `backend/models/active_generation.json` and `backend/src/services/historical_backfill_service.py` (lines 59–66), the canonical league metadata and model artifacts are pinned:

| # | Canonical League ID | Country | Division Code | League Name (`football-data.org`) | Active Model Artifact |
| :-: | :--- | :--- | :-: | :--- | :--- |
| **1** | `EPL` | England | `E0` | Premier League | `epl_ensemble_v5_phase7.pkl` |
| **2** | `LA_LIGA` | Spain | `SP1` | Primera Division | `la_liga_ensemble_v5_phase7.pkl` |
| **3** | `BUNDESLIGA` | Germany | `D1` | Bundesliga | `bundesliga_ensemble_v5_phase7.pkl` |
| **4** | `SERIE_A` | Italy | `I1` | Serie A | `serie_a_ensemble_v5_phase7.pkl` |
| **5** | `LIGUE_1` | France | `F1` | Ligue 1 | `ligue_1_ensemble_v5_phase7.pkl` |
| **6** | `EREDIVISIE` | Netherlands | `N1` | Eredivisie | `eredivisie_ensemble_v5_phase7.pkl` |

#### The Structural Policy for UCL (UEFA Champions League)
- UEFA Champions League fixtures are synchronized into the database via `fixture_sync_service.py` under competition code `CL`.
- **Zero machine learning artifacts exist for UCL** in `active_generation.json`.
- Because UCL represents cross-league knockout competition with disparate domestic strengths, variable rotation, and small historical cross-league sample sizes:
  1. UCL is **structurally capped at `ACTIONABLE`**; reaching `HIGH_CONVICTION` is prohibited (`betting_intelligence.py:527`).
  2. Public model prediction capture and betting verdict generation for UCL are withheld until a dedicated, certified cross-league model and calibration policy are trained, validated, and promoted (`models/AGENTS.md:17`).

---

# Section 2: Model Serving & Calibration Loop

### 2.1 Calibrated Ensemble Deployment in FastAPI

Model inference in SabiScore is centralized in `backend/src/models/prediction.py` (`PredictionEngine`), managed through `active_generation.py`, and served to API routes.

#### Serving Architecture & Artifact Footprint
- The 6 league ensemble pickles total **11 MB on disk** (~1.8 MB per league).
- Loaded once into memory at boot via `PredictionEngine.prime_cache()`, consuming ~55 MB of resident heap across all 6 leagues.
- Base learners within each league ensemble:
  - `RandomForestClassifier` (`n_estimators=300, max_depth=12`)
  - `XGBClassifier` (`n_estimators=250, max_depth=7, tree_method="hist"`)
  - `LGBMClassifier` (`n_estimators=250, max_depth=7`)
- Inference pipeline for 68-dimensional canonical APEX feature vector $\mathbf{x} \in \mathbb{R}^{68}$ (`apex_v1_68`):
  1. Base learners predict individual 1X2 probability triples: $\mathbf{p}_{\text{rf}}, \mathbf{p}_{\text{xgb}}, \mathbf{p}_{\text{lgbm}} \in \Delta^2$.
  2. Stacking meta-features: $\mathbf{z} = [\mathbf{p}_{\text{rf}}, \mathbf{p}_{\text{xgb}}, \mathbf{p}_{\text{lgbm}}] \in \mathbb{R}^9$.
  3. Meta-Model: Temperature-Scaled / Vector-Scaled / Multinomial Logistic Regression produces ensemble probability $\mathbf{p}_{\text{meta}}$.
  4. Post-Hoc Calibrator (`FittedCalibrator`): Platt Sigmoid or Isotonic mapping.
  5. Optional Bivariate Poisson Draw Overlay: Blends draw probability with Skellam distribution.
  6. Simplex validation: Verifies $\sum_{k=0}^2 p_k = 1.0 \pm 10^{-6}$.

#### Closed-Form Platt Scaling (Resolution of DEBT Item 133)
In `docs/DEBT.md` (Item 133), scikit-learn version drift between development (Python 3.14 / sklearn 1.8) and production Render (Python 3.11 / sklearn 1.3.2) caused unpickled `LogisticRegression` objects to crash with `AttributeError: 'LogisticRegression' object has no attribute 'multi_class'` inside `predict_proba`. This previously forced all 6 leagues into uncalibrated raw serving (ECE 10.51%).

To achieve permanent stability across Python/scikit-learn runtime versions, `backend/src/models/calibration.py` (lines 209–249) implements **direct closed-form sigmoid arithmetic**:
$$\text{logit} = \text{clip}\left(w \cdot p + b, \, -30.0, \, 30.0\right)$$
$$P(y = 1 \mid p) = \sigma(\text{logit}) = \frac{1}{1 + e^{-\text{logit}}}$$
Where $w$ and $b$ are extracted as raw NumPy floats from `calibrator.coef_[0]` and `calibrator.intercept_[0]`.

#### Resolution Path for DEBT Item 142 (Model Selection Discrepancy)
In `docs/DEBT.md` (Item 142), empirical evaluation revealed that the served post-hoc calibrator was originally fitted on the base-learner equal-weight average, whereas `PredictionEngine` serves the stacked meta-model with that calibrator applied on top. Stacking a calibrator onto an already scaled meta-model worsened holdout RPS in 6 of 6 leagues (e.g. Bundesliga RPS degraded from 0.1994 to 0.2101).

**The Council Directive for DEBT 142**:
1. During the upcoming model retraining cycle, operators must evaluate holdout performance on the 2024/25 chronological season under two candidate architectures:
   - **Candidate A**: Refit post-hoc calibrators directly on the 9-dimensional output of the served stacked meta-model head.
   - **Candidate B**: Formally remove the post-hoc calibrator wrapper where the meta-model wrapper (`TemperatureScaledMetaModel` or `VectorScaledMetaModel`) already achieves ECE $\le 0.03$.
2. In accordance with the DEBT-83 fail-closed hardening contract: if the meta-model fails at runtime, the engine **must never** substitute the base-learner average under a serialized calibrator; it must fail closed to the fallback simplex ($[0.333, 0.333, 0.334]$) with `calibration_method="uniform"`.

---

### 2.2 The Continuous Calibration Loop & Frozen C6 Protocol

To mathematically verify that SabiScore's model probabilities remain sharper than market closing prices, SabiScore enforces the **Frozen C6 Protocol** (`reports/research/c6-served-generation-vs-close-protocol.json`, SHA-256 `9d63da25324a79f4f08416d79991281bd45155064ec33fd8f67284b28be46ba7`).

#### C6 Protocol Specification
- **Population Definition**: Settled fixtures where the forecast was captured pre-kickoff ($t_{\text{created}} < t_{\text{closing}} < t_{\text{kickoff}}$) under the served generation identity (`v5_phase7-20260922@417b9b8ff7ce563d`) with `payload.capture_trigger = "interactive_full_analysis"`.
- **Closing Snapshot**: Verified Pinnacle closing quote captured within 5 minutes of kickoff ($0 < t_{\text{kickoff}} - t_{\text{captured}} \le 5\text{ min}$).
- **Primary Metric**: Paired Ranked Probability Score difference on match $i$:
  $$\Delta RPS_i = RPS_{\text{model}, i} - RPS_{\text{close}, i}$$
- **Statistical Testing via ISO-Week Cluster Bootstrap (`week_cluster_ci`)**:
  - 10,000 bootstrap replicates, fixed random seed 42.
  - Clustered by ISO calendar week to preserve intra-gameweek correlation.
  - Multiplicity control: 3 pre-registered looks at milestones $N \in \{200, 500, 1000\}$ settled fixtures.
  - Significance level with Bonferroni correction:
    $$\alpha = \frac{0.05}{3} \approx 0.016667 \implies 98.33\% \text{ Confidence Interval}$$
- **Decision Rules**:
  - **Sharper than Market Close**: Upper bound of 98.33% CI is strictly negative ($\Delta RPS < 0$).
  - **Inferior to Market Close**: Lower bound of 98.33% CI is strictly positive ($\Delta RPS > 0$).
  - **Inconclusive**: 98.33% CI straddles 0.0.
- **Interim Metric Withholding (DEBT Items 157, 161)**: Below 200 settled joined forecasts, endpoints (`/model-performance`) withhold the mean $\Delta RPS$ and confidence interval, returning only the joined count with `status: METRICS_UNAVAILABLE`.

---

### 2.3 Exact Mathematical Formulations

#### 1. Multiclass 10-Bin Expected Calibration Error (ECE)
Predictions are partitioned into $M=10$ equal-width bins $B_{m, c} = \left( \frac{m-1}{M}, \, \frac{m}{M} \right]$ for each outcome class $c \in \{0, 1, 2\}$ ($\text{Home}=0, \text{Draw}=1, \text{Away}=2$):
$$ECE_c = \sum_{m=1}^M \frac{|B_{m, c}|}{N} \left| \text{acc}(B_{m, c}) - \text{conf}(B_{m, c}) \right|$$
$$ECE_{\text{mean}} = \frac{1}{C} \sum_{c=0}^{C-1} ECE_c$$
Where:
$$\text{acc}(B_{m, c}) = \frac{1}{|B_{m, c}|} \sum_{i \in B_{m, c}} \mathbf{1}(y_i = c), \quad \text{conf}(B_{m, c}) = \frac{1}{|B_{m, c}|} \sum_{i \in B_{m, c}} p_{ic}$$

#### 2. Multiclass Brier Score & Murphy (1973) 3-Term Decomposition
Multiclass Brier score across $N$ matches:
$$BS = \frac{1}{N} \sum_{i=1}^N \sum_{c=0}^{C-1} (p_{ic} - y_{ic})^2$$
Where $y_{ic} = \mathbf{1}(y_i = c)$.

Murphy (1973) partition into Reliability, Resolution, and Uncertainty:
$$BS = \text{Reliability} - \text{Resolution} + \text{Uncertainty}$$
$$\text{Reliability} = \frac{1}{N} \sum_{m=1}^M |B_m| \sum_{c=0}^{C-1} (\bar{p}_{mc} - \bar{o}_{mc})^2 \quad (\text{Calibration error; lower is better, } 0 = \text{perfect})$$
$$\text{Resolution} = \frac{1}{N} \sum_{m=1}^M |B_m| \sum_{c=0}^{C-1} (\bar{o}_{mc} - \bar{o}_c)^2 \quad (\text{Discriminative sharpness; higher is better})$$
$$\text{Uncertainty} = \sum_{c=0}^{C-1} \bar{o}_c (1 - \bar{o}_c) \quad (\text{Irreducible environmental base-rate variance})$$

#### 3. Ranked Probability Score (RPS)
For 3 ordered football outcomes ($0=\text{Home}, 1=\text{Draw}, 2=\text{Away}$):
$$RPS = \frac{1}{K - 1} \sum_{r=1}^{K-1} \left( \sum_{j=1}^r p_j - \sum_{j=1}^r y_j \right)^2 = \frac{1}{2} \sum_{r=0}^1 \left( \sum_{j=0}^r p_j - \sum_{j=0}^r y_j \right)^2$$
Evaluated in `backend/src/models/evaluation/metrics.py` via cumulative sums (`np.cumsum`) for high-throughput vectorized execution.

#### 4. Walk-Forward Validation Strategies
- **Expanding Window Splits (`dt.to_period("A-JUL")`)**: Expanding seasons ending in July to match European football calendars (`backend/src/models/evaluation/temporal_splits.py`). Requires at least 3 initial seasons for training.
- **Purging**: Enforces a 48-hour exclusion buffer between training and test sets to eliminate simultaneous gameweek shocks and shared weather/referee conditions.
- **Embargoing**: Imposes a 7-day post-training evaluation blackout window to ensure rolling form features (e.g. 5-match exponential moving averages) do not leak future information across splits.

---

### 2.4 Market De-Vigging Algorithms

Bookmakers build an overround $\Pi = \sum_{i=1}^3 q_i > 1$ into decimal odds $O_i$, where gross implied probability is $q_i = \frac{1}{O_i}$. SabiScore extracts true fair probabilities $p_i$ through two formal de-vigging algorithms:

#### 1. Proportional Normalization (Active in live API serving paths)
$$p_i = \frac{q_i}{\Pi} = \frac{1 / O_i}{\sum_{j=1}^3 (1 / O_j)}$$
*Limitation*: Assumes margin is distributed evenly. In reality, bookmakers bias margin toward longshots (the Favourite-Longshot Bias), leading proportional de-vigging to slightly overstate longshot probabilities.

#### 2. Shin's Method (1992, 1993) (Canonical G18 Certification Baseline)
Models prices as equilibrium betting quotes in the presence of an insider trading proportion $z \in [0, 1)$:
$$p_i(z) = \frac{\sqrt{z^2 + 4(1 - z) \frac{q_i^2}{\Pi}} - z}{2(1 - z)}$$
Subject to the exact simplex constraint:
$$\sum_{i=1}^3 p_i(z) = 1$$
- Implemented in `backend/src/models/evaluation/market_baseline.py`.
- **Provable Bisection Convergence**: The residual function $f(z) = \sum_{i=1}^3 p_i(z) - 1$ is strictly continuous on $[0, 1)$. At $z=0$, $f(0) = \sqrt{\Pi} - 1 > 0$ for any vigged market ($\Pi > 1$). As $z \to 1$, $f(1-) < 0$. The bisection solver converges unconditionally to tolerance $10^{-12}$ in under 200 iterations, removing the Favourite-Longshot Bias.

---

### 2.5 Expected Value (+EV) and Fractional Kelly Staking

SabiScore adheres strictly to mathematical positive expectancy (+EV) against de-vigged fair market probabilities:

#### 1. Edge & Expected Value Formulation
$$\text{Edge}_k = p_{\text{model}, k} - p_{\text{fair}, k}$$
$$\text{EV}_k = p_{\text{model}, k} \cdot O_k - 1.0$$
*Invariant*: To qualify for an actionable recommendation, **both** $\text{Edge} > 0$ and $\text{EV} > 0$ must be strictly positive.

#### 2. Fractional Kelly Sizing (Quarter-Kelly)
Full Kelly stake fraction:
$$f^* = \frac{p_{\text{model}} \cdot O - 1}{O - 1} = \frac{\text{EV}}{O - 1}$$
Quarter-Kelly sizing applied:
$$f_{\text{recommended}} = \min\left(0.25 \times f^*, \, \text{LeagueCap}, \, 0.05\right)$$
- **Global Hard Cap**: 5.0% of bankroll (`MAX_KELLY_CAP = 0.05`).
- **Per-League Caps**:
  - EPL, La Liga, Bundesliga, Serie A, Ligue 1: **4.0%**
  - Eredivisie: **2.5%**
  - UEFA Champions League (UCL): **2.0%** (when certified)
- **Strict Zero Staking**: If $\text{EV} \le 0$ or $\text{Edge} \le 0$, stake fraction is identically $0.0\%$.
- **Withheld States**: No stake fraction is exposed for `PARTIAL`, `NO_BET`, `HOLD`, or `SPECULATIVE`.

---

### 2.6 Six-Tier Verdict Hierarchy & Abstention Logic

SabiScore enforces a 6-tier, fail-closed decision hierarchy:

```
                          Match Evidence Evaluated
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
      Critical Gaps Present?                  Zero Critical Gaps
                 │                                       │
       YES ──────┴──────► [PARTIAL]                      ▼
                            (Withheld)          Both EV > 0 & Edge > 0?
                                                         │
                                              NO ────────┴──────► [NO_BET]
                                                         │          (Pass)
                                                YES ─────┘
                                                         │
                                           Execution Blockers Present?
                                           (Stale, Low Tier, 1 Provider,
                                            Unconfirmed Lineups ≤ 90m)
                                                         │
                                              YES ───────┴──────► [HOLD]
                                                         │          (Pass)
                                               NO ───────┘
                                                         │
                                               Edge < 4.2% Threshold?
                                                         │
                                              YES ───────┴──────► [SPECULATIVE]
                                                         │          (Watchlist Only)
                                               NO ───────┘
                                                         │
                                       UCL Competition OR Providers < 4?
                                                         │
                                              YES ───────┴──────► [ACTIONABLE]
                                                         │          (Play)
                                               NO ───────┘
                                                         │
                                           Edge ≥ 6.2% & Epistemic ≤ 0.05
                                           & Confirmed Lineups & Providers ≥ 4
                                                         │
                                              YES ──────────────► [HIGH_CONVICTION]
                                                                    (Play)
```

#### Exact Tier Definitions & Rules
1. **`PARTIAL` (WITHHELD)**: Critical data gap present (missing metadata, uncertified model generation, 0 verified providers, market overround outside $[1.00, 1.25]$, or simplex violation). Staking is strictly Withheld.
2. **`NO_BET` (PASS)**: Clean data, but market price yields $\text{EV} \le 0$ or $\text{Edge} \le 0$. Staking is 0.0%.
3. **`HOLD` (PASS / ABSTAIN)**: Positive edge exists, but execution is blocked by operational risk:
   - Single-provider ceiling: `verified_provider_count == 1` caps verdict at `HOLD` (minimum 2 providers required to bet).
   - Market snapshot is `STALE` (>15 minutes old).
   - Kickoff is within 90 minutes and lineups are unconfirmed.
   - Low evidence confidence tier or conflicting sharp market movement.
4. **`SPECULATIVE` (WATCHLIST ONLY)**: Sub-threshold positive edge ($\text{Edge} < 4.2$ pp) supported by sharp market confirmation. Excluded from top opportunities. Staking is strictly 0.0%.
5. **`ACTIONABLE` (PLAY)**: Clean evidence, $\text{Edge} \ge 4.2$ pp, positive EV, fresh market odds, 2–3 independent verified providers, or UCL. Sized via Quarter-Kelly up to league cap.
6. **`HIGH_CONVICTION` (PLAY)**: $\text{Edge} \ge 6.2$ pp, epistemic uncertainty $\le 0.05$, market fresh ($\le 15$ min), confirmed starting lineups, $\ge 4$ independent verified providers, and **strictly NOT UCL**. Sized via Quarter-Kelly up to league cap.

---

### 2.7 Reconciliation of the Three Betting Engines

The codebase contains three distinct evaluation services that must be formally reconciled:

| Architectural Property | `betting_intelligence.py` | `core_engine.py` | `rl_betting_agent.py` |
| :--- | :--- | :--- | :--- |
| **Contract Version** | Contract v1.2.0 (`BettingIntelligenceService`) | Engine v2.1.0-prod (`CoreEngine`) | Phase 6-C Advisory Prototype (`RLBettingAgent`) |
| **Primary Route** | `/api/v1/betting-intelligence/analyze` | `/api/v1/core-engine/evaluate` | `/api/v1/rl-agent/recommend` |
| **Verdict Taxonomy** | 6 Tiers: `PARTIAL`, `NO_BET`, `HOLD`, `SPECULATIVE`, `ACTIONABLE`, `HIGH_CONVICTION` | 6 String Tiers: `PARTIAL`, `NO_BET`, `HOLD`, `SPECULATIVE`, `ACTIONABLE`, `HIGH_CONVICTION` | **No shared taxonomy**: Returns binary `abstain` and float `stake_fraction` |
| **Outcome Optimization** | Evaluates all 3 outcomes (1X2), selects best via Confidence-Adjusted Value ($CAV$) | Evaluates all 3 outcomes, ranks by $CAV$ | Fallback picks argmax probability (`_pick_market`); SAC uses 4-logit argmax |
| **De-vigging Method** | Proportional (`_compute_devig`) | Proportional | **No de-vigging**: Evaluates raw $1/O$ |
| **Kelly Staking** | Quarter-Kelly: $0.25 \times \frac{EV}{O - 1}$, capped $\le 5\%$ | Quarter-Kelly: $0.25 \times \frac{EV}{O - 1}$, capped $\le 5\%$ | Raw Kelly: $\frac{p \cdot O - 1}{O - 1}$, capped at `rl_max_kelly_cap` (0.05) |
| **Production Status** | **Unified Production Authority** | **Unified Production Authority** | **Advisory Only / Never Runs Live** (No stable-baselines3, no artifact; DEBT 160) |

**Directive Reconciliation Mandate**:
`betting_intelligence.py` and `core_engine.py` represent the unified, deterministic production authorities. `rl_betting_agent.py` is an uncertified research prototype that must remain strictly advisory and isolated from production betting decision paths.

---

# Section 3: Quantitative UX (Next.js 15)

### 3.1 Technology Stack & Architectural Boundaries

- **Pinned Framework Versions**:
  - `next`: `^15.5.6` (App Router)
  - `react`: `^18.3.1` (Strictly pinned in `apps/web/package.json`; upgrading to React 19 is prohibited without council approval)
  - `tailwindcss`: `3.4.14`
  - `recharts`: `^2.15.4` (isolated exclusively to client bundles via `next/dynamic({ ssr: false })`)
- **Server Components (RSC) by Default**:
  - `app/match/[id]/page.tsx` is an async React Server Component with `export const dynamic = "force-dynamic"` and `export const runtime = "nodejs"`. It renders semantic HTML, breadcrumbs, structured SEO JSON-LD (`generateSportsEventJsonLd`), and exactly one `<h1>` (`matchupLabelFor(...)`, resolving DEBT Item 163 U15).
- **Client Dynamic Import Boundaries**:
  - `FullAnalysisSection` dynamically loads `FullAnalysisDashboard` with `{ ssr: false, loading: () => <FullAnalysisSkeleton /> }`. This boundary decreased the shared first-load JS bundle from 198 kB to **103 kB** and route JS from 267 kB to **173 kB** (DEBT Item 158).
- **SSR Hydration Defense**:
  - Resolving DEBT Item 161: `ConsentProvider` must render child content on the server unconditionally. Deferring content rendering behind client `localStorage` checks destroys server HTML and wipes out SEO headings. The 18+ consent modal appears post-hydration without blocking initial paint.

---

### 3.2 Strict Prohibition of Client-Side Betting Math

Enforced by `apps/web/src/lib/no-client-ev-contract.test.ts`. An automated AST scan scans every TypeScript file in `apps/web/src/` to guarantee that no browser code executes odds calculations:
```typescript
const ODDS_ARITHMETIC = [
  /\b1(?:\.0)?\s*\/\s*\(?[\w.?]*odds\w*/i, // 1 / odds -> implied probability
  /[\w.?)\]]*odds\w*\s*-\s*1(?![\d.])/i,  // odds - 1 -> Kelly denominator / net odds
  /\*\s*\(?[\w.?]*odds\w*/i,              // p * odds -> EV calculation
];
```

#### Rationale
Historical attempts to compute odds math in the browser produced conflicting values between components (e.g. vigged implied probability in one widget vs. de-vigged fair price in another). The FastAPI backend is the sole authority for de-vigging, EV, and Kelly sizing; the frontend merely projects backend fields.

---

### 3.3 Obsidian Nocturne v2 Design Language

Defined across `apps/web/src/app/globals.css`, `tailwind.config.ts`, and Directives v8 §3.1, v9 U4, v10 U8.

| Semantic Token | HSL / CSS Value | Semantic Role & Strict Invariants |
| :--- | :--- | :--- |
| `--surface-card` | `222 35% 8%` | Primary container surface (Obsidian card field). |
| `--surface-elevated` | `222 30% 11%` | Elevated cards, flyouts, and dropdowns. |
| `--border-subtle` | `222 25% 16%` | Hairline dividers and card borders. |
| `--text-muted` | `215 20% 55%` | Secondary and metadata typography. |
| `--brand-prediction` | `#29cff3` | Cyan: **Selected output / active node only — NEVER implies confidence.** |
| `--state-play` | `145 63% 45%` | Actionable qualified recommendation (`CheckCircle2` icon). |
| `--state-pass` | `215 20% 65%` | Evaluable fixture with no positive value (`MinusCircle` icon). |
| `--state-withheld` | `215 16% 47%` | Neutral slate for uncertified/incomplete fixtures (`CircleDashed` icon). |
| `--risk-counter` | `amber-500/20 bg-amber-500/[0.04]` | Muted amber: **Strictly reserved for counter-case and advisory warnings.** |
| `:focus-visible` | `outline: 2px solid hsl(var(--conviction-actionable))` | WCAG 2.4.7 keyboard accessibility without per-component duplication. |

#### Redundant Triple-Encoding for Complete Color-Blind Accessibility
Decision state is **never communicated by color alone**. SabiScore enforces simultaneous redundant encoding across all badges:
- `PLAY`: Text "Play" + `CheckCircle2` icon + emerald token (`--state-play`).
- `PASS`: Text "Pass" + `MinusCircle` icon + slate token (`--state-pass`).
- `WITHHELD`: Text "Withheld" + `CircleDashed` icon + neutral dark slate token (`--state-withheld`).
All indicators survive 100% grayscale and all forms of color-vision deficiency.

---

### 3.4 Probability Visualization Strategy (True vs. Implied)

#### 1. `ProbabilityDumbbell` (`apps/web/src/components/probability-dumbbell.tsx`)
Rendered as an accessible, lightweight inline SVG (`viewBox="-2 0 104 30"`), adding 0 bytes of external charting dependencies:
- **Model Probability ($p_k$)**: Rendered as a filled circle ● at $x = p_k \times 100$. Filled with `--state-play` (emerald) ONLY if `stakePermitted && edge > 0`; otherwise filled with `--state-withheld` (neutral slate).
- **Fair De-vigged Probability ($\text{fair}_k$)**: Rendered as a hollow circle ○ at $x = \text{fair}_k \times 100$ (`fill-slate-950 stroke-[hsl(var(--state-withheld))]`).
- **Break-Even Implied Probability ($1/O_k$)**: Rendered as a vertical tick line `|` across the track (`stroke-slate-400`). Drawn on top so it is never obscured.
- **Horizontal Gap Bar**: Connects $\text{fair}_k$ to $p_k$.
- Legend: `● model  ○ fair  | break-even`.

#### 2. `MarketComparisonTable` (`apps/web/src/components/full-analysis-dashboard.tsx:1037`)
Accessible companion table displaying Outcome, Bookmaker Price ($O_k$), Fair Market Probability ($\text{fair}_k$), Model Probability ($p_k$), Gap ($p_k - \text{fair}_k$ in pp), and Expected Return per unit staked ($EV$).

**The Decisive Truth Rule**:
If the active model generation is uncertified (e.g. `MODEL_GENERATION_UNCERTIFIED`):
- The edge gap is rendered in neutral slate (`text-slate-300`).
- Expected Return is suppressed (`—`).
- The table renders the mandatory disclosure:
  > *"This model has not passed certification against the market, so a gap here is not evidence of value and no expected return is shown."*
- Staking display: In `OddsEdgeCard`, Kelly stake displays `"Withheld"`, **never `0.00%`** (Directive v9 U2).

---

### 3.5 Disjoint Decision States & Headline Logic

In `apps/web/src/lib/full-analysis-contract.ts` (`mapFullAnalysisPresentation`), the decision state maps to three strictly disjoint categories:

```typescript
const blocked = !predictionAvailable || hasCriticalEvidenceIssue;
const stakePermitted = !blocked && actionableVerdict && data.stake_permitted && 
                       !data.rl_recommendation.abstain && data.rl_recommendation.stake_fraction > 0;

const decisionState = stakePermitted && data.odds_edge
  ? "PLAY"
  : blocked || !data.odds_edge
    ? "WITHHELD"
    : "PASS";
```

#### Headline Copy Contract
- `PLAY`: `"Qualifies · stake {stake_pct}% of bankroll"`
- `PASS`: `"No value at this price"` (or `"Watchlist only — no stake"` for `SPECULATIVE`)
- `WITHHELD`: Names the primary blocking reason (e.g. `"Model generation uncertified"`, `"Model uncertainty unavailable"`, `"No verified market price is available"`).
- **Invariant**: `PASS` and `WITHHELD` must **never** collapse into a generic "No Bet".

---

### 3.6 Mandatory Counter-Case Panel ("Why this might fail")

Implemented in `CounterCase` (`apps/web/src/components/full-analysis-dashboard.tsx:422`):
- **Unconditional Display**: Renders whenever a forecast exists, including on `PLAY` recommendations. Sports betting is inherently stochastic; presenting only positive EV generates overconfidence.
- **Visual Styling**: Muted amber frame (`border border-amber-500/20 bg-amber-500/[0.04]`), heading `Why this might fail`.
- **Structured Evidence Chain (in strict order)**:
  1. **Loss Probability**: `"The model gives {outcome} a {p}% chance, so it loses {1 - p}% of the time."`
  2. **Market Movement**: Discloses price movement from earliest sighting to current snapshot (`"The price for {outcome} moved from {first} to {current} since SabiScore first saw it at this bookmaker ({time} WAT)."`).
  3. **Uncertified Edge Warning**: `"The model puts {outcome} {edge}pp above the fair market price, but it has not passed certification against the market, so that gap is not evidence of value."`
  4. **Epistemic Uncertainty**: States credible interval (`"Model uncertainty interval: {low}% to {high}%."`) or plainly discloses `"Model uncertainty is unavailable for this fixture; no interval is inferred."`
  5. **Live Calibration Threshold**: Discloses that calibration is evaluated only after 200 forecasts settle.
  6. **Advisory Gaps**: Enumerates non-blocking missing inputs (`"{count} non-blocking inputs are missing, which makes this forecast less reliable."`).

---

### 3.7 Responsible Gambling Compliance

Governed by `apps/web/src/lib/copy-contract.test.ts` and `evidence-copy-contract.test.ts`:
- **Prohibited Certainty Terms**: Automatic AST rejection for `lock`, `banker`, `guaranteed`, `sure bet`, `free money`, `execute immediately`.
- **Prohibited Promotional Claims**: `maximize your betting edge`, `beat the market`, `win more`, `winning pick`, `highly accurate predictions`, `profitable predictions`, `guaranteed returns`.
- **Prohibited Unshipped Method Names**: `RL Bet Recommendation`, `RL betting`, `BNN uncertainty`, `Bayesian Neural Network` (DEBT Items 159, 160).
- **Prohibited Staking Claims**: `1/8 Kelly`, `eighth-kelly` (banned; SabiScore public staking is strictly Quarter-Kelly).
- **Mandatory Timezone Labeling**: Unlabeled browser-zone times (`toLocaleTimeString()`) are banned; all user-facing times must be formatted in West Africa Time (`WAT`) via `@/lib/lagos-time.ts`.

---

# Section 4: NEXUS Agent Orchestration

### 4.1 The Strict Operational Boundary

As codified across Directives v8 §4.1, v9 §4.1, and v12 §4:
> **LLM agents NEVER run inside production calibration, settlement, CLV capture, or data ingestion loops.**

- **Production Loops**: Production loops are deterministic, idempotent Python `asyncio` background tasks inside `backend/src/api/main.py`.
- **Agent Operating Domain**: Multi-agent orchestration operates strictly during **offline development, research, protocol design, code modification, and audit cycles**.

---

### 4.2 Supervisor-Worker Hierarchy & File-and-Hash Handoffs

```
Supervisor (Lead session: NEXUS intent classifier, owns Git branch, PR, and heavy gate execution)
├── Planner (Architect: read-only; authors protocol.json, computes SHA-256, freezes protocol)
├── Worker / Implementer (Code & test author; restricted to assigned file slice; runs light checks)
├── Evaluator (QA-Verifier: applies frozen decision rules mechanically; executes test suites)
└── Reviewer (Auditor: diff review with confidence filtering, security and secret scanning)
```

#### File-and-Hash Handoff Protocol
Agents do not share in-memory session context. All inter-agent handoffs cross boundaries via immutable file artifacts in `backend/reports/research/<exp-id>/`:
1. `protocol.json` + `protocol.json.sha256`: Written by Planner **before** any run. Defines hypothesis, dataset hash, validation folds, metrics, decision thresholds, and a `no_retuning` clause.
2. `run_manifest.json`: Written by Worker/Runner. Contains Git commit SHA, dataset hash, protocol SHA, peak RSS (MB), execution time (s), $n_{\text{jobs}}$, and random seed.
3. `results.json`: Written by Worker/Runner. Contains raw empirical measurements without spin or narrative.
4. `decision.md`: Written by Evaluator. Mechanically applies the pre-registered decision rules to `results.json`, emitting one of `PROMISING`, `NEGATIVE`, or `INCONCLUSIVE`.

---

### 4.3 Memory Management Under 8GB Local Constraint

To prevent workstation freezing or swapping during agent-driven development:
1. **The Heavy Process Mutex**:
   - **Exactly one heavy process may run at any time.**
   - Heavy processes:
     - Full backend test suite (`pytest`, ~8.5 minutes, peak ~1.2 GB RSS)
     - Next.js production build (`next build`, peak ~1.8 GB RSS)
     - End-to-end browser suite (`playwright test`, peak ~1.5 GB RSS)
     - Full typechecking (`mypy` or `tsc --noEmit`)
     - Model training / backfill evaluation runs
   - Heavy tasks must execute sequentially, never in parallel.
2. **Subagent Concurrency Bounds**:
   - At most 2 lightweight subagents may be active concurrently.
   - **Zero subagents may run while a heavy task is executing.** The supervisor retains sole execution of heavy jobs.
3. **Language Server Memory Cap**:
   - VS Code / editor configuration must enforce `typescript.tsserver.maxTsServerMemory: 3072` (capped at 3.0 GB).

---

### 4.4 Protocol Governance for Backfills & Calibration

- **Permitted Backfills**:
  - Ingesting a newly completed season's historical results CSV via Git pull request.
  - Replaying Elo rating calculations over settled historical matches.
- **Prohibited Backfills**:
  - **Retroactive prediction backfills are strictly prohibited**: Predictions cannot be backfilled for matches that have already kicked off. Any prediction generated post-kickoff constitutes data leakage and falsifies C6.
- **Continuous Calibration Sharpness Protocol**:
  - Sharpness is evaluated exclusively under the frozen C6 Protocol at sample milestones (200, 500, 1,000 settled forecasts).
  - **No autonomous agent or automated script may refit models, recalibrate weights, or alter `certification_state`.** Calibration decisions are reserved exclusively for human operators at defined milestones.

---

## Directive Attestation & Operational Verification Matrix

To independently verify all architectural claims, constraints, and contracts in this directive, run the following authoritative command suite:

```bash
# 1. Verify Memory Watchdog Implementation (D1)
pytest backend/tests/unit/test_resource_guard.py -v

# 2. Verify Instance Memory Cgroup Reader & Headroom Calculation
pytest backend/tests/unit/test_instance_memory.py -v

# 3. Verify Heavy Job Single-Lane Serialization (S3)
pytest backend/tests/unit/test_heavy_jobs.py -v

# 4. Verify Active League Model Artifacts in active_generation.json
python -c "import json; m=json.load(open('backend/models/active_generation.json')); print(list(m['artifacts'].keys()))"
# Expected: ['bundesliga', 'epl', 'eredivisie', 'la_liga', 'ligue_1', 'serie_a']

# 5. Verify Platt Scaling Closed-Form Sigmoid Arithmetic (DEBT 133)
pytest backend/tests/unit/test_calibrator_load_and_preflight.py -v

# 6. Verify Shin De-Vigging Bisection Inversion & Provable Bracketing (G18)
pytest backend/tests/unit/test_market_baseline.py -v

# 7. Verify Frozen C6 Protocol SHA-256 Immutability
pytest backend/tests/unit/test_c6_protocol_frozen.py -v

# 8. Verify No Client-Side Betting Math Contract (Vitest AST Scan)
cd apps/web && pnpm test src/lib/no-client-ev-contract.test.ts

# 9. Verify Responsible Gambling Copy Contract & Banned Term AST Scan
cd apps/web && pnpm test src/lib/copy-contract.test.ts src/lib/evidence-copy-contract.test.ts

# 10. Verify Heading Contract (Exactly 1 <h1> per page)
cd apps/web && pnpm test src/lib/heading-contract.test.ts

# 11. Verify Probability Dumbbell and Dashboard UI Components
cd apps/web && pnpm test src/components/probability-dumbbell.test.tsx src/components/full-analysis-dashboard.test.tsx
```

---
*Signed by the Multi-Agent Engineering Council on this 29th day of September, 2026.*
