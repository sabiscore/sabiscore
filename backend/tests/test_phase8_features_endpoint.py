"""Phase 8 Sprint 2: phase8-features endpoint unit tests.

Validates:
  P8-1: endpoint returns correct shape with phase8 disabled (status="disabled")
  P8-2: feature registry exports are consistent (counts, no overlap with P7)
  P8-3: DEFAULT_FEATURE_VALUES_86 covers all CANONICAL_FEATURES_86 keys
  P8-4: PHASE8_FEATURES_18 contains exactly 21 features (legacy name)
  P8-5: Pi / Berrar / EWMA / Market / Context group counts are stable
"""

from __future__ import annotations

import sys
import os

import pytest

# ── registry imports ─────────────────────────────────────────────────────────

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.models.feature_registry import (
    CANONICAL_FEATURES_58,
    CANONICAL_FEATURES_83,
    CANONICAL_FEATURES_86,
    DEFAULT_FEATURE_VALUES_86,
    PHASE7_FEATURES_7,
    PHASE7_FEATURES_REMOVED,
    PHASE8_FEATURES_PI,
    PHASE8_FEATURES_BERRAR,
    PHASE8_FEATURES_FORM,
    PHASE8_FEATURES_MARKET,
    PHASE8_FEATURES_CONTEXT,
    PHASE8_FEATURES_18,
    canonical_feature_count_phase8,
)


# ── P8-2 / P8-3 / P8-4 / P8-5: Registry invariants ──────────────────────────


