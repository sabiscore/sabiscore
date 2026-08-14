# 0003 — Settlement-join scheduling

**Status:** Accepted · 2026-08-05
**First ADR in this repository.** `docs/adr/` was empty prior to this file despite
several R3+ decisions having already shipped without one (WP-0's collision deletion,
WP-1's identity-resolution approach, WP-2's provenance approach, WP-3.1's fail-closed
padding). This is a paper-trail gap, not a template being introduced for its own sake —
it is not backfilled retroactively; it starts here.

## Context

**2026-08-14 follow-up.** The scheduling decision below shipped and is called in
production. The remaining zero-data cause was on the prediction side of the join:
fresh verified-fixture full analysis did not write `MatchPredictionLog`. The Apex v3
candidate now uses one shared capture path for finite real-model simplexes on an
existing scheduled fixture strictly before kickoff, deduplicated by
match/model/input hash without a migration. Settlement and CLV queries also select
only the latest prediction strictly before kickoff or closing-line capture. This is
`EXISTS / TESTED`, not `DEPLOYED / DATA-FED / VERIFIED`; the original production
context and decision history remain below.

`get_settled_predictions()` (`backend/src/repositories/fixtures.py`) and
`walk_forward_validate()` (`backend/src/models/model_registry.py`) were both correct
and fully unit-tested, but had zero production callers. Nothing in the deployed
process ever transitioned `Match.status` to `"finished"` with a real score, so both
functions always operated on an empty table (`docs/DEBT.md` item 2). `render.yaml`
runs exactly one `uvicorn --workers 1` process with no separate worker/cron service —
any scheduling has to be an in-process asyncio task.

## Decision

A new, independent, genuinely periodic background task —
`_background_settlement_sync()` in `backend/src/api/main.py`, hourly — that calls
`services/settlement_service.run_settlement_pass()`, which composes: fetch recent
results from a new `FootballDataAPIClient.get_recent_results()` provider method →
`fixture_sync_service.sync_settled_results()` (settle matching `Match` rows, keyed by
the same deterministic `fd-{id}` scheme `sync_upcoming_fixtures()` already writes, so
no identity re-resolution is needed) → `get_settled_predictions()` →
`walk_forward_validate()`. Registered via `asyncio.create_task()` in `lifespan()`,
alongside the existing fixture-sync task; its handle is stored and cancelled on
shutdown (it is infinite, unlike the one-shot fixture-sync task, so it needs explicit
cleanup).

## Alternatives considered

**(a) Extend `_background_fixture_sync`'s cadence with a settlement-check pass
immediately after each sync.** This was the campaign document's first-listed option,
on the premise that fixture-sync already runs on a recurring cadence. Tracing the
code found that premise false: `_background_fixture_sync` is a **one-shot task**,
fired once via `asyncio.create_task()` at process boot, with no loop — there is no
existing cadence to extend. Rejected because the alternative doesn't exist as
described; the shipped design is effectively this option's spirit (a second
independent periodic task) without the false premise.

**(c) Revive `ProductionOrchestrator.start()`
(`backend/src/services/orchestrator.py`).** Has zero callers anywhere in the
repository. If invoked, it would call `DataIngestionService.start()` — the same
scraper-based path below — plus add Redis-backed health/metrics loops with no unique
settlement-relevant behavior. Rejected: reviving a class with zero callers and unknown
behavioural currency is higher blast-radius than building a small, fresh, targeted
task next to a pattern (`_background_fixture_sync`) already proven correct in
production.

**`DataIngestionService._update_match_score` / `cli/start_ingestion.py`.** Sources
scores from `FlashscoreScraper` (a scraper, not an official provider), defaults
`status` to `"live"` not `"finished"` (so a row it writes wouldn't even satisfy
`SETTLED_MATCH_STATUSES` without a second fix), and only runs as a standalone CLI
process (`python -m backend.src.cli.start_ingestion`) never started by `render.yaml`.
Rejected: not part of the deployed process, wrong data source, wrong default status.

**`backend/src/tasks/background.py`'s Celery `beat_schedule`.** Has a
`calculate-model-performance` entry that looks like exactly this feature. Rejected
outright, not merely deprioritized: **the module cannot be imported.** It does
`from ..models.match import Match` (that file does not exist) and
`from ..models.prediction import Prediction` (exists, but defines
`PredictionEngine`/`PredictionResult`, not a `Prediction` class). No Celery
worker/beat process is deployed anywhere (`Procfile`/`docker-compose*.yml`/
`Dockerfile`/`render.yaml` all grepped, zero hits). Not prior art — a red herring
that happens to share a name with this work package's goal.

**Routing the new provider call through `providers/football_data_org.py`'s
`FootballDataOrgProvider`** instead of extending
`data/loaders/football_data_api.py`. A nicer-looking, already-registered gateway
with real (not hardcoded) status passthrough. Rejected: its `FixtureRecord` has no
score fields either, so it is not a free win; it is a live traffic-serving class
backing `/api/v1/fixtures` and `/api/v1/providers`, so extending it risks that
surface for a capability nothing there needs; and `fixture_sync_service.py` — which
the new `sync_settled_results()` must live beside and mirror — already depends on
`data/loaders/football_data_api.py`. Pulling in the *other* football-data.org
integration would make one file straddle two competition-code maps, two auth
patterns, two envelopes. Noted as a pre-existing duplication between the two
football-data.org integrations, not resolved by this ADR.

## Consequences

- `Match.status`/`home_score`/`away_score` — pre-existing nullable columns — are now
  written outside the fixture-sync path for the first time. No schema change, no
  Alembic migration.
- One new provider method (`get_recent_results`), one new sync function
  (`sync_settled_results`), one new file (`settlement_service.py`), one new
  background task, one new `/health` component, a real `/model-performance` branch.
- `/model-performance` stays `503 insufficient_settled_predictions` until ≥10 settled,
  logged predictions exist for the requested scope (`walk_forward_validate`'s own
  `n_splits*2` floor at the default `n_splits=5`) — an honest wait, not a bug, and not
  papered over with an adaptive metric.
- Once a match hits `SETTLED_MATCH_STATUSES`, its score is frozen — a provider-side
  score correction after settlement is never re-applied. Accepted, not solved here.
- `create_prediction()`'s synthetic `match_id` (`api/endpoints/predictions.py`,
  `f"{home}_{away}_{timestamp}"` when the caller omits a real one) can never join to
  a `Match.id` — an existing, orthogonal risk to `settled_join_rate`'s eventual
  ceiling. Tracked as `docs/DEBT.md` item 5, not fixed here.

## Reversal

**Cost:** low. Pure code revert — delete the new task registration in `main.py`, the
new file, and the additive provider/sync methods. No data migration needed: any
`Match` rows already settled during this feature's operation remain valid under the
already-shipped `get_settled_predictions()` query layer even after a revert; reverting
only stops *new* settlements, it does not corrupt or need to undo old ones.
**Trigger:** if the hourly cadence turns out to meaningfully strain the
football-data.org 10 req/min free tier once all 7 competitions are active
simultaneously (unlikely at ~0.12 req/min average, but re-check once EPL/La
Liga/Bundesliga/Ligue 1/Serie A all open), or if a future dedicated worker/cron
service replaces the single-dyno constraint this design was built around, making an
in-process asyncio loop the wrong shape rather than the only available one.
