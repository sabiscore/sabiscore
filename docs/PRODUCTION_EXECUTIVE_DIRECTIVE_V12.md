# SabiScore — Production Executive Directive v12.0

### Delta on v11: a deploy that could not recover from one failed ping, a frozen judge waiting for its first data, and the round that starts on 9 Oct

Date: 2026-09-27 (evening). v8 §1–§7 and v9–v11 stay in force. v12 replaces v11's §0 evidence and
§5 execution order. The work behind it is `docs/DEBT.md` items 161 and 162. Every number below was
measured on 27 Sep; estimates say so.

The brief is the one v8–v11 answered. Against today's numbers:

| Brief says | Measured 2026-09-27 | Consequence |
| --- | --- | --- |
| Node.js workers ingest the data | No Node process runs. Ingestion is Python asyncio inside the API process: fixture sync (6 h), market capture (5 min), prediction capture (5 min), settlement (hourly), evidence retention (hourly). The scraper cron is disabled (OG-04) and heap-capped at 384 MB. | No Node memory work until an operator enables the scraper (§1.4). |
| 8 GB Windows is the absolute limit | Serving runs in a **512 MB cgroup**: working set 327 MB, anon 304 MB, headroom 184 MB after 19.4 h up. Locally, heavy gates ran one at a time. | Budget production changes against the peak headroom during a burst; budget local work one heavy process at a time. |
| XGBoost, LightGBM and logistic regression, validated by ECE, Brier and walk-forward | Served: random forest + XGBoost + LightGBM → stacked softmax head → sigmoid calibrator, schema `apex_v1_68`, six league artifacts. Item 142 is still open: the calibrator was fitted on a different composition. 0 settled forecasts under the served identity. | No serving change. The first live measurement comes at 200 settled (§2.3). |
| Probabilities stay sharper than the market closing line value (CLV) | "Sharper than the close" and CLV are different measurements. C6, frozen today, measures sharpness: paired RPS against the de-vigged Pinnacle close. CLV needs a price that was actually taken, and none is. | C6 is the only sharpness test. CLV is reported only, never evidence (§2.4). |
| A continuous calibration loop | C6 forbids refitting or recalibrating after any result. v11 §2.4: no job or agent refits, recalibrates or promotes. | The loop measures continuously and decides at milestones (200, 500, 1,000), by the operator. |
| Show potential ROI and fractional-Kelly units | No stake has ever been placed, so there is no ROI to measure. Staking is off: `basis: NONE`, `UNVERIFIED`. | Show expected return per unit staked, only when the backend returns it. The stake comes from the backend only (§3). |
| Every insight ends in Play or Pass | Every fixture is Withheld, because the generation is uncertified. | Keep all three states. Pass is reachable at certification; Play also needs the market baseline (0 of 6 leagues). |
| Agents automate calibration and backfills | Agents never refit, recalibrate, move a threshold, promote a generation, edit the certification state or edit the frozen protocol. A forecast is never backfilled after kickoff. | Agents automate measurement, reporting and evidence backfill only (§4). |

---

## 0. Evidence (measured 2026-09-27, 18:57–20:35 UTC)

| Fact | Value | Source |
| --- | --- | --- |
| #251 merged | `f6e9063`, 18:57 UTC. All 14 CI checks passed, SonarCloud included. | GitHub |
| Web | Serves `f6e9063`. Every page's server HTML now carries its headings; before, it was a lone spinner. | `/api/health`, page HTML |
| **Backend deploy of `f6e9063`** | **Failed.** The build succeeded (6 artifacts verified). Startup completed at 20:12:40, 94 s after "Deploying". Then `/health/ready` answered 503 every 10 s until "Timed Out" at 20:26:07, and Render kept `b8d3a4c`. The new instance logged `external Redis unavailable`; the old one reports Redis connected. | Render log, `/health` |
| Root defect | `RedisCache.__init__` pinged Redis once and set `redis_client = None` for the life of the process on failure. `production_ready()` returned False while it was None, so a single failed ping kept readiness at 503 until Render gave up. Fixed in DEBT 162. | code |
| Why the first ping failed | **Unknown.** The deploy log's `Redis unavailable at …: <reason>` line was not in the excerpt. | — |
| Not yet live on the backend | #251's named sign-in rejections, U12's withheld interval, and the C6 reader code | — |
| Memory, serving instance | RSS 325, working set 327, anon 304, headroom 184 MB, after 19.4 h up | `/health` |
| Settled, served identity | 0 (`v5_phase7-20260922@417b9b8ff7ce563d`) | `/health` |
| Staking | `permitted: false`, `basis: NONE`, `UNVERIFIED` | `/health` |
| Odds API | 188 remaining, 312 used, no reset date reported | `/api/v1/providers/evidence` |
| Fixtures in the database | **50, exactly the sync cap**, from 9 Oct 18:00 to 11 Oct 16:30 UTC: EPL 9, Bundesliga 9, Eredivisie 9, Ligue 1 8, La Liga 8, Serie A 7. Later kickoffs enter on later 6-hourly syncs. | `/api/v1/fixtures/upcoming` (`total: 50`) |
| C6 | `PRE-REGISTERED`, sha256 `9d63da25…46ba7`. A test fails on any edit to it. | registry |
| Google sign-in | Google accepts the callback. The backend answers 401 on a claim check; the likeliest cause is a mismatched client ID on Render. | Render log, probe |
| Web first-load JS | 103 kB shared | `next build` |

