# SabiScore — Production Finishing Directive

**Successor to** `docs/APEX_FINAL_PRODUCTION_ACTIVATION_DIRECTIVE.md`
**Authored** 2026-08-30 · **Verified against** live production, not inferred
**Working state at authoring** — `master` / Render / Vercel all agree at `4afd7b6`

| Signal | Value |
|---|---|
| Backend suite | 1764 passed / 14 skipped / 0 failed |
| Web suite | 248 passed |
| Critical gaps blocking every stake | **2** |
| Advisory gaps (live EPL fixture) | 9 |
| Providers | 5 configured · 5 enabled |
| Elo rows | 25,726 / 186 teams |

---

## §0 — How to read this

Every claim here is a **checkpoint, not a fact**. The numbers were true when written and
decay within hours. Re-probe before acting on any of them.

Three states appear throughout:

- **VERIFIED OPEN** — reproduced live, unfixed, with the probe that found it.
- **BLOCKED** — cannot be closed by code; needs a decision or elapsed match volume.
- **SHIPPED** — landed and gate-verified.

Two rules override everything below:

1. **Never lower a threshold after seeing it fail.** That a gate is the last thing between
   the platform and a green board makes changing it *more* dangerous, not less (APEX §23).
2. **A guard you have not watched fail is not a guard.** Revert the fix, confirm the test
   goes red and names the right file, restore, then trust it.

```bash
# Re-verify before starting. Three SHAs must be reconciled, not assumed equal.
git rev-parse --short=7 origin/master
curl -s .../health                | jq '{sha, status}'
curl -s <vercel-alias>/api/health | jq '{sha, backendStatus}'

# A backend SHA behind master is USUALLY CORRECT (render.yaml rootDir: backend).
git diff --name-only <render-sha>..origin/master -- backend/   # empty = legitimate skip

# Counters separate "data absent" from "data silently discarded" — the difference
# between a gap and a bug that looks exactly like one.
curl -s .../metrics | jq '.production.counters'
```

⚠️ **Local `curl` timing is not valid evidence from the authoring machine.** Five endpoints
with different workloads all returned ~12.1 s, and the breakdown showed `dns=0 tcp=0 tls=0`
with a 12 s TTFB — impossible for a real HTTPS round-trip. That is a local proxy artifact.
Measure server-side (Render metrics) or from a host with clean egress.

---

# Pillar 1 — Consumer language & UX clarity

> The platform currently explains itself in its own vocabulary. The fix is not softer
> wording — it is a boundary, enforced by a test, between what the system calls things and
> what a person is shown.

## 1.1 VERIFIED OPEN — Raw feature identifiers render as user-facing text

Five of the seven advisory codes on a live fixture have **no consumer copy**.
`describeEvidenceCode()` falls through to `titleCaseCode()`, so a reader is shown
**"Ppda Ratio"** and **"Set Piece Xg Diff"** — internal column names, title-cased.

```ts
// apps/web/src/lib/full-analysis-contract.ts:427
export function describeEvidenceCode(code: string): string {
  return EVIDENCE_CODE_COPY[code] ?? titleCaseCode(code);   // ← the leak
}
```

**Evidence** — live probe of `fd-560556` (EPL):

| Advisory code | Mapped? | User currently sees |
|---|---|---|
| `ppda_ratio` | ✗ | "Ppda Ratio" |
| `progressive_carry_diff` | ✗ | "Progressive Carry Diff" |
| `set_piece_xg_diff` | ✗ | "Set Piece Xg Diff" |
| `elo_league_adjusted` | ✗ | "Elo League Adjusted" |
| `causal_analysis` | ✗ | "Causal Analysis" |
| `total_goals_expected` | ✓ | mapped |
| `STALE_ENRICHMENT_EVIDENCE` | ✓ | mapped |

⚠️ **This is the same class as the model-provenance leak APEX §11 already forbids:** values
that are *correct but not for this audience*. No zero-fabrication scan can see it, because
nothing is false. Every prior truthfulness pass was structurally blind to it.

### Fix at the map

```ts
// apps/web/src/lib/full-analysis-contract.ts
const EVIDENCE_CODE_COPY: Record<string, string> = {
  // …existing entries…
  ppda_ratio:             "Pressing intensity data not published for this match",
  progressive_carry_diff: "Ball-carrying data not published for this match",
  set_piece_xg_diff:      "Set-piece chance quality not available yet",
  shot_quality_diff:      "Shot-quality breakdown not available yet",
  key_passes_under_pressure_diff: "Chance-creation-under-pressure data unavailable",
  elo_league_adjusted:    "Cross-league strength adjustment unavailable",
  causal_analysis:        "Driver analysis not available for this match",
};
```

