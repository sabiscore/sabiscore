-- backend/scripts/verify_clv_settlement.sql
-- Read-only production verification for prediction -> settlement -> closing line -> CLV.
-- Closing odds are evaluation evidence only; this script never creates betting actionability.
-- A legitimate closing line must be observed strictly before fixture kickoff.

BEGIN TRANSACTION READ ONLY;

WITH predictions AS (
    SELECT p.*, m.match_date, m.status AS match_status, m.home_score, m.away_score
    FROM match_prediction_logs p
    LEFT JOIN matches m ON m.id = p.match_id
),
eligible AS (
    SELECT *
    FROM predictions
    WHERE match_date IS NOT NULL
      AND created_at < match_date
),
settled AS (
    SELECT *
    FROM eligible
    WHERE lower(match_status) = 'finished'
      AND home_score IS NOT NULL
      AND away_score IS NOT NULL
),
closing AS (
    SELECT ms.*,
           m.match_date AS kickoff,
           count(*) OVER (PARTITION BY ms.match_id) AS closing_rows_per_match
    FROM market_snapshots ms
    LEFT JOIN matches m ON m.id = ms.match_id
    WHERE ms.is_closing_line IS TRUE
),
valid_closing AS (
    SELECT *
    FROM closing
    WHERE kickoff IS NOT NULL
      AND captured_at < kickoff
      AND coherent IS TRUE
      AND home_odds > 1
      AND draw_odds > 1
      AND away_odds > 1
      AND home_implied_prob_devigged BETWEEN 0 AND 1
      AND draw_implied_prob_devigged BETWEEN 0 AND 1
      AND away_implied_prob_devigged BETWEEN 0 AND 1
      AND abs(
          home_implied_prob_devigged
        + draw_implied_prob_devigged
        + away_implied_prob_devigged
        - 1.0
      ) <= 0.001
),
joined AS (
    SELECT s.id AS prediction_id,
           s.match_id,
           s.model_version,
           s.created_at AS prediction_created_at,
           s.match_date,
           s.home_probability,
           s.draw_probability,
           s.away_probability,
           c.id AS market_snapshot_id,
           c.provider,
           c.bookmaker,
           c.captured_at,
           c.closing_rows_per_match,
           c.home_implied_prob_devigged,
           c.draw_implied_prob_devigged,
           c.away_implied_prob_devigged,
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
    JOIN valid_closing c ON c.match_id = s.match_id
)
SELECT metric, value
FROM (
    SELECT 'prediction_rows'::text AS metric, count(*)::text AS value FROM match_prediction_logs
    UNION ALL SELECT 'prediction_match_join_missing', count(*)::text FROM predictions WHERE match_date IS NULL
    UNION ALL SELECT 'eligible_pre_kickoff_predictions', count(*)::text FROM eligible
    UNION ALL SELECT 'post_kickoff_or_equal_predictions', count(*)::text
      FROM predictions WHERE match_date IS NOT NULL AND created_at >= match_date
    UNION ALL SELECT 'fundamentally_invalid_prediction_simplex', count(*)::text
      FROM eligible
      WHERE home_probability < 0 OR home_probability > 1
         OR draw_probability < 0 OR draw_probability > 1
         OR away_probability < 0 OR away_probability > 1
         OR abs((home_probability + draw_probability + away_probability) - 1.0) > 0.001
    UNION ALL SELECT 'quantized_near_simplex', count(*)::text
      FROM eligible
      WHERE abs((home_probability + draw_probability + away_probability) - 1.0) > 0.000001
        AND abs((home_probability + draw_probability + away_probability) - 1.0) <= 0.001
    UNION ALL SELECT 'max_prediction_simplex_error', coalesce(max(abs((home_probability + draw_probability + away_probability) - 1.0))::text, 'NULL') FROM eligible
    UNION ALL SELECT 'settled_eligible_predictions', count(*)::text FROM settled
    UNION ALL SELECT 'market_snapshot_rows', count(*)::text FROM market_snapshots
    UNION ALL SELECT 'opening_nonclosing_snapshot_rows', count(*)::text FROM market_snapshots WHERE is_closing_line IS FALSE
    UNION ALL SELECT 'closing_snapshot_rows', count(*)::text FROM closing
    UNION ALL SELECT 'coherent_closing_snapshot_rows', count(*)::text FROM closing WHERE coherent IS TRUE
    UNION ALL SELECT 'valid_pre_kickoff_closing_snapshot_rows', count(*)::text FROM valid_closing
    UNION ALL SELECT 'closing_match_join_missing', count(*)::text FROM closing WHERE kickoff IS NULL
    UNION ALL SELECT 'closing_captured_at_or_after_kickoff', count(*)::text
      FROM closing WHERE kickoff IS NOT NULL AND captured_at >= kickoff
    UNION ALL SELECT 'invalid_closing_market_rows', count(*)::text
      FROM closing
      WHERE NOT (
          kickoff IS NOT NULL
          AND captured_at < kickoff
          AND coherent IS TRUE
          AND home_odds > 1 AND draw_odds > 1 AND away_odds > 1
          AND home_implied_prob_devigged BETWEEN 0 AND 1
          AND draw_implied_prob_devigged BETWEEN 0 AND 1
          AND away_implied_prob_devigged BETWEEN 0 AND 1
          AND abs((home_implied_prob_devigged + draw_implied_prob_devigged + away_implied_prob_devigged) - 1.0) <= 0.001
      )
    UNION ALL SELECT 'matches_with_multiple_closing_rows', count(DISTINCT match_id)::text FROM closing WHERE closing_rows_per_match > 1
    UNION ALL SELECT 'closing_captured_after_kickoff', count(*)::text
      FROM closing WHERE kickoff IS NOT NULL AND captured_at > kickoff
    UNION ALL SELECT 'closing_captured_more_than_60m_after_kickoff', count(*)::text
      FROM closing WHERE kickoff IS NOT NULL AND captured_at > kickoff + interval '60 minutes'
    UNION ALL SELECT 'settled_predictions_with_valid_closing_join', count(*)::text FROM joined
    UNION ALL SELECT 'distinct_settled_matches_with_valid_closing_join', count(DISTINCT match_id)::text FROM joined
    UNION ALL SELECT 'clv_sample_size', count(*)::text FROM joined
    UNION ALL SELECT 'clv_mean_diagnostic_only', coalesce(avg(clv)::text, 'NULL') FROM joined
    UNION ALL SELECT 'clv_positive_count_diagnostic_only', count(*) FILTER (WHERE clv > 0)::text FROM joined
    UNION ALL SELECT 'oldest_settled_prediction', coalesce(min(created_at)::text, 'NULL') FROM settled
    UNION ALL SELECT 'newest_settled_prediction', coalesce(max(created_at)::text, 'NULL') FROM settled
) q
ORDER BY metric;

