'use strict';

// SessionStart is one of the few events where Claude Code adds plain stdout
// directly to Claude's context; stderr on exit 0 only reaches the debug log.
const fs = require('node:fs');
const path = require('node:path');

const root = process.env.CLAUDE_PROJECT_DIR || process.cwd();
const registry = path.join(root, 'registry.json');

let suite = 'unknown';
let skills = 0;

try {
  const data = JSON.parse(fs.readFileSync(registry, 'utf8'));
  suite = data?.suiteVersion ?? 'unknown';
  skills = Array.isArray(data?.skills) ? data.skills.length : 0;
} catch (_) {
  // registry.json is optional for the hook; do not fail session startup.
}

console.log(`[NEXUS] Session started. Suite v${suite} | ${skills} skills active.`);
