# SabiScore Apex Final Production Activation Directive

Last refined: 2026-08-10

## Role and outcome

Act as the release engineer for the canonical SabiScore repository. Inspect the
current tree and deployed evidence, implement only demonstrable gaps, and finish
with an evidence-backed release decision. The objective is a reliable football
intelligence product, not a larger feature count or a higher volume of bets.

Optimize for real data, calibrated probabilities, evidence completeness, coherent
market context, bounded latency, clear user decisions, accessibility, security,
and operational simplicity. Missing or conflicting evidence must remain visible
and non-executable.

## Instruction precedence and entry

1. Read `AGENTS.md`, then activate the `nexus` skill and read `NEXUS.md`.
2. Read the nearest nested `AGENTS.md` before changing backend, model, scraper,
   or web code.
3. Inspect `CLAUDE.md`, `CHANGELOG.md`, `docs/DEBT.md`,
   `docs/MODEL_CARD_APEX.md`, `docs/rollback.md`, and
   `docs/ai/CODEX_VERIFIED_STATE.md` as dated hints, not runtime truth.
4. Inspect Git branch/status, recent commits, authoritative source, tests, CI,
   and deployment configuration before editing.
5. Preserve unrelated changes. Never force-push or rewrite shared history.

Open implementation work with the repository NEXUS trace. Record each release
gate as `PASS`, `FAIL`, `BLOCKED`, or `SKIPPED`; a timeout or missing runner is
never a pass.

## Current starting evidence to reverify

The following describes the 2026-08-10 starting point and must be refreshed when
execution begins:

- The full backend suite last passed with 1,265 tests and 13 skips; the web lint,
  typecheck, 123 Vitest tests, production build, and 36 desktop/mobile Playwright
  cases also passed.
- Six active artifact pairs are hash-locked, but the active generation is
  `UNVERIFIED`; both betting engines therefore enforce zero stake.
- Live upcoming and model-performance proxy calls have timed out or returned
  structured 503 responses. Five warm upcoming responses below two seconds have
  not been demonstrated.
- Render and Vercel release-SHA parity has not been proven.
- GitHub required jobs have not executed on a runner; empty-step/billing failures
  are release blockers, not code passes.
- Current-tree secret scanning passed, but two historical findings lack recorded
  revocation evidence.
- Docker image builds and the Linux canonical `make verify` do not have successful
  evidence from the current release candidate.
- The local default interpreter is Python 3.14. The production runtime is Python
  3.11; CatBoost, SHAP, MLflow, and related research tools require an isolated
  Python 3.11-3.13 environment.

Do not repeat completed work unless current source or tests show regression.

## Canonical boundaries

- `backend/src/api/main.py` and backend services are authoritative for provider
  access, fixture identity, evidence, features, inference, calibration, market
  normalization, EV, Kelly, verdicts, abstention, settlement, and persistence.
- `apps/web` validates and proxies backend contracts, then explains backend truth.
  It must not calculate official probabilities, EV, stakes, verdicts, provider
  readiness, performance, or settlement outcomes.
- `apps/scraper` performs permitted acquisition and manifests only. It is not a
  provider-secret client or prediction engine.
- Alembic is the schema authority. Runtime table creation is forbidden.
- Browser bundles, logs, reports, fixtures, commits, and screenshots must contain
  no credentials.

## Truth and fail-closed invariants

Never fabricate fixtures, features, xG, injuries, lineups, odds, probabilities,
outcomes, accuracy, ROI, provider health, or model certification. Never convert a
missing probability or feature to zero merely to satisfy a schema.

Preserve these executable invariants:

- every probability is finite, in `[0, 1]`, and the 1X2 vector sums to one within
  the contract tolerance;
- evidence is temporally valid and no future observation enters training or
  serving features;
- a coherent 1X2 book uses one bookmaker snapshot;
- critical gaps force `PARTIAL`; `PARTIAL`, `NO_BET`, and `HOLD` expose zero stake;
- `stake_permitted=false` zeroes every stake in both independent engines;
- `SPECULATIVE` is watchlist-only and UCL never exceeds `ACTIONABLE`;
- Quarter-Kelly, league caps, the UCL ceiling, price sensitivity, de-vigging,
  abstention, and responsible-gambling copy remain intact;
