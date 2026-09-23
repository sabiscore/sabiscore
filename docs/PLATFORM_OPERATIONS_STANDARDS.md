# Platform Operations Standards (OPS)

**Cite as `OPS §N`.** `APEX §N` and `DID §N` refer to
`PRODUCTION_EXECUTIVE_DIRECTIVE.md` and `DATA_INTELLIGENCE_DIRECTIVE.md`
respectively; a bare `§N` is ambiguous across all three and should not be used
(the failure class `docs/DEBT.md` item 105 records).

**Scope and authority.** This document institutionalises operational lessons
already paid for — every standard below traces to a specific incident in
`docs/DEBT.md`. It is *subordinate* to APEX and to the ADRs: where it appears
to conflict with `docs/adr/*`, APEX §23 (no post-hoc gate loosening), or a
certification policy threshold, those win and this document is wrong.
It authorises nothing. It cannot promote a generation, relax a gate, or widen
a Class C authorization.

**Status semantics.** Each standard carries a status as of **2026-09-21**:

| Status | Meaning |
|---|---|
| `ENFORCED` | An automated guard fails if the standard is violated. Named below. |
| `FIXED` | The defect is repaired, but no guard prevents recurrence. |
| `OPEN` | Not satisfied. The blocker is named. |

⚠️ **Status is a point-in-time claim, not a guarantee.** Re-derive it from the
named guard before relying on it. A guard that was never watched failing is
not a guard (`docs/DEBT.md` items 111, 117 — two cases where a check could not
fail and nobody noticed for weeks).

---

## OPS §1 — Guard execution and CI integrity

### §1.1 A check must be verified by execution against a known violation

`ENFORCED` — `backend/tests/unit/test_zero_fabrication_scan_enforces.py`

Reading a guard is not evidence it works. Every guard must be watched failing
on a seeded violation before it is trusted, and that demonstration should live
in a test rather than in a commit message.

Origin: `docs/DEBT.md` item 111 — all nine zero-fabrication checks were written
as `! grep …`, and POSIX exempts a `!`-inverted command from `set -e`, so a
positive match never aborted the step. Eight were inert from the day they were
written, with a real `datetime.utcnow` violation sitting in `master` while the
gate reported green. Item 117 is the same class in TypeScript: every assertion
in the evidence-copy contract test was structurally unfailable.

**Rule.** Shell guards record violations and exit non-zero on a non-zero tally.
They do not invert exit codes with `!`. A `grep` that *cannot run* (bad path,
unreadable file) counts as a violation, never as clean.

### §1.2 Resolve executables by running them, not by locating them

`ENFORCED` — `backend/tests/unit/test_zero_fabrication_scan_enforces.py::_bash_works`

`shutil.which("bash")` proves a file exists; it does not prove the file runs.
On Windows several `bash.exe` candidates coexist (Git Bash, a WSL launcher stub
in `System32`, a WindowsApps execution alias), and the one `subprocess.run`
resolves is not guaranteed to be the one `which` found.

Origin: `docs/DEBT.md` item 126 — on a machine with a malformed `.wslconfig`,
two tests failed with a WSL configuration error instead of skipping, which at a
glance is indistinguishable from a real zero-fabrication violation.

**Rule.** Availability preconditions are verified by executing the thing
(`bash -c "true"` and checking the exit code), the same way the DB-dependent
tests check connectivity rather than trusting that `DATABASE_URL` is set.

### §1.3 Pin linter rule selections explicitly

`ENFORCED` — `backend/tests/unit/test_ci_local_enforcer_ruff_steps.py`;
`scripts/ci_local_enforcer.sh:111,114`

Origin: `docs/DEBT.md` item 112 — the "MANDATORY, zero-exit" local enforcer
could not reach zero exit on a fresh install, because its ruff steps ran
unselected against an unpinned ruff version and surfaced mass false positives.

**Rule.** CI and the local enforcer both run `ruff check <path> --select E4,E7,E9,F`.
Never widen the selection to make a run pass; fix the finding or narrow the path.
Subprocess-based tests pin the environment variables they depend on rather than
inheriting an ambient shell.

---

## OPS §2 — ML artifact provenance and calibration

### §2.1 Artifacts carry every key they were serialized with

`ENFORCED` — `backend/tests/unit/test_calibrator_load_and_preflight.py`;
`backend/src/models/ensemble.py:475-476`

Origin: `docs/DEBT.md` item 122 — `SabiScoreEnsemble.load_model()` copied five
of the artifact's six keys and never read `calibrator`, so `prime_cache`'s
`getattr(model, "calibrator", None)` bridge silently yielded `None`. Only the
cold path ever saw the calibrator. This is item 87's two-loader defect (which
dropped `meta_model`) recurring one field over.

**Rule.** Any change to artifact *structure* is validated against **both**
loaders — the startup path (`SabiScoreEnsemble.load_model`) and the request
path (`PredictionEngine._wrap_artifact`). Knowing a second loader exists is not
the same as testing against it.

