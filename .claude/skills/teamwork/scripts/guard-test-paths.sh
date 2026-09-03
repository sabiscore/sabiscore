#!/bin/bash
# guard-test-paths.sh — global PreToolUse gate, registered in settings.json.
#
# Confirmed fields: `agent_type` (common hook input field, present when the
# hook fires inside a subagent/teammate) and `tool_input.file_path` (directly
# evidenced in Claude Code's own MCP-tool-hook documentation example). This
# script only restricts the qa-verifier role; every other agent (lead,
# architect, implementer, debugger) passes through untouched.
set -euo pipefail

INPUT=$(cat)
AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // empty')

if [ "$AGENT_TYPE" != "qa-verifier" ]; then
  exit 0
fi

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# No file_path on this tool call (e.g. Bash) — nothing to gate.
if [ -z "$FILE_PATH" ]; then
  exit 0
fi

if echo "$FILE_PATH" | grep -qiE '(\.test\.|\.spec\.|/__tests__/|/tests?/)'; then
  exit 0
fi

echo "Blocked: qa-verifier may only Edit/Write test or spec files. Got: $FILE_PATH. Report implementation fixes to the owning impl-* teammate instead of applying them yourself." >&2
exit 2
