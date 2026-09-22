"""
Live Platt Calibration Loop
Real-time probability calibration using Platt scaling with 180-second updates

This module provides continuous model calibration based on recent match outcomes
to adjust predicted probabilities in real-time.
"""

import asyncio
import logging
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression
import redis.asyncio as redis

logger = logging.getLogger(__name__)


class PlattCalibrator:
    """Real-time Platt scaling calibration for probability adjustment"""

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        calibration_window_hours: int = 24,
        min_samples: int = 30,
    ):
        """Initialize Platt calibrator

        Args:
            redis_client: Redis client for storing live predictions/outcomes
            calibration_window_hours: Time window for calibration data (default 24h)
            min_samples: Minimum samples required for calibration (default 30)
        """
        self.redis_client = redis_client
        self.calibration_window = timedelta(hours=calibration_window_hours)
        self.min_samples = min_samples

        # Platt scaling parameters (a, b in sigmoid: 1 / (1 + exp(a*x + b)))
        self.platt_a = 1.0
        self.platt_b = 0.0

        # Isotonic calibrator as alternative
        self.isotonic = None

        self.last_calibration = None
        self.calibration_metrics = {}

    async def calibrate_loop(self, interval_seconds: int = 180):
        """Run continuous calibration loop with circuit breaker and async optimization

        Args:
            interval_seconds: Calibration interval in seconds (default 180s)
        """
        logger.info(f"Starting Platt calibration loop (interval: {interval_seconds}s)")

        # Circuit breaker state
        failure_count = 0
        circuit_open = False
        circuit_reset_time = 300  # 5 minutes
        last_failure_time = None

        while True:
            try:
                # Check circuit breaker
                if circuit_open:
                    elapsed = (
                        datetime.now(timezone.utc) - last_failure_time
                    ).total_seconds()
                    if elapsed >= circuit_reset_time:
                        circuit_open = False
                        failure_count = 0
                        logger.info("Circuit breaker CLOSED - resuming calibration")
                    else:
                        await asyncio.sleep(interval_seconds)
                        continue

                # Perform calibration with timeout
                await asyncio.wait_for(
                    self.perform_calibration(),
                    timeout=30.0,  # 30 second timeout
                )

                # Reset failure count on success
                failure_count = max(0, failure_count - 1)

                await asyncio.sleep(interval_seconds)

            except asyncio.TimeoutError:
                logger.error("Calibration timeout - circuit breaker triggered")
                failure_count += 1

                if failure_count >= 3:
                    circuit_open = True
                    last_failure_time = datetime.now(timezone.utc)
                    logger.warning("Circuit breaker OPENED due to repeated failures")

                await asyncio.sleep(interval_seconds)

            except asyncio.CancelledError:
                logger.info("Calibration loop cancelled")
                break

            except Exception as e:
                logger.error(f"Calibration loop error: {e}", exc_info=True)
                failure_count += 1

                if failure_count >= 3:
                    circuit_open = True
                    last_failure_time = datetime.now(timezone.utc)

                await asyncio.sleep(interval_seconds)

    async def perform_calibration(self) -> bool:
        """Perform single calibration update with async optimization

        Returns:
            True if calibration successful, False otherwise
        """
        try:
            # Fetch recent predictions and outcomes from Redis (async + parallel)
            predictions, outcomes = await self._fetch_recent_data_async()

            if len(predictions) < self.min_samples:
                logger.warning(
                    f"Insufficient samples for calibration: {len(predictions)} < {self.min_samples}"
                )
                return False

            # Run CPU-intensive calibration in thread pool (non-blocking)
            loop = asyncio.get_event_loop()

            # Fit Platt scaling (async)
            await loop.run_in_executor(
                None, self._fit_platt_scaling, predictions, outcomes
            )

            # Optionally fit isotonic regression (async, parallel)
            if len(predictions) >= 50:
                await loop.run_in_executor(
                    None, self._fit_isotonic_regression, predictions, outcomes
                )

            # Store calibration parameters in Redis (async)
            await self._store_calibration_params()

            # Calculate calibration metrics (async)
            await loop.run_in_executor(
                None, self._calculate_calibration_metrics, predictions, outcomes
            )

            self.last_calibration = datetime.now(timezone.utc)
            logger.info(
                f"Calibration complete: a={self.platt_a:.4f}, b={self.platt_b:.4f}"
            )

            return True

            return True

        except Exception as e:
            logger.error(f"Calibration failed: {e}", exc_info=True)
            return False

    def _fit_platt_scaling(self, predictions: np.ndarray, outcomes: np.ndarray):
        """Fit Platt scaling parameters using logistic regression

        Platt scaling: calibrated_prob = 1 / (1 + exp(a * raw_prob + b))
        """
        try:
            # Convert probabilities to log-odds
            epsilon = 1e-10
            predictions = np.clip(predictions, epsilon, 1 - epsilon)
            log_odds = np.log(predictions / (1 - predictions))

            # Fit logistic regression
            lr = LogisticRegression(C=1e10, solver="lbfgs")
            lr.fit(log_odds.reshape(-1, 1), outcomes)

            # Extract Platt parameters
            self.platt_a = float(lr.coef_[0][0])
            self.platt_b = float(lr.intercept_[0])

        except Exception as e:
            logger.error(f"Platt scaling fit failed: {e}")
            # Keep previous parameters
            pass

    def _fit_isotonic_regression(self, predictions: np.ndarray, outcomes: np.ndarray):
        """Fit isotonic regression as alternative calibrator"""
        try:
            iso = IsotonicRegression(out_of_bounds="clip")
            iso.fit(predictions, outcomes)
            self.isotonic = iso
            logger.info("Isotonic regression calibration fitted")
        except Exception as e:
            logger.error(f"Isotonic regression fit failed: {e}")

    def calibrate_probability(
        self, raw_probability: float, method: str = "platt"
    ) -> float:
        """Apply calibration to raw model probability

        Args:
            raw_probability: Uncalibrated probability from model
            method: Calibration method ("platt" or "isotonic")

        Returns:
            Calibrated probability
        """
        try:
            if method == "isotonic" and self.isotonic is not None:
                return float(self.isotonic.predict([raw_probability])[0])

            # Platt scaling (default)
            epsilon = 1e-10
            raw_probability = np.clip(raw_probability, epsilon, 1 - epsilon)
            log_odds = np.log(raw_probability / (1 - raw_probability))

            calibrated_log_odds = self.platt_a * log_odds + self.platt_b
            calibrated_prob = 1.0 / (1.0 + np.exp(-calibrated_log_odds))

            return float(np.clip(calibrated_prob, 0.01, 0.99))

        except Exception as e:
            logger.error(f"Calibration application failed: {e}")
            return raw_probability

    async def _fetch_recent_data_async(self) -> Tuple[np.ndarray, np.ndarray]:
        """Fetch recent predictions and outcomes from Redis with async optimization

        Returns:
            Tuple of (predictions, outcomes) as numpy arrays
        """
        if not self.redis_client:
            # Return mock data for testing
            return self._generate_mock_data()

        try:
            # Fetch live prediction keys from last N hours (async)
            cutoff_time = datetime.now(timezone.utc) - self.calibration_window
            cutoff_timestamp = cutoff_time.timestamp()

            # Use Redis SCAN for efficient key iteration (non-blocking)
            predictions = []
            outcomes = []

            # Scan for prediction keys in batches
            cursor = 0
            batch_size = 100

            while True:
                cursor, keys = await self.redis_client.scan(
                    cursor=cursor, match="live_prediction:*", count=batch_size
                )

                if keys:
                    # Fetch values in parallel using pipeline
                    pipe = self.redis_client.pipeline()
                    for key in keys:
                        pipe.hgetall(key)

                    results = await pipe.execute()

                    # Process results
                    for result in results:
                        if result:
                            timestamp = float(result.get(b"timestamp", 0))

                            if timestamp >= cutoff_timestamp:
                                pred = float(result.get(b"prediction", 0))
                                outcome = float(result.get(b"outcome", -1))

                                # Only include matches with known outcomes
                                if outcome >= 0:
                                    predictions.append(pred)
                                    outcomes.append(outcome)

                if cursor == 0:
                    break

            if not predictions:
                logger.warning("No recent prediction data found")
                return np.array([]), np.array([])

            return np.array(predictions), np.array(outcomes)

        except Exception as e:
            logger.error(f"Failed to fetch recent data: {e}")
            return np.array([]), np.array([])

    async def _fetch_recent_data(self) -> Tuple[np.ndarray, np.ndarray]:
        """Legacy method - redirects to async version"""
        return await self._fetch_recent_data_async()

    def _generate_mock_data(self) -> Tuple[np.ndarray, np.ndarray]:
        """Generate mock calibration data for testing"""
        np.random.seed(42)
        n_samples = 100

        # Generate predictions with some miscalibration
        predictions = np.random.beta(2, 2, n_samples)

        # Generate outcomes (biased to test calibration)
        outcomes = (predictions + np.random.normal(0, 0.2, n_samples)) > 0.5
        outcomes = outcomes.astype(int)

        return predictions, outcomes

    async def _store_calibration_params(self):
        """Store calibration parameters in Redis"""
        if not self.redis_client:
            return

        try:
            await self.redis_client.hset(
                "calibration:params",
                mapping={
                    "platt_a": str(self.platt_a),
                    "platt_b": str(self.platt_b),
                    "last_update": datetime.now(timezone.utc).isoformat(),
                },
            )

            # Set 1-hour expiry
            await self.redis_client.expire("calibration:params", 3600)

        except Exception as e:
            logger.error(f"Error storing calibration params: {e}")

    def _calculate_calibration_metrics(
        self, predictions: np.ndarray, outcomes: np.ndarray
    ):
        """Calculate calibration quality metrics"""
        try:
            # Calibrate predictions
            calibrated = np.array([self.calibrate_probability(p) for p in predictions])

            # Brier score (lower is better)
            brier_raw = np.mean((predictions - outcomes) ** 2)
            brier_calibrated = np.mean((calibrated - outcomes) ** 2)

            # Log loss (lower is better)
            epsilon = 1e-10
            log_loss_raw = -np.mean(
                outcomes * np.log(predictions + epsilon)
                + (1 - outcomes) * np.log(1 - predictions + epsilon)
            )
            log_loss_calibrated = -np.mean(
                outcomes * np.log(calibrated + epsilon)
                + (1 - outcomes) * np.log(1 - calibrated + epsilon)
            )

            self.calibration_metrics = {
                "n_samples": len(predictions),
                "brier_raw": float(brier_raw),
                "brier_calibrated": float(brier_calibrated),
                "brier_improvement": float(brier_raw - brier_calibrated),
                "log_loss_raw": float(log_loss_raw),
                "log_loss_calibrated": float(log_loss_calibrated),
                "log_loss_improvement": float(log_loss_raw - log_loss_calibrated),
            }

            logger.info(
                f"Calibration metrics: Brier {brier_calibrated:.4f} "
                f"(improvement: {self.calibration_metrics['brier_improvement']:+.4f})"
            )

        except Exception as e:
            logger.error(f"Error calculating calibration metrics: {e}")

    def get_metrics(self) -> Dict:
        """Get current calibration metrics"""
        return {
            "platt_a": self.platt_a,
            "platt_b": self.platt_b,
            "last_calibration": self.last_calibration.isoformat()
            if self.last_calibration
            else None,
            "metrics": self.calibration_metrics,
        }


async def main():
    """Test calibration loop"""
    calibrator = PlattCalibrator()

    # Perform single calibration
    success = await calibrator.perform_calibration()
    print(f"Calibration success: {success}")
    print(f"Metrics: {calibrator.get_metrics()}")

    # Test probability calibration
    raw_prob = 0.65
    calibrated_prob = calibrator.calibrate_probability(raw_prob)
    print(f"Raw: {raw_prob:.3f} → Calibrated: {calibrated_prob:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
