#!/usr/bin/env bash
#
# Remote CI verification — the closure test for docs/DEBT.md item 99.
#
# WHY THIS EXISTS
# ---------------
# Item 99 makes `ci_local_enforcer.sh` mandatory before every push, and states
# its own closure condition precisely:
#
#   "Delete the mandate only once a real workflow run has been observed
#    reaching step 1 with a non-empty `runner_name` — not when someone
#    believes the billing issue was settled."
#
# This script is that observation, automated. It exists because the two states
# it distinguishes are indistinguishable from every summary view GitHub offers:
# a workflow that FAILED and a workflow that NEVER RAN both render as a red X.
#
# ⚠️ THE ASSERTION IS AT JOB LEVEL, NOT RUN LEVEL, AND THAT IS THE WHOLE POINT.
# `gh run list --json status,conclusion` reports `conclusion: "failure"` under
# the billing lock exactly as it would for a genuine test failure — it carries
# no `runner_name` field at all. Only `GET /actions/runs/{id}/jobs` exposes
# `runner_name` and `steps`, and the lock's signature is `runner_name: ""` with
# `steps: 0`. A run that fails in three seconds having executed zero steps has
# not tested anything.
#
# ⚠️ Do NOT substitute wall-clock duration for this check. A locked job can sit
# queued for minutes before failing, which looks like a real run that died.
#
# TWO INDEPENDENT VERDICTS
# ------------------------
# The script reports them separately because they close different things:
#
#   RUNNER BOOTED  — a runner picked the job up (non-empty runner_name, >=1
#                    step). This is what closes item 99 and lifts the local
#                    enforcement mandate, EVEN IF the suite then failed.
#   CI PASSED      — every required workflow concluded `success`. This is what
#                    gates a merge.
#
# Exit codes:
#   0  runner booted AND every required workflow passed
#   1  runner booted, but at least one required workflow failed  (lock cleared,
#      real red CI — item 99 closes, the failures are genuine and must be fixed)
#   2  billing lock still active (no job ever reached step 1)
#   3  no run found for the target commit, or polling timed out
#   4  prerequisite missing (gh not installed or not authenticated)
#
# USAGE
#   ./scripts/verify_remote_ci.sh                 # poll HEAD of origin/master
#   ./scripts/verify_remote_ci.sh --sha <sha>     # a specific commit
#   ./scripts/verify_remote_ci.sh --once          # single check, no polling
#   ./scripts/verify_remote_ci.sh --timeout 3600 --interval 60
#
set -euo pipefail

BRANCH="master"
SHA=""
TIMEOUT=1800
INTERVAL=30
ONCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --branch)   BRANCH="$2"; shift 2 ;;
    --sha)      SHA="$2"; shift 2 ;;
    --timeout)  TIMEOUT="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --once)     ONCE=1; shift ;;
    -h|--help)  sed -n '2,50p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 4 ;;
  esac
done

# ⚠️ VERIFIED 2026-09-17: master's ruleset (id 20939497, active) contains
# exactly four rules — deletion, non_fast_forward, required_linear_history and
# pull_request (1 approving review). There is NO `required_status_checks` rule,
# so GitHub does not block a merge on red CI even when runners are working.
# This list is therefore the gate this REPOSITORY treats as binding, not one
# GitHub enforces; re-derive it with
#   gh api repos/<owner>/<repo>/rules/branches/master
# before trusting it. A run of some other workflow (Keep-alive ping, say)
# booting a runner is still valid evidence for item 99, but it is NOT evidence
# that the suite is green — which is why the two verdicts are computed over
# different sets.
REQUIRED_WORKFLOWS=(
  "CI - Canonical Platform"
  "Secret Scan"
  "Block large files"
  "Validate Model Artifacts"
)

command -v gh >/dev/null 2>&1 || { echo "FAIL: gh CLI not installed." >&2; exit 4; }
gh auth status >/dev/null 2>&1 || { echo "FAIL: gh CLI not authenticated." >&2; exit 4; }

REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"

if [ -z "$SHA" ]; then
  SHA="$(git rev-parse "origin/$BRANCH" 2>/dev/null || git rev-parse "$BRANCH")"
fi
# The REST head_sha filter is an exact match, so a short SHA finds nothing and
# would be reported as "never built". Expand it locally first.
if [ "${#SHA}" -ne 40 ]; then
  SHA="$(git rev-parse "$SHA" 2>/dev/null || echo "$SHA")"
fi
SHORT_SHA="${SHA:0:7}"

echo "repo   : $REPO"
echo "branch : $BRANCH"
echo "commit : $SHORT_SHA"
echo

