# SabiScore — Production Executive Directive V15.0

**Author**: Multi-Agent Engineering Council (Architecture, Quantitative Modeling, Frontend Systems, Orchestration)  
**Date**: 2026-09-30  
**Status**: ACTIVE / MANDATORY PRODUCTION DIRECTIVE  
**Supersedes**: Directive V14.0 (`docs/PRODUCTION_EXECUTIVE_DIRECTIVE_V14.md`), Directive V13.0, and all predecessor directives.  
**Ground Truth Authorities**: `docs/DEBT.md` (Items 1–167), `backend/src/api/main.py`, `backend/models/active_generation.json`, `apps/web/src/`, `NEXUS.md`, `AGENTS.md`.

---

## Executive Summary & Core Mandate

This directive establishes the authoritative operational, quantitative, and architectural governance for the SabiScore platform. SabiScore is a quantitative football intelligence and predictive modeling engine operating under a strict positive expected value (+EV) and capital preservation philosophy. 

All systems, agents, and engineers must strictly adhere to four non-negotiable architectural realities:
1. **Physical Resource Boundaries**: The production backend operates in a **512 MB cgroup v2 Linux container** on Render's free tier (`working_set` = 337–442 MB, leaving 69–174 MB operational headroom). Developer workstations and CI runners operate under an **8,192 MB (8 GB) local memory budget**, where heavy execution (training, full test suites, production builds) is serialized behind a single-process 3.0 GB ceiling enforced by `ResourceGuard` (`SABISCORE_MAX_RSS_MB=3072`), while native ML C-extensions are clamped to single-thread kernels (`OMP_NUM_THREADS="1"`, `MKL_NUM_THREADS="1"`, DEBT 167).
2. **In-Process Python Ingestion vs. Constrained Offline Worker**: Real-time acquisition is driven entirely by asynchronous Python lifespan loops in `backend/src/api/main.py`. The Node.js crawler in `apps/scraper/` is exclusively an offline, batch-oriented data acquisition tool, deactivated in production (`SCRAPER_PRODUCTION_ENABLED="false"`), and constrained by `--max-old-space-size=384` and `CRAWLEE_MEMORY_MBYTES=512`.
3. **Rigorous Model Calibration & Market Superiority**: Predictions for the 6 canonical domestic leagues (EPL, La Liga, Bundesliga, Serie A, Ligue 1, Eredivisie) are served by `PredictionEngine` using stacked ensemble models (Random Forest, XGBoost, LightGBM, and Logistic Regression meta-models) consuming only 11 MB of disk storage and 55 MB of resident heap, with an expanded 8-model in-memory cache (`MAX_CACHED_MODELS=8`, DEBT 167) preventing LRU eviction churn. Model sharpness is continuously evaluated against Pinnacle closing lines via the pre-registered, frozen C6 Protocol using paired $\Delta RPS$ with ISO-week cluster bootstrapping (10,000 replicates, $\alpha = 0.05/3 = 0.016667$) at sample milestones of 200, 500, and 1,000 settled forecasts.
4. **Deterministic UX & Zero-Fabrication Philosophy**: The Next.js 15.5.6 + React 18.3.1 frontend is strictly a projection layer with W3C distributed trace propagation (`proxyHeaders(incoming)`, DEBT 167). The browser is mathematically prohibited from computing odds arithmetic, implied probabilities, Expected Value, or Kelly stake sizing (`no-client-ev-contract.test.ts`). Every forecast displays the true vs. fair vs. implied probability dumbbell, a distinct tri-state verdict (`PLAY`, `PASS`, or `WITHHELD`), and a mandatory counter-case panel ("Why this might fail") disclosing loss probability ($1 - p_k$), market price movement, uncertainty bounds, and non-blocking advisory gaps.

---

# Section 1: Resource-Constrained Data & Feature Engineering

### 1.1 Ingestion Reality: Python Asyncio vs. Offline Node.js Scraper

A fundamental architectural invariant of SabiScore is that **no Node.js worker or crawler runs in the live ingestion loop**. 

Production ingestion is executed entirely in-process by the FastAPI application runtime (`backend/src/api/main.py`) via async lifespan background tasks initialized during server startup:

```
FastAPI Application Lifespan (Python 3.11/3.14, Single Uvicorn Worker)
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
- **Distributed Lease Locking**: During rolling deployments on Render, two container instances temporarily overlap. To prevent concurrent executions from double-billing paid API quotas (The Odds API, football-data.org) or triggering HTTP 429 rate limits, `fixture_sync_service.py` acquires an atomic distributed lease key in Redis (`sabiscore:job:fixture_sync:lease`, TTL 600s) using a Lua script before initiating synchronization:
```lua
if redis.call('set', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2]) then
  return 1
