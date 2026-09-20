# SabiScore — Data Intelligence & Prediction Improvement Directive v6

### Production Data Intelligence, Information Gain & Forecast Improvement Programme

**Version:** 6.1 · **Supersedes:** v5 (2026-09-08) · **Date:** 2026-09-20 (v6.0: 2026-09-18)
**Repository:** `sabiscore/sabiscore` · **Status:** ACTIVE RESEARCH GOVERNANCE

**Governing principle:** **New trustworthy information → measurable incremental information gain → statistically defensible out-of-sample improvement → production-grade intelligence**

---

## Changelog (v6.0 → v6.1, 2026-09-20)

One rule strengthened, by the same standard the rest of this document holds itself to: an observed
execution failure, not a review opinion.

**Rule 15 gains two measured instances and one corollary.** A metadata-registration guard was
watched failing — in the only configuration where it works — and merged to `master` inert; and
`alembic check` was cited as passing for a class of drift its comparator cannot see. The corollary:
*watching a guard fail once is not enough — it has to be watched failing in the configuration CI
runs*, and a guard sharing mutable process state with the rest of the suite must be isolated before
its failure is evidence of anything.

Nothing else in v6.0 changed. No threshold, gate, experiment decision or statistical requirement is
touched.

---

## Changelog (v5 → v6)

v5 governed 15 registered experiments but **existed nowhere in this repository** — it lived only in
chat transcripts. `reports/research/experiment_registry.yaml` cited it as
`PRODUCTION_EXECUTIVE_DIRECTIVE.md §38`; that filename resolves to the *Production Execution &
Certification Directive v7.4*, whose §38 is "Documentation Discipline" and which has no §51 at all
(it ends at §46). Every `§38 / §39 / §51` citation in the registry therefore pointed at the wrong
document and a section that does not exist. A governance document that is not in version control
cannot govern, and §38's own rule — *"no research result exists unless it is reproducible from the
registry"* — was undercut by the registry pointing into thin air. **Committing this file at a stable
path, and repointing `schema_reference` at it, is the single largest correction in v6.**

Substantive changes, each earned by an observed execution failure rather than by review:

1. **§0.1 (new)** — document identity, precedence against v7.4, and citation discipline. A bare
   "§23" was ambiguous between two active directives.
2. **Rules 11–15 (new)** — verify the brief's own premises; a null is not a negative; name the
   cherry-pick; an unsatisfiable gate is a defect in the gate; verify the enforcement mechanism,
   not just the gate.
3. **§15.7 (new)** — run a cheap information test on the coverage you already have *before*
   investing in coverage expansion.
4. **§16 Stage 3** — the raw de-vigged market reference is now **mandatory**, not optional.
5. **§26** — the escalation ladder gains its first measured empirical anchor.
6. **§36** — a named tool must be verified installable in the target interpreter before an
   experiment plans on it.
7. **§40 Gate R7.1 (new)** — certification must verify that its enforcement mechanism is live.
8. **§51** — explicit authority split: who may take a terminal decision.
9. **§54–§57 (new)** — recorded empirical findings, operational verification discipline,
   duplication policy, and this document's own maintenance rules.

**⚠️ Numbering stability is a hard constraint of this revision.** §51 is cited 45 times across
scripts, registry entries and `docs/DEBT.md`; §20, §18, §42, §23, §21 are each cited 20+ times.
**No v5 section was renumbered.** Additions are appended (§54+) or inserted as sub-sections
(§X.1). Where v5's prose was wrong — §5 claimed to contain six portfolios while containing one —
the *text* was corrected and the *number* left alone.

---

# 0. Mission

SabiScore must not pursue prediction improvement as a generic feature-engineering or
model-complexity exercise.

The objective is to determine, with production-grade evidence, whether SabiScore can acquire **new
information genuinely unavailable to its current forecasting system**, transform it into
reproducible pre-match intelligence, and demonstrate **incremental out-of-sample predictive value**
beyond:

1. the current SabiScore incumbent;
2. the de-vigged market baseline;
3. established structural baselines;
4. information already represented by the current feature contract.

The required chain:

> **New information** → **reliable acquisition** → **correct temporal reconstruction** →
> **independent information** → **incremental predictive value** → **statistically significant and
> practically meaningful improvement** → **production-safe serving** → **continuous verification**

No component may be skipped.

The programme answers a narrower and harder question than *"what additional football features could
we add?"*:

> **"What information does SabiScore not currently know, can know before prediction time, can
> reconstruct historically without leakage, can acquire legally and reproducibly, and can
> demonstrate to contain incremental information after conditioning on SabiScore and the market?"**

If no source survives that sequence, the correct outcome is a documented negative result.

---

## 0.1 Document identity, precedence and citation discipline

**Two directives are active and they do not compete.**

| Document | Path | Governs |
|---|---|---|
| **Production Execution & Certification Directive v7.4** | `docs/PRODUCTION_EXECUTIVE_DIRECTIVE.md` | Execution, hardening, gates G01–G30, operator gates OG-01–OG-12, invariants INV-01–INV-24, release and certification |
| **Data Intelligence Directive v6** (this file) | `docs/DATA_INTELLIGENCE_DIRECTIVE.md` | Research, information acquisition, experiment design, statistical evidence, §51 decisions |

**Precedence.** Where the two touch the same subject, **v7.4 wins on anything that reaches
production** — certification, promotion, staking, serving, safety vocabulary, invariants. This
document wins on anything that stays in research — experiment design, statistical standards,
registry schema, source qualification. Neither may loosen the other's gates. An experiment that
passes every gate here still faces v7.4's certification unchanged (§40 Gate R7).

**Citation discipline is mandatory and was previously absent.** A bare `§23` is ambiguous: v7.4's
§23 forbids post-hoc gate loosening, this document's §23 is the Event Data Research Programme.
Every citation must name its document:

```text
DID §23      this document
APEX §23     PRODUCTION_EXECUTIVE_DIRECTIVE.md (v7.4)
```

Existing bare citations in `reports/research/` and `docs/DEBT.md` predate this rule. They are not
retroactively rewritten — that would be a large, low-value diff across research records that are
otherwise correct — but **every new citation uses the prefixed form**, and any bare citation being
edited for another reason is corrected in passing.

---

# 1. Strategic Position

## 1.1 Current evidence

Established across multiple independent analyses in this repository:

- the incumbent does not demonstrate an edge over the de-vigged market;
- previous feature-expansion programmes produced negligible aggregate improvement;
- the system carries a meaningful calibration defect;
- the uncertainty contract is incomplete;
- several apparent public "gates" were not part of the versioned certification policy;
- parts of the data stack are installed but unused;
- several promising-looking research directions are blocked by coverage or production constraints.

These are not invitations to repeat the same experiments. They establish the research prior:

> **Future improvement must come from better use of information already available, better
> extraction of latent structure from legitimately available information, or genuinely new
> information unavailable to the incumbent.**

The programme must explicitly distinguish these three.

---

## 1.2 Primary strategic objectives

**Objective A — Repair known forecast defects.** Improve calibration and forecast integrity using
information already held.

**Objective B — Discover genuine information gaps.** Identify information unavailable to the current
system with a credible causal relationship to pre-match outcomes.

**Objective C — Prove incremental value.** Demonstrate improvement in proper scoring rules and/or
decision-relevant metrics *after conditioning on incumbent and market*.

**Objective D — Convert only surviving evidence into production intelligence.** Integrate without
weakening train/serve parity, provenance, fail-closed semantics, licensing discipline, or
certification.

---

# 2. Non-Negotiable Research Doctrine

## Rule 1 — Information beats feature count

One independent source with demonstrable incremental value outweighs dozens of redundant derived
features. Feature volume is not progress.

---

## Rule 2 — Data acquisition is itself an experiment

A source may not be integrated because it is free, popular, column-rich, contains xG, has
event-level data, was used in a paper, or is used by another analytics project.

A source first requires:

> **coverage → legality → temporal reconstructability → reliability → identity resolution →
> redundancy analysis → incremental information test**

Only then may engineering investment be authorized.

---

## Rule 3 — Pre-match information is the unit of truth

Every candidate feature must answer: **exactly when did this information become knowable?**

