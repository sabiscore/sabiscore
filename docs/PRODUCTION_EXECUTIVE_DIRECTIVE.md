# SabiScore — Production Executive Directive (v2, 2026-09-03)

Supersedes the "Production Implementation Plan" and "Recommendations" drafts.
Every constant below was read out of the repository or a live endpoint on
2026-09-03. Where a number cannot be known without a production query, this
document says so rather than quoting a stale one.

**Read this section before any other.** The failure mode of the previous three
directives was not ambition; it was confidently wrong constants driving work
that could not succeed.

---

## 0. Verified ground truth — do not restate from memory

| Fact | Verified value | Source |
|---|---|---|
| Backend runtime | **Python 3.11.13** | `backend/runtime.txt` |
| Frontend | Next.js 15.5.6, **React 18.3.1** (pinned) | `apps/web/package.json` |
| Charting | Recharts 2.15.4 (already a dependency) | `apps/web/package.json` |
| Head migration | `0013_push_devices` | Render deploy log |
| Active generation | `v5_phase7-20260808` | `models/active_generation.json` |
| Certification state | `UNVERIFIED` / `ACTIVE_FAIL_CLOSED` | same |
| Served feature schema | `phase7_68` (68 columns) | same |
| Feature contract SHA-256 | `7681886093e33af49f1efcca2880e76d1fa66732fc26e2796f56a6c0ee6d6d13` | `models/feature_contract.json` |
| Certification policy | **v1.1.0**, SHA-256 `7e1e238456df14de182d957a0351485c63892c7980746d3a72488f248697d07a` | `certification_policy.policy_sha256()` |
| Live staking state | `stake_permitted: false`, `manifest_valid: true`, `models_loaded: true` | `GET /api/v1/models/status` |
| mypy ceiling | 784 (currently 768) | `scripts/check_mypy_ceiling.py` |
| Understat corpus | **10,633 distinct** played matches (12,459 rows before dedup) | `src/data/understat_corpus.py` |

### Constants the previous drafts got wrong — do not propagate

- ❌ "Python 3.12" → it is **3.11.13**.
- ❌ "React 19" → it is **18.3.1**, and `CLAUDE.md` forbids bumping it without a
  planned upgrade.
- ❌ "PostgreSQL 18" → unverified; do not assert a major version you have not read.
- ❌ "feature contract SHA `b63a0517…`" → the real digest is `7681886093e33af4…`.
- ❌ "policy v1.0.0 / `41cb7703…`" → policy is **v1.1.0** / `7e1e2384…`.
- ❌ **"11,694 reviewed `match_stats` rows" / "23,388 rows expected"** → that count
  came from the *pre-deduplication* manifest over 12,459 rows. The corpus is now
  10,633 distinct matches, so the READY count is necessarily lower and **the
  manifest SHA-256 has changed**. The number is unknown until a fresh review run
  against production. Do not hardcode it, and do not assert a row-count
  postcondition derived from it.
- ❌ Invented promotion gates ("draw_recall_minimum", "≥15/68 responsiveness",
  "6/6 leagues"). The real seven are listed in §3.
- ❌ `from src.db.models import MatchStats` → it lives in `src.core.database`.
- ❌ `MatchStats(updated_at=…)` → **there is no `updated_at` column** on that table.

---

## 1. Closed questions — do not re-litigate without new evidence

Each of these was measured, not argued. Re-opening one requires new measurement,
not a new plan.

| Question | Verdict | Evidence |
|---|---|---|
| Heterogeneous ensemble to clear Gate 50 | **REFUTED** — 3 seed blocks (1000, 7000, 4242). RF-only skill −0.0161/−0.0370/−0.0244 at N=3/5/10 | DEBT 59; `spike_independent_ensemble_uncertainty.py` |
| Adding xG causal drivers (`apex_v2_71`) | **REJECTED** — mean RPS −0.00159 on identical rows, market_baseline 0/5 | DEBT 58; `reports/evaluation/apex-v2-71-candidate-evaluation.*` |
| Populating the 4 `ALWAYS_DATA_GAP` slots | **INERT** — zero-variance columns; no tree splits on them | DEBT 56 Finding 1 |
| Re-specifying `error_association` per aleatoric stratum | **FORBIDDEN** — post-hoc threshold change (APEX §23); also would not cleanly pass (2 of 3 strata still wrong-signed) | DEBT 50 Hypothesis 1 |
| BullMQ / Celery / Node worker layer | **REJECTED** — competing scheduler; use FastAPI lifespan loops | DEBT 54 |
| BNN / PyTorch staking path | **CLOSED** — ADR 0009 locks `UNCERTAINTY_METHOD = "ensemble_dispersion"` | DEBT 42/43 |

