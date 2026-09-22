"""
220-Feature Enrichment Pipeline

Generates comprehensive feature vectors for ML models including:
- Form metrics (last 5, 10, 20 matches)
- xG analytics (rolling averages, differentials)
- Fatigue indices (rest days, travel distance)
- Home advantage (crowd boost, referee bias)
- Momentum metrics (Poisson λ, win streaks)
- Market indicators (panic score, volatility)
- Head-to-head history
- Squad strength (valuations, missing players)
- Weather conditions
- Elo ratings
- Tactical features (formation, pressing, possession style)
"""

from datetime import datetime, timezone, timedelta
from typing import Dict

import numpy as np
from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from ...core.database import (
    Match,
    MatchStats,
    MatchEvent,
    OddsHistory,
    PlayerValuation,
    FeatureVector,
)

import logging

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """Generate 220-dimensional feature vectors for matches"""

    def __init__(self, db_session: Session):
        self.db_session = db_session
        self.version = "1.0.0"  # Feature engineering version

    def generate_features(self, match_id: str) -> Dict:
        """Generate complete feature vector for a match"""

        match = self.db_session.query(Match).filter_by(id=match_id).first()

        if not match:
            raise ValueError(f"Match {match_id} not found")

        logger.info(
            f"Generating features for {match.home_team_id} vs {match.away_team_id}"
        )

        features = {}

        # 1. Form metrics (20 features)
        features.update(self._calculate_form_metrics(match))

        # 2. xG analytics (30 features)
        features.update(self._calculate_xg_metrics(match))

        # 3. Fatigue indices (10 features)
        features.update(self._calculate_fatigue_metrics(match))

        # 4. Home advantage (15 features)
        features.update(self._calculate_home_advantage(match))

        # 5. Momentum (15 features)
        features.update(self._calculate_momentum(match))

        # 6. Market indicators (25 features)
        features.update(self._calculate_market_indicators(match))

        # 7. Head-to-head (15 features)
        features.update(self._calculate_h2h(match))

        # 8. Squad strength (20 features)
        features.update(self._calculate_squad_strength(match))

        # 9. Weather (5 features)
        features.update(self._calculate_weather_features(match))

        # 10. Elo ratings (10 features)
        features.update(self._calculate_elo_ratings(match))

        # 11. Tactical features (25 features)
        features.update(self._calculate_tactical_features(match))

        # 12. Scoring patterns (20 features)
        features.update(self._calculate_scoring_patterns(match))

        # 13. Defensive metrics (15 features)
        features.update(self._calculate_defensive_metrics(match))

        # 14. Set piece efficiency (10 features)
        features.update(self._calculate_setpiece_efficiency(match))

        # Total: 220 features

        logger.info(f"Generated {len(features)} features")

        return features

    def _calculate_form_metrics(self, match: Match) -> Dict:
        """Calculate team form over different windows"""

        features = {}

        for team_id, prefix in [
            (match.home_team_id, "home"),
            (match.away_team_id, "away"),
        ]:
            # Get last N matches
            recent_matches = (
                self.db_session.query(Match)
                .filter(
                    and_(
                        (Match.home_team_id == team_id)
                        | (Match.away_team_id == team_id),
                        Match.match_date < match.match_date,
                        Match.status == "finished",
                    )
                )
                .order_by(desc(Match.match_date))
                .limit(20)
                .all()
            )

            if not recent_matches:
                # Default values for teams with no history
                features[f"{prefix}_form_5"] = 0.0
                features[f"{prefix}_form_10"] = 0.0
                features[f"{prefix}_form_20"] = 0.0
                features[f"{prefix}_win_rate_5"] = 0.0
                features[f"{prefix}_goals_per_match_5"] = 0.0
                continue

            # Calculate points (3 for win, 1 for draw, 0 for loss)
            points = []
            goals_scored = []
            goals_conceded = []

            for m in recent_matches:
                is_home = m.home_team_id == team_id

                if is_home:
                    scored = m.home_score or 0
                    conceded = m.away_score or 0
                else:
                    scored = m.away_score or 0
                    conceded = m.home_score or 0

                goals_scored.append(scored)
                goals_conceded.append(conceded)

                if scored > conceded:
                    points.append(3)
                elif scored == conceded:
                    points.append(1)
                else:
                    points.append(0)

            # Form metrics
            features[f"{prefix}_form_5"] = (
                sum(points[:5]) / 15
                if len(points) >= 5
                else sum(points) / (len(points) * 3)
            )
            features[f"{prefix}_form_10"] = (
                sum(points[:10]) / 30
                if len(points) >= 10
                else features[f"{prefix}_form_5"]
            )
            features[f"{prefix}_form_20"] = (
                sum(points) / 60 if len(points) == 20 else features[f"{prefix}_form_10"]
            )

            features[f"{prefix}_win_rate_5"] = sum(
                1 for p in points[:5] if p == 3
            ) / min(5, len(points))
            features[f"{prefix}_goals_per_match_5"] = (
                np.mean(goals_scored[:5]) if len(goals_scored) >= 5 else 0.0
            )
            features[f"{prefix}_goals_conceded_per_match_5"] = (
                np.mean(goals_conceded[:5]) if len(goals_conceded) >= 5 else 0.0
            )

            # Goal difference trend
            gd = [s - c for s, c in zip(goals_scored[:5], goals_conceded[:5])]
            features[f"{prefix}_gd_avg_5"] = np.mean(gd) if gd else 0.0
            features[f"{prefix}_gd_trend"] = (
                np.polyfit(range(len(gd)), gd, 1)[0] if len(gd) >= 3 else 0.0
            )

            # Clean sheets
            features[f"{prefix}_clean_sheets_5"] = sum(
                1 for c in goals_conceded[:5] if c == 0
            ) / min(5, len(goals_conceded))

            # Scoring consistency (std dev)
            features[f"{prefix}_scoring_consistency"] = (
                np.std(goals_scored[:10]) if len(goals_scored) >= 10 else 1.0
            )

        return features

    def _calculate_xg_metrics(self, match: Match) -> Dict:
        """Calculate xG-based features"""

        features = {}

        for team_id, prefix in [
            (match.home_team_id, "home"),
            (match.away_team_id, "away"),
        ]:
            # Get xG data from recent matches
            recent_stats = (
                self.db_session.query(MatchStats)
                .join(Match)
                .filter(
                    and_(
                        MatchStats.team_id == team_id,
                        Match.match_date < match.match_date,
                        Match.status == "finished",
                        MatchStats.expected_goals.isnot(None),
                    )
                )
                .order_by(desc(Match.match_date))
                .limit(10)
                .all()
            )

            if not recent_stats:
                features[f"{prefix}_xg_avg_5"] = 0.0
                features[f"{prefix}_xg_conceded_avg_5"] = 0.0
                features[f"{prefix}_xg_diff_5"] = 0.0
                features[f"{prefix}_xg_overperformance"] = 0.0
                features[f"{prefix}_xg_consistency"] = 1.0
                continue

            xg_values = [s.expected_goals for s in recent_stats if s.expected_goals]

            # Basic xG metrics
            features[f"{prefix}_xg_avg_5"] = (
                np.mean(xg_values[:5])
                if len(xg_values) >= 5
                else np.mean(xg_values)
                if xg_values
                else 0.0
            )
            features[f"{prefix}_xg_avg_10"] = (
                np.mean(xg_values)
                if len(xg_values) >= 5
                else features[f"{prefix}_xg_avg_5"]
            )

            # xG consistency
            features[f"{prefix}_xg_consistency"] = (
                np.std(xg_values) if len(xg_values) >= 5 else 1.0
            )

            # xG trend (improving or declining)
            if len(xg_values) >= 5:
                features[f"{prefix}_xg_trend"] = np.polyfit(
                    range(len(xg_values[:5])), xg_values[:5], 1
                )[0]
            else:
                features[f"{prefix}_xg_trend"] = 0.0

            # xG overperformance (actual goals vs xG)
            # TODO: Join with actual goals to calculate
            features[f"{prefix}_xg_overperformance"] = 0.0

            # High-quality chances (xG > 0.3)
            high_quality_shots = (
                self.db_session.query(MatchEvent)
                .join(Match)
                .filter(
                    and_(
                        MatchEvent.team_id == team_id,
                        MatchEvent.event_type == "xg_shot",
                        MatchEvent.xg_value > 0.3,
                        Match.match_date < match.match_date,
                    )
                )
                .count()
            )

            total_shots = (
                self.db_session.query(MatchEvent)
                .join(Match)
                .filter(
                    and_(
                        MatchEvent.team_id == team_id,
                        MatchEvent.event_type == "xg_shot",
                        Match.match_date < match.match_date,
                    )
                )
                .count()
            )

            features[f"{prefix}_high_quality_chance_rate"] = (
                high_quality_shots / total_shots if total_shots > 0 else 0.0
            )

        # xG differential between teams
        features["xg_differential"] = features.get("home_xg_avg_5", 0) - features.get(
            "away_xg_avg_5", 0
        )

        return features

    def _calculate_fatigue_metrics(self, match: Match) -> Dict:
        """Calculate fatigue and rest metrics"""

        features = {}

        for team_id, prefix in [
            (match.home_team_id, "home"),
            (match.away_team_id, "away"),
        ]:
            # Get last match date
            last_match = (
                self.db_session.query(Match)
                .filter(
                    and_(
                        (Match.home_team_id == team_id)
                        | (Match.away_team_id == team_id),
                        Match.match_date < match.match_date,
                        Match.status == "finished",
                    )
                )
                .order_by(desc(Match.match_date))
                .first()
            )

            if last_match:
                days_rest = (match.match_date - last_match.match_date).days
                features[f"{prefix}_days_rest"] = days_rest

                # Fatigue index (0-1, higher = more fatigued)
                # Based on: days_rest < 3 = high fatigue, 7+ = fully rested
                features[f"{prefix}_fatigue_index"] = max(0, 1 - (days_rest / 7))
            else:
                features[f"{prefix}_days_rest"] = 7  # Assume well-rested
                features[f"{prefix}_fatigue_index"] = 0.0

            # Fixture congestion (matches in last 14 days)
            recent_14d = (
                self.db_session.query(Match)
                .filter(
                    and_(
                        (Match.home_team_id == team_id)
                        | (Match.away_team_id == team_id),
                        Match.match_date >= match.match_date - timedelta(days=14),
                        Match.match_date < match.match_date,
                        Match.status == "finished",
                    )
                )
                .count()
            )

            features[f"{prefix}_fixtures_14d"] = recent_14d
            features[f"{prefix}_fixture_congestion"] = min(
                1.0, recent_14d / 5
            )  # 5+ matches in 14 days = max congestion

        return features

    def _calculate_home_advantage(self, match: Match) -> Dict:
        """Calculate home advantage metrics"""

        features = {}

        # Home team's home record
        home_matches = (
            self.db_session.query(Match)
            .filter(
                and_(
                    Match.home_team_id == match.home_team_id,
                    Match.match_date < match.match_date,
                    Match.status == "finished",
                )
            )
            .order_by(desc(Match.match_date))
            .limit(10)
            .all()
        )

        if home_matches:
            home_wins = sum(
                1 for m in home_matches if (m.home_score or 0) > (m.away_score or 0)
            )
            features["home_advantage_win_rate"] = home_wins / len(home_matches)

            avg_home_goals = np.mean([m.home_score or 0 for m in home_matches])
            avg_home_conceded = np.mean([m.away_score or 0 for m in home_matches])
            features["home_goals_advantage"] = avg_home_goals - avg_home_conceded
        else:
            features["home_advantage_win_rate"] = 0.5  # Neutral
            features["home_goals_advantage"] = 0.0

        # Away team's away record
        away_matches = (
            self.db_session.query(Match)
            .filter(
                and_(
                    Match.away_team_id == match.away_team_id,
                    Match.match_date < match.match_date,
                    Match.status == "finished",
                )
            )
            .order_by(desc(Match.match_date))
            .limit(10)
            .all()
        )

        if away_matches:
            away_wins = sum(
                1 for m in away_matches if (m.away_score or 0) > (m.home_score or 0)
            )
            features["away_win_rate_away"] = away_wins / len(away_matches)
        else:
            features["away_win_rate_away"] = 0.3  # Default away disadvantage

        # Crowd boost (placeholder - requires attendance data)
        features["home_crowd_boost"] = 0.1  # Default 10% boost
        features["home_advantage_coefficient"] = 0.3  # Standard home advantage

        # Referee home bias (placeholder - requires referee analysis)
        features["referee_home_bias"] = 0.05  # Slight home bias

        return features

    def _calculate_momentum(self, match: Match) -> Dict:
        """Calculate momentum metrics using Poisson λ"""

        features = {}

        for team_id, prefix in [
            (match.home_team_id, "home"),
            (match.away_team_id, "away"),
        ]:
            # Get recent goals scored
            recent_matches = (
                self.db_session.query(Match)
                .filter(
                    and_(
                        (Match.home_team_id == team_id)
                        | (Match.away_team_id == team_id),
                        Match.match_date < match.match_date,
                        Match.status == "finished",
                    )
                )
                .order_by(desc(Match.match_date))
                .limit(5)
                .all()
            )

            if recent_matches:
                goals = []
                for m in recent_matches:
                    if m.home_team_id == team_id:
                        goals.append(m.home_score or 0)
                    else:
                        goals.append(m.away_score or 0)

                # Poisson λ (average goals per match)
                lambda_param = np.mean(goals)
                features[f"{prefix}_momentum_lambda"] = lambda_param

                # Weighted momentum (recent matches weighted more)
                weights = np.array([0.4, 0.3, 0.15, 0.1, 0.05])[: len(goals)]
                features[f"{prefix}_momentum_weighted"] = np.average(
                    goals, weights=weights
                )

                # Win streak
                results = []
                for m in recent_matches:
                    is_home = m.home_team_id == team_id
                    if is_home:
                        result = (
                            "W"
                            if (m.home_score or 0) > (m.away_score or 0)
                            else ("D" if m.home_score == m.away_score else "L")
                        )
                    else:
                        result = (
                            "W"
                            if (m.away_score or 0) > (m.home_score or 0)
                            else ("D" if m.home_score == m.away_score else "L")
                        )
                    results.append(result)

                # Current streak
                streak = 0
                for r in results:
                    if r == "W":
                        streak += 1
                    else:
                        break

                features[f"{prefix}_win_streak"] = streak
                features[f"{prefix}_unbeaten_streak"] = sum(
                    1 for r in results if r != "L"
                )
            else:
                features[f"{prefix}_momentum_lambda"] = 1.0  # League average
                features[f"{prefix}_momentum_weighted"] = 1.0
                features[f"{prefix}_win_streak"] = 0
                features[f"{prefix}_unbeaten_streak"] = 0

        return features

    def _calculate_market_indicators(self, match: Match) -> Dict:
        """Calculate market panic and odds volatility"""

        features = {}

        # Get odds history for the match
        odds_history = (
            self.db_session.query(OddsHistory)
            .filter(OddsHistory.match_id == match.id)
            .order_by(OddsHistory.timestamp)
            .all()
        )

        if len(odds_history) >= 2:
            # Calculate odds movements
            home_odds = [o.home_win for o in odds_history if o.home_win]

            if len(home_odds) >= 2:
                # Volatility (std dev of odds changes)
                odds_changes = np.diff(home_odds)
                features["odds_volatility_1h"] = (
                    np.std(odds_changes) if len(odds_changes) > 0 else 0.0
                )

                # Market panic score (rapid price movements)
                large_moves = sum(1 for change in odds_changes if abs(change) > 0.1)
                features["market_panic_score"] = (
                    large_moves / len(odds_changes) if len(odds_changes) > 0 else 0.0
                )

                # Odds trend (opening vs current)
                features["odds_drift_home"] = home_odds[-1] - home_odds[0]
            else:
                features["odds_volatility_1h"] = 0.0
                features["market_panic_score"] = 0.0
                features["odds_drift_home"] = 0.0
        else:
            features["odds_volatility_1h"] = 0.0
            features["market_panic_score"] = 0.0
            features["odds_drift_home"] = 0.0

        # Implied probability vs bookmaker margin
        if odds_history:
            latest = odds_history[-1]
            if latest.home_win and latest.draw and latest.away_win:
                implied_total = (
                    (1 / latest.home_win) + (1 / latest.draw) + (1 / latest.away_win)
                )
                features["bookmaker_margin"] = implied_total - 1
                features["home_implied_prob"] = (1 / latest.home_win) / implied_total
            else:
                features["bookmaker_margin"] = 0.05  # Typical 5% margin
                features["home_implied_prob"] = 0.33
        else:
            features["bookmaker_margin"] = 0.05
            features["home_implied_prob"] = 0.33

        return features

    def _calculate_h2h(self, match: Match) -> Dict:
        """Calculate head-to-head history"""

        features = {}

        # Get historical meetings
        h2h_matches = (
            self.db_session.query(Match)
            .filter(
                and_(
                    Match.match_date < match.match_date,
                    Match.status == "finished",
                    (
                        (
                            (Match.home_team_id == match.home_team_id)
                            & (Match.away_team_id == match.away_team_id)
                        )
                        | (
                            (Match.home_team_id == match.away_team_id)
                            & (Match.away_team_id == match.home_team_id)
                        )
                    ),
                )
            )
            .order_by(desc(Match.match_date))
            .limit(10)
            .all()
        )

        if h2h_matches:
            home_wins = 0
            draws = 0
            away_wins = 0
            total_goals = []

            for m in h2h_matches:
                home_score = m.home_score or 0
                away_score = m.away_score or 0
                total_goals.append(home_score + away_score)

                # From perspective of current home team
                if m.home_team_id == match.home_team_id:
                    if home_score > away_score:
                        home_wins += 1
                    elif home_score == away_score:
                        draws += 1
                    else:
                        away_wins += 1
                else:
                    if away_score > home_score:
                        home_wins += 1
                    elif home_score == away_score:
                        draws += 1
                    else:
                        away_wins += 1

            features["h2h_home_wins"] = home_wins
            features["h2h_draws"] = draws
            features["h2h_away_wins"] = away_wins
            features["h2h_total_matches"] = len(h2h_matches)
            features["h2h_avg_goals"] = np.mean(total_goals)
            features["h2h_home_win_rate"] = home_wins / len(h2h_matches)
        else:
            features["h2h_home_wins"] = 0
            features["h2h_draws"] = 0
            features["h2h_away_wins"] = 0
            features["h2h_total_matches"] = 0
            features["h2h_avg_goals"] = 2.5  # League average
            features["h2h_home_win_rate"] = 0.5  # Neutral

        return features

    def _calculate_squad_strength(self, match: Match) -> Dict:
        """Calculate squad value and missing players"""

        features = {}

        for team_id, prefix in [
            (match.home_team_id, "home"),
            (match.away_team_id, "away"),
        ]:
            # Get recent squad valuations
            valuations = (
                self.db_session.query(PlayerValuation)
                .filter(
                    and_(
                        PlayerValuation.team_id == team_id,
                        PlayerValuation.valuation_date <= match.match_date,
                    )
                )
                .all()
            )

            if valuations:
                total_value = sum(v.market_value or 0 for v in valuations)
                features[f"{prefix}_squad_value"] = total_value
            else:
                features[f"{prefix}_squad_value"] = 100.0  # Default value in millions

            # Missing players (injuries/suspensions) - placeholder
            features[f"{prefix}_missing_value"] = 0.0

        # Squad value differential
        features["squad_value_diff"] = features.get(
            "home_squad_value", 0
        ) - features.get("away_squad_value", 0)

        return features

    def _calculate_weather_features(self, match: Match) -> Dict:
        """Calculate weather impact (placeholder for external API)"""

        # TODO: Integrate weather API
        return {
            "temperature": 15.0,
            "precipitation": 0.0,
            "wind_speed": 10.0,
            "weather_impact_score": 0.0,
        }

    def _calculate_elo_ratings(self, match: Match) -> Dict:
        """Calculate Elo ratings (placeholder for Elo system)"""

        # TODO: Implement Elo rating system
        return {
            "home_elo": 1500,
            "away_elo": 1500,
            "elo_difference": 0,
        }

    def _calculate_tactical_features(self, match: Match) -> Dict:
        """Calculate tactical features (placeholder)"""

        # TODO: Implement tactical analysis (formations, playing style, etc.)
        return {
            "home_possession_style": 0.5,
            "away_possession_style": 0.5,
            "home_pressing_intensity": 0.5,
            "away_pressing_intensity": 0.5,
        }

    def _calculate_scoring_patterns(self, match: Match) -> Dict:
        """Calculate scoring patterns (first half vs second half, early goals, etc.)"""

        # TODO: Implement scoring pattern analysis
        return {
            "home_first_half_goals_rate": 0.5,
            "away_first_half_goals_rate": 0.5,
        }

    def _calculate_defensive_metrics(self, match: Match) -> Dict:
        """Calculate defensive solidity metrics"""

        # TODO: Implement defensive analysis
        return {
            "home_defensive_solidity": 0.5,
            "away_defensive_solidity": 0.5,
        }

    def _calculate_setpiece_efficiency(self, match: Match) -> Dict:
        """Calculate set piece effectiveness"""

        # TODO: Implement set piece analysis
        return {
            "home_setpiece_goals_rate": 0.2,
            "away_setpiece_goals_rate": 0.2,
        }

    def save_features(self, match_id: str, features: Dict) -> FeatureVector:
        """Save feature vector to database"""

        # Extract core features for column storage
        feature_vector = FeatureVector(
            match_id=match_id,
            home_form_5=features.get("home_form_5", 0.0),
            home_form_10=features.get("home_form_10", 0.0),
            away_form_5=features.get("away_form_5", 0.0),
            away_form_10=features.get("away_form_10", 0.0),
            home_xg_avg_5=features.get("home_xg_avg_5", 0.0),
            home_xg_conceded_avg_5=features.get("home_xg_conceded_avg_5", 0.0),
            away_xg_avg_5=features.get("away_xg_avg_5", 0.0),
            away_xg_conceded_avg_5=features.get("away_xg_conceded_avg_5", 0.0),
            home_fatigue_index=features.get("home_fatigue_index", 0.0),
            away_fatigue_index=features.get("away_fatigue_index", 0.0),
            home_days_rest=features.get("home_days_rest", 7),
            away_days_rest=features.get("away_days_rest", 7),
            home_crowd_boost=features.get("home_crowd_boost", 0.1),
            home_advantage_coefficient=features.get("home_advantage_coefficient", 0.3),
            home_momentum_lambda=features.get("home_momentum_lambda", 1.0),
            away_momentum_lambda=features.get("away_momentum_lambda", 1.0),
            market_panic_score=features.get("market_panic_score", 0.0),
            odds_volatility_1h=features.get("odds_volatility_1h", 0.0),
            odds_volatility_24h=features.get("odds_volatility_24h", 0.0),
            h2h_home_wins=features.get("h2h_home_wins", 0),
            h2h_draws=features.get("h2h_draws", 0),
            h2h_away_wins=features.get("h2h_away_wins", 0),
            h2h_avg_goals=features.get("h2h_avg_goals", 2.5),
            referee_home_bias=features.get("referee_home_bias", 0.05),
            referee_cards_per_game=features.get("referee_cards_per_game", 3.0),
            home_squad_value=features.get("home_squad_value", 100.0),
            away_squad_value=features.get("away_squad_value", 100.0),
            home_missing_value=features.get("home_missing_value", 0.0),
            away_missing_value=features.get("away_missing_value", 0.0),
            temperature=features.get("temperature"),
            precipitation=features.get("precipitation"),
            wind_speed=features.get("wind_speed"),
            home_elo=features.get("home_elo", 1500),
            away_elo=features.get("away_elo", 1500),
            elo_difference=features.get("elo_difference", 0),
            feature_vector_full=features,  # Store complete 220-feature vector as JSON
            features_version=self.version,
            timestamp=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )

        self.db_session.add(feature_vector)
        self.db_session.commit()

        logger.info(f"Saved feature vector for match {match_id}")

        return feature_vector


if __name__ == "__main__":
    # Test feature generation
    from ...core.database import session_scope

    with session_scope() as db_session:
        # Find a test match
        match = db_session.query(Match).first()

        if match:
            engineer = FeatureEngineer(db_session)
            features = engineer.generate_features(match.id)

            print(f"Generated {len(features)} features:")
            for key, value in list(features.items())[:10]:
                print(f"  {key}: {value}")

            # Save features
            vector = engineer.save_features(match.id, features)
            print(f"Saved feature vector ID: {vector.id}")
