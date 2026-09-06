-- ===========================================================================
-- Domestic fixture-identity audit -- READ ONLY
-- ===========================================================================
-- Target:   sabiscore_db_v3 (production). Unreachable from agent sessions
--           (single-IP allowlist), so a human operator runs this.
-- Purpose:  produce the evidence required before ANY entry may be added to
--           `_AUDITED_ALIASES` in backend/src/services/team_identity.py.
--
-- Why this exists
-- ---------------
-- A live census of all 68 upcoming fixtures (2026-09-06, via
-- GET /api/v1/matches/upcoming/{id}/full-analysis?league=<canonical>)
-- returned FIXTURE_IDENTITY_UNVERIFIED on 22. Fifteen are UCL and are
-- CORRECT -- there is no UCL Elo corpus, and cross-league ties have no
-- single-league history to resolve against. Seven are domestic and are not:
--
--   EPL         Everton FC              vs  Manchester United FC
--   EPL         Aston Villa FC          vs  Nottingham Forest FC
--   EPL         Arsenal FC              vs  Chelsea
--   EPL         Sunderland AFC          vs  Arsenal FC
--   LA_LIGA     Valencia CF             vs  FC Barcelona
--   LA_LIGA     Real Madrid CF          vs  Rayo Vallecano de Madrid
--   BUNDESLIGA  RB Leipzig              vs  Hamburg
--
-- Two distinct causes are expected, and Q1/Q2 below separate them:
--
--   (a) Corpus abbreviation with no alias. data/cache/fd_E0_*.csv spells
--       these "Man United" and "Nott(apostrophe)m Forest"; the provider sends
--       the full legal name. `_AUDITED_ALIASES` already covers
--       ("EPL","manchester city") and ("EPL","newcastle united") but NOT these.
--
--   (b) Near-orphan duplicate Team rows. resolve_team_id()'s own comment
--       records that fixture sync has minted provider-named rows carrying
--       1-2 matches alongside the real historical row carrying 267+.
--       Affix-stripping lands on the near-orphan. "Arsenal FC" and
--       "FC Barcelona" identity-key cleanly, so those must be cause (b).
--
-- !! Do NOT assert an alias whose target Q2 shows with little or no Elo
-- history. An alias naming an absent or empty target makes resolve_team_id
-- fail CLOSED -- worse than the current state, not better. The Paris FC /
-- Paris SG incident (docs/DEBT.md item 40) is what happens when a plausible
-- identity is asserted without this evidence: 276 Elo snapshots belonging to
-- PSG were merged into the Paris FC row.
--
-- Every statement here is SELECT. Nothing writes. Safe to run on production.
-- Usage:  psql "$DATABASE_URL" -f investigate_domestic_aliases_v3.sql
-- ===========================================================================

\echo '=== Q1. Every Team row in the three affected leagues, with real history ==='
-- Reveals duplicate/near-orphan pairs directly: two rows for one club, one
-- with hundreds of Elo snapshots and one with ~0. The row with history is the
-- alias target; the other is the shadow that currently wins resolution.
SELECT
    t.league_id,
    t.id                                   AS team_id,
    t.name                                 AS team_name,
    t.active,
    COUNT(DISTINCT e.id)                   AS elo_snapshots,
    COUNT(DISTINCT m.id)                   AS matches_played,
    MIN(e.match_date)::date                AS elo_first,
    MAX(e.match_date)::date                AS elo_last
FROM teams t
LEFT JOIN elo_rating_snapshots e
       ON e.team_id = t.id
      AND e.league  = t.league_id
LEFT JOIN matches m
       ON (m.home_team_id = t.id OR m.away_team_id = t.id)
      AND m.status = 'finished'
WHERE t.league_id IN ('EPL', 'LA_LIGA', 'BUNDESLIGA')
GROUP BY t.league_id, t.id, t.name, t.active
ORDER BY t.league_id, elo_snapshots DESC, t.name;

\echo ''
\echo '=== Q2. The seven unresolved names: candidate targets ranked by history ==='
-- One row per (provider name, candidate team). The operator reads off the
-- highest-history row as the alias target. A club returning a single
-- HISTORICAL row means cause (a) -- a missing alias. Two or more rows with one
-- near-empty means cause (b) -- a duplicate to be rebound, NOT aliased.
WITH probes(league_id, provider_name, needle) AS (
    VALUES
        ('EPL',        'Manchester United FC',      '%anchester%nited%'),
        ('EPL',        'Nottingham Forest FC',      '%orest%'),
        ('EPL',        'Arsenal FC',                '%rsenal%'),
        ('EPL',        'Chelsea',                   '%helsea%'),
        ('EPL',        'Sunderland AFC',            '%underland%'),
        ('EPL',        'Aston Villa FC',            '%illa%'),
        ('LA_LIGA',    'FC Barcelona',              '%arcelona%'),
        ('LA_LIGA',    'Valencia CF',               '%alencia%'),
        ('LA_LIGA',    'Real Madrid CF',            '%eal%adrid%'),
        ('LA_LIGA',    'Rayo Vallecano de Madrid',  '%ayo%'),
        ('BUNDESLIGA', 'RB Leipzig',                '%eipzig%'),
        ('BUNDESLIGA', 'Hamburg',                   '%amburg%')
)
SELECT
    p.provider_name,
    t.league_id,
    t.id                        AS candidate_team_id,
    t.name                      AS candidate_team_name,
    COUNT(DISTINCT e.id)        AS elo_snapshots,
    MAX(e.match_date)::date     AS elo_last,
    CASE
        WHEN COUNT(DISTINCT e.id) = 0  THEN 'NO HISTORY - never an alias target'
        WHEN COUNT(DISTINCT e.id) < 20 THEN 'NEAR-ORPHAN - likely the shadow row'
        ELSE                                'HISTORICAL - candidate alias target'
    END                         AS verdict
