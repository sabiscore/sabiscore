#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
ROOT="$(cd "$ROOT" && pwd -P)"
SOURCE="$ROOT/.ai/skills"
PARENT="$ROOT/.agents"
DEST="$PARENT/skills"

if [[ ! -d "$SOURCE" ]]; then
  echo "error: canonical skill directory not found: $SOURCE" >&2
  exit 1
fi

mkdir -p "$PARENT"

if [[ -L "$DEST" ]]; then
  if [[ "$(cd "$DEST" && pwd -P)" == "$(cd "$SOURCE" && pwd -P)" ]]; then
    echo "Legacy Codex skill bridge is already configured: $DEST -> $SOURCE"
    exit 0
  fi
  echo "error: $DEST is a symlink with an unexpected target; review it manually" >&2
  exit 1
fi
if [[ -e "$DEST" && ! -d "$DEST" ]]; then
  echo "error: $DEST exists and is not a directory; review it manually" >&2
  exit 1
fi

mkdir -p "$DEST"
created=0
reused=0

for skill in "$SOURCE"/*; do
  [[ -f "$skill/SKILL.md" ]] || continue
  name="$(basename "$skill")"
  discovered="$DEST/$name"
  expected="$(cd "$skill" && pwd -P)"

  if [[ -L "$discovered" ]]; then
    if [[ "$(cd "$discovered" && pwd -P)" != "$expected" ]]; then
      echo "error: discovery collision for '$name': unexpected symlink target" >&2
      exit 1
    fi
    reused=$((reused + 1))
    continue
  fi
  if [[ -e "$discovered" ]]; then
    echo "error: discovery collision for '$name': $discovered is not a symlink" >&2
    exit 1
  fi

  ln -s "../../.ai/skills/$name" "$discovered"
  created=$((created + 1))
done

if ((created + reused == 0)); then
  echo "error: no canonical SKILL.md packages found under $SOURCE" >&2
  exit 1
fi

echo "Codex skill overlay configured at $DEST ($created created, $reused reused)."
echo "External discovery entries were preserved."
echo "Restart Codex/VS Code if /skills does not refresh automatically."