---

## 1. Resource-constrained data and feature engineering

### 1.1 Budgets

| Where | Budget | Rule |
| --- | --- | --- |
| Production API process | 512 MB cgroup; working-set headroom ≥ 100 MB at the burst peak (v11 M2) | Read headroom from `cgroup_working_set_mb`, never from raw `cgroup_current_mb`, which includes reclaimable page cache. |
| Local Windows, 8 GB | One heavy process at a time: the backend suite, `next build`, Playwright and mypy each run alone. The backend suite runs in the background, writing to a log. | Never overlap two of these. `NODE_ENV=production` for every build. |
| Node scraper (dormant) | `--max-old-space-size=384` | Stays off until OG-04. |

### 1.2 Work items

| ID | Item | Acceptance |
| --- | --- | --- |
| **R1 (P0)** | Tier-1 Redis reconnects: readiness retries a failed connection at most once per 30 s (DEBT 162). | The next backend deploy goes live. If it still fails, read the log's `Redis unavailable at …: <reason>`. `max number of clients reached` means the two overlapping instances exceed the Redis plan's connection cap; lowering `redis_max_connections` (default 50) is then an O9 decision. |
| R2 | Fixture coverage. The sync keeps the 50 earliest kickoffs across all competitions (`limit=50`); the slicing is local, one provider request per competition. | After 11 Oct, check that every fixture of the round was in the database by kickoff − 3 h, the start of the capture window. If any was not, raise the cap to 100: no extra requests, about 50 more rows. It changes coverage, not C6's population definition. |
| R3 | Read the burst (M2), after the last kickoff each day: `python scripts/read_capture_burst.py --since 2026-10-09T15:00:00Z` from `backend/`. | PASS, or a named failure: missed capture, headroom < 100 MB, or a restart. |
| R4 | Odds API budget (M3, O7). Per league per kickoff slot: CLV capture takes about 2 requests and prediction capture about 1, each costing 2 credits (`uk,eu`). About 25 league-slots per round is roughly 150 credits, an estimate; page views are extra. | Record quota before and after the round and project the month. **Halving regions is now a C6 population change and forbidden.** A plan change or the reset date are the only levers. |

### 1.3 Historical and live data, six leagues

| Stage | Where | Memory note |
| --- | --- | --- |
| Historical corpus | `backend/data/cache/fd_*.csv`, 12,765 matches in 36 files, about 11 MB | Loaded once at boot; the log says "no new matches" when nothing changed. Too small to need chunking. |
| Elo | PostgreSQL `elo_rating_snapshots`, 26,192 rows, 222 teams | Read per fixture, never loaded whole. |
| Fixture sync | football-data.org, 6 h, 50-fixture cap | R2 |
| Market capture | The Odds API board per league, every 5 min while a fixture is ≤ 10 min from kickoff; Pinnacle first | Fresh by design: a close must be the last pre-kickoff observation. |
| Prediction capture | `get_full_analysis`, every 5 min for fixtures in [kickoff − 3 h, kickoff − 15 min] | Shares the 120 s board cache with page views. |
| Settlement | hourly, scoped to the served identity | — |
| Offline research | Understat and StatsBomb corpora, local | One league-season at a time; never at serving time. |

### 1.4 Node, if an operator enables it

The scraper stays batch-only: raw snapshots plus manifests. It never computes probabilities, EV or
stakes (CLAUDE.md). If OG-04 enables it:
- stream each competition-season as JSON lines;
- write each page to disk before fetching the next;
- run with `--max-old-space-size=384 --heapsnapshot-near-heap-limit=1`;
- profile with one `--heap-prof` run per source before scheduling it.