else
  return 0
end
```

---

### 1.2 Mathematical Allocation of 8GB Local Workstation Memory

Local engineering environments (Windows 11 / Linux developer workstations, CI runners) are strictly budgeted within an **8,192 MB (8.0 GB)** physical RAM ceiling. Heavy execution must not induce OS paging or out-of-memory thrashing.

#### Local Workstation Memory Budget Table (8,192 MB Total)

| Subsystem / Process | Target Allocation | Peak Ceiling | Accounting & Operational Rules |
| :--- | :---: | :---: | :--- |
| **Host OS & Desktop Environment** | **3,500 MB** | 3,800 MB | Windows 11 / Linux desktop manager, kernel, background services, shell terminals, VS Code, and `tsserver` (`typescript.tsserver.maxTsServerMemory <= 3072`). |
| **Local PostgreSQL 16** | **350 MB** | 512 MB | Native or lightweight container: `shared_buffers = 128MB`, `work_mem = 4MB`, `max_connections = 50`. |
| **Local Redis 7** | **150 MB** | 256 MB | In-memory key-value store: `--maxmemory 256mb`, `--maxmemory-policy allkeys-lru`. |
| **FastAPI Backend Runtime** | **455 MB** | 650 MB | Python runtime (42 MB) + Scientific ML stack (135 MB) + 6 unpickled league ensembles (55 MB resident heap) + DB/Redis connection pools (15 MB). Single-thread clamped (`OMP_NUM_THREADS="1"`). |
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
- **Parallelism Clamping (`SABISCORE_MAX_JOBS`)**: Scikit-learn defaults to `n_jobs=-1`, which spawns one worker process per CPU core, duplicating memory. In `train_on_real_matches.py` (lines 1464–1466), `n_jobs` is clamped to `SABISCORE_MAX_JOBS` (default: **2** locally).
- **Single-Thread Runtime Clamping (DEBT 167)**: `OMP_NUM_THREADS="1"`, `OPENBLAS_NUM_THREADS="1"`, `MKL_NUM_THREADS="1"`, `VECLIB_MAXIMUM_THREADS="1"`, `NUMEXPR_NUM_THREADS="1"` set at the entrypoint of `backend/src/api/main.py` prevent CPU thread context switching overhead and memory fragmentation.
- **Sequential League Training (Directive D4)**: Training across the 6 leagues executes sequentially with explicit `del bundle` and `gc.collect()` between leagues, guaranteeing peak RSS remains under 3.0 GB.

---

### 1.3 Node.js Worker & Scraper Memory Profiling

The scraper in `apps/scraper/` is packaged via `Dockerfile.worker` and scheduled as a bi-weekly cron job (`"0 3 * * 1,4"` in `render.yaml`). It is strictly gated by `SCRAPER_PRODUCTION_ENABLED="false"`. If enabled by operator approval (OG-04), it must adhere to strict profiling and execution constraints:

```yaml
# render.yaml lines 221-226
- key: NODE_OPTIONS
  value: "--max-old-space-size=384 --heapsnapshot-near-heap-limit=1"
- key: CRAWLEE_MEMORY_MBYTES
  value: "512"
```

1. `CRAWLEE_MEMORY_MBYTES=512`: Instructs Crawlee's `AutoscaledPool` of the host container limit so it throttles internal request queues.
2. `--max-old-space-size=384`: Hard-caps the V8 JavaScript heap at 384 MB, guaranteeing $512\text{ MB} - 384\text{ MB} = 128\text{ MB}$ of container headroom for native C++ bindings, libuv thread pools, and OpenSSL buffers.
3. `--heapsnapshot-near-heap-limit=1`: Directs V8 to write an emergency heap snapshot file to disk immediately prior to an out-of-memory crash.
4. **Single Concurrency & Zero Session Pool**: In `apps/scraper/src/http.mjs` (lines 43–56), `PublicHttpClient` constrains Crawlee to:
   - `minConcurrency: 1`, `maxConcurrency: 1`, `maxRequestsPerCrawl: 1`
   - `sameDomainDelaySecs: 3`, `maxRequestsPerMinute: 6`, `maxRequestRetries: 2`
   - `useSessionPool: false`
5. **In-Process Request Boundary Sampling (`sampleHeap`)**: In `apps/scraper/src/storage.mjs` (lines 389–425), `sampleHeap()` samples `process.memoryUsage().heapUsed` across request lifecycle hooks. Every generated manifest records measured `peak_rss_mb` and `peak_heap_used_mb`.

---

### 1.4 Data Chunking and Streaming Architecture

#### The 200 MB File Chunking Trigger Rule (Directive D6 & DEBT Item 88)
SabiScore's entire 6-league historical training corpus (`backend/data/cache/fd_*.csv`) comprises 36 CSV files totaling **6.0 MB on disk** (~11 MB uncompressed, 12,765 matches). Peak traced RAM during evaluation is under 1.0 MB (0.617 MB).

**The Directive Rule**:
- **Chunking is a trigger, not a universal mandate.**
- If an individual dataset file exceeds **200 MB**, loaders must switch `pandas.read_csv` to `chunksize=...` with explicit `usecols` and downcasted types (`float32` for features, `category` for team identifiers).
- Datasets below 200 MB must be loaded in a single vector operation to minimize interpreter loop overhead.

#### Database Streaming (Directive D5)
When querying historical match archives or Elo state histories, queries must enforce pagination or chunked streaming:
```python
query = select(Match).order_by(Match.match_date.asc()).limit(500)
```
Or when processing unbounded sets:
```python
query = select(Match).execution_options(yield_per=500)
async for partition in (await session.stream(query)).partitions():
    for match in partition:
        process_match(match)