The canonical record includes source timestamp, observed timestamp, publication timestamp where
applicable, effective timestamp, fixture kickoff, allowed prediction cutoff, freshness at inference,
and whether the value changed between historical observation and post-match archival state.

A feature reconstructed from current historical webpages is not automatically valid for historical
inference.

---

## Rule 4 — Historical availability must be reconstructable

Current data existing does not make a source historically valid. Distinguish:

**A. Historical reconstructability** — the value reproduces as it existed before kickoff.
**B. Historical availability with revision risk** — exists historically, may have been corrected after the match.
**C. Current-only availability** — usable for production, unsuitable for retrospective evaluation.
**D. Post-match archival data** — usable for analysis, prohibited from pre-match forecasting.

This distinction must exist in the experiment registry.

⚠️ **A source can silently serve category D while appearing to serve category A.** Measured: the
Open-Meteo Historical Forecast API returns ERA5 *reanalysis* — post-hoc actuals — with a well-formed
HTTP 200 and no warning for any date before its archive begins. Three of seven corpus seasons would
have trained on post-match truth believing it was forecast. The guard is a hard date cutoff probed
against the reanalysis endpoint hour by hour, not care. **Probe the boundary; do not assume the
endpoint tells you.**

---

## Rule 5 — No fabricated data

Unknown remains `None`. Missing information must not become `0`, league average, neutral prior,
"not injured", "normal weather", "average player", synthetic odds, or placeholder confidence.

**A missing value is a state of knowledge, not a measurement.**

---

## Rule 6 — The market is mandatory evidence

No candidate is a predictive improvement merely because it beats the incumbent. Every meaningful
experiment compares:

> candidate vs. incumbent vs. de-vigged market vs. appropriate structural baseline

A candidate may demonstrate better calibration, discrimination, distributional forecasting,
conditional performance or robustness **without beating the market**. Those are valid findings. They
must not be translated into "market edge" without separate evidence.

---

## Rule 7 — Redundant market reconstruction is not independent signal

A source that primarily reconstructs bookmaker probability is not an independent football-information
source. Market-derived features may still be useful, but are classified as **market intelligence**,
not **independent football intelligence**.

The research must explicitly estimate how much a candidate adds beyond the market.

---

## Rule 8 — No model shopping

A failed information source cannot be passed through increasingly sophisticated models until one
produces an apparent improvement. The information layer must demonstrate value before architectural
escalation.

> source → data quality → information value → representation → simple model → advanced model

not

> source → transformer → ensemble → HPO → report improvement

---

## Rule 9 — Statistical uncertainty is mandatory

No decision rests on a point estimate. Every candidate result includes sample size, temporal test
window, metric convention, confidence interval, paired comparison, effect size, statistical test,
multiple-testing context, practical significance, and robustness across folds or periods.

---

## Rule 10 — Negative evidence compounds

A failed experiment narrows the research space. The experiment registry and `docs/DEBT.md` are
research assets, not administrative records. Each negative result must improve the prior.

---

## Rule 11 — Verify the brief's own premises before executing it

**New in v6. Earned twice in a single execution cycle.**

An instruction — from an operator, a prior directive, or a prior session's own notes — may contain a
premise that is false in the current repository. Executing it faithfully then produces confident,
well-documented nonsense.

Before acting on a brief, verify every factual premise it asserts:

- named tools exist and run in the target environment (DID §36);
- named files, fields, endpoints and flags exist at the cited path;
- claimed prior states ("X is now fully sourced", "Y is merged", "Z is blocked on W") hold against
  the current SHA;
- the stated blocker is the *binding* one.

Measured instances, both in one cycle:

| Premise as briefed | Measured reality |
|---|---|
| "Run walk-forward on XGBoost and **CatBoost**" | CatBoost is pinned `python_version < "3.14"` in all three requirements files, has no wheel for the 3.14.6 interpreter, and is **not a member of the served ensemble** (`random_forest + xgboost + lightgbm` → logistic meta) |
| "F3 is **fully sourced**, geographically isolated and confirmed" | Geocoding was fixed, but G1's binding constraint was never geocoding — 4,806 of 12,765 fixtures predate the forecast archive, capping *perfect* geocoding at 62.35% against an 85% bar |

Neither was worked around silently. Both were executed as far as the evidence permitted and the
correction reported alongside the result. **State the correction; deliver the rest of the scope.**
A false premise is not grounds to narrow the work — it is grounds to name what cannot be done and
finish what can.

---

## Rule 12 — A null is not a negative

**New in v6.**

"Indistinguishable from baseline" and "measurably worse than baseline" are different findings with
different consequences, and a binary promote/reject label erases the difference in both directions.

Every result must report:

- the **decision label** the promotion framework requires (DID §51); and
- the **precise reading**, separately, stating which of these was measured:
  - *improves* — paired CI excludes zero in the candidate's favour;
  - *no measurable effect* — paired CI straddles zero; the candidate is statistically
    indistinguishable from baseline;
  - *degrades* — paired CI excludes zero against the candidate.

Measured instance: the F3 weather Stage 3 test returned `DEGRADES_BASELINE` under a binary operator
rule, while all six pooled CIs straddled zero — every point estimate in the 4th decimal of RPS, log
loss moving < 0.008 and ECE < 0.002 in *both* directions across folds. Recording only the label
would have claimed weather actively harms the forecast, which the evidence does not support.

⚠️ **Report a secondary-metric null explicitly.** A candidate can cut log loss by growing sharper
while getting worse calibrated; only reporting both shows it. A null on RPS *and* log loss *and* ECE
is much stronger evidence of no information than a null on RPS alone.

---

## Rule 13 — Name the cherry-pick

**New in v6.**

Rule 9 requires multiple-testing context. That is necessary but not sufficient: a per-slice census
that *exists* in a JSON file still gets quoted selectively months later.

Every result that scores more than one slice (league, band, period, learner) must publish, in the
narrative record and not only the machine record:

- how many slices were scored;
- how many would clear the bar by chance at the stated level;
- how many cleared it favourably and how many unfavourably;
- **the single most quotable favourable slice, named explicitly, with the reason it is not
  evidence.**

Measured instance: of 32 per-league slices in the F3 test, exactly one had a CI excluding zero
favourably (BUNDESLIGA, test 2025, logistic) — and the *same league on the same fold* under XGBoost
was significant in the opposite direction, against ~1.6 expected false positives. That slice is
named in `docs/DEBT.md` item 103 precisely so it cannot later be cited as a Bundesliga weather
effect.

No per-slice result may be presented as a finding unless it was pre-registered as a hypothesis.

---

## Rule 14 — A gate no candidate can satisfy is a defect in the gate

**New in v6.**

A gate that is unsatisfiable by construction is not a high standard; it is a broken instrument. It
must be escalated as a defect — **not silently loosened, and not ground against indefinitely.**

Two live instances:

- **Structurally unsatisfiable:** the promotion gate required `always_data_gap_slots == 0`, while
  four (now six) features are permanent `ALWAYS_DATA_GAP` slots in every 68-wide schema by
  deliberate design. A flawless candidate failed. (`docs/DEBT.md` item 38.)
- **Unreachable ceiling:** Gate G1 requires 85% fixture coverage; the forecast archive caps it at
  62.35% no matter how much geocoding work is spent. (`docs/DEBT.md` item 103.)

The required response is an explicit, authorized decision recorded in the registry — amend the gate,
restrict the experiment's scope, or accept the capability as serving-only. **Loosening a threshold
after observing that it is what blocks a result is prohibited** (APEX §23) and is not what this rule
authorizes. The decision must be reachable *before* the blocking result is known, or taken by the
operator with the block explicitly on the record.

---

## Rule 15 — Verify the enforcement mechanism, not just the gate

**New in v6.**

A gate that is defined, tested and documented still enforces nothing if the mechanism that runs it
is not live. Confirm the mechanism, not the definition.

Five measured instances in this repository:

- **CI that never ran.** Under the GitHub Actions billing lock, every job reports
  `conclusion: "failure"` — identical to a genuine test failure. Only
  `GET /actions/runs/{id}/jobs` exposes `runner_name` and the executed-step count; the lock's
  signature is `runner_name: ""` with `steps: 0`. Three defects reached `master` during a period
  when the suite appeared merely red. (`scripts/verify_remote_ci.sh`; `docs/DEBT.md` items 16, 99.)
