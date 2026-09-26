# SabiScore — Production Executive Directive v10.0

### Delta on v9: ship the first real loop round, pre-register how it will be judged, and keep every page statement tied to a measurement

Date: 2026-09-26. v8 (`docs/PRODUCTION_EXECUTIVE_DIRECTIVE_V8.md`) §1–§7 and v9 stay in force.
v10 replaces v9's §0 evidence and §5 execution order. v9's phases 1 and 2 are done in code
(`docs/DEBT.md` item 157) on branch `fix/directive-v9-phase1-2`, which is not yet merged.

**Status, 2026-09-26 evening (superseded by `docs/PRODUCTION_EXECUTIVE_DIRECTIVE_V11.md`):**
- Phase 0 is done: #247 merged as `63f9bf2`, and all four post-deploy checks pass.
- P1 is drafted: C6 is `PROPOSED`, awaiting O8.
- U5–U10 are done (`docs/DEBT.md` item 158).
- Correction to §3: the client Sentry SDK was *not* loaded lazily. `instrumentation-client.ts` imported
  it statically, and that was the 198 kB shared bundle; it is now 103 kB.
- v11 replaces §0 and §5.

The brief behind v10 is the same one v8 and v9 answered, so their corrected premises still hold.
Here they are against today's numbers:

| Brief says | Measured 2026-09-26 | Consequence |
| --- | --- | --- |
| Node.js workers ingest the data | No Node worker runs. `apps/scraper` is batch-only and `SCRAPER_PRODUCTION_ENABLED=false`. Ingestion is Python, in-process: fixture sync (6 h), market capture (5 min), settlement (hourly), prediction capture (5 min, new). | No Node memory work until an operator enables the scraper; its 384 MB heap cap (v8 N1) is already set. |
| 8 GB Windows is the absolute limit | Serving runs in a 512 MB Render cgroup: working set 309 MB, **202 MB headroom** (08:06 UTC). The laptop bounds only tests and builds: the full backend suite took 5 min 41 s, then `next build`, then Playwright, run one after another. | Budget runtime changes against 202 MB, not 8 GB. |
| Probabilities stay sharper than the closing line | The served identity `v5_phase7-20260922@417b9b8ff7ce563d` has **1 prediction log and 0 settled**. Before this pass, nothing captured a forecast unless a person opened a fixture. | The loop now has a scheduled input (L4). The first honest answer comes at 200 settled, no earlier than the first week of November. |
| Every insight ends in Play or Pass | Every fixture is WITHHELD: `UNVERIFIED`, `permitted: false`. A false "market unavailable" gap would also have turned every no-value fixture into WITHHELD after certification; that gap is fixed (§2.2). | PASS is now reachable the day a generation is certified. PLAY additionally needs `market_baseline`, currently 0/6. |

---

## 0. Evidence (measured 2026-09-26, 07:36–09:40 UTC)

