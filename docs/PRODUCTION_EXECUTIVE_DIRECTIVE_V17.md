# SabiScore — Production Executive Directive V17.0

**Author**: Multi-Agent Engineering Council (Platform Architecture, Quantitative Modeling, Backend Systems, Risk Engineering, Frontend Systems, SRE/Security)  
**Date**: 2026-10-01  
**Status**: ACTIVE / MANDATORY PRODUCTION DIRECTIVE  
**Supersedes**: Directive V16.0 (`docs/PRODUCTION_EXECUTIVE_DIRECTIVE_V16.md`), Directive V15.0, Directive V14.0, and all predecessor directives.  
**Ground Truth Authorities**: [`docs/DEBT.md`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/docs/DEBT.md) (Items 1–170), [`backend/src/api/main.py`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/backend/src/api/main.py), [`backend/models/active_generation.json`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/backend/models/active_generation.json), [`apps/web/src/`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/apps/web/src/), [`NEXUS.md`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/NEXUS.md), [`AGENTS.md`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/AGENTS.md).

---

## Executive Summary & Core Mandate

This Directive codifies the authoritative operational, quantitative, and architectural governance for the SabiScore platform. SabiScore is a quantitative football intelligence and predictive modeling engine operating strictly under a positive expected value ($+\text{EV}$) and capital preservation philosophy. SabiScore is an analytical decision engine, **not a gambling site**.

All systems, background loops, autonomous agents, and engineering workflows must adhere to four immutable architectural realities:

1. **Hardware & Resource Ceiling (8GB Local / 512MB Container)**: The production backend runs in a **512 MB cgroup v2 Linux container** on Render (`working_set` maintained at 320–340 MB, ensuring $\ge 170\text{ MB}$ operational headroom). Local development and CI execution run on an **8,192 MB (8.0 GB) RAM ceiling**, where all heavy jobs (model training, integration test suites, Next.js production builds) are strictly serialized behind a single-process 3.0 GB ceiling enforced by [`_resource_guard.py`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/backend/scripts/_resource_guard.py) (`SABISCORE_MAX_RSS_MB=3072`). Native C-extension threading is hard-clamped to single-thread execution (`OMP_NUM_THREADS="1"`, `MKL_NUM_THREADS="1"`).
2. **In-Process Python Lifespan vs. Constrained Offline Scraper**: Real-time fixture acquisition, odds ingestion, and settlements run entirely in-process within FastAPI lifespan background loops in [`backend/src/api/main.py`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/backend/src/api/main.py). The Node.js crawler in `apps/scraper/` is strictly an offline, batch-oriented tool deactivated in production (`SCRAPER_PRODUCTION_ENABLED="false"`) and hard-clamped to `--max-old-space-size=384` and `CRAWLEE_MEMORY_MBYTES=512`.
3. **Calibrated Ensemble Inference & Frozen C6 Protocol**: Predictions for the 6 canonical domestic leagues (EPL, La Liga, Bundesliga, Serie A, Ligue 1, Eredivisie) are served by [`PredictionEngine`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/backend/src/models/prediction.py) using stacked ensemble learners (Random Forest, XGBoost, LightGBM, and Logistic Regression meta-models) consuming 11 MB disk storage and ~55 MB resident heap, backed by an expanded 8-model LRU cache (`MAX_CACHED_MODELS=8`, DEBT 167). Model calibration sharpness against Pinnacle closing lines is continuously evaluated via the frozen C6 Protocol using paired $\Delta RPS$ with ISO-week cluster bootstrapping (10,000 replicates, $\alpha = 0.05/3 \approx 0.016667$) at sample milestones of 200, 500, and 1,000 settled forecasts.
4. **Deterministic UX & Zero-Fabrication Philosophy**: The Next.js 15.5.6 + React 18.3.1 frontend is strictly a deterministic projection layer. The browser is mathematically prohibited from computing odds arithmetic, implied probabilities, Expected Value, or Kelly stake sizing ([`no-client-ev-contract.test.ts`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/apps/web/src/lib/no-client-ev-contract.test.ts)). Every forecast displays the true vs. fair vs. implied probability dumbbell, a distinct tri-state verdict (`PLAY`, `PASS`, or `WITHHELD`), and a mandatory counter-case panel ("Why this might fail") disclosing loss probability ($1 - p_k$), market price movement, uncertainty bounds, and non-blocking advisory gaps.

---

# Section 1: Resource-Constrained Data & Feature Engineering

### 1.1 Ingestion Architecture: Async Python Lifespan vs. Offline Node.js Crawler

