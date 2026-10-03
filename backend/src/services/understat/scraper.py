"""Asynchronous Understat match-page scraper.

Fetches ``https://understat.com/match/{match_id}``, extracts the embedded
``shotsData`` and ``match_info`` JSON payloads, decodes Understat's
hex-encoded unicode-escaped format, validates through Pydantic v2, and
returns a typed ``UnderstatMatchPayload``.

Design constraints
------------------
* Uses ``aiohttp`` exclusively — no synchronous I/O in the hot path.
* User-Agent header is rotated from a small curated list to reduce 403/429
  risk.  For heavy production use, integrate a real proxy tier.
* Exponential back-off via ``tenacity`` with jitter.  Stops after 5 attempts
  to avoid hammering Understat.
* All decoding goes through ``codecs.decode(payload_bytes, "unicode_escape")``
  as Understat's JSON strings are hex-unicode-escaped and will silently
  corrupt if decoded naively.
"""

from __future__ import annotations

import codecs
import json
import logging
import random
import re
from typing import Any

import aiohttp
from bs4 import BeautifulSoup  # type: ignore[import-untyped]
from pydantic import BaseModel, Field, field_validator
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://understat.com/match/{match_id}"

_USER_AGENTS: list[str] = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
        "Gecko/20100101 Firefox/124.0"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.4.1 Safari/605.1.15"
    ),
]

# Understat embeds JSON as: var <name> = JSON.parse('<hex-escaped-string>');
# The payload is a single-quoted hex-unicode-escaped string.
_SHOTS_DATA_RE = re.compile(
    r"var\s+shotsData\s*=\s*JSON\.parse\('(.+?)'\)", re.DOTALL
)
_MATCH_INFO_RE = re.compile(
    r"var\s+match_info\s*=\s*JSON\.parse\('(.+?)'\)", re.DOTALL
)

# ---------------------------------------------------------------------------
# Pydantic v2 payload models
# ---------------------------------------------------------------------------


class ShotRecord(BaseModel):
    """Single shot event from Understat's shotsData."""

    id: str
    minute: str
    result: str
    X: str  # pitch x coordinate (string in source)
    Y: str  # pitch y coordinate (string in source)
    xG: str  # expected goals value
    player: str
    h_a: str  # "h" or "a"
    player_id: str
    situation: str
    season: str
    shotType: str
    match_id: str
    h_team: str
    a_team: str
    h_goals: str
    a_goals: str
    date: str
    player_assisted: str | None = None
    lastAction: str

    @field_validator("xG", "X", "Y", mode="before")
    @classmethod
    def _coerce_numeric_string(cls, v: Any) -> str:  # noqa: ANN401
        return str(v)


class ShotsData(BaseModel):
    """Top-level shotsData object with home and away shot lists."""

    h: list[ShotRecord] = Field(default_factory=list)
    a: list[ShotRecord] = Field(default_factory=list)


class MatchInfoSide(BaseModel):
    """Team-side summary from match_info."""

    id: str
    title: str
    short_title: str


class MatchInfoGoals(BaseModel):
    h: str | int | None = None
    a: str | int | None = None


class MatchInfo(BaseModel):
    """Parsed match_info payload."""

    id: str
    isResult: bool
    h: MatchInfoSide
    a: MatchInfoSide
    goals: MatchInfoGoals
    xG: MatchInfoGoals
    datetime: str
    league_id: str
    league: str
    season: str


class UnderstatMatchPayload(BaseModel):
    """Validated, combined payload for a single Understat match page."""

    match_id: int
    match_info: MatchInfo
    shots_data: ShotsData

    @property
    def home_xg(self) -> float:
        raw = self.match_info.xG.h
        return float(raw) if raw is not None else 0.0

    @property
    def away_xg(self) -> float:
        raw = self.match_info.xG.a
        return float(raw) if raw is not None else 0.0

    @property
    def home_xa(self) -> float:
        total = sum(
            float(s.xG) for s in self.shots_data.h if s.player_assisted is not None
        )
        return total

    @property
    def away_xa(self) -> float:
        total = sum(
            float(s.xG) for s in self.shots_data.a if s.player_assisted is not None
        )
        return total


# ---------------------------------------------------------------------------
# Decoding helpers
# ---------------------------------------------------------------------------


def _decode_understat_payload(raw_escaped: str) -> Any:  # noqa: ANN401
    """Decode Understat's unicode-escaped hex payload and parse JSON.

    Understat embeds data as a single-quoted string that has been processed
    through Python's ``unicode_escape`` codec.  Naive string decoding silently
    produces corrupted output; we must:

    1. Encode the extracted string as ``latin-1`` bytes (preserving raw byte
       values 0-255 without interpretation).
    2. Decode those bytes with the ``unicode_escape`` codec to expand all
       ``\\uXXXX`` and ``\\xXX`` sequences.
    3. Pass the resulting clean unicode string to ``json.loads``.
    """
    payload_bytes = raw_escaped.encode("utf-8")
    decoded_str = codecs.decode(payload_bytes, "unicode_escape")
    return json.loads(decoded_str)


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------


