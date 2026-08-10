import os
import sys
import json
from urllib.request import urlopen, Request


BASE = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SABISCORE_BACKEND_URL", "")


def get(path: str):
    req = Request(f"{BASE}{path}", headers={"User-Agent": "SabiScore-Smoke/1.0"})
    with urlopen(req, timeout=20) as r:
        body = r.read()
        ctype = r.headers.get("content-type", "")
        if "json" in ctype:
            return r.status, json.loads(body)
        return r.status, body.decode("utf-8", errors="ignore")


def main() -> int:
    if not BASE:
        print("SABISCORE_BACKEND_URL or an explicit BASE_URL argument is required", file=sys.stderr)
        return 2

    print(f"Smoke testing backend: {BASE}\n")

    tests_passed = 0
    tests_failed = 0

    # health
    try:
        code, body = get("/health")
        print(f"✓ /health: {code} - {body}")
        if code != 200:
            tests_failed += 1
        else:
            tests_passed += 1
    except Exception as e:
        print(f"✗ /health: {e}")
        tests_failed += 1

    # openapi up
    try:
        code, body = get("/openapi.json")
        paths_count = len(body.get("paths", {})) if isinstance(body, dict) else "?"
        print(f"✓ /openapi.json: {code} - {paths_count} paths")
        if code != 200:
            tests_failed += 1
        else:
            tests_passed += 1
    except Exception as e:
        print(f"✗ /openapi.json: {e}")
        tests_failed += 1

    # matches upcoming (may be 200 even if empty)
    try:
        code, body = get("/api/v1/matches/upcoming?limit=2")
        match_count = len(body.get("matches", [])) if isinstance(body, dict) else 0
        print(f"✓ /api/v1/matches/upcoming: {code} - {match_count} matches")
        if code not in (200, 204):
            tests_failed += 1
        else:
            tests_passed += 1
    except Exception as e:
        print(f"✗ /api/v1/matches/upcoming: {e}")
        tests_failed += 1

    # predictions value-bets (thresholded)
    try:
        code, body = get("/api/v1/predictions/value-bets/today")
        bets_count = len(body) if isinstance(body, list) else 0
        print(f"✓ /api/v1/predictions/value-bets/today: {code} - {bets_count} value bets")
        if code not in (200, 204):
            tests_failed += 1
        else:
            tests_passed += 1
    except Exception as e:
        print(f"✗ /api/v1/predictions/value-bets/today: {e}")
        tests_failed += 1

    print(f"\n{'='*60}")
    print(f"Tests Passed: {tests_passed}")
    print(f"Tests Failed: {tests_failed}")
    print(f"{'='*60}")

    if tests_failed > 0:
        print("\n⚠ Some tests failed. Check logs above.")
        return 1

    print("\n✓ All smoke tests passed!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