# Emits one "name<TAB>status<TAB>conclusion<TAB>runner_name<TAB>steps" line per
# job across every run for this commit. `steps` is the count of executed steps:
# 0 means the job was created but never started, the billing-lock signature.
collect_jobs() {
  # Queried by head_sha rather than by scanning a page of `gh run list`: a
  # commit older than that page would silently look like it had never been
  # built, which is the exact 'absence read as evidence' failure this script
  # exists to prevent.
  local run_ids
  run_ids="$(gh api "repos/$REPO/actions/runs?head_sha=$SHA&per_page=100" \
      --jq '.workflow_runs[].id' 2>/dev/null || true)"
  [ -z "$run_ids" ] && return 1

  local id
  for id in $run_ids; do
    gh api "repos/$REPO/actions/runs/$id/jobs" --paginate \
      --jq '.jobs[] | [.workflow_name // .name, .status, (.conclusion // "null"), (.runner_name // ""), (.steps | length)] | @tsv' \
      2>/dev/null || true
  done
}

is_required() {
  local name="$1" w
  for w in "${REQUIRED_WORKFLOWS[@]}"; do
    [ "$name" = "$w" ] && return 0
  done
  return 1
}

evaluate() {
  local jobs="$1"
  BOOTED=0; PENDING=0; LOCKED=0
  REQUIRED_SEEN=0; REQUIRED_PASSED=0; REQUIRED_FAILED=0
  REPORT=""

  while IFS=$'\t' read -r name status conclusion runner steps; do
    [ -z "${name:-}" ] && continue
    local verdict
    if [ -n "$runner" ] && [ "${steps:-0}" -ge 1 ]; then
      BOOTED=$((BOOTED + 1))
      verdict="ran on '$runner' (${steps} steps) -> $conclusion"
    elif [ "$status" != "completed" ]; then
      PENDING=$((PENDING + 1))
      verdict="$status (no runner yet)"
    else
      LOCKED=$((LOCKED + 1))
      verdict="NEVER STARTED - runner_name empty, ${steps:-0} steps [billing lock]"
    fi
    REPORT="${REPORT}  ${name} :: ${verdict}"$'\n'

    if is_required "$name"; then
      REQUIRED_SEEN=$((REQUIRED_SEEN + 1))
      if [ "$conclusion" = "success" ]; then
        REQUIRED_PASSED=$((REQUIRED_PASSED + 1))
      elif [ "$status" = "completed" ]; then
        REQUIRED_FAILED=$((REQUIRED_FAILED + 1))
      fi
    fi
  done <<< "$jobs"
}

DEADLINE=$(( $(date +%s) + TIMEOUT ))
while :; do
  if ! JOBS="$(collect_jobs)" || [ -z "$JOBS" ]; then
    echo "No workflow run found for $SHORT_SHA."
    [ "$ONCE" -eq 1 ] && exit 3
    if [ "$(date +%s)" -ge "$DEADLINE" ]; then
      echo "TIMEOUT: no run appeared for $SHORT_SHA within ${TIMEOUT}s." >&2
      exit 3
    fi
    sleep "$INTERVAL"; continue
  fi

  evaluate "$JOBS"
  printf '%s' "$REPORT"
  echo

  if [ "$BOOTED" -gt 0 ]; then
    echo "RUNNER BOOTED: yes — ${BOOTED} job(s) reached step 1 with a real runner."
    echo "  => docs/DEBT.md item 99's closure condition is SATISFIED."
    if [ "$PENDING" -gt 0 ] && [ "$ONCE" -eq 0 ] && [ "$(date +%s)" -lt "$DEADLINE" ]; then
      echo "  (${PENDING} job(s) still in flight — waiting for a final verdict.)"
      sleep "$INTERVAL"; continue
    fi
    echo "REQUIRED WORKFLOWS: ${REQUIRED_PASSED} passed, ${REQUIRED_FAILED} failed," \
         "of ${REQUIRED_SEEN} seen."
    if [ "$REQUIRED_FAILED" -eq 0 ] && [ "$REQUIRED_PASSED" -gt 0 ]; then
      echo "PASS: remote CI is green for $SHORT_SHA."
      exit 0
    fi
    echo "FAIL: the lock is clear but required workflows are red — these are" \
         "genuine failures and must be fixed." >&2
    exit 1
  fi

  if [ "$PENDING" -gt 0 ]; then
    echo "Runs are queued but no runner has started one yet."
    if [ "$ONCE" -eq 1 ] || [ "$(date +%s)" -ge "$DEADLINE" ]; then
      echo "INCONCLUSIVE: nothing reached step 1 within the window." >&2
      exit 2
    fi
    sleep "$INTERVAL"; continue
  fi

  echo "RUNNER BOOTED: NO — ${LOCKED} job(s) completed without executing a step."
  echo "  This is the GitHub Actions billing lock (docs/DEBT.md items 16, 99)."
  echo "  ci_local_enforcer.sh remains MANDATORY before every push."
  if [ "$ONCE" -eq 1 ] || [ "$(date +%s)" -ge "$DEADLINE" ]; then
    exit 2
  fi
  sleep "$INTERVAL"
done
