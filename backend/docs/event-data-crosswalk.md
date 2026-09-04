# Event-Data Ingestion Crosswalk
# `home_pressing_intensity` and `progressive_carry_diff`

**Status:** Architectural draft — not yet ingesting live event data.  
**Purpose:** Document the exact mapping from available event-data providers to the two
remaining `PHASE7_FEATURES_ALWAYS_DATA_GAP` slots that require event-level (not
match-level) statistics. Blocking `serving_feature_availability` from reaching zero
until this work is done.

---

## 1. Target features

| Canonical name | CANONICAL_FEATURES_68 index | Default value | Current serving state |
|---|---|---|---|
| `home_pressing_intensity` | 28 | 0.55 | `ALWAYS_DATA_GAP` |
| `away_pressing_intensity` | 29 | 0.50 | `ALWAYS_DATA_GAP` |
| `progressive_carry_diff` | 30 | 0.00 | `ALWAYS_DATA_GAP` |

These are part of the `PHASE7_FEATURES_10` block defined in `feature_registry.py`.
`shot_quality_diff` is excluded from this crosswalk because it requires PSxG data
(post-shot expected goals), which StatsBomb Open does not publish for most seasons.

---

## 2. Provider landscape

### 2a. StatsBomb Open (free tier)

**Coverage**: 40+ competitions, full event streams, publicly available.  
**Format**: JSON event streams per match.  
**Python SDK**: `statsbombpy` (Apache 2.0 licence).  
**Limitation**: Coverage excludes the current live season for most competitions;
data for Ligue 1 and Bundesliga is sparse or absent.

**Relevant fields**:

| StatsBomb event type | Field | Maps to |
|---|---|---|
| Pressure events | Count of pressure events per team per 90 min | `pressing_intensity` (home/away) |
| Carry events | `progressive_carry_diff` = team carries crossing the D-box | `progressive_carry_diff` |

**PPDA** (Passes Allowed Per Defensive Action) is the established pressing proxy:
`ppda = opponent_passes_in_defensive_third / (defensive_actions_pressure + recoveries)`.
StatsBomb's Open competition data includes `type.name == "Pressure"` events and
allows computing team-level PPDA directly.

`StatsBombAggregator` (`src/data/enrichment/statsbomb_aggregator.py`) already holds
the cache schema (columns: `ppda_ratio`, `progressive_carry_diff`, …) and the read
path. The **gap is population**: the parquet cache is empty in production because
no ingestion script writes to it for the seven supported leagues.

### 2b. Understat extended fields

**Coverage**: EPL, La Liga, Bundesliga, Serie A, Ligue 1 — NOT Eredivisie or UCL.  
**Format**: JSON from `understat.com` via `soccerdata`'s `Understat` reader.  
**Relevant fields**: Understat does not publish pressing intensity or carry counts.
xG, xGA, and shot-quality proxies are available but blocked by `PHASE7_FEATURES_ALWAYS_DATA_GAP`
policy (see `docs/DEBT.md` item 56).

**Decision**: Understat does NOT supply either target feature. Skip for this crosswalk.

---

## 3. Identity normalisation

Both `home_pressing_intensity` and `progressive_carry_diff` require joining
a **StatsBomb team name** to a SabiScore canonical team ID.

StatsBomb names examples: `"Manchester City"`, `"FC Barcelona"`, `"Paris Saint-Germain"`,
`"Borussia Dortmund"`.

### Normalisation path

```
statsbomb_team_name
    │
    ▼
team_identity._identity_key(name)       # backend/src/data/team_identity.py
    │  folds diacritics (NFKD), lower-cases, strips legal tokens
    │  ("FC", "CF", "SC", "United", …), drops punctuation
    │
    ▼
identity_key   e.g. "manchester city", "barcelona", "paris saint germain"
    │
    ▼
_AUDITED_ALIASES lookup                 # corpus abbreviation → canonical key
    │  e.g. "man city" → "manchester city"
    │
    ▼
resolve_team_id(identity_key, league)   # providers/reconciliation.py
    │  fuzzy-scored against Team.name rows for that league
    │  VERIFIED (>=0.94) / REQUIRES_REVIEW / UNKNOWN
    │
    ▼
Team.id  →  canonical SabiScore team ID (e.g. "fd-team-epl:manchester_city")
```

### Known abbreviation additions needed

The StatsBomb→Understat naming clash (documented in `docs/DEBT.md` item 39) also
affects StatsBomb→SabiScore: some StatsBomb names differ from football-data.co.uk
abbreviations in `_AUDITED_ALIASES`. Known additions:

