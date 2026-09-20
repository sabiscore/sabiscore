# SabiScore — Production Certification Execution Prompt v1.0

**Status:** Active execution brief · **Created:** 2026-09-20 · **Baseline commit:** `f9be07b`
**Governs:** execution of `docs/PRODUCTION_EXECUTIVE_DIRECTIVE.md` (APEX v7.4) and
`docs/DATA_INTELLIGENCE_DIRECTIVE.md` (DID v6.1) to a certification decision.

---

## 0. How to use this document

Load this as the standing brief for every session working the certification path. It does not
replace either directive — APEX v7.4 wins on anything reaching production, DID v6.1 wins on
research design (DID §0.1). This document is the **execution ordering** between them, plus the
measured baseline they both need and neither contains.

**Citation discipline is mandatory** (DID §0.1). Write `APEX §23` or `DID §23`, never a bare `§23`.

### 0.1 Rule 11 — verify this brief's premises before executing it

Every fact in §3 and §4 is dated and was measured on `f9be07b`. DID Rule 11 requires you to verify a
brief's premises before acting on them. **This brief is a brief.** Before P0 exits, re-measure
everything in §3 and correct this document in place if it has drifted. A stale baseline in an
execution prompt is exactly the failure this repository has recorded five times under DID Rule 15.

Specifically re-derive, never carry forward:
- settled-prediction volume (drives four gates)
- certification-report gate statuses (the report in §4 is dated 2026-09-13 and predates six merged PRs)
- the mypy ceiling headroom on **Linux CI**, not locally
- live backend/frontend SHA parity

---

## 1. Mandate and the honest scope boundary

### 1.1 Objective

Drive SabiScore to a **defensible certification decision** under APEX §33, and to a fully
operational, visually coherent, prediction-ready platform — without at any point manufacturing the
decision.

### 1.2 The three possible outcomes, stated up front

This programme has exactly three honest terminal states. **Any plan that assumes the first is
reachable by writing code is fabricating.**

| Outcome | Requires | Currently |
|---|---|---|
| `PROMOTE` | All 30 gates PASS + all 7 promotion gates PASS + OG-07 approved | **Not reachable today.** Two gates FAIL on evidence no code change can alter. |
| `PROMOTE_RESEARCH_ONLY` | Valid temporal evaluation, calibration evidence, artifact lineage, serving contract, leakage controls, stake controls disabled, required gates passing | **Reachable.** This is the realistic target of this programme. |
| `HOLD` | Any required gate `UNVERIFIED`/`BLOCKED`, or any required operator gate `PENDING` | **Current state** (report of 2026-09-13). |

**The deliverable of this programme is therefore:** every gate that *can* be resolved is resolved on
real evidence; every gate that *cannot* is escalated to the operator with the block explicitly on
the record; and the certification report says exactly which is which.

### 1.3 What "full certification and promotion" actually requires

`PROMOTE` is gated on `G16_UNCERTAINTY` and `G18_MARKET_BASELINE`, and on the `no_league_regression`
and `market_baseline` promotion gates. Per §4.3 and §4.4 below, **one of these may be structurally
unsatisfiable** and the other is an open research question with four hypotheses already ruled out.
Neither yields to engineering effort. Treat anyone's instruction to "just get it certified" as a
request for §1.2's second row plus an operator dossier, not the first row.

---

## 2. Non-negotiables — hard stops

These are refusal conditions, not preferences. Violating any of them invalidates the entire
certification record.