- stale, incomplete, conflicting, timed-out, or uncertified analysis returns
  `No bet — insufficient evidence` with structured provenance and no executable
  recommendation.

## Execution work packages

### 1. Reconcile source, Git, and release truth

- Compare local HEAD, intended branch, `origin/master`, PR head, Render backend SHA,
  Vercel frontend SHA, aliases, and the custom domain.
- Use a clean worktree. Exclude unrelated local edits and
  `data/cache/football_data/E0_2324.csv` from release commits.
- Build a P0-P3 defect ledger from current evidence. Prefer small contract-safe
  fixes over broad rewrites.

### 2. Make upcoming intelligence bounded and database-first

- Keep interactive fixture reads database/cache-first. External fixture providers
  belong to the periodic sync path, not the request path.
- `include_predictions=false` must call neither models nor providers.
- Enforce backend and Next.js deadlines below Vercel’s function ceiling.
- Return additive `data_gap`, source, freshness, provenance, reason, and retry
  semantics for empty, stale, or timed-out data.
- `/value-bet-scan` may return only persisted, fresh, fully gated opportunities.
  It must not synchronously analyze a bulk fixture set.
- Instrument latency, cache outcomes, deadline outcomes, fixture sync, and provider
  classifications without logging secrets.

### 3. Preserve one public source of truth

- Health and performance values come only from settled backend predictions. Use
  nullable values and `Pending` when the sample is insufficient.
- Public outcome mutation remains retired. Client-local monitoring cannot provide
  accuracy, ROI, drift, or settlement truth.
- `/api/predict` remains a strict validated proxy. Preserve backend values and
  reject invalid simplexes or unverified fixture context.
- Model status must expose active version, generation, artifact hash, feature
  schema, served head, certification state, promotion state, and update time with
  no optimistic defaults.
- Readiness must expose backend and frontend release SHAs.

### 4. Establish model-research tooling without bypassing promotion

- Create an isolated Python 3.11-3.13 environment and install
  `backend/requirements-training.txt`. Verify imports with
  `backend/scripts/verify_training_stack.py`.
- MLflow is experiment observability only. Its URI must never be logged, it must
  not be imported when unconfigured, and it is not a production promotion
  authority.
- SHAP explanations must be derived from a successfully loaded real model and the
  exact serving feature vector. If unavailable or invalid, return an explicit
  explanation gap; never return mock feature importance.
- CatBoost is a disabled shadow candidate until chronological evaluation proves it
  improves the primary metric without calibration, league, responsiveness,
  coherent-price, latency, feature-availability, or abstention regression.
- Installing a library is not evidence of accuracy improvement.

### 5. Apply the settlement and promotion hard gate

Before any feature-selection, tuning, retraining, calibration, drift-threshold, or
promotion change, prove that the settlement pipeline is running against real data
and report the settled sample count. If that proof is absent or the count is zero,
stop model-changing work and mark it blocked while continuing independent
availability, UX, security, test, and documentation work.

When the gate clears:

1. Produce a feature-availability matrix with training source, serving source,
   coverage, missingness, freshness, variability, and defaulted slots.
2. Use chronological training, later calibration, and an untouched final test set.
3. Report RPS, Brier, log loss, calibration, accuracy, coverage, abstention, sample
   sizes, league-prior baseline, market baseline, and pooled fallbacks.
4. Require valid simplexes, input responsiveness, coherent-price perturbation
   behavior, serving-time feature availability, primary-metric improvement, and no
   league-gate regression.
5. Keep existing numerical promotion thresholds unchanged.
6. Promote only the complete artifact/metadata set through the committed,
   hash-validated active-generation manifest. Rollback reverts that release commit.

Keep v5 active unless every candidate gate passes. If the active generation itself
cannot be certified, analytical output may continue but both betting engines must
enforce zero stake.

### 6. Finish the decision experience

Verify the complete `/intelligence` flow on desktop and mobile:

