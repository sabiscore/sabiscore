"""Pins the frozen uncertainty-certification policy (ADR 0009).

Mirrors `test_certification_policy.py`: the policy is a specification written
BEFORE its implementation, so what can be checked today is that it stays frozen,
stays honest about not being implemented, and cannot be quietly mutated.

The gates themselves are exercised by the M2 implementation's own tests, which
do not exist yet — `test_specification_does_not_claim_to_be_implemented` is what
stops this module from being mistaken for a passing result in the meantime.
"""

from __future__ import annotations

import pytest

from src.models.uncertainty_policy import (
    AVAILABILITY_SEMANTICS,
    FORBIDDEN_EPISTEMIC_SOURCES,
    IMPLEMENTATION_STATUS,
    UNCERTAINTY_GATES,
    UNCERTAINTY_METHOD,
    UNCERTAINTY_POLICY_VERSION,
    uncertainty_policy,
    uncertainty_policy_sha256,
)


def test_specification_does_not_claim_to_be_implemented():
    """The gate must stay closed while only the specification exists.

    If this ever flips, the M2 implementation and its validation tests must have
    landed — not merely the intent to build them.
    """
    assert IMPLEMENTATION_STATUS["state"] == "SPECIFIED_NOT_IMPLEMENTED"
    assert IMPLEMENTATION_STATUS["gates_exercised"] is False
    assert IMPLEMENTATION_STATUS["gate_remains_closed"] == "MODEL_UNCERTAINTY_UNAVAILABLE"


def test_probability_derived_proxies_are_forbidden():
    """The whole point of ADR 0009: self-referential uncertainty cannot pass."""
    joined = " ".join(FORBIDDEN_EPISTEMIC_SOURCES).lower()
    for banned in ("1 - max(p)", "entropy(p)", "1 - confidence", "expected_brier_score(p)"):
        assert banned.lower() in joined, f"{banned} must remain explicitly forbidden"
    assert UNCERTAINTY_METHOD == "ensemble_dispersion"


def test_availability_never_permits_a_fallback_value():
    """`available=true` must require a real computation, never a substitute."""
    assert "no_fallback" in AVAILABILITY_SEMANTICS
    assert "forbidden" in AVAILABILITY_SEMANTICS["no_fallback"].lower()


def test_policy_is_deep_copied_so_it_cannot_be_mutated_in_process():
    """Same defect `certification_policy()` was fixed for.

    Returning the module dicts by reference would let a caller rewrite the
    "frozen" policy, and because the digest hashes those same objects it would
    move with the mutation and report the tampered policy as authentic.
    """
    before = uncertainty_policy_sha256()
    grabbed = uncertainty_policy()
    grabbed["gates"]["independence_from_confidence"]["threshold"][
        "max_abs_confidence_correlation"
    ] = 0.999
    grabbed["forbidden_epistemic_sources"].clear()

    assert uncertainty_policy_sha256() == before, "policy digest moved after caller mutation"
    assert (
        UNCERTAINTY_GATES["independence_from_confidence"]["threshold"][
            "max_abs_confidence_correlation"
        ]
        == 0.70
    )
    assert FORBIDDEN_EPISTEMIC_SOURCES, "module constant was emptied by a caller"


def test_digest_is_stable_and_content_addressed():
    # The default-argument path and an explicitly-passed policy must agree —
    # comparing the function to itself would be a tautology that proves nothing.
    assert uncertainty_policy_sha256(uncertainty_policy()) == uncertainty_policy_sha256()
    assert len(uncertainty_policy_sha256()) == 64

    perturbed = uncertainty_policy()
    perturbed["policy_version"] = "9.9.9"
    assert uncertainty_policy_sha256(perturbed) != uncertainty_policy_sha256()


@pytest.mark.parametrize("gate", sorted(UNCERTAINTY_GATES))
def test_every_gate_declares_a_rule_and_a_verifiable_source(gate):
    entry = UNCERTAINTY_GATES[gate]
    assert entry["rule"].strip(), f"{gate} has no stated rule"
    assert entry["source"].strip(), f"{gate} has no source to verify against"
    assert "threshold" in entry, f"{gate} declares no threshold"


def test_policy_version_is_semver():
    parts = UNCERTAINTY_POLICY_VERSION.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)
