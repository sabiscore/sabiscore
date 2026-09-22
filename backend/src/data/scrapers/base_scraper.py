"""
Base Scraper Infrastructure for SabiScore
==========================================

Streamlined abstract base class for all scrapers with:
- Ethical rate limiting and delays
- robots.txt compliance checking
- User-agent rotation
- Local data fallback (raw/processed merge)
- Retry logic with exponential backoff
- Common parsing utilities
- Circuit breaker pattern

All scrapers inherit from this class for consistent, ethical scraping.
"""

import json
import logging
import os
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# Expanded user agents for better rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Edge/120.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
]

# Data directories
DATA_DIR = Path(
    os.environ.get("SABISCORE_DATA_DIR", Path(__file__).parents[4] / "data")
)
PROCESSED_DIR = DATA_DIR / "processed"
RAW_DIR = (
    DATA_DIR / "raw" if (DATA_DIR / "raw").exists() else DATA_DIR / "processed" / "raw"
)
CACHE_DIR = DATA_DIR / "cache"

# Ensure directories exist
for dir_path in [PROCESSED_DIR, CACHE_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Robots.txt helper
# ---------------------------------------------------------------------------


@lru_cache(maxsize=64)
def _fetch_robots_parser(base_url: str, user_agent: str) -> Optional[RobotFileParser]:
    """Retrieve and cache robots.txt parser for a given origin."""
    try:
        parsed = urlparse(base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp
    except Exception as exc:  # pragma: no cover
        logging.getLogger(__name__).debug(
            f"Could not fetch robots.txt for {base_url}: {exc}"
        )
        return None


class CircuitBreaker:
    """
    Circuit breaker to prevent repeated failures from overloading scrapers.

    States:
    - CLOSED: Normal operation, requests allowed
    - OPEN: Failures exceeded threshold, requests blocked
    - HALF_OPEN: Test state after timeout, one request allowed
    """

    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = "closed"

    def record_success(self) -> None:
        """Reset circuit breaker on success."""
        self.failures = 0
        self.state = "closed"

    def record_failure(self) -> None:
        """Record a failure and potentially open circuit."""
        self.failures += 1
        self.last_failure_time = datetime.now(timezone.utc)

        if self.failures >= self.failure_threshold:
            self.state = "open"
            logger.warning(
                f"Circuit breaker OPEN after {self.failures} failures. "
                f"Will retry after {self.timeout}s"
            )

    def can_attempt(self) -> bool:
        """Check if request can be attempted."""
        if self.state == "closed":
            return True

        if self.state == "open" and self.last_failure_time:
            elapsed = (
                datetime.now(timezone.utc) - self.last_failure_time
            ).total_seconds()
            if elapsed >= self.timeout:
                self.state = "half_open"
                logger.info("Circuit breaker entering HALF_OPEN state")
                return True

        return self.state == "half_open"


class BaseScraper(ABC):
    """
    Abstract base class for all SabiScore scrapers.

    Provides:
    - Session management with retry logic
    - Ethical rate limiting (configurable delays)
    - User-agent rotation
    - Local data fallback for reduced scraping load
    - Metrics collection
    - Circuit breaker protection

    Usage:
        class MyScraper(BaseScraper):
            def __init__(self):
                super().__init__("https://example.com")
                self.local_raw_path = PROCESSED_DIR / "my_raw.csv"
                self.local_processed_path = PROCESSED_DIR / "my_processed.json"

            def _fetch_remote(self, *args, **kwargs):
                # Implement remote fetching
                pass

            def _parse_data(self, page_content):
                # Implement parsing
                pass
    """

    def __init__(
        self,
        base_url: str,
        rate_limit_delay: float = 3.0,
        max_retries: int = 3,
        timeout: int = 30,
        respect_robots: bool = True,
    ):
        self.base_url = base_url
        self.rate_limit_delay = rate_limit_delay
        self.max_retries = max_retries
        self.timeout = timeout
        self.respect_robots = respect_robots

        # Local data paths (subclasses override)
        self.local_raw_path: Optional[Path] = None
        self.local_processed_path: Optional[Path] = None

        # Session setup
        self.session = self._create_session()
        self.last_request_time = 0.0

        # Circuit breaker
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, timeout=60)

        # Metrics
        self.metrics = {
            "requests_total": 0,
            "requests_success": 0,
            "requests_failed": 0,
            "requests_blocked_robots": 0,
            "cache_hits": 0,
            "retries_total": 0,
        }

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry strategy."""
        session = requests.Session()

        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            raise_on_status=False,
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # Default headers
        session.headers.update(self._get_headers())

        return session

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with random user agent."""
        return {
            "User-Agent": self._get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    def _get_random_user_agent(self) -> str:
        """Return a randomized desktop user agent."""
        return random.choice(USER_AGENTS)

    # ------------------------------------------------------------------
    # Robots.txt compliance
    # ------------------------------------------------------------------

    def _is_allowed_by_robots(self, url: str) -> bool:
        """Return True if the URL is allowed per robots.txt (or if disabled)."""
        if not self.respect_robots:
            return True
        user_agent = self.session.headers.get("User-Agent", "*")
        rp = _fetch_robots_parser(self.base_url, user_agent)
        if rp is None:
            # Hardened: fail closed when robots.txt cannot be fetched
            logger.warning(
                "robots.txt unavailable for %s; blocking %s", self.base_url, url
            )
            self.metrics["requests_blocked_robots"] += 1
            return False
        allowed = rp.can_fetch(user_agent, url)
        if not allowed:
            self.metrics["requests_blocked_robots"] += 1
        return allowed

    def _rate_limit(self) -> None:
        """Enforce ethical rate limiting between requests."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            sleep_time = self.rate_limit_delay - elapsed
            # Add jitter for more natural timing
            jitter = random.random() * 0.5 * self.rate_limit_delay
            total_sleep = sleep_time + jitter
            logger.debug(f"Rate limiting: sleeping {total_sleep:.2f}s")
            time.sleep(total_sleep)
        self.last_request_time = time.time()

    def _wait_rate_limit(self) -> None:
        """Public helper for enforcing the internal rate limit."""
        self._rate_limit()

    def get_page(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        method: str = "GET",
        **kwargs,
    ) -> Optional[str]:
        """Utility to fetch a page respecting rate limits, circuit breaker, and robots.txt."""
        if not self.circuit_breaker.can_attempt():
            logger.warning("Circuit breaker OPEN - skipping remote request")
            return None

        # Robots.txt check
        if not self._is_allowed_by_robots(url):
            logger.info(f"Blocked by robots.txt: {url}")
            self.metrics["requests_blocked_robots"] += 1
            return None

        headers = kwargs.pop("headers", self._get_headers())

        try:
            self.metrics["requests_total"] += 1
            self._wait_rate_limit()
            response = self.session.request(
                method.upper(),
                url,
                params=params,
                timeout=kwargs.pop("timeout", self.timeout),
                headers=headers,
                **kwargs,
            )
            response.raise_for_status()
            self.metrics["requests_success"] += 1
            self.circuit_breaker.record_success()
            return response.text
        except Exception as exc:
            logger.error(f"Failed to fetch page {url}: {exc}")
            self.metrics["requests_failed"] += 1
            self.circuit_breaker.record_failure()
            return None

    def _load_local(self) -> Optional[Union[pd.DataFrame, Dict, List]]:
        """
        Load and merge local raw/processed data.

        Creative fallback: Checks both raw and processed paths,
        merges if both exist to provide augmented data.

        Returns:
            Merged data if available, None otherwise
        """
        raw_data = None
        processed_data = None

        # Load raw data
        if self.local_raw_path and self.local_raw_path.exists():
            try:
                if str(self.local_raw_path).endswith(".csv"):
                    raw_data = pd.read_csv(self.local_raw_path, encoding="latin1")
                elif str(self.local_raw_path).endswith(".json"):
                    with open(self.local_raw_path, "r", encoding="utf-8") as f:
                        raw_data = json.load(f)
                logger.debug(f"Loaded raw data from {self.local_raw_path}")
            except Exception as e:
                logger.warning(f"Failed to load raw data: {e}")

        # Load processed data
        if self.local_processed_path and self.local_processed_path.exists():
            try:
                if str(self.local_processed_path).endswith(".csv"):
                    processed_data = pd.read_csv(
                        self.local_processed_path, encoding="utf-8"
                    )
                elif str(self.local_processed_path).endswith(".json"):
                    with open(self.local_processed_path, "r", encoding="utf-8") as f:
                        processed_data = json.load(f)
                logger.debug(f"Loaded processed data from {self.local_processed_path}")
            except Exception as e:
                logger.warning(f"Failed to load processed data: {e}")
        if raw_data is not None and processed_data is not None:
            return self._merge_data(raw_data, processed_data)
        elif raw_data is not None:
            return raw_data
        elif processed_data is not None:
            return processed_data

        return None

    def _merge_data(
        self,
        raw_data: Union[pd.DataFrame, Dict, List],
        processed_data: Union[pd.DataFrame, Dict, List],
    ) -> Union[pd.DataFrame, Dict, List]:
        """
        Merge raw and processed data intelligently.

        DataFrames are concatenated, dicts are updated, lists are extended.
        """
        if isinstance(raw_data, pd.DataFrame) and isinstance(
            processed_data, pd.DataFrame
        ):
            # Concatenate and deduplicate
            combined = pd.concat([raw_data, processed_data], ignore_index=True)
            # Remove duplicates if possible
            if "date" in combined.columns and "home_team" in combined.columns:
                combined = combined.drop_duplicates(
                    subset=["date", "home_team", "away_team"], keep="last"
                )
            return combined
        elif isinstance(raw_data, dict) and isinstance(processed_data, dict):
            # Deep merge dicts
            merged = raw_data.copy()
            merged.update(processed_data)
            return merged
        elif isinstance(raw_data, list) and isinstance(processed_data, list):
            return raw_data + processed_data

        # Fallback: return processed (usually more refined)
        return processed_data

    def _save_local(self, data: Union[pd.DataFrame, Dict, List]) -> None:
        """Save scraped data to local cache for future use."""
        if not self.local_processed_path:
            return

        try:
            self.local_processed_path.parent.mkdir(parents=True, exist_ok=True)

            if isinstance(data, pd.DataFrame):
                if str(self.local_processed_path).endswith(".json"):
                    data.to_json(self.local_processed_path, orient="records", indent=2)
                else:
                    data.to_csv(self.local_processed_path, index=False)
            else:
                with open(self.local_processed_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, default=str)

            logger.info(f"Saved data to {self.local_processed_path}")
        except Exception as e:
            logger.warning(f"Failed to save local data: {e}")

    def fetch_data(
        self, *args, use_cache: bool = True, force_refresh: bool = False, **kwargs
    ) -> Optional[Union[pd.DataFrame, Dict, List]]:
        """
        Main entry point for fetching data.

        1. Check local cache first (unless force_refresh)
        2. Fallback to remote scrape if cache miss/stale
        3. Parse and save result locally

        Args:
            use_cache: Whether to use local cache
            force_refresh: Force remote fetch even if cache exists
            *args, **kwargs: Passed to _fetch_remote

        Returns:
            Parsed data or None on failure
        """
        # Check local cache first
        if use_cache and not force_refresh:
            local_data = self._load_local()
            if local_data is not None:
                self.metrics["cache_hits"] += 1
                logger.info(
                    f"Using local cache from {self.local_processed_path or self.local_raw_path}"
                )
                return local_data

        # Check circuit breaker
        if not self.circuit_breaker.can_attempt():
            logger.warning("Circuit breaker OPEN - using stale cache if available")
            return self._load_local()

        # Fetch from remote
        try:
            self.metrics["requests_total"] += 1
            self._wait_rate_limit()

            page_content = self._fetch_remote(*args, **kwargs)
            if page_content is None:
                raise ValueError("Empty response from remote")

            parsed = self._parse_data(page_content)

            # Success - update metrics
            self.metrics["requests_success"] += 1
            self.circuit_breaker.record_success()

            # Save for future use
            if use_cache:
                self._save_local(parsed)

            return parsed

        except Exception as e:
            logger.error(f"Fetch failed: {e}")
            self.metrics["requests_failed"] += 1
            self.circuit_breaker.record_failure()

            # Fallback to stale cache
            return self._load_local()

    @abstractmethod
    def _fetch_remote(self, *args, **kwargs) -> Any:
        """
        Subclass implements remote fetching logic.

        Should return raw page content/response for parsing.
        """
        pass

    @abstractmethod
    def _parse_data(self, page_content: Any) -> Union[pd.DataFrame, Dict, List]:
        """
        Subclass implements parsing logic.

        Should return structured data (DataFrame, dict, or list).
        """
        pass

    def get_metrics(self) -> Dict[str, Any]:
        """Get scraper performance metrics."""
        success_rate = (
            self.metrics["requests_success"] / self.metrics["requests_total"]
            if self.metrics["requests_total"] > 0
            else 0.0
        )
        return {
            **self.metrics,
            "success_rate": round(success_rate, 3),
            "circuit_breaker_state": self.circuit_breaker.state,
            "circuit_breaker_failures": self.circuit_breaker.failures,
        }