class TestPhase8RegistryInvariants:
    """Static invariants on the Phase 8 feature registry."""

    def test_phase8_features_18_actual_count_is_21(self):
        """PHASE8_FEATURES_18 has 21 entries despite the legacy _18 suffix."""
        assert len(PHASE8_FEATURES_18) == 21, (
            f"Expected 21 Phase 8 features (legacy name PHASE8_FEATURES_18), "
            f"got {len(PHASE8_FEATURES_18)}"
        )

    def test_numeric_suffix_names_match_their_own_length(self):
        """A constant named `_N` must hold N entries. `PHASE8_FEATURES_18` (21) and
        `CANONICAL_FEATURES_83` (86) both drifted from their own names for a whole
        release — this pins the accurate names so the next group that grows renames
        its constant instead of quietly outgrowing it. Deprecated aliases are
        exempt by construction: they are excluded by name, not by count."""
        import re

        from src.models import feature_registry

        deprecated_aliases = {
            "PHASE8_FEATURES_18",
            "CANONICAL_FEATURES_83",
            "CANONICAL_FEATURES_86",
            "CANONICAL_FEATURES_65",
            "PHASE7_FEATURES_7",
        }
        mismatches = []
        for name in dir(feature_registry):
            match = re.fullmatch(r"(?:CANONICAL_FEATURES|PHASE\d+_FEATURES)_(\d+)", name)
            if not match or name in deprecated_aliases:
                continue
            claimed = int(match.group(1))
            actual = len(getattr(feature_registry, name))
            if claimed != actual:
                mismatches.append(f"{name} claims {claimed}, holds {actual}")

        assert not mismatches, "Feature-registry names disagree with their own length: " + "; ".join(mismatches)

    def test_canonical_features_86_count(self):
        """The Phase 8 set is 68 phase7 + 21 phase8 = 89. It was 86 while the Phase 7
        base was 65; restoring the three artifact-compatibility slots moved it, and
        CANONICAL_FEATURES_86 is now a deprecated alias for CANONICAL_FEATURES_89."""
        assert len(CANONICAL_FEATURES_86) == 89

    def test_canonical_features_83_is_alias_for_86(self):
        """CANONICAL_FEATURES_83 and CANONICAL_FEATURES_86 resolve identically."""
        assert CANONICAL_FEATURES_83 is CANONICAL_FEATURES_86 or CANONICAL_FEATURES_83 == CANONICAL_FEATURES_86

    def test_canonical_feature_count_phase8_function(self):
        assert canonical_feature_count_phase8() == 89

    def test_phase8_pi_group_count(self):
        assert len(PHASE8_FEATURES_PI) == 6

    def test_phase8_berrar_group_count(self):
        assert len(PHASE8_FEATURES_BERRAR) == 3

    def test_phase8_form_group_count(self):
        assert len(PHASE8_FEATURES_FORM) == 6

    def test_phase8_market_group_count(self):
        assert len(PHASE8_FEATURES_MARKET) == 5

    def test_phase8_context_group_count(self):
        assert len(PHASE8_FEATURES_CONTEXT) == 1

    def test_phase8_groups_sum_to_21(self):
        total = (
            len(PHASE8_FEATURES_PI)
            + len(PHASE8_FEATURES_BERRAR)
            + len(PHASE8_FEATURES_FORM)
            + len(PHASE8_FEATURES_MARKET)
            + len(PHASE8_FEATURES_CONTEXT)
        )
        assert total == 21

    def test_phase8_no_overlap_with_phase7(self):
        p7_set = set(PHASE7_FEATURES_7)
        p8_set = set(PHASE8_FEATURES_18)
        overlap = p7_set & p8_set
        assert overlap == set(), f"Phase 7/8 feature overlap: {overlap}"

    def test_phase8_no_overlap_with_base_58(self):
        base_set = set(CANONICAL_FEATURES_58)
        p8_set = set(PHASE8_FEATURES_18)
        overlap = base_set & p8_set
        assert overlap == set(), f"Base-58/Phase-8 feature overlap: {overlap}"

    def test_phase8_removed_features_are_present_but_permanently_gapped(self):
        """Re-scoped 2026-08-08. The three removed features occupy vector slots for
        v5_phase7 artifact compatibility (all six .pkl files expect 68 columns), but
        every one is pinned to DATA_GAP so no live value is ever computed for it —
        which is the property that actually matters."""
        from src.models.feature_registry import PHASE7_FEATURES_ALWAYS_DATA_GAP

        for feat in PHASE7_FEATURES_REMOVED:
            assert feat in CANONICAL_FEATURES_86
            assert feat in PHASE7_FEATURES_ALWAYS_DATA_GAP, (
                f"'{feat}' occupies a slot but is not pinned to DATA_GAP"
            )

    def test_default_values_86_covers_all_canonical_86(self):
        """DEFAULT_FEATURE_VALUES_86 must have a value for every feature in CANONICAL_FEATURES_86."""
        missing = [f for f in CANONICAL_FEATURES_86 if f not in DEFAULT_FEATURE_VALUES_86]
        assert missing == [], f"DEFAULT_FEATURE_VALUES_86 missing keys: {missing}"

    def test_canonical_86_no_duplicates(self):
        seen: set[str] = set()
        dupes: list[str] = []
        for f in CANONICAL_FEATURES_86:
            if f in seen:
                dupes.append(f)
            seen.add(f)
        assert dupes == [], f"Duplicate features in CANONICAL_FEATURES_86: {dupes}"


# ── P8-1: Endpoint helpers (no live server needed) ────────────────────────────


