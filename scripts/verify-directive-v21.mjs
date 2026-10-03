#!/usr/bin/env node
/** V21 60-gate evidence runner. Empirical blockers remain visible as BLOCKED. */

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL(".", import.meta.url)), "..");
const python = process.env.PYTHON || "python";
const baseEnv = {
  ...process.env,
  PYTHONPATH: root,
  SABISCORE_MAX_RSS_MB: "3072",
  PROVIDER_LIVE_TESTS: "false",
};

function run(label, command, args) {
  process.stdout.write(`${label} ...\n`);
  const result = spawnSync(command, args, {
    cwd: root,
    env: baseEnv,
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
  });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  return result.status === 0;
}

const reportGenerated = run("Generate V21 protocol and evidence reports", python, [
  "-m", "backend.scripts.v21_certification", "generate-reports",
]);
const v20 = run("Gates 1–40 (V20 regression matrix)", python, [
  "-m", "backend.scripts.run_under_resource_guard", "--",
  process.execPath, join(root, "scripts/verify-directive-v20.mjs"),
]);
const v21 = run("Gates 41–60 (V21 admission and evidence checks)", python, [
  "-m", "backend.scripts.run_under_resource_guard", "--",
  python, "-m", "pytest", "backend/tests/unit/test_v21_certification_recovery.py",
  "-k", "test_gate_", "-q", "-c", "backend/pytest.ini",
]);

let certification;
try {
  certification = JSON.parse(readFileSync(join(root, "reports/research/v21-model-certification.json"), "utf8"));
} catch (error) {
  console.error(`Could not read V21 certification report: ${error}`);
  process.exit(1);
}

console.log("\nV21 certification gate matrix:");
let certifiedPass = 0;
let blocked = 0;
let failed = 0;
for (let gate = 1; gate <= 60; gate += 1) {
  const status = certification.gates[`gate_${gate}`] ?? "UNVERIFIED";
  if (status === "PASS") certifiedPass += 1;
  else if (["FAIL", "UNVERIFIED", "PENDING"].includes(status)) blocked += 1;
  else failed += 1;
  console.log(`  ${String(gate).padStart(2, "0")}: ${status}`);
}
console.log(`\nEvidence checks: V20=${v20 ? "PASS" : "FAIL"}, V21=${v21 ? "PASS" : "FAIL"}, reports=${reportGenerated ? "PASS" : "FAIL"}`);
console.log(`Certification states: ${certifiedPass} PASS, ${blocked} BLOCKED/FAIL, ${failed} other out of 60`);
console.log(`Release decision: ${certification.overall_decision}`);
if (!reportGenerated || !v20 || !v21) process.exit(1);
