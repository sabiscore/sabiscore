"""Regression guard: production scraper adapters must never synthesize evidence."""

from pathlib import Path

SCRAPER_DIR = Path(__file__).resolve().parents[1] / "src" / "data" / "scrapers"
CANONICAL_INGESTION_FILE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "services"
    / "canonical_manifest_ingestion.py"
)
FORBIDDEN_TOKENS = (
    "random.uniform(",
    "random.randint(",
    "_simulate_",
    "simulated_data",
    "generate_mock",
)
FORBIDDEN_INGESTION_TOKENS = (
    "betting_intelligence",
    "core_engine",
    "ultra_prediction",
    "value_bet",
)


def test_legacy_scrapers_do_not_generate_synthetic_football_evidence() -> None:
    offenders: list[str] = []
    for path in sorted(SCRAPER_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8").lower()
        for token in FORBIDDEN_TOKENS:
            if token.lower() in source:
                offenders.append(f"{path.name}: {token}")
    assert not offenders, "Synthetic production scraper paths found:\n" + "\n".join(offenders)


def test_canonical_manifest_ingestion_stays_data_only() -> None:
    source = CANONICAL_INGESTION_FILE.read_text(encoding="utf-8").lower()
    offenders = [token for token in FORBIDDEN_INGESTION_TOKENS if token in source]
    assert not offenders, (
        "Canonical manifest ingestion imported prediction/betting surfaces:\n"
        + "\n".join(offenders)
    )