**Corollary that reframes the whole mission:** `uncertainty_policy.py` states the
two gates are independent — *"clearing `MODEL_GENERATION_UNCERTIFIED` does not
clear `MODEL_UNCERTAINTY_UNAVAILABLE`"* — and the converse holds. **Clearing
Gate 50 would not enable staking.** Staking additionally requires
`certification_state: CERTIFIED`, which requires `market_baseline`, which
currently fails **0/5 for every model measured** — incumbent and both candidates.

> **The single blocker is: no SabiScore model beats the de-vigged market-implied
> RPS in any league.** Every plan that does not attack that is not a plan to
> ship staking.

---

## 2. The highest-value unexplored work — 16 defaulted training slots

This is the finding the previous directives missed, and it is the best available
attack on `market_baseline`.

`serving_feature_availability` requires `training_defaulted_slots == 0`. It is
currently **16** — and these are *not* the four policy-gapped slots (those are
correctly excluded since DEBT 49). Measured directly from
`models/candidate/feature_availability_matrix.json`:

```
h2h block (6)      h2h_home_wins, h2h_away_wins, h2h_draws, h2h_matches,
                   h2h_dominance, h2h_market_agreement
venue block (4)    home_venue_win_rate, home_venue_draw_rate,
                   home_venue_loss_rate, home_advantage_strength
interactions (3)   form_market_agreement_home, form_market_disagreement,
                   venue_market_combo
scalar (1)         total_goals_expected
event-data (2)     home_pressing_intensity, progressive_carry_diff
```

**Fourteen of the sixteen are derivable from `data/cache/fd_*.csv`, which is
already committed.** Head-to-head records and home-venue records are ordinary
walk-forward accumulations over the same corpus `TeamHistory` already walks.

The asymmetry is the point: `data/transformers.py:407–474` **computes h2h and
venue features at serving time today.** Training leaves them constant. A column
that is constant in training is never split on, so the model provably cannot use
14 features that serving is already paying to compute. This is not a marginal
feature idea — it is signal the model has never once seen, on data already in
the repository.

`home_pressing_intensity` and `progressive_carry_diff` are **not** derivable from
football-data or Understat (they need event-level data). They stay defaulted, and
`serving_feature_availability` cannot reach 0 until they are either sourced or
moved to the policy-gap list by an authorized decision. State that plainly; do
not quietly reclassify them.

---

## 3. The seven real promotion gates

Transcribed from `certification_policy.PROMOTION_GATES` (v1.1.0).
`PROMOTION_REQUIRES_ALL_GATES = True`.

| Gate | Threshold |
|---|---|
| `valid_probability_simplex` | no candidate holdout row rejected by `evaluate()` |
| `input_responsiveness` | `min_responsive_features_per_league: 1` |
| `coherent_price_perturbation` | `directionally_coherent: True` |
| `serving_feature_availability` | `training_defaulted_slots == 0`, `serving_schema_misaligned_slots == 0`, `min_training_rows ≥ 1` |
| `primary_metric_improvement` | mean RPS improvement **strictly > 0** vs incumbent |
| `no_league_regression` | candidate wins on RPS in **every** league compared |
| `market_baseline` | candidate RPS < market-implied RPS in **every** league |

Cite the policy hash, never this table, in a certification manifest.

---

## 4. Non-negotiable constraints

**Architecture.** FastAPI is the sole backend authority. PostgreSQL is durable
truth; Alembic is the only schema authority. Redis is hot state. `apps/web` is
presentation + BFF and computes no EV, stake, edge, or de-vigging. No second job
queue. No second team-name normalizer beside `team_identity._identity_key` — the
football-data ↔ Understat crosswalk in `features/xg_replay.py` is a *data table*
consulted after that normalizer, and it must stay out of `_AUDITED_ALIASES`.