- **A merge gate that was never configured.** `master`'s ruleset contains `deletion`,
  `non_fast_forward`, `required_linear_history` and a 1-approving-review `pull_request` rule —
  **no `required_status_checks`**. Red or absent CI has never blocked a merge here, independent of
  the billing lock and outliving it. (`docs/DEBT.md` item 104.)
- **A guard that WAS watched failing — in the only configuration where it works.** *(added
  2026-09-20.)* `tests/unit/test_alembic_metadata_registration.py` asserted against the
  process-global `Base.metadata`. Reverting the `alembic/env.py` import and running that file alone
  reddened 3 tests, and that reading was recorded in the PR as evidence. But
  `tests/unit/test_adversarial_m2_m3.py` imports `src.api.main` → `auth.py` →
  `social_auth_models`, and **"adversarial" sorts before "alembic"**, so in the full-suite
  collection CI actually performs, the mapper is already registered before a single assertion in
  the guard executes. The identical revert then gives **16 passed**. The guard was inert in CI from
  the commit that introduced it, and shipped that way to `master` in PR #220. Fixed by capturing
  the metadata in a fresh interpreter (`subprocess`, importing only `env.py`'s derived module set);
  the same experiment then gives **3 failed**.
- **A gate that could not fail at all.** *(added 2026-09-20.)* Every check in CI's
  "Zero-fabrication scan" — nine of them, including the one forbidding a deprecated stdlib call
  across `src` — was written as `! grep …`. POSIX exempts a command whose return value is inverted
  with `!` from `set -e`, so a positive match did not abort and the step's exit code was only ever
  the **last** line's. Eight checks were decorative from the day they were written, and a real
  violation sat in `master` while the gate reported green. Reproduced under exactly what
  `shell: bash` invokes: on the identical seeded violation the old form exits **0** and the
  repaired form exits **1**. ⚠️ **The first repair was also inert, differently**:
  `out="$(grep …)"; rc=$?` takes the substitution's status, so under `set -e` a *clean* grep aborted
  the step — caught only by executing the script, not by reading it. (`docs/DEBT.md` item 111.)
- **A gate that is structurally blind to a class of drift.** *(added 2026-09-20.)* `alembic check`
  with `compare_type=True` cannot report an unbounded ORM `String` against a migration's
  `VARCHAR(32)`: its default comparator reduces to
  `t1.length is not None and t1.length != t2.length`, so a metadata type with no length reads as
  *don't care*. The gate ran on real PostgreSQL 15 with migration 0014 applied and passed while
  three `user_identities` columns genuinely disagreed. **A green gate is evidence only for the
  classes it can see** — before citing one, read what it actually compares.

> **A guard you have not watched fail is not a guard, and a gate you have not watched block is not
> a gate.**
>
> **And watching it fail once is not enough — it has to be watched failing in the configuration CI
> runs.** A guard that shares mutable process state with the rest of the suite (module-level
> registries, import side effects, a global `metadata`) proves nothing when run alone. Isolate it
> — a subprocess, a fresh interpreter — before its failure is evidence of anything.
>
> **And a gate written in shell must be executed, not read.** `set -e` does not mean what it looks
> like it means around `!`, `||`, `&&` and command substitution; two consecutive attempts at the
> same nine-line scan were silently non-enforcing for two different reasons. Seed a violation, run
> the real script under the runner's own shell invocation, and watch it exit non-zero.

---

# 3. Current Ground Truth — Mandatory Re-verification

**Re-verify at the start of every working session, not merely every research cycle.** v5 required
this "before any new research branch is authorized", which proved too coarse: within one cycle,
three PRs merged to `master` without the executing session knowing, and work began against a
13-commit-stale local clone.

Do not rely on this document, or on any prior session's summary, for values that can be measured.

**Repository** — current SHA; branch; dirty state; **`origin/master` vs local divergence**; **open
and recently-merged PRs**; active generation; model artifact identity; feature schema; model
registry; certification policy; certification hash; active thresholds; training configuration.

**Deployment** — Render SHA; Vercel SHA; backend SHA; local SHA; backend/web divergence; deployment
timestamp. ⚠️ A backend SHA behind the frontend's is usually *correct* — `render.yaml` sets
`rootDir: backend` and Render skips deploys when nothing under it changed. Check
`git diff --name-only <deployed>..HEAD -- backend/` before calling it an incident.

**Database** — PostgreSQL version; Alembic head; schema inventory; active prediction tables;
feature/data provenance tables; model-generation tables.

**Runtime** — Python version; production dependency tree; research dependency tree; memory limits;
inference latency; feature resolution latency; external provider latency.

**Evidence** — settled prediction count; calibration metrics; RPS; Brier; log loss; ECE; market
baseline; CLV diagnostic; uncertainty status; staking status; promotion gates.

**Enforcement (new in v6, per Rule 15)** — is CI actually executing? are required status checks
configured? is the local enforcer clean? Record the answer, not the assumption.

Output: `GROUND_TRUTH_SNAPSHOT_<date>.json`, immutable for the experiment cycle.

---

# 4. The SabiScore Information Model

Five formally distinguished layers:

**Layer 1 — Raw information.** What the external world says: shot, player availability, lineup
announcement, injury, referee, weather, market quote, manager appointment.

**Layer 2 — Validated observation.** After schema validation, timestamp validation, identity
resolution, duplication checks, provenance assignment, source confidence classification.

**Layer 3 — Prediction-time state.** The subset legally and temporally available at a specific
prediction cutoff. **This is the authoritative training/serving object.**

**Layer 4 — Derived representation.** Rolling xG; expected minutes; replacement strength; tactical
compatibility; pressing mismatch; dynamic team state.

**Layer 5 — Forecast.** `P(Home)`, `P(Draw)`, `P(Away)`; score distribution; confidence interval;
conformal set where authorized.

This separation prevents post-match or revised data from silently entering the feature space.

---

# 5. Research Portfolio — index

The programme is divided into **six portfolios, defined in §5 through §10**:

| Portfolio | Section | Subject |
|---|---|---|
| A | §5 (below) | Calibration |
| B | §6 | Player availability intelligence |
| C | §7 | Event-derived team state |
| D | §8 | Tactical matchup intelligence |
| E | §9 | Information arrival / market microstructure |
| F | §10 | Contextual state |

*(v5 announced six portfolios under §5 and then defined only Portfolio A here, with B–F as separate
top-level sections. The numbering is load-bearing and unchanged; this index removes the ambiguity.)*

## Portfolio A — Calibration

> Can SabiScore materially improve the statistical quality of its probabilities without acquiring
> additional information?

Candidates: temperature scaling; vector scaling; isotonic regression; beta calibration;
hierarchical calibration; horizon-conditional calibration; probability shrinkage; class-specific
calibration.

Primary target: **reduce reliability while preserving or improving resolution.**
Secondary: ECE; log loss; RPS; Brier.

**Calibration does not constitute a market-edge claim.**

⚠️ Calibration evidence must be measured on a holdout, never in-sample. A calibrator fitted and
scored on identical rows reports a perfect `ece_after` that means nothing. In-sample figures may be
retained only as explicitly labelled diagnostics beside the holdout headline.

---

# 6. Portfolio B — Player Availability Intelligence

The highest-priority new-information branch. The hypothesis is not "players are important" but:

> **The current match-level system may know team strength but fail to observe last-minute changes
> in the composition and expected quality of the team actually available to play.**

Investigate: injuries; suspensions; probable XI; confirmed XI; expected minutes; replacement
quality; bench depth; role importance; positional scarcity; lineup continuity; player return timing;
minutes restrictions; manager selection patterns.

The representation should not initially be player-name-heavy. Start with measurable latent
quantities:

- **Availability delta** — `expected_available_strength − baseline_team_strength`
- **Replacement cost** — `starter_strength − expected_replacement_strength`
- **Positional disruption** — importance-weighted missing strength by role
- **Continuity** — expected XI overlap with recent XI
- **Depth resilience** — quality retained after removing unavailable players

Only after these aggregates survive should player embeddings or lineup graphs be considered.

---

# 7. Portfolio C — Event-Derived Team State

Do not begin with a universal StatsBomb/VAEP implementation. First determine where sufficient
coverage exists.

Candidate families: shots; shot locations; xG; passes; progressive actions; possession chains;
pressures; turnovers; defensive actions; set pieces; transition frequency; final-third entries.

The central question is not *"can we calculate xT?"* but:

> **"Does event-derived team state contain information that the current SabiScore + market
> representation does not already contain?"**

Candidate representations: rolling opponent-adjusted xG; shot-quality profile; shot-location
distribution; build-up directness; progression intensity; pressing intensity; transition propensity;
set-piece strength; defensive concession profile.

---

# 8. Portfolio D — Tactical Matchup Intelligence

The highest-value "unknown unknown" branch. The objective is not to classify teams as possession /
pressing / defensive — usually too coarse. The target is **interaction**:

- pressing vulnerability × opponent build-up quality;
- low-block attack quality × opponent low-block defense;
- transition creation × opponent transition concession;
- aerial/set-piece strength × opponent set-piece weakness;
- progressive carrying × opponent defensive channel exposure;
- defensive line height × opponent runner threat.

> **Team A behavior × Team B susceptibility**, not independent team statistics.

No tactical feature may be promoted unless out-of-sample evidence shows the interaction adds more
than its constituent components.

---

# 9. Portfolio E — Information Arrival / Market Microstructure

Investigates whether useful information enters the public forecasting ecosystem over time.

Required timestamps where available: opening quote; subsequent quote; lineup publication; injury
update; manager announcement; weather revision; closing quote.

Questions: When does meaningful probability movement occur? What observable external event coincides
with it? Does a non-market source provide the same information earlier? Does SabiScore gain by
observing the source directly? Is the effect independent of final market state?

Candidates: opening → intermediate movement; cross-book dispersion; market disagreement; quote
volatility; pre-lineup vs post-lineup movement; injury/news shocks; weather shocks; convergence
velocity.

A model that reproduces the final market is not an independent-information success.

---

# 10. Portfolio F — Contextual State

Rest; fixture congestion; travel distance and time; time-zone displacement; weather; altitude;
stadium conditions; referee characteristics; scheduling asymmetry.

Intentionally lower priority. Must prove information value before engineering investment.

> Default prior: potentially useful, but likely weaker than player availability, team state,
> tactical interaction and information-arrival signals.

**The prior has since been tested twice and held both times.** F1 (rest/congestion/referee) closed
REJECT. F3 (T−2h weather forecast) reached a full Stage 3 test on 4,921 fixtures across three
walk-forward origins and two learners: **no measurable effect**, all six pooled CIs straddling zero
(DID §54.1). Portfolio F is not a promising branch that has been under-resourced; it is a branch
whose own stated prior has been confirmed by measurement. Treat further F-family proposals
accordingly.

---

# 11. Data Source Qualification Framework

Every external source receives a formal score across:

| Dimension | Requirement |
|---|---|
| Coverage | Relevant fixtures represented |
| Historical depth | Adequate retrospective window |
| Temporal fidelity | Historical values reconstructable |
| Freshness | Appropriate for serving |
| Identity quality | Stable entity mapping |
| Reliability | Measured source consistency |
| Missingness | Quantified, not assumed |
| Independence | Incremental information potential |
| Legal status | Explicitly classified |
| Access stability | API/scrape/download reliability |
| Cost | Free/freemium/paid |
| Rate limits | Measured |
| Integration cost | Engineering estimate |
| Compute cost | Processing estimate |
| Operational fragility | Failure likelihood |
| Provenance | Raw-data retention possible |

---

# 12. Source Legal / Access Classification

**L0 — Explicitly reusable.** Open licence / explicit public-data terms permitting intended use.
**L1 — Research-use constrained.** Usable for research; legal review before production.
**L2 — Publicly visible, rights unclear.** No production entry without explicit approval.
**L3 — Terms hostile to automated production access.** Research-only unless status changes.
**L4 — Prohibited.** Do not ingest.

The roadmap must never describe "publicly scrapeable" as equivalent to "legally reusable."

---

# 13. Data Opportunity Matrix

Every candidate source receives a row:

| Opportunity | Source | Signal | Current Gap | Coverage | History | Temporal fidelity | Independence | Cost | Legal class | Integration | Leakage risk | Expected information gain | Priority |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

> Priority = **expected information gain × coverage × temporal reliability × legal viability ÷
> implementation cost**

Not source popularity.

---

# 14. Tier Definitions

**Tier 0 — Immediate research.** Plausibly high-value; current system lacks it; historical testing
feasible; integration cost bounded. Candidates: calibration; player availability;
lineup/expected-minutes state; historical event-derived team state where coverage clears;
information-arrival/market timing.

**Tier 1 — High-value conditional.** Tactical matchup; replacement quality; squad depth; dynamic
team state; set-piece matchup; manager-change state.

**Tier 2 — Research.** Richer network representations; graph-based lineup representations;
state-space team models; temporal embeddings.

**Tier 3 — Experimental.** Transformers; deep spatial encoders; GNNs; neural point processes. No
Tier-3 architecture may be built merely because it appears in the literature.

**Reject.** Redundant feature expansion; repeated league carve-outs; repeated HPO without new
information; market-copying features; low-coverage sources; legally unsuitable scraping; features
depending on post-match revisions; features that default on an unacceptable share of served
fixtures; architectures adding complexity without information gain.

---

# 15. Coverage Gate

**G1 — Fixture coverage.** Percentage of SabiScore fixtures with usable records.
**G2 — Historical depth.** Contiguous seasons and gaps.
**G3 — Cross-season stability.** Whether coverage collapses outside the source's strongest seasons.
**G4 — Cross-league portability.** Whether the signal generalizes beyond one competition.
**G5 — Prediction-time availability.** Percentage available at the intended prediction cutoff.
**G6 — Default rate.** A candidate with a high production default rate is rejected unless the
missingness is separately modeled and demonstrably informative.

---

## 15.7 Run the cheap information test before buying coverage

**New in v6.**

v5's ordering — coverage gates (§15) strictly before information testing (§16) — is correct as a
*promotion* sequence but wrong as a *spending* sequence. It licenses expensive coverage work on a
source whose information value is still entirely unknown.

> **If an information test is runnable on the coverage already in hand, run it first.**

A null on partial coverage is nearly always decisive, because coverage expansion changes sample
size, not the presence of signal. A source with no measurable information at n = 4,921 will not
acquire it at n = 8,000.

Measured instance: `docs/DEBT.md` item 103 posed three expensive options for F3's unreachable G1
ceiling — lower the bar by authorized decision, restrict scope to the post-archive window, or accept
serving-only. **All three were moot.** The Stage 3 test on existing coverage returned a null, which
settled the question at the cost of one afternoon and zero additional acquisition.

The gates in §15 remain mandatory **before promotion**. They are not mandatory before *learning
whether promotion is worth pursuing*. Where a cheap test exists, the registry must record why it was
or was not run before coverage investment was authorized.

---

# 16. Information Value Testing

Hierarchical evidence, not correlation-first.

## Stage 1 — Descriptive

Distributions; variance; missingness; season drift; league drift; entity coverage.

## Stage 2 — Dependence

Mutual information; conditional mutual information; residual association; monotonicity; redundancy;
feature-feature dependence. **Diagnostic tools, not promotion criteria.**

## Stage 3 — Incremental forecasting

Fit the smallest defensible temporal baseline. Compare:

```text
incumbent            vs.  incumbent + candidate
market               vs.  market + candidate
raw de-vigged market      (unmodeled reference — MANDATORY)
```

This isolates whether the information contributes to SabiScore, to the market, or to neither.

⚠️ **The raw unmodeled market reference is mandatory in v6, not optional.** v5 made it conditional
("where given"). It is the cheapest line in the harness and it caught something no other comparison
could: in the F3 test the **raw de-vigged market beat both fitted models on 2 of 3 folds**
(test 2024: raw 0.19690 vs logistic 0.19741 vs XGBoost 0.20482). Without it, "candidate ≈ baseline"
reads as a clean null; with it, the finding is that *neither model earns its own existence on this
feature set*. That is a different and more actionable result.

Implementation: `backend/scripts/_incremental_value_harness.py` — one shared implementation, several
callers. Do not write a fourth copy (DID §56).

## Stage 4 — Conditional value

Performance across probability bands; leagues; team-strength bands; home/away; congestion; data
completeness; lineup disruption; prediction horizon. **A feature that performs only in one fragile
slice is not globally validated** — and see Rule 13 before quoting any slice.

---

# 17. Primary Statistical Test

> Does candidate information reduce expected proper scoring loss out-of-sample?

**Primary:** RPS; multiclass Brier; log loss.

**Secondary:** ECE; Murphy reliability; Murphy resolution; calibration slope/intercept; sharpness;
CLV only under a proper economic definition; economic utility only after the forecast is certified.

Per Rule 12, secondary metrics are reported whether or not they move — a null across RPS, log loss
and ECE together is materially stronger evidence than a null on RPS alone.

---

# 18. Statistical Validation Protocol

**Temporal integrity.** No random train/test split for forecasting claims.
**Walk-forward evaluation.** Rolling-origin across multiple periods.
**Final untouched holdout.** Sealed until the hypothesis is frozen. Where none was reserved, say so
explicitly in the registry rather than leaving the field blank.
**Paired evaluation.** Identical eligible test fixtures for candidate and baseline.
**Confidence intervals.** Block bootstrap appropriate to temporal dependence.
**Hypothesis correction.** Pre-declared multiple-testing protocol (FDR or family-wise) where
multiple candidates are tested — plus the Rule 13 census.
**Effect size.** Absolute and relative.
**Practical significance.** A statistically detectable but operationally negligible result must not
be promoted.
**Robustness.** Must not depend on one season, league, seed or narrow parameter choice.

---

# 19. No Arbitrary `ΔBrier` Gate

Do not hard-code a universal threshold such as `ΔBrier ≥ 0.01` unless a power analysis shows it
appropriate for the available sample and business objective.

Instead: **statistical criterion** (paired CI excludes zero); **practical criterion** (exceeds a
pre-registered minimum effect size); **robustness criterion** (survives multiple temporal folds);
**market criterion** (does not merely reproduce the market); **operational criterion** (source
remains available and reliable in production).

⚠️ A threshold cited in a directive but absent from `certification_policy.py` is not a gate. Before
applying any numeric bar, confirm it exists in the hashed policy (APEX §23, DID Rule 15).

---

# 20. Calibration Workstream

**B1 — Immutable baseline.** Persist RPS; Brier; reliability; resolution; uncertainty; ECE; log
loss; reliability plots; sample count; calibration window.

**B2 — Candidate recalibration.** Temperature scaling; vector scaling; isotonic regression; beta
calibration where justified. Use the existing independent calibration holdout.

**B3 — Promotion test.** A candidate succeeds only if calibration error materially improves;
discrimination does not materially degrade; proper scoring does not degrade; improvement survives
paired uncertainty analysis; behaviour persists on untouched data; existing promotion gates pass.

⚠️ **Selection over a fixed recipe set, judged on a holdout, is an accept/reject gate — not a
fitting target — and this distinction must be stated wherever the practice is used.** Choosing among
four fixed calibrators by holdout performance is bounded and auditable; tuning a calibrator's
parameters against that same holdout is not. A stricter reading requiring a fourth untouched split
is a legitimate policy change and requires an explicit decision, not a silent tightening.

---

# 21. Uncertainty Workstream

Conformal prediction may be investigated; the claim must be explicit.

**Valid:** "The system's prediction sets achieve measured marginal coverage under the evaluation
assumptions."
**Invalid:** "The system now knows which predictions will be wrong."

Non-adaptive split conformal may be evaluated first. Adaptive methods are prohibited until an
appropriate difficulty signal has been demonstrated.

Acceptance criteria: empirical coverage; nominal coverage; set size; failure concentration;
stability across temporal windows. **Coverage alone is not sufficient.**

⚠️ An uncertainty signal that fails to associate with error is a real negative result, not a tuning
problem. Where highest-epistemic-uncertainty slices score *better* than lowest across every
scoreable league, that is a finding about the decomposition, and it must not be resolved by
relaxing the gate (`docs/DEBT.md` item 50).

---

# 22. Player Availability Research Programme

**Hypothesis.** Pre-match player availability and expected lineup quality contain incremental
information not already represented by SabiScore team-state features and market probabilities.

**Data candidates** (research, do not prematurely integrate): injury feeds; suspension information;
lineup announcements; expected lineups; player appearances; minutes; role; squad depth.

**Derived representations.** Unavailable starting-strength; replacement cost; positional disruption;
expected-XI continuity; expected available strength; bench resilience.

**Baseline.** `incumbent` vs `incumbent + availability`; `market` vs `market + availability`; raw
market reference.

**Promotion requirement.** Incremental value independent of final market probability.

---

# 23. Event Data Research Programme

Before implementing `socceraction`, VAEP, xT or GNN infrastructure:

**D1 — Coverage audit.** Measure the StatsBomb/Understat identity crosswalk.
**D2 — Event completeness.** Event completeness; missing matches; malformed events; team identity
consistency; shot coverage; player identity coverage.
**D3 — Prediction-time aggregation.** Build only pre-match rolling state.
**D4 — Information test.** Demonstrate incremental predictive value.
**D5 — Representation escalation.** Only after simple aggregates survive: xT; VAEP; possession
chains; graph representations; spatial encoders.

This prevents a high-complexity implementation from masking a low-information dataset.

⚠️ **A connector that has shipped, been tested and never produced an artefact has not been
validated.** A zero-artefact connector means suspect the connector, not the schedule — a green suite
over a module whose only real integration path has never executed is not evidence that path works.

---

# 24. Tactical Interaction Research

The first tactical model should be explicit and interpretable:

```text
home_pressing_intensity × away_build_up_vulnerability
```

rather than immediately building a GNN.

Candidates: press × buildup; transition × defensive concession; set-piece attack × set-piece
defense; crossing × aerial vulnerability; carry × defensive containment; line-height × depth-runner
threat.

The question is whether interaction terms improve the conditional forecast **after accounting for
their constituent signals**.

---

# 25. Structural Baselines

Evaluation-only reference models: historical frequency; league-adjusted frequency; Elo; dynamic Elo;
Poisson; Dixon-Coles; market implied probability; current SabiScore; simple blend; candidate model.

These are reference instruments, not automatic production candidates.

---

# 26. Model Escalation Ladder

**Level 0** simple statistical baseline · **Level 1** regularized logistic/linear · **Level 2**
existing tree ensemble · **Level 3** calibrated ensemble · **Level 4** dynamic state-space /
Bayesian · **Level 5** sequence model · **Level 6** graph/spatial model.

A model may advance only if the preceding level shows the information warrants greater
representational complexity.

## 26.1 Measured anchor (new in v6)

The ladder now has an empirical data point from this repository rather than only a principle:

> On 5 features over ~2,400–4,000 training rows, **Level 2 (XGBoost, the repository's own shipped
> `_BASE_PARAMS`) was uniformly worse than Level 1 (multinomial logistic)** across all three
> walk-forward origins — RPS ≈ 0.203 vs ≈ 0.197, ECE 0.038–0.055 vs 0.018–0.031.

Escalating architecture at this feature count and sample size costs both discrimination *and*
calibration. Cite this measurement when a proposal seeks to skip Level 1.

---

# 27. Auxiliary Targets

Secondary targets may include goals scored; goals conceded; expected goals; shot volume; chance
quality; first goal; scoreline distribution; latent team strength.

Auxiliary prediction is not automatically useful. Before multi-task learning, test: **does the
auxiliary task improve the primary 1X2 distribution?** If not, it remains research-only.

---

# 28. Market Intelligence Rules

Separate **market baseline** (used to evaluate the model), **market information** (used as a
feature), and **economic execution data** (used only after certified forecasting).

No metric may be labelled "CLV" unless it measures actual price movement relative to an obtainable
reference price. A model-belief-minus-closing-probability diagnostic must have a different name, and
CLV may be sourced only from records explicitly flagged as closing lines.

---

# 29. Error-Driven Research Engine

The backlog is generated from observed failures. For every failed prediction record: league;
team-strength band; market probability; model probability; calibration residual; prediction horizon;
lineup state; availability state; congestion state; tactical state where available; source
completeness; market movement.

Aggregate into failure clusters. Select the next acquisition hypothesis partly from:

> **largest reproducible error cluster × plausible missing information × acquisition feasibility**

---

# 30. Unknown-Unknowns Programme

Every cycle contains a structured exercise asking:

> What materially relevant match information exists in the real world that is absent from our data
> model because we have never represented it?

Families: expected starting XI; player role changes; lineup chemistry; replacement quality; manager
tactical adaptation; opponent-specific tactical mismatch; set-piece matchup; schedule fatigue;
information arrival timing; squad rotation; manager-change regime shifts; latent tactical state;
market-news lag.

Classify each: **H1** observable and testable → proceed · **H2** observable but difficult →
feasibility research · **H3** latent but inferable → representation research · **H4** speculative →
document, do not engineer before a testable proxy exists.

---

# 31. Data Architecture

```text
External Source → Acquisition Adapter → Raw Immutable Store → Validation →
Entity Resolution → Temporal Alignment → Prediction-Time State → Feature Generation →
Feature Contract → Training Dataset / Serving → Model → Calibration → FastAPI →
Production Observability
```

PostgreSQL is durable application truth. Alembic is schema authority. Redis is hot operational
state. FastAPI is backend authority.

No second queue. No second team-name normalizer. No hidden feature service. No client-side
prediction computation. (Extended to research code by DID §56.)

---

# 32. Raw Data Rules

Every new source requires raw payload retention; source URL/API identifier; acquisition timestamp;
source timestamp; schema version; content hash where feasible; parser version; transformation
version; licence/access classification.

A derived feature must always be traceable back to its raw observation.

---

# 33. Feature Lineage

```text
feature_id · source_id · source_timestamp · effective_timestamp · prediction_cutoff
transformation_version · availability_status · missingness_semantics
training_eligibility · serving_eligibility · provenance
```

This becomes part of certification. Fields no code can answer carry the literal `UNDECLARED` —
never a plausible reconstruction.

---

# 34. Production Failure Semantics

External data failure must not silently produce a fabricated feature. Permitted outcomes:

**A** feature available and valid · **B** feature unavailable and omitted · **C** feature dependency
makes prediction ineligible · **D** system fails closed.

No fallback to arbitrary neutral values.

⚠️ A neutral default is also forbidden on the *display* surface. A backend that fills an absent Elo
with `1500/1500` must not be rendered as a measurement; render `—`.

---

# 35. Memory and Compute Policy

Development target: ~8 GB RAM; CPU-first; remote GPU only when justified.

Preferred: DuckDB; Polars; PyArrow where genuinely required; memory-mapped data; Parquet; streaming
aggregation; incremental processing.

Production dependencies remain minimal. A research dependency belongs in the ML environment unless
runtime serving genuinely requires it.

The registry records peak RSS; runtime; CPU usage; disk consumption; dataset size; model artifact
size.

⚠️ Optimize against measurement, not intuition. A chunked/streaming rewrite proposed for a job whose
measured peak was 0.617 MB — 0.0075% of budget — adds complexity against a failure mode with no
evidence of existing. Measure with `tracemalloc` before restructuring for memory.

---

# 36. Tooling Evaluation

Candidate tools are scored on:

> capability × reliability × license × coverage × maintainability × integration cost × compute cost

Components under consideration: DuckDB; Polars; scikit-learn; XGBoost; LightGBM; CatBoost; PyTorch;
Optuna; MLflow; Evidently; DVC; Great Expectations; Apache Arrow.

No tool enters production solely because it is free or fashionable.

## 36.1 Environment reality check (new in v6)

**A tool named in an experiment plan must be verified importable in the target interpreter before
the plan is approved.** Listing a package in `requirements*.txt` is not verification — version
markers may exclude the running interpreter entirely.

Measured instance: CatBoost appears in all three requirements files and in this section's list, and
is pinned `python_version < "3.14"` in every one. On the 3.14.6 development interpreter it has no
wheel and cannot be installed. An experiment arm planned around it could be written, but never
executed or verified.

The check is one line:

```bash
python -c "import catboost, xgboost, lightgbm"   # per tool, in the target env
```

Where a planned tool is unavailable, the experiment records it as an explicit `UNAVAILABLE` arm with
the reason — **never silently omitted**, because a missing arm and a failed arm look identical in a
results table. Where the tool is also not part of the served stack, record that too: its absence
then leaves no production path untested, which materially changes how much the gap matters.

---

# 37. Agentic Research Architecture

Agents may accelerate: **Research Agent** (literature, repositories, source documentation);
**Data Agent** (source schemas and coverage); **Feature Scientist** (hypotheses from known gaps);
**Experiment Agent** (registered experiment specifications); **Statistical Reviewer** (pre-declared
significance and robustness tests); **Production Reviewer** (lineage, dependencies, legal status,
failure behaviour, parity); **Certification Agent** (evidence packets, cannot certify autonomously).

Agents may never invent evidence; rewrite test outcomes; modify promotion thresholds after seeing
results; promote a model; activate staking; alter certification policy; or suppress negative
results.

Human authorization remains mandatory. See DID §51.1 for which decisions require it.

---

# 38. Experiment Registry

```yaml
experiment_id:
hypothesis:
information_source:
source_version:
source_license_class:
source_coverage:
historical_window:
prediction_cutoff:
dataset_version:
feature_version:
representation_version:
model_version:
parameters:
seed:
training_window:
validation_windows:
final_holdout:
baseline_models:
market_baseline:
primary_metrics:
secondary_metrics:
bootstrap_method:
statistical_test:
multiple_testing_family:
effect_size:
confidence_interval:
sample_size:
result:
robustness:
failure_modes:
compute:
peak_rss:
runtime:
decision:
artifact_location:
provenance:
reviewer:
certification_status:
```

The registry must be machine-readable. Canonical file: `reports/research/experiment_registry.yaml`,
validated by `backend/scripts/validate_experiment_registry.py --strict`.

**Honesty contract.** `UNDECLARED` means the study did not record this — not "zero", not "none".
`null` means genuinely not applicable. Back-filling an `UNDECLARED` with a plausible reconstruction
is fabrication and is prohibited.

⚠️ **`UNDECLARED` is for facts that could not be recorded, not for facts nobody bothered to record.**
A new experiment declaring fields the run could have captured — `seed`, `runtime`, `peak_rss`,
`training_window` — is a process failure, and the validator warns on it. Record them at run time.

---

# 39. Experiment State Machine

```text
PROPOSED → SOURCE_QUALIFIED → DATA_VALIDATED → TEMPORAL_VALIDATED → INFORMATION_TEST →
MODEL_CANDIDATE → OUT_OF_SAMPLE_EVALUATION → STATISTICAL_REVIEW → ROBUSTNESS_REVIEW →
PRODUCTION_REVIEW → SHADOW → CERTIFICATION → PROMOTION
```

Plus terminal `CLOSED`.

Never jump `PROPOSED → PRODUCTION` or `FEATURE → MODEL` without intermediate evidence.

**State and decision are independent axes.** Advancing state records what was *done*; the decision
records what was *concluded*. An experiment that runs its information test advances to
`INFORMATION_TEST` regardless of outcome — including a null — while its decision may remain `HOLD`
pending authorization (DID §51.1).

---

# 40. Research Gates

**R0 — Ground truth.** Repository and deployment state verified (DID §3).
**R1 — Source qualification.** Coverage, legality, temporal reproducibility, provenance.
**R2 — Information qualification.** Non-trivial incremental information demonstrated.
**R3 — Forecast improvement.** Proper scores improve under temporal validation.
**R4 — Statistical robustness.** Confidence intervals, paired testing, multiple-testing controls.
**R5 — Production viability.** Runtime, freshness, failure behaviour, dependency budget.
**R6 — Shadow production.** Live data proves operational integrity.
**R7 — Certification.** APEX promotion policy passes **without modification**.

## R7.1 — Enforcement verification (new in v6, per Rule 15)

Gate R7 assumes the certification and merge machinery is live. That assumption must be checked, not
inherited:

- Is CI executing? (`scripts/verify_remote_ci.sh` — exit 2 means the billing lock still holds and
  nothing has been gated.)
- Are required status checks configured on the target branch?
  (`gh api repos/<owner>/<repo>/rules/branches/master`.)
- Did the local enforcer exit zero on the exact tree being certified?
  (`scripts/ci_local_enforcer.sh` — and read its exit code directly, per DID §55.)

A certification produced while the enforcement mechanism was dark records that fact explicitly.

---

# 41. Kill Criteria

**Data failure** — insufficient coverage; unacceptable missingness; unreliable historical
reconstruction; unstable source; unresolved identity mapping.
**Legal failure** — unclear or incompatible production rights; prohibited automation; unresolvable
licensing risk.
**Information failure** — no incremental value conditional on incumbent; none conditional on market;
demonstrably redundant.
**Statistical failure** — improvement indistinguishable from noise; disappears across folds; depends
on one narrow period; disappears after multiplicity correction.
**Operational failure** — excessive latency or memory; unreliable source; unacceptable maintenance
burden.
**Complexity failure** — a more complex representation cannot beat the simpler one on the same
information.

---

# 42. Reopening a Rejected Idea

A closed branch reopens only if at least one is materially different: new information; new
historical coverage; new prediction cutoff; new causal hypothesis; a representation encoding
genuinely different information; a corrected methodological defect; previously unavailable
statistical power.

> "Try it again with XGBoost instead of LightGBM" is not sufficient.

---

# 43. Priority Experiment Backlog

**E0 — Calibration repair.** Hypothesis: probabilities are materially miscalibrated. No new source.
Temperature/vector/isotonic candidates against current serving probabilities. Success: meaningful
reliability/ECE reduction without discrimination loss. *Immediate.*

**E1 — Player availability delta.** Expected available team strength contains incremental
information. Representation: availability delta, replacement cost, positional disruption. Baseline:
incumbent + market. *Highest-priority new-information candidate.*

**E2 — Expected XI / continuity.** Lineup continuity and expected-XI state contribute incremental
signal.

**E3 — Event-derived team state.** Historical event-derived performance contains information not in
current aggregates. Prerequisite: coverage gate — subject to DID §15.7.

**E4 — Tactical interaction.** Opponent-specific interaction beyond independent team strength.
Interaction terms first; graph model only if warranted.

**E5 — Market information arrival.** Timing and structure of market movement reveal information
arrival not captured by opening prices. Must distinguish market intelligence from independent
football intelligence.

**E6 — Dynamic team state.** Latent team strength changes faster than current Elo/rating
representation. Lightweight state-space candidate.

**E7 — Distributional goal model.** Modelling score distributions directly improves 1X2 quality.
Poisson/Dixon-Coles baseline first.

---

# 44. What Not to Do

Prohibited unless reopened under a materially different hypothesis (DID §42):

Broad feature-density expansion · blind addition of dozens of statistics · repeated HPO campaigns ·
repeated ensemble expansion · league-specific carving without causal justification · generic
weather-feature dumping · indiscriminate bookmaker-source aggregation · GNN/Transformer
implementation before information qualification · automatic StatsBomb integration because the
dataset is rich · scraping every available website · replacing missing values with neutral
measurements · marketing claims based on model-market disagreement · treating calibration as
evidence of market superiority.

---

# 45. Immediate Production Hygiene

Prerequisites for trustworthy experimentation:

**A1** Resolve phantom certification thresholds. **A2** Correct CLV terminology. **A3** Move
research-only dependencies out of runtime. **A4** Correct latency definitions. **A5** Resolve
authorized feature-availability instrumentation. **A6** Resolve duplicated/malformed historical
corpus issues before using the corpus as a calibration or modelling source.

---

# 46. Phase Plan

**Phase 0 — Ground truth.** Repository, source, feature, model, market, certification and debt
inventories.
**Phase 1 — Calibration.** Baseline series; recalibration candidates; statistical comparison;
candidate artifact; certification packet.
**Phase 2 — Missing-information discovery.** Opportunity matrix; source qualification table;
legal/access assessment; coverage map; historical reconstructability map.
**Phase 3 — Data qualification.** Source adapters; raw snapshots; entity-resolution audit; temporal
audit; missingness audit; provenance records. *No production integration yet.*
**Phase 4 — Information-value testing.** `data → simple representation → incremental test →
kill/promote`. **The principal research gate.**
**Phase 5 — Representation research.** Dynamic state; interactions; embeddings; graphs; spatial
models.
**Phase 6 — Controlled model experiments.** Frozen experiment configurations.
**Phase 7 — Statistical validation.** Temporal folds; block bootstrap; paired tests;
multiple-testing correction; holdout confirmation.
**Phase 8 — Shadow production.** Data freshness; feature availability; serving parity; latency;
failures; operational completeness.
**Phase 9 — Certification.** All existing gates remain authoritative. Research may not modify policy
to pass a candidate.
**Phase 10 — Production integration.** Schema migration; feature activation; model promotion;
telemetry activation; post-deploy verification.

---

# 47. Top Ten Immediate Actions

1. **Freeze the current evidence baseline** under a versioned snapshot.
2. **Complete calibration repair** using the existing temporal holdout before acquiring new data.
3. **Build the canonical Information Opportunity Matrix** — what SabiScore knows, what the market
   knows, what exists outside both.
4. **Run a formal player-availability source study.** Do not integrate yet: legality, historical
   depth, expected-lineup availability, timestamp fidelity, coverage.
5. **Build a prediction-time source contract** — `observed_at`, `effective_at`, `available_at`,
   `cutoff`, `source_version`.
6. **Re-run event-data coverage audits**, especially the StatsBomb/Understat crosswalk. Do not
   authorize VAEP/xT merely because the libraries exist.
7. **Maintain the incremental-information harness** comparing incumbent / incumbent + source /
   market / market + source / raw market, on identical temporal folds. One implementation
   (DID §56).
8. **Establish structural evaluation baselines** — Poisson, Dixon-Coles, dynamic rating.
   Evaluation-only.
9. **Maintain the machine-readable experiment registry.** No research result exists unless it is
   reproducible from the registry — and the registry must cite a directive section that exists
   (DID §57).
10. **Run bounded experiments before architecture.** Calibration, player availability, and
    event-derived team state where coverage qualifies. No GNN/Transformer research before those
    results exist.

---

# 48. Definition of Success

The programme does **not** succeed because more data was acquired, more features created, a neural
network trained, an RPS point estimate improved, a paper reproduced, the market beaten on one fold,
an accuracy number increased, or a dashboard made more sophisticated.

It succeeds when it produces at least one complete chain:

```text
NEW INFORMATION → RELIABLY ACQUIRED → LEGALLY USABLE → HISTORICALLY RECONSTRUCTABLE →
TEMPORALLY VALID → INDEPENDENT OF CURRENT FEATURES → INCREMENTAL INFORMATION DEMONSTRATED →
OUT-OF-SAMPLE FORECAST IMPROVEMENT → STATISTICALLY ROBUST → PRACTICALLY MATERIAL →
PRODUCTIONALLY RELIABLE → CERTIFIED
```

Anything short of that remains research.

---

# 49. Definition of Failure

The programme must be willing to conclude:

> **No sufficiently independent, economically practical, legally usable source was demonstrated to
> improve SabiScore out-of-sample under the specified validation regime.**

That is a successful scientific conclusion if the evidence supports it. The system must never
manufacture a roadmap merely because a roadmap is expected to contain positive findings.

---

# 50. Standing Product Position

SabiScore must represent its forecasting capability accurately.

**May claim:** probabilistic forecasting; calibration measurement; uncertainty research; transparent
evidence; model diagnostics; market comparison.

**Must not claim:** superior accuracy; market-beating performance; profitable betting performance;
closing-line value; predictive superiority — unless the corresponding evidence passes the platform's
actual certification requirements.

Internal generation identifiers (`v5_phase7`, schema names, meta-model class names, certification
enum values) are **not** consumer-facing vocabulary; they belong in authenticated diagnostics only.

---

# 51. Final Decision Framework

Every research branch ends with one of four decisions.

**PROMOTE** — information value, forecast value, statistical robustness, operational viability and
certification readiness all demonstrated.
**RESEARCH** — promising, but evidence or production readiness incomplete.
**HOLD** — plausible, but insufficiently powered or historically reconstructable.
**REJECT** — evidence indicates the source/representation does not justify further investment.

The default after an inconclusive small sample is **HOLD** — not PROMOTE, not forced REJECT.

## 51.1 Decision authority (new in v6)

v5 listed four decisions without saying who may take them. That gap produced a real hesitation: an
experiment whose information test had returned a clean null had no recorded authority to close
itself.

| Action | Authority |
|---|---|
| Advance `state` along DID §39 to reflect work actually done | **Executing agent or engineer.** Recording what happened is not a decision. |
| Record or retain `HOLD` / `RESEARCH` | **Executing agent or engineer.** Both are non-terminal and reversible. |
| `PROMOTE` | **Operator only.** Irreversible in effect; touches serving, certification and staking. |
| `REJECT` | **Operator only.** Terminal under DID §42 — reopening requires a materially different hypothesis. |

Where the evidence indicates a terminal decision the executing agent may not take, the agent must:

1. advance the state to reflect the work done;
2. retain the non-terminal decision;
3. **record explicitly, in `decision_detail`, which terminal decision the evidence indicates and
   that it was not authorized.**

Silence is not neutrality — an unmarked `HOLD` over evidence that indicates `REJECT` misrepresents
the research prior to the next reader, which is precisely what Rule 10 exists to prevent.

---

# 52. Core Research Question

> **What new, trustworthy, legally usable, temporally available information can SabiScore acquire
> and transform into genuinely independent predictive signal, and what is the smallest rigorous
> experimental sequence capable of proving whether that information improves out-of-sample
> forecasting?**

The answer is expressed as:

```text
Source → Coverage → Legal Status → Temporal Fidelity → Missingness → Entity Resolution →
Independent Information → Representation → Baseline → Out-of-Sample Result →
Confidence Interval → Statistical Decision → Production Decision
```

No step may be inferred from another.

---

# 53. Executive Principle

> **Do not build the feature until the information earns the feature.**
> **Do not build the model until the information earns the model.**
> **Do not build the infrastructure until the model earns production.**
> **Do not claim the result until the evidence earns the claim.**

SabiScore does not need more data for its own sake. It needs **better information, better temporal
truth, better calibration, better representations of genuinely missing state, and better evidence
about whether any of those actually improve forecasting.**

---

# 54. Recorded Empirical Findings

**New in v6.** Results that should not be re-derived. Each is measured in this repository, with its
artifact cited. This section exists because Rule 10 is only real if negative evidence is *findable*.

## 54.1 Portfolio F — T−2h weather forecast (F3): no measurable effect

Expanding-window walk-forward, three origins (test 2023/24, 2024/25, 2025/26), two learners, 4,921
fixtures joined to a coherent de-vigged Bet365 price. Baseline: market. Candidate: market +
temperature + precipitation at T−2h.

| arm | fold | RPS base | RPS cand | 95% CI (paired) |
|---|---|---|---|---|
| logistic | 2023 | 0.18706 | 0.18695 | [−0.0006, +0.0004] |
| logistic | 2024 | 0.19741 | 0.19748 | [−0.0004, +0.0005] |
| logistic | 2025 | 0.20061 | 0.20023 | [−0.0009, +0.0002] |
| xgboost | 2023 | 0.20197 | 0.20294 | [−0.0023, +0.0042] |
| xgboost | 2024 | 0.20482 | 0.20458 | [−0.0025, +0.0022] |
| xgboost | 2025 | 0.20336 | 0.20353 | [−0.0022, +0.0026] |

All six CIs straddle zero. Log loss moves < 0.008 and ECE < 0.002 in both directions. The null is
stable across 2 learners, 3 origins, 6 leagues and 3 metric families.

Artifact: `reports/research/portfolio-f3-weather-incremental-value.json`.
Script: `backend/scripts/study_f3_weather_incremental_value.py`.
Do not re-run without a materially different hypothesis (DID §42).

## 54.2 The raw market beats fitted models on the market's own probabilities

In the same test the **unmodeled de-vigged market outscored both fitted arms on 2 of 3 folds**
(test 2024: raw 0.19690 · logistic 0.19741 · XGBoost 0.20482). A model trained on market
probabilities does not reliably improve on them at this feature count. This is the reason DID §16
Stage 3 makes the raw reference mandatory.

## 54.3 Gate G1 is unreachable for any forecast-archive source

4,806 of 12,765 corpus fixtures (37.65%) predate the 2022-03-01 forecast archive. Perfect geocoding
caps G1 at **62.35%** against an 85% bar. Geocoding work is worth +19.54pp and cannot close the gap.
(`docs/DEBT.md` item 103.)

## 54.4 Level 2 underperforms Level 1 at low feature count

See DID §26.1.

---

# 55. Operational Verification Discipline

**New in v6.** Research conclusions are only as good as the commands that produced them.

**Never judge a gate through a pipe.** `cmd | tail -30` reports *tail's* exit status, not the gate's.
This has produced false "pass" readings on the Docker build, `make verify`, an Alembic upgrade, and
a CI check in this repository. Redirect to a file and read `$?`, or capture `${PIPESTATUS[0]}`.

**Watch every new guard fail before trusting it.** A test that has only ever passed proves nothing
about what it catches. Revert the fix, confirm the test reddens *and names the right thing*, restore.

**Verify the cause you report, not the one that sounds right.** A plausible attribution is not a
measurement: when 481 of 5,402 rows failed to join, "missing market price" was the natural story —
and was confirmed only by checking every dropped key against the raw corpus (481 present, 0 key
mismatches). Had it been a date-parsing bug the story would have read identically.

**Prefer a counter to an inference.** Where `/metrics` or an equivalent exists, a moving counter
distinguishes "data absent" from "data silently discarded"; nothing about the output does.

---

# 56. Duplication Policy for Research Code

**New in v6.** §31's "no second team-name normalizer" was scoped to production, and research code
duplicated freely underneath it. This repository has paid for that repeatedly — three team-name
normalizers, four goals/gd remaps, two `_team_key` implementations, and **six copies of the
dual-vocabulary corpus CSV reader**.

The corpus ships in two column vocabularies (`date`/`home_team`/`bet365_home` through 2024/25;
`Date`/`HomeTeam`/`B365H` from 2025/26) and **a reader that speaks only one sees an empty season
rather than an error** — the same silent-absence shape as the canonical/display league-id trap.

Rules:

1. A shared implementation exists for: corpus loading, de-vigging, temporal splitting, RPS and
   bootstrap scoring, and feature-group derivation. Use it.
   (`backend/scripts/_incremental_value_harness.py`, `backend/src/models/evaluation/metrics.py`,
   `backend/src/models/feature_registry.py`.)
2. Adding a consumer is free. Adding a **copy** requires a recorded reason.
3. When a shared helper is missing, add it to the shared module and use it there — do not fork a
   sibling script.
4. Migrating existing duplicates is not required by this rule and must not be bundled into an
   unrelated change: silently rewriting a working research script risks changing an already-published
   result. Record the duplicates; migrate deliberately.

---

# 57. Maintenance of This Document

**New in v6.**

1. **This file is the canonical location.** `docs/DATA_INTELLIGENCE_DIRECTIVE.md`. A revision that
   exists only in a chat transcript governs nothing — the failure v6 was created to correct.
2. **Numbering is stable.** §51 is cited 45 times across scripts, registry entries and
   `docs/DEBT.md`; §20, §18, §42, §23 and §21 are each cited 20+ times. Never renumber an existing
   section. Append (§58+) or add sub-sections (§X.1). Correct wrong prose in place.
3. **Citations name their document** (DID §0.1). `DID §23` and `APEX §23` are different rules.
4. **Cross-references must resolve.** Any file citing this directive — starting with
   `reports/research/experiment_registry.yaml`'s `schema_reference` — must name a section that
   exists here. Check before changing a heading.
5. **Every new rule cites its evidence.** Rules 11–15 and §54–§56 each name the measured failure
   that produced them. A rule with no incident behind it is a preference, and preferences belong in
   review comments, not in a directive.
6. **Supersession is explicit.** A new version restates what changed and why, as this one does.

---

**End of Directive v6.**