---

## 2. Model serving and pipeline refinement

### 2.1 Serving: unchanged

One process serves six artifacts. The startup log reads "PredictionEngine cache reused 6/6 validated
league models". Scheduled capture calls the endpoint's own analysis path, so it adds no model load.
Do not add a model server, ONNX or a second worker: with 184 MB of headroom, a second copy of the
models does not fit.

### 2.2 The readiness contract (new)

Render deploys only after `/health/ready` answers 200. A startup failure in any dependency must
therefore be recoverable inside the deploy window (about 14 minutes), or the deploy fails silently
while CI is green.

| Dependency | Before | Now |
| --- | --- | --- |
| Redis (tier 1) | One ping at import; a failure was permanent | Retried by readiness, at most once per 30 s |
| Database | Checked on every readiness call | unchanged |
| Models | Loaded at startup; strict | unchanged |

After every merge that touches `backend/`, confirm `/health` → `sha` equals the merge SHA. If it has
not changed within 45 minutes, read the Render deploy log. Do not assume a slow build.

### 2.3 The calibration loop, as it stands

| Step | State | Next |
| --- | --- | --- |
| Capture | Live; forecast-time price on the Pinnacle-first book | First round 9–11 Oct |
| Close | Strict pre-kickoff snapshot, Pinnacle first | Check on 9 Oct that closing rows carry `bookmaker = pinnacle` wherever Pinnacle quotes |
| Judge | **C6 frozen:** 10,000 replicates, seed 42, a 98.33% decision interval with the 95% beside it, `interactive_full_analysis` rows only | — |
| Measure | Milestones at 200, 500 and 1,000 settled forecasts with a close | 200 is about four rounds away: the first week of November, an estimate |
| Decide | The operator, at milestones only | Item 142 (calibrator composition) waits for an operator decision, using season-2425 selection evidence |

Between milestones, `/model-performance` shows only the joined count (U12). The milestone run is
local, by a person. It calls `get_clv_records(..., capture_trigger='interactive_full_analysis')`
and then `week_cluster_ci(..., n_boot=10000, seed=42, alpha=0.05 / 3)`.

### 2.4 CLV, correctly named

True CLV is `ln(o_taken / o_close)` and needs a taken price. The forecast-time price is stored in
`payload.recommendation_market`, but no price is taken while staking is off. At 200, report the
price movement from the forecast-time price to the Pinnacle close for the recommended outcome, labelled
"price movement", not CLV. It is reported only, never evidence, and it is not part of C6.

---

## 3. Quantitative UX and actionable insights (Next.js 15)

### 3.1 The decision card, as built and live

- **One headline state per card.** Play, Pass or Withheld; the verdict tier sits in the evidence
  line.
- **Model vs fair market.** Per outcome: the model's probability, the de-vigged fair price and the
  gap in percentage points, drawn as a dumbbell on dark tokens (model ●, fair ○, break-even |).
- **Gap colour follows `stake_permitted`, not the sign.** While the generation is uncertified, the
  table says a gap is not evidence of value, and no expected return is shown.
- **Why this might fail.** Always shown when a forecast exists: the losing probability, the
  uncertified gap, the calibration status and the count of missing inputs.
- **Evidence passport.** The market row names the book and capture time of the displayed price.

### 3.2 The contract (unchanged; restated because the brief asks for it)

| Element | Source | Shown when |
| --- | --- | --- |
| True probability | backend `probabilities` | a forecast exists |
| Implied (fair) probability | backend de-vigged market | a coherent 1X2 price exists |
| Expected return per unit | backend `expected_value` | the fixture is evaluable and the generation certified; otherwise hidden, never zero |
| Stake | backend, quarter-Kelly under the league cap | `stake_permitted`; never computed in the browser (`no-client-ev-contract.test.ts`) |
| Play | backend | `stake_permitted` and EV > 0 |
| Pass | backend | evaluable, no value |
| Withheld | backend | not evaluable; never merged with Pass |

### 3.3 Open items

| ID | Item | Acceptance |
| --- | --- | --- |
| U15 | Every page has two `<h1>`: the workspace header's "Prediction and market intelligence" and the page title. This became visible once pages rendered on the server. Make the header a non-heading with the same styling. | One `<h1>` per page, pinned by a server-render test. |
| U16 | The passport's Elo row reads "RESOLVED" beside "1 field missing". The missing field is `elo_league_adjusted`, a permanent gap by policy. Label it as an advisory field, or leave permanent gaps out of the count. | The row never pairs RESOLVED with an unqualified "missing". |
| U17 | After the backend deploys: the sign-in error names configuration when the client IDs differ, and `/model-performance` shows `skipped: true, milestone: 200`. | Both read live. |

