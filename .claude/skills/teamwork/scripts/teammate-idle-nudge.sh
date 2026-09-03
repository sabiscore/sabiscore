#!/bin/bash
# teammate-idle-nudge.sh — TeammateIdle gate, registered in settings.json.
#
# Same confidence note as task-hygiene-gate.sh: the exact fields for
# determining "does this teammate have unclaimed dependent work" weren't
# confirmed in the source documentation. This intentionally does NOT try to
# inspect the shared task list on disk (its exact schema under
# ~/.claude/tasks/{team-name}/ also wasn't confirmed). It fails open by
# default. Set TEAMWORK_REQUIRE_EXPLICIT_HANDOFF=1 only after you've
# verified the real payload shape yourself with `claude --debug`.
set -euo pipefail

REQUIRE_EXPLICIT_HANDOFF="${TEAMWORK_REQUIRE_EXPLICIT_HANDOFF:-0}"

if [ "$REQUIRE_EXPLICIT_HANDOFF" != "1" ]; then
  exit 0
fi

INPUT=$(cat)
AGENT=$(echo "$INPUT" | jq -r '.agent_type // .agent_id // "teammate"')

echo "Before going idle, confirm you've either marked your task complete via TaskUpdate or sent a status message to the lead. If neither is true, keep working." >&2
exit 2
