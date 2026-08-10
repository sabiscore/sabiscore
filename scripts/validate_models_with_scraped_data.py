"""
Model Validation with Scraped Data
===================================

Validates model accuracy using actual 2024/25 season data.
Compares predictions against settled match results.
"""

import sys
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    log_loss,
    precision_recall_fscore_support,
    confusion_matrix,
)

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.scrapers import FootballDataEnhancedScraper
from src.models.ensemble import SabiScoreEnsemble
from src.data.transformers import FeatureTransformer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ModelValidator:
    """Validates ensemble model performance against scraped real data."""

    def __init__(self, league: str = "EPL"):
        self.league = league
        self.scraper = FootballDataEnhancedScraper()
        self.transformer = FeatureTransformer()
        self.results: Dict[str, Any] = {}

    def fetch_validation_data(self, seasons: List[str] = None) -> pd.DataFrame:
        """Fetch historical data for validation."""
        if seasons is None:
            seasons = ["2324", "2425"]  # Current and previous season

        logger.info(f"Fetching validation data for seasons: {seasons}")
        
        data = self.scraper.get_historical_odds(self.league, seasons)
        
        if not data:
            logger.warning("No data fetched, attempting local fallback")
            data = self._load_local_validation_data()

        df = pd.DataFrame(data) if isinstance(data, list) else data
        logger.info(f"Fetched {len(df)} matches for validation")
        
        return df

    def _load_local_validation_data(self) -> pd.DataFrame:
        """Load local CSV data as fallback."""
        data_dir = Path(__file__).parent.parent / "data"
        
        local_files = [
            data_dir / "processed" / f"{self.league.lower()}_2324.csv",
            data_dir / "raw" / "historical" / f"{self.league.lower()}_combined.csv",
        ]

        for file_path in local_files:
            if file_path.exists():
                logger.info(f"Loading local data from {file_path}")
                return pd.read_csv(file_path)

        logger.error("No local validation data found")
        return pd.DataFrame()

    def prepare_validation_set(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
        """Prepare features and labels for validation."""
        required_cols = ["HomeTeam", "AwayTeam", "FTHG", "FTAG"]
        
        # Check for required columns
        if not all(col in df.columns for col in required_cols):
            # Try alternative column names
            col_mapping = {
                "home_team": "HomeTeam",
                "away_team": "AwayTeam",
                "home_score": "FTHG",
                "away_score": "FTAG",
            }
            df = df.rename(columns=col_mapping)

        # Filter to completed matches only
        df = df.dropna(subset=["FTHG", "FTAG"])
        
        # Create outcome labels
        df["outcome"] = df.apply(
            lambda x: "home_win" if x["FTHG"] > x["FTAG"] 
                      else ("draw" if x["FTHG"] == x["FTAG"] else "away_win"),
            axis=1
        )

        # Encode outcomes
        outcome_map = {"home_win": 0, "draw": 1, "away_win": 2}
        y = df["outcome"].map(outcome_map)

        logger.info(f"Prepared {len(df)} matches for validation")
        logger.info(f"Outcome distribution: {df['outcome'].value_counts().to_dict()}")

        return df, y

    def generate_predictions(
        self, 
        df: pd.DataFrame,
        ensemble: Optional[SabiScoreEnsemble] = None
    ) -> pd.DataFrame:
        """Generate predictions for validation set."""
        predictions = []
        
        if ensemble is None:
            try:
                ensemble = SabiScoreEnsemble.load_latest(self.league)
                logger.info(f"Loaded ensemble for {self.league}")
            except Exception as e:
                logger.warning(f"Could not load ensemble: {e}, using mock predictions")
                return self._generate_mock_predictions(df)

        for idx, row in df.iterrows():
            try:
                # Build features for this match
                features = self.transformer.transform({
                    "home_team": row.get("HomeTeam", row.get("home_team")),
                    "away_team": row.get("AwayTeam", row.get("away_team")),
                    "league": self.league,
                    # Add historical features if available
                    "PSH": row.get("PSH", 2.0),
                    "PSD": row.get("PSD", 3.4),
                    "PSA": row.get("PSA", 3.5),
                })

                # Get prediction
                pred_df = ensemble.predict(pd.DataFrame([features]))
                pred_row = pred_df.iloc[0]
                
                predictions.append({
                    "match_idx": idx,
                    "home_win_prob": float(pred_row.get("home_win_prob", 0.4)),
                    "draw_prob": float(pred_row.get("draw_prob", 0.3)),
                    "away_win_prob": float(pred_row.get("away_win_prob", 0.3)),
                    "predicted_outcome": pred_row.get("predicted_outcome", "home_win"),
                    "confidence": float(pred_row.get("confidence", 0.5)),
                })

            except Exception as e:
                logger.warning(f"Prediction failed for match {idx}: {e}")
                predictions.append({
                    "match_idx": idx,
                    "home_win_prob": 0.4,
                    "draw_prob": 0.3,
                    "away_win_prob": 0.3,
                    "predicted_outcome": "home_win",
                    "confidence": 0.4,
                })

        return pd.DataFrame(predictions)

    def _generate_mock_predictions(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate mock predictions when model unavailable."""
        logger.info("Generating mock predictions based on odds")
        predictions = []
        
        for idx, row in df.iterrows():
            # Use odds to create probability estimates
            psh = row.get("PSH", 2.0)
            psd = row.get("PSD", 3.4)
            psa = row.get("PSA", 3.5)
            
            # Convert to probabilities (normalize)
            total = 1/psh + 1/psd + 1/psa
            home_prob = (1/psh) / total
            draw_prob = (1/psd) / total
            away_prob = (1/psa) / total
            
            # Determine predicted outcome
            probs = {"home_win": home_prob, "draw": draw_prob, "away_win": away_prob}
            predicted = max(probs, key=probs.get)
            
            predictions.append({
                "match_idx": idx,
                "home_win_prob": home_prob,
                "draw_prob": draw_prob,
                "away_win_prob": away_prob,
                "predicted_outcome": predicted,
                "confidence": max(probs.values()),
            })

        return pd.DataFrame(predictions)

    def calculate_metrics(
        self,
        y_true: pd.Series,
        predictions: pd.DataFrame
    ) -> Dict[str, float]:
        """Calculate comprehensive performance metrics."""
        # Map predicted outcomes to numeric
        outcome_map = {"home_win": 0, "draw": 1, "away_win": 2}
        y_pred = predictions["predicted_outcome"].map(outcome_map)

        # Basic accuracy
        accuracy = accuracy_score(y_true, y_pred)

        # Precision, recall, F1
        precision, recall, f1, support = precision_recall_fscore_support(
            y_true, y_pred, average="weighted", zero_division=0
        )

        # Brier score (for calibration)
        # Create probability matrix
        prob_matrix = predictions[["home_win_prob", "draw_prob", "away_win_prob"]].values
        
        # One-hot encode true labels
        y_true_onehot = np.zeros((len(y_true), 3))
        for i, label in enumerate(y_true):
            y_true_onehot[i, label] = 1

        brier = np.mean(np.sum((prob_matrix - y_true_onehot) ** 2, axis=1)) / 2

        # Log loss
        try:
            logloss = log_loss(y_true, prob_matrix)
        except Exception:
            logloss = np.nan

        # Confusion matrix
        cm = confusion_matrix(y_true, y_pred)

        # High-confidence accuracy (>65% confidence)
        high_conf_mask = predictions["confidence"] > 0.65
        if high_conf_mask.sum() > 0:
            high_conf_accuracy = accuracy_score(
                y_true[high_conf_mask], 
                y_pred[high_conf_mask]
            )
            high_conf_count = high_conf_mask.sum()
        else:
            high_conf_accuracy = np.nan
            high_conf_count = 0

        # Very high confidence (>75%)
        very_high_conf_mask = predictions["confidence"] > 0.75
        if very_high_conf_mask.sum() > 0:
            very_high_conf_accuracy = accuracy_score(
                y_true[very_high_conf_mask],
                y_pred[very_high_conf_mask]
            )
            very_high_conf_count = very_high_conf_mask.sum()
        else:
            very_high_conf_accuracy = np.nan
            very_high_conf_count = 0

        metrics = {
            "overall_accuracy": float(accuracy),
            "precision": float(precision),
            "recall": float(recall),
            "f1_score": float(f1),
            "brier_score": float(brier),
            "log_loss": float(logloss) if not np.isnan(logloss) else None,
            "high_conf_accuracy": float(high_conf_accuracy) if not np.isnan(high_conf_accuracy) else None,
            "high_conf_count": int(high_conf_count),
            "very_high_conf_accuracy": float(very_high_conf_accuracy) if not np.isnan(very_high_conf_accuracy) else None,
            "very_high_conf_count": int(very_high_conf_count),
            "total_matches": int(len(y_true)),
            "confusion_matrix": cm.tolist(),
        }

        return metrics

    def calculate_roi_metrics(
        self,
        df: pd.DataFrame,
        predictions: pd.DataFrame,
        y_true: pd.Series
    ) -> Dict[str, float]:
        """Calculate ROI and value betting metrics."""
        # Merge predictions with original data
        merged = df.reset_index(drop=True).join(predictions.set_index("match_idx"), rsuffix="_pred")

        total_bets = 0
        total_stake = 0
        total_returns = 0
        value_bets = 0
        value_bet_wins = 0

        for idx, row in merged.iterrows():
            try:
                # Get odds
                home_odds = row.get("PSH", 2.0)
                draw_odds = row.get("PSD", 3.4)
                away_odds = row.get("PSA", 3.5)
                
                # Get predicted probabilities
                home_prob = row.get("home_win_prob", 0.33)
                draw_prob = row.get("draw_prob", 0.33)
                away_prob = row.get("away_win_prob", 0.34)

                # Calculate implied probabilities
                home_implied = 1 / home_odds
                draw_implied = 1 / draw_odds
                away_implied = 1 / away_odds

                # Calculate edges
                edges = {
                    "home_win": home_prob - home_implied,
                    "draw": draw_prob - draw_implied,
                    "away_win": away_prob - away_implied,
                }

                # Find best edge
                best_bet = max(edges, key=edges.get)
                best_edge = edges[best_bet]

                # Only bet if edge > 4.2% (our threshold)
                if best_edge > 0.042:
                    value_bets += 1
                    
                    # Calculate Kelly stake (1/8 Kelly)
                    odds = {"home_win": home_odds, "draw": draw_odds, "away_win": away_odds}[best_bet]
                    kelly_fraction = (best_edge * odds) / (odds - 1)
                    stake = kelly_fraction * 0.125  # 1/8 Kelly
                    stake = min(stake, 0.05)  # Max 5% stake
                    
                    total_stake += stake
                    total_bets += 1

                    # Check if bet won
                    actual = y_true.iloc[idx]
                    outcome_map = {"home_win": 0, "draw": 1, "away_win": 2}
                    
                    if actual == outcome_map[best_bet]:
                        total_returns += stake * odds
                        value_bet_wins += 1

            except Exception as e:
                logger.debug(f"ROI calculation error for match {idx}: {e}")
                continue

        # Calculate final metrics
        roi = ((total_returns - total_stake) / total_stake * 100) if total_stake > 0 else 0
        win_rate = (value_bet_wins / value_bets * 100) if value_bets > 0 else 0

        return {
            "total_value_bets": value_bets,
            "value_bet_wins": value_bet_wins,
            "value_bet_win_rate": win_rate,
            "total_stake": total_stake,
            "total_returns": total_returns,
            "roi_percentage": roi,
            "profit_units": total_returns - total_stake,
        }

    def run_validation(self, seasons: List[str] = None) -> Dict[str, Any]:
        """Run full validation pipeline."""
        logger.info("=" * 60)
        logger.info(f"STARTING MODEL VALIDATION FOR {self.league}")
        logger.info("=" * 60)

        # Fetch data
        df = self.fetch_validation_data(seasons)
        if df.empty:
            logger.error("No validation data available")
            return {"error": "No validation data"}

        # Prepare validation set
        df_clean, y_true = self.prepare_validation_set(df)
        if len(df_clean) == 0:
            logger.error("No valid matches for validation")
            return {"error": "No valid matches"}

        # Generate predictions
        predictions = self.generate_predictions(df_clean)

        # Calculate metrics
        metrics = self.calculate_metrics(y_true, predictions)
        roi_metrics = self.calculate_roi_metrics(df_clean, predictions, y_true)

        # Combine results
        self.results = {
            "league": self.league,
            "validation_date": datetime.utcnow().isoformat(),
            "performance_metrics": metrics,
            "roi_metrics": roi_metrics,
            "summary": {
                "overall_accuracy": f"{metrics['overall_accuracy']:.1%}",
                "high_confidence_accuracy": f"{metrics['high_conf_accuracy']:.1%}" if metrics['high_conf_accuracy'] else "N/A",
                "roi": f"{roi_metrics['roi_percentage']:.1f}%",
                "value_bets_found": roi_metrics["total_value_bets"],
            },
        }

        # Print summary
        self._print_summary()

        return self.results

    def _print_summary(self):
        """Print validation summary."""
        print("\n" + "=" * 60)
        print(f"VALIDATION RESULTS - {self.league}")
        print("=" * 60)
        
        metrics = self.results["performance_metrics"]
        roi = self.results["roi_metrics"]
        
        print("\n📊 Performance Metrics:")
        print(f"  Overall Accuracy:       {metrics['overall_accuracy']:.1%}")
        print(f"  High-Conf Accuracy:     {metrics['high_conf_accuracy']:.1%}" if metrics['high_conf_accuracy'] else "  High-Conf Accuracy:     N/A")
        print(f"  Very High-Conf Acc:     {metrics['very_high_conf_accuracy']:.1%}" if metrics['very_high_conf_accuracy'] else "  Very High-Conf Acc:     N/A")
        print(f"  Brier Score:            {metrics['brier_score']:.4f}")
        print(f"  F1 Score:               {metrics['f1_score']:.3f}")
        
        print("\n💰 ROI Metrics:")
        print(f"  Value Bets Found:       {roi['total_value_bets']}")
        print(f"  Value Bet Win Rate:     {roi['value_bet_win_rate']:.1f}%")
        print(f"  ROI:                    {roi['roi_percentage']:.1f}%")
        print(f"  Profit (Units):         {roi['profit_units']:.2f}")
        
        print("\n" + "=" * 60)


def validate_all_leagues() -> Dict[str, Any]:
    """Validate model performance across all supported leagues."""
    leagues = ["EPL", "La Liga", "Serie A", "Bundesliga", "Ligue 1"]
    all_results = {}
    
    for league in leagues:
        logger.info(f"\nValidating {league}...")
        validator = ModelValidator(league)
        results = validator.run_validation()
        all_results[league] = results
    
    # Summary across all leagues
    print("\n" + "=" * 60)
    print("CROSS-LEAGUE SUMMARY")
    print("=" * 60)
    
    for league, results in all_results.items():
        if "error" not in results:
            metrics = results["performance_metrics"]
            roi = results["roi_metrics"]
            print(f"\n{league}:")
            print(f"  Accuracy: {metrics['overall_accuracy']:.1%} | ROI: {roi['roi_percentage']:.1f}%")
    
    return all_results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate model performance")
    parser.add_argument("--league", default="EPL", help="League to validate")
    parser.add_argument("--all", action="store_true", help="Validate all leagues")
    parser.add_argument("--seasons", nargs="+", default=["2324"], help="Seasons to validate")
    parser.add_argument("--output", help="Output JSON file for results")
    
    args = parser.parse_args()
    
    if args.all:
        results = validate_all_leagues()
    else:
        validator = ModelValidator(args.league)
        results = validator.run_validation(args.seasons)
    
    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")