```
This bounds ORM identity map resident memory to 500 instances at a time.

---

### 1.5 The 6 Canonical Target Leagues and UCL Structural Cap

SabiScore predicts and models exactly **6 domestic leagues**:

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

# Section 2: Model Serving & Pipeline Refinement

### 2.1 Calibrated Ensemble Deployment in FastAPI

Model inference in SabiScore is centralized in `backend/src/models/prediction.py` (`PredictionEngine`), managed through `active_generation.py`, and served to API routes.

#### Serving Architecture & Artifact Footprint
- The 6 league ensemble pickles total **11 MB on disk** (~1.8 MB per league).
- Loaded once into memory at boot via `PredictionEngine.prime_cache()`, consuming ~55 MB of resident heap across all 6 leagues.
- Model Cache Sizing (DEBT 167): `PredictionService.MAX_CACHED_MODELS` is set to **8** (expanded from 5), guaranteeing that all 6 domestic leagues and cup models reside in memory without LRU cache eviction churn.
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

#### Closed-Form Platt Scaling (DEBT Item 133)
To achieve permanent stability across Python/scikit-learn runtime versions, `backend/src/models/calibration.py` implements **direct closed-form sigmoid arithmetic**:
$$\text{logit} = \text{clip}\left(w \cdot p + b, \, -30.0, \, 30.0\right)$$
$$P(y = 1 \mid p) = \sigma(\text{logit}) = \frac{1}{1 + e^{-\text{logit}}}$$
Where $w$ and $b$ are extracted as raw NumPy floats from `calibrator.coef_[0]` and `calibrator.intercept_[0]`.

---

### 2.2 Continuous Calibration Loop & Frozen C6 Protocol

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

### 2.3 Market De-Vigging Algorithms

Bookmakers build an overround $\Pi = \sum_{i=1}^3 q_i > 1$ into decimal odds $O_i$, where gross implied probability is $q_i = \frac{1}{O_i}$. SabiScore extracts true fair probabilities $p_i$ through two formal de-vigging algorithms:

#### 1. Proportional Normalization (Active in live API serving paths)
$$p_i = \frac{q_i}{\Pi} = \frac{1 / O_i}{\sum_{j=1}^3 (1 / O_j)}$$

#### 2. Shin's Method (1992, 1993) (Canonical G18 Certification Baseline)
Models prices as equilibrium betting quotes in the presence of an insider trading proportion $z \in [0, 1)$:
$$p_i(z) = \frac{\sqrt{z^2 + 4(1 - z) \frac{q_i^2}{\Pi}} - z}{2(1 - z)}$$
Subject to the exact simplex constraint:
$$\sum_{i=1}^3 p_i(z) = 1$$
- Implemented in `backend/src/models/evaluation/market_baseline.py`.
- **Provable Bisection Convergence**: The residual function $f(z) = \sum_{i=1}^3 p_i(z) - 1$ converges unconditionally to tolerance $10^{-12}$ in under 200 iterations, removing the Favourite-Longshot Bias.

---

### 2.4 Expected Value (+EV) and Fractional Kelly Staking

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

# Section 3: Quantitative UX & Actionable Insights (Next.js 15)

### 3.1 Technology Stack & Architectural Boundaries

- **Pinned Framework Versions**:
  - `next`: `^15.5.6` (App Router)
  - `react`: `^18.3.1` (Strictly pinned in `apps/web/package.json`; upgrading to React 19 is prohibited without council approval)
  - `tailwindcss`: `3.4.14`
  - `recharts`: `^2.15.4` (isolated exclusively to client bundles via `next/dynamic({ ssr: false })`)
- **Server Components (RSC) by Default**:
  - `app/match/[id]/page.tsx` is an async React Server Component with `export const dynamic = "force-dynamic"` and `export const runtime = "nodejs"`. It renders semantic HTML, breadcrumbs, structured SEO JSON-LD (`generateSportsEventJsonLd`), and exactly one `<h1>` (`matchupLabelFor(...)`, resolving DEBT Item 163 U15).
- **Client Dynamic Import Boundaries**:
  - `FullAnalysisSection` dynamically loads `FullAnalysisDashboard` with `{ ssr: false, loading: () => <FullAnalysisSkeleton /> }`. This boundary keeps the shared first-load JS bundle at **103 kB** and route JS at **173 kB** (DEBT Item 158).
- **Distributed Trace Context Propagation (DEBT 167)**:
  - Next.js proxy route handlers (`/api/predict`, `/api/upcoming`) pass incoming `x-request-id`, `traceparent`, and `tracestate` headers directly to FastAPI via `proxyHeaders(request)`, ensuring end-to-end W3C distributed trace correlation.

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

The FastAPI backend is the sole authority for de-vigging, EV, and Kelly sizing; the frontend merely projects backend fields.

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
If the active model generation is uncertified:
- The edge gap is rendered in neutral slate (`text-slate-300`).
- Expected Return is suppressed (`—`).
- The table renders the mandatory disclosure:
  > *"This model has not passed certification against the market, so a gap here is not evidence of value and no expected return is shown."*
- Staking display: In `OddsEdgeCard`, Kelly stake displays `"Withheld"`, **never `0.00%`**.

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

### 4.1 The Strict Operational Boundary

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
     - Full backend test suite (`pytest`, peak ~1.2 GB RSS)
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

To independently verify all architectural claims, constraints, and contracts in this directive, run either the unified single-command matrix runner or the portable individual commands below.

### Option A: Unified Automated Matrix Runner (Recommended)

Executes all 11 verification steps sequentially, automatically resolves local Python/.venv environments, and runs without mutating the terminal's working directory:

```bash
# Via pnpm / npm:
pnpm verify:directive

