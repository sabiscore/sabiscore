-- backend/scripts/verify_clv_settlement.sql
BEGIN TRANSACTION READ ONLY;

WITH predictions AS (
    SELECT p.*, m.match_date, m.status AS match_status,
           m.home_score, m.away_score
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
           count(*) OVER (PARTITION BY ms.match_id) AS closing_rows_per_match
    FROM market_snapshots ms
    WHERE ms.is_closing_line IS TRUE
),
valid_closing AS (
    SELECT *
    FROM closing
    WHERE coherent IS TRUE
      AND home_odds > 1
      AND draw_odds > 1
      AND away_odds > 1
      AND home_implied_prob_devigged BETWEEN 0 AND 1
      AND draw_implied_prob_devigged BETWEEN 0 AND 1
      AND away_implied_prob_devigged BETWEEN 0 AND 1
      AND abs(
          home_implied_prob_devigged +
          draw_implied_prob_devigged +
          away_implied_prob_devigged - 1.0
      ) <= 0.001
)
SELECT
    (SELECT count(*) FROM eligible) AS pre_kickoff_predictions,
    (SELECT count(*) FROM settled) AS settled_predictions,
    (SELECT count(*) FROM market_snapshots
        WHERE is_closing_line IS FALSE) AS opening_snapshots,
    (SELECT count(*) FROM closing) AS closing_snapshots,
    (
        SELECT count(*)
        FROM settled s
        JOIN valid_closing c ON c.match_id = s.match_id
    ) AS clv_join_count,
    (
        SELECT count(DISTINCT s.match_id)
        FROM settled s
        JOIN valid_closing c ON c.match_id = s.match_id
    ) AS clv_match_count;

ROLLBACK;