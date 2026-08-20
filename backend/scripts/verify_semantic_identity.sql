-- Read-only semantic identity gate for historical Match/Elo state.
--
-- Structural checks such as `elo.league = match.league_id` are insufficient if
-- a Match participant itself points at a Team owned by another league. This
-- script detects that cross-domain contamination without modifying any row.

BEGIN TRANSACTION READ ONLY;

WITH historical_matches AS (
    SELECT m.*
    FROM matches m
    WHERE m.id LIKE 'fdco-%'
),
match_identity AS (
    SELECT m.id,
           m.match_date,
           m.league_id,
           m.home_team_id,
           ht.name AS home_team_name,
           ht.league_id AS home_team_league,
           m.away_team_id,
           at.name AS away_team_name,
           at.league_id AS away_team_league
    FROM historical_matches m
    LEFT JOIN teams ht ON ht.id = m.home_team_id
    LEFT JOIN teams at ON at.id = m.away_team_id
),
snapshot_identity AS (
    SELECT e.id,
           e.match_id,
           e.team_id,
           e.league AS snapshot_league,
           t.name AS team_name,
           t.league_id AS team_league,
           e.match_date
    FROM elo_rating_snapshots e
    LEFT JOIN teams t ON t.id = e.team_id
)
SELECT metric, value
FROM (
    SELECT 'historical_match_home_team_league_mismatch'::text AS metric,
           count(*)::text AS value
    FROM match_identity
    WHERE home_team_league IS NULL OR home_team_league <> league_id

    UNION ALL
    SELECT 'historical_match_away_team_league_mismatch', count(*)::text
    FROM match_identity
    WHERE away_team_league IS NULL OR away_team_league <> league_id

    UNION ALL
    SELECT 'historical_matches_with_semantic_identity_mismatch', count(*)::text
    FROM match_identity
    WHERE home_team_league IS NULL
       OR away_team_league IS NULL
       OR home_team_league <> league_id
       OR away_team_league <> league_id

    UNION ALL
    SELECT 'elo_snapshot_team_league_mismatch', count(*)::text
    FROM snapshot_identity
    WHERE team_league IS NULL OR team_league <> snapshot_league
) summary
ORDER BY metric;

-- Exact historical Match participant violations.
SELECT id AS match_id,
       match_date,
       league_id AS match_league,
       home_team_id,
       home_team_name,
       home_team_league,
       away_team_id,
       away_team_name,
       away_team_league
FROM match_identity
WHERE home_team_league IS NULL
   OR away_team_league IS NULL
   OR home_team_league <> league_id
   OR away_team_league <> league_id
ORDER BY match_date, id;

-- Exact Elo snapshot semantic violations. A certified state must return zero.
SELECT id AS snapshot_id,
       match_id,
       team_id,
       team_name,
       team_league,
       snapshot_league,
       match_date
FROM snapshot_identity
WHERE team_league IS NULL OR team_league <> snapshot_league
ORDER BY match_date, match_id, team_id;

ROLLBACK;