Production data ingestion is executed **in-process** within the FastAPI application runtime via deterministic, asynchronous lifespan background loops. Node.js crawlers are prohibited from executing in the live serving path.

```text
FastAPI Application Lifespan (Python 3.11+, Single Uvicorn Worker)
│
├── _background_fixture_sync() ────────── Every 21,600s (6 Hours)
│   ├── [Boot Tick Only] run_historical_backfill() (Offline CSV parsing)
│   └── run_fixture_sync() (football-data.org, 14-day lookahead, 50-fixture cap)
│       └── Redis Lease Lock: "sabiscore:job:fixture_sync:lease" (TTL 600s)
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

#### Lifespan HTTP Client & Distributed Concurrency Guard
- **Lifespan HTTP Client**: Provider requests share a single application-lifespan `httpx.AsyncClient` configured with strict connection limits:
  $$\text{Limits}(\text{max\_connections} = 20, \, \text{max\_keepalive\_connections} = 10), \quad \text{timeout} = 8.0\text{s}$$
- **Distributed Lease Locking**: During container rolling deployments on Render, instances temporarily overlap. To prevent concurrent executions from double-billing external API quotas or triggering HTTP 429 rate limits, [`fixture_sync_service.py`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/backend/src/services/fixture_sync_service.py) acquires an atomic distributed lease key in Redis (`sabiscore:job:fixture_sync:lease`, TTL 600s) via an atomic Lua script:
  ```lua
  if redis.call('set', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2]) then
    return 1
  else
    return 0
  end
  ```

---

### 1.2 Node.js Worker & Scraper Memory Profiling

The scraper in `apps/scraper/` is packaged via `Dockerfile.worker` and scheduled as a bi-weekly cron job (`"0 3 * * 1,4"` in `render.yaml`). It is strictly deactivated in production via `SCRAPER_PRODUCTION_ENABLED="false"`. When enabled by operator approval for offline data acquisition, it must adhere to strict runtime boundaries:

```yaml
# render.yaml lines 221-226
- key: NODE_OPTIONS
  value: "--max-old-space-size=384 --heapsnapshot-near-heap-limit=1"
- key: CRAWLEE_MEMORY_MBYTES
  value: "512"
