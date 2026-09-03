#!/bin/bash
# task-hygiene-gate.sh — TaskCreated / TaskCompleted gate, when configured in
# settings.json.
#
# CONFIDENCE NOTE: the common hook input fields (session_id, cwd,
# hook_event_name, agent_id, agent_type) are documented; the event-specific
# TaskCreated/TaskCompleted payload fields (task title/description/id) were
# not fully enumerated in the documentation snapshot this kit was built
# from. This script tries several plausible jq paths and FAILS OPEN
# (exit 0, allow) if none resolve, rather than blocking on an unverified
# guess. Before relying on this for anything that must never false-positive:
# run `claude --debug`, trigger a real TaskCreated/TaskCompleted event, read
# the actual JSON from the debug log, then tighten the jq path below.
set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "task-hygiene-gate: jq is unavailable; allowing hook to fail open." >&2
  exit 0
fi

INPUT=$(cat)
EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // empty')

DESC=$(echo "$INPUT" | jq -r '
  .task.description // .task.title // .description // .title //
  .tool_input.description // .tool_input.title // empty
')

if [ -z "$DESC" ]; then
  echo "task-hygiene-gate: no description field matched for $EVENT; allowing. Tighten jq paths after inspecting --debug output." >&2
  exit 0
fi

if [ "${#DESC}" -lt 10 ]; then
  echo "Blocked: task description too short to be actionable (\"$DESC\"). Give teammates a concrete, file-scoped task, not a one-word label." >&2
  exit 2
fi

exit 0