Write from the reader's side — what is missing and whether it matters, never the column name.

### Then make it unskippable

The map alone will drift the moment a feature is added. The durable half is a repo-wide guard
in the idiom already used by `league-contract.test.ts` and `model-identity-contract.test.ts`:

```ts
// apps/web/src/lib/evidence-copy-contract.test.ts
it("every gap code the backend can emit has consumer copy", () => {
  // Source of truth is the backend's own registry, not a hand-kept list here —
  // a code added there must fail this test until someone writes its copy.
  const emitted  = readBackendGapCodes();           // parses feature_contract.json
  const unmapped = emitted.filter((c) => !(c in EVIDENCE_CODE_COPY));
  expect(unmapped, "unmapped gap codes reach users as raw identifiers").toEqual([]);
});
```

⚠️ Watch it fail first: delete one entry, confirm the test names that code, restore.

## 1.2 VERIFIED OPEN — Evidence counts are stated as arithmetic, not meaning

The decision card reads **"2 critical gaps · 10 advisory gaps · 0 conflicts"**. A reader
cannot act on that: it does not say which of the two blocks the bet, that the ten advisory
ones do not, or what would change the answer. Both live critical codes are also permanent
right now, so the same message shows on every fixture — which trains users to ignore it.

### Rewrite as cause → consequence → recourse

| Today | Replace with | Why |
|---|---|---|
| `2 critical gaps · 10 advisory · 0 conflicts` | "Not enough verified data to price this match. 10 optional inputs are also missing — those lower confidence but don't block." | Separates blocking from non-blocking; counts stop implying equal weight |
| `MODEL_GENERATION_UNCERTIFIED` | "This model version hasn't passed its accuracy review yet, so we're showing forecasts for research only." | Names state and consequence without the identifier |
| `MODEL_UNCERTAINTY_UNAVAILABLE` | "We can't measure how confident this forecast is, so we won't suggest a stake." | Explains the refusal as a safety choice, not a malfunction |
| `Partial Data` | "Incomplete" | "Partial Data" is a status enum; "Incomplete" is English |

**Do not re-do the tooltip layer.** Kelly, Edge, Epistemic, Aleatoric and CI already have
explainers wired through the shared `Tooltip`. What is missing is the tier *above* it: the
page should be readable **without opening a single tooltip**.

---

# Pillar 2 — Advanced models & feature engineering

> Precision is not currently limited by model sophistication. It is limited by one
> unattainable threshold and by features the corpus does not contain.

## 2.1 SHIPPED — Bayesian tuning, in the trainer that actually ships artifacts

Hyperparameters were hardcoded in `train_on_real_matches.py`. The pre-existing
`scripts/optuna_tune_ensemble.py` tunes a **dead v4 / 58-feature generation** that cannot
feed a `v5_phase7` / 68-feature serving path — tuning it produces something unpromotable.

Tuning now lives where promotable artifacts are built, opt-in via `--tune N`. An untuned run
stays **byte-identical** to every prior candidate.

```python
# backend/scripts/train_on_real_matches.py  --tune 30
study = optuna.create_study(
    direction="minimize",                                  # RPS: lower is better
    sampler=optuna.samplers.TPESampler(seed=42),           # Bayesian, not grid
    pruner=optuna.pruners.MedianPruner(n_warmup_steps=1),  # abandon bad configs at fold 1
)
```

Three deliberate choices:

- **RPS, not accuracy or log-loss.** It is the certified promotion metric
  (`compare_models` defaults to it, ascending) and is ordinal-aware — backing the wrong side
  of a draw is punished correctly. Tuning on anything else optimizes a target certification
  does not read.
- **`TimeSeriesSplit` over the TRAINING slice only.** Calibration and holdout stay unseen, so
  holdout RPS remains an out-of-sample number rather than a search artifact.
- **`n_jobs=1` inside trials.** Parallelism multiplies across trees × folds × trials, which
  is what exhausts memory on a laptop. The pruner also abandons a bad configuration after its
  first fold instead of paying for all of them.

### CatBoost parameter mapping

⚠️ **CatBoost cannot be tuned or verified locally** — it is pinned `python_version < "3.14"`
and this interpreter is 3.14.6. Its axes are searched through their equivalents:

