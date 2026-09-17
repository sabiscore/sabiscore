#!/usr/bin/env node
/**
 * scripts/copy-scan.mjs
 * Responsible-gambling prohibited-copy scanner.
 * Source of truth for the term list: CLAUDE.md, "Prohibited UI terms",
 * reconciled against the pre-existing outcome-claim patterns that were
 * previously inline-only in ci.yml and undocumented in CLAUDE.md.
 *
 * Exit code 0 = clean. Exit code 1 = one or more violations found.
 * No `|| true` permitted anywhere this script is invoked.
 */

import { readFileSync, globSync, statSync } from "node:fs";

const TARGET_GLOB = "apps/web/src/**/*.{ts,tsx}";
const EXCLUDE_GLOB = "apps/web/src/**/*.{test,spec}.{ts,tsx}";

const NEGATION_WORDS = /\b(not|no|never|isn't|aren't|without|non-|un)\b/i;

// Group 1: base literal/phrase terms (word- or phrase-bounded, case-insensitive)
const BASE_RULES = [
  { name: "banker", pattern: /\bbanker\b/i },
  { name: "sure bet", pattern: /\bsure\s+bet\b/i },
  { name: "free money", pattern: /\bfree\s+money\b/i },
  { name: "execute immediately", pattern: /\bexecute\s+immediately\b/i },
  { name: "lock", pattern: /\block\b/i, camelCaseSkip: true },
];

// Group 2: negation-sensitive terms — legitimate responsible-gambling
// disclaimers ("returns are not guaranteed") must NOT be flagged.
const NEGATION_RULES = [
  { name: "guaranteed", pattern: /\bguaranteed\b/i },
  { name: "risk-free", pattern: /\brisk[- ]free\b/i },
];

// Group 3: new certainty-of-outcome phrases (bare "certain" intentionally excluded)
const CERTAINTY_RULES = [
  { name: "can't lose", pattern: /\bcan(?:'|\u2019)?t\s+lose\b|\bcannot\s+lose\b/i },
  { name: "certain to win", pattern: /\bcertain\s+to\s+win\b/i },
  { name: "certain profit", pattern: /\bcertain\s+profit\b/i },
  { name: "certain return", pattern: /\bcertain\s+return\b/i },
  { name: "100% certain", pattern: /\b100%\s*certain\b/i },
];

// Group 4: pre-existing outcome-claim phrases — ported unchanged from the
// original inline `outcome_claim_hits` grep (no negation filtering applied
// there originally; preserved as-is rather than silently tightened).
const OUTCOME_CLAIM_RULES = [
  { name: "maximize betting edge", pattern: /\bmaximi[sz]e (your )?betting edge\b/i },
  { name: "beat the market/odds", pattern: /\bbeat(?:s|ing)? (?:the market|the odds)\b/i },
  { name: "win more", pattern: /\bwin more\b/i },
  { name: "winning picks", pattern: /\bwinning picks?\b/i },
  { name: "highly accurate predictions", pattern: /\bhighly accurate predictions?\b/i },
  { name: "profitable predictions", pattern: /\bprofitable predictions?\b/i },
  { name: "guaranteed returns", pattern: /\bguaranteed returns?\b/i },
];

function isImportOrCommentLine(line) {
  const trimmed = line.trim();
  return (
    trimmed.startsWith("import ") ||
    trimmed.startsWith("//") ||
    trimmed.startsWith("/*") ||
    trimmed.startsWith("*")
  );
}

function isCamelCaseOrScrollHook(line, matchIndex, matchLength) {
  const before = line[matchIndex - 1];
  const after = line[matchIndex + matchLength];
  const wordChar = /[A-Za-z0-9_]/;
  const glued = (before && wordChar.test(before)) || (after && wordChar.test(after));
  const isUseScroll = /use-scroll/i.test(line);
  return glued || isUseScroll;
}

function hasNearbyNegation(line, matchIndex, window = 24) {
  const start = Math.max(0, matchIndex - window);
  return NEGATION_WORDS.test(line.slice(start, matchIndex));
}

function scanFile(path) {
  const violations = [];
  const lines = readFileSync(path, "utf8").split("\n");

  lines.forEach((line, idx) => {
    if (isImportOrCommentLine(line)) return;

    for (const rule of BASE_RULES) {
      const m = rule.pattern.exec(line);
      if (!m) continue;
      if (rule.camelCaseSkip && isCamelCaseOrScrollHook(line, m.index, m[0].length)) continue;
      violations.push({ file: path, lineNumber: idx + 1, term: rule.name, snippet: line.trim().slice(0, 120) });
    }

    for (const rule of NEGATION_RULES) {
      const m = rule.pattern.exec(line);
      if (!m) continue;
      if (hasNearbyNegation(line, m.index)) continue;
      violations.push({ file: path, lineNumber: idx + 1, term: rule.name, snippet: line.trim().slice(0, 120) });
    }

    for (const rule of [...CERTAINTY_RULES, ...OUTCOME_CLAIM_RULES]) {
      const m = rule.pattern.exec(line);
      if (!m) continue;
      violations.push({ file: path, lineNumber: idx + 1, term: rule.name, snippet: line.trim().slice(0, 120) });
    }
  });

  return violations;
}

/**
 * Files matching `pattern`, directories excluded.
 *
 * Uses Node's built-in `fs.globSync` (stable since v22) rather than the `glob`
 * package, which this repository never declared as a dependency anywhere — so
 * `node scripts/copy-scan.mjs`, the exact command CI runs, failed with
 * ERR_MODULE_NOT_FOUND. That went unnoticed because no workflow has reached
 * step 1 since the Actions billing lock engaged (docs/DEBT.md items 16, 99).
 *
 * `fs.globSync` has no `nodir` option, hence the explicit file filter. Both
 * call sites use this helper, so path separators stay consistent between the
 * exclusion set and the scan list.
 */
function globFiles(pattern) {
  return globSync(pattern).filter((entry) => statSync(entry).isFile());
}

function main() {
  const excluded = new Set(globFiles(EXCLUDE_GLOB));
  const files = globFiles(TARGET_GLOB).filter((f) => !excluded.has(f));
  const allViolations = files.flatMap(scanFile);

  if (allViolations.length === 0) {
    console.log(`✓ No prohibited gambling copy (${files.length} files scanned)`);
    process.exit(0);
  }

  for (const v of allViolations) {
    console.error(`${v.file}:${v.lineNumber}: [${v.term}] ${v.snippet}`);
  }
  console.error("ERROR: Prohibited gambling copy found — see matches above");
  process.exit(1);
}

main();