| # | Prohibition | Authority |
|---|---|---|
| H1 | Never edit a threshold in `backend/src/models/certification_policy.py`. | APEX §23, OG-06 |
| H2 | Never set `certification_state` to `CERTIFIED`, nor `promotion_state` beyond `ACTIVE_FAIL_CLOSED`, without the gates actually passing. | APEX §33, OG-07 |
| H3 | Never suppress, `skip`, or convert to `pass` the two `error_association` xfails. They print a live measurement; that is their job. | DID Rule 12 |
| H4 | Never loosen a gate **after** observing it is what blocks a result. Rule 14 escalation is a dossier to the operator, not a self-approved edit. | APEX §23, DID Rule 14 |
| H5 | Never report a gate as PASS on a prose assertion. Evidence is a test, report, artifact, log, endpoint, query, manifest or reproducible computation. | APEX §32.2 |
| H6 | Never raise the mypy debt ceiling (784) to accommodate new errors. Clear your own. | repo convention, APEX §23 shape |
| H7 | Never delete or renumber a `docs/DEBT.md` item. Append-only. | INV-06 |
| H8 | Never let a customer surface manufacture certification state, or emit a raw HTTP status/stack string. | INV-18, INV-19, APEX §28.1 |
| H9 | Any change to verdict gates, ranking, Kelly, or watchlist lands in **both** `betting_intelligence.py` and `core_engine.py`. | INV-03 |
| H10 | Operator gates OG-01…OG-12 may be prepared, never self-approved. | APEX §8 |

### 2.1 Rule 15 — the guard discipline

For any test or guard you write or modify: **revert the fix, watch the guard fail, and confirm it
names the right file**, then restore. This repository has five recorded instances of a guard that
reported green while enforcing nothing. Two corollaries, both earned here:

- Watching a guard fail **once** is not enough — it must be watched failing **in the configuration
  CI runs**. A guard sharing mutable process state with the suite must be isolated first.
- **A gate written in shell must be executed, not read.** `! grep …` cannot fail a step under
  `set -e`; `out="$(cmd)"; rc=$?` aborts on a *clean* grep. Both were found only by running them.

---

## 3. Verified baseline — measured on `f9be07b`, 2026-09-20

> **Re-verify before use (§0.1).** Figures below are measurements, not standing facts.