| CatBoost | Searched as | Range |
|---|---|---|
| `depth` | `max_depth` (XGB, LGBM) | 3 – 8 |
| `l2_leaf_reg` | `reg_lambda` | 0.5 – 20.0 (log) |
| `iterations` | `n_estimators` | 100 – 500 |
| `learning_rate` | `learning_rate` | 0.01 – 0.2 (log) |

## 2.2 Momentum and rolling averages already exist — do not rebuild

The registry already derives `elo_momentum_cross`, `home_elo_trend_5`, and last-5/10/20
rolling form through **shared helpers that both serving pipelines and the training builder
call**. A parity harness pins 44 of 68 features across train and serve.

⚠️ Adding a second momentum implementation would reintroduce exactly the drift that harness
exists to prevent. The genuine feature gaps are elsewhere:

- **Weather** — acquisition shipped and live-verified; integration gated (below).
- **Tactical / StatsBomb** — 4 of 68 slots, permanently gapped by design until a corpus
  regeneration and point-in-time parity review (`docs/DEBT.md` item 13).

## 2.3 SHIPPED — Weather acquisition, chosen for train/serve symmetry

A weather feature is only usable if it resolves for **every historical match** *and* for a
**fixture that hasn't kicked off**. A source with one half teaches the model to lean on a
signal serving cannot supply — the train/serve skew that forced the vΩ.46 retrain.

| Provider | Historical | Forecast | Key | Verdict |
|---|---|---|---|---|
| **Open-Meteo** | archive to 1940 | 16 days | none | **chosen** — identical `hourly` schema on both, so one parser serves both and they cannot drift |
| Visual Crossing | yes | yes | required | 1,000 records/day free — will not cover a 12,765-match backfill |
| NOAA / NWS | yes | yes | none | US-only; every supported competition is European |

⚠️ **There were zero coordinates anywhere in the repo.** `Match.venue` is NULL in production
(`fixture_sync_service` never sets it) and `Team.stadium` is nullable free text. Hand-entering
~130 stadium positions was rejected as invented reference data — wrong coordinates produce
*confidently wrong* weather, worse than none. Open-Meteo's keyless geocoding resolves them
instead, at a resolution coarser than the weather grid cell anyway.

**Live verification** — `probe: VERIFIED` (first keyless provider here to reach it),
Liverpool GB → 53.41/−2.98, archive 20.5 °C for a past kickoff, forecast path distinct,
beyond the 16-day horizon returns `None` rather than extrapolating.

### Integration is deliberately NOT done

Weather in the model means a new `feature_schema_version`, a full retrain, and a promotion
decision. Three things must hold first:

1. **A team → location mapping with a review step.** Geocoding is derived, not invented, but
   it is still a guess for clubs whose name is not their city (Bayer Leverkusen, Hoffenheim,
   Atalanta). Needs the same `VERIFIED`/`REQUIRES_REVIEW` treatment as team identity.
2. **A persisted backfill** over 12,765 matches, rate-limited, so training is reproducible
   rather than re-fetched.
3. **A parity check** that the archive value used in training and the forecast value used at
   serving are the same variable at the same hour. `MatchWeather.source` records which
   endpoint answered precisely so the two can never be silently interchanged.

Until then a missing reading is **advisory**. Weather can never be critical evidence — the
trust tier is `OPEN_DATA` and the provider is not a football source.

---

# Pillar 3 — UI polish & visual cohesion

> The design system is sound. What breaks cohesion is a small number of surfaces that drifted
> from conventions the codebase already settled.

## 3.1 PARTLY SHIPPED — Hydration mismatch in `PredictionAgePill`

Two distinct hydration hazards sat in the **render body** of this `"use client"` component.
One is fixed; one is not.

**SHIPPED — the `toLocaleString()` sweep.** Commit `01025ca` moved all five sites onto the
shared `formatLagosTimestamp()`, and pinned it with a repo-wide guard
(`apps/web/src/lib/timestamp-contract.test.ts`) that fails on any user-facing date rendered
through a bare `toLocaleString()`. Re-verified against current source: **zero remaining**.

> ⚠️ An earlier draft of this directive listed all five sites as open. That was **stale** —
> the sweep had already landed. Re-grep before acting on any file list in a document.

**STILL OPEN — `Date.now()` in the render body:**

```ts
// apps/web/src/components/full-analysis-dashboard.tsx:481-484
function PredictionAgePill({ generatedAt }: { generatedAt: string }) {
  const generatedMs = new Date(generatedAt).getTime();
  const ageSecs = Number.isFinite(generatedMs)
    ? Math.max(0, Math.round((Date.now() - generatedMs) / 1000))   // ← server ≠ client
    : 0;
```

