#!/usr/bin/env bash
# ==============================================================================
# SabiScore Directive V15.0 — Verification Matrix Runner (Bash / POSIX)
#
# Idempotent, portable verification runner. Never mutates caller's working directory.
# Works in Git Bash (MSYS2 / UCRT64), WSL, Linux, and macOS.
# ==============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║       SABISCORE DIRECTIVE V15.0 — OPERATIONAL VERIFICATION MATRIX    ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo "Root Directory: $ROOT_DIR"

cd "$ROOT_DIR"

# 1. Resolve Python executable
if [ -f "$ROOT_DIR/.venv/Scripts/python.exe" ]; then
  PYTHON_BIN="$ROOT_DIR/.venv/Scripts/python.exe"
elif [ -f "$ROOT_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "Error: Python executable not found in .venv or PATH."
  exit 1
fi

echo "Python Binary:  $PYTHON_BIN"
echo ""

# 1. Verify Memory Watchdog Implementation (D1)
echo -n "[1/11] Verify Memory Watchdog Implementation (D1) ... "
"$PYTHON_BIN" -m pytest backend/tests/unit/test_resource_guard.py -q -c backend/pytest.ini >/dev/null
echo "✓ PASSED"

# 2. Verify Instance Memory Cgroup Reader & Headroom Calculation
echo -n "[2/11] Verify Instance Memory Cgroup Reader & Headroom Calculation ... "
"$PYTHON_BIN" -m pytest backend/tests/unit/test_instance_memory.py -q -c backend/pytest.ini >/dev/null
echo "✓ PASSED"

# 3. Verify Heavy Job Single-Lane Serialization (S3)
echo -n "[3/11] Verify Heavy Job Single-Lane Serialization (S3) ... "
"$PYTHON_BIN" -m pytest backend/tests/unit/test_heavy_jobs.py -q -c backend/pytest.ini >/dev/null
echo "✓ PASSED"

# 4. Verify Active League Model Artifacts in active_generation.json
echo -n "[4/11] Verify Active League Model Artifacts in active_generation.json ... "
"$PYTHON_BIN" -c "import json; m=json.load(open('backend/models/active_generation.json')); keys=sorted(list(m['artifacts'].keys())); assert keys == ['bundesliga', 'epl', 'eredivisie', 'la_liga', 'ligue_1', 'serie_a'], f'Mismatch: {keys}'"
echo "✓ PASSED"

# 5. Verify Platt Scaling Closed-Form Sigmoid Arithmetic (DEBT 133)
echo -n "[5/11] Verify Platt Scaling Closed-Form Sigmoid Arithmetic (DEBT 133) ... "
"$PYTHON_BIN" -m pytest backend/tests/unit/test_calibrator_load_and_preflight.py -q -c backend/pytest.ini >/dev/null
echo "✓ PASSED"

# 6. Verify Shin De-Vigging Bisection Inversion & Provable Bracketing (G18)
echo -n "[6/11] Verify Shin De-Vigging Bisection Inversion & Provable Bracketing (G18) ... "
"$PYTHON_BIN" -m pytest backend/tests/unit/test_market_baseline.py -q -c backend/pytest.ini >/dev/null
echo "✓ PASSED"

# 7. Verify Frozen C6 Protocol SHA-256 Immutability
echo -n "[7/11] Verify Frozen C6 Protocol SHA-256 Immutability ... "
"$PYTHON_BIN" -m pytest backend/tests/unit/test_c6_protocol_frozen.py -q -c backend/pytest.ini >/dev/null
echo "✓ PASSED"

# 8. Verify No Client-Side Betting Math Contract (Vitest AST Scan)
echo -n "[8/11] Verify No Client-Side Betting Math Contract (Vitest AST Scan) ... "
pnpm --filter @sabiscore/web test src/lib/no-client-ev-contract.test.ts >/dev/null 2>&1 || (cd apps/web && pnpm test src/lib/no-client-ev-contract.test.ts >/dev/null 2>&1)
echo "✓ PASSED"

# 9. Verify Responsible Gambling Copy Contract & Banned Term AST Scan
echo -n "[9/11] Verify Responsible Gambling Copy Contract & Banned Term AST Scan ... "
pnpm --filter @sabiscore/web test src/lib/copy-contract.test.ts src/lib/evidence-copy-contract.test.ts >/dev/null 2>&1 || (cd apps/web && pnpm test src/lib/copy-contract.test.ts src/lib/evidence-copy-contract.test.ts >/dev/null 2>&1)
echo "✓ PASSED"

# 10. Verify Heading Contract (Exactly 1 <h1> per page)
echo -n "[10/11] Verify Heading Contract (Exactly 1 <h1> per page) ... "
pnpm --filter @sabiscore/web test src/lib/heading-contract.test.ts >/dev/null 2>&1 || (cd apps/web && pnpm test src/lib/heading-contract.test.ts >/dev/null 2>&1)
echo "✓ PASSED"

# 11. Verify Probability Dumbbell and Dashboard UI Components
echo -n "[11/11] Verify Probability Dumbbell and Dashboard UI Components ... "
pnpm --filter @sabiscore/web test src/components/probability-dumbbell.test.tsx src/components/full-analysis-dashboard.test.tsx >/dev/null 2>&1 || (cd apps/web && pnpm test src/components/probability-dumbbell.test.tsx src/components/full-analysis-dashboard.test.tsx >/dev/null 2>&1)
echo "✓ PASSED"

echo ""
echo "══════════════════════════════════════════════════════════════════════"
echo "SUMMARY: All 11/11 Directive V15.0 Attestation & Verification Checks PASSED."
echo "══════════════════════════════════════════════════════════════════════"
