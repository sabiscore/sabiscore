#!/usr/bin/env bash
#
# Local CI enforcement — mandatory while the GitHub Actions billing lock holds.
#
# WHY THIS EXISTS
# ---------------
# Every workflow run currently fails before step 1 with runner_name:"" and
# steps:0 (docs/DEBT.md items 16, 99). A red suite and a suite that never ran
# look identical from the outside, which is exactly how three defects reached
# master unnoticed in a single week (DEBT 96, 97, 98). Until the lock is
# administratively resolved, this script is the only thing standing between a
# regression and master.
#
# It mirrors .github/workflows/ci.yml rather than inventing its own checks, so
# that a clean run here means the same thing a green CI run would have meant.
#
# FAIL-CLOSED SEMANTICS
# ---------------------
# `set -euo pipefail` aborts on the first non-zero exit. Steps that genuinely
# cannot run in a local environment (Alembic needs a live PostgreSQL) are
# reported as SKIPPED with a reason and counted separately — a skip is never
# printed as a pass, and the final summary states plainly which gates were not
# exercised. Silence is not success.
#
# USAGE
#   ./scripts/ci_local_enforcer.sh              # full run
#   ./scripts/ci_local_enforcer.sh --fast       # skip the slow web build + e2e
#   DATABASE_URL=postgresql://... ./scripts/ci_local_enforcer.sh   # includes Alembic
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

FAST=0
[ "${1:-}" = "--fast" ] && FAST=1

# Prefer the repo virtualenv over whatever `python` resolves to on PATH — on
# Windows a bare `python` is usually the system interpreter with none of the
# scientific dependencies installed (the same trap Makefile's PYTHON_BIN
# documents).
if [ -x "$REPO_ROOT/.venv/Scripts/python.exe" ]; then
  PY="$REPO_ROOT/.venv/Scripts/python.exe"
elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PY="$REPO_ROOT/.venv/bin/python"
else
  echo "FATAL: no repo virtualenv at .venv — create it before running this gate." >&2
  exit 1
fi

PASSED=0
SKIPPED=0
SKIPPED_NAMES=()
STARTED_AT=$SECONDS

hr() { printf '%s\n' "────────────────────────────────────────────────────────────────"; }

# Run a required step. Any non-zero exit aborts the whole script via `set -e`.
step() {
  local name="$1"; shift
  hr
  printf '▶  %s\n' "$name"
  hr
  local t0=$SECONDS
  "$@"
  printf '✓  %s  (%ss)\n\n' "$name" "$((SECONDS - t0))"
  PASSED=$((PASSED + 1))
}

# Record a gate that could not be exercised here. Counted and re-stated in the
# summary so it can never be mistaken for a pass.
skip() {
  local name="$1" reason="$2"
  hr
  printf '⊘  SKIPPED: %s\n   reason: %s\n\n' "$name" "$reason"
  SKIPPED=$((SKIPPED + 1))
  SKIPPED_NAMES+=("$name — $reason")
}

printf '\n'
hr
printf 'SabiScore local CI enforcer\n'
printf 'repo:   %s\n' "$REPO_ROOT"
printf 'python: %s\n' "$PY"
printf 'commit: %s\n' "$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
printf 'branch: %s\n' "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
[ "$FAST" = "1" ] && printf 'mode:   --fast (web build and e2e skipped)\n'
hr
printf '\n'

# ── 1. Python lint ───────────────────────────────────────────────────────────
# CI runs `ruff check src --select E4,E7,E9,F` from backend/. This is stricter:
# the full rule set over src/ AND scripts/. scripts/ matters — linting it is
# what surfaced the missing `pathlib` import that made the G24 gate script
# (validate_deployment.py) raise NameError before it could write its artifact.
step "ruff — backend/src" \
  bash -c "cd '$REPO_ROOT/backend' && '$PY' -m ruff check src/"

step "ruff — backend/scripts" \
  bash -c "cd '$REPO_ROOT/backend' && '$PY' -m ruff check scripts/"

# ── 2. Type debt ceiling ─────────────────────────────────────────────────────
# Never raise the ceiling to fit new debt — clear the errors your change added.
# NOTE: this reading is platform-sensitive. Linux CI reports higher than local
# Windows (measured gap ~9); only the CI number is authoritative once the lock
# clears. Budget headroom accordingly.
step "mypy debt ceiling (784)" \
  bash -c "cd '$REPO_ROOT/backend' && '$PY' scripts/check_mypy_ceiling.py --ceiling 784"

# ── 3. Research registry integrity ───────────────────────────────────────────
step "experiment registry (--strict)" \
  bash -c "cd '$REPO_ROOT/backend' && PYTHONPATH=. '$PY' scripts/validate_experiment_registry.py --strict"

# ── 4. Certification / artifact lineage ──────────────────────────────────────
# This is the gate Render runs in its buildCommand: every served artifact must
# match its hash-locked manifest entry, and a CERTIFIED claim must carry
# hash-verified evidence.
step "active artifact lineage (INV-14)" \
  bash -c "cd '$REPO_ROOT/backend' && PYTHONPATH=. '$PY' scripts/verify_active_artifacts.py"