| StatsBomb name | NFKD key | `_AUDITED_ALIASES` entry needed |
|---|---|---|
| `"Paris Saint-Germain"` | `"paris saint germain"` | ✅ already resolves via fuzzy |
| `"Bayern München"` | `"bayernmunchen"` | needs `"bayernmunchen": "fc bayern munchen"` |
| `"Borussia Mönchengladbach"` | `"borussiamochengladbach"` | needs alias |
| `"Atlético Madrid"` | `"atletico madrid"` | ✅ already resolves |
| `"Deportivo Alavés"` | `"deportivo alaves"` | ✅ already resolves (NFKD strips accent) |

These aliases must be added to `team_identity._AUDITED_ALIASES` before ingestion.
Do not add them speculatively — derive from a real StatsBomb board for the target league.

---

## 4. Feature-level mapping

### 4a. `home_pressing_intensity` / `away_pressing_intensity`

```
Source:     StatsBomb Open — "Pressure" event type
Producer:   backend/src/data/enrichment/statsbomb_aggregator.py (cache column: ppda_ratio)
Mapping:    pressing_intensity ≈ 1 / ppda_ratio
            (lower PPDA = more pressing; invert to make "higher = more pressing")
            Clamp to [0.1, 2.0] to handle edge cases (extremely passive teams)
            home_pressing_intensity = 1 / home_ppda_ratio (5-match rolling average)
            away_pressing_intensity = 1 / away_ppda_ratio (5-match rolling away games)
Wiring site: data/transformers.py:FeatureTransformer._project_to_canonical_features()
             lines 539-545 — already checks for `home_pressing_intensity` in expected;
             reads from home_stats["pressing_intensity"] OR enhanced["home_pressing_intensity"]
```

No schema change needed. The `StatsBombAggregator` parquet cache already has
`ppda_ratio`; the transformer already reads `pressing_intensity`; the canonical
remap in `data/transformers.py:539` already writes `home_pressing_intensity`.

**Gap**: `StatsBombAggregator` is not called from `UpcomingMatchFeatureProjector`'s
serving path. Wiring it is gated on confirming StatsBomb Open coverage for the seven
supported leagues and population of the parquet cache.

### 4b. `progressive_carry_diff`

```
Source:     StatsBomb Open — "Carry" event type (carries that cross D-box line)
Producer:   backend/src/data/enrichment/statsbomb_aggregator.py (cache column: progressive_carry_diff)
Mapping:    progressive_carry_diff = home_progressive_carries_per90 − away_progressive_carries_per90
            (positive → home team carries more, suggesting territorial advantage)
Wiring site: data/transformers.py:547-550 — already checks and reads
             "progressive_carry_diff" or "sb_progressive_carry_diff"
```

Same gap as above: the cache column exists and the transformer reads it, but the
aggregator is not yet called from the serving path.

---

## 5. Ingestion prerequisites

Before any live serving value can replace the `ALWAYS_DATA_GAP` default:

1. **StatsBomb Open coverage audit** — confirm which of {EPL, LA_LIGA, BUNDESLIGA,
   SERIE_A, LIGUE_1, EREDIVISIE} are in the Open dataset for recent seasons.
   EREDIVISIE is historically absent; UCL Open data is partial.

2. **Parquet cache population script** — write an offline batch job (analogous to
   `scripts/train_on_real_matches.py`) that reads StatsBomb JSON events, computes
   per-team per-match PPDA and progressive-carry counts, and writes to the parquet
   cache path (`settings.statsbomb_cache_path`).

3. **Team alias additions** — add missing `_AUDITED_ALIASES` entries for StatsBomb
   names that do not resolve cleanly through NFKD + fuzzy scoring.

4. **`UpcomingMatchFeatureProjector` wiring** — call `StatsBombAggregator.get_team_features()`
   in `upcoming_match_feature_service.py`, alongside the existing `_get_team_stats()` call.
   Guard behind `ENABLE_STATSBOMB_ENRICHMENT=false` safe default.

5. **`feature_availability_matrix.json` regeneration** — run
   `scripts/generate_feature_availability_matrix.py` after wiring to update
   `serving_feature_availability` gate counts.

---

## 6. What this crosswalk does NOT authorise

- It does not add `progressive_carry_diff` or `home_pressing_intensity` to the
  canonical feature vector width (68-wide). They are already slots 28–30.
- It does not modify any certification gate or threshold.
- It does not wire StatsBomb into the serving path (step 4 above is gated on
  coverage confirmation and is a separate, authorised implementation task).
- It does not use `aggregator.py`'s fake `pressing_intensity` (Elo-derived, lines 217
  and 246) — that value is a fabrication and must NOT be mapped to this feature.
  `aggregator.py:217-246` should be removed when this crosswalk is implemented.

---

*Drafted 2026-09-04. Implementation is Phase 5 gated on StatsBomb Open coverage
audit (step 1 above). Re-derive team aliases from a real board, never from this doc.*
