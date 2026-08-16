-- backend/scripts/verify_clv_by_generation.sql
-- Read-only provenance guard: never pool CLV evidence across model versions.

BEGIN TRANSACTION READ ONLY;

WITH settled AS (
    SELECT p.*, m.match_date
    FROM match_prediction_logs p
    JOIN matches m ON m.id = p.match_id
    WHERE p.created_at < m.match_date
      AND lower(m.status) = 'finished'
      AND m.home_score IS NOT NULL
      AND m.away_score IS NOT NULL
),
closing AS (
    SELECT ms.*
    FROM market_snapshots ms
    WHERE ms.is_closing_line IS TRUE
      AND ms.coherent IS TRUE
      AND ms.home_odds > 1
      AND ms.draw_odds > 1
      AND ms.away_odds > 1
      AND ms.home_implied_prob_devigged BETWEEN 0 AND 1
      AND ms.draw_implied_prob_devigged BETWEEN 0 AND 1
      AND ms.away_implied_prob_devigged BETWEEN 0 AND 1
),
joined AS (
    SELECT s.model_version,
           s.id AS prediction_id,
           s.match_id,
           s.created_at,
           CASE
               WHEN s.home_probability >= s.draw_probability
                AND s.home_probability >= s.away_probability
                   THEN s.home_probability - c.home_implied_prob_devigged
               WHEN s.draw_probability >= s.home_probability
                AND s.draw_probability >= s.away_probability
                   THEN s.draw_probability - c.draw_implied_prob_devigged
               ELSE s.away_probability - c.away_implied_prob_devigged
           END AS clv
    FROM settled s
    JOIN closing c ON c.match_id = s.match_id
)
SELECT model_version,
       count(*) AS clv_joined_predictions,
       count(DISTINCT match_id) AS clv_joined_matches,
       min(created_at) AS oldest_prediction,
       max(created_at) AS newest_prediction,
       avg(clv) AS clv_mean_diagnostic_only,
       count(*) FILTER (WHERE clv > 0) AS positive_clv_count_diagnostic_only
FROM joined
GROUP BY model_version
ORDER BY model_version;

ROLLBACK;
