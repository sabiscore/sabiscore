"""
Data loaders for historical and real-time football data.

Loaders:
- FootballDataLoader: CSV files from football-data.co.uk (180k matches, 2018-2025)
- UnderstatLoader: xG data scraper with Playwright
- FBrefLoader: Scouting reports and advanced stats
- TransfermarktLoader: Player valuations and squad data
"""


def _missing_loader(exc: Exception, message: str):
    class _MissingLoader:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            raise RuntimeError(message) from exc

    return _MissingLoader


try:
    from .football_data import FootballDataLoader
except Exception as exc:  # pragma: no cover - optional dependency path
    FootballDataLoader = _missing_loader(
        exc, "FootballDataLoader unavailable: install optional dependency 'aiohttp'"
    )

try:
    from .understat import UnderstatLoader
except Exception as exc:  # pragma: no cover - optional dependency path
    UnderstatLoader = _missing_loader(
        exc, "UnderstatLoader unavailable: install optional dependency 'tenacity'"
    )

try:
    from .fbref import FBrefLoader
except Exception as exc:  # pragma: no cover - optional dependency path
    FBrefLoader = _missing_loader(
        exc, "FBrefLoader unavailable: install optional scraper dependencies"
    )

try:
    from .transfermarkt import TransfermarktLoader
except Exception as exc:  # pragma: no cover - optional dependency path
    TransfermarktLoader = _missing_loader(
        exc, "TransfermarktLoader unavailable: install optional scraper dependencies"
    )

from .football_data_api import FootballDataAPIClient  # noqa: E402

__all__ = [
    "FootballDataLoader",
    "UnderstatLoader",
    "FBrefLoader",
    "TransfermarktLoader",
    "FootballDataAPIClient",
]
