# SabiScore — Production Executive Directive (v3, 2026-09-06)

Supersedes v2 (2026-09-03). Every constant below was read out of the repository
or a live endpoint on 2026-09-06, after PR #156 merged as `1115d1d`. v2's
failure mode was "confidently wrong constants driving work that could not
succeed" — three of v2's own headline numbers had already drifted by the time
this was written (§0). This version adds a harder constraint v2 did not have:
**a fourth independent measurement, from a different angle each time, that the
market cannot currently be beaten by anything in this repository — including
the market's own forecast against an intuitive accuracy bar.** Any directive
that asks for "high-accuracy predictions" as a near-term deliverable is asking
for something this repository has now measured four ways and not found. §2
reframes the mission around what is actually achievable and valuable; §5–§7
are the concrete plan under that reframing.

---

## 0. Verified ground truth — do not restate from memory, re-verify next time

| Fact | Verified value | Source | vs. v2 |
|---|---|---|---|
| Head commit | `1115d1d` (PR #156, squash-merged) | `git log` | — |
| Deploy parity | Render `sha:1115d1d` `healthy`; Vercel `sha:1115d1d`, `backendSha` full match, `backendStatus:ok` | live probe, this session | confirmed in sync |
| Active generation | `v5_phase7-20260808` | `models/active_generation.json` | unchanged |
| Certification state | `UNVERIFIED` / `ACTIVE_FAIL_CLOSED` | same | unchanged |
| Served feature schema | `phase7_68` (68 columns) | same | unchanged |
| **Feature contract SHA-256** | `2f80df948bb52e0a1f746271573c3b448fd6be23f322b2c988cf6d3a98076288` | `models/feature_contract.json` | **v2 quoted a different hash — regenerated since (PR #149 changed a training-side attribution string; the file is content-hashed, so any attribution edit moves it)** |
| **Certification policy** | **v1.1.1**, SHA-256 `f823648253fc2708fc676b5fe25da807d3393d25a62bf80a3085508f130908f8` | `certification_policy.policy_sha256()` | **v2 quoted v1.1.0 / a different hash — bumped since, PR #153 era** |
| `serving_feature_availability` | FAIL — `training_defaulted_slots=16` (needs 0), `always_data_gap_slots` floor now **6** (was 4) | DEBT item 49 | **v2 didn't carry this number; verify fresh each time — it has moved twice since 2026-08-22** |
| `market_baseline` | FAIL — **0 of 6 leagues**, both the best candidate and the serving incumbent, with 95% CI | DEBT item 62, this session | **new: v2 treated this as a point-comparison gate; it is now a bootstrapped, statistically confirmed 0/6** |
| `MODEL_UNCERTAINTY_UNAVAILABLE` | CRITICAL, unconditional, on 100% of live requests | `full_analysis.py:_uncertainty_from_features` | unchanged; DEBT item 50 |
| Live staking state | `stake_permitted: false` on every fixture, all 5 providers `enabled:true` | live census, this session | providers now fully enabled (v2-era blocker resolved) |
| mypy ceiling | 784 (currently 769) | `scripts/check_mypy_ceiling.py` | unchanged |
| Backend suite | 2284 passed, 17 skipped, 2 xfailed | this session, full run | +5 vs. v2's 2279 (new tests from this session) |

### Constants v2 got wrong or let go stale — the exact failure mode this file exists to prevent

- ❌ Feature contract hash `7681886093e33af4…` → now `2f80df948bb52e0a1…`. **A content hash is not a fact you carry forward — it moves whenever a hashed field changes, and it changed twice between v2 and v3.**
- ❌ Policy `v1.1.0` / `7e1e2384…` → now `v1.1.1` / `f8236482…`.
- ❌ v2 treated `market_baseline` as answerable by a single RPS comparison. It is not — see §2. A 0.0005 RPS margin over 375 fixtures is statistically indistinguishable from zero (§2), and v2 had no way to know that because nobody had built the instrument yet.
- ❌ "3 of 5 providers disabled, Render Blueprint sync outstanding" — resolved; all 5 are `enabled:true` in production today. Do not re-flag this.
- ✅ Everything else in v2 §0 (runtime, React pin, `training_defaulted_slots` mechanism, dual-loader hazard) re-verified unchanged and still holds.

---

## 1. Closed questions — do not re-litigate without new evidence

Each row is a measurement, not an argument. v2's table carried five; this adds
a sixth, and strengthens the framing on one v2 already had.

| Question | Verdict | Evidence |
|---|---|---|
| Heterogeneous ensemble to clear Gate 50 | **REFUTED** — 3 seed blocks. RF-only skill negative at every N tested | DEBT 59 |
| Adding xG causal drivers (`apex_v2_71`) | **REJECTED** — mean RPS −0.00159, market_baseline 0/5 | DEBT 58 |
| Populating the 4 (now 6) `ALWAYS_DATA_GAP` slots | **INERT** — zero-variance columns, no tree splits on them | DEBT 56 |
| Populating h2h/venue/interaction slots (`apex_v3_68`) | **REJECTED** — 16→3 defaulted slots, genuinely used (35→43 responsive features), still 0/6 vs. market | DEBT item filed 2026-09-04, `apex-v3-68-candidate-evaluation.md` |
| Re-specifying `error_association` per stratum | **FORBIDDEN** — post-hoc threshold change; also would not cleanly pass | DEBT 50 |
| BullMQ / Celery / Node worker layer | **REJECTED** — competing scheduler; FastAPI lifespan loops are correct and sufficient at current load (§0: full-analysis measured 1–2.5s cold, not the "heavy ML inference" a queue would be justified by) | DEBT 54 |
| BNN / PyTorch staking path | **CLOSED** — ADR 0009 locks `ensemble_dispersion` as the only authorised method | DEBT 42/43 |
| **HPO + a league-stratified certification carve-out (`apex_v5_66`, EPL)** | **REJECTED — paired bootstrap CI, 0/6 leagues, both heads** | **DEBT 62, this session** |

**The corollary v2 stated is now measured, not inferred:** `uncertainty_policy.py`
states clearing `MODEL_GENERATION_UNCERTIFIED` does not clear
`MODEL_UNCERTAINTY_UNAVAILABLE`, and the converse holds. Both gates are
independently, currently, unconditionally failing — one on a statistically
confirmed 0/6 result, one on a real, reproducible-both-ways sign reversal
(`error_association`, DEBT 50). **Clearing either would not enable staking.
Clearing both is not currently possible by any means this repository has not
already tried.**

---

## 2. The central finding, reframed — read this before writing any more model code

v2 said: "the single blocker is: no SabiScore model beats the de-vigged
market-implied RPS in any league." That was correct but incomplete, and its
incompleteness is what licensed a plausible-sounding but wrong follow-up
proposal (the EPL stratification directive this session rejected). The
complete picture, assembled from four independent measurements across three
different sessions:

1. **DEBT 58** — adding real, causally-validated xG features (ATE > 0.18,
   p < 1e-68) made the model *worse* against the market in 4 of 5 leagues.
2. **`apex_v3_68`** — adding real h2h and home-venue history (genuinely used:
   responsive features rose 35→43 per league) produced a statistical wash
   against the incumbent (3 wins, 3 losses) and 0/6 against the market.
3. **DEBT 62 (this session)** — the single number that looked like an edge
   anywhere in this whole program (`apex_v5_66`, EPL, +0.0005 RPS) is
   **0.078σ of an unpaired standard error**, and a properly paired 95% CI on
   the exact same data has a half-width **5.7x** the point estimate. It spans
   zero. So does the incumbent's.
4. **DEBT 43** — the de-vigged bookmaker market's own Brier score is 0.5787,
   which fails the platform's own BNN certification gate (≤0.220) **by 2.6x**.
   The market — priced by firms with structurally more capital, faster data,
   and more staff than this project — is not "highly accurate" by that bar
   either.

**Read together, these four say something more specific than "the model isn't
good enough yet": football's 1X2 outcome, at the horizon and evidence this
platform has, is close to its predictability ceiling once market information
is available, and that ceiling is well short of what "high-accuracy
predictions" connotes to a general audience.** This is not a defect to
engineer away. It is very likely close to the actual shape of the domain —
consistent with a large academic and industry literature on football
outcome forecasting that this project's own four measurements now
independently reproduce.

**What this changes about the mission, concretely:**

- **Do not promise "high accuracy" as a product claim.** APEX §11 and
  CLAUDE.md's prohibited-copy list already forbid `guaranteed`/`sure bet`/
  `lock`; this finding means the softer promise — "our model is highly
  accurate" — is equally unsupportable and should be held to the same
  standard. The honest, defensible, and (per APEX's own design intent)
  differentiating claim is **calibration and transparency**: "here is exactly
  how much we know, how we know it, and where the gaps are" — not
  "trust our accuracy."
- **Do not spend further engineering cycles on §1's closed feature-density
  branch.** Three different feature families (xG, h2h/venue, and a fourth
  covered by HPO) have now been tried and rejected by the same mechanism.
  A fifth attempt in the same shape (find/engineer a feature, retrain,
  compare RPS) should be expected, on priors, to fail the same way, and
  should not be greenlit without a stated reason to expect a different
  result than the last three.
- **Two structurally different levers remain**, neither of them "more
  features": (a) event-level data this platform does not have at all
  (real StatsBomb shot-maps/PPDA at scale — `home_pressing_intensity` and
  `progressive_carry_diff` remain the only two permanently-gapped slots,
  DEBT 49/56, blocked on data acquisition, not modeling); (b) `error_association`
  (DEBT 50) — a genuine open research question about whether ensemble
  dispersion tracks real error on football data at all, not an engineering
  gap. Neither is "try another feature and retrain."
- **The product's value, if it is not "beats the market," is honest
  intelligence infrastructure** — evidence provenance, calibration displayed
  as a first-class citizen (not buried), a portfolio-exposure view, and a
  UX that makes "why does this fixture have no bet" as informative and
  well-designed as "why does this fixture have one." §6 is this section made
  concrete.

---

## 3. Non-negotiable constraints (carried forward from v2, re-affirmed)

**Architecture.** FastAPI is the sole backend authority. PostgreSQL is durable
truth; Alembic is the only schema authority. Redis is hot state. `apps/web` is
presentation + BFF and computes no EV, stake, edge, or de-vigging. **No second
job queue** — confirmed again this session against a live latency measurement
(full-analysis: 2.5s cold, ~1s warm; a queue would add a second cold-start
surface, not remove one). No second team-name normalizer beside
`team_identity._identity_key`.

**Zero fabrication.** Unobserved is `None`, never `0.0`, never a neutral prior
presented as a measurement. A feature that training defaults must not be
described as observed. This now extends explicitly to **product copy**: a
"confidence" or "accuracy" claim is fabrication in the same sense a fake
feature value is, if it is not backed by a number the platform can show its
work for.

**Train/serve parity is bidirectional.** Serving must not consume a feature
training never varied; training must not consume a feature serving cannot
reproduce. Both directions are tested (`test_feature_vector_parity.py`).

**Fail-closed.** A gate that blocks promotion or staking is never relaxed to
unblock it. "Uncertainty remains unavailable and fail-closed" and "no model
currently beats the market" are acceptable terminal outcomes; a manufactured
PASS, a stratified carve-out built to admit one flattering number, or a
softened accuracy claim are not — this directive treats all three as the same
category of violation after this session's evidence.

**Memory.** 8 GB dev machines. `maxTsServerMemory ≤ 3072`. ML research venv is
`.venv-ml`; no training deps on Python 3.14.

**Attribution.** `Co-authored-by: SCAR (Claude Code) <claude@anthropic.com>` on
commits; the standard PR footer on pull requests.

---

## 4. The two remaining model-side gates, precisely

### 4.1 `serving_feature_availability` — one bounded, authorization-gated fix

`training_defaulted_slots` is 16 (needs 0); of those, 6 are the permanent,
by-policy `PHASE7_FEATURES_ALWAYS_DATA_GAP` slots that can never be anything
else (DEBT 49). The correction that measures *unexpectedly* defaulted slots
instead of counting the permanent ones was scoped, implemented once already
(2026-09-03) and even has its exact diff recorded in DEBT 49 — but it does not
promote anything (16→ still nonzero; `serving_schema_misaligned_slots` is
independently 11 from a separate deadlock, DEBT 37). **This is a measurement
correction, not a threshold change**, by the same reasoning item 38 already
used — but per APEX §23 it still needs an explicit authorization before
landing, exactly as item 38 and item 49's prior pass both required. If you
want this gate's number to be honest, authorize the one-liner in DEBT 49 and
regenerate the availability matrix. It will not flip `promotion_permitted` to
`true` on its own — `market_baseline` and the uncertainty gate are
independent and both still fail.

### 4.2 `error_association` — a real research question, not a backlog item

DEBT 50. The highest-epistemic quartile scores *better* RPS than the lowest,
in every league, on two independent member-selection designs. This is not
something a sprint closes. Two honest paths, both requiring an explicit
decision rather than more code:

- **Accept it as a property of this domain and this uncertainty method**,
  and stop treating staking-readiness as the platform's near-term target —
  consistent with §2's reframing.
- **Fund a genuine research effort** (a different uncertainty
  quantification method entirely — not a threshold change on the current
  one) with no assumption it succeeds. `ADR 0009` would need superseding,
  not amending, since it names `ensemble_dispersion` as the *only* authorised
  method.

Nothing in §5–§7 depends on this resolving. Both are compatible with shipping
a genuinely useful product now.

---

## 5. Execution order

Sequenced by what is bounded and authorization-ready versus what is open-ended
research versus what is pure product value that does not wait on either.

### Phase A — Close what is bounded (days, not weeks)

1. Get an explicit authorization decision on DEBT 49's one-line measurement
   fix (§4.1). Land it or explicitly decline it — do not leave it as a
   standing "authorized but not applied" note a third time.
2. Resolve DEBT item 57 (Understat corpus: 1,826 duplicated matches, 2021/22
   season missing) if any future feature work will read that corpus again.
   Bounded data-hygiene, no modeling judgment required.
3. Run the domestic fixture-identity SQL audit this session shipped
   (`backend/scripts/sql/investigate_domestic_aliases_v3.sql`) against
   production and resolve the 7 domestic identity failures it was built to
   diagnose (of 22 total; 15 are UCL and correctly unresolved). This directly
   reduces the live `REQUIRED_MODEL_INPUTS_UNAVAILABLE` rate, independent of
   any certification question.

### Phase B — The one open research question (§4.2)

Get an explicit decision from whoever owns this platform: accept the current
`error_association` result as a domain property (recommended, given four
independent measurements now pointing the same direction), or commission a
genuinely new uncertainty-method research effort with a stated budget and no
guaranteed outcome. **Do not let this phase block Phase C** — it is
independent of every product/UX improvement below.

### Phase C — The product, reframed around §2

This is the "fully operational, visually cohesive, world-class platform" the
mission calls for, built on the honest premise §2 establishes: the value is
transparency and calibration, not an accuracy claim the evidence does not
support.

**Implementation checkpoint — PR #157 (2026-09-06).** The first bounded
frontend increment of Phase C is complete. It changed presentation and
consumer-copy enforcement only: no backend response contract, calibration
calculation, certification state, promotion rule, verdict gate, Kelly rule, or
staking permission changed. The active generation remains `UNVERIFIED` /
`ACTIVE_FAIL_CLOSED`.

**C1. Make calibration a first-class, not buried, surface — first increment
complete.**
`/performance` already has the pieces (Murphy decomposition, walk-forward RPS,
CLV) gated on real-data floors most of which are still below threshold. Where
the floor is not yet crossed, the UI's job is to say so with the same design
quality as when it is — a floor-not-met state is not an error state, it is
real information ("11 settled predictions; 10 needed before a reliability
curve is meaningful" reads as competent, not broken). Audit every stat tile
against DEBT-documented neutral-defaults incidents (items 24/28/41 in the
historical ledger) before shipping a new one — the recurring failure mode
this platform has hit five times is rendering a registry default as if it
were a measurement.

PR #157 now distinguishes a legitimate sample-floor state from malformed
contracts and infrastructure failures, carries the selected evaluation window
through the request, states the serving-generation and settled-record scope,
and exposes plotted observations in a keyboard-readable table. It retries only
retryable infrastructure failures and removes the unsupported ECE target.
Future additions remain subject to the neutral-default audit above.

**C2. Finish the Evidence Passport pattern everywhere a verdict appears —
audited fixture surfaces complete.**
Per-family provenance, freshness, and resolution status, visible without a
click, using the existing `describeEvidenceCode()` vocabulary. A gapped
family renders as gapped, styled with the same care as a resolved one —
this is the concrete expression of "transparency over accuracy" as a design
principle, not a slogan.

PR #157 completes this contract for the two audited fixture-specific verdict
surfaces: full analysis and betting intelligence. Both use the shared human
evidence vocabulary and age labels without merging their distinct wire
contracts. Result-backed analytical sharing now derives probabilities,
verdict, model maturity, stake permission, and gap counts from a successfully
parsed full-analysis response; fixture-header sharing remains URL-only.
Reduced-evidence output exposes no analytical share action. Static verdict
education and team-form taxonomy remain outside this fixture-evidence rule.

**C3. Model-identity discipline stays enforced, not re-litigated.**
`lib/model-identity.ts` (APEX §11) already maps internal generation strings to
consumer-safe labels and fails closed on an unrecognised state. Any new
surface showing model provenance routes through it — do not re-introduce a
raw `v5_phase7`/`UNVERIFIED` string on a consumer page, the exact defect this
session's history (item 41) already found and fixed once.

**C4. Accessibility and performance as table stakes, not a phase.**
WCAG 2.2 AA contrast, ≥24px targets, visible focus, `prefers-reduced-motion`
respected — verify at 360/768/1280px on every new surface, per the standing
convention this repo already follows (§5 of every prior directive said this;
it has not changed).

**C5. SEO and growth, bounded by the truthfulness constraint.**
`robots.ts`/`sitemap.ts` exist; extend them as new public routes ship.
Metadata titles are guarded by `metadata-title-contract.test.ts` — extend
coverage to any new route rather than hand-writing a title. No growth copy
may use the accuracy framing §2 forbids; the differentiator in metadata and
social copy is "evidence-first," "shows its work," "calibrated," never
"accurate" or "wins."

**C6. Prohibited-copy list gains one more entry — complete.**
Given §2's finding, `CLAUDE.md`'s existing prohibited-terms list
(`lock`, `banker`, `guaranteed`, `sure bet`, `free money`, `execute
immediately`) is now supplemented by aligned Vitest and CI phrase guards for
unsupported outcome claims such as "highly accurate predictions," "winning
picks," and "beats the odds/market." The guard is intentionally contextual:
measured or walk-forward accuracy, historical match wins, and backend-owned
edge metrics remain valid analytical language. Public documentation now also
describes the active artifacts as hash-verified research artifacts with model
certification still pending.

---

## 6. Verification

```bash
# backend/
ruff check src --select E4,E7,E9,F     # CI's actual scope — not scripts/, not tests/
python scripts/check_mypy_ceiling.py    # ceiling 784; never raise it
PYTHONPATH=. python -m pytest tests/unit -q
PYTHONPATH=. python -m pytest tests/integration -q
python scripts/verify_active_artifacts.py

# apps/web/
pnpm exec tsc --noEmit
pnpm exec next lint --dir src
pnpm build

# repo root — full release gate
make verify        # no step may be bypassed with `|| true`
```

Deployment parity: compare `GET /health` `sha` (Render) against
`GET /api/health` `sha`/`backendSha` (Vercel) and local `git rev-parse
--short=7 HEAD` after any push — three-way match, not two.

Any claim about a market-beating candidate must be accompanied by
`scripts/bootstrap_market_edge_ci.py` output with the CI excluding zero,
ideally under the reported Bonferroni column — a point-estimate RPS
comparison alone is no longer sufficient evidence in this repository (§2).

---

## 7. Definition of done

A phase is done when **all** hold:

1. Code merged with tests proportional to risk, CI green (all required checks,
   not just the ones that happened to run — confirm via `gh pr checks`, and
   re-verify after any post-open-PR commit, including ones you did not push
   yourself: this session found a GitHub Copilot auto-fix agent had pushed
   directly to an open PR branch mid-review).
2. Any new measured model result is recorded under `backend/reports/` or
   `docs/DEBT.md` — including, especially, a negative one. Product-only work
   does not manufacture a model finding merely to satisfy this checklist.
3. Documentation updated: `CHANGELOG.md` and the relevant directive or
   architecture document; `docs/DEBT.md` and the model card when a candidate,
   durable defect, or model-state change was actually evaluated.
4. No gate threshold changed. No `active_generation.json` promotion without
   all seven `certification_policy` gates passing on their own evidence, and
   no consumer-facing accuracy claim without a calibration number to back it.
5. Production state re-verified and reported, including when unchanged —
   three-way SHA parity (Render / Vercel / local HEAD), not assumed from a
   prior session's report.

**The platform is production-ready today in the sense that matters: it fails
closed correctly, and it can now say precisely how far from staking-ready it
is, in numbers, four ways. It is not, and will not soon be, a high-accuracy
prediction engine — the evidence for that ceiling is now as solid as anything
else in this codebase. The version of "world-class" available to this
platform right now is the most honest, best-calibrated, best-designed
evidence-transparency product in its category — not the best predictor. Build
that.**
