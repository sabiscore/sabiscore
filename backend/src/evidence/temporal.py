"""Temporal Lineage Checker and Leakage Sentinel.

Directive V18.0 Section 3.1 & 3.2.
Guarantees Point-in-Time (PIT) compliance:
    t_feature <= t_evaluation < t_closing < t_kickoff
Blocks features with effective_at > information_cutoff or ambiguous provenance.
Fails closed on future-derived artifacts, post-match events, and retrospective data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence


class TemporalViolationError(ValueError):
    """Raised when an evidence observation violates point-in-time constraints."""


@dataclass(frozen=True)
class TemporalCheckResult:
    is_valid: bool
    feature_name: str
    effective_at: datetime
    information_cutoff: datetime
    kickoff_timestamp: datetime
    violation_reason: Optional[str] = None


class TemporalLineageChecker:
    """Enforces PIT constraints across feature projections."""

    @staticmethod
    def parse_iso(ts_str: str) -> datetime:
        """Parse ISO-8601 string to timezone-aware UTC datetime."""
        clean = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def verify_feature_timing(
        self,
        feature_name: str,
        source_effective_at: str | datetime,
        information_cutoff: str | datetime,
        kickoff_timestamp: str | datetime,
    ) -> TemporalCheckResult:
        """Check that effective_at <= information_cutoff < kickoff_timestamp."""
        eff = (
            self.parse_iso(source_effective_at)
            if isinstance(source_effective_at, str)
            else source_effective_at
        )
        cutoff = (
            self.parse_iso(information_cutoff)
            if isinstance(information_cutoff, str)
            else information_cutoff
        )
        kickoff = (
            self.parse_iso(kickoff_timestamp)
            if isinstance(kickoff_timestamp, str)
            else kickoff_timestamp
        )

        if eff > cutoff:
            return TemporalCheckResult(
                is_valid=False,
                feature_name=feature_name,
                effective_at=eff,
                information_cutoff=cutoff,
                kickoff_timestamp=kickoff,
                violation_reason=(
                    f"Leakage detected: feature '{feature_name}' effective_at ({eff.isoformat()}) "
                    f"> information_cutoff ({cutoff.isoformat()})"
                ),
            )

        if cutoff >= kickoff:
            return TemporalCheckResult(
                is_valid=False,
                feature_name=feature_name,
                effective_at=eff,
                information_cutoff=cutoff,
                kickoff_timestamp=kickoff,
                violation_reason=(
                    f"Cutoff invalid: information_cutoff ({cutoff.isoformat()}) "
                    f">= kickoff_timestamp ({kickoff.isoformat()})"
                ),
            )

        return TemporalCheckResult(
            is_valid=True,
            feature_name=feature_name,
            effective_at=eff,
            information_cutoff=cutoff,
            kickoff_timestamp=kickoff,
        )

    def audit_batch(
        self,
        features: Sequence[Dict[str, Any]],
        information_cutoff: str | datetime,
        kickoff_timestamp: str | datetime,
    ) -> List[TemporalCheckResult]:
        """Audit a collection of feature records. Fails closed if any record fails."""
        results = []
        for feat in features:
            name = feat.get("feature_name", "unknown")
            eff = feat.get("effective_at")
            if not eff:
                results.append(
                    TemporalCheckResult(
                        is_valid=False,
                        feature_name=name,
                        effective_at=datetime.min.replace(tzinfo=timezone.utc),
                        information_cutoff=(
                            self.parse_iso(information_cutoff)
                            if isinstance(information_cutoff, str)
                            else information_cutoff
                        ),
                        kickoff_timestamp=(
                            self.parse_iso(kickoff_timestamp)
                            if isinstance(kickoff_timestamp, str)
                            else kickoff_timestamp
                        ),
                        violation_reason=f"Ambiguous provenance: missing effective_at for '{name}'",
                    )
                )
                continue

            res = self.verify_feature_timing(
                feature_name=name,
                source_effective_at=eff,
                information_cutoff=information_cutoff,
                kickoff_timestamp=kickoff_timestamp,
            )
            results.append(res)
        return results


class LeakageSentinel:
    """Adversarial detector for post-match events and future-derived feature contamination."""

    PROHIBITED_FUTURE_SUBSTRINGS = (
        "final_score",
        "ft_score",
        "full_time",
        "post_match",
        "settled_result",
        "actual_goals",
        "retrospective",
        "future_",
    )

    @classmethod
    def scan_feature_schema(cls, feature_names: Sequence[str]) -> List[str]:
        """Detect prohibited post-match or future contamination columns."""
        flagged = []
        for feat in feature_names:
            lower = feat.lower()
            if any(sub in lower for sub in cls.PROHIBITED_FUTURE_SUBSTRINGS):
                flagged.append(feat)
        return flagged

    @classmethod
    def assert_no_leakage(
        cls,
        feature_names: Sequence[str],
        timing_results: Sequence[TemporalCheckResult],
    ) -> None:
        """Fail-closed assertion for any PIT leakage or contaminated columns."""
        contaminated = cls.scan_feature_schema(feature_names)
        if contaminated:
            raise TemporalViolationError(
                f"Contaminated future features detected in schema: {contaminated}"
            )

        failed_timing = [r for r in timing_results if not r.is_valid]
        if failed_timing:
            reasons = "; ".join(r.violation_reason or "" for r in failed_timing)
            raise TemporalViolationError(
                f"PIT boundary violation in {len(failed_timing)} features: {reasons}"
            )
