-- backend/scripts/verify_clv_by_generation.sql
-- Read-only provenance guard: never pool CLV evidence across model versions.
-- A legitimate closing line must be observed strictly before fixture kickoff.

BEGIN TRANSACTION READ ONLY;

WITH closing_ranked AS (
    SELECT ms.*,
           row_number() OVER (
               PARTITION BY ms.match_id
               ORDER BY ms.captured_at DESC, ms.id DESC
           ) AS closing_rank
    FROM market_snapshots ms
    JOIN matches m ON m.id = ms.match_id
    WHERE ms.is_closing_line IS TRUE
      AND ms.coherent IS TRUE
      AND ms.captured_at < m.match_date
      AND ms.home_odds > 1
      AND ms.draw_odds > 1
      AND ms.away_odds > 1
      AND ms.home_implied_prob_devigged BETWEEN 0 AND 1
      AND ms.draw_implied_prob_devigged BETWEEN 0 AND 1
      AND ms.away_implied_prob_devigged BETWEEN 0 AND 1
      AND abs(
          ms.home_implied_prob_devigged
        + ms.draw_implied_prob_devigged
        + ms.away_implied_prob_devigged
        - 1.0
      ) <= 0.001
),
current_closing AS (
    SELECT *
    FROM closing_ranked
    WHERE closing_rank = 1
),
prediction_ranked AS (
    SELECT p.model_version,
           p.id AS prediction_id,
           p.match_id,
           p.created_at,
           p.home_probability,
           p.draw_probability,
           p.away_probability,
           c.home_implied_prob_devigged,
           c.draw_implied_prob_devigged,
           c.away_implied_prob_devigged,
           row_number() OVER (
               PARTITION BY p.match_id, p.model_version
               ORDER BY p.created_at DESC, p.id DESC
           ) AS prediction_rank
    FROM match_prediction_logs p
    JOIN matches m ON m.id = p.match_id
    JOIN current_closing c ON c.match_id = p.match_id
    WHERE p.created_at < c.captured_at
      AND lower(m.status) = 'finished'
      AND m.home_score IS NOT NULL
      AND m.away_score IS NOT NULL
      AND p.model_version IS NOT NULL
      AND btrim(p.model_version) <> ''
),
joined AS (
    SELECT model_version,
           prediction_id,
           match_id,
           created_at,
           CASE
               WHEN home_probability >= draw_probability
                AND home_probability >= away_probability
                   THEN home_probability - home_implied_prob_devigged
               WHEN draw_probability >= home_probability
                AND draw_probability >= away_probability
                   THEN draw_probability - draw_implied_prob_devigged
               ELSE away_probability - away_implied_prob_devigged
           END AS clv
    FROM prediction_ranked
    WHERE prediction_rank = 1
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

-- Missing generation identity is a hard audit failure for certification. These
-- rows remain preserved for forensics but cannot enter the scoped join above.
SELECT count(*) AS prediction_rows_without_generation_scope
FROM match_prediction_logs
WHERE model_version IS NULL OR btrim(model_version) = '';

-- Invalid temporal rows remain in storage for forensic audit but are excluded
-- from `current_closing` above and therefore cannot contribute to CLV.
SELECT count(*) AS closing_rows_at_or_after_kickoff
FROM market_snapshots ms
JOIN matches m ON m.id = ms.match_id
WHERE ms.is_closing_line IS TRUE
  AND ms.captured_at >= m.match_date;

ROLLBACK;