# Offline only — it reads the committed manifest and issues no geocoding
# requests, so it is deterministic and safe on every commit. Re-geocoding in
# CI would be rate-limited and flaky for no added assurance. It caught RCD
# Espanyol resolved to Tenerife, ~1,296 km from its real stadium, feeding
# subtropical weather into a Barcelona fixture's features.
step "venue manifest integrity (DEBT 44)" \
  bash -c "cd '$REPO_ROOT/backend' && PYTHONPATH=. '$PY' scripts/validate_venue_manifest.py"

# ── 5. Backend tests ─────────────────────────────────────────────────────────
# The whole suite. A collection error here aborts everything before a single
# test runs, which is precisely the failure DEBT 97 recorded.
step "pytest — backend/tests" \
  bash -c "cd '$REPO_ROOT/backend' && '$PY' -m pytest tests/ -q -p no:randomly"

# ── 6. Schema authority ──────────────────────────────────────────────────────
# Alembic is the sole schema authority (INV-11), but it needs a live database.
#
# ⚠️  THIS GATE REFUSES ANY NON-LOCAL DATABASE, DELIBERATELY.
# `alembic upgrade head` applies migrations. A developer's shell very often has
# DATABASE_URL pointing at the Render production instance — this environment
# did, and the first run of this script executed `upgrade head` against
# production before this guard existed. It happened to be a no-op because
# production was already at head, but "happened to be" is not a safety
# property. A pre-commit gate must never be able to migrate production, so the
# host is parsed and anything but a loopback address is refused.
#
# To exercise this gate, point DATABASE_URL at a local throwaway database:
#   DATABASE_URL=postgresql://postgres@localhost:5432/sabiscore_verify ./scripts/ci_local_enforcer.sh
_db_host() {
  # Extract the host from a URL of the form scheme://[user[:pass]]@host[:port]/db
  printf '%s' "${DATABASE_URL:-}" | sed -n 's#^[^:]*://\([^@]*@\)\?\([^:/?]*\).*#\2#p'
}

if [ -z "${DATABASE_URL:-}" ]; then
  skip "alembic upgrade + drift check" \
    "DATABASE_URL unset — point it at a LOCAL database to exercise this gate."
else
  DB_HOST="$(_db_host)"
  case "$DB_HOST" in
    localhost|127.0.0.1|::1|"")
      step "alembic upgrade head" \
        bash -c "cd '$REPO_ROOT/backend' && '$PY' -m alembic upgrade head"
      step "alembic drift check" \
        bash -c "cd '$REPO_ROOT/backend' && '$PY' -m alembic check"
      ;;
    *)
      skip "alembic upgrade + drift check" \
        "REFUSED: DATABASE_URL points at non-local host '$DB_HOST'. This gate applies migrations and must never target a remote or production database."
      ;;
  esac
fi

# ── 7. Secret scanning ───────────────────────────────────────────────────────
if command -v gitleaks >/dev/null 2>&1; then
  step "gitleaks — working tree" gitleaks detect --no-git --redact
else
  skip "gitleaks secret scan" "gitleaks not on PATH — install it to exercise this gate."
fi

# ── 8. Web ───────────────────────────────────────────────────────────────────
if command -v pnpm >/dev/null 2>&1; then
  step "web lint"      pnpm --filter @sabiscore/web lint
  step "web typecheck" pnpm --filter @sabiscore/web typecheck
  step "web tests"     pnpm --filter @sabiscore/web test
  step "responsible-gambling copy scan" node scripts/copy-scan.mjs
  step "scraper validate" pnpm --filter @sabiscore/scraper validate
  step "scraper tests"    pnpm --filter @sabiscore/scraper test

  if [ "$FAST" = "1" ]; then
    skip "web production build" "--fast requested"
  else
    # NODE_ENV must be pinned: a shell exporting development makes `next build`
    # fail at the /404 prerender with a misleading <Html> error.
    step "web production build" \
      bash -c "NODE_ENV=production pnpm --filter @sabiscore/web build"
  fi
else
  skip "web + scraper gates" "pnpm not on PATH."
fi

# ── Summary ──────────────────────────────────────────────────────────────────
ELAPSED=$((SECONDS - STARTED_AT))
printf '\n'
hr
printf 'RESULT: %d gate(s) passed, %d skipped, in %dm%02ds\n' \
  "$PASSED" "$SKIPPED" "$((ELAPSED / 60))" "$((ELAPSED % 60))"
hr
if [ "$SKIPPED" -gt 0 ]; then
  printf '\n⚠  The following gates were NOT exercised — this run does not\n'
  printf '   certify them, and they must be covered before relying on it:\n'
  for s in "${SKIPPED_NAMES[@]}"; do printf '     • %s\n' "$s"; done
fi
printf '\n✓ Local enforcement passed. This substitutes for CI only while the\n'
printf '  GitHub Actions billing lock holds (docs/DEBT.md items 16, 99).\n\n'
