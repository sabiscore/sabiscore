-- backend/scripts/verify_elo.sql
BEGIN TRANSACTION READ ONLY;

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
    SELECT match_id,
           count(*) AS row_count,
           count(DISTINCT team_id) AS team_count
    FROM elo_rating_snapshots
    GROUP BY match_id
),
processed AS (
    SELECT f.*, s.row_count, s.team_count
    FROM eligible_finished f
    JOIN snapshot_counts s ON s.match_id = f.id
)
SELECT
    (SELECT count(*) FROM elo_rating_snapshots) AS elo_rows,
    (SELECT count(DISTINCT team_id) FROM elo_rating_snapshots) AS unique_team_ids,
    (SELECT count(*) FROM eligible_finished) AS eligible_finished_matches,
    (SELECT count(*) FROM processed) AS processed_matches,
    (
        SELECT count(*)
        FROM eligible_finished f
        WHERE NOT EXISTS (
            SELECT 1
            FROM elo_rating_snapshots e
            WHERE e.match_id = f.id
        )
    ) AS unprocessed_matches,
    (
        SELECT count(*)
        FROM processed
        WHERE row_count <> 2 OR team_count <> 2
    ) AS non_two_snapshot_matches,
    (
        SELECT count(*)
        FROM elo_rating_snapshots e
        LEFT JOIN teams t ON t.id = e.team_id
        WHERE t.id IS NULL
    ) AS orphan_team_ids,
    (
        SELECT count(*)
        FROM elo_rating_snapshots e
        JOIN matches m ON m.id = e.match_id
        WHERE e.team_id <> m.home_team_id
          AND e.team_id <> m.away_team_id
    ) AS team_identity_mismatches,
    (SELECT max(match_date) FROM elo_rating_snapshots) AS latest_processed_match;

ROLLBACK;