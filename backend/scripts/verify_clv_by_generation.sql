-- backend/scripts/verify_clv_by_generation.sql
BEGIN TRANSACTION READ ONLY;

WITH settled AS (
    SELECT p.*
    FROM match_prediction_logs p
    JOIN matches m ON m.id = p.match_id
    WHERE p.created_at < m.match_date
      AND lower(m.status) = 'finished'
      AND m.home_score IS NOT NULL
      AND m.away_score IS NOT NULL
),
closing AS (
    SELECT *
    FROM market_snapshots
    WHERE is_closing_line IS TRUE
      AND coherent IS TRUE
)
SELECT
    s.model_version,
    count(*) AS clv_joined_predictions,
    count(DISTINCT s.match_id) AS clv_joined_matches,
    min(s.created_at) AS oldest_prediction,
    max(s.created_at) AS newest_prediction
FROM settled s
JOIN closing c ON c.match_id = s.match_id
GROUP BY s.model_version
ORDER BY s.model_version;

ROLLBACK;