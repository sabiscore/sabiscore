"""The CLAUDE.md SAFE DEFAULTS block is a contract; nothing enforced it until now.

Every developer has a gitignored `backend/.env`, so local runs never exercise the
code defaults. That is exactly how `use_phase7_models` reached CI as a surprise
(PR #154): it defaults False, a local .env set it True, and no test said so.
"""

import pytest

from src.core.config import Settings

# CLAUDE.md "SAFE DEFAULTS (PRODUCTION FAIL-CLOSED)", plus the two flags that
# have actually bitten us. Value is what the code must default to with no env.
SAFE_DEFAULTS = {
    "debug": False,
    "mock_mode": False,
    "enable_legacy_inference": False,
    "scraper_allow_insecure_fallback": False,
    "allow_sqlite_fallback": False,
    "provider_live_tests": False,
    "use_phase9_candidate_features": False,
    "phase9_shadow_only": True,
    "use_phase7_models": False,
    "enable_statsbomb_enrichment": False,
}


def _env_names() -> set[str]:
    """Every env name that can feed a setting, so the test sees pure defaults."""
    names: set[str] = set()
    for name, field in Settings.model_fields.items():
        names.add(name.upper())
        alias = field.validation_alias or field.alias
        if isinstance(alias, str):
            names.add(alias.upper())
        elif alias is not None:  # AliasChoices
            names.update(str(c).upper() for c in alias.choices)
    return names


@pytest.fixture
def bare_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for env_name in _env_names():
        monkeypatch.delenv(env_name, raising=False)
    return Settings(_env_file=None)


@pytest.mark.parametrize("field_name,expected", sorted(SAFE_DEFAULTS.items()))
def test_flag_is_safe_with_no_env(bare_settings: Settings, field_name: str, expected: bool) -> None:
    assert getattr(bare_settings, field_name) is expected, (
        f"{field_name} must default to {expected} with no .env present. "
        "Changing a safe default silently changes production behaviour."
    )


def test_every_setting_has_a_default_so_a_bare_boot_is_possible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No required field: the app must construct settings with zero env supplied."""
    for env_name in _env_names():
        monkeypatch.delenv(env_name, raising=False)
    required = [n for n, f in Settings.model_fields.items() if f.is_required()]
    assert not required, f"Settings fields without a default: {required}"
    assert Settings(_env_file=None).app_env == "development"
