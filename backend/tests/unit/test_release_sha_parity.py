"""Exact production release-identity parity regressions."""

from __future__ import annotations

import pytest

from scripts.verify_release_sha_parity import evaluate_release_parity

SHA = "2beb31e0d4ed8c340fa55ea0063af93daae1d4f7"


def test_release_parity_passes_only_when_all_independent_shas_match() -> None:
    result = evaluate_release_parity(
        expected_sha=SHA,
        backend_payload={"release_sha": SHA},
        frontend_payload={"vercelSha": SHA, "backendSha": SHA},
    )

    assert result["status"] == "PASS"
    assert result["errors"] == []


@pytest.mark.parametrize(
    ("backend_sha", "vercel_sha", "proxied_backend_sha"),
    [
        ("a" * 40, SHA, SHA),
        (SHA, "b" * 40, SHA),
        (SHA, SHA, "c" * 40),
    ],
)
def test_release_parity_fails_on_any_exact_sha_mismatch(
    backend_sha: str,
    vercel_sha: str,
    proxied_backend_sha: str,
) -> None:
    result = evaluate_release_parity(
        expected_sha=SHA,
        backend_payload={"release_sha": backend_sha},
        frontend_payload={
            "vercelSha": vercel_sha,
            "backendSha": proxied_backend_sha,
        },
    )

    assert result["status"] == "FAIL"
    assert result["errors"]


def test_release_parity_fails_closed_when_runtime_sha_is_unknown() -> None:
    result = evaluate_release_parity(
        expected_sha=SHA,
        backend_payload={"release_sha": None},
        frontend_payload={"vercelSha": SHA, "backendSha": SHA},
    )

    assert result["status"] == "FAIL"
    assert "release_sha must be an exact 40-character Git SHA" in result["errors"]


def test_release_parity_rejects_truncated_expected_sha() -> None:
    with pytest.raises(ValueError, match="exact 40-character"):
        evaluate_release_parity(
            expected_sha="2beb31e",
            backend_payload={"release_sha": SHA},
            frontend_payload={"vercelSha": SHA, "backendSha": SHA},
        )