class TestPhase8EndpointHelpers:
    """Isolated tests for phase8_features endpoint logic."""

    def test_phase8_disabled_flag_returns_false_by_default(self, monkeypatch):
        from src.api.endpoints.phase8_features import _is_phase8_enabled, settings

        os.environ.pop("USE_PHASE8_FEATURES", None)
        # Pin the settings fallback so a local .env with phase8 enabled
        # cannot flip this default-contract test (read-only property -> patch class).
        monkeypatch.setattr(type(settings), "phase8_enabled", property(lambda self: False))
        assert _is_phase8_enabled() is False

    def test_phase8_enabled_flag_true(self):
        from src.api.endpoints.phase8_features import _is_phase8_enabled

        os.environ["USE_PHASE8_FEATURES"] = "true"
        try:
            assert _is_phase8_enabled() is True
        finally:
            os.environ.pop("USE_PHASE8_FEATURES", None)

    def test_build_feature_values_fills_all_phase8_features(self):
        """_build_feature_values returns an entry for all 21 Phase 8 features."""
        from src.api.endpoints.phase8_features import _build_feature_values

        gaps: list[str] = []
        result = _build_feature_values({}, gaps)
        assert len(result) == 21
        assert set(result.keys()) == set(PHASE8_FEATURES_18)

    def test_build_feature_values_marks_all_as_gap_when_empty(self):
        from src.api.endpoints.phase8_features import _build_feature_values

        gaps: list[str] = []
        result = _build_feature_values({}, gaps)
        assert all(fv.is_data_gap for fv in result.values())
        assert len(gaps) == 21

    def test_build_feature_values_live_overrides_default(self):
        from src.api.endpoints.phase8_features import _build_feature_values

        live = {"home_pi_attack": 0.72, "pi_attack_diff": -0.15}
        gaps: list[str] = []
        result = _build_feature_values(live, gaps)

        assert result["home_pi_attack"].value == pytest.approx(0.72)
        assert result["home_pi_attack"].is_data_gap is False
        assert result["home_pi_attack"].source == "live"

        assert result["pi_attack_diff"].value == pytest.approx(-0.15)
        assert result["pi_attack_diff"].is_data_gap is False

        # All others should be gaps
        assert "home_pi_attack" not in gaps
        assert "pi_attack_diff" not in gaps

    def test_build_groups_returns_five_groups(self):
        from src.api.endpoints.phase8_features import _build_feature_values, _build_groups

        gaps: list[str] = []
        fv_map = _build_feature_values({}, gaps)
        groups = _build_groups(fv_map)
        assert len(groups) == 5

    def test_build_groups_all_not_available_when_gaps(self):
        from src.api.endpoints.phase8_features import _build_feature_values, _build_groups

        gaps: list[str] = []
        fv_map = _build_feature_values({}, gaps)
        groups = _build_groups(fv_map)
        assert all(not g.all_available for g in groups)

    def test_build_groups_all_available_when_fully_live(self):
        from src.api.endpoints.phase8_features import _build_feature_values, _build_groups
        from src.models.feature_registry import DEFAULT_FEATURE_VALUES_86

        live = {f: DEFAULT_FEATURE_VALUES_86.get(f, 0.0) for f in PHASE8_FEATURES_18}
        gaps: list[str] = []
        fv_map = _build_feature_values(live, gaps)
        groups = _build_groups(fv_map)
        assert all(g.all_available for g in groups)

    def test_build_groups_none_freshness_does_not_crash(self):
        """_build_groups must not crash when live features have freshness_seconds=None."""
        from src.api.endpoints.phase8_features import _build_feature_values, _build_groups
        from src.models.feature_registry import DEFAULT_FEATURE_VALUES_86

        # Live values, no per_feature_freshness supplied → all freshness_seconds=None
        live = {f: DEFAULT_FEATURE_VALUES_86.get(f, 0.0) for f in PHASE8_FEATURES_18}
        gaps: list[str] = []
        fv_map = _build_feature_values(live, gaps)
        groups = _build_groups(fv_map)
        # group_freshness_seconds defaults to 0 when all live features have None freshness
        for group in groups:
            assert group.group_freshness_seconds == 0

    def test_build_feature_values_carries_source(self):
        """per_feature_source entries must propagate to FeatureValue.source."""
        from src.api.endpoints.phase8_features import _build_feature_values

        live = {"home_pi_attack": 0.65}
        sources = {"home_pi_attack": "pi_ratings"}
        gaps: list[str] = []
        fv_map = _build_feature_values(live, gaps, per_feature_source=sources)

        assert fv_map["home_pi_attack"].source == "pi_ratings", (
            "per_feature_source entry must be carried to FeatureValue.source"
        )

    def test_build_feature_values_data_gap_source_is_registry_default(self):
        """DATA_GAP features with no explicit source get 'registry_default' source."""
        from src.api.endpoints.phase8_features import _build_feature_values

        gaps: list[str] = []
        fv_map = _build_feature_values({}, gaps)

        for fv in fv_map.values():
            assert fv.source == "registry_default", (
                f"DATA_GAP feature '{fv.name}' should have source='registry_default', "
                f"got {fv.source!r}"
            )

    def test_build_feature_values_freshness_none_for_data_gaps(self):
        """DATA_GAP features must have freshness_seconds=None (not 0)."""
        from src.api.endpoints.phase8_features import _build_feature_values

        gaps: list[str] = []
        fv_map = _build_feature_values({}, gaps)

        for fv in fv_map.values():
            assert fv.freshness_seconds is None, (
                f"DATA_GAP feature '{fv.name}' must have freshness_seconds=None, "
                f"got {fv.freshness_seconds!r}"
            )