Server and client evaluate this at different instants, so a render that straddles a bucket
boundary flips the text ("Analyzed just now" → "Analyzed 1m ago") and React logs a mismatch.
The `title` on the next line is already correct — only the age calculation needs hoisting:

```diff
- const ageSecs = Number.isFinite(generatedMs)
-   ? Math.max(0, Math.round((Date.now() - generatedMs) / 1000))
-   : 0;
+ const [ageSecs, setAgeSecs] = useState<number | null>(null);
+ useEffect(() => {
+   if (!Number.isFinite(generatedMs)) return;
+   setAgeSecs(Math.max(0, Math.round((Date.now() - generatedMs) / 1000)));
+ }, [generatedMs]);
+ // null on the server pass → render the timestamp alone, no mismatch
```

The existing guard does not cover this: it scans for `toLocaleString`, not for clock reads in
render. Extending it to flag `Date.now()` outside `useEffect`/`useState`/handlers would close
the class rather than this instance.

## 3.2 Two layout traps this codebase has already paid for

Both recurred. Treat as checklist items, not cautions.

**Container parity is FOUR things, not three** — the loading interstitial, its SSR skeleton,
the selector overlay wrapper, *and* the root `<main>`'s own padding. That layout regressed
four times, most recently by adding `p-4` to a component whose parent already supplies
`px-4 py-5 sm:px-6 lg:px-8`. **Check what the parent supplies before adding any.**

**`min-w-0` belongs on the grid item, not its inner text block.** Grid and flex items default
to `min-width: auto`. A 27 px mobile overflow traced to a row rendering 359 px inside its own
303 px column, with `min-w-0` present one level too deep. `truncate` alone does not fix it.

⚠️ Diagnose both by **measuring**, not theory — apply the candidate fix with `page.evaluate`
and re-measure `documentElement.scrollWidth` *before* editing source.

## 3.3 Accessibility — finish the focus layer

The shared `Tooltip` was hardened for keyboard access (focus/blur, `role="tooltip"`,
`aria-describedby`), fixing every caller at once. What remains is a visible focus state on
custom interactive surfaces — league chips, fixture rows, filter pills — which currently rely
on the browser default over a dark ground.

```css
/* One token, applied at the shared layer rather than per component. */
:where(a, button, [role="button"], [tabindex="0"]):focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
  border-radius: 3px;
}
```

---

# Pillar 4 — Targeted quick wins

> Ranked by value per hour. Each was checked against the codebase first — several obvious
> candidates are **already done**, and re-doing them is the most common way this list wastes
> a session.

| Win | Effort | Status |
|---|---|---|
| Hoist `Date.now()` out of `PredictionAgePill` render | ~15 min | **Open** — removes a live hydration mismatch |
| Evidence-copy map + guard test | ~1 h | **Open** — highest user-visible gain |
| Shared `:focus-visible` token | ~20 min | **Open** — one rule, every control |
| Timestamp formatter sweep | — | **Already shipped** in `01025ca`, guarded by `timestamp-contract.test.ts` |
| Skeleton loaders | — | **Already shipped.** Do not rebuild |
| Redis caching layer | — | **Already shipped.** 3-tier, live-verified |
| Error boundary recovery | — | **Already shipped.** `router.refresh()`, never a document reload |
| DB indexes on hot columns | — | **Skip.** ~13 k rows; a scan is sub-millisecond. Premature |
| Payload trimming | — | **Unmeasurable here** (see §0) |

### Static backend audit — passed

- Single aliased outer-join on the hot path — **no N+1**, bounded `LIMIT`.
- `pool_pre_ping`, `pool_size`, `max_overflow`, `pool_recycle` all configured; `NullPool`
  on the fallback path.
- One worker, one process, one pool. Connection exhaustion is structurally not a risk.
- `apps/web` holds **no database client** — the proxy-only production contract holds.

One observation recorded with its threshold rather than acted on:
`func.lower(Match.league_id) == league.lower()` makes `ix_matches_league_date` unusable for
that predicate. It is defensive against legacy lowercase rows and irrelevant at current
volume. **Revisit above ~1M rows, not before.**

---

# Blocked on a decision — two items

Neither yields to more engineering. Both are recorded in `docs/DEBT.md` with the mechanism
and options, and deliberately **not chosen**.

## Decision 1 — The uncertainty gap (`docs/DEBT.md` item 42)

