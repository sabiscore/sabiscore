#!/usr/bin/env node
/**
 * SabiScore Directive V20.0 — Authoritative 40-Gate Verification & Certification Matrix Runner
 *
 * Executes the complete 36-gate quantitative, empirical, operational, and architectural matrix:
 * - Gates 1–18: Baseline System & Production Scaffolding (Memory watchdog, Cgroups, Heavy jobs, Active Gen,
 *               Platt closed-form, Shin bisection, C6 frozen SHA, PIT sentinels, Evidence curation,
 *               Legacy deprecation, Preprocessing E2E, Alembic parity, Cache jitter, Zero client math AST,
 *               Responsible copy AST, Single <h1> contract AST, Dumbbell/Dashboard UI, Web typecheck).
 * - Gates 19–36: Empirical Model Certification & Promotion Governance (Dataset fitness, Candidate artifacts,
 *                Adversarial leakage / PIT order, Protocol SHA-256 immutability, Chronological OOS validation,
 *                Calibration diagnostics, Frozen C6 benchmark bootstrap, Benchmark identity integrity,
 *                Adversarial stress / C7-G, Feature ablation report, Uncertainty semantics / C7-F,
 *                Drift monitoring / C7-I, Reproducibility rebuild hash, Shadow validation pipeline,
 *                Data gap recovery roadmap, Provider live health, Promotion governance fail-closed state,
 *                Rollback readiness & Executive promotion attestation).
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
      const test = spawnSync(bin, ['--version'], { stdio: 'ignore' });
      if (test.status === 0) return bin;
    }
  }
  return 'python';
}

const pythonBin = resolvePython();

// 2. Define Directive V19 Matrix Steps (40 Gates)
const STEPS = [
  // ─── GATES 1–18: Baseline Foundation & Safety Contracts (V18 Suite) ───────
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
    title: 'Verify Point-in-Time (PIT) Leakage Sentinel Suite (Directive V18 Phase 2)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_pit_leakage_sentinel.py', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 9,
    title: 'Verify Offline Evidence Curator Precedence & Conflict Engine (Directive V18 Phase 6)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_evidence_curator.py', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 10,
    title: 'Verify Legacy Orchestrator Deprecation & Fail-Closed Guard (Directive V18 Phase 7)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_legacy_orchestrator_deprecation.py', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 11,
    title: 'Verify Preprocessing Feature Pipeline E2E Integration (Directive V18 Phase 7)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/integration/test_preprocessing_e2e.py', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 12,
    title: 'Verify Alembic Metadata Registration & Schema Parity (Directive V18 Phase 7)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_alembic_metadata_registration.py', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 13,
    title: 'Verify Cache Stampede Bounded Jitter Engine (Directive V18 Phase 7)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_cache.py', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 14,
    title: 'Verify No Client-Side Betting Math Contract (Vitest AST Scan)',
    cmd: 'pnpm',
    args: ['--filter', '@sabiscore/web', 'test', 'src/lib/no-client-ev-contract.test.ts', '--run'],
    cwd: ROOT_DIR
  },
  {
    id: 15,
    title: 'Verify Responsible Gambling Copy Contract & Banned Term AST Scan',
    cmd: 'pnpm',
    args: ['--filter', '@sabiscore/web', 'test', 'src/lib/copy-contract.test.ts', '--run'],
    cwd: ROOT_DIR
  },
  {
    id: 16,
    title: 'Verify Heading Contract (Exactly 1 <h1> per page)',
    cmd: 'pnpm',
    args: ['--filter', '@sabiscore/web', 'test', 'src/lib/heading-contract.test.ts', '--run'],
    cwd: ROOT_DIR
  },
  {
    id: 17,
    title: 'Verify Probability Dumbbell, Full Dashboard & Evidence Provenance UI Components',
    cmd: 'pnpm',
    args: ['--filter', '@sabiscore/web', 'test', 'src/components/probability-dumbbell.test.tsx', 'src/components/full-analysis-dashboard.test.tsx', '--run'],
    cwd: ROOT_DIR
  },
  {
    id: 18,
    title: 'Verify Web TypeScript Typecheck Compilation',
    cmd: 'pnpm',
    args: ['--filter', '@sabiscore/web', 'typecheck'],
    cwd: ROOT_DIR
  },

  // ─── GATES 19–36: Empirical Model Certification & Governance (V19 Suite) ──
  {
    id: 19,
    title: 'Verify Dataset Fitness, Settlement Rate & League Coverage (Directive V19 Phase 3)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_19', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 20,
    title: 'Verify Candidate Generation Artifacts & Schema Lineage (Directive V19 Phase 2)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_20', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 21,
    title: 'Verify Adversarial Zero-Leakage & Temporal Order Protocol (Directive V19 Phase 6)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_21', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 22,
    title: 'Verify Evaluation Protocol SHA-256 Immutability Checksum (Directive V19 Phase 6)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_22', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 23,
    title: 'Verify Chronological Out-of-Sample Predictive Superiority (Directive V19 Phase 7)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_23', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 24,
    title: 'Verify Multi-Class Calibration Diagnostics & ECE (Directive V19 Phase 8)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_24', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 25,
    title: 'Verify Frozen C6 Market Benchmark 10,000 Bootstrap Evaluation (Directive V19 Phase 9)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_25', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 26,
    title: 'Verify Market Benchmark Identity & Registry Integrity (Directive V19 Phase 9)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_26', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 27,
    title: 'Verify Adversarial Stress & Robustness Diagnostics / C7-G (Directive V19 Phase 10)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_27', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 28,
    title: 'Verify Empirical Feature Ablation Incremental Signal (Directive V19 Phase 5)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_28', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 29,
    title: 'Verify Uncertainty Calibration & Dirichlet Decomposition / C7-I (Directive V19 Phase 10)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_29', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 30,
    title: 'Verify Covariate and Concept Drift Monitoring Policy / C7-J (Directive V19 Phase 10)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_30', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 31,
    title: 'Verify End-to-End Candidate Reproducibility Lineage Hash (Directive V19 Phase 2)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_31', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 32,
    title: 'Verify Candidate Shadow Validation Pipeline Execution (Directive V19 Phase 11)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_32', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 33,
    title: 'Verify Multi-Provider Data Gap Recovery Roadmap (Directive V19 Phase 3 & 4)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_33', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 34,
    title: 'Verify Live Provider Health & Circuit Breaker Readiness (Directive V19 Phase 15)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_34', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 35,
    title: 'Verify Active Generation Promotion Governance State Machine (Directive V19 Phase 12)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_35', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 36,
    title: 'Verify Rollback Invariants & Signed Executive Promotion Attestation (Directive V19 Phase 14 & 26)',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v19_certification.py', '-k', 'test_gate_36', '-v', '-c', 'backend/pytest.ini'],
    cwd: ROOT_DIR
  },
  {
    id: 37,
    title: 'Verify Phase 8 Serving Feature Bridge & Redis Rating Cache Parity',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v20_promotion.py', '-k', 'test_gate_37', '-v'],
    cwd: ROOT_DIR
  },
  {
    id: 38,
    title: 'Verify Market Alpha Calibration & Bounded Blend RPS Parity vs Open Market',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v20_promotion.py', '-k', 'test_gate_38', '-v'],
    cwd: ROOT_DIR
  },
  {
    id: 39,
    title: 'Verify C6 Live Sample Accumulation Pipeline & N>=200 Telemetry Gauge',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v20_promotion.py', '-k', 'test_gate_39', '-v'],
    cwd: ROOT_DIR
  },
  {
    id: 40,
    title: 'Verify Historical Closing Odds Backfill PIT Safety & Imputation Integrity',
    cmd: pythonBin,
    args: ['-m', 'pytest', 'backend/tests/unit/test_directive_v20_promotion.py', '-k', 'test_gate_40', '-v'],
    cwd: ROOT_DIR
  }
];

console.log('╔══════════════════════════════════════════════════════════════════════╗');
console.log('║       SABISCORE DIRECTIVE V20.0 — 40-GATE AUTHORITATIVE MATRIX       ║');
console.log('╚══════════════════════════════════════════════════════════════════════╝');
console.log(`Root Directory:   ${ROOT_DIR}`);
console.log(`Python Binary:    ${pythonBin}\n`);

let passedCount = 0;
let failedCount = 0;
const results = [];
const isWindows = process.platform === 'win32';

for (const step of STEPS) {
  process.stdout.write(`[${String(step.id).padStart(2, '0')}/${STEPS.length}] ${step.title} ... `);
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
    // Continue to collect a complete evidence matrix; any failure still makes
    // the process exit non-zero after every independent gate has run.
  }
}

console.log('\n══════════════════════════════════════════════════════════════════════');
console.log(`SUMMARY: ${passedCount} PASSED, ${failedCount} FAILED out of ${STEPS.length} verification steps`);
console.log('══════════════════════════════════════════════════════════════════════\n');

if (failedCount > 0) {
  process.exit(1);
} else {
  console.log('✓ All Directive V20.0 Attestation & Verification Checks PASSED.');
  process.exit(0);
}