# ── Phase8FeaturesResponse schema invariants ──────────────────────────────────


class TestPhase8ResponseSchema:
    """Verify Phase8FeaturesResponse includes all required Phase 1 fields."""

    def test_response_has_feature_source_field(self):
        """Phase8FeaturesResponse must expose feature_source as a top-level dict."""
        from src.api.endpoints.phase8_features import Phase8FeaturesResponse

        assert hasattr(Phase8FeaturesResponse.model_fields, "feature_source") or \
               "feature_source" in Phase8FeaturesResponse.model_fields, (
            "Phase8FeaturesResponse missing required 'feature_source' field"
        )

    def test_response_has_feature_freshness_seconds_field(self):
        from src.api.endpoints.phase8_features import Phase8FeaturesResponse

        assert "feature_freshness_seconds" in Phase8FeaturesResponse.model_fields

    def test_response_feature_source_default_empty_dict(self):
        """feature_source must default to an empty dict (not None)."""
        from src.api.endpoints.phase8_features import Phase8FeaturesResponse, _build_feature_values, _build_groups
        from src.models.feature_registry import PHASE8_FEATURES_18

        gaps: list[str] = list(PHASE8_FEATURES_18)
        fv_map = _build_feature_values({}, gaps)
        groups = _build_groups(fv_map)

        resp = Phase8FeaturesResponse(
            match_id="test_match_id_schema",
            league="EPL",
            status="partial",
            data_gaps=gaps,
            feature_groups=groups,
            available_features=0,
            phase8_enabled=True,
        )
        assert isinstance(resp.feature_source, dict)
        assert resp.feature_source == {}

    def test_response_feature_source_populated_when_provided(self):
        """feature_source dict in response must carry projector-supplied source strings."""
        from src.api.endpoints.phase8_features import Phase8FeaturesResponse, _build_feature_values, _build_groups
        from src.models.feature_registry import PHASE8_FEATURES_MARKET

        live = {f: 0.0 for f in PHASE8_FEATURES_MARKET}
        sources = {f: "odds_service" for f in PHASE8_FEATURES_MARKET}
        gaps: list[str] = []
        fv_map = _build_feature_values(live, gaps, per_feature_source=sources)
        groups = _build_groups(fv_map)

        source_out = {k: v for k, v in sources.items()}
        resp = Phase8FeaturesResponse(
            match_id="test_match_id_source",
            league="EPL",
            status="ok",
            data_gaps=[],
            feature_groups=groups,
            feature_freshness_seconds={},
            feature_source=source_out,
            available_features=len(PHASE8_FEATURES_MARKET),
            phase8_enabled=True,
        )
        for feat in PHASE8_FEATURES_MARKET:
            assert resp.feature_source.get(feat) == "odds_service", (
                f"feature_source['{feat}'] should be 'odds_service'"
            )
