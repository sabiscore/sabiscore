"""Shared pytest fixtures for API tests and runtime shims."""
import pytest
import sys
import types
from unittest.mock import MagicMock

from src.core.cache import RedisCache


@pytest.fixture(autouse=True)
def _cleanup_mock_patches():
    """Clean up any mock patches that might leak between tests.
    
    This helps ensure test isolation when running the full test suite.
    """
    # Run the test
    yield
    
    # After each test, reset any mocked modules that might have leaked
    # This is particularly important for scrapers that get mocked in integration tests
    modules_to_check = [
        'src.data.scrapers.football_data_scraper',
        'src.data.scrapers.betfair_scraper',
        'src.data.scrapers.flashscore_scraper',
        'src.data.aggregator',
        'src.features.transformer',
    ]
    
    for mod_name in modules_to_check:
        if mod_name in sys.modules:
            mod = sys.modules[mod_name]
            # If the module has been replaced by a mock, reimport it
            if isinstance(mod, MagicMock) or hasattr(mod, '_mock_name'):
                del sys.modules[mod_name]


@pytest.fixture(autouse=True)
def _ensure_numpy_shim(monkeypatch):
    """Augment stubbed numpy modules injected by tests with required attrs.

    Some unit tests inject a minimal 'numpy' stub into sys.modules, which can
    confuse third-party tools (e.g., pytest.approx expects np.isscalar). This
    autouse fixture runs before each test and adds missing attributes to the
    stub in a non-intrusive way.
    """
    np = sys.modules.get("numpy")
    if isinstance(np, types.ModuleType):
        if not hasattr(np, "isscalar"):
            monkeypatch.setattr(
                np,
                "isscalar",
                lambda x: isinstance(x, (int, float, bool, complex)) or getattr(x, "shape", None) in (None, (), []),
                raising=False,
            )
        if not hasattr(np, "nan"):
            monkeypatch.setattr(np, "nan", float("nan"), raising=False)
    yield


@pytest.fixture
def mock_redis():
    """Mock Redis cache with circuit breaker disabled."""
    mock = MagicMock(spec=RedisCache)
    mock.metrics_snapshot.return_value = {
        "hits": 0,
        "misses": 0,
        "errors": 0,
        "circuit_open": False,
        "backend_available": True,
    }
    return mock
