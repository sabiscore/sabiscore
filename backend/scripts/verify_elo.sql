-- backend/scripts/verify_elo.sql
-- Read-only production evidence audit for durable real-identity Elo.
-- Run against the production-equivalent PostgreSQL database.
-- This script MUST NOT be used to advance/replay state.

BEGIN TRANSACTION READ ONLY;

-- 1. Integrity and replay-idempotency summary.
WITH eligible_finished AS (
    SELECT m.id, m.league_id, m.home_team_id, m.away_team_id, m.match_date
    FROM matches m
    WHERE lower(m.status) = 'finished'
      AND m.home_score IS NOT NULL
      AND m.away_score IS NOT NULL
      AND m.league_id IS NOT NULL
      AND m.home_team_id IS NOT NULL
      AND m.away_team_id IS NOT NULL
      AND m.home_team_id <> m.away_team_id
),
snapshot_counts AS (
    SELECT e.match_id,
           count(*) AS row_count,
           count(DISTINCT e.team_id) AS team_count
    FROM elo_rating_snapshots e
    GROUP BY e.match_id
),
processed AS (
    SELECT f.*, s.row_count, s.team_count
    FROM eligible_finished f
    JOIN snapshot_counts s ON s.match_id = f.id
),
upcoming AS (
    SELECT m.id, m.league_id, m.home_team_id, m.away_team_id, m.match_date
    FROM matches m
    WHERE lower(m.status) = 'scheduled'
      AND m.match_date >= (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
),
upcoming_resolution AS (
    SELECT u.*,
           EXISTS (
               SELECT 1
               FROM elo_rating_snapshots e
               WHERE e.team_id = u.home_team_id
                 AND e.league = u.league_id
                 AND e.match_date < u.match_date
           ) AS home_resolved,
           EXISTS (
               SELECT 1
               FROM elo_rating_snapshots e
               WHERE e.team_id = u.away_team_id
                 AND e.league = u.league_id
                 AND e.match_date < u.match_date
           ) AS away_resolved
    FROM upcoming u
)
SELECT metric, value
FROM (
    SELECT 'elo_rows'::text AS metric, count(*)::text AS value FROM elo_rating_snapshots
    UNION ALL SELECT 'elo_unique_team_ids', count(DISTINCT team_id)::text FROM elo_rating_snapshots
    UNION ALL SELECT 'elo_distinct_matches', count(DISTINCT match_id)::text FROM elo_rating_snapshots
    UNION ALL SELECT 'elo_earliest_match_date', coalesce(min(match_date)::text, 'NULL') FROM elo_rating_snapshots
    UNION ALL SELECT 'elo_latest_match_date', coalesce(max(match_date)::text, 'NULL') FROM elo_rating_snapshots
    UNION ALL SELECT 'eligible_finished_matches', count(*)::text FROM eligible_finished
    UNION ALL SELECT 'processed_eligible_matches', count(*)::text FROM processed
    UNION ALL SELECT 'unprocessed_eligible_finished_matches', count(*)::text
      FROM eligible_finished f
      WHERE NOT EXISTS (SELECT 1 FROM elo_rating_snapshots e WHERE e.match_id = f.id)
    UNION ALL SELECT 'processed_matches_not_exactly_two_rows', count(*)::text
      FROM processed WHERE row_count <> 2 OR team_count <> 2
    UNION ALL SELECT 'partial_one_row_matches', count(*)::text FROM snapshot_counts WHERE row_count = 1
    UNION ALL SELECT 'duplicate_match_team_pairs', count(*)::text
      FROM (
          SELECT match_id, team_id
          FROM elo_rating_snapshots
          GROUP BY match_id, team_id
          HAVING count(*) > 1
      ) d
    UNION ALL SELECT 'orphan_snapshot_match_ids', count(*)::text
      FROM elo_rating_snapshots e LEFT JOIN matches m ON m.id = e.match_id
      WHERE m.id IS NULL
    UNION ALL SELECT 'orphan_snapshot_team_ids', count(*)::text
      FROM elo_rating_snapshots e LEFT JOIN teams t ON t.id = e.team_id
      WHERE t.id IS NULL
    UNION ALL SELECT 'snapshot_team_not_home_or_away', count(*)::text
      FROM elo_rating_snapshots e JOIN matches m ON m.id = e.match_id
      WHERE e.team_id <> m.home_team_id AND e.team_id <> m.away_team_id
    UNION ALL SELECT 'snapshot_match_date_mismatch', count(*)::text
      FROM elo_rating_snapshots e JOIN matches m ON m.id = e.match_id
      WHERE e.match_date <> m.match_date
    UNION ALL SELECT 'snapshot_league_mismatch', count(*)::text
      FROM elo_rating_snapshots e JOIN matches m ON m.id = e.match_id
      WHERE e.league <> m.league_id
    UNION ALL SELECT 'finished_self_play_matches_excluded', count(*)::text
      FROM matches m
      WHERE lower(m.status) = 'finished'
        AND m.home_score IS NOT NULL
        AND m.away_score IS NOT NULL
        AND m.home_team_id IS NOT NULL
        AND m.home_team_id = m.away_team_id
    UNION ALL SELECT 'historical_fdco_self_play_matches', count(*)::text
      FROM matches m
      WHERE m.home_team_id IS NOT NULL
        AND m.home_team_id = m.away_team_id
        AND m.id LIKE 'fdco-%'
    UNION ALL SELECT 'non_historical_self_play_matches', count(*)::text
      FROM matches m
      WHERE m.home_team_id IS NOT NULL
        AND m.home_team_id = m.away_team_id
        AND m.id NOT LIKE 'fdco-%'
    UNION ALL SELECT 'scheduled_self_play_matches', count(*)::text
      FROM matches m
      WHERE lower(m.status) = 'scheduled'
        AND m.home_team_id IS NOT NULL
        AND m.home_team_id = m.away_team_id
    UNION ALL SELECT 'scheduled_upcoming_matches', count(*)::text FROM upcoming
    UNION ALL SELECT 'upcoming_home_elo_resolved', count(*) FILTER (WHERE home_resolved)::text FROM upcoming_resolution
    UNION ALL SELECT 'upcoming_away_elo_resolved', count(*) FILTER (WHERE away_resolved)::text FROM upcoming_resolution
    UNION ALL SELECT 'upcoming_both_elo_resolved', count(*) FILTER (WHERE home_resolved AND away_resolved)::text FROM upcoming_resolution
) q
ORDER BY metric;

-- 2. Per-league coverage. Zero rows are evidence, not a neutral rating.
WITH eligible AS (
    SELECT m.*
    FROM matches m
    WHERE lower(m.status) = 'finished'
      AND m.home_score IS NOT NULL
      AND m.away_score IS NOT NULL
      AND m.league_id IS NOT NULL
      AND m.home_team_id IS NOT NULL
      AND m.away_team_id IS NOT NULL
      AND m.home_team_id <> m.away_team_id
),
processed AS (
    SELECT DISTINCT e.match_id
    FROM elo_rating_snapshots e
)
SELECT e.league_id,
       count(*) AS eligible_finished_matches,
       count(*) FILTER (WHERE p.match_id IS NOT NULL) AS processed_matches,
       count(*) FILTER (WHERE p.match_id IS NULL) AS unprocessed_matches,
       round(
           100.0 * count(*) FILTER (WHERE p.match_id IS NOT NULL) / nullif(count(*), 0),
           2
       ) AS processed_pct,
       min(e.match_date) FILTER (WHERE p.match_id IS NOT NULL) AS first_processed_match,
       max(e.match_date) FILTER (WHERE p.match_id IS NOT NULL) AS last_processed_match
FROM eligible e
LEFT JOIN processed p ON p.match_id = e.id
GROUP BY e.league_id
ORDER BY e.league_id;

-- 3. Exact integrity violations. A healthy replay should return zero rows.
SELECT e.match_id,
       count(*) AS snapshot_rows,
       count(DISTINCT e.team_id) AS snapshot_teams,
       array_agg(e.team_id ORDER BY e.team_id) AS team_ids
FROM elo_rating_snapshots e
GROUP BY e.match_id
HAVING count(*) <> 2 OR count(DISTINCT e.team_id) <> 2
ORDER BY e.match_id;

-- 4. Identity violations. A healthy replay should return zero rows.
SELECT e.id AS snapshot_id,
       e.match_id,
       e.team_id,
       m.home_team_id,
       m.away_team_id,
       e.league AS snapshot_league,
       m.league_id AS match_league,
       e.match_date AS snapshot_match_date,
       m.match_date AS stored_match_date
FROM elo_rating_snapshots e
LEFT JOIN matches m ON m.id = e.match_id
LEFT JOIN teams t ON t.id = e.team_id
WHERE m.id IS NULL
   OR t.id IS NULL
   OR (e.team_id <> m.home_team_id AND e.team_id <> m.away_team_id)
   OR e.league <> m.league_id
   OR e.match_date <> m.match_date
ORDER BY e.match_date, e.match_id, e.team_id;

-- 5. Upcoming fixture-level resolution. This never substitutes 1500 for absence.
SELECT m.id AS match_id,
       m.league_id,
       m.home_team_id,
       m.away_team_id,
       m.match_date,
       EXISTS (
           SELECT 1 FROM elo_rating_snapshots e
           WHERE e.team_id = m.home_team_id
             AND e.league = m.league_id
             AND e.match_date < m.match_date
       ) AS home_elo_resolved,
       EXISTS (
           SELECT 1 FROM elo_rating_snapshots e
           WHERE e.team_id = m.away_team_id
             AND e.league = m.league_id
             AND e.match_date < m.match_date
       ) AS away_elo_resolved
FROM matches m
WHERE lower(m.status) = 'scheduled'
  AND m.match_date >= (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
ORDER BY m.match_date, m.id;

-- 6. Largest chronological gaps in processed history by league. Gaps are
-- diagnostic evidence; they are not automatically corruption because season
-- breaks are legitimate.
WITH processed_matches AS (
    SELECT DISTINCT m.id, m.league_id, m.match_date
    FROM matches m
    JOIN elo_rating_snapshots e ON e.match_id = m.id
),
ordered AS (
    SELECT league_id,
           id,
           match_date,
           lag(match_date) OVER (PARTITION BY league_id ORDER BY match_date, id) AS previous_match_date
    FROM processed_matches
)
SELECT league_id,
       id AS match_id,
       previous_match_date,
       match_date,
       match_date - previous_match_date AS gap
FROM ordered
WHERE previous_match_date IS NOT NULL
ORDER BY gap DESC NULLS LAST
LIMIT 50;

-- 7. Self-play provenance. Known residual fdco rows remain visible, while any
-- non-historical writer collision is mechanically distinguishable and must be
-- treated as a new integrity incident. This audit never rewrites either class.
SELECT m.id AS match_id,
       m.league_id,
       m.match_date,
       m.status,
       m.home_team_id,
       m.away_team_id,
       m.created_at,
       m.updated_at,
       CASE
           WHEN m.id LIKE 'fdco-%' THEN 'HISTORICAL_FDCO_RESIDUAL'
           ELSE 'NON_HISTORICAL_WRITER'
       END AS provenance_class
FROM matches m
WHERE m.home_team_id IS NOT NULL
  AND m.home_team_id = m.away_team_id
ORDER BY provenance_class, m.match_date, m.id;

ROLLBACK;