-- Per-prediction evidence chain. Only a valid pre-kickoff closing snapshot may
-- populate closing_snapshot_id. Invalid temporal rows remain visible above via
-- audit counts but never enter the CLV chain.
WITH eligible AS (
    SELECT p.*, m.match_date, m.status AS match_status, m.home_score, m.away_score
    FROM match_prediction_logs p
    JOIN matches m ON m.id = p.match_id
    WHERE p.created_at < m.match_date
),
closing AS (
    SELECT ms.*,
           row_number() OVER (PARTITION BY ms.match_id ORDER BY ms.captured_at DESC, ms.id DESC) AS rn,
           count(*) OVER (PARTITION BY ms.match_id) AS closing_rows_per_match
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
)
SELECT e.id AS prediction_id,
       e.match_id,
       e.model_version,
       e.created_at AS prediction_created_at,
       e.match_date AS kickoff,
       lower(e.match_status) = 'finished' AND e.home_score IS NOT NULL AND e.away_score IS NOT NULL AS settled,
       e.home_probability,
       e.draw_probability,
       e.away_probability,
       e.home_probability + e.draw_probability + e.away_probability AS probability_sum,
       c.id AS closing_snapshot_id,
       c.provider,
       c.bookmaker,
       c.captured_at AS closing_captured_at,
       c.closing_rows_per_match,
       c.coherent,
       c.home_implied_prob_devigged,
       c.draw_implied_prob_devigged,
       c.away_implied_prob_devigged,
       CASE
           WHEN c.id IS NULL THEN NULL
           WHEN e.home_probability >= e.draw_probability AND e.home_probability >= e.away_probability
               THEN e.home_probability - c.home_implied_prob_devigged
           WHEN e.draw_probability >= e.home_probability AND e.draw_probability >= e.away_probability
               THEN e.draw_probability - c.draw_implied_prob_devigged
           ELSE e.away_probability - c.away_implied_prob_devigged
       END AS clv
FROM eligible e
LEFT JOIN closing c ON c.match_id = e.match_id AND c.rn = 1
ORDER BY e.created_at, e.id;

-- Provider request observations. Absence is UNKNOWN, not success.
SELECT provider,
       status,
       count(*) AS observations,
       min(acquired_at) AS oldest_observation,
       max(acquired_at) AS newest_observation
FROM provider_request_summaries
GROUP BY provider, status
ORDER BY provider, status;

ROLLBACK;