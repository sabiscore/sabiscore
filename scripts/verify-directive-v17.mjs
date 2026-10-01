#!/usr/bin/env node
/**
 * SabiScore Directive V17.0 — Authoritative Verification Matrix Runner
 *
 * Executes the complete 11-step verification matrix across backend and frontend,
 * resolving environment differences between Windows PowerShell, MSYS2/Git Bash,
 * and Linux/macOS. Guarantees zero directory mutation and resilient virtualenv detection.
 */

import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = resolve(fileURLToPath(import.meta.url), '..');
const ROOT_DIR = resolve(__dirname, '..');

// 1. Resolve Python executable
function resolvePython() {
  const candidates = [
    join(ROOT_DIR, '.venv', 'Scripts', 'python.exe'),
    join(ROOT_DIR, '.venv', 'bin', 'python'),
    'python',
    'python3'
  ];

  for (const bin of candidates) {
    if (bin.includes('/') || bin.includes('\\')) {
      if (existsSync(bin)) return bin;
    } else {
      // test system PATH candidate
      const test = spawnSync(bin, ['--version'], { stdio: 'ignore' });
      if (test.status === 0) return bin;
    }
  }
  return 'python';
}

const pythonBin = resolvePython();

// 2. Define Matrix Steps
const STEPS = [
  {
    id: 1,
    title: 'Verify Memory Watchdog Implementation (D1)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_resource_guard.py', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 2,
    title: 'Verify Instance Memory Cgroup Reader & Headroom Calculation',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_instance_memory.py', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 3,
    title: 'Verify Heavy Job Single-Lane Serialization (S3)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_heavy_jobs.py', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 4,
    title: 'Verify Active League Model Artifacts in active_generation.json',
    cmd: pythonBin,
    args: [
      '-c',
      "import json; m=json.load(open('backend/models/active_generation.json')); keys=sorted(list(m['artifacts'].keys())); assert keys == ['bundesliga', 'epl', 'eredivisie', 'la_liga', 'ligue_1', 'serie_a'], f'Mismatch: {keys}'; print(keys)"
    ],
    cwd: ROOT_DIR
  },
  {
    id: 5,
    title: 'Verify Platt Scaling Closed-Form Sigmoid Arithmetic (DEBT 133)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_calibrator_load_and_preflight.py', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 6,
    title: 'Verify Shin De-Vigging Bisection Inversion & Provable Bracketing (G18)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_market_baseline.py', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 7,
    title: 'Verify Frozen C6 Protocol SHA-256 Immutability',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_c6_protocol_frozen.py', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 8,
    title: 'Verify No Client-Side Betting Math Contract (Vitest AST Scan)',
    cmd: 'pnpm',
    args: ['--filter', '@sabiscore/web', 'test', 'src/lib/no-client-ev-contract.test.ts'],
    cwd: ROOT_DIR
  },
  {
    id: 9,
    title: 'Verify Responsible Gambling Copy Contract & Banned Term AST Scan',
    cmd: 'pnpm',
    args: ['--filter', '@sabiscore/web', 'test', 'src/lib/copy-contract.test.ts', 'src/lib/evidence-copy-contract.test.ts'],
    cwd: ROOT_DIR
  },
  {
    id: 10,
    title: 'Verify Heading Contract (Exactly 1 <h1> per page)',
    cmd: 'pnpm',
    args: ['--filter', '@sabiscore/web', 'test', 'src/lib/heading-contract.test.ts'],
    cwd: ROOT_DIR
  },
  {
    id: 11,
    title: 'Verify Probability Dumbbell and Dashboard UI Components',
    cmd: 'pnpm',
    args: ['--filter', '@sabiscore/web', 'test', 'src/components/probability-dumbbell.test.tsx', 'src/components/full-analysis-dashboard.test.tsx'],
    cwd: ROOT_DIR
  }
];

console.log('╔══════════════════════════════════════════════════════════════════════╗');
console.log('║       SABISCORE DIRECTIVE V17.0 — OPERATIONAL VERIFICATION MATRIX    ║');
console.log('╚══════════════════════════════════════════════════════════════════════╝');
console.log(`Root Directory:   ${ROOT_DIR}`);
console.log(`Python Binary:    ${pythonBin}\n`);

let passedCount = 0;
let failedCount = 0;
const results = [];
const isWindows = process.platform === 'win32';

for (const step of STEPS) {
  process.stdout.write(`[${step.id}/11] ${step.title} ... `);
  const start = Date.now();
  const isPnpm = step.cmd === 'pnpm' || step.cmd === 'pnpm.cmd';
  const res = spawnSync(step.cmd, step.args, {
    cwd: step.cwd,
    stdio: 'pipe',
    encoding: 'utf-8',
    shell: isWindows && isPnpm,
    env: { ...process.env, PYTHONPATH: 'backend' }
  });
  const duration = ((Date.now() - start) / 1000).toFixed(2);

  if (res.status === 0) {
    passedCount++;
    console.log(`✓ PASSED (${duration}s)`);
    results.push({ id: step.id, title: step.title, status: 'PASSED', duration: `${duration}s` });
  } else {
    failedCount++;
    console.log(`✗ FAILED (${duration}s)`);
    console.error(`\n--- STDOUT ---\n${res.stdout || '(none)'}`);
    console.error(`\n--- STDERR ---\n${res.stderr || '(none)'}\n`);
    results.push({ id: step.id, title: step.title, status: 'FAILED', duration: `${duration}s` });
    break; // Fail-closed: halt on first verification failure
  }
}

console.log('\n══════════════════════════════════════════════════════════════════════');
console.log(`SUMMARY: ${passedCount} PASSED, ${failedCount} FAILED out of ${STEPS.length} verification steps`);
console.log('══════════════════════════════════════════════════════════════════════\n');

if (failedCount > 0) {
  process.exit(1);
} else {
  console.log('✓ All Directive V17.0 Attestation & Verification Checks PASSED.');
  process.exit(0);
}