**Rule.** A serialized calibrator is admitted only if it demonstrably runs in
the current runtime (`_usable_calibrator`'s interior-simplex probe). A rejected
calibrator leaves the league serving uncalibrated probabilities, reported
honestly as `calibration_method="raw"` — never as calibrated.

### §2.2 A generation records its own origin

`ENFORCED` for new generations — `backend/src/models/training_manifest.py`
(`dataset_sha256` :152, `git.commit` :261, `reproducibility_sha256` :307)

`OPEN` for the served generation — `docs/DEBT.md` item 124

The training pipeline already emits a complete binding manifest. The served
`v5_phase7-20260808` generation predates that tooling, so its artifacts are
hash-pinned but their *origin* is not recorded, and no code can bind them
retroactively.

**Rule.** Any generation promoted from here carries a manifest binding it to an
exact source commit and dataset snapshot. **The existing gap closes only with a
retrain — it is not a code task, and must not be reported as one.**

### §2.3 A generation-name suffix names exactly one feature schema

`ENFORCED` for the served generation — `_verify_feature_contract()`,
`backend/src/models/active_generation.py:292`, invoked from
`load_active_generation()` (`:125`, runs in Render's build command)

`OPEN` for the candidate track — `docs/DEBT.md` item 86

Origin: PR #234 — `active_generation.json` declared `feature_schema_version:
"phase7_68"` for `v5_phase7-20260808` while all six artifacts were actually
trained on `apex_v1_68`. Both are distinct, non-alias 68-wide schemas
(`feature_registry.FEATURE_SCHEMA_VERSIONS`) that differ in the market-feature
block, slots 20–30. Verification checked feature-vector *width* only, so the
mismatch passed silently on every live prediction.

**Rule.** An `artifact_suffix` / generation-name string is bound to exactly one
entry in `FEATURE_SCHEMA_VERSIONS`. It is never reused to name two different
registered schemas.

`_verify_feature_contract` now rejects a manifest whose declared schema
disagrees with what any artifact's own hash-verified training metadata
records — added in PR #234, and it is what makes this instance `ENFORCED`
rather than merely documented.

**The identical collision exists a second time, unguarded.** `docs/DEBT.md`
item 86: `train_on_real_matches.py`'s `_SCHEMAS` table maps `apex_v1_68` to the
same `v5_phase7` suffix the served generation used for `phase7_68` before
PR #234. `_verify_feature_contract` only runs inside `load_active_generation()`,
so nothing checks this in `models/candidate/`. Item 86 itself already
confirmed why it is inert today: candidate output never writes to the served
`backend/models/` root, and `load_active_generation()`'s SHA-256 check would
fail closed on any accidental serving-path collision regardless.

A real fix here — either a candidate-track guard, or the suffix rename item 86
originally floated (`v5_phase7_incumbent_today`) — is deferred, not built.
Item 86 is closed as a documented, monitored risk on the strength of this
section, not on new code.

---

## OPS §3 — Operator overrides and consumer data contracts

### §3.1 Consumer copy is derived from live state, never asserted statically

`ENFORCED` — `apps/web/src/lib/evidence-copy-contract.test.ts`;
`apps/web/src/lib/model-identity-contract.test.ts`

Origin: `docs/DEBT.md` item 119 — consumer copy contradicted the active
operator override in two places, one asserting stakes were withheld while the
platform was staking, one asserting the model was certified while it was
serving under ADR-0011's uncertified override.

**Rule.** Any surface answering "is staking on?" or "is this certified?" reads
`staking_authorization()` / `active_generation_is_certified()` rather than
inferring from `certification_state` or `promotion_state` alone. A static
reassurance that can outlive its condition is a defect, not copy.

### §3.2 Response schemas declare every field the service layer sets

`ENFORCED` — `backend/tests/unit/test_risk_guard_wire_contract.py`;
`backend/src/api/endpoints/upcoming_matches.py:201,266`

Origin: `docs/DEBT.md` item 115 — `risk_guard` was set by the service and then
silently dropped at Pydantic response validation, so the ADR-0011 circuit
breaker's reason for suppressing a stake never reached any consumer.

**Rule.** A field constructed by a service and not declared on its response
model is discarded without warning. Schema and constructor are changed together,
and a test pins the field's survival across validation.

### §3.3 Source literals are scanned for mojibake, not just provider data

`ENFORCED` — `backend/tests/unit/test_no_mojibake_in_source_literals.py`

Origin: `docs/DEBT.md` item 116 — double-encoded UTF-8 reached a user-facing
betting narrative; every existing guard covered ingested provider data and none
covered strings written directly into source.

---

## OPS §4 — Market baselines and evaluation harnesses

### §4.1 The market baseline is Shin's method

`ENFORCED` — `backend/tests/unit/test_market_baseline_shin.py`;
`backend/src/models/evaluation/market_baseline.py`

Origin: `docs/DEBT.md` item 123. Proportional normalisation assumes the
bookmaker spreads margin evenly across outcomes; it does not — margin
concentrates on longshots, so proportional de-vigging overstates the market's
longshot probabilities and mis-specifies the bar a model is scored against.

**Scope.** This is the *certification baseline* only. Live serving paths
(`odds_service`, `market_intel`, `betting_intelligence`, `core_engine`) still
normalise proportionally, deliberately: changing them moves published EV/edge
numbers on production surfaces and puts both betting engines in scope under the
dual-engine rule. That is a separate authorization.

**Rule.** Calibration metrics (Brier, RPS, ECE, log loss) and market-comparison
metrics (model-vs-market RPS, CLV) are reported separately and never
substituted for one another. A pre-match model-vs-current-market comparison is
not CLV.

### §4.2 Evaluation harnesses are isolated from the serving dependency set

`FIXED` — `docs/CERTIFICATION_HARNESSES_V7_3.md` §1 (dedicated `.venv-cert`,
explicit MAPIE pin warning, `pip freeze` recorded per run)

Origin: `docs/DEBT.md` item 113 — `pip install mapie==1.5.0` per the then-current
runbook silently upgraded `scikit-learn` from the repo's pinned `1.3.2` to
`1.9.1`, and the resulting crash was an artifact of the environment rather than
of the codebase. MAPIE 1.5.0 requires `scikit-learn>=1.4`, which cannot coexist
with production's pin.

**Rule.** Certification runs happen in a dedicated environment whose complete
lockfile is recorded in the evidence artifact. A harness never mutates the
serving dependency set.

⚠️ **Open residual, not yet measured.** The certification venv runs Python 3.12
(→ scikit-learn 1.5.2, required for MAPIE compatibility) while production pins
3.11.9 (→ scikit-learn 1.3.2). `docs/DEBT.md` items 113/122 establish that the
committed calibrators behave *differently* across exactly these versions — they
load and apply under a newer scikit-learn and raise `AttributeError` under
1.3.2. A G16 run in the certification venv may therefore measure a calibrated
path production does not serve. This has not been tested and is recorded here
rather than assumed either way.

### §4.3 A harness's own numerical tolerances are part of its correctness

`PENDING` — guard is `backend/tests/unit/test_evaluate_g16_uncertainty_adapter.py`,
which lands with PR #226 and **does not exist on `master` as of this writing**.
Re-status this to `ENFORCED` when that merges; until then the standard is
stated but unguarded.

Origin: `docs/DEBT.md` item 127 — the G16 MAPIE adapter validated served
probabilities against `atol=1e-5` on a `float32` array, tighter than float32
precision supports, and rejected 94 of 301 genuinely valid rows as an "invalid
probability simplex." The model and calibrator were correct; the instrument was
not.

**Rule.** A tolerance is justified against the dtype and the operation count it
is measuring, and the justification is recorded where the tolerance lives.
Where an external library imposes its own stricter check (MAPIE validates
probability rows at `rtol=1e-05, atol=0`), fix the cause — normalise the data
being handed over — rather than loosening thresholds outward until something
passes.

---

## OPS §5 — Repository governance

### §5.1 `master` requires passing status checks

`ENFORCED` — GitHub ruleset `20939497`, `required_status_checks`, added
2026-09-21 (`docs/DEBT.md` item 104)

Human approval alone is not sufficient to admit unverified code. Ten checks are
required; `SonarCloud Code Analysis`, `Vercel Preview Comments` and
`Supabase Preview` are deliberately excluded — the last reports `SKIPPED`, and a
required check that never concludes blocks a PR indefinitely.

⚠️ Required contexts are matched by **string name**. Renaming a CI job silently
stops it being enforced. Re-derive the live set from
`gh api repos/<owner>/<repo>/rules/branches/master` rather than trusting any
written record, including this one.

### §5.2 Directives live in the repository

`ENFORCED` for the research directive — `docs/DATA_INTELLIGENCE_DIRECTIVE.md`
(`docs/DEBT.md` item 105); this document is the same rule applied to itself.

A directive that exists only in a chat transcript governs work that nobody can
audit later, and its citations resolve to nothing. Item 105's specific finding:
`reports/research/experiment_registry.yaml` cited "§38" of a document that had
no §38, and `validate_experiment_registry.py --strict` passed 15 experiments
against a section that did not exist, because a citation nothing resolves is
indistinguishable from a correct one.

**Rule.** Operational standards are committed before they are enforced, and
cited with an unambiguous prefix (`OPS §N`, `DID §N`, `APEX §N`).

### §5.3 Squash merges must not truncate the ledger

`FIXED` — `docs/DEBT.md` item 110 (entry restored 2026-09-20)

Origin: PR #220 merged 24 minutes after PR #219 from a branch cut *before* item
108 existed, so its copy of `DEBT.md` overwrote master's and deleted the only
ledger record that staking was live on an uncertified generation. Every code
file the two PRs shared was byte-identical, so nothing conflicted and nothing
warned.

⚠️ **No automated guard prevents recurrence.** The entry was restored by hand;
`DEBT.md` is referenced by `scripts/ci_local_enforcer.sh` and
`scripts/verify_remote_ci.sh`, but neither has been confirmed to detect a
truncating overwrite. Treat this as `FIXED`, not `ENFORCED`, and re-check the
ledger's item count after any merge of a long-lived branch.
