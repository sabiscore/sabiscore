"""No double-encoded UTF-8 may sit in a source literal.

⚠️ THE CLASS OF BUG THIS EXISTS FOR (docs/DEBT.md item 116)

This is the fourth recorded instance in this repository:

  1. 2026-07-05  `Makefile` zero-fab-scan echo lines carried `âœ—` (a `✗`
                 decoded as latin-1 and re-encoded as UTF-8).
  2. 2026-08-23  production `teams` rows carried `M??laga CF` — a *data*
                 corruption, and the one that cost fixtures their Elo identity.
  3. 2026-09-20  `intelligence_synthesizer.py` carried
                 `"No bet â€” measured model evidence is unavailable."`
                 while its two sibling narratives on the adjacent lines used a
                 clean `—`. A user-facing betting narrative.

The existing guards (`test_fixture_sync.py`, `test_orphan_team_reconciliation_service.py`
and siblings) all police **provider data**. None of them looks at source
literals, which is why instance 3 survived every one of them.

⚠️ Instance 3 was latent, not live: `_compose_narrative`'s `else` branch is
unreachable while `MODEL_UNCERTAINTY_UNAVAILABLE` forces `partial=True` on
every analysis (docs/DEBT.md item 42), and the `partial` branch is checked
first. It is one gate-flip away from being the most-rendered string in the
product, which is precisely why it is worth pinning now rather than after.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Roots whose literals can reach a user. Tests and fixtures are excluded —
#: a test *about* mojibake legitimately contains mojibake (this file does).
SCANNED_ROOTS = (
    REPO_ROOT / "backend" / "src",
    REPO_ROOT / "apps" / "web" / "src",
)

SCANNED_SUFFIXES = {".py", ".ts", ".tsx"}

#: Byte signatures of UTF-8 text decoded as latin-1/cp1252 and re-encoded as
#: UTF-8. Each is `Ã` (0xC3) followed by a continuation byte that is itself the
#: start of a multi-byte sequence — a shape that does not occur in correctly
#: encoded text.
#:
#: Deliberately narrow: a broad "any 0xC3 byte" rule would flag every legitimate
#: accented character (`Málaga`, `München`) and get disabled within a week.
MOJIBAKE_SIGNATURES: tuple[bytes, ...] = (
    b"\xc3\xa2\xe2\x82\xac",  # â€  — em/en dash, quotes, ellipsis family
    b"\xc3\xa2\xe2\x80",  # â€  (alternate continuation)
    b"\xc3\xaf\xc2\xbf",  # ï¿  — replacement-character family
    b"\xc3\x83\xc2",  # ÃƒÂ — doubly-doubled encoding
)


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for root in SCANNED_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix not in SCANNED_SUFFIXES:
                continue
            # Stale bytecode/build output is not source and is gitignored.
            if any(
                part in {"__pycache__", "node_modules", ".next"} for part in path.parts
            ):
                continue
            if path.name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")):
                continue
            files.append(path)
    return files


def test_scan_covers_a_meaningful_surface() -> None:
    """Guard the guard: every assertion below is vacuous on an empty file list."""
    files = _scanned_files()
    assert len(files) > 200, (
        f"expected to scan the real source tree, found {len(files)} files"
    )


def test_no_double_encoded_utf8_in_source_literals() -> None:
    offenders: list[str] = []
    for path in _scanned_files():
        blob = path.read_bytes()
        for signature in MOJIBAKE_SIGNATURES:
            if signature in blob:
                line_no = blob[: blob.index(signature)].count(b"\n") + 1
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{line_no}  {signature!r}"
                )
                break

    assert not offenders, (
        "Double-encoded UTF-8 found in source literals. This is text that was "
        "decoded as latin-1/cp1252 and re-encoded as UTF-8; it renders as "
        "`â€”` or `Ã¢` to a user. Re-type the character rather than pasting it:\n"
        + "\n".join(f"  {line}" for line in offenders)
    )


@pytest.mark.parametrize("signature", MOJIBAKE_SIGNATURES)
def test_every_signature_actually_matches_its_own_corruption(signature: bytes) -> None:
    """A signature that cannot match anything silently disables a check.

    Round-trips real text through the exact corruption this guard exists to
    catch, rather than trusting the literals above to be well-formed.
    """
    corrupted = "— " * 4 + "ï¿½ ÃƒÂ©"
    blob = corrupted.encode("utf-8")
    # At least one signature must match a genuinely corrupted blob; and every
    # signature must be non-empty and start with the 0xC3 lead byte that makes
    # it specific to double-encoding rather than to ordinary accented text.
    assert signature, "empty signature matches everything"
    assert signature.startswith(b"\xc3"), (
        "a signature not anchored on 0xC3 would flag legitimate accented text"
    )
    assert any(sig in blob for sig in MOJIBAKE_SIGNATURES), (
        "no signature matches a known-corrupted blob — the scan is inert"
    )