FROM probes p
JOIN teams t
      ON t.league_id = p.league_id
     AND t.name ILIKE p.needle
LEFT JOIN elo_rating_snapshots e
      ON e.team_id = t.id
     AND e.league  = t.league_id
GROUP BY p.provider_name, t.league_id, t.id, t.name
ORDER BY p.provider_name, elo_snapshots DESC;

\echo ''
\echo '=== Q3. Upcoming fixtures currently pointing at a zero-Elo team row ==='
-- The operational consequence. Any fixture listed here with a 0 on either side
-- will report FIXTURE_IDENTITY_UNVERIFIED and REQUIRED_MODEL_INPUTS_UNAVAILABLE
-- until that side is rebound to a history-bearing row.
SELECT
    m.league_id,
    m.id                        AS fixture_id,
    m.match_date,
    ht.name                     AS home_team,
    (SELECT COUNT(*) FROM elo_rating_snapshots e
      WHERE e.team_id = m.home_team_id AND e.league = m.league_id) AS home_elo_rows,
    at.name                     AS away_team,
    (SELECT COUNT(*) FROM elo_rating_snapshots e
      WHERE e.team_id = m.away_team_id AND e.league = m.league_id) AS away_elo_rows
FROM matches m
JOIN teams ht ON ht.id = m.home_team_id
JOIN teams at ON at.id = m.away_team_id
WHERE m.status = 'scheduled'
  AND m.match_date >= NOW() - INTERVAL '1 day'
  AND m.league_id IN ('EPL', 'LA_LIGA', 'BUNDESLIGA', 'SERIE_A', 'LIGUE_1', 'EREDIVISIE')
ORDER BY m.league_id, m.match_date;

\echo ''
\echo '=== Q4. Durable provider-ID bridges already asserted for these leagues ==='
-- A VERIFIED provider_elo_team_mappings row means the durable provider-ID
-- bridge already answers this identity and NO alias is needed -- resolution is
-- failing somewhere else. Check this before writing anything.
SELECT
    pem.competition,
    pem.provider,
    pem.provider_team_id,
    pem.provider_team_name,
    pem.team_id,
    t.name                      AS mapped_team_name,
    pem.reconciliation_status,
    pem.reconciliation_confidence
FROM provider_elo_team_mappings pem
LEFT JOIN teams t ON t.id = pem.team_id
WHERE pem.competition IN ('EPL', 'LA_LIGA', 'BUNDESLIGA')
ORDER BY pem.competition, pem.provider_team_name;

\echo ''
\echo '=== Q5. Non-VERIFIED canonical-team reconciliations in the same leagues ==='
SELECT
    ptm.competition,
    ptm.provider,
    ptm.provider_team_name,
    ptm.canonical_team_id,
    ct.name                     AS canonical_name,
    ptm.reconciliation_status,
    ptm.reconciliation_confidence
FROM provider_team_mappings ptm
LEFT JOIN canonical_teams ct ON ct.id = ptm.canonical_team_id
WHERE ptm.competition IN ('EPL', 'LA_LIGA', 'BUNDESLIGA')
  AND ptm.reconciliation_status <> 'VERIFIED'
ORDER BY ptm.competition, ptm.provider_team_name;

-- ===========================================================================
-- What to do with the output
-- ===========================================================================
-- Cause (a), a missing alias -- Q2 shows exactly one HISTORICAL row and the
--   provider name differs from it:
--     add ("<LEAGUE>", "<identity_key(provider_name)>"):
--         "<identity_key(historical_row_name)>"
--     to _AUDITED_ALIASES, quoting the Q2 elo_snapshots count in the comment,
--     as every existing entry already does.
--
-- Cause (b), a duplicate row -- Q2 shows a HISTORICAL row AND a NEAR-ORPHAN:
--   this is a rebind, not an alias. Use the existing authorized Class C path
--   (POST /api/v1/release/orphan-team-repair-review, then -apply with the
--   reviewed manifest digest). Adding an alias here would leave the orphan in
--   place to be re-selected by the next fixture sync.
--
-- Q4 non-empty for a club -- neither: the durable bridge already answers it,
--   so investigate why resolve_team_id is not reaching that path.
--
-- Re-run the live census after any change: for each upcoming fixture,
-- GET .../full-analysis?league=<canonical> and count
-- FIXTURE_IDENTITY_UNVERIFIED. Baseline 2026-09-06: 22/68 (15 UCL, 7 domestic).
-- ===========================================================================
