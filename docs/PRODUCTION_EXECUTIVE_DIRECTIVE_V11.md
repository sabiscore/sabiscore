# SabiScore — Production Executive Directive v11.0

### Delta on v10: one bookmaker for the price and the close, a judge frozen before the first capture, and headroom read at its peak

Date: 2026-09-26 (evening). v8 §1–§7, v9 and v10 stay in force. v11 replaces v10's §0 evidence and
§5 execution order. The work behind it is `docs/DEBT.md` item 158 (branch
`fix/directive-v10-live-pass`). Every number below was measured today; estimates say so.

The brief is the one v8–v10 answered. Against today's numbers:

| Brief says | Measured 2026-09-26 | Consequence |
| --- | --- | --- |
| Node.js workers ingest the data | No Node process runs; the scraper cron is disabled and already heap-capped at 384 MB. Ingestion is Python inside the API process: fixture sync (6 h), market capture (5 min), prediction capture (5 min), settlement (hourly), retention (hourly). | No Node memory work until an operator enables the scraper. |
| 8 GB Windows is the absolute limit | Serving runs in a 512 MB cgroup. One process read 74 MB of headroom at 12:24 UTC and 167 MB at 15:32 UTC, with no restart. | Budget runtime changes against the peak during a burst, not a single reading (§1). |
| XGBoost, LightGBM and logistic regression | Served: random forest + XGBoost + LightGBM → stacked softmax head → sigmoid calibrator; schema `apex_v1_68`; six artifacts. Item 142 (the calibrator was fitted on a different composition) is still open. | No change to serving. |
| Probabilities stay sharper than the closing line | 0 settled forecasts for the served generation. The "close" was whichever bookmaker's key sorts first, a soft book, until this pass. | The close is now the sharpest book quoted (Pinnacle first). C6 is drafted and must be frozen before 9 Oct 15:00 UTC. The first answer comes at 200 settled. |
| Show potential ROI | No stake has ever been placed, so realised ROI has nothing to measure. | Show "expected return per unit staked", only for an evaluable fixture. Never ROI or profit. |
| Every insight ends in Play or Pass | Every fixture is Withheld: the generation is uncertified. | Pass becomes reachable at certification; Play also needs the market baseline (0 of 6 leagues). |

---

## 0. Evidence (measured 2026-09-26, 11:30–15:35 UTC)