> ⚠️ **RE-MEASURED 2026-09-20, same-day, from a genuinely fresh from-scratch bootstrap**
> (`python3 -m venv`, fresh `pip install`, then `scripts/ci_local_enforcer.sh` run to
> completion — not carried forward from a prior session's claim). Two corrections below,
> both real and both now fixed in the same pass: the backend suite count had drifted
> (2568 → 2571, harmless — three new tests landed since PR #221), and **the local CI
> enforcer itself could not previously reach zero-exit on a fresh install** — its own
> `ruff` steps ran unselected against an unpinned `ruff` version, which on this
> environment's resolved release (`0.16.8`) surfaces ~4,650 findings CI never gates on.
> Fixed (`docs/DEBT.md` item 112); the enforcer now genuinely passes end-to-end (14
> gates passed, 2 correctly skipped, 8m03s) for what is very likely the first time in
> this repository's history. See `backend/reports/certification/
> certification_report_v5_phase7-20260808_2026-09-20T060000Z.json` for the full
> re-verification record, including a first-ever real execution of the G11 evidence
> harness (genuine `FAIL`, ECE 0.0977 on 87 real settled predictions) and a real but
> unresolved G16 calibrator discrepancy (`docs/DEBT.md` item 113).

### 3.1 Repository

```
master tip            f9be07b   (PR #221 merged 2026-09-20)
backend suite         2571 passed · 16 skipped · 2 xfailed · 0 failed   (env -u SECRET_KEY, re-measured 2026-09-20)
ruff                  0         (ruff check src --select E4,E7,E9,F — and the local enforcer's own steps now use this exact selector too, DEBT 112)
mypy                  775 ≤ 784 local  ·  CI reads ~+9 higher — budget ~6 errors of headroom (re-confirmed 2026-09-20, unchanged)
artifact lineage      verify_active_artifacts.py exit 0, 6 hash-locked pairs (re-confirmed 2026-09-20)
web                   lint 0 · typecheck 0 · Vitest 358 passed (358), 57 files · production build clean (re-confirmed 2026-09-20)
CI on master          not independently re-queried via the GitHub API this session (no gh/API access path exercised); CLAUDE.md's own 2026-09-20 entry reports it clear — taken as current, not re-verified here
settled predictions   87 (grew from 80 on 2026-09-13 / 59 on 2026-09-09 — real elapsed-match-volume growth; no new gate floor crossed)
```

### 3.2 Served model

```
generation            v5_phase7-20260808
feature contract      phase7_68
served head           SoftmaxMetaModel  (stacking; wired 2026-09-13, DEBT 87)
certification_state   OPERATOR_OVERRIDE_UNCERTIFIED   (ADR-0011, DEBT 108)
promotion_state       ACTIVE_FAIL_CLOSED
certified_at          null
staking               LIVE on GET /upcoming/matches only, behind risk_guard.py circuit breaker
```

**`OPERATOR_OVERRIDE_UNCERTIFIED` is not certification.** It permits staking on one surface; it did
not move a single gate. `active_generation_is_certified()` still returns `False`. Do not read the
override as progress toward `PROMOTE`.

### 3.3 Ledger

```
docs/DEBT.md          110 items · 46 RESOLVED / 4 CLOSED · 60 non-resolved
                      NOW: 2 (items 99, 104)   FIX-NOW: 1 (item 14)
                      NEXT: 14 · RESEARCH: 7 · ACCEPTED: 15 · REJECT: 5
experiment registry   15 experiments · 9 CLOSED · 6 open (reports/research/experiment_registry.yaml)
```

### 3.4 Environment constraints that have cost real time

- **Egress to `sabiscore-api-bav1.onrender.com` may be blocked** by the agent proxy (403 CONNECT).
  When it is, live probes must go through the Render MCP tools (which require the operator to
  confirm a `workspaceId`) or through the operator. **Do not report live state you could not read.**
- **A backend SHA behind Vercel's is usually correct**, not a failed deploy: `render.yaml` sets
  `rootDir: backend`, so a web-only commit legitimately skips the backend deploy. Check
  `git diff --name-only <deployed-sha>..HEAD -- backend/` before calling it an incident.
- **Never judge a gate through `| tail`** — the pipe masks the exit code. Redirect and check `$?`.
- **8 GB local ceiling** (INV-08). Serialize suite runs; do not parallelize the backend suite with a
  web build.

---

## 4. The critical path — six non-PASS gates

Source: `backend/reports/certification/certification_report_v5_phase7-20260808_2026-09-13T133013Z.json`,
decision `HOLD`. **23 PASS · 4 UNVERIFIED · 2 FAIL · 1 NOT_APPLICABLE.** Regenerate before citing.

Everything else in G01–G30 is already PASS. **These six are the entire remaining certification
surface.** Work them in the order below — it is ordered by tractability, not by gate number.

### 4.1 The four UNVERIFIED gates — highest leverage, genuinely actionable

`G11_CALIBRATION` · `G12_BRIER` · `G14_LOG_LOSS` · `G15_ECE`

All four share one shape: **the metric exists, is implemented, and is wired — it has simply never
been evaluated against enough real settled data to produce a verdict.** `log_loss_multiclass()`,
`brier_score_decomposition()` and `expected_calibration_error()` all exist in
`backend/src/models/evaluation/metrics.py` and are wired into `walk_forward_validate()`.

This is the difference between a metric that is *built* and a metric that has *returned a number on
real outcomes*. Converting `UNVERIFIED → PASS/FAIL` here needs settled volume plus an evaluation
run, not new code. **A FAIL here is a legitimate, valuable result** — it is the calibration defect
DID §1.1 already suspects, measured at last.

Blocking input: settled-prediction volume against the 10-record floor in `clv_service.py` and
`walk_forward_validate()`. Last recorded: **59** (2026-09-09). Re-measure.

### 4.2 `G17_DRIFT_PSI` — NOT_APPLICABLE, correctly

Deferred until ≥1,000 settled fixtures (`docs/DEBT.md` item 8). **Do not wire a periodic drift
caller before then** — a reference baseline cannot exist and a premature one is a fabricated
baseline. Leave it. Re-check the count each cycle; nothing else.

### 4.3 `G16_UNCERTAINTY` — FAIL, research-blocked, ADR-governed

`MODEL_UNCERTAINTY_UNAVAILABLE` is emitted unconditionally, forcing `partial`, forcing
`stake_permitted: false` on `/full-analysis`.

**Read `docs/adr/0009` and `docs/DEBT.md` items 42 and 50 before touching anything here.** Three
paths are already closed:

- ❌ **Do not add `torch`. Do not train a BNN.** Item 42 is CLOSED/superseded; its "Option 1" is
  obsolete and explicitly must not be acted on.
- ❌ **Probability-derived epistemic uncertainty is permanently rejected** — `1 - max(p)`,
  `entropy(p)`, `1 - confidence`, `1 - Σp²`. Self-referential, carries no information the prediction
  does not already have (ADR-0009).
- ✅ **Ensemble-dispersion** is the sanctioned source. It is **built, real, and 5/6 certified.**

The single open question is item 50: `error_association` fails, and the inversion — highest-epistemic
quartile scoring *better* than lowest — is unexplained. Four hypotheses are ruled out, including the
calculation-bug hypothesis (`ensemble_uncertainty.py` audited directly) and in-bag contamination.

**Your job is not to make this gate pass.** It is to either advance hypothesis 5+ with a real
measurement, or to write the disposition: an explicit, operator-facing statement that
ensemble-dispersion uncertainty is certified on 5 of 6 criteria with a measured, unexplained
inversion on the sixth, and that `G16` is therefore an accepted limitation of this generation.
The item-108 circuit breaker already mitigates the *consequence*; it does not resolve the *cause*.

### 4.4 `G18_MARKET_BASELINE` — FAIL, and possibly unsatisfiable by construction

The gate requires the candidate to beat the de-vigged market RPS **in every league**. Measured: 1/6
by point estimate. Worse, `docs/DEBT.md` item 62 ran a **paired block bootstrap** (10,000 replicates)
on that single win and found its 95% CI `[-0.0029, +0.0028]` — indistinguishable from zero.
**0 of 6 leagues have a CI excluding zero, for the candidate *and* for the serving incumbent.**

DID §54.2 records the structural reason: *the raw de-vigged market outscored both fitted arms on 2 of
3 folds.* A model trained on market probabilities does not reliably improve on them at this feature
count.

**This is a live DID Rule 14 candidate** — "a gate no candidate can satisfy is a defect in the gate."
It is not yet established as unsatisfiable; unlike G1's hard 62.35% ceiling, no proof exists that
*no* feature set can beat the market. So:

- ❌ **Do not loosen it.** Changing `{"leagues_beating_market": "all"}` after observing that it is
  what blocks promotion is precisely APEX §23's prohibition, and H1/H4 above.
- ✅ **Build the Rule 14 escalation dossier** and put it to the operator as **OG-06**, with the block
  explicitly on the record: the paired-bootstrap CIs for all 6 leagues, both arms; DID §54.2's fold
  results; the measured gap; and three options (amend to a majority or CI-based rule / restrict
  scope to leagues with demonstrated edge / accept the capability as serving-only under
  `PROMOTE_RESEARCH_ONLY`). **The operator decides. You prepare.**

---

## 5. Execution plan — APEX phases P0–P18

> **Numbering rule (APEX §13):** exactly 19 phases, `P0`–`P18`. Tasks are `P<n>.T<m>`. Never invent
> alternate phase identifiers. The **Tracks** below are scheduling groupings only — they are not
> phase identifiers, and every task still carries its `P<n>.T<m>` id.

Each phase exits only on its exit condition (APEX §40), emitting `PHASE_STATUS · OUTCOME · EVIDENCE ·
CHANGED_FILES · OPEN_RISKS · BLOCKERS · NEXT_PHASE`. A blocked phase does not silently advance.

### Track A — Ground truth and merge integrity (run first, blocks everything)

**P0 — Ground Truth.**
- `P0.T1` Sync `master`; confirm working tree clean; record SHA.
- `P0.T2` Run `./scripts/ci_local_enforcer.sh` to a **zero exit**. `docs/DEBT.md` item 99 makes this
  mandatory before every commit. A skipped gate in its summary is not a pass (INV-17).
- `P0.T3` Re-measure everything in §3 and correct this document in place (§0.1).
- `P0.T4` Establish live state: backend `/health` SHA, `/health/ready` components, Vercel
  `/api/health` SHA, migrations head, settled-prediction count. If egress is blocked, say so and
  route through the operator — **do not report live state you could not read** (INV-02).
- **Exit:** baseline table in §3 is current; enforcer green; live state known or explicitly marked
  unread.

**P16 — Deployment & CI Integrity** *(pulled forward — it guards every later phase)*
- `P16.T1` **`docs/DEBT.md` item 104 is `NOW` and unresolved:** `master`'s ruleset has
  `deletion`, `non_fast_forward`, `required_linear_history`, `pull_request` — and **no
  `required_status_checks` rule**. Red CI has never blocked a merge here. Prepare the exact ruleset
  change and put it to the operator. This is repository settings, not code — **OG-gated, prepare
  only.** Until it lands, `P0.T2` is the only real gate (INV-17).
- `P16.T2` Verify backend/frontend SHA parity per §3.4's three innocent explanations before
  declaring any deploy incident.
- **Exit:** parity verified; item 104 dossier delivered to operator.

### Track B — Evidence accumulation (the long pole; start early, it is time-gated)

**P2 — Data Provenance & Entity Integrity.**
- `P2.T1` Confirm entity integrity holds: zero self-play rows, zero duplicate Elo pairs, zero
  non-canonical league ids, zero `?`-corrupted team names.
- `P2.T2` `docs/DEBT.md` item 40 — PSG's Elo history on the Paris FC row, a place-name collision.
  Two distinct clubs merged. Repair is Class C; build the review manifest, do not mutate.
- `P2.T3` `docs/DEBT.md` item 22 — `the_odds_api` key regressed. Without it,
  `clv_capture` captures nothing and `G19`'s evidence stops accumulating. **Operator-only.**

**P10 — Ingestion & Scraper Reliability.**
- `P10.T1` Confirm fixture sync, settlement sync and CLV capture are all running and their
  `/health` components report `ok` with non-zero throughput.
- `P10.T2` OG-04 (scraper production activation) stays `PENDING` unless the operator moves it.

**P4 — Experiment & Model Governance.**
- `P4.T1` `docs/DEBT.md` item 86 — `training_manifest.json` declares `apex_v1_68` for the same
  `v5_phase7` artifact suffix `active_generation.json` calls `phase7_68`. A bare-suffix naming
  collision is this repository's recurring two-vocabulary failure shape. Confirm benign or fix.

> **Track B has a hard floor nothing can shorten: real matches must be played and settled.** Do not
> simulate, synthesize, or backfill settled outcomes to reach a floor (INV-01, DID Rule 5).

### Track C — Certification evidence (the actual deliverable)

**P5 — Calibration & Uncertainty.** → drives `G11`, `G16`
- `P5.T1` Re-run calibration evaluation once settled volume clears the floor. The serving stack now
  correctly calls the trained `SoftmaxMetaModel` (DEBT 87), but that head is itself **uncalibrated** —
  it predates the item-64 calibration-selection cascade. Record which calibrator actually ran.
- `P5.T2` Resolve `G11_CALIBRATION` to `PASS` or `FAIL` on real evidence. A FAIL is a result.
- `P5.T3` G16 disposition per §4.3 — advance a hypothesis or write the accepted-limitation record.

**P6 — Certification Policy & Metrics.** → drives `G12`, `G14`, `G15`
- `P6.T1` Evaluate Brier decomposition, multiclass log-loss and ECE on the settled population.
  Resolve all three `UNVERIFIED` gates to a verdict.
- `P6.T2` Policy stays frozen at **v1.2.0**, `policy_sha256() = 4e050ad00ff6dcf8c00661e8976486025109a63f6144a9afe8e3e60a2387f664`, unless the operator moves it (H1). ⚠️ `CLAUDE.md` also quotes `41cb7703…f8f3dab` — that is the **v1.0.0** hash and is stale for the current policy. Re-derive from `policy_sha256()`, never copy a hash forward.

**P8 — Model Comparison & Market Diagnostics.** → drives `G18`
- `P8.T1` Regenerate `feature_availability_matrix.json` **before** reading any gate — it is a stale
  input that `compare_candidate_vs_incumbent.py` reads but never writes.
- `P8.T2` Re-run the candidate/incumbent comparison on the current holdout. Report the honest gate
  table: `no_league_regression` and `market_baseline` counts, per league, with paired bootstrap CIs.
- `P8.T3` Assemble the Rule 14 / OG-06 dossier per §4.4.

**P7 — Drift & Monitoring.** `G17` stays `NOT_APPLICABLE`. Re-check the count; wire nothing (§4.2).

### Track D — Platform coherence (parallel; independent of evidence volume)

**P14 — Frontend Intelligence UX.** This is the "visually cohesive" half of the mandate.
- `P14.T1` Enforce the canonical hierarchy on every intelligence surface:
  `MATCH → MODEL PROBABILITY → FAIR PROBABILITY → CONFIDENCE/EVIDENCE → MARKET COMPARISON →
  PROBABILITY DELTA → SUPPORTING EVIDENCE → LIMITATIONS`.
- `P14.T2` Percentage points, never "6% edge" unless the surface defines the term.
- `P14.T3` Audit **every** backend failure mode against APEX §28.1's mapping table. No raw HTTP
  status, stack trace or generic error string may reach a customer surface. Any unmapped mode is a
  defect.
- `P14.T4` Research / shadow / certified states must be visually distinct **and semantically
  accessible** — never color alone (WCAG).
- `P14.T5` **Extend the repo-wide contract-test idiom rather than hand-checking.** Seven already
  exist (`copy-contract`, `evidence-copy-contract`, `league-contract`, `metadata-title-contract`,
  `model-identity-contract`, `timestamp-contract`, `full-analysis-contract`). This pattern has
  caught what hand-greps missed — including a ninth offender a hand-written grep had missed. Add one
  for the §28.1 vocabulary mapping and one for the §14 hierarchy ordering. **Watch each fail first
  (§2.1).**
- `P14.T6` `docs/DEBT.md` item 21 lists frontend residuals left deliberately after the 2026-08-13
  truthfulness pass. Re-read; close what is now closable; keep what is still deliberate.
- **Zero-fabrication on display surfaces is the standing hazard here.** This repository has found
  four distinct instances of a neutral backend default rendered as a measurement (Elo `1500/1500`,
  RL reward components, credible intervals, `edge_quality_score` mislabels). **Every new stat tile
  must be checked against what the backend emits when evidence is absent.**

**P13 — Observability & Security.**
- `P13.T1` `docs/DEBT.md` item 67 — "zero Sentry issues" is a false negative; nothing is
  instrumented. Either instrument it or stop citing it as evidence.
- `P13.T2` OTel is registered but a true no-op without an OTLP endpoint. Record that honestly;
  activating it is OG-10 if it carries recurring cost.

**P11/P12 — Infrastructure & Runtime / Backend, DB & Redis.**
- `P11.T1` `docs/DEBT.md` item 94 — the WebSocket real-time layer is wired and deployed but dormant
  end to end: no producer publishes to `match_events:{id}`, no consumer connects, and ISR
  revalidation is fail-closed on unset env. Turning it on is a **product decision**, not cleanup.

**P9 — Betting Safety.** Verified `ALREADY_CORRECT` 2026-09-13. Re-verify, change nothing:
no `EXECUTE_BET` path exists; UCL is hard-capped below `HIGH_CONVICTION` in **both** engines
(INV-03); `stake_permitted` gating intact. **Any change here is OG-12.**

**P15 — LLM Explanation Safety.** Explanations must be evidence-bound; no certainty vocabulary (§6).

### Track E — Close-out

**P1 — Architecture Reconciliation.** Subsystem inventory current; every change classified.
**P3 — Feature & Weather Integrity.** Items 36 (9 of 10 contract fields still `UNDECLARED`), 44
(weather acquired but not a feature), 29 (6 of 21 Phase-8 columns structurally underivable).
**P17 — Testing & Customer Smoke.** Full local enforcer + Playwright desktop/mobile + live smoke.
**P18 — Certification, Promotion & Release.** §6 below.

---

## 6. Certification and release (P18)

### 6.1 Produce the report

Regenerate via `backend/scripts/compile_certification_report.py` into
`artifacts/certification/certification_report_<generation>_<timestamp>.json`, **or** a dated Markdown
gate table under `docs/certification/` following `blocked-release-report-2026-09-14.md`.

**Never overwrite a historical report — write a new dated file** (APEX §32.3). Required top-level
sections, all of them: `report_version · generated_at · repository · deployment · model · data ·
policy · metrics · gates · operator_gates · risks · changes · validation · decision`.

### 6.2 Decide honestly

```
EXECUTION STATUS     = what the agent is doing
CERTIFICATION STATUS = what the evidence currently proves
RELEASE DECISION     = what may be promoted
```

**Do not merge these** (APEX §34). `Execution: COMPLETE` + `Certification: HOLD` + `Release: HOLD` is
a valid, common, correct outcome. A completed coding task does not imply a certifiable release.

Mandatory `HOLD`: any required gate `UNVERIFIED` or `BLOCKED`, any required operator gate `PENDING`,
deployment identity incompatible, or required evidence missing.

### 6.3 Release reproducibility and rollback

A release must be reconstructable from source SHA · dataset snapshot · provider versions · feature
contract · model artifact · calibrator artifact · policy version+hash · evaluation config · serving
manifest (APEX §35). Rollback must be **executable, not theoretical** (APEX §36).

---

## 7. Per-commit protocol

```bash
./scripts/ci_local_enforcer.sh          # MANDATORY, zero exit, no skipped gates (DEBT 99)
```

Then, for the change you made:
1. **Rule 15** — revert the fix, watch the guard fail naming the right file, restore (§2.1).
2. Re-read your own diff adversarially: what would make CI reject this?
3. Keep the diff minimal (INV-07). Do not widen scope on your own.
4. `git diff --name-only | grep -E "betting_intelligence|core_engine"` — both or neither (INV-03).
5. If you changed a feature attribution string, **regenerate `backend/models/feature_contract.json`**
   or the Render build gate fails the deploy.
6. New `DEBT.md` entry for every newly discovered defect (APEX §37); append-only (INV-06).

**When two open PRs both touch `docs/DEBT.md`, rebase the second on the first.** A squash merge of a
branch cut before an entry existed deletes that entry with no conflict and no warning — it has
already happened once, to the only record of a live staking override.

---

## 8. What this programme cannot deliver — operator decisions required

State these plainly in every status report. None of them yields to more code.

| Blocker | Gate / Item | Decision needed |
|---|---|---|
| `market_baseline` all-leagues rule vs. measured 0/6 CI | G18, DEBT 62 | **OG-06** — amend, restrict scope, or accept serving-only (§4.4) |
| Promotion beyond `FORECAST_ONLY` | OG-07 | Operator approval, after gates |
| `master` has no required status checks | DEBT 104 | Repository ruleset change |
| `the_odds_api` key invalid | DEBT 22 | Key rotation + Render env update |
| Scraper production activation | OG-04 | Operator |
| Redis credential revocation | DEBT 15 | Console evidence, dated |
| Historical Gitleaks fingerprints | DEBT 16 | Credential owner's dated revocation |
| `sabiscore.com` DNS `SERVFAIL` | — | Registrar; deprioritized by operator 2026-08-27 |
| Docker image build proof | DEBT 16 | No reachable daemon in agent environments |
| Settled-outcome volume | G11/G12/G14/G15/G17 | **Elapsed real-world time only** |

---

## 9. Response contract

Every implementation response carries both blocks (APEX §9, §10):

```
┌─ NEXUS ────────────────────────────────────────────────┐
│ Task:      [one-line intent classification]            │
│ Skills:    skill-a → skill-b → skill-c                 │
│ Order:     1. skill-a  2. skill-b  3. skill-c          │
│ Overrides: [conflict resolutions, or NONE]             │
│ Risk:      [critical risks identified, or NONE]        │
└────────────────────────────────────────────────────────┘

EXECUTION STATUS     : <state>
CERTIFICATION STATUS : <state>
RELEASE DECISION     : <state>
PHASE                : P<n>  STATUS: NOT_STARTED|ACTIVE|COMPLETE|BLOCKED|HOLD
EVIDENCE             : <test / report / artifact / query — never prose>
BLOCKERS             : <or NONE>
NEXT                 : P<n>.T<m>
```

---

## 10. Closing principle

The measure of this programme is not how many gates end green. It is whether a future engineer can
read the certification report and know **exactly what was proven, what was not, and which of those
was a decision rather than a discovery.**

A gate that fails honestly is worth more than a gate that passes because someone moved it.