# Or directly via Node:
node scripts/verify-directive-v14.mjs

# Or in Git Bash / Linux / macOS:
bash scripts/verify-directive-v14.sh
```

### Option B: Individual Verification Commands (Portable & Safe)

```bash
# 1. Verify Memory Watchdog Implementation (D1)
python -m pytest backend/tests/unit/test_resource_guard.py -v -c backend/pytest.ini

# 2. Verify Instance Memory Cgroup Reader & Headroom Calculation
python -m pytest backend/tests/unit/test_instance_memory.py -v -c backend/pytest.ini

# 3. Verify Heavy Job Single-Lane Serialization (S3)
python -m pytest backend/tests/unit/test_heavy_jobs.py -v -c backend/pytest.ini

# 4. Verify Active League Model Artifacts in active_generation.json
python -c "import json; m=json.load(open('backend/models/active_generation.json')); print(list(m['artifacts'].keys()))"

# 5. Verify Platt Scaling Closed-Form Sigmoid Arithmetic (DEBT 133)
python -m pytest backend/tests/unit/test_calibrator_load_and_preflight.py -v -c backend/pytest.ini

# 6. Verify Shin De-Vigging Bisection Inversion & Provable Bracketing (G18)
python -m pytest backend/tests/unit/test_market_baseline.py -v -c backend/pytest.ini

# 7. Verify Frozen C6 Protocol SHA-256 Immutability
python -m pytest backend/tests/unit/test_c6_protocol_frozen.py -v -c backend/pytest.ini

# 8. Verify No Client-Side Betting Math Contract (Vitest AST Scan)
pnpm --filter @sabiscore/web test src/lib/no-client-ev-contract.test.ts

# 9. Verify Responsible Gambling Copy Contract & Banned Term AST Scan
pnpm --filter @sabiscore/web test src/lib/copy-contract.test.ts src/lib/evidence-copy-contract.test.ts

# 10. Verify Heading Contract (Exactly 1 <h1> per page)
pnpm --filter @sabiscore/web test src/lib/heading-contract.test.ts

# 11. Verify Probability Dumbbell and Dashboard UI Components
pnpm --filter @sabiscore/web test src/components/probability-dumbbell.test.tsx src/components/full-analysis-dashboard.test.tsx
```

---
*Signed by the Multi-Agent Engineering Council on this 30th day of September, 2026.*
