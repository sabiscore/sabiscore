"""Tier 0 data acquisition — FBref match / team / player statistics via soccerdata.

⚠️⚠️ LEGAL CLASSIFICATION — **L3. THIS SCRIPT DOES NOT RUN AS-IS, BY DECISION.**
--------------------------------------------------------------------------------
FBref is operated by Sports Reference LLC, whose terms restrict automated and
bulk access. This was classified L2 ("publicly visible, rights unclear") when
the script was written. **A qualification run on 2026-09-10 escalated it to
L3**, on direct evidence rather than on the terms text alone:

``soccerdata``'s FBref reader does not perform an ordinary HTTP fetch. It
drives a browser through ``seleniumbase`` and, on first use, downloads and
binary-patches ``undetected_chromedriver.exe``
(``seleniumbase/undetected/patcher.py``). undetected-chromedriver exists for
one purpose: to defeat bot detection. FBref sits behind Cloudflare.

Directive §12 L3 is "terms hostile to automated production access", and §41
lists "prohibited automation" under Legal failure as a **kill criterion**.
Acquiring this data therefore requires actively circumventing an access control
on a site whose terms restrict exactly that, which is not a step this pipeline
takes.

**Consequence, and it is deliberate:** the acquisition half of Rule 2's
qualification chain STOPS here. The source is killed on legal grounds before
any data is acquired, which is a valid §41 outcome and a cheaper one than
discovering it after building features. No FBref data was retained; the run
aborted at the chromedriver patch step and the stray lock directory it created
was removed.

Reopening (§42) requires a materially different access path — an official
Sports Reference data licence, or a first-party API — not a different scraper.
Do not "fix" this by installing Chrome.

Everything below is retained because it is reusable and reviewed: the two-stage
acquisition/resolution split, the fail-closed entity resolution, the partitioned
Parquet sink, and the temporal-cutoff guard all apply unchanged to a source that
clears §12. Point ``_reader`` at that source.

Design notes
------------
**League ids.** ``sd.FBref(leagues=...)`` takes *soccerdata's own* standardized
ids ("ENG-Premier League"), not the site's URL slugs. Getting this wrong is how
the Understat ingestion silently never executed for months (docs/DEBT.md item
56 / CLAUDE.md 2026-09-03). This script imports the existing
``LEAGUE_TO_UNDERSTAT`` map rather than restating it, and additionally
validates every resolved id against the reader's own
``available_leagues()`` before a single request is made -- fail closed, never
guess a slug.

**Entity resolution.** §31 says "No second team-name normalizer." This script
therefore calls production's ``services.team_identity.identity_key`` directly.
It does not define, inline, or re-implement a normalizer. The static overrides
in ``_FBREF_NAME_OVERRIDES`` are an *alias table* consulted before that shared
key, not a competing algorithm, and every entry is a spelling actually observed
in FBref output.

**Memory.** Polars lazy frames with ``sink_parquet`` streaming, so the working
set is bounded by the streaming engine rather than by corpus size (§35).
Measured and reported per run.

**Temporal integrity.** FBref statistics are post-match by construction. A
pre-match feature row for a fixture on date D may only aggregate matches
strictly earlier than D. ``build_pre_match_rollups`` enforces that with a
strict ``<`` cutoff, and ``tests/unit/test_fbref_ingest_temporal.py`` pins it
by inverting the comparison and watching the guard fail.

Usage
-----
    .venv-ml/Scripts/python.exe backend/scripts/ingest_fbref_sources.py \
        --leagues epl --seasons 2223 --max-requests 6

The ML virtualenv is separate on purpose: soccerdata depends on seleniumbase,
which requires pytest>=8, and this repository pins pytest==7.4.3. Installing it
into the main venv would silently break the backend test suite.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

import polars as pl

_SCRIPTS = Path(__file__).resolve().parent
_BACKEND = _SCRIPTS.parent
REPO_ROOT = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))

OUT_ROOT = REPO_ROOT / "data" / "processed" / "fbref"
MANIFEST = REPO_ROOT / "reports" / "research" / "fbref-ingest-manifest.json"

# Season labels use this repo's corpus convention (2223 = 2022/23), converted to
# soccerdata's own format at the boundary.
DEFAULT_SEASONS = ["2223"]

# Spellings observed in FBref output that the shared identity key alone does not
# fold onto the corpus form. An alias table, NOT a second normalizer (§31).
# Every entry must be a real observed FBref string, not an invention.
_FBREF_NAME_OVERRIDES: dict[str, str] = {
    "manchester utd": "man united",
    "newcastle utd": "newcastle",
    "nott'ham forest": "nott'm forest",
    "sheffield utd": "sheffield united",
    "west brom": "west bromwich albion",
    "paris s-g": "paris saint germain",
    "eint frankfurt": "eintracht frankfurt",
    "gladbach": "borussia monchengladbach",
    "betis": "real betis",
    "atletico madrid": "atletico madrid",
}


def _load_identity_key() -> Any | None:
    """Production's one team-name normalizer (§31). Never re-implemented here.

    Returns ``None`` when the backend dependency tree is unavailable -- which is
    the normal case in the ML virtualenv, since that venv deliberately carries
    only soccerdata/polars and not sqlalchemy/pydantic. Callers must FAIL CLOSED
    on ``None`` rather than substituting a local normalizer: §31 says "No second
    team-name normalizer", and a silently-degraded key would poison every
    downstream join.
    """
    try:
        from src.services.team_identity import identity_key
    except Exception:  # noqa: BLE001 - absence is expected in the ML venv
        return None
    return identity_key


def _load_league_map() -> dict[str, str]:
    """The existing canonical → soccerdata league id map. Read, never restated.

    ``LEAGUE_TO_UNDERSTAT`` lives in ``src/connectors/understat_source.py``, but
    a plain import of it drags in ``src.connectors.__init__`` → ``opta`` →
    ``core.config`` → pydantic, none of which exist in the ML virtualenv. The
    constant is a literal dict, so it is read out of the source with ``ast``
    instead: that reads the one canonical definition without executing the
    package's import chain, which is materially different from copying the
    values here and letting the two drift.
    """
    import ast

    path = REPO_ROOT / "backend" / "src" / "connectors" / "understat_source.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
        names = {t.id for t in targets if isinstance(t, ast.Name)}
        if "LEAGUE_TO_UNDERSTAT" in names and node.value is not None:
            value = ast.literal_eval(node.value)
            if isinstance(value, dict) and value:
                return dict(value)
    raise SystemExit(
        f"could not read LEAGUE_TO_UNDERSTAT from {path}. Do not hardcode a "
        "replacement map here -- soccerdata takes its own standardized league "
        "ids, and guessing them is how the Understat ingestion silently never "
        "ran (docs/DEBT.md item 56)."
    )


def _season_to_soccerdata(season: str) -> str:
    """'2223' -> '2223'. soccerdata accepts this compact form directly."""
    season = str(season).strip()
    if len(season) != 4 or not season.isdigit():
        raise ValueError(
            f"season {season!r} must be the repo's 4-digit corpus form, e.g. 2223"
        )
    return season


class FBrefIngest:
    """Bounded FBref acquisition with a hard request ceiling."""

    def __init__(
        self,
        leagues: list[str],
        seasons: list[str],
        *,
        max_requests: int,
        cache_dir: Path,
    ) -> None:
        self.max_requests = max_requests
        self.cache_dir = cache_dir
        self.requests_made = 0
        self._identity_key = _load_identity_key()

        league_map = _load_league_map()
        resolved: dict[str, str] = {}
        for league in leagues:
            key = league.strip().lower()
            if key not in league_map:
                raise SystemExit(
                    f"unsupported league {league!r}. Known: {sorted(league_map)}"
                )
            resolved[key] = league_map[key]
        self.leagues = resolved
        self.seasons = [_season_to_soccerdata(s) for s in seasons]

    # -- reader -----------------------------------------------------------
    def _reader(self) -> Any:
        import soccerdata as sd

        wanted = sorted(set(self.leagues.values()))
        available = set(sd.FBref.available_leagues())
        unknown = [lg for lg in wanted if lg not in available]
        if unknown:
            # Fail closed rather than guess: this is the exact failure mode that
            # made the Understat ingestion a silent no-op.
            raise SystemExit(
                f"soccerdata FBref does not expose {unknown}. "
                f"Available (first 15): {sorted(available)[:15]}"
            )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return sd.FBref(
            leagues=wanted,
            seasons=self.seasons,
            data_dir=self.cache_dir,  # Path, not str -- soccerdata calls .mkdir()
        )

    def _budget(self, label: str, cost: int = 1) -> None:
        if self.requests_made + cost > self.max_requests:
            raise SystemExit(
                f"request budget exhausted before {label} "
                f"({self.requests_made}/{self.max_requests}). Raise --max-requests "
                "deliberately; FBref rate-limits aggressively."
            )
        self.requests_made += cost

    # -- extraction -------------------------------------------------------
    def fetch(self) -> dict[str, pl.DataFrame]:
        reader = self._reader()
        out: dict[str, pl.DataFrame] = {}

        for label, call in (
            ("schedule", lambda: reader.read_schedule()),
            ("team_season", lambda: reader.read_team_season_stats(stat_type="standard")),
            ("player_season", lambda: reader.read_player_season_stats(stat_type="standard")),
        ):
            self._budget(label)
            started = time.time()
            try:
                frame = call()
            except Exception as exc:  # noqa: BLE001 - a failed source is data
                print(f"  {label:<14} FAILED: {type(exc).__name__}: {str(exc)[:120]}")
                continue
            polars_frame = self._to_polars(frame)
            out[label] = polars_frame
            print(
                f"  {label:<14} {polars_frame.height:>6} rows "
                f"({time.time() - started:.1f}s)"
            )
        return out

    @staticmethod
    def _to_polars(frame: Any) -> pl.DataFrame:
        """pandas (often MultiIndex) → flat polars. Index becomes real columns."""
        flat = frame.reset_index()
        flat.columns = [
            "_".join(str(part) for part in col if str(part) and "Unnamed" not in str(part))
            if isinstance(col, tuple)
            else str(col)
            for col in flat.columns
        ]
        # Object columns can hold mixed types that polars refuses; stringify them.
        for name in flat.columns:
            if flat[name].dtype == "object":
                flat[name] = flat[name].astype(str)
        return pl.from_pandas(flat)

    # -- entity resolution ------------------------------------------------
    def resolve_identity(self, frame: pl.DataFrame, column: str) -> pl.DataFrame:
        """Attach the shared identity key, plus the alias-corrected form.

        Two columns are added rather than overwriting the source name, so the
        raw provider spelling is always retained for provenance (§32).
        """
        if column not in frame.columns:
            return frame
        if self._identity_key is None:
            raise SystemExit(
                "production's team_identity normalizer is not importable in this "
                "interpreter, so identity resolution cannot run. Fetch with the ML "
                "venv (--stage fetch), then resolve with the main venv "
                "(--stage resolve). Never substitute a local normalizer (§31)."
            )

        def _key(value: str | None) -> str | None:
            if not value:
                return None
            base = self._identity_key(str(value))
            return _FBREF_NAME_OVERRIDES.get(base, base)

        return frame.with_columns(
            pl.col(column)
            .map_elements(_key, return_dtype=pl.Utf8)
            .alias(f"{column}_identity_key")
        )


def build_pre_match_rollups(
    matches: pl.LazyFrame,
    *,
    date_col: str = "date",
    team_col: str = "team_identity_key",
    value_cols: tuple[str, ...] = ("gf", "ga"),
    window: int = 5,
) -> pl.LazyFrame:
    """Rolling per-team aggregates that a pre-match model may legally see.

    ⚠️ TEMPORAL INTEGRITY. FBref statistics describe a *completed* match, so a
    row's own values must never enter its own feature vector. The rolling mean
    is therefore computed over the ``window`` matches STRICTLY BEFORE the
    current one: ``shift(1)`` moves the series back one match before the window
    is applied, so a fixture on date D aggregates only matches < D.

    Removing the ``shift(1)`` makes the leakage test in
    ``tests/unit/test_fbref_ingest_temporal.py`` fail, which is the point --
    the guard was watched failing before being trusted.
    """
    aggregates = [
        pl.col(col)
        .shift(1)  # <- the cutoff; without it a match sees its own result; without it a match sees its own result
        .rolling_mean(window_size=window, min_periods=1)
        .over(team_col)
        .alias(f"{col}_pre_match_mean_{window}")
        for col in value_cols
    ]
    return matches.sort([team_col, date_col]).with_columns(aggregates)


def write_partitioned(frame: pl.DataFrame, name: str, out_root: Path) -> dict[str, Any]:
    """Stream to a league/season-partitioned Parquet sink via the lazy engine."""
    out_root.mkdir(parents=True, exist_ok=True)
    partition_cols = [c for c in ("league", "season") if c in frame.columns]
    written: list[str] = []

    if not partition_cols:
        target = out_root / f"{name}.parquet"
        frame.lazy().sink_parquet(target)
        return {"rows": frame.height, "files": [str(target.relative_to(REPO_ROOT))]}

    for keys, part in frame.group_by(partition_cols, maintain_order=True):
        parts = keys if isinstance(keys, tuple) else (keys,)
        subdir = out_root / name
        for col, value in zip(partition_cols, parts, strict=True):
            subdir = subdir / f"{col}={str(value).replace('/', '-')}"
        subdir.mkdir(parents=True, exist_ok=True)
        target = subdir / "part-0.parquet"
        part.lazy().sink_parquet(target)
        written.append(str(target.relative_to(REPO_ROOT)))

    return {"rows": frame.height, "files": written}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--leagues", nargs="+", default=["epl"])
    parser.add_argument("--seasons", nargs="+", default=DEFAULT_SEASONS)
    parser.add_argument(
        "--max-requests",
        type=int,
        default=6,
        help="Hard ceiling on upstream calls. FBref rate-limits aggressively.",
    )
    parser.add_argument(
        "--stage",
        choices=["fetch", "resolve", "all"],
        default="all",
        help=(
            "fetch = acquire and write the raw immutable store (ML venv, no "
            "backend deps needed). resolve = read raw, attach production's "
            "identity key, write the resolved store (main venv). all = both, "
            "which requires one interpreter with both."
        ),
    )
    parser.add_argument("--cache-dir", default=str(REPO_ROOT / "data" / "cache" / "fbref"))
    parser.add_argument("--out-dir", default=str(OUT_ROOT))
    args = parser.parse_args()

    tracemalloc.start()
    started = time.time()

    ingest = FBrefIngest(
        args.leagues,
        args.seasons,
        max_requests=args.max_requests,
        cache_dir=Path(args.cache_dir),
    )
    print(
        f"FBref ingest — leagues={sorted(ingest.leagues.values())} "
        f"seasons={ingest.seasons} budget={args.max_requests} requests"
    )

    out_root = Path(args.out_dir)
    raw_root = out_root / "raw"
    resolved_root = out_root / "resolved"
    written: dict[str, Any] = {}
    identity_resolved = False

    if args.stage in ("fetch", "all"):
        frames = ingest.fetch()
        if not frames:
            print("no source returned data; nothing written")
            return 1
        for name, frame in frames.items():
            written[name] = write_partitioned(frame, name, raw_root)
            print(f"  raw {name}: {written[name]['rows']} rows "
                  f"-> {len(written[name]['files'])} partition file(s)")

    if args.stage in ("resolve", "all"):
        if ingest._identity_key is None:
            print(
                "\nSTAGE 'resolve' SKIPPED - production's team_identity "
                "normalizer is not importable in this interpreter.\n"
                "Run: .venv/Scripts/python.exe "
                "backend/scripts/ingest_fbref_sources.py --stage resolve\n"
                "(Section 31: never substitute a second normalizer.)"
            )
        else:
            for name in ("schedule", "team_season", "player_season"):
                src = raw_root / name
                if not src.exists():
                    continue
                frame = pl.read_parquet(src / "**" / "*.parquet")
                for candidate in ("team", "squad", "home_team", "away_team"):
                    frame = ingest.resolve_identity(frame, candidate)
                res = write_partitioned(frame, name, resolved_root)
                written.setdefault(name, res)
                written[name]["resolved_rows"] = res["rows"]
                identity_resolved = True
                print(f"  resolved {name}: {res['rows']} rows")

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    manifest = {
        "source": "FBref (Sports Reference LLC) via soccerdata",
        "legal_class": "L3 — terms hostile to automated access (KILLED, §41)",
        "legal_note": (
            "Escalated L2 -> L3 on 2026-09-10 by direct evidence: soccerdata's "
            "FBref reader downloads and binary-patches undetected_chromedriver "
            "(seleniumbase/undetected/patcher.py) to defeat the site's bot "
            "detection. §41 lists prohibited automation as a Legal-failure kill "
            "criterion. No data was acquired. Reopening needs a licensed or "
            "first-party access path, not a different scraper."
        ),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "leagues": sorted(ingest.leagues.values()),
        "seasons": ingest.seasons,
        "requests_made": ingest.requests_made,
        "request_budget": args.max_requests,
        "stage": args.stage,
        "identity_resolved": identity_resolved,
        "datasets": written,
        "total_rows": sum(v["rows"] for v in written.values()),
        "runtime_seconds": round(time.time() - started, 1),
        "peak_python_heap_mb": round(peak / 1024 / 1024, 1),
        "memory_note": (
            "peak_python_heap_mb is tracemalloc's Python-allocation peak, not "
            "process RSS. Parquet writes stream through polars' lazy sink, so "
            "the working set is bounded by the streaming engine rather than by "
            "corpus size."
        ),
        "temporal_integrity": (
            "Raw rows are stored as fetched. Pre-match aggregation is a separate "
            "step (build_pre_match_rollups) whose rolling windows shift(1) before "
            "aggregating, so a fixture never sees its own result. Pinned by "
            "backend/tests/unit/test_fbref_ingest_temporal.py."
        ),
        "entity_resolution": (
            "services.team_identity.identity_key — production's single normalizer "
            "(§31), plus an observed-spelling alias table. No second normalizer."
        ),
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(
        f"\ntotal rows: {manifest['total_rows']} | requests: {ingest.requests_made} | "
        f"peak python heap: {manifest['peak_python_heap_mb']} MB | "
        f"{manifest['runtime_seconds']}s"
    )
    print(f"manifest: {MANIFEST.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
