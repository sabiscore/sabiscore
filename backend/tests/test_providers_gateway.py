import pytest

from src.providers.espn import ESPN_LEAGUE_SLUGS, ESPNProvider
from src.providers.base import ProviderResult, ProviderStatus, TrustTier
from src.providers.reconciliation import FixtureCandidate, reconcile_fixture
from src.providers.registry import build_provider_registry


def test_espn_gateway_is_keyless_supplementary_and_covers_supported_slugs():
    provider = ESPNProvider(enabled=True, live_tests=False)

    assert provider.provider_id == "espn"
    assert provider.requires_key is False
    assert provider.trust_tier is TrustTier.UNOFFICIAL_PUBLIC
    assert set(ESPN_LEAGUE_SLUGS) == {
        "EPL",
        "LA_LIGA",
        "SERIE_A",
        "BUNDESLIGA",
        "LIGUE_1",
        "EREDIVISIE",
        "UCL",
    }


@pytest.mark.asyncio
async def test_espn_scoreboard_fails_closed_when_live_calls_disabled():
    provider = ESPNProvider(enabled=True, live_tests=False)

    result = await provider.scoreboard("EPL")

    assert isinstance(result, ProviderResult)
    assert result.status is ProviderStatus.PARTIAL
    assert result.records == []
    assert "live_provider_calls_disabled" in result.warnings


@pytest.mark.asyncio
async def test_enabled_provider_health_is_configured_not_verified_without_live_probe():
    provider = ESPNProvider(enabled=True, live_tests=False)

    health = await provider.health()

    assert health.status is ProviderStatus.CONFIGURED_UNVERIFIED
    assert health.configured is True
    assert "live_probe_not_run" in health.warnings


def test_espn_normalize_event_timestamp_discipline():
    """provider_timestamp must be None when ESPN supplies no lastModified; kickoff_utc
    must come from event.date only — the two fields must never share the same value."""
    provider = ESPNProvider(enabled=True, live_tests=False)

    event = {
        "id": "abc123",
        "date": "2026-08-15T19:45:00Z",
        "status": {"type": {"name": "STATUS_SCHEDULED"}},
        "competitions": [
            {
                "competitors": [
                    {"homeAway": "home", "team": {"displayName": "Arsenal"}},
                    {"homeAway": "away", "team": {"displayName": "Chelsea"}},
                ]
            }
        ],
    }
    record = provider.normalize_event(event, "EPL")

    assert record["kickoff_utc"] == "2026-08-15T19:45:00Z"
    assert record["provider_timestamp"] is None, (
        "provider_timestamp must be None when ESPN response has no lastModified"
    )


def test_espn_normalize_event_uses_last_modified_when_present():
    provider = ESPNProvider(enabled=True, live_tests=False)

    event = {
        "id": "xyz",
        "date": "2026-08-15T19:45:00Z",
        "lastModified": "2026-08-15T20:01:30Z",
        "status": {"type": {"name": "STATUS_IN_PROGRESS"}},
        "competitions": [
            {
                "competitors": [
                    {"homeAway": "home", "team": {"displayName": "Liverpool"}},
                    {"homeAway": "away", "team": {"displayName": "Everton"}},
                ]
            }
        ],
    }
    record = provider.normalize_event(event, "EPL")

    assert record["kickoff_utc"] == "2026-08-15T19:45:00Z"
    assert record["provider_timestamp"] == "2026-08-15T20:01:30Z"
    assert record["kickoff_utc"] != record["provider_timestamp"]


def test_provider_registry_registers_canonical_provider_set():
    registry = build_provider_registry()
    provider_ids = {provider.provider_id for provider in registry.providers}

    assert provider_ids == {
        "espn",
        "football_data_org",
        "api_football",
        "sportmonks",
        "the_odds_api",
    }
    assert registry.get("espn").requires_key is False
    assert registry.get("the_odds_api").requires_key is True


def test_reconciliation_reports_ambiguity_instead_of_guessing():
    from datetime import datetime, timezone

    provider_record = FixtureCandidate(
        fixture_id="provider-a",
        provider="espn",
        provider_event_id="a",
        home_team="Arsenal",
        away_team="Chelsea",
        kickoff_utc=datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc),
        competition="EPL",
    )
    candidates = [
        FixtureCandidate(
            fixture_id="fixture-1",
            provider="football_data_org",
            provider_event_id="b",
            home_team="Arsenal",
            away_team="Chelsea",
            kickoff_utc=datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc),
            competition="EPL",
        ),
        FixtureCandidate(
            fixture_id="fixture-2",
            provider="api_football",
            provider_event_id="c",
            home_team="Arsenal",
            away_team="Chelsea",
            kickoff_utc=datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc),
            competition="EPL",
        ),
    ]

    decision = reconcile_fixture(provider_record, candidates)

    assert decision.status == "CONFLICTING"
    assert decision.fixture_id is None
    assert decision.reason == "ambiguous_candidate"