class UnderstatScraper:
    """Async Understat match-page scraper with retry and UA rotation."""

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
        *,
        max_attempts: int = 5,
        wait_min: float = 1.0,
        wait_max: float = 30.0,
        request_timeout: float = 20.0,
    ) -> None:
        self._external_session = session
        self._session: aiohttp.ClientSession | None = None
        self._max_attempts = max_attempts
        self._wait_min = wait_min
        self._wait_max = wait_max
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)

    async def __aenter__(self) -> "UnderstatScraper":
        if self._external_session is None:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        else:
            self._session = self._external_session
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._external_session is None and self._session is not None:
            await self._session.close()
            self._session = None

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": random.choice(_USER_AGENTS),  # noqa: S311
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

    async def _fetch_html(self, match_id: int) -> str:
        """Fetch raw HTML for a match page with retry + back-off."""
        url = _BASE_URL.format(match_id=match_id)
        if self._session is None:
            raise RuntimeError(
                "UnderstatScraper must be used as an async context manager."
            )
        session = self._session

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_attempts),
                wait=wait_exponential_jitter(
                    initial=self._wait_min, max=self._wait_max, jitter=2.0
                ),
                retry=retry_if_exception_type(
                    (aiohttp.ClientError, aiohttp.ServerDisconnectedError)
                ),
                reraise=True,
            ):
                with attempt:
                    async with session.get(url, headers=self._headers()) as resp:
                        if resp.status in (429, 503):
                            logger.warning(
                                "Rate-limited by Understat (status=%d) match_id=%d",
                                resp.status,
                                match_id,
                            )
                            raise aiohttp.ClientResponseError(
                                resp.request_info,
                                resp.history,
                                status=resp.status,
                            )
                        resp.raise_for_status()
                        return await resp.text()
        except RetryError as exc:
            raise RuntimeError(
                f"Understat fetch failed after {self._max_attempts} attempts "
                f"for match_id={match_id}"
            ) from exc

        raise RuntimeError(
            f"Understat fetch failed unexpectedly for match_id={match_id}"
        )

    @staticmethod
    def _extract_json_payloads(
        html: str,
    ) -> tuple[str, str]:
        """Return the raw escaped shotsData and match_info strings using BeautifulSoup."""
        soup = BeautifulSoup(html, "html.parser")
        shots_data_raw: str | None = None
        match_info_raw: str | None = None

        for script in soup.find_all("script"):
            content = script.string or script.text or ""
            if not content:
                continue
            if "shotsData" in content and shots_data_raw is None:
                m = _SHOTS_DATA_RE.search(content)
                if m:
                    shots_data_raw = m.group(1)
            if "match_info" in content and match_info_raw is None:
                m = _MATCH_INFO_RE.search(content)
                if m:
                    match_info_raw = m.group(1)
            if shots_data_raw is not None and match_info_raw is not None:
                break

        # Fallback to direct regex on raw html if BeautifulSoup script traversal missed it
        if shots_data_raw is None:
            shots_match = _SHOTS_DATA_RE.search(html)
            if shots_match:
                shots_data_raw = shots_match.group(1)
        if match_info_raw is None:
            match_info_match = _MATCH_INFO_RE.search(html)
            if match_info_match:
                match_info_raw = match_info_match.group(1)

        if not shots_data_raw:
            raise ValueError("shotsData variable not found in Understat HTML")
        if not match_info_raw:
            raise ValueError("match_info variable not found in Understat HTML")

        return shots_data_raw, match_info_raw

    async def fetch_match(self, match_id: int) -> UnderstatMatchPayload:
        """Fetch, parse, decode, and validate a single Understat match.

        Args:
            match_id: The integer Understat match identifier.

        Returns:
            A fully validated ``UnderstatMatchPayload``.

        Raises:
            RuntimeError: If the page cannot be fetched after all retries.
            ValueError: If the expected script variables are absent.
            pydantic.ValidationError: If the decoded JSON fails schema validation.
        """
        logger.info("Fetching Understat match match_id=%d", match_id)
        html = await self._fetch_html(match_id)

        raw_shots, raw_match_info = self._extract_json_payloads(html)

        shots_dict: Any = _decode_understat_payload(raw_shots)
        match_info_dict: Any = _decode_understat_payload(raw_match_info)

        shots_data = ShotsData.model_validate(shots_dict)
        match_info = MatchInfo.model_validate(match_info_dict)

        payload = UnderstatMatchPayload(
            match_id=match_id,
            match_info=match_info,
            shots_data=shots_data,
        )
        logger.info(
            "Fetched match_id=%d home_xg=%.3f away_xg=%.3f shots_h=%d shots_a=%d",
            match_id,
            payload.home_xg,
            payload.away_xg,
            len(payload.shots_data.h),
            len(payload.shots_data.a),
        )
        return payload


__all__ = [
    "UnderstatScraper",
    "UnderstatMatchPayload",
    "MatchInfo",
    "ShotsData",
    "ShotRecord",
]