---

## 4. NEXUS agent orchestration

Production loops stay in-process asyncio tasks. Agents work at development time.

### 4.1 What this pass taught

- **Green CI does not mean deployed.** #251 passed every check, and then the backend deploy timed
  out on readiness. Verify `/health` → `sha` after every merge.
- **Revert checks use `git stash`.** A reversible-looking `sed` rewrote a second, original line.
- **A dependency failure that never retries is a deploy failure waiting for a cold start.** Every
  one-shot startup connection needs a retry path that readiness can drive.

### 4.2 Roles and handoffs (8 GB)

| Role | Does | Memory rule |
| --- | --- | --- |
| Supervisor (the lead session) | Routes via NEXUS, owns the branch and the PR | Runs the heavy gates itself, one at a time |
| Planner (`architect`) | Read-only design: file ownership, interfaces | Reads files only |
| Worker (`implementer`) | One file set per worker | At most one worker runs a heavy command at a time |
| Evaluator (`qa-verifier`) | Runs tests independently, reports failures to the owning worker | Owns the heavy-gate slot while it runs |
| Reviewer | Reviews the diff with confidence filtering | Read-only |

Handoffs are files, never agent memory: the `docs/DEBT.md` item, the directive status table, the
PR body and `reports/` JSON. Subagents start cold and cost a re-read, so spawn them only on an
explicit request.

### 4.3 Automations (development time; they measure, never change a model)

| ID | Automation | Cadence | Output |
| --- | --- | --- | --- |
| A1 | Settled-count watcher: reads `/health` settlement | weekly | Notifies at 200, 500 and 1,000; evaluates nothing |
| A2 | Post-merge deploy check: `/health` `sha` against the merge SHA | after each merge, up to 45 min | Notifies on mismatch, with a pointer to the Render deploy log |
| A3 | Burst reader: `read_capture_burst.py` | after the last kickoff of each round day | M2 verdict and quota |
| A4 | Quota watcher: The Odds API `remaining` | daily | Notifies below 100 and below 40 |

**Allowed backfills:** a new season's results CSV (by PR), and Elo replay over settled matches.
**Forbidden:** backfilling a forecast or a close for a fixture that has kicked off, refitting,
recalibrating, moving any threshold, editing the certification state, and editing the C6 protocol.

---

## 5. Execution order and operator decisions

| Phase | Work | Done when |
| --- | --- | --- |
| 0: now | Merge DEBT 162 (Redis reconnect and this directive). | Backend `/health` `sha` equals the merge SHA and readiness is 200. If readiness stays 503, read the Redis reason line (R1). |
| 1: before 9 Oct 15:00 UTC | Render `GOOGLE_OAUTH_CLIENT_ID` equals Vercel's `AUTH_GOOGLE_ID`, without quotes. The Odds API reset date or plan (O7). Confirm C6 (c), the sample cut, which took the recommendation. | One sign-in succeeds or logs a named reason. Quota covers about 150 credits for the round. |
| 2: 9–11 Oct | R3 after each round day. R2 coverage check. Check that closing rows are Pinnacle. | M2 verdict recorded; fixture coverage recorded. |
| 3: after the round | U15–U17; the R2 decision; the M3 monthly projection. | — |

**Operator decisions:**
- **O2 is done.** Google accepts the callback. What remains is the Render client ID (Phase 1).
- **O7 is urgent.** 188 credits are left. Rotating the key adds none.
- **O8 is done.** C6 is frozen. Confirm (c) before the first capture if you wanted a different cut.
- **O9 (new, only if R1 shows a connection-cap error):** the Redis plan or `redis_max_connections`.
- O1 (keep the instance awake) and O4 (certification, item 142) are unchanged.

**Status, 2026-09-28 (DEBT 163):**
- Phase 0 is done. The backend serves `369bd9d` with readiness 200 and Redis connected.
- The Google half of Phase 1 is superseded. The 401 was python-jose's default `at_hash` check,
  not a client-ID mismatch, and is fixed in code. The client IDs need no change unless the log
  names an audience mismatch after that deploy.
- U15, U16 and U17 are closed.
- R3: a low headroom with a flat `cgroup_anon_mb` is page cache, not a failure.