**Zero fabrication.** Unobserved is `None`, never `0.0`, never a neutral prior
presented as a measurement. `rolling_xg_mean` returning `None` below its
minimum-periods floor is the reference implementation of this rule. A feature
that training defaults must not be described as observed.

**Train/serve parity is bidirectional.** Serving must not consume a feature
training never varied (§2), and training must not consume a feature serving
cannot reproduce (the `apex_v2_71` row-drop rule). Both directions are parity
violations; only the second is currently tested.

**Fail-closed.** Missing critical evidence degrades to `PARTIAL` /
`RESEARCH_ONLY` with `stake_permitted=false`. A gate that blocks promotion is
never relaxed to unblock it. "Uncertainty remains unavailable and fail-closed" is
an acceptable terminal outcome; a manufactured PASS is not.

**Memory.** 8 GB dev machines. Batch DB work (the backfill executor chunks at
1,000). `maxTsServerMemory ≤ 3072`. The ML research venv is `.venv-ml`; do not
pip-install training deps on Python 3.14.

---

## 5. Execution order

Sequenced by evidence value, not by visibility. Do not start a later phase to
avoid an earlier one.

### Phase 1 — Make `match_stats` real (unblocks serving-side measurement)

1. Re-run the review; the dedup moved the digest:
   `python scripts/review_understat_match_stats_backfill.py --full`
2. Record the fresh `manifest_sha256`, `summary.ready_rows`, and the blocked
   breakdown. **Report the real number; do not reuse 11,694.**
3. Apply under authorization:
   ```
   python scripts/review_understat_match_stats_backfill.py --apply \
     --manifest-sha256 <fresh> --authorization-id <change-id> \
     --confirm APPLY_UNDERSTAT_MATCH_STATS
   ```
4. **Acceptance:** `inserted_rows == 2 × ready_rows`; re-running reports
   `inserted_rows: 0` and `already_present_rows == 2 × ready_rows`; the printed
   `reversals_total` is retained with the authorization record.
5. Then measure what serving can now answer: sample upcoming fixtures and count
   how many get a non-`None` `project_xg_rolling_features`. That number decides
   whether xG has a serving future at all, and it is the measurement DEBT 58
   named as the one that would separate its two candidate explanations.

### Phase 2 — Populate the 14 derivable defaulted slots (attacks `market_baseline`)

1. Extend `train_on_real_matches.build_dataset` with walk-forward h2h and
   home-venue accumulators, updated strictly **after** each row is emitted —
   the existing `TeamHistory` / `elo_replay` pattern, not a new one.
2. Compute the three interaction features from the now-real venue/form and the
   existing Apex market block.
3. **Parity is the acceptance criterion, not the feature count.** Each new
   training value must equal what `data/transformers.py` computes at serving for
   the same fixture, asserted to float tolerance in a parity test — the pattern
   `tests/unit/test_xg_rolling_parity.py` already establishes.
4. **Acceptance:** `training_defaulted_slots` drops 16 → 2 (the two event-data
   features), measured by regenerating the availability matrix. Report the RPS
   delta per league against the incumbent whatever it is.
5. Train as a **new registered schema key**, never by widening a served list.
   `apex_v2_71` is the worked example of how to do this without breaking
   artifacts; its rejection does not invalidate its mechanics.

### Phase 3 — Candidate evaluation, honestly

- `python scripts/train_on_real_matches.py --schema <new-key>`
- `python scripts/generate_feature_availability_matrix.py --schema <new-key> …`
- `python scripts/compare_candidate_vs_incumbent.py --candidate-schema <new-key>`
- Score both heads on the **identical** holdout rows before claiming any delta —
  the `apex_v2_71` headline mixed "added features" with "dropped rows" until it
  was separated.
- Metric contract: multiclass Brier is **mean-over-samples of sum-over-classes**
  (`reports/evaluation/metric-contract.json`).