```

1. **V8 Heap Capping (`--max-old-space-size=384`)**: Hard-caps the V8 JavaScript heap at 384 MB, guaranteeing $512\text{ MB} - 384\text{ MB} = 128\text{ MB}$ of container headroom for native C++ bindings, libuv thread pools, and OpenSSL TLS buffers.
2. **Emergency Heap Snapshots (`--heapsnapshot-near-heap-limit=1`)**: Directs V8 to write an emergency diagnostic heap snapshot to disk immediately prior to an OOM crash.
3. **Concurrency Clamping**: In `apps/scraper/src/http.mjs`, Crawlee's `BasicCrawler` / `PlaywrightCrawler` is clamped to:
   - `minConcurrency: 1`, `maxConcurrency: 1`, `maxRequestsPerCrawl: 1`
   - `sameDomainDelaySecs: 3`, `maxRequestsPerMinute: 6`, `maxRequestRetries: 2`
   - `useSessionPool: false` (eliminates multi-session resident browser contexts)
4. **In-Process Request Boundary Sampling (`sampleHeap`)**: In `apps/scraper/src/storage.mjs`, `sampleHeap()` samples `process.memoryUsage().heapUsed` before and after request hooks. If `heapUsed > 320 MB`, the crawler halts gracefully, flushes manifests, and releases memory.
5. **Streaming NDJSON Pipeline**: Batch scraper output is written using Node.js `stream/promises` and `readline`. Ingesting raw JSON into Postgres uses chunked streaming directly into `COPY ... FROM STDIN WITH (FORMAT csv)` or chunked bulk inserts, preventing multi-megabyte string deserialization in V8 heap.

---

### 1.3 Mathematical Allocation of 8GB Local Workstation Memory

Local engineering workstations (Windows 11 / Linux) and CI runners operate under a rigid **8,192 MB (8.0 GB)** physical RAM ceiling.

#### Local Workstation Memory Budget Table (8,192 MB Total)

| Subsystem / Process | Target Allocation | Peak Ceiling | Accounting & Operational Rules |
| :--- | :---: | :---: | :--- |
| **Host OS & Desktop Environment** | **3,500 MB** | 3,800 MB | Windows 11 kernel, desktop manager, background services, shell terminals, VS Code, and `tsserver` (`typescript.tsserver.maxTsServerMemory <= 3072`). |
| **Local PostgreSQL 16** | **350 MB** | 512 MB | `shared_buffers = 128MB`, `work_mem = 4MB`, `max_connections = 50`. |
| **Local Redis 7** | **150 MB** | 256 MB | `--maxmemory 256mb`, `--maxmemory-policy allkeys-lru`. |
| **FastAPI Backend Runtime** | **455 MB** | 650 MB | Python runtime (42 MB) + Scientific ML stack (135 MB) + 6 unpickled league ensembles (55 MB resident heap) + DB/Redis connection pools (15 MB). Single-thread clamped (`OMP_NUM_THREADS="1"`). |
| **Next.js 15 Web Application** | **350 MB** | 600 MB | Node.js production runner (`next start`). For `next dev`, V8 heap capped at 1,024 MB. |
| **Idle System Slack & Browser Tabs** | **377 MB** | 500 MB | Web browser inspecting endpoints, Git index, and OS file cache. |
| **Dedicated Heavy Job Reservation** | **3,000 MB** | **3,072 MB** | **Strictly reserved for exactly ONE active heavy job** (Model training, `pytest` suite, `next build`, or bootstrap evaluation). |
| **TOTAL LOCAL ALLOCATION** | **8,182 MB** | **8,192 MB** | **Completely accounted within 8,192 MB physical boundary.** |

#### Enforcing the 3.0 GB Ceiling via `ResourceGuard`
In [`backend/scripts/_resource_guard.py`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/backend/scripts/_resource_guard.py), SabiScore implements an active memory watchdog:
- Samples total process resident memory plus all child processes recursively (`_tree_rss_mb()`) every 0.5 seconds:
  $$\text{RSS}_{\text{tree}} = \text{RSS}_{\text{parent}} + \sum_{k} \text{RSS}_{\text{child}_k}$$
- Pinned by `SABISCORE_MAX_RSS_MB` (default: **3,072 MB = 3.0 GB**).
- If $\text{RSS}_{\text{tree}} > 3,072\text{ MB}$, the watchdog immediately terminates all worker child processes via `SIGKILL`, writes structured error JSON to `stderr`, and aborts execution via `os._exit(137)` to prevent OS swap lockup.
- **Worker Clamping (`SABISCORE_MAX_JOBS`)**: In `train_on_real_matches.py`, `n_jobs` is clamped to `SABISCORE_MAX_JOBS` (default: **2** locally).
- **Single-Thread Clamping (DEBT 167)**: `OMP_NUM_THREADS="1"`, `OPENBLAS_NUM_THREADS="1"`, `MKL_NUM_THREADS="1"`, `VECLIB_MAXIMUM_THREADS="1"`, `NUMEXPR_NUM_THREADS="1"` set at the entrypoint of `backend/src/api/main.py`.
- **Sequential League Training (Directive D4)**: Training across the 6 leagues executes sequentially with explicit `del bundle` and `gc.collect()` between leagues.

---

### 1.4 Data Streaming and Point-in-Time (PIT) Feature Pipeline

#### 200 MB File Chunking Trigger Rule (Directive D6 & DEBT Item 88)
The entire historical training corpus (`backend/data/cache/fd_*.csv`) comprises 36 CSV files totaling **6.0 MB on disk** (~11 MB uncompressed, 12,765 matches). Peak traced RAM during evaluation is under 1.0 MB (0.617 MB).
- **Rule**: Datasets below 200 MB are loaded in a single vector operation to eliminate interpreter loop overhead.
- If an individual file exceeds **200 MB**, loaders must switch to chunked iteration:
  ```python
  chunks = pd.read_csv(filepath, chunksize=10000, usecols=REQUIRED_COLS, dtype=DTYPE_MAP)
  ```
  with explicit downcasting (`float32` for features, `category` for team identifiers).

#### Database Streaming (Directive D5)
Queries processing historical match sets must enforce pagination or chunked streaming:
```python
query = select(Match).order_by(Match.match_date.asc()).execution_options(yield_per=500)
async for partition in (await session.stream(query)).partitions():
    for match in partition:
        process_match(match)
