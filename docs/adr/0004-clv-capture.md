# 0004 — Pre-match market lifecycle and CLV evidence

**Status:** Accepted · 2026-08-05 · reconciled 2026-08-17

## Context

SabiScore never executes a bet at a captured price. Its CLV diagnostic is therefore
**model probability vs. de-vigged closing-market probability**, not a bettor's
placed-price-vs-closing-price calculation. Missing market evidence must remain
missing; it must never be reconstructed from a later line or fabricated from a
fallback value.

The production data plane now has two distinct market stores with different jobs:

- `OddsHistory` is the numerical time-series consumed by Phase-8 market-drift
  features (`market_type="match_odds"` for 1X2 observations).
- `MarketSnapshot` is the evidence/provenance surface used by CLV and audit paths.
  It stores raw 1X2 odds, de-vigged probabilities, capture timestamps, provider and
  bookmaker identity, and lifecycle provenance.

`fixture_sync_service` now creates verified canonical fixture/event mappings in
addition to the legacy `matches` rows, so current market evidence may populate both
`match_id` and `canonical_fixture_id` when that mapping exists. `match_id` remains
the compatibility join used by current CLV queries.

Normalized `TheOddsAPIProvider.odds()` records include `provider_event_id`, event
kickoff, **home and away team names**, bookmaker identity/update time, 1X2 odds,
coherence/executability flags, and capture time. Older assumptions that only
kickoff proximity was available are obsolete.

## Decision

### 1. Preserve the existing numerical stream

Do not create a second odds-history table. Every accepted real 1X2 observation is
written to `OddsHistory` with:

- `match_id`;
- one real bookmaker;
- `market_type="match_odds"`;
- home/draw/away decimal odds;
- the actual observation timestamp.

The writer does **not** median each outcome across different bookmakers. Independent
per-outcome aggregation would create a synthetic market that no bookmaker offered.
For each provider event/board pass, SabiScore selects one deterministic coherent
bookmaker record and preserves that bookmaker in provenance.

### 2. Classify temporal evidence explicitly

`MarketSnapshot.provenance["evidence_class"]` uses these states:

- `PRE_MATCH_OPENING` — the first real observation SabiScore saw **before** the
  final closing window. This means first-observed-by-SabiScore, not the bookmaker's
  official market-open price.
- `PRE_MATCH_INTERMEDIATE` — a changed real observation after opening and before
  the final closing window.
- `PRE_MATCH_CLOSING` — the current final eligible observation in the documented
  pre-kickoff closing window.
- `PRE_MATCH_CLOSING_SUPERSEDED` — an earlier valid closing candidate retained for
  audit after a later eligible pre-kickoff close replaced it.
- `POST_KICKOFF_REJECTED` — classification used by runtime counters/logs for an
  observation at or after kickoff. These observations are **not persisted as valid
  `OddsHistory`/`MarketSnapshot` market evidence**.

If the first real observation arrives inside the closing window, it is a closing
observation only. SabiScore does not relabel it as opening evidence.

### 3. Closing-line invariant

A valid close must satisfy:

```text
captured_at < kickoff
```

Equality is rejected. The lifecycle uses the final five minutes before kickoff as
the closing classification window while the existing five-minute scheduler keeps a
ten-minute near-kickoff network trigger window. A later eligible close supersedes
all earlier current closing candidates while retaining those rows for audit. At
most one row per match is current with `is_closing_line=true`.

Unchanged prices are normally deduplicated. Closing is the exception: an unchanged
price observed later inside the closing window is still new temporal evidence and
must receive its own timestamp so the final pre-kickoff observation is provable.

### 4. Fixture identity must use participants and time

Odds events are matched to stored fixtures using all of:

1. canonical league;
2. normalized home-team identity in the same home orientation;
3. normalized away-team identity in the same away orientation;
4. provider kickoff within the documented tolerance.

Zero matches or multiple matches fail closed. Swapped participants are not accepted.
Timestamp-only matching is no longer permitted for this writer.

When the football-data.org event mapping for the legacy `match_id` is verified,
`canonical_fixture_id` is copied into the market snapshot. Absence of that mapping
remains `NULL`; it is never guessed.

### 5. Provider and transaction discipline

The existing CLV background loop owns provider network I/O. Market lifecycle
persistence consumes the already-fetched league board, so this change does not add
provider polling or quota consumption.

Production injects the lifespan-owned, registry-instrumented Odds API provider.
Provider request evidence is persisted independently by the provider-evidence
recorder. No durable observation means provider status remains `UNKNOWN`.

Each market event write runs inside a savepoint so one malformed/provider-specific
row cannot poison the entire league board or leave the parent `AsyncSession` in a
failed transaction. The outer capture pass explicitly rolls back any unhandled
DBAPI failure before returning the session to the pool.

### 6. CLV consumption remains evidence-only

CLV joins only current `MarketSnapshot(is_closing_line=true)` rows that are:

- strictly pre-kickoff;
- coherent;
- valid decimal 1X2 prices;
- valid de-vigged probabilities summing to one within tolerance.

Historical invalid/post-kickoff rows remain auditable but are excluded from CLV.
Generation-specific samples remain separate. A tiny or positive CLV sample cannot
certify a model.

Repository settlement and CLV reads require an explicit, non-empty
`model_version`; there is no unscoped production or research default. The canonical
SQL audit selects exactly one latest valid close per match, then the latest
prediction strictly before that close per `(match_id, model_version)`. CLV counts
and diagnostics are grouped by generation so duplicate captures and newer foreign
generations cannot multiply or hide a sample.

`MarketSnapshot.executable` is kept false by lifecycle persistence. Market evidence
is not permission to place a bet, enable Kelly sizing, or infer staking suitability.

## Schema history

Migration `0005_clv_capture_schema` added/relaxed the schema required for CLV:

- nullable `MarketSnapshot.canonical_fixture_id`;
- compatibility `MarketSnapshot.match_id`;
- de-vigged home/draw/away probabilities;
- `is_closing_line`;
- `MatchPredictionLog.closing_market_snapshot_id`.

The 2026-08-17 lifecycle implementation intentionally requires **no new migration**.
Lifecycle classification and linkage use existing `MarketSnapshot.provenance`, and
numerical observations use existing `OddsHistory`.

## Consequences

- Opening/intermediate/closing evidence can accumulate from the existing scheduler
  without extra provider calls.
- Phase-8 market drift can stop being structurally `DATA_GAP` only after real
  `OddsHistory(match_odds)` rows naturally accumulate.
- Missing opening evidence remains missing when the first observation is late.
- Post-kickoff observations cannot become closing prices.
- Canonical fixture provenance is used where verified but legacy `match_id` remains
  the current compatibility join.
- Provider configuration is not provider verification; zero durable requests stays
  `UNKNOWN`.
- Model certification, public value insight, and stake sizing remain separate gates.

## Reversal

The lifecycle writer is additive at the application layer and introduces no schema
migration. Reversal consists of disabling/removing lifecycle persistence while
retaining accumulated `OddsHistory` and `MarketSnapshot` rows as immutable audit
evidence. Existing CLV temporal-integrity rules remain valid independently of the
writer.