| Fact | Value | Source |
| --- | --- | --- |
| Production SHA | web and backend both `fc7749c` (#246). The screenshots' host `web-8lccentfm-…` serves the same commit, so they show current production. | `/api/health`, `/health` |
| Staking | `permitted: false`, `basis: NONE`, `UNVERIFIED`, `is_override: false` | `/health` → `staking` |
| Serving memory | RSS 322 MB; working set 309 of 512 MB; headroom 202 MB | `/health` → `components.resources.memory` |
| Prediction logs | served identity: 1 (25 Sep, an interactive open of `fd-558881`, which carries its forecast-time price: Pinnacle 1.24 / 7.36 / 8.65). Legacy, not evidence for it: 118 `v5_phase7`, 6 `v6_phase8`. | `match_prediction_logs`, read-only |
| Settled under the served identity | 0; walk-forward `skipped: no_records` | `/health` → `settlement` |
| Scheduled fixtures, next 14 days | 4, all on 9 Oct 18:00–19:00 UTC (EREDIVISIE, BUNDESLIGA, LIGUE_1, LA_LIGA) | `matches`, read-only |
| Market snapshots | 1,024 (190 closing); last capture 20 Sep (international break) | `market_snapshots`, read-only |
| Odds API quota | 236 remaining, 264 used; the provider reports no reset time (`reset_at: null`) | `/api/health` → `the_odds_api.quota` |
| Provider evidence | the_odds_api `LIVE_VERIFIED`; football_data_org `DEGRADED` (a staleness defect, fixed in this pass, §1.3); espn `STALE`, 1 observation ever (20 Sep); api_football and sportmonks 0 observations. The only caller of those three is the `/intelligence` "Retrieve evidence" button. | `/api/v1/providers/evidence` |
| Evidence tables | 9,944 rows each in `provider_health_log` and `provider_request_summaries`, 9,796 in `provider_quota_observations`; about 2,680 older than 30 days in each | read-only query |
| Log noise | `/model-performance/summary` returned 503 on every header refresh (about 2 per minute per tab); fixed in this pass (v9 L2) | Render log 07:36–07:51 |
| Web bundle | shared first-load JS 198 kB (184 kB on 23 Sep, 103 kB at vΩ.25) | `next build`, this pass |
| `/sources/freshness` | every source `never_checked`: its writer, `record_source_check`, has zero callers | code search; live response |

### Readiness tiers (v8 terms)

| Tier | Status | Blocking evidence |
| --- | --- | --- |
| `PLATFORM_READY` | **PARTIAL** | Green in code; DEBT 157 is not merged or deployed yet. Instance sleep (v9 O1) was not re-measured today. |
| `FORECAST_READY` | **NOT MEASURABLE** | 0 settled. L4's first input is 9 Oct. |
| `ACTIONABLE_CERTIFIED` | **NOT MET** | `UNVERIFIED`; `market_baseline` 0/6; G18 v1 negative; no certified uncertainty measure (item 42). |

---

## 1. Resource-constrained data & feature engineering

### 1.1 Budgets

| Environment | Limit | Measured | Rule |
| --- | --- | --- | --- |
| Render `sabiscore-api` (1 uvicorn worker) | 512 MB | working set 309 MB, headroom 202 MB | Read headroom from the working set. No change may cost more than half the headroom without a measured RSS delta. |
| Local Windows | 8 GB | backend suite 5 min 41 s; build; Playwright 19 s | One heavy step at a time. |
| Node scraper cron | 512 MB, heap cap 384 MB | disabled | No work until enabled. |

### 1.2 Six-league pipeline (after DEBT 157)

| Stage | Where | Cadence | State |
| --- | --- | --- | --- |
| Historical corpus | `backend/data/cache/fd_*.csv` | once at boot | 12,765 matches, complete |
| Fixture sync | `fixture_sync_service` | 6 h | 4 fixtures in the 14-day window |
| Market capture | `clv_capture_service` | 5 min | first observation, intermediate and closing, strictly pre-kickoff |
| **Prediction capture** | `prediction_capture_service` (new) | 5 min, after market capture | one forecast per fixture in [kickoff − 3 h, kickoff − 15 min] under the served identity |
| Settlement | `settlement_service` | hourly | 0 finished during the break |
| Evidence retention | `prune_provider_evidence` (new) | hourly, after settlement | keeps 30 days plus every row the evidence reader can read |

### 1.3 Work items

**D1: measure the first capture burst (9 Oct).** Captures run one after another inside the CLV
tick, at 0.6–0.9 s each (the 25 Sep log). The pass now reports `duration_ms` on `/health` →
`components.prediction_capture`. Between 15:00 and 18:45 UTC on 9 Oct, record `duration_ms`,
`captured` and the memory block. Acceptance: headroom stays at or above 100 MB, and a pass
finishes in under 60 s. If a Saturday slot pushes a pass past 60 s, capture each league on its own
tick instead of running the work concurrently: memory is the binding constraint, not wall time.

**D2: the Odds API budget, measured rather than assumed.** Each capture reads the league board
(cached for 120 s and shared with the market capture in the same tick). Market capture fetches
once per tick while a fixture is inside its 10-minute closing window. That is an **estimate** of
about 3–4 requests per league per kickoff slot. After the first full round, sum `quota_cost` from
`provider_quota_observations` for the round and project the month from it. If the projection
exceeds what remains, operator decision O7 applies (§5).

**D3: retention, verified.** The first hourly pass after deploy should delete about 2,680
health-log rows. Render logs the count as `provider_evidence_retention deleted=`. Confirm that
`/api/v1/providers/evidence` reports the same states before and after the pass.

**Fixed in this pass (DEBT 157 item 10):** football-data.org read `DEGRADED` on a healthy day.
One 1-hour staleness clock was applied to the UPCOMING stream, which fixture sync observes only
every 6 h, so the header's live-validated count moved between 1 and 2 as the clock ran.
Scheduled streams are now judged against their own schedule, and a test pins that schedule to
`api/main.py`.

---

## 2. Model serving & the calibration loop

### 2.1 Serving: unchanged

One process serves six artifacts (`v5_phase7-20260922`, schema `apex_v1_68`, head
`stacked_meta_model`). L4 reuses the endpoint path and the loaded models, so it adds no model
load. Do not add a model server, ONNX or a second worker (202 MB headroom).

### 2.2 What changed in the loop this pass

| Step | State |
| --- | --- |
| Capture | **L4 shipped** (code). The first real round is 9 Oct. Each capture stores its forecast-time price in `payload.recommendation_market`. |
| Close | Unchanged: strict pre-kickoff closing snapshot (`is_closing_line=True`). |
| Settle | Unchanged: hourly, scoped to the served identity. |
| Measure | `/model-performance*` returns 200 while pending (v9 L2). `model_vs_close` (`clv_service.compute_model_vs_close`, ISO-week cluster CI via `metrics.week_cluster_ci`) is already on the endpoint. |
| Decide | The operator, at milestones only. |

**Defect fixed while building U1 (DEBT 157 item 5).** `COHERENT_1X2_MARKET_UNAVAILABLE` fired
whenever no outcome had positive EV, not only when there was no market. That turned "no value at
this price" (PASS) into "no market" (a critical gap, WITHHELD). The gap now follows market
coherence, and an explicit abstain ("no outcome offers value at the current price") holds the
stake gate where the false gap used to.

### 2.3 P1: pre-register the C6 evaluation now, before any data exists

The first 200 settled forecasts will exist in about four rounds (at most 57 fixtures per round).
Freeze how they will be judged **before 9 Oct**, following the G18 pattern: a protocol file, its
sha256 recorded in `reports/research/experiment_registry.yaml`, and a commit that predates the
data.

| Element | Frozen value |
| --- | --- |
| Population | Served identity `v5_phase7-20260922@417b9b8ff7ce563d`. Fixtures with an L4 or interactive capture strictly before kickoff **and** a strict pre-kickoff closing snapshot. |
| Join rate | Reported. A result with a join rate under 80% is flagged as possibly biased: fixtures missing a close are not random. |
| Primary metric | Per fixture, RPS(model) − RPS(de-vigged close). The mean, with an ISO-week cluster bootstrap 95% CI (`week_cluster_ci`, 10,000 replicates, fixed seed). |
| Decision | "Sharper than the close" only if the CI's upper bound is below 0. "Less sharp" if the lower bound is above 0. Otherwise inconclusive. |
| Secondary, reported only | Adaptive ECE, Brier decomposition, per-league slices. Slices are not evidence. |
| Milestones | 200, 500 and 1,000 settled with a close. No evaluation between milestones. |
| Forbidden | Refitting, recalibrating, moving a threshold or changing the population after seeing any result. |

Deliverable: `reports/research/c6-served-generation-vs-close-protocol.json`, plus a registry
entry at state `PROTOCOL_FROZEN`. It needs operator approval (O8) before it is frozen.

### 2.4 Unchanged operator decisions

Item 142 (what a future generation serves), G18 v2 capture scope and certification are unchanged
from v8 and v9.

---

## 3. Quantitative UX (Next.js 15)

### 3.1 Shipped in this pass (DEBT 157)

- **Market block (U1).** Every analysis carries price, implied, fair (proportional de-vig), model
  probability and gap for all three outcomes. `MarketComparisonTable` renders them from backend
  values only, and it replaces the single-outcome bar and card, which repeated one of its rows.
- **EV is published only when the fixture is evaluable:** a certified generation, a forecast,
  and no critical gap or conflict. The backend schema and the web Zod contract both refuse an EV
  on anything else, so an uncertified 21% draw at 7.36 can never print "+55%".
- `OddsEdgeCard` reads "Outcome", and shows Kelly as "Withheld" when no stake is permitted (U2).
  The snapshot form previews nothing until its inputs are complete (U3). A `--state-withheld`
  token drives the neutral edge fill (U4).
- **Five statements no longer said without a measurement:** the gaps are listed once, not three
  times with two counts; the "UNKNOWN" freshness pill is gone; the passport no longer prints "Data
  unavailable" beside "Resolved"; football-data.org no longer reads DEGRADED between syncs; and
  metrics that are merely pending return 200.

### 3.2 Display contract (v8 §3.2–§3.5, restated with what enforces it)

| Rule | Enforced by |
| --- | --- |
| PLAY needs `stake_permitted` and backend EV > 0. PASS: evaluable, but no value. WITHHELD: not evaluable. PASS and WITHHELD never merge. | `mapFullAnalysisPresentation`; the market-gap fix |
| EV and a stake appear only in PLAY and PASS | Pydantic `FullMatchMarketResponse` and the Zod `market` refinement |
| The web never de-vigs and never computes EV or Kelly | `no-client-ev-contract.test.ts` |
| Green means "the backend will stake on this". Every other gap is neutral, with its sign printed. | tests on `EdgeDeltaBar`, `OddsEdgeCard` and `MarketComparisonTable` |
| A counter-case whenever a forecast exists, loss probability first, and no line repeated from the status card or the gap banner | `CounterCase` tests |
| No freshness chip or pill without a measured age | panel and hero tests |

### 3.3 Open items

| ID | Item | Acceptance |
| --- | --- | --- |
| U5 | **ProbabilityDumbbell** over `market.outcomes`: one row per outcome on a shared 0–100% axis, with a filled dot for the model, a hollow dot for fair, and a tick at implied (the break-even). The segment between the dots is neutral (`--state-withheld`) unless a stake is permitted. Draw it as inline SVG: no chart dependency, because recharts would add to a 198 kB shared bundle. The existing table is its accessible text, so the SVG is `aria-hidden`. | Renders all three rows from backend values only; not green while withheld; the no-client-EV scan stays clean; Playwright desktop and mobile pass. |
| U6 | **Counter-case line 5: price movement.** The backend adds `first_seen` odds per outcome to `market`, from the earliest `PRE_MATCH_OPENING` snapshot. The counter-case says "price moved from X to Y since SabiScore first saw it". It must never say "opening line": the lifecycle service defines that observation as SabiScore's first sighting, not the bookmaker's open. | Line omitted when no snapshot exists; wording pinned by a test. |
| U7 | **On-demand providers show an age, not a verdict.** ESPN (1 observation, 6 days) and API-Football/Sportmonks (0) are called only by "Retrieve evidence". Show "Last checked 6 d ago" or "Not yet used", not an amber "Stale". Apply the same rule to the header count's tooltip. | An on-demand provider never renders "Stale"; a scheduled one still does after missing its schedule. |
| U8 | `DecisionStateBadge` colours through `--state-play`, `--state-pass` and `--state-withheld` (the token layer's second consumer) | Badge colours come only from tokens; the existing state tests pass. |
| U9 | **Shared bundle 198 kB, cause unknown.** DEBT 144 suspected a static client import of `@sentry/nextjs`, but that no longer holds: the client SDK is already imported dynamically (`lib/error-utils.ts`), and `instrumentation.ts` is server-side. Measure the shared chunk's composition with a bundle analyzer before changing anything. | A dated composition report; any fix states its measured before/after delta. |
| U10 | `performance-page-client.test.tsx` "distinguishes a real outage" failed once under full-suite load (1 s `findBy` against an 8.6 s run) | Set an explicit `findBy` timeout; the suite passes 3 runs in a row. |

---

## 4. NEXUS agent orchestration

### 4.1 Boundary (unchanged)

Production loops are in-process asyncio tasks, not agents: fixture sync, market capture,
prediction capture, settlement and retention. Agents work at development time only. They never
refit, recalibrate, move a threshold, promote a generation or edit `certification_state`.

### 4.2 The workflow this pass used, and what it taught

| Role | Did | Lesson for the next pass |
| --- | --- | --- |
| Evidence worker | Compared the screenshot host's SHA with production (they matched), queried Render Postgres read-only, and read `/health` and the Render log | Query the database before trusting a derived claim. The forecast-time price looked unrecorded from the code, but the stored row showed it was. |
| Implementer | Fixed at the shared root: one staleness rule, one `health_status` annotation that cleared 15 mypy errors, one market-coherence test | Read a directive's rule against its reader before implementing it. R2's literal rule would have changed the evidence output it promised to preserve. |
| QA verifier | Reverted each guard's rule and watched the test fail, then ran the suites one at a time | A stub that raises cannot fail against code that swallows every exception (R1's first guard). Record the call instead. |
| Ledger writer | DEBT 157, v9 status, CLAUDE.md, this directive | Record estimates as estimates (D2), and remove any claim no field supports (the quota reset date). |

Handoffs are files in the session scratchpad with a sha256 header (v8 §4.3). On the 8 GB machine,
parallelism means parallel reading, never parallel heavy processes.

### 4.3 Automations

| Automation | Trigger | Steps | Output |
| --- | --- | --- | --- |
| Post-deploy verification | DEBT 157 deploys | Evidence worker runs the four checks in DEBT 157 against the production alias, never a `web-<hash>` URL | a dated note in DEBT 157 |
| Capture watch | 9 Oct, 15:00–19:00 UTC | read `/health` → `prediction_capture` and `resources.memory` each tick | D1 numbers |
| C6 milestone probe | a weekly cloud routine (`schedule` skill) | reads the settled count under the served identity; at 200, 500 or 1,000 it notifies the operator | a notification only. The frozen protocol runs locally, by a person. |

### 4.4 Backfills

None. The corpus is complete, and retroactive prediction capture is forbidden: a forecast made
after the result is known is leakage.

---

## 5. Execution order

| Phase | Work | Exit gate |
| --- | --- | --- |
| 0: now | Merge DEBT 157 and deploy | CI green; operator approval; the four post-deploy checks pass on the production alias |
| 1: before 9 Oct | P1: write the C6 protocol, get O8 approval, freeze it, register it | The protocol's sha256 is in the registry, in a commit dated before 9 Oct |
| 2: 9 Oct and the first round | D1, D2, D3 | `captured` equals the eligible fixtures; headroom ≥ 100 MB; a measured quota projection |
| 3 | U5–U10 | lint, typecheck, Vitest, build, Playwright desktop and mobile all pass; every fixture still WITHHELD |
| 4: about the first week of November | C6 at 200 settled, under the frozen protocol | `model_vs_close` CI reported, with its join rate |

### Operator decisions (none can be made by an agent)

- **O1** (from v9): stop the instance sleeping. Not re-measured today.
- **O2** (from v9): Google sign-in configuration.
- **O3** (from v9): check `sabiscore.vercel.app`, never a `web-<hash>` URL.
- **O4** (from v8): item 142, G18 v2 scope, certification.
- **O7 (new):** if D2's projection exceeds the Odds API quota, choose a paid plan or fewer
  capture fetches. Choose before the second full round.
- **O8 (new):** approve the C6 protocol (§2.3) before it is frozen.

---

## 6. Standard of evidence

v8 §7 applies unchanged. Report each item as CLAIM / EVIDENCE / FILE / COMMAND / RESULT / FAILURE
MODE / CONFIDENCE / BLOCKER. A guard counts only after it has been watched failing. A number counts
only if it comes from a dated measurement. An estimate is labelled as one, and it is replaced by a
measurement before any decision depends on it.