`stake_permitted` requires `not partial`, and any critical gap forces `partial`. Every
analysis carries `MODEL_UNCERTAINTY_UNAVAILABLE` because `torch` is in neither requirements
file and no trained BNN artifact exists.

> **Certifying the model will NOT enable staking.** A candidate clearing every gate in
> `certification_policy.py` still returns `stake_permitted: false` on every fixture.

Options: ship torch + a trained artifact; reclassify the gap to advisory under authorization;
or accept research-only serving as a recorded decision.

⚠️ Do not reclassify autonomously. Loosening a staking gate *after* observing that it is what
stands between the platform and a green board is precisely the shape APEX §23 forbids.

## Decision 2 — The Brier convention (`docs/DEBT.md` item 43)

The BNN gate is `≤ 0.220`. The bookmaker market scores **0.5787** on the same convention —
the target is **2.6× better than the market** and not reachable by any honest model.

Two readings, both one-line changes:

- **Units** — `_brier_score()`'s docstring says "*mean* Brier across all three classes" while
  the code sums. Under the mean convention the market is 0.193 and the real-corpus model
  0.194, both inside 0.220.
- **Threshold** — the constant was simply set without an attainable referent.

Until settled, Pillar 2 tuning optimizes toward a number nothing can reach.

## Operator-only (no code path)

Old Redis credential revocation; two historical Gitleaks fingerprints
(`backend/.env.example` @ `d604c13`, `67ed0ab`); a fresh Docker image build needing 6–8 GB VM
memory. The custom domain is deprioritized — the Vercel alias is canonical.

---

# Sequencing

P1, P3 and P4 are independent and can ship in any order. P2 is gated.

1. **Settle Decision 2** before any tuning run. Five minutes, and it determines whether
   Pillar 2 has a meaningful objective at all.
2. **Ship the P4 quick wins** — timestamp sweep, focus token. Contained, guarded, and neither
   touches model or staking logic.
3. **Ship P1's copy map with its guard test.** Largest visible improvement per hour, and the
   guard stops the next feature from reopening it.
4. **Then P3's layout checklist**, measuring before editing.
5. **P2 integration last**, and only once Decision 1 has an answer — the retrain, the schema
   bump and the promotion gate are one atomic change, not three.

## Gates before every PR

```bash
cd backend
../.venv/Scripts/python.exe -m ruff check src/                  # must be 0
../.venv/Scripts/python.exe -m pytest tests/ -q -p no:randomly  # ~9 min, 0 failed
../.venv/Scripts/python.exe scripts/check_mypy_ceiling.py       # <= 784, no new in touched files
../.venv/Scripts/python.exe scripts/verify_active_artifacts.py  # exit 0
cd ../ && pnpm --filter @sabiscore/web lint typecheck test
NODE_ENV=production pnpm --filter @sabiscore/web build
```

⚠️ **Never judge a gate through `| tail`** — the pipe masks the exit code. Redirect to a file
and check `$?`. Use `.venv/Scripts/python.exe` explicitly; bare `python` resolves to a system
interpreter without the scientific stack. A stale `.mypy_cache` false-fails the ceiling gate —
re-run with `--no-incremental` before believing a persistent error.

**Merging:** `master` requires an approving review and repo-level auto-merge is disabled.
Open the PR, wait for green + approval, then squash-merge. Do not use `--admin` to bypass
branch protection without explicit instruction.

---

## Appendix — Scope note on Prisma

An operational directive circulated proposing a Prisma migration strategy
(`prisma migrate dev` / `migrate deploy`, `prisma/migrations` in VCS, a global
`PrismaClient`, PgBouncer, `tenantId` + RLS). **It does not apply to this repo.** Verified:

- No `schema.prisma`, no `prisma/` directory, no `PrismaClient` usage anywhere.
- `prisma.config.ts` is `definePrismaConfig({ skills: { agents: [...] } })` — the
  **agent-skills sync tool**, with no datasource, generator, or models.
- Schema authority is **9 Alembic migrations**, head `0009_quarantine_post_kickoff_closings`,
  exactly as CLAUDE.md declares. There are no "newly merged database schemas" — PR #109
  contains zero migrations.
- No multi-tenancy exists — `tenant_id` / `Tenant` return nothing repo-wide.
- Connection pooling: `apps/web` has no DB client and the backend runs `--workers 1`, so one
  process holds one pool. PgBouncer would add a hop and solve nothing at this scale.

That guidance is sound for the **TaxBridge / Hashablanca / SwarmX** verticals, which are
Prisma 5 per CLAUDE.md's stack table. It is simply a different vertical.