def test_reconciliation_requires_review_for_single_low_confidence_candidate():
    """A single plausible-but-imperfect candidate is reviewable, not unknown.

    Distinct from CONFLICTING (multiple equally-scored candidates) and from
    UNKNOWN (no candidate at all): here there is exactly one candidate that
    cleared the kickoff/competition filter but didn't reach the auto-accept
    confidence bar, so a human reviewer needs the fixture_id to confirm it.
    """
    from datetime import datetime, timezone

    # "Man United" vs "Manchester United" is a single-field abbreviation with
    # an otherwise exact match (away team + kickoff) — scores ~0.896 with
    # SequenceMatcher, comfortably inside [REVIEW_THRESHOLD, AUTO_ACCEPT_THRESHOLD).
    provider_record = FixtureCandidate(
        fixture_id="provider-a",
        provider="espn",
        provider_event_id="a",
        home_team="Man United",
        away_team="Chelsea",
        kickoff_utc=datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc),
        competition="EPL",
    )
    candidates = [
        FixtureCandidate(
            fixture_id="fixture-1",
            provider="football_data_org",
            provider_event_id="b",
            home_team="Manchester United",
            away_team="Chelsea",
            kickoff_utc=datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc),
            competition="EPL",
        ),
    ]

    decision = reconcile_fixture(provider_record, candidates)

    assert decision.status == "REQUIRES_REVIEW"
    assert decision.fixture_id is None
    assert decision.review_candidate_id == "fixture-1"
    assert decision.reason == "below_auto_accept_threshold_but_reviewable"


def test_reconciliation_unknown_only_when_no_candidate_exists():
    from datetime import datetime, timezone

    provider_record = FixtureCandidate(
        fixture_id="provider-a",
        provider="espn",
        provider_event_id="a",
        home_team="Arsenal",
        away_team="Chelsea",
        kickoff_utc=datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc),
        competition="EPL",
    )

    decision = reconcile_fixture(provider_record, [])

    assert decision.status == "UNKNOWN"
    assert decision.fixture_id is None
    assert decision.reason == "no_candidate"


def test_redact_url_scrubs_api_token_query_param():
    from src.providers.base import redact_url

    url = "https://api.sportmonks.com/v3/football/sidelined?api_token=SECRET123&include=x"
    redacted = redact_url(url)
    assert "SECRET123" not in redacted
    assert "api_token=%5BREDACTED%5D" in redacted or "api_token=[REDACTED]" in redacted


def test_redact_text_scrubs_tokens_embedded_in_exception_messages():
    from src.providers.base import redact_text

    # httpx.HTTPStatusError embeds the full request URL in its message
    message = (
        "Client error '404 Not Found' for url "
        "'https://api.sportmonks.com/v3/football/sidelined?api_token=SECRET123'"
    )
    redacted = redact_text(message)
    assert "SECRET123" not in redacted
    assert "api_token=[REDACTED]" in redacted
    # non-sensitive text is preserved
    assert "404 Not Found" in redacted


def test_redact_text_handles_multiple_sensitive_params():
    from src.providers.base import redact_text

    text = "https://x.test/?apiKey=AAA&token=BBB&normal=keep"
    redacted = redact_text(text)
    assert "AAA" not in redacted and "BBB" not in redacted
    assert "normal=keep" in redacted


def test_redaction_scrubs_dsn_userinfo_and_bearer_tokens():
    from src.core.redaction import redact_text, redact_url, safe_endpoint

    dsn = "rediss://default:SUPERSECRET@cache.example.com:6379/0"
    message = f"connection failed for {dsn}; Authorization: Bearer abc.def-123"

    redacted = redact_text(message)
    assert "SUPERSECRET" not in redacted
    assert "abc.def-123" not in redacted
    assert "rediss://[REDACTED]@cache.example.com:6379/0" in redacted
    assert "Bearer [REDACTED]" in redacted

    assert redact_url(dsn) == "rediss://cache.example.com:6379/0"
    assert safe_endpoint(dsn) == "rediss://cache.example.com:6379"
