import json
import logging
import random
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import quote_plus

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from requests.exceptions import SSLError, ConnectionError, Timeout

from ..core.config import settings


logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Circuit breaker to prevent repeated failures from overloading scrapers."""

    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = "closed"  # closed, open, half_open

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
                f"Circuit breaker opened after {self.failures} failures. "
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
                logger.info("Circuit breaker entering half-open state")
                return True

        return False

    def is_open(self) -> bool:
        """Check if circuit is open."""
        return self.state == "open"


def _create_retry_session() -> requests.Session:
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": settings.user_agent})
    return session


class BaseScraper:
    """Base scraper with retry, rate limiting, circuit breaker, and polite headers."""

    def __init__(self) -> None:
        self.session = _create_retry_session()
        self.base_delay = settings.rate_limit_delay
        self.last_scrape_at: Optional[datetime] = None
        self._default_verify = settings.scraper_ssl_verify
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, timeout=60)
        self.metrics = {
            "requests_total": 0,
            "requests_success": 0,
            "requests_failed": 0,
            "retries_total": 0,
        }

    def _throttle(self, attempt: int = 0) -> None:
        jitter = random.uniform(0, 0.3 * self.base_delay)
        # Exponential backoff with max cap
        delay = min(self.base_delay * (2**attempt) + jitter, 30.0)
        logger.debug("Throttling for %.2fs (attempt %d)", delay, attempt + 1)
        time.sleep(delay)

    def _make_request(self, url: str, retries: int = 3) -> Optional[requests.Response]:
        """Make HTTP request with circuit breaker, retries, and metrics."""
        self.metrics["requests_total"] += 1

        # Check circuit breaker
        if not self.circuit_breaker.can_attempt():
            logger.warning("Circuit breaker is open, skipping request to %s", url)
            self.metrics["requests_failed"] += 1
            return None

        last_exception: Optional[Exception] = None
        verify: bool | str = self._default_verify

        for attempt in range(retries):
            if attempt > 0:
                self.metrics["retries_total"] += 1
                self._throttle(attempt)

            try:
                response = self.session.get(
                    url,
                    timeout=settings.request_timeout,
                    verify=verify,
                )

                # Handle server errors
                if response.status_code >= 500:
                    raise requests.HTTPError(f"Server error {response.status_code}")

                response.raise_for_status()
                self.last_scrape_at = datetime.now(timezone.utc)

                # Success - update metrics and circuit breaker
                self.metrics["requests_success"] += 1
                self.circuit_breaker.record_success()
                return response

            except SSLError as exc:
                last_exception = exc
                if settings.scraper_allow_insecure_fallback and verify:
                    logger.warning(
                        "SSL verification failed for %s (%d/%d). Retrying without verification.",
                        url,
                        attempt + 1,
                        retries,
                    )
                    verify = False
                    continue
                logger.warning(
                    "SSL failure for %s (%d/%d): %s",
                    url,
                    attempt + 1,
                    retries,
                    exc,
                )
            except (ConnectionError, Timeout) as exc:
                last_exception = exc
                logger.warning(
                    "Network error for %s (%d/%d): %s",
                    url,
                    attempt + 1,
                    retries,
                    type(exc).__name__,
                )
            except Exception as exc:
                last_exception = exc
                logger.warning(
                    "Request to %s failed (%d/%d): %s",
                    url,
                    attempt + 1,
                    retries,
                    exc,
                )

        # All retries exhausted
        logger.error("All retries failed for %s: %s", url, last_exception)
        self.metrics["requests_failed"] += 1
        self.circuit_breaker.record_failure()
        return None

    def get_metrics(self) -> Dict[str, any]:
        """Get scraper metrics for monitoring."""
        success_rate = (
            self.metrics["requests_success"] / self.metrics["requests_total"]
            if self.metrics["requests_total"] > 0
            else 0.0
        )
        return {
            **self.metrics,
            "success_rate": success_rate,
            "circuit_breaker_state": self.circuit_breaker.state,
            "circuit_breaker_failures": self.circuit_breaker.failures,
        }

    def _parse_table_to_df(
        self, soup: BeautifulSoup, table_selector: str
    ) -> pd.DataFrame:
        table = soup.select_one(table_selector)
        if not table:
            return pd.DataFrame()

        headers = [th.get_text(strip=True) for th in table.select("thead th")]
        rows = []
        for tr in table.select("tbody tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if cells:
                rows.append(cells)

        return pd.DataFrame(rows, columns=headers or None)

    def _validate_match_data(self, match: Dict) -> bool:
        """Validate scraped match data has required fields."""
        required_fields = ["home_team", "away_team", "date"]

        for field in required_fields:
            if not match.get(field):
                logger.warning(f"Missing required field: {field}")
                return False

        # Validate team names are not empty or invalid
        if not match["home_team"].strip() or not match["away_team"].strip():
            logger.warning("Invalid team names")
            return False

        return True


def _slugify_team(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or name.lower().replace(" ", "-")


def _normalize_team_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    for suffix in ("fc", "cf", "sc", "club", "ac", "afc"):
        normalized = normalized.replace(suffix, "")
    return normalized


def _extract_ft_score(match: Dict[str, any]) -> Optional[Tuple[int, int]]:
    score_block = match.get("score") or {}
    full_time = score_block.get("ft")
    if isinstance(full_time, (list, tuple)) and len(full_time) >= 2:
        try:
            return int(full_time[0]), int(full_time[1])
        except (TypeError, ValueError):
            return None
    return None


def _apply_data_retention(df: pd.DataFrame, date_column: str = "date") -> pd.DataFrame:
    """Drop records older than the configured data retention window."""
    retention_days = getattr(settings, "data_retention_days", None)
    if df.empty or date_column not in df.columns:
        return df
    if not retention_days or retention_days <= 0:
        return df

    dates = pd.to_datetime(df[date_column], errors="coerce")
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    mask = dates >= cutoff

    if mask.all():
        df = df.copy()
        df[date_column] = dates
        return df

    filtered = df.loc[mask].copy()
    filtered[date_column] = dates.loc[mask]
    dropped = len(df) - len(filtered)
    if dropped > 0:
        logger.info(
            "Data retention dropped %d %s records older than %d days",
            dropped,
            date_column,
            retention_days,
        )
    return filtered


class FlashscoreScraper(BaseScraper):
    BASE_URL = "https://www.flashscore.com"
    _team_path_cache: Dict[str, str] = {}

    def _load_fallback_data(self, team: str, league: str) -> pd.DataFrame:
        """Load historical match data from processed JSON files as fallback."""
        try:
            league_map = {
                "EPL": "epl_matches.json",
                "La Liga": "la_liga_matches.json",
                "Serie A": "serie_a_matches.json",
                "Bundesliga": "bundesliga_matches.json",
                "Ligue 1": "ligue_1_matches.json",
            }
            filename = league_map.get(league)
            if not filename:
                return pd.DataFrame()

            file_path = settings.data_path / filename
            if not file_path.exists():
                return pd.DataFrame()

            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            matches = data.get("matches", [])
            df_data = []
            target_normalized = _normalize_team_name(team)

            for match in matches:
                teams = (match.get("team1", ""), match.get("team2", ""))
                normalized = [_normalize_team_name(t) for t in teams]
                if target_normalized not in normalized:
                    continue

                score = _extract_ft_score(match)
                if score is None:
                    continue

                df_data.append(
                    {
                        "date": match.get("date"),
                        "competition": data.get("name", league),
                        "home_team": teams[0],
                        "away_team": teams[1],
                        "home_score": score[0],
                        "away_score": score[1],
                        "status": "FT",
                    }
                )

            df = pd.DataFrame(df_data)
            if not df.empty:
                df["home_score"] = pd.to_numeric(df["home_score"], errors="coerce")
                df["away_score"] = pd.to_numeric(df["away_score"], errors="coerce")
                df = df.dropna(subset=["home_score", "away_score"])
                df = _apply_data_retention(df, date_column="date")
                logger.info(
                    "Loaded %d fallback matches for %s from %s", len(df), team, filename
                )
            return df

        except Exception as e:
            logger.warning("Failed to load fallback data for %s: %s", team, e)
            return pd.DataFrame()

    def _resolve_team_path(self, team: str, league: str) -> Optional[str]:
        key = (league or "").lower() + ":" + _normalize_team_name(team)
        if key in self._team_path_cache:
            return self._team_path_cache[key]

        search_url = f"{self.BASE_URL}/search/?q={quote_plus(team)}"
        response = self._make_request(search_url)
        if response is None:
            logger.warning("Unable to resolve Flashscore path for %s", team)
            return None

        soup = BeautifulSoup(response.text, "lxml")
        slug = _slugify_team(team)
        for anchor in soup.select("a"):
            href = anchor.get("href") or ""
            if "/team/" not in href or slug not in href:
                continue

            normalized_text = _normalize_team_name(anchor.get_text(strip=True))
            if normalized_text != _normalize_team_name(team):
                continue

            parts = href.strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "team":
                base_path = "/".join(parts[:3])
                self._team_path_cache[key] = base_path
                return base_path

        logger.warning("Flashscore search did not yield a valid team path for %s", team)
        return None

    def scrape_match_results(self, team: str, league: str) -> pd.DataFrame:
        logger.info("Scraping Flashscore results for %s (%s)", team, league)
        path = self._resolve_team_path(team, league)
        if not path:
            logger.warning(
                "Falling back to local data for %s due to unresolved path", team
            )
            return self._load_fallback_data(team, league)

        url = f"{self.BASE_URL}/{path}/results"
        response = self._make_request(url)
        if response is None:
            logger.warning("Scraping failed for %s, using fallback data", team)
            return self._load_fallback_data(team, league)

        soup = BeautifulSoup(response.text, "lxml")
        table = self._parse_table_to_df(soup, "table.wld")
        if table.empty:
            logger.warning("No data scraped for %s, using fallback data", team)
            return self._load_fallback_data(team, league)

        table.columns = [
            "date",
            "competition",
            "home_team",
            "away_team",
            "score",
            "status",
        ][: len(table.columns)]

        score_split = table["score"].str.extract(
            r"(?P<home_score>\d+)\s*:\s*(?P<away_score>\d+)"
        )
        table = pd.concat([table, score_split], axis=1)
        table["home_score"] = pd.to_numeric(table["home_score"], errors="coerce")
        table["away_score"] = pd.to_numeric(table["away_score"], errors="coerce")

        result = table.dropna(subset=["home_score", "away_score"])
        if result.empty:
            logger.warning("No valid scores scraped for %s, using fallback data", team)
            return self._load_fallback_data(team, league)

        return _apply_data_retention(result, date_column="date")


class OddsPortalScraper(BaseScraper):
    BASE_URL = "https://www.oddsportal.com"

    def scrape_odds(self, home_team: str, away_team: str) -> Dict[str, float]:
        logger.info("Scraping odds for %s vs %s", home_team, away_team)
        url = f"{self.BASE_URL}/match/{_slugify_team(home_team)}-{_slugify_team(away_team)}/#1X2;2"
        response = self._make_request(url)
        if response is None:
            logger.warning(
                "Odds scraping failed for %s vs %s, using mock odds",
                home_team,
                away_team,
            )
            return self._mock_odds()

        soup = BeautifulSoup(response.text, "lxml")
        odds_table = soup.select_one("table.table-main")
        if not odds_table:
            logger.warning(
                "No odds table found for %s vs %s, using mock odds",
                home_team,
                away_team,
            )
            return self._mock_odds()

        odds_cells = odds_table.select("tbody tr:first-child td.odds")
        if len(odds_cells) < 3:
            logger.warning(
                "Insufficient odds data for %s vs %s, using mock odds",
                home_team,
                away_team,
            )
            return self._mock_odds()

        try:
            home, draw, away = [
                float(cell.get_text(strip=True)) for cell in odds_cells[:3]
            ]
        except ValueError:
            logger.warning(
                "Failed to parse odds for %s vs %s, using mock odds",
                home_team,
                away_team,
            )
            return self._mock_odds()

        return {
            "home_win": home,
            "draw": draw,
            "away_win": away,
        }

    def _mock_odds(self) -> Dict[str, float]:
        """Return mock odds for demonstration purposes."""
        return {
            "home_win": 2.1,
            "draw": 3.4,
            "away_win": 3.8,
        }


class TransfermarktScraper(BaseScraper):
    BASE_URL = "https://www.transfermarkt.com"
    _team_id_cache: Dict[str, str] = {}

    def _resolve_team_id(self, team: str) -> Optional[str]:
        normalized_name = _normalize_team_name(team)
        if normalized_name in self._team_id_cache:
            return self._team_id_cache[normalized_name]

        search_url = f"{self.BASE_URL}/schnellsuche/ergebnis/schnellsuche?query={quote_plus(team)}"
        response = self._make_request(search_url)
        if response is None:
            logger.warning("Unable to resolve Transfermarkt ID for %s", team)
            return None

        soup = BeautifulSoup(response.text, "lxml")
        for anchor in soup.select("a"):
            href = anchor.get("href") or ""
            if "/verein/" not in href:
                continue

            text_normalized = _normalize_team_name(anchor.get_text(strip=True))
            if text_normalized != normalized_name:
                continue

            match = re.search(r"/verein/(\d+)", href)
            if match:
                team_id = match.group(1)
                self._team_id_cache[normalized_name] = team_id
                return team_id

        logger.warning("Transfermarkt search did not return a team id for %s", team)
        return None

    def scrape_injuries(self, team: str) -> pd.DataFrame:
        logger.info("Scraping Transfermarkt injuries for %s", team)
        team_id = self._resolve_team_id(team)
        if not team_id:
            return pd.DataFrame(
                columns=["player", "injury", "expected_return", "status"]
            )

        url = f"{self.BASE_URL}/{_slugify_team(team)}/verletzte/verein/{team_id}"
        response = self._make_request(url)
        if response is None:
            return pd.DataFrame(
                columns=["player", "injury", "expected_return", "status"]
            )

        soup = BeautifulSoup(response.text, "lxml")
        table = self._parse_table_to_df(soup, "table.items")
        if table.empty:
            return pd.DataFrame(
                columns=["player", "injury", "expected_return", "status"]
            )

        table.columns = [
            "player",
            "injury",
            "since",
            "expected_return",
            "status",
        ][: len(table.columns)]

        return table[
            [
                col
                for col in table.columns
                if col in {"player", "injury", "expected_return", "status"}
            ]
        ]

    def scrape_player_values(self, team: str) -> pd.DataFrame:
        logger.info("Scraping Transfermarkt values for %s", team)
        team_id = self._resolve_team_id(team)
        if not team_id:
            return pd.DataFrame(columns=["name", "position", "value", "age"])

        url = f"{self.BASE_URL}/{_slugify_team(team)}/kader/verein/{team_id}"
        response = self._make_request(url)
        if response is None:
            return pd.DataFrame(columns=["name", "position", "value", "age"])

        soup = BeautifulSoup(response.text, "lxml")
        table = self._parse_table_to_df(soup, "table.items")
        if table.empty:
            return pd.DataFrame(columns=["name", "position", "value", "age"])

        table.columns = [
            "number",
            "name",
            "position",
            "age",
            "nationality",
            "market_value",
        ][: len(table.columns)]

        clean = pd.DataFrame()
        clean["name"] = table.get("name")
        clean["position"] = table.get("position")
        clean["age"] = pd.to_numeric(table.get("age"), errors="coerce")
        clean["value"] = table.get("market_value")

        return clean.dropna(subset=["name"])


# Convenience functions ------------------------------------------------
def scrape_flashscore(team: str, league: str) -> pd.DataFrame:
    return FlashscoreScraper().scrape_match_results(team, league)


def scrape_oddsportal(home_team: str, away_team: str) -> Dict[str, float]:
    return OddsPortalScraper().scrape_odds(home_team, away_team)


def scrape_transfermarkt_injuries(team: str) -> pd.DataFrame:
    return TransfermarktScraper().scrape_injuries(team)


# =============================================================================
# FootballDataScraper - Historical data from football-data.co.uk
# =============================================================================


class FootballDataScraper:
    """
    Scraper for football-data.co.uk historical data.

    Implements ethical scraping:
    - Rate limiting (2s between requests)
    - Retry with exponential backoff
    - Caching to minimize requests
    - User-agent identification

    This site provides free CSV downloads of historical football data including:
    - Match results (home/away goals)
    - Pinnacle odds (best proxy for closing line)
    - Shot statistics, corners, fouls
    - Referee data

    Usage:
        scraper = FootballDataScraper()
        df = scraper.download_season_data('E0', '2526')  # EPL 2025/26
    """

    # Base URL for football-data.co.uk
    BASE_URL = "https://www.football-data.co.uk"

    # League code mapping
    LEAGUE_CODES = {
        "EPL": "E0",
        "Championship": "E1",
        "La Liga": "SP1",
        "La_Liga": "SP1",
        "Bundesliga": "D1",
        "Serie A": "I1",
        "Serie_A": "I1",
        "Ligue 1": "F1",
        "Ligue_1": "F1",
        "Eredivisie": "N1",
        "Portuguese": "P1",
        "Turkish": "T1",
        "Greek": "G1",
    }

    # Column mapping for standardization
    COLUMN_MAPPING = {
        "Date": "date",
        "HomeTeam": "home_team",
        "AwayTeam": "away_team",
        "FTHG": "home_goals",
        "FTAG": "away_goals",
        "FTR": "result",  # H/D/A
        "HTHG": "ht_home_goals",
        "HTAG": "ht_away_goals",
        "HTR": "ht_result",
        "HS": "home_shots",
        "AS": "away_shots",
        "HST": "home_shots_target",
        "AST": "away_shots_target",
        "HF": "home_fouls",
        "AF": "away_fouls",
        "HC": "home_corners",
        "AC": "away_corners",
        "HY": "home_yellows",
        "AY": "away_yellows",
        "HR": "home_reds",
        "AR": "away_reds",
        # Pinnacle odds (our preferred bookmaker)
        "PSH": "pinnacle_home",
        "PSD": "pinnacle_draw",
        "PSA": "pinnacle_away",
        # Bet365 odds (backup)
        "B365H": "bet365_home",
        "B365D": "bet365_draw",
        "B365A": "bet365_away",
        # Market average
        "AvgH": "avg_home",
        "AvgD": "avg_draw",
        "AvgA": "avg_away",
        "MaxH": "max_home",
        "MaxD": "max_draw",
        "MaxA": "max_away",
    }

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize the football-data.co.uk scraper.

        Args:
            cache_dir: Directory for caching downloaded files
        """
        self.session = self._create_session()
        self.cache_dir = cache_dir or settings.data_path / "football_data_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_request_time = 0.0
        self.rate_limit_delay = 2.0  # 2 seconds between requests

        logger.info(f"FootballDataScraper initialized with cache at {self.cache_dir}")

    def _create_session(self) -> requests.Session:
        """Create a session with retry logic."""
        session = requests.Session()

        retry_strategy = Retry(
            total=3,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # Identify ourselves as SabiScore
        session.headers.update(
            {
                "User-Agent": f"SabiScore/1.0 (Research Project; {settings.user_agent})",
                "Accept": "text/csv,application/csv,text/plain;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
        )

        return session

    def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            sleep_time = self.rate_limit_delay - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    def _get_league_code(self, league: str) -> str:
        """Convert league name to football-data.co.uk code."""
        # If already a code, return it
        if league in ["E0", "E1", "SP1", "D1", "I1", "F1", "N1", "P1", "T1", "G1"]:
            return league

        # Look up in mapping
        return self.LEAGUE_CODES.get(league, league)

    def _get_season_url(self, league_code: str, season: str) -> str:
        """
        Build URL for season CSV download.

        Args:
            league_code: League code (e.g., 'E0')
            season: Season string (e.g., '2526' for 2025/26)

        Returns:
            URL for CSV download
        """
        # Season format: '2526' -> '25-26' folder
        if len(season) == 4:
            folder = f"{season[:2]}{season[2:]}"
        else:
            folder = season

        return f"{self.BASE_URL}/mmz4281/{folder}/{league_code}.csv"

    def _get_cache_path(self, league_code: str, season: str) -> Path:
        """Get cache file path for a league/season."""
        return self.cache_dir / f"{league_code}_{season}.csv"

    def download_season_data(
        self, league: str, season: str, use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Download historical match data for a season.

        Args:
            league: League name or code (e.g., 'EPL' or 'E0')
            season: Season code (e.g., '2526' for 2025/26)
            use_cache: Whether to use cached data if available

        Returns:
            DataFrame with standardized column names
        """
        import io

        league_code = self._get_league_code(league)
        cache_path = self._get_cache_path(league_code, season)

        # Check cache first
        if use_cache and cache_path.exists():
            cache_age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
            if cache_age_hours < 24:  # Cache valid for 24 hours
                logger.info(f"Using cached data for {league_code} {season}")
                df = pd.read_csv(cache_path)
                return self._standardize_dataframe(df)

        # Download from website
        url = self._get_season_url(league_code, season)
        logger.info(f"Downloading data from {url}")

        self._rate_limit()

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            # Parse CSV
            df = pd.read_csv(io.StringIO(response.text))

            # Cache the raw data
            df.to_csv(cache_path, index=False)
            logger.info(f"Cached {len(df)} matches to {cache_path}")

            return self._standardize_dataframe(df)

        except requests.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(f"Season data not found: {url}")
                return pd.DataFrame()
            raise
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")

            # Try to use stale cache as fallback
            if cache_path.exists():
                logger.warning("Using stale cache as fallback")
                df = pd.read_csv(cache_path)
                return self._standardize_dataframe(df)

            return pd.DataFrame()

    def _standardize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize column names and add computed features.

        Args:
            df: Raw DataFrame from CSV

        Returns:
            Standardized DataFrame
        """
        # Rename columns that exist
        rename_map = {k: v for k, v in self.COLUMN_MAPPING.items() if k in df.columns}
        df = df.rename(columns=rename_map)

        # Parse date column
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
        elif "Date" in df.columns:
            df["date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")

        # Add computed columns
        if "home_goals" in df.columns and "away_goals" in df.columns:
            df["total_goals"] = df["home_goals"] + df["away_goals"]
            df["goal_diff"] = df["home_goals"] - df["away_goals"]

        # Add over/under markers
        if "total_goals" in df.columns:
            df["over_2.5"] = (df["total_goals"] > 2.5).astype(int)
            df["over_3.5"] = (df["total_goals"] > 3.5).astype(int)
            df["btts"] = ((df["home_goals"] > 0) & (df["away_goals"] > 0)).astype(int)

        # Calculate implied probabilities from Pinnacle odds
        if all(
            col in df.columns
            for col in ["pinnacle_home", "pinnacle_draw", "pinnacle_away"]
        ):
            df["implied_home_prob"] = 1 / df["pinnacle_home"]
            df["implied_draw_prob"] = 1 / df["pinnacle_draw"]
            df["implied_away_prob"] = 1 / df["pinnacle_away"]
            df["margin"] = (
                df["implied_home_prob"]
                + df["implied_draw_prob"]
                + df["implied_away_prob"]
                - 1
            )

        # Add metadata
        df["source"] = "football-data.co.uk"
        df["downloaded_at"] = datetime.now().isoformat()

        return _apply_data_retention(df, date_column="date")

    def download_multiple_seasons(
        self, league: str, seasons: list, use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Download and combine data from multiple seasons.

        Args:
            league: League name or code
            seasons: List of season codes (e.g., ['2425', '2526'])
            use_cache: Whether to use cached data

        Returns:
            Combined DataFrame with season column
        """
        all_data = []

        for season in seasons:
            df = self.download_season_data(league, season, use_cache)
            if not df.empty:
                df["season"] = season
                all_data.append(df)

        if not all_data:
            return pd.DataFrame()

        combined = pd.concat(all_data, ignore_index=True)
        combined = combined.sort_values("date", ascending=True)

        logger.info(f"Combined {len(combined)} matches across {len(seasons)} seasons")

        return combined

    def download_all_leagues(
        self, season: str, leagues: Optional[list] = None, use_cache: bool = True
    ) -> Dict[str, pd.DataFrame]:
        """
        Download data for multiple leagues in a season.

        Args:
            season: Season code
            leagues: List of leagues (defaults to top 5)
            use_cache: Whether to use cached data

        Returns:
            Dict mapping league to DataFrame
        """
        if leagues is None:
            leagues = ["EPL", "La Liga", "Bundesliga", "Serie A", "Ligue 1"]

        results = {}

        for league in leagues:
            df = self.download_season_data(league, season, use_cache)
            if not df.empty:
                results[league] = df

        logger.info(f"Downloaded data for {len(results)} leagues")

        return results

    def get_team_history(
        self, team_name: str, league: str, seasons: list, use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Get all matches for a specific team.

        Args:
            team_name: Team name to search for
            league: League code
            seasons: Seasons to search
            use_cache: Whether to use cache

        Returns:
            DataFrame of team's matches
        """
        all_data = self.download_multiple_seasons(league, seasons, use_cache)

        if all_data.empty:
            return pd.DataFrame()

        # Find matches where team played (home or away)
        team_lower = team_name.lower()
        mask = all_data["home_team"].str.lower().str.contains(
            team_lower, na=False
        ) | all_data["away_team"].str.lower().str.contains(team_lower, na=False)

        team_matches = all_data[mask].copy()
        logger.info(f"Found {len(team_matches)} matches for {team_name}")

        return team_matches

    def clear_cache(self) -> None:
        """Clear all cached data files."""
        for cache_file in self.cache_dir.glob("*.csv"):
            cache_file.unlink()
            logger.info(f"Deleted cache file: {cache_file}")


def scrape_football_data(league: str, season: str) -> pd.DataFrame:
    """Convenience function to scrape football-data.co.uk."""
    return FootballDataScraper().download_season_data(league, season)