- **If `market_baseline` still fails, say so and stop.** Do not promote, do not
  adjust a threshold, do not report a partial pass as progress.

### Phase 4 — Gate 50: measure and record only

Permitted: measure aleatoric stratification, persist BALD dispersion as shadow
telemetry, extend the ADR 0009 addendum with new evidence.
**Forbidden:** re-specifying `error_association`, changing the member basis,
changing `UNCERTAINTY_METHOD`, or shipping any of it into serving. Those need an
authorized decision on recorded evidence, not an agent edit.

### Phase 5 — Consumer UX, within honesty constraints

Only after Phases 1–3 have produced something true to display.

- **Evidence Passport** on `/match/[id]`: per-family provenance, freshness, and
  resolution status. A gapped family renders as gapped — never omitted, never
  filled.
- **Calibration / reliability view** on `/performance`: Murphy decomposition
  (reliability − resolution + uncertainty) with a sample-count floor. Below the
  floor, render the floor message, not a chart of noise.
  Backend: a cached endpoint (6 h TTL) computing from settled predictions only —
  Recharts 2.15.4 is already a dependency; add nothing.
- **APEX §11:** no raw identifiers on consumer surfaces. `UNVERIFIED` →
  "Research Mode"; `v5_phase7` → "Generation 5". Route through
  `lib/model-identity.ts`.
- **Prohibited copy:** `lock`, `banker`, `guaranteed`, `sure bet`, `free money`,
  `execute immediately`. No countdowns, streak badges, or bet-slip animation.
- **Accessibility:** WCAG 2.2 AA contrast, ≥24 px targets, visible focus,
  `prefers-reduced-motion` respected. Verify at 360 / 768 / 1280 px.

> ✅ **Phase 5 executed 2026-09-04 — with one correction to this section's
> own premise.** The calibration/reliability view item 2 asks for **already
> existed**: `GET /api/v1/model-performance/calibration` and
> `CalibrationCurveChart.tsx` shipped in PR #127 and have been mounted on
> `/performance` since. CLAUDE.md's WP-16 entry claiming a reliability-diagram
> UI was "deliberately deferred" predates that PR and was never updated — do
> not trust it. The real work was **deletion, not construction**: the shipped
> chart rendered five fabricated values, including a hardcoded ±3% error bar
> captioned as a Künsch block bootstrap and an ECE fallback of `0.018`
> against a live 0.1402. Full record: `docs/DEBT.md` item 60.
>
> Delivered: the five fabrications removed, a 6h cache and
> `meets_sample_floor`/`minimum_sample_size` added to the endpoint, the
> Evidence Passport built on `/match/[id]` (always visible —
> `EvidenceStatusCard` self-suppresses once staking is permitted, so it could
> not be extended into one), three raw backend enums removed from that page,
> and the a11y items above applied to the calibration control (`role="group"`
> + `aria-pressed`, `min-h-9`, visible focus ring, `prefers-reduced-motion`
> gating on chart animation). The prohibited-copy scan was already clean and
> remains so; APEX §11 model provenance was already routed through
> `lib/model-identity.ts` on both target routes and was not the leak — the
> leak was evidence-source enums.

---

## 6. Verification — commands that exist

```bash
# backend/
ruff check src/ scripts/
python scripts/check_mypy_ceiling.py            # ceiling 784; never raise it
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

Deployment parity: compare `GET /api/v1/models/status` `generation_hash` against
`models/active_generation.json` after any artifact change.

---

## 7. Definition of done

A phase is done when **all** hold:

1. Code merged with tests proportional to risk, CI green.
2. A measured result recorded under `backend/reports/` — including a negative
   one. `apex-v2-71-candidate-evaluation.md` is the reference format.
3. Documentation updated: `CHANGELOG.md`, `docs/DEBT.md`, and the model card if
   a candidate was evaluated.
4. No gate threshold changed. No `active_generation.json` promotion without all
   seven gates passing on their own evidence.
5. Production state re-verified and reported, including when it is unchanged.

**The platform is production-ready today in the only sense currently available:
it fails closed correctly and says so honestly.** It is not staking-ready, and
it will not be until a model beats the market. Any directive that promises
otherwise is describing a different system.