| Fact | Value | Source |
| --- | --- | --- |
| Production SHA | Web and backend both `63f9bf2` (#247). The screenshots' host `web-qjzuzffsd-…` serves the same commit. | `/api/health`, `/health` |
| #247 post-deploy checks | All four pass: capture `ok`; `/summary` 200 `METRICS_UNAVAILABLE`; football-data.org `LIVE_VERIFIED`; retention deleted 2,701 / 2,701 / 2,662 rows with provider states unchanged | `/health`, Render log 11:30:17 |
| Staking | `permitted: false`, basis `NONE`, `UNVERIFIED` | `/health` |
| Memory, same process | 12:24 UTC: RSS 398, working set 437, headroom 74 MB (`/health` degraded). 15:32 UTC: RSS 354, working set 344, headroom 167 MB (healthy). No `server_failed` event in 7 days. | `/health`, Render events |
| Import cost, `fc7749c` vs `63f9bf2` | 450 MB vs 450 MB; 3,754 vs 3,755 modules (local, Windows) | measured |
| Settled, served identity | 0 | `/health` settlement |
| Next fixtures (UTC) | 9 Oct: 18:00 PSV–Heerenveen, 18:30 Dortmund–Bremen, 18:45 Lens–Lyon, 19:00 Málaga–Espanyol; 10 Oct from 11:30 | `/api/v1/fixtures/upcoming` |
| Kickoff display | Homepage and `/match` rows read "18:00 WAT" for an 18:00 UTC kickoff (19:00 WAT) | screenshots, API payload |
| Market capture bookmaker | Alphabetically first key per event; the live price took the provider's listing order | code |
| Odds API quota | 222 remaining, 278 used, reset time not reported; 14 used by page views today | provider quota |
| Google sign-in | `redirect_uri_mismatch` on `https://sabiscore.vercel.app` itself | probe |
| Web first-load JS | shared 198 kB, of which the Sentry SDK is 179 of 324 modules in one chunk | `next build` |

| Tier (v8 terms) | Status | Blocking evidence |
| --- | --- | --- |
| `PLATFORM_READY` | PARTIAL | This PR must deploy before 9 Oct. Instance sleep (O1) and Google sign-in (O2) are open. |
| `FORECAST_READY` | NOT MEASURABLE | 0 settled; first scheduled captures on 9 Oct. |
| `ACTIONABLE_CERTIFIED` | NOT MET | Uncertified; market baseline 0 of 6; G18 v1 negative; no certified uncertainty measure. |

---

## 1. Resource-constrained data and feature engineering

The binding limit is the 512 MB serving instance. The laptop bounds tests and builds only, and this
pass ran every heavy step one at a time (backend suite, `next build` three times, Playwright).

### 1.1 Budgets

| Environment | Limit | Measured | Rule |
| --- | --- | --- | --- |
| Render API (1 worker) | 512 MB cgroup | working set 344–437 MB, headroom 167–74 MB on one process | Judge headroom at its peak during a burst, split into process (anon) and cache (file) memory. |
| Local Windows | 8 GB | backend suite 6 min 27 s; three sequential `next build` runs; Playwright 8.5 s | One heavy step at a time. Parallel agents only read or write new files. |
| Node scraper cron | 512 MB, heap cap 384 MB | disabled | Nothing to do until it is enabled. |

### 1.2 Work items

**M1: attribute memory before 9 Oct.** The 74 MB reading followed about 30 concurrent requests from
two open tabs, and the same process recovered to 167 MB with no restart. So it was mostly transient,
but `/health` cannot yet say which part is process memory. Another session has added
`cgroup_anon_mb` and `cgroup_active_file_mb` to `/health`; that change is uncommitted and must be
merged. Then read `/health` at boot, +1 h and +4 h. Anon memory is what the kernel cannot reclaim;
decide from it, not from the working set.

**M2: D1 restated.**
- **Acceptance:** on 9 Oct, the peak working-set headroom across the capture burst (15:00–18:45 UTC)
  is at least 100 MB, and no instance restarts.
- **Evidence:** this pass adds `/health` → `components.prediction_capture.recent`. It holds the last
  48 passes that had work to do, each with `duration_ms`, counts and process RSS, so the burst is
  read once, after 19:00 UTC, instead of by polling. The history is lost on restart, and a restart is
  itself a failure of this item.
- **If it fails:**
  1. Attribute the peak (M1).
  2. If anon memory grew, try `MALLOC_ARENA_MAX=2` as a Render environment variable, measured
     against the same points. Python's thread pools can leave freed memory in per-thread glibc
     arenas. This is an operator change and reversible.
  3. Only if the burst itself is the cause, capture one league per tick.

**M3: the Odds API budget (D2).** 222 requests remain and no reset time is reported. Spending has two
sources:
- Capture reads each league's board, cached for 120 s. That is roughly one request per league per
  kickoff slot, an estimate.
- Page views fetch boards on demand; they used about 14 today.

After the 9–10 Oct round, subtract the quota readings, project the month, and bring the result to
O7 before the second round.

**M4: Node.** No Node work runs. The scraper cannot compute probabilities, EV or stakes (CLAUDE.md),
and memory work must not move computation into it.

### 1.3 Six-league pipeline

| Stage | Where | Cadence | State after this pass |
| --- | --- | --- | --- |
| Historical corpus | `backend/data/cache/fd_*.csv` | once at boot | 12,765 matches |
| Fixture sync | `fixture_sync_service` | 6 h | 32 fixtures received (PL 6, PD 5, BL1 7, SA 3, FL1 6, DED 5) |
| Market capture | `clv_capture_service` → `market_observation_service` | 5 min | **One book per event: Pinnacle, else the first key** (`the_odds_api.bookmaker_preference`) |
| Prediction capture | `prediction_capture_service` | 5 min, after market capture | one forecast per fixture in [kickoff − 3 h, kickoff − 15 min]; the price it records uses the same book rule |
| Settlement | `settlement_service` | hourly | 0 finished during the break |
| Evidence retention | `prune_provider_evidence` | hourly | first pass deleted 2,701 health rows |

---

## 2. Model serving and the calibration loop

### 2.1 Serving: unchanged

One process serves six artifacts (`v5_phase7-20260922`, `apex_v1_68`, stacked head, sigmoid
calibrator). Scheduled capture calls the endpoint's own analysis path, so it adds no model load. Do
not add a model server, ONNX or a second worker: a second worker does not fit in 167 MB, let alone 74.

### 2.2 One bookmaker for the price, the first sighting and the close (shipped)

Before this pass the forecast-time price came from the provider's listing order and the close from
alphabetical key order ("betclic" sorts before "pinnacle"). That had two consequences:
- "model vs close" could compare two different books;
- the benchmark could be a soft book, whose wider, noisier close flatters any model.

| Use | Reader | Book |
| --- | --- | --- |
| Forecast-time price (`payload.recommendation_market`) | `odds_service.get_match_odds` | `bookmaker_preference` |
| First sighting (§3, U6) | `full_analysis._first_sighting` | the same book as the displayed price |
| Close (C6 benchmark, CLV) | `market_observation_service` | `bookmaker_preference` |

This rule is part of C6's population. It must be live before the first capture (9 Oct 15:00 UTC)
and approved with the protocol; changing it after a result exists is forbidden.

### 2.3 The judge before the data (C6, v10 P1)

The protocol is drafted at `reports/research/c6-served-generation-vs-close-protocol.json` (sha256
`6dc8a2d6…`), registered as `C6`, state `PROPOSED`. Freezing needs O8 to settle six points:

| # | Question | Recommendation |
| --- | --- | --- |
| a | Which prediction-log writers count? Two writers (`predictions.py`, `analytics.py`) skip the pre-kickoff check. | Count only `capture_trigger == "interactive_full_analysis"` (scheduled and interactive captures both write this), applied in the milestone script. |
| b | Replicates and seed | 10,000 replicates, seed 42, for the milestone. The live endpoint's 2,000 replicates with seed 0 stay a display figure. |
| c | Sample cut at a milestone | Every settled, joined forecast up to the N-th one's kickoff, taking whole kickoff groups. |
| d | Interim display: `/model-performance` computes `model_vs_close` from 10 joined rows | Show only the count until 200. A visible interim interval invites the peeking the protocol forbids. |
| e | The closing book | Pinnacle first (§2.2). |
| f | Three looks at 95% | Decide on 98.3% intervals (0.05 / 3) and report the 95% interval beside them. Three unadjusted looks put the family-wise false-claim rate near 14% if the looks were independent; nested samples make it somewhat lower, but still above 5%. |

**Freeze** = set the protocol status to `PRE-REGISTERED`, record its new sha256 in the registry entry,
and commit before 9 Oct 15:00 UTC.

### 2.4 The loop, as it stands

| Step | State | Next |
| --- | --- | --- |
| Capture | Shipped; forecast-time price on the Pinnacle-first book | first real round 9–10 Oct |
| Close | Strict pre-kickoff snapshot, now Pinnacle-first | observe on 9 Oct: rows for 9 Oct fixtures should carry `bookmaker = pinnacle` wherever Pinnacle quotes |
| Settle | Hourly, scoped to the served identity | — |
| Measure | Model vs close: paired ΔRPS, ISO-week cluster CI | at 200, 500 and 1,000 settled (200 is about four rounds: the first week of November, an estimate) |
| Decide | The operator, at milestones only | nothing is refitted, recalibrated or promoted by any job or agent |

---

## 3. Quantitative UX (Next.js 15)

### 3.1 Shipped in this pass

| Item | Change | Measured result |
| --- | --- | --- |
| Kickoff times | Backend list rows carry `+00:00` (`db_time.to_utc_iso`); the row's date is pinned to `Africa/Lagos` like its time | PSV reads 19:00 WAT after deploy (18:00 before) |
| U9 bundle | The Sentry SDK is imported only when a DSN is set | shared first-load JS 198 → 103 kB; `/` 319 → 226, `/match/[id]` 267 → 173 kB |
| U5 | `ProbabilityDumbbell` above the market table: model dot, fair dot, break-even tick, neutral unless a stake is permitted | live PSV payload: 0 px overflow at 1280 and 360 px |
| U6 | Counter-case line from `market.first_seen`: "moved from X to Y since SabiScore first saw it at this bookmaker" | omitted without a same-book snapshot |
| U7 | On-demand providers show "Last checked 6d ago" or "Not yet used"; backend `cadence` per provider | ESPN no longer reads Stale |
| U8 | Decision badge colours only from `--state-*` tokens; Withheld is neutral, not amber | 3 tests |
| U10 | Explicit wait under a 10 s test timeout | 21 clean runs after one failure on the first run after the edit |
| Sign-in | Production sends pinned hosts to the canonical host before any cookie | O2 still required |
| Copy | "No odds snapshot" instead of "Provider unavailable"; correct Gap, Kelly and CLV definitions; no calibration chip without a forecast | tests on each |

### 3.2 The decision card, as built

```
DecisionCard (backend fields only; the web computes no odds maths: no-client-ev-contract.test.ts)
├─ DecisionStateBadge      Play | Pass | Withheld   word + icon shape + --state-* token
├─ MarketComparisonTable   price · fair · model · gap (+ expected return only when evaluable)
│  └─ ProbabilityDumbbell  picture of the table; the table is the accessible text
├─ CounterCase             loss probability first → price move since first sighting →
│                          uncertified gap is not value → calibration status → advisory count
└─ EvidencePassport        per-family status from this fixture's evidence only
```

The quantities are as defined in v8 §3.3 and are computed by the backend only:
- implied = 1/o;
- fair = implied / Σ implied (proportional de-vig);
- edge = p − fair;
- EV = p·o − 1, published only when evaluable;
- stake = min(¼ Kelly, league cap, 5%), and only when `stake_permitted`.

Play requires `stake_permitted` and EV > 0. Pass means evaluable with no value. Withheld means not
evaluable. Pass and Withheld never merge.

### 3.3 Open items

| ID | Item | Acceptance |
| --- | --- | --- |
| U11 | The match card shows three state words at once ("Withheld · Partial Data · Not evaluable"). Make the decision state the headline and fold the verdict into the evidence line. Add Play, Pass and Withheld to the homepage glossary, which explains only verdict tiers. | One headline state per card; the glossary covers both vocabularies; state tests pass. |
| U12 | If O8 agrees (§2.3 d), `/model-performance` shows the joined count, not an interval, until 200. | No interval below 200; a test pins it. |
| U13 | Evidence Passport market row names the book and capture time of the displayed price. | From backend fields; nothing shown without them. |
| U14 | First visit stacks an 18+ gate and then a cookie banner over the market table at 360 px. | One consent step, or the banner clears the table; Playwright screenshot at 360 px. |

---

## 4. NEXUS agent orchestration

Production loops stay in-process asyncio tasks. Agents work at development time and never refit,
recalibrate, move a threshold, promote a generation or edit the certification state.

### 4.1 What this pass taught

| Observation | Rule from now on |
| --- | --- |
| A second session edited `monitoring.py` and `DEBT.md` in the same working tree while this one switched branches. Nothing was lost, but only by checking. | One `git worktree` per session (`git worktree add ../sabiscore-<topic> -b <branch> origin/master`). Never switch branches in a shared tree. Announce file ownership by message before editing, and claim DEBT numbers in that message. |
| The C6 agent reported that the close came from the first bookmaker key. That was verified in code (`market_observation_service.py:399`) before anything depended on it. | An agent's report is evidence to check, not a finding. |
| The dumbbell agent owned two new files only, and showed failing-first evidence for its guards. | Background agents get new files or read-only work, and run only their own tests; the lead runs every heavy gate, one at a time. |
| U9 needed a bundle composition, and the analyzer opens a browser. Splitting the built chunk into its webpack modules and walking their imports found the root in minutes. | Measure the built artifact before changing configuration; state the measured delta. |

### 4.2 Roles and handoffs (unchanged from v10, restated briefly)

- **Planner (lead):** classifies through NEXUS, assigns file ownership and runs the heavy gates.
- **Evidence worker (read-only):** checks that the SHA in the URL bar matches production, then reads
  live payloads, Render logs and read-only queries.
- **Implementer:** fixes at the shared root, with a failing-first test.
- **QA verifier:** reruns each guard against reverted code.
- **Ledger writer:** writes DEBT, CLAUDE.md and the directive, and states nothing the verifier did
  not verify.

Handoffs are files. On the 8 GB machine, running in parallel means parallel reading, never parallel
heavy processes.

### 4.3 Automations

| Automation | Trigger | Output |
| --- | --- | --- |
| Post-deploy verification of this PR | deploy | The §5 checks on `sabiscore.vercel.app`, never a `web-<hash>` URL; a dated note in DEBT 158. |
| Capture read | 9 Oct after 19:00 UTC, and 10 Oct after the last kickoff | `prediction_capture.recent` plus the anon reading (M1, M2); the quota delta (M3). |
| C6 milestone probe | a weekly cloud routine | Reads the settled count and notifies at 200, 500 or 1,000. The frozen protocol is run locally, by a person. |

There are no backfills. The corpus is complete, and a forecast captured after kickoff is leakage.

---

## 5. Execution order and operator decisions

| Phase | Work | Exit gate |
| --- | --- | --- |
| 0: now | Merge this PR and deploy before 9 Oct. | The post-deploy checks below pass on the production alias. |
| 1: before 9 Oct 15:00 UTC | O8 answers §2.3 a–f; freeze C6. | The protocol's sha256 is in the registry, committed before the first capture. |
| 2: 9–10 Oct | M1, M2, M3 | Captured equals eligible; peak headroom at least 100 MB; a quota projection. |
| 3 | U11–U14 | Lint, typecheck, Vitest, build and Playwright pass; every fixture still Withheld. |
| 4: about the first week of November | C6 at 200 settled, under the frozen protocol | The model-vs-close interval and its join rate are reported. |

**Post-deploy checks for this PR**
1. `/api/v1/upcoming/matches` rows end `match_date` with `+00:00`, and the homepage PSV row reads
   19:00 WAT.
2. The shared first-load chunk contains no `NextjsClientStackFrameNormalization`.
3. `/api/v1/providers/evidence` rows carry `cadence`.
4. `/health` → `prediction_capture.recent` is present (empty until a fixture is due).
5. `/api/auth/google/start` on a `web-<hash>` host redirects to
   `https://sabiscore.vercel.app/api/auth/google/start`.
6. `/intelligence` fixture rows read "No odds snapshot".

**Decisions only the operator can make**
- **O1:** stop the instance sleeping, with an external monitor on `/health/live` or a paid plan. The
  keep-alive runs every 3–5 h, not every 14 min.
- **O2:** register `https://sabiscore.vercel.app/api/auth/google/callback` in Google Cloud for the
  production client. The measured failure is on the canonical alias itself.
- **O4:** item 142, G18 v2 scope and certification. Unchanged.
- **O7:** the Odds API plan, if M3's projection exceeds what remains.
- **O8:** approve C6, answering §2.3 a–f, before 9 Oct 15:00 UTC.
- **Housekeeping:** the parallel session's memory breakdown (M1) is uncommitted in the shared tree.
  Commit and merge it before 9 Oct, or M2 cannot attribute a peak.

The standard of evidence is v8 §7, unchanged:
- a guard counts only after it has been watched failing;
- a number counts only with a dated measurement;
- an estimate is replaced by a measurement before any decision depends on it.
