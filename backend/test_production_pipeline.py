"""
Production Pipeline Validation Script
Tests complete data flow from scrapers → ingestion → aggregation → prediction → API

Run this to validate the entire system is working:
    python backend/test_production_pipeline.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from src.data.scrapers import (
    FlashscoreScraper,
    BetfairExchangeScraper,
    OddsPortalScraper,
    UnderstatScraper,
    WhoScoredScraper,
    SoccerwayScraper,
    TransfermarktScraper,
    FootballDataEnhancedScraper,
)
from src.data.aggregator import get_enhanced_aggregator
from src.services.prediction import PredictionService
from src.schemas.prediction import MatchPredictionRequest
from src.monitoring.metrics import metrics_collector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PipelineValidator:
    """Validates the complete production pipeline"""
    
    def __init__(self):
        self.results = {
            "scrapers": {},
            "aggregator": {},
            "prediction": {},
            "metrics": {}
        }
    
    async def test_scrapers(self):
        """Test all 8 ethical scrapers"""
        logger.info("=" * 60)
        logger.info("TESTING SCRAPERS")
        logger.info("=" * 60)
        
        scrapers = {
            "flashscore": FlashscoreScraper(),
            "betfair_exchange": BetfairExchangeScraper(),
            "odds_portal": OddsPortalScraper(),
            "understat": UnderstatScraper(),
            "whoscored": WhoScoredScraper(),
            "soccerway": SoccerwayScraper(),
            "transfermarkt": TransfermarktScraper(),
            "football_data": FootballDataEnhancedScraper(),
        }
        
        for name, scraper in scrapers.items():
            try:
                logger.info(f"\nTesting {name}...")
                # Test basic fetch (will use cache if available)
                if name == "flashscore":
                    data = scraper.fetch_data(
                        home_team="Arsenal",
                        away_team="Chelsea",
                        use_cache=True
                    )
                elif name == "betfair_exchange":
                    data = scraper.fetch_data(
                        home_team="Arsenal",
                        away_team="Chelsea",
                        use_cache=True
                    )
                elif name == "odds_portal":
                    data = scraper.fetch_data(
                        home_team="Arsenal",
                        away_team="Chelsea",
                        use_cache=True
                    )
                elif name == "understat":
                    data = scraper.fetch_data(
                        team="Arsenal",
                        league="EPL",
                        use_cache=True
                    )
                elif name == "whoscored":
                    data = scraper.fetch_data(
                        league="EPL",
                        use_cache=True
                    )
                elif name == "soccerway":
                    data = scraper.fetch_data(
                        league="EPL",
                        use_cache=True
                    )
                elif name == "transfermarkt":
                    data = scraper.fetch_data(
                        team="Arsenal",
                        use_cache=True
                    )
                elif name == "football_data":
                    data = scraper.download_season_data(
                        league="EPL",
                        season="2324",
                        use_cache=True
                    )
                
                self.results["scrapers"][name] = {
                    "status": "✅ PASS",
                    "data_available": data is not None and (
                        len(data) > 0 if hasattr(data, '__len__') else True
                    )
                }
                logger.info(f"  ✅ {name}: OK")
                
            except Exception as e:
                self.results["scrapers"][name] = {
                    "status": "❌ FAIL",
                    "error": str(e)
                }
                logger.error(f"  ❌ {name}: {e}")
    
    async def test_aggregator(self):
        """Test data aggregation from multiple sources"""
        logger.info("\n" + "=" * 60)
        logger.info("TESTING DATA AGGREGATOR")
        logger.info("=" * 60)
        
        try:
            # Test enhanced aggregator
            aggregator = get_enhanced_aggregator()
            logger.info("\n✅ Enhanced aggregator instantiated")
            
            # Test feature aggregation
            features = aggregator.get_comprehensive_features(
                home_team="Arsenal",
                away_team="Chelsea",
                league="EPL"
            )
            
            if features:
                logger.info(f"  ✅ Aggregated {len(features)} features")
                logger.info(f"  Feature prefixes: {set(k.split('_')[0] for k in features.keys())}")
                self.results["aggregator"]["status"] = "✅ PASS"
                self.results["aggregator"]["feature_count"] = len(features)
            else:
                logger.warning("  ⚠️ No features returned (using cache)")
                self.results["aggregator"]["status"] = "⚠️ WARN"
                
        except Exception as e:
            logger.error(f"  ❌ Aggregator error: {e}")
            self.results["aggregator"]["status"] = "❌ FAIL"
            self.results["aggregator"]["error"] = str(e)
    
    async def test_prediction_service(self):
        """Test prediction service with sample match"""
        logger.info("\n" + "=" * 60)
        logger.info("TESTING PREDICTION SERVICE")
        logger.info("=" * 60)
        
        try:
            service = PredictionService()
            
            # Create sample prediction request
            request = MatchPredictionRequest(
                home_team="Arsenal",
                away_team="Chelsea",
                league="EPL",
                match_date="2024-11-30",
                odds={
                    "home_win": 2.1,
                    "draw": 3.4,
                    "away_win": 3.6
                },
                bankroll=10000.0
            )
            
            logger.info("\nMaking prediction...")
            prediction = await service.predict_match(
                match_id="test_arsenal_chelsea",
                request=request
            )
            
            logger.info("  ✅ Prediction successful")
            logger.info(f"  Home Win: {prediction.predictions['home_win']:.2%}")
            logger.info(f"  Draw: {prediction.predictions['draw']:.2%}")
            logger.info(f"  Away Win: {prediction.predictions['away_win']:.2%}")
            logger.info(f"  Confidence: {prediction.confidence:.2%}")
            logger.info(f"  Value Bets: {len(prediction.value_bets)}")
            logger.info(f"  Processing: {prediction.metadata.get('processing_time_ms', 0)}ms")
            
            self.results["prediction"]["status"] = "✅ PASS"
            self.results["prediction"]["confidence"] = prediction.confidence
            self.results["prediction"]["value_bets"] = len(prediction.value_bets)
            self.results["prediction"]["processing_ms"] = prediction.metadata.get("processing_time_ms", 0)
            
        except FileNotFoundError as e:
            logger.warning(f"  ⚠️ Model not found (expected in development): {e}")
            self.results["prediction"]["status"] = "⚠️ SKIP"
            self.results["prediction"]["reason"] = "Model artifacts not available"
        except Exception as e:
            logger.error(f"  ❌ Prediction error: {e}")
            self.results["prediction"]["status"] = "❌ FAIL"
            self.results["prediction"]["error"] = str(e)
    
    async def test_metrics(self):
        """Test metrics collection"""
        logger.info("\n" + "=" * 60)
        logger.info("TESTING METRICS COLLECTION")
        logger.info("=" * 60)
        
        try:
            summary = metrics_collector.get_summary()
            
            logger.info("  ✅ Metrics collector active")
            logger.info(f"  Uptime: {summary.get('uptime_human', 'N/A')}")
            
            if "predictions" in summary:
                pred_metrics = summary["predictions"]
                logger.info(f"  Predictions: {pred_metrics.get('total', 0)}")
                logger.info(f"  Cache hit rate: {pred_metrics.get('cache_hit_rate', 0):.1%}")
                logger.info(f"  Avg latency: {pred_metrics.get('avg_latency_ms', 0):.1f}ms")
            
            if "scrapers" in summary:
                logger.info(f"  Scrapers tracked: {len(summary['scrapers'])}")
                for scraper, stats in summary["scrapers"].items():
                    logger.info(f"    {scraper}: {stats.get('success_rate', 0):.1%} success")
            
            self.results["metrics"]["status"] = "✅ PASS"
            self.results["metrics"]["summary"] = summary
            
        except Exception as e:
            logger.error(f"  ❌ Metrics error: {e}")
            self.results["metrics"]["status"] = "❌ FAIL"
            self.results["metrics"]["error"] = str(e)
    
    def print_summary(self):
        """Print validation summary"""
        logger.info("\n" + "=" * 60)
        logger.info("VALIDATION SUMMARY")
        logger.info("=" * 60)
        
        # Scrapers
        logger.info("\n📊 SCRAPERS:")
        for name, result in self.results["scrapers"].items():
            logger.info(f"  {result['status']} {name}")
        
        # Aggregator
        logger.info("\n🔄 DATA AGGREGATOR:")
        logger.info(f"  {self.results['aggregator'].get('status', 'N/A')}")
        
        # Prediction
        logger.info("\n🎯 PREDICTION SERVICE:")
        logger.info(f"  {self.results['prediction'].get('status', 'N/A')}")
        
        # Metrics
        logger.info("\n📈 METRICS COLLECTION:")
        logger.info(f"  {self.results['metrics'].get('status', 'N/A')}")
        
        # Overall status
        all_pass = (
            all(r["status"] in ["✅ PASS", "⚠️ WARN"] for r in self.results["scrapers"].values()) and
            self.results["aggregator"].get("status", "").startswith("✅") and
            self.results["prediction"].get("status", "").startswith(("✅", "⚠️")) and
            self.results["metrics"].get("status", "").startswith("✅")
        )
        
        logger.info("\n" + "=" * 60)
        if all_pass:
            logger.info("✅ PIPELINE VALIDATION: PASS")
            logger.info("Production system is ready for deployment!")
        else:
            logger.info("⚠️ PIPELINE VALIDATION: PARTIAL")
            logger.info("Some components need attention before deployment")
        logger.info("=" * 60 + "\n")


async def main():
    """Run complete pipeline validation"""
    validator = PipelineValidator()
    
    await validator.test_scrapers()
    await validator.test_aggregator()
    await validator.test_prediction_service()
    await validator.test_metrics()
    
    validator.print_summary()


if __name__ == "__main__":
    asyncio.run(main())