- competition and real-fixture selection;
- bounded loading, retry, empty, timeout, `PARTIAL`, `HOLD`, and `NO_BET` states;
- concise prediction summary, uncertainty, reasons, evidence gaps, freshness,
  market context, fair price, acceptable-price ceiling, and stake permission;
- pending performance and accurate model metadata;
- visible focus, keyboard operation, WCAG AA contrast, screen-reader labels,
  reduced motion, stable layout, and responsible-gambling language.

Do not redesign components that already pass these checks. Fix concrete defects and
add regression coverage. Preserve nonce/`strict-dynamic` CSP and all security
headers. Prohibited public claims include `lock`, `banker`, `guaranteed`,
`sure bet`, `free money`, and `execute immediately`.

### 7. Security and operator checkpoints

- Run current-tree and full-history Gitleaks with redacted output.
- Never waive an active secret. For a historical finding, first record provider-side
  revocation/rotation evidence, then waive only its exact fingerprint with owner,
  date, and rationale. Do not rewrite shared history.
- A Render Redis change is an operator checkpoint: configure a valid `rediss://`
  secret, prove connectivity, revoke the prior value, and inspect redacted logs.
- Do not consume provider quota in CI. Live provider checks require explicit
  operator approval and remain bounded.

### 8. Verification

Run focused tests after each change, then all available release gates:

- Ruff; full backend pytest; active-artifact verification; dual-engine, model,
  odds, timeout, provider, secret-safety, OpenAPI, settlement, and migration tests;
- mypy with a no-new-errors ceiling against the recorded 783-error baseline;
- scraper doctor/tests and manifest validation;
- web lint, typecheck, all Vitest tests, production build, prohibited-copy/CSP scan,
  Playwright desktop/mobile flows, and accessibility checks;
- Alembic upgrade/check on an isolated production-like database;
- Gitleaks current tree and full history;
- Docker Compose config, backend image, and web image;
- canonical Linux `make verify` and all required GitHub checks.

Do not suppress a failed gate. Capture the command, exit status, result count, and
material warning. Distinguish product defects from runner, credential, database,
network, provider, and operator blockers.

### 9. Documentation and Git delivery

Update `CHANGELOG.md`, `docs/DEBT.md`, `docs/MODEL_CARD_APEX.md`, deployment and
rollback guidance, and `docs/ai/CODEX_VERIFIED_STATE.md` with executed evidence and
unresolved blockers. Re-derive numerical claims; do not copy old metrics forward.

Commit cohesive Conventional Commits to the intended feature branch and update the
PR only after focused checks pass. Push or fast-forward `master` only when required
security, backend, web, Playwright, model-validation, migration, image, and CI gates
have passed. Never use direct master push to bypass a protected or unavailable
required check.

Deploy only the certified merged SHA. Render activation follows the Redis operator
checkpoint and migration verification. Vercel promotion follows exact backend SHA
proof. Require five successful upcoming probes within the proxy deadline, warm
latency below two seconds, a bounded full analysis, correct CSP, and no new timeout
cluster during observation. Be ready to roll back by reverting the release commit.

## Terminal acceptance test

A release candidate passes only when a user can select a real supported competition
and upcoming fixture, request bounded intelligence, understand probabilities and
uncertainty, inspect reasons/provenance/freshness, see coherent market and risk
context when available, and understand an abstention when evidence is insufficient.
The same result must be reproducible, temporally valid, settleable, auditable,
accessible, responsive, and traceable to the deployed SHAs.

## Required final report

Lead with exactly one repository-standard decision:

- `PRODUCTION READY`
- `READY WITH DOCUMENTED LIMITATIONS`
- `NOT SAFE FOR PRODUCTION`

Then report:

1. current branch, local/remote/deployed SHA parity;
2. P0-P3 findings and implemented work packages;
3. files changed and compatibility/security/performance implications;
4. prediction capability by competition and the settled sample count;
5. model/tooling state, certification state, and why any candidate stayed shadowed;
6. UI/UX and accessibility verification;
7. exact verification matrix with `PASS`/`FAIL`/`BLOCKED`/`SKIPPED`;
8. operator-only actions and evidence-backed remaining debt.

Never describe an unexecuted check, commit, push, deployment, provider call, model
evaluation, or production state as completed.