```
This bounds the SQLAlchemy ORM identity map resident memory to 500 instances at a time.

#### Point-in-Time (PIT) Feature Construction (`apex_v1_68`)
The canonical `apex_v1_68` schema requires 68 features computed with strict temporal bounds:
$$t_{\text{feature}} \le t_{\text{evaluation}} < t_{\text{closing}} < t_{\text{kickoff}}$$
- **Zero Lookahead Leakage**: No post-match event (cards, actual corners, full-time xG, post-match Elo adjustments) may enter feature vectors before match settlement.
- **Fail-Closed Imputation**: Missing inputs trigger structured `advisory_gaps` or `critical_gaps`. Zero-filling, median substitution, or synthetic value fabrication is strictly forbidden.

---

### 1.5 Target Leagues & UCL Structural Policy

SabiScore predicts and models exactly **6 domestic leagues**:

| # | Canonical League ID | Country | Division Code | League Name (`football-data.org`) | Active Model Artifact |
| :-: | :--- | :--- | :-: | :--- | :--- |
| **1** | `EPL` | England | `E0` | Premier League | `epl_ensemble_v5_phase7.pkl` |
| **2** | `LA_LIGA` | Spain | `SP1` | Primera Division | `la_liga_ensemble_v5_phase7.pkl` |
| **3** | `BUNDESLIGA` | Germany | `D1` | Bundesliga | `bundesliga_ensemble_v5_phase7.pkl` |
| **4** | `SERIE_A` | Italy | `I1` | Serie A | `serie_a_ensemble_v5_phase7.pkl` |
| **5** | `LIGUE_1` | France | `F1` | Ligue 1 | `ligue_1_ensemble_v5_phase7.pkl` |
| **6** | `EREDIVISIE` | Netherlands | `N1` | Eredivisie | `eredivisie_ensemble_v5_phase7.pkl` |

#### UEFA Champions League (UCL) Structural Policy
- Fixtures are ingested under competition code `CL`.
- **Zero machine learning artifacts exist for UCL** in [`backend/models/active_generation.json`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/backend/models/active_generation.json).
- Because UCL represents cross-league knockout competition with disparate domestic strengths, variable rotation, and small historical cross-league sample sizes:
  1. UCL is **structurally capped at `ACTIONABLE`**; reaching `HIGH_CONVICTION` is prohibited (`betting_intelligence.py:527`).
  2. Public model prediction capture and betting verdict generation for UCL are withheld until a dedicated, certified cross-league model and calibration policy are trained, validated, and promoted (`models/AGENTS.md:17`).

---

# Section 2: Model Serving & Pipeline Refinement

### 2.1 Calibrated Ensemble Deployment in FastAPI

Model inference is centralized in [`backend/src/models/prediction.py`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/backend/src/models/prediction.py) (`PredictionEngine`) and managed via [`active_generation.py`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/backend/src/models/active_generation.py).

#### Serving Architecture & Memory Footprint
- 6 league ensemble pickles total **11 MB on disk** (~1.8 MB each).
- Deserialized at boot via `PredictionEngine.prime_cache()`, consuming ~55 MB of resident heap across all 6 leagues.
- **Cache Sizing (DEBT 167)**: `PredictionService.MAX_CACHED_MODELS` is set to **8** (expanded from 5), guaranteeing that all 6 domestic leagues and cup models reside in memory without LRU cache eviction churn.
- Base learners per ensemble:
  - `RandomForestClassifier` (`n_estimators=300, max_depth=12`)
  - `XGBClassifier` (`n_estimators=250, max_depth=7, tree_method="hist"`)
  - `LGBMClassifier` (`n_estimators=250, max_depth=7`)
- Inference pipeline for 68-dimensional APEX feature vector $\mathbf{x} \in \mathbb{R}^{68}$:
  1. Base learners predict individual 1X2 probability triples: $\mathbf{p}_{\text{rf}}, \mathbf{p}_{\text{xgb}}, \mathbf{p}_{\text{lgbm}} \in \Delta^2$.
  2. Stacking meta-features: $\mathbf{z} = [\mathbf{p}_{\text{rf}}, \mathbf{p}_{\text{xgb}}, \mathbf{p}_{\text{lgbm}}] \in \mathbb{R}^9$.
  3. Meta-Model: Temperature-Scaled / Vector-Scaled / Multinomial Logistic Regression produces ensemble probability $\mathbf{p}_{\text{meta}}$.
  4. Post-Hoc Calibrator ([`FittedCalibrator`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/backend/src/models/calibration.py#L98)): Platt Sigmoid or Isotonic mapping.
  5. Optional Bivariate Poisson Draw Overlay: Blends draw probability with Skellam distribution:
     $$P(\text{draw}) = e^{-(\lambda_H + \lambda_A)} I_0\left(2\sqrt{\lambda_H \lambda_A}\right)$$
  6. Simplex validation: Verifies $\sum_{k=0}^2 p_k = 1.0 \pm 10^{-6}$.

#### Closed-Form Platt Scaling (DEBT Item 133)
In [`backend/src/models/calibration.py`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/backend/src/models/calibration.py#L247), SabiScore enforces **closed-form sigmoid arithmetic**:
$$\text{logit} = \text{clip}\left(w \cdot p + b, \, -30.0, \, 30.0\right), \quad P(y = 1 \mid p) = \sigma(\text{logit}) = \frac{1}{1 + e^{-\text{logit}}}$$
Where $w$ and $b$ are extracted as raw floats from `calibrator.coef_[0]` and `calibrator.intercept_[0]`. This eliminates scikit-learn version deserialization warnings and prevents float overflow.

#### Serialization Modernization (DEBT Item 169)
For candidate generation retraining (`v6_phase8`), XGBoost artifacts must migrate from raw pickle serialization to native JSON serialization (`Booster.save_model("...json")`), eliminating `InconsistentVersionWarning` across scikit-learn/XGBoost minor version upgrades.

---

### 2.2 Continuous Calibration Loop & Frozen C6 Protocol

To verify that model probabilities remain sharper than Pinnacle market closing prices, SabiScore enforces the **Frozen C6 Protocol** (`reports/research/c6-served-generation-vs-close-protocol.json`, SHA-256 `9d63da25324a79f4f08416d79991281bd45155064ec33fd8f67284b28be46ba7`).

#### Protocol Specification
- **Population**: Settled fixtures where the forecast was captured pre-kickoff ($t_{\text{created}} < t_{\text{closing}} < t_{\text{kickoff}}$) under served generation `v5_phase7-20260922@417b9b8ff7ce563d` with `payload.capture_trigger = "interactive_full_analysis"`.
- **Closing Snapshot**: Verified Pinnacle closing quote captured within 5 minutes of kickoff ($0 < t_{\text{kickoff}} - t_{\text{captured}} \le 5\text{ min}$).
- **Primary Metric**: Paired Ranked Probability Score difference on match $i$:
  $$\Delta RPS_i = RPS_{\text{model}, i} - RPS_{\text{close}, i}$$
- **Statistical Testing via ISO-Week Cluster Bootstrap (`week_cluster_ci`)**:
  - 10,000 bootstrap replicates, fixed random seed 42.
  - Clustered by ISO calendar week to preserve intra-gameweek correlation.
  - Multiplicity control: 3 pre-registered looks at milestones $N \in \{200, 500, 1000\}$ settled fixtures.
  - Bonferroni-corrected significance level:
    $$\alpha = \frac{0.05}{3} \approx 0.016667 \implies 98.33\% \text{ Confidence Interval}$$
- **Decision Rules**:
  - **Sharper than Market Close**: Upper bound of 98.33% CI is strictly negative ($\Delta RPS < 0$).
  - **Inferior to Market Close**: Lower bound of 98.33% CI is strictly positive ($\Delta RPS > 0$).
  - **Inconclusive**: 98.33% CI straddles 0.0.
- **Interim Metric Withholding (DEBT Items 157, 161)**: Below 200 settled joined forecasts, endpoints (`/model-performance`) withhold mean $\Delta RPS$ and confidence intervals, returning `status: METRICS_UNAVAILABLE`.

---

### 2.3 Market De-Vigging Algorithms

Bookmakers build an overround $\Pi = \sum_{i=1}^3 q_i > 1$ into decimal odds $O_i$, where gross implied probability is $q_i = \frac{1}{O_i}$. SabiScore extracts true fair probabilities $p_i$ through two de-vigging algorithms:

#### 1. Proportional Normalization (Active in live API serving paths)
$$p_i = \frac{q_i}{\Pi} = \frac{1 / O_i}{\sum_{j=1}^3 (1 / O_j)}$$

#### 2. Shin's Method (1992, 1993) (Canonical G18 Certification Baseline)
Implemented in [`backend/src/models/evaluation/market_baseline.py`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/backend/src/models/evaluation/market_baseline.py#L179), Shin's method models prices as equilibrium quotes in the presence of an insider trading proportion $z \in [0, 1)$:
$$p_i(z) = \frac{\sqrt{z^2 + 4(1 - z) \frac{q_i^2}{\Pi}} - z}{2(1 - z)}$$
Subject to the exact simplex constraint:
$$\sum_{i=1}^3 p_i(z) = 1$$
- **Provable Bisection Convergence**: The residual function $f(z) = \sum_{i=1}^3 p_i(z) - 1$ is continuous, strictly monotonic, with $f(0) = \sqrt{\Pi} - 1 > 0$ and $\lim_{z \to 1^-} f(z) = -1 < 0$. Bisection converges to tolerance $10^{-12}$ in $<200$ iterations, removing the Favourite-Longshot Bias.

---

### 2.4 Expected Value (+EV) and Fractional Kelly Staking

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

# Section 3: Quantitative UX & Actionable Insights (Next.js 15)

### 3.1 Technology Stack & Architectural Boundaries

- **Pinned Framework Versions**:
  - `next`: `^15.5.6` (App Router)
  - `react`: `^18.3.1` (Strictly pinned in `apps/web/package.json`; upgrading to React 19 is prohibited without council approval)
  - `tailwindcss`: `3.4.14`
  - `recharts`: `^2.15.4` (isolated exclusively to client dynamic bundles)
- **Server Components (RSC) Default**:
  - `app/match/[id]/page.tsx` is an async React Server Component (`export const dynamic = "force-dynamic"`, `export const runtime = "nodejs"`). Renders semantic HTML, breadcrumbs, structured SEO JSON-LD (`generateSportsEventJsonLd`), and exactly one `<h1>` (`matchupLabelFor(...)`, resolving DEBT 163 U15).
- **Client Dynamic Import Boundaries**:
  - `FullAnalysisSection` dynamically loads `FullAnalysisDashboard` with `{ ssr: false, loading: () => <FullAnalysisSkeleton /> }`. Keeps shared first-load JS at **103 kB** and route JS at **173 kB** (DEBT 158).
- **Distributed Trace Context Propagation (DEBT 167)**:
  - Next.js proxy route handlers (`/api/predict`, `/api/upcoming`) propagate incoming `x-request-id`, `traceparent`, and `tracestate` headers to FastAPI via `proxyHeaders(request)`, ensuring end-to-end W3C distributed trace correlation.

---

### 3.2 Strict Prohibition of Client-Side Betting Math

Enforced by [`apps/web/src/lib/no-client-ev-contract.test.ts`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/apps/web/src/lib/no-client-ev-contract.test.ts). An automated AST scan scans every TypeScript file in `apps/web/src/` to guarantee that no browser code executes odds calculations:
```typescript
const ODDS_ARITHMETIC = [
  /\b1(?:\.0)?\s*\/\s*\(?[\w.?]*odds\w*/i, // 1 / odds -> implied probability
  /[\w.?)\]]*odds\w*\s*-\s*1(?![\d.])/i,  // odds - 1 -> Kelly denominator / net odds
  /\*\s*\(?[\w.?]*odds\w*/i,              // p * odds -> EV calculation
];
```
FastAPI is the sole authority for de-vigging, EV, and Kelly sizing; the frontend merely projects backend fields.

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
Decision state is **never communicated by color alone**:
- `PLAY`: Text "Play" + `CheckCircle2` icon + emerald token (`--state-play`).
- `PASS`: Text "Pass" + `MinusCircle` icon + slate token (`--state-pass`).
- `WITHHELD`: Text "Withheld" + `CircleDashed` icon + neutral dark slate token (`--state-withheld`).
All indicators survive 100% grayscale and all forms of color-vision deficiency.

---

### 3.4 Probability Visualization Strategy (True vs. Implied)

#### 1. `ProbabilityDumbbell` ([`apps/web/src/components/probability-dumbbell.tsx`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/apps/web/src/components/probability-dumbbell.tsx))
Rendered as an accessible inline SVG (`viewBox="-2 0 104 30"`), adding 0 bytes of external charting dependencies:
- **Model Probability ($p_k$)**: Rendered as a filled circle ● at $x = p_k \times 100$. Filled with `--state-play` (emerald) ONLY if `stakePermitted && edge > 0`; otherwise filled with `--state-withheld` (neutral slate).
- **Fair De-vigged Probability ($\text{fair}_k$)**: Rendered as a hollow circle ○ at $x = \text{fair}_k \times 100$ (`fill-slate-950 stroke-[hsl(var(--state-withheld))]`).
- **Break-Even Implied Probability ($1/O_k$)**: Rendered as a vertical tick line `|` across the track (`stroke-slate-400`). Drawn on top so it is never obscured.
- **Horizontal Gap Bar**: Connects $\text{fair}_k$ to $p_k$.
- Legend: `● model  ○ fair  | break-even`.

#### 2. `MarketComparisonTable` ([`apps/web/src/components/full-analysis-dashboard.tsx`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/apps/web/src/components/full-analysis-dashboard.tsx#L1037))
Accessible companion table displaying Outcome, Bookmaker Price ($O_k$), Fair Market Probability ($\text{fair}_k$), Model Probability ($p_k$), Gap ($p_k - \text{fair}_k$ in pp), and Expected Return per unit staked ($EV$).

**The Decisive Truth Rule**:
If the active model generation is uncertified:
- The edge gap is rendered in neutral slate (`text-slate-300`).
- Expected Return is suppressed (`—`).
- The table renders the mandatory disclosure:
  > *"This model has not passed certification against the market, so a gap here is not evidence of value and no expected return is shown."*
- Staking display: In `OddsEdgeCard`, Kelly stake displays `"Withheld"`, **never `0.00%`**.

---

### 3.5 Disjoint Decision States & Headline Logic

In [`apps/web/src/lib/full-analysis-contract.ts`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/apps/web/src/lib/full-analysis-contract.ts) (`mapFullAnalysisPresentation`), the decision state maps to three strictly disjoint categories:

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

Implemented in `CounterCase` ([`apps/web/src/components/full-analysis-dashboard.tsx:422`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/apps/web/src/components/full-analysis-dashboard.tsx#L422)):
- **Unconditional Display**: Renders whenever a forecast exists, including on `PLAY` recommendations.
- **Visual Styling**: Muted amber frame (`border border-amber-500/20 bg-amber-500/[0.04]`), heading `Why this might fail`.
- **Structured Evidence Chain (in strict order)**:
  1. **Loss Probability**: `"The model gives {outcome} a {p}% chance, so it loses {1 - p}% of the time."`
  2. **Market Movement**: Discloses price movement from earliest sighting to current snapshot (`"The price for {outcome} moved from {first} to {current} since SabiScore first saw it at this bookmaker ({time} WAT)."`).
  3. **Uncertified Edge Warning**: `"The model puts {outcome} {edge}pp above the fair market price, but it has not passed certification against the market, so that gap is not evidence of value."`
  4. **Epistemic Uncertainty**: States credible interval (`"Model uncertainty interval: {low}% to {high}%."`) or plainly discloses `"Model uncertainty is unavailable for this fixture; no interval is inferred."`
  5. **Live Calibration Threshold**: Discloses that calibration is evaluated only after 200 forecasts settle.
  6. **Advisory Gaps**: Enumerates non-blocking missing inputs (`"{count} non-blocking inputs are missing, which makes this forecast less reliable."`).

---

# Section 4: NEXUS Agent Orchestration

### 4.1 Strict Operational Boundary

> **LLM agents NEVER execute inside production calibration, settlement, CLV capture, or data ingestion loops.**

- **Production Loops**: Pure, deterministic Python `asyncio` background tasks inside [`backend/src/api/main.py`](file:///c:/Users/UBEC-DC-ANAMBRA/Documents/sabiscore/backend/src/api/main.py).
- **Agent Operating Domain**: Offline development, quantitative research, model training protocol design, code modification, and automated audit cycles.

---

### 4.2 Supervisor-Worker Hierarchy & File-and-Hash Handoffs

```text
Supervisor (Lead session: NEXUS intent classifier, owns Git branch, PR, and heavy gate execution)
├── Planner (Architect: read-only; authors protocol.json, computes SHA-256, freezes protocol)
├── Worker / Implementer (Code & test author; restricted to assigned file slice; runs light checks)
├── Evaluator (QA-Verifier: applies frozen decision rules mechanically; executes test suites)
```

#### Protocol Handoff Rules
1. **Zero Implicit Memory**: Agents communicate strictly through version-controlled files in `docs/`, `reports/`, and Git diffs.
2. **Digest Verification**: A downstream agent must verify the SHA-256 digest of an upstream artifact before consuming it. If the hash mismatches, execution halts immediately.
3. **No Cross-Role Mutation**: A Planner may not edit code; an Implementer may not modify a frozen protocol or promotion gate; an Evaluator may not relax an assertion to manufacture a passing run.

---

### 4.3 8GB RAM Protection in Multi-Agent Execution

1. **Max Concurrency = 1**: Heavy processes (`pytest`, `train_on_real_matches.py`, `next build`) are strictly serialized. Spawning concurrent workers running local heavy tasks is prohibited.
2. **Subagent Task Scoping**: Each subagent prompt must specify the exact, minimal file paths and functions it is authorized to touch. Broad "refactor the codebase" tasks are forbidden.
3. **Heavy Process Serialization via `ResourceGuard`**: All heavy test suites or training runs execute inside `ResourceGuard` (`SABISCORE_MAX_RSS_MB=3072`), guaranteeing that the host OS never exhausts physical RAM.

---

### 4.4 Automated Model Calibration & Backfill Pipeline

When backfilling historical match data or running periodic offline model retraining:
1. **Data Backfill Job**:
   - Ingests chronological fixture CSVs via `football-data.org` archives.
   - Computes 68-dimensional `apex_v1_68` feature vectors with strict point-in-time timestamping.
   - Appends to PostgreSQL fixture and feature store tables using paginated bulk copy (`yield_per=500`).
2. **Model Training & Platt Fitting**:
   - Executes sequentially across the 6 domestic leagues under `ResourceGuard` (single heavy job).
   - Fits Random Forest, XGBoost, and LightGBM base learners on train split (`1920-2324`).
   - Fits Logistic Regression stacking meta-model on calibration split (`2425`).
   - Fits closed-form Platt scaling calibrator.
   - Evaluates strictly on chronological holdout season (`2526`).
3. **Shadow Manifest Generation**:
   - Generates candidate generation manifest (`backend/models/candidate_generation.json`).
   - Evaluates C6 baseline against historical Pinnacle closing lines.
   - Promotes candidate to `active_generation.json` ONLY if all frozen promotion gates pass.

---

# Section 5: Authoritative Operational Verification Matrix

The authoritative release verification matrix is implemented in `scripts/verify-directive-v17.mjs` and verified through `pnpm verify:directive`:

| Step | Verification Target | Command & Configuration | Acceptance Criteria |
| :-: | :--- | :--- | :--- |
| **1** | Memory Watchdog (D1) | `python -m pytest backend/tests/unit/test_resource_guard.py -v -c backend/pytest.ini` | ResourceGuard terminates rogue child trees and traps `SIGKILL` |
| **2** | Cgroup Headroom Reader | `python -m pytest backend/tests/unit/test_instance_memory.py -v -c backend/pytest.ini` | Accurately reads `/sys/fs/cgroup/memory.current` with $\ge 50$ MB headroom |
| **3** | Single-Lane Serialization (S3) | `python -m pytest backend/tests/unit/test_heavy_jobs.py -v -c backend/pytest.ini` | Heavy job lock rejects concurrent execution with HTTP 409 / lock error |
| **4** | Active League Artifacts | `python -c "import json; m=json.load(open('backend/models/active_generation.json')); assert sorted(m['artifacts'].keys()) == ['bundesliga','epl','eredivisie','la_liga','ligue_1','serie_a']"` | All 6 canonical domestic leagues defined with metadata and artifact SHAs |
| **5** | Platt Scaling Sigmoid Arithmetic | `python -m pytest backend/tests/unit/test_calibrator_load_and_preflight.py -v -c backend/pytest.ini` | Closed-form $\text{logit} = \text{clip}(w \cdot p + b, -30, 30)$ verified |
| **6** | Shin De-Vigging Bisection (G18) | `python -m pytest backend/tests/unit/test_market_baseline.py -v -c backend/pytest.ini` | Inversion converges to tolerance $10^{-12}$ in $<200$ iterations |
| **7** | Frozen C6 Protocol SHA-256 | `python -m pytest backend/tests/unit/test_c6_protocol_frozen.py -v -c backend/pytest.ini` | Hash matches `9d63da25...` identically |
| **8** | No Client-Side Betting Math | `pnpm --filter @sabiscore/web test src/lib/no-client-ev-contract.test.ts` | Zero odds arithmetic in web AST scan |
| **9** | Responsible Gambling Copy | `pnpm --filter @sabiscore/web test src/lib/copy-contract.test.ts src/lib/evidence-copy-contract.test.ts` | Zero banned promotional terms (`lock`, `banker`, `guaranteed`) |
| **10** | Single `<h1>` Heading Contract | `pnpm --filter @sabiscore/web test src/lib/heading-contract.test.ts` | Exactly one `<h1>` per consumer route |
| **11** | Dumbbell & Dashboard UI | `pnpm --filter @sabiscore/web test src/components/probability-dumbbell.test.tsx src/components/full-analysis-dashboard.test.tsx` | True/fair/implied dumbbell and tri-state indicators pass rendering assertions |

```text
══════════════════════════════════════════════════════════════════════
SUMMARY: 11 PASSED, 0 FAILED out of 11 verification steps
══════════════════════════════════════════════════════════════════════
✓ All Directive V17.0 Attestation & Verification Checks PASSED.
```
