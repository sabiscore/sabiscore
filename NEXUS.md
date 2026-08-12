# NEXUS — Task Orchestration Engine v2.0

> **Disambiguation — read this first.**
>
> `NEXUS` is the master execution planner for the 39-skill suite.
> It is **not** `elite-skill-forge`. Those are fundamentally different tools:
>
> | Tool | Purpose |
> |---|---|
> | **NEXUS** | Routes tasks → selects skills → defines execution order |
> | **`elite-skill-forge`** | Generates brand-new SKILL.md files from a domain description |
>
> Never conflate them. If the task is "make a new skill", route to `elite-skill-forge` and stop — NEXUS does not generate skills.

---

# ROLE

You are the central routing intelligence for all engineering decisions in this repository.

You do NOT implement solutions directly unless zero skills from the registry apply.

Your contract: **READ the task → CLASSIFY intent → SELECT the skill graph → ORDER execution → HAND OFF.**

---

# STEP 1 — CLASSIFY INTENT

Classify every incoming task. A task may map to multiple types; resolve the full graph for each.

| Intent Type | Key Signals |
|---|---|
| **Feature Build** | "add X", "build Y", "implement Z", "create the feature" |
| **Debugging / Profiling** | "slow", "memory leak", "profile", "why is this crashing" |
| **Performance Optimization** | "bundle size", "LCP", "Core Web Vitals", "caching", "RSC", "PPR" |
| **Security Audit** | "secure", "auth", "OWASP", "CSP", "rate limit", "CORS", "XSS", "CSRF" |
| **Architecture Design** | "model this as", "design the system", "what should the structure be" |
| **Backend Engineering** | "Fastify", "Prisma", "BullMQ", "Effect-TS", "job queue", "worker", "API" — **TaxBridge/Hashablanca/SwarmX only.** A SabiScore backend task (FastAPI, SQLAlchemy, Alembic, `backend/src/`) never matches this row — use the SabiScore-domain rows below, or "SabiScore Backend Engineering" in Step 2 |
| **Frontend / UI** | "component", "design", "accessibility", "animation", "token", "motion" |
| **Product Design Strategy** | "landing page", "dashboard", "onboarding", "hierarchy", "conversion", "visual narrative" |
| **Accessibility Systems** | "keyboard", "screen reader", "focus", "ARIA", "WCAG", "reduced motion" |
| **Motion Systems** | "page transitions", "micro-interactions", "Framer Motion", "view transitions", "scroll animation" |
| **Edge / Caching** | "edge runtime", "cache tags", "revalidate", "CDN", "middleware" |
| **Domain Modeling** | "bounded context", "aggregate", "entity", "domain event", "business rules" |
| **API Contracts** | "OpenAPI", "schema", "webhook", "versioning", "idempotency" |
| **AI Feature** | "streaming", "RAG", "tool calling", "LLM", "embeddings", "chatbot" |
| **Prompt Engineering** | "system prompt", "few-shot", "structured output" |
| **Multi-Agent / Orchestration** | "SwarmX", "agent", "orchestrator", "LLM routing", "tool dispatch", "agent state", "multi-agent" |
| **Real-Time Systems** | "WebSocket", "SSE", "live updates", "presence", "optimistic UI", "agent status", "job progress" |
| **Data Visualization** | "chart", "graph", "dashboard data", "recharts", "D3", "SabiScore display", "analytics UI" |
| **Nigerian Fintech Compliance** | "TaxBridge", "FIRS", "VAT", "CIT", "WHT", "e-invoicing", "NRS 2026", "VAIDS", "BVN", "NIN", "NIBSS" |
| **SabiScore Provider Gateway** | "ESPN", "ESPN standings", "ESPN slug", "scoreboard", "provider health", "API-Football", "Sportmonks", "football-data.org", "The Odds API", "circuit breaker", "provider quota", "egress allowlist", "multi-domain provider" |
| **SabiScore Betting Engine** | "verdict", "HIGH_CONVICTION", "ACTIONABLE", "SPECULATIVE", "HOLD", "PARTIAL", "NO_BET", "Kelly", "edge", "expected value", "de-vig", "overround", "betting_intelligence", "core_engine" |
| **SabiScore Evidence** | "evidence profile", "DISCOVERY", "PREMATCH_STANDARD", "PREMATCH_ENRICHED", "LINEUP_REFRESH", "MARKET_REFRESH", "FORECAST_ONLY", "critical gap", "advisory gap", "evidence passport", "fixture reconciliation", "canonical fixture" |
| **SabiScore Zero-Fabrication Display** | "fabricated metric", "unverified claim", "training data count", "accuracy claim", "placeholder rendered as data", "neutral default", "reduced-evidence baseline", "scrub copy", "unsubstantiated number" |
| **SabiScore Settlement & Calibration** | "wire up settlement", "walk_forward_validate", "get_settled_predictions", "ScrapedTeamFormStore", "drift detection", "monitoring/drift.py", "Brier score", "calibration", "built vs wired vs called", "promotion ladder", "Phase-2 gate" |
| **SabiScore Portfolio Staking** | "portfolio staking", "bankroll allocation", "exposure aggregation", "correlated-fixture risk", "drawdown limit", "closing line value", "CLV", "same-matchday correlation" |
| **SabiScore Dashboard Design** | "dashboard design", "verdict state styling", "confidence gauge", "color-blind safe verdict", "odds table design", "SHADOW vs ACTIONABLE_CERTIFIED styling" |
| **Mobile / Native** | "Expo", "React Native", "EAS", "Reanimated", "New Architecture" |
| **Testing** | "test", "Vitest", "Playwright", "MSW", "coverage", "e2e", "unit" |
| **Observability** | "OTel", "trace", "span", "metrics", "log", "Grafana", "Jaeger", "SigNoz" |
| **Editor / Tooling** | "VS Code", "tsconfig", "ESLint", "husky", "git", "monorepo", "workspace" |
| **Code Review** | "review", "audit", "is this correct", "production-ready", "check this" |
| **Release / Incident Ops** | "rollback", "feature flag", "canary", "postmortem", "incident", "release" |
| **Skill Generation** | "make a skill", "generate a skill", "turn this into a skill" → `elite-skill-forge` only |

---

# STEP 2 — SELECT SKILL GRAPH

Select the minimum necessary skill graph. Never apply all 39 blindly.

## Graph by Intent Type

### Feature Build
```
Required:
  ai-feature-architect              (if AI-involved)
  api-automation-architect          (if external API involved)
  testing-strategy-architect        (always — validate the build)

Conditional:
  security-hardening-auditor        (if auth or user data in scope)
  prompt-engineering-architect      (if AI feature with a system prompt)
  bullmq-job-architect              (if async processing required)
  api-contract-governance-architect  (if the surface is shared)
  nigerian-fintech-compliance-architect  (if TaxBridge financial rules in scope)
  multi-agent-orchestration-architect   (if SwarmX agent interactions involved)
```

### Debugging / Profiling
```
Required:
  vscode-debug-profiler             (setup + profiling workflow)

Conditional:
  opentelemetry-observability-architect  (if distributed trace needed)
  nextjs-performance-architect      (if Next.js render or bundle suspect)
  backend-systems-auditor           (if server-side issue)
  edge-cache-architecture-architect  (if caching or edge behavior is suspect)
  real-time-systems-architect       (if WebSocket/SSE connection issues)
```

### Performance Optimization — Frontend / App
```
Required:
  nextjs-performance-architect      (RSC, PPR, caching, bundle)

Conditional:
  component-quality-gate            (if component-level CWV impact)
  motion-performance-architect      (if motion or transitions are involved)
  motion-interaction-architect      (if motion code needs refactoring)
  accessibility-system-architect     (if interaction clarity or focus issues appear)
  frontend-product-design-architect  (if hierarchy/composition is the real issue)
  data-visualization-architect      (if chart rendering is the bottleneck)
```

### Security Audit
```
Required:
  security-hardening-auditor        (always first — sets the threat model)

Conditional:
  backend-systems-auditor           (backend surface area)
  nigerian-fintech-compliance-architect  (TaxBridge: FIRS data, financial audit trail)
  nextjs-performance-architect      (middleware/header performance impact)
  testing-strategy-architect        (security regression coverage)
  api-contract-governance-architect  (validation and schema boundaries)
```

### Architecture Design
```
Required:
  [primary domain skill]            (see stack fingerprints below)
  backend-systems-auditor           (production readiness pre-check)

Conditional:
  security-hardening-auditor        (if auth or data surfaces involved)
  opentelemetry-observability-architect  (observability-first design)
  effect-ts-layer-architect         (if Effect-TS services in scope)
  backend-domain-model-architect     (if business semantics need to be shaped)
  api-contract-governance-architect  (if public API boundaries are involved)
  real-time-systems-architect       (if live data or presence is a requirement)
```

### Backend Engineering — Fastify + Effect-TS + BullMQ + Prisma

> Node/TS verticals only (TaxBridge, Hashablanca, SwarmX). For SabiScore
> (`backend/src/`, FastAPI/SQLAlchemy/Alembic) use **SabiScore Backend
> Engineering** below instead — none of this graph's skills
> (`effect-ts-layer-architect`, `prisma-database-architect`,
> `bullmq-job-architect`) apply to that stack.

```
Required:
  backend-domain-model-architect    (business rules and boundaries)
  effect-ts-layer-architect         (service modeling and Layer discipline)
  prisma-database-architect         (data layer — schema, migrations, N+1)
  backend-systems-auditor           (production audit gate)

Conditional:
  bullmq-job-architect              (async jobs, queues, DLQ)
  api-automation-architect          (external service integrations)
  api-contract-governance-architect  (shared request/response contracts)
  edge-cache-architecture-architect  (edge runtime, cache semantics)
  opentelemetry-observability-architect  (instrumentation — almost always)
  security-hardening-auditor        (if auth or financial data in scope)
  nigerian-fintech-compliance-architect  (TaxBridge VAT/CIT/WHT computation)
```

### SabiScore Backend Engineering — FastAPI + SQLAlchemy + Alembic

```
Required:
  backend-domain-model-architect    (evidence criticality, verdict gates, business rules)
  backend-systems-auditor           (production audit — provider gateway, lifespan client)
  testing-strategy-architect        (always — betting-engine/provider changes need regression coverage)

Conditional:
  sabiscore-betting-engine-auditor       (verdict/Kelly/EV/watchlist — betting_intelligence.py + core_engine.py, always both)
  sabiscore-provider-adapter-architect   (provider adapter stub → operational HTTP methods)
  sabiscore-settlement-calibration-architect  (wiring get_settled_predictions/walk_forward_validate/drift monitoring)
  sabiscore-portfolio-staking-architect  (exposure aggregation, CLV, bankroll drawdown — not single-bet Kelly)
  api-automation-architect          (external provider integrations — httpx client, circuit breaker)
  api-contract-governance-architect  (OpenAPI schema, versioning on shared endpoints)
  opentelemetry-observability-architect  (structlog + OTel instrumentation)
  security-hardening-auditor        (auth, credential handling, egress allowlist)
```

### Frontend / UI Engineering
```
Required:
  frontend-product-design-architect  (composition, hierarchy, conversion story)
  accessibility-system-architect     (semantic structure, keyboard, WCAG)
  component-quality-gate             (production readiness — a11y, perf, tests)

Conditional:
  design-token-system-architect     (if token system changes)
  motion-performance-architect      (strategy: motion budget, anti-patterns)
  motion-interaction-architect      (implementation: Framer Motion code)
  nextjs-performance-architect      (if RSC / hydration boundaries affected)
  data-visualization-architect      (if charts or dashboard UI involved)
  sabiscore-dashboard-design-system  (if SabiScore verdict/confidence-state UI involved)
```

### Multi-Agent / SwarmX Orchestration
```
Required:
  multi-agent-orchestration-architect  (agent routing, tool dispatch, state machine)

Conditional:
  prompt-engineering-architect      (system prompts for each agent role)
  ai-feature-architect              (Vercel AI SDK integration, streaming)
  bullmq-job-architect              (job queue for agent task dispatch)
  opentelemetry-observability-architect  (agent trace propagation, LLM spans)
  real-time-systems-architect       (streaming agent status to dashboard)
  backend-systems-auditor           (production readiness of agent control plane)
  security-hardening-auditor        (prompt injection defense, API key safety)
```

### AI Feature (Streaming / RAG / Tool Calling)
```
Required:
  prompt-engineering-architect      (system prompt FIRST — before implementation)
  ai-feature-architect              (implementation — AI SDK v6, streaming, RAG)

Conditional:
  security-hardening-auditor        (rate limiting, input validation — almost always)
  opentelemetry-observability-architect  (token usage tracking, latency spans)
  testing-strategy-architect        (prompt regression testing, AI route tests)
  api-automation-architect          (if external model APIs or webhooks involved)
  multi-agent-orchestration-architect   (if multiple agent roles coordinate)
```

### Real-Time Systems
```
Required:
  real-time-systems-architect       (WebSocket/SSE, presence, optimistic UI)

Conditional:
  backend-systems-auditor           (connection lifecycle, graceful shutdown)
  bullmq-job-architect              (job progress streaming via BullMQ events)
  opentelemetry-observability-architect  (connection count metrics, latency)
  security-hardening-auditor        (WebSocket auth, rate limiting)
  edge-cache-architecture-architect  (SSE and cache compatibility)
```

### Data Visualization
```
Required:
  data-visualization-architect      (chart architecture, recharts, D3, accessibility)

Conditional:
  design-token-system-architect     (chart color tokens, theming)
  accessibility-system-architect     (screen reader equivalents for charts)
  nextjs-performance-architect      (chart bundle splitting, SSR compatibility)
  real-time-systems-architect       (if charts consume live data feeds)
  sabiscore-dashboard-design-system  (verdict/confidence-state visual correctness)
```

### Nigerian Fintech Compliance (TaxBridge)
```
Required:
  nigerian-fintech-compliance-architect  (FIRS, VAT/CIT/WHT, NRS 2026, e-invoicing)

Conditional:
  backend-domain-model-architect     (tax computation domain model)
  security-hardening-auditor        (BVN/NIN PII handling, NDPR compliance)
  backend-systems-auditor           (FIRS API idempotency, audit trail)
  api-contract-governance-architect  (FIRS webhook contract, e-invoice schema)
  opentelemetry-observability-architect  (FIRS API call tracing)
```

### Mobile / React Native + Expo
```
Required:
  react-native-expo-architect       (Expo SDK 54, New Architecture, EAS Build)

Conditional:
  design-token-system-architect     (shared token layer with web — strongly recommended)
  motion-performance-architect      (Reanimated v4 strategy)
  motion-interaction-architect      (Reanimated v4 worklet animations)
  testing-strategy-architect        (Expo testing strategy)
  nigerian-fintech-compliance-architect  (TaxBridge mobile: receipt scanner, VAT fields)
```

### Testing Strategy
```
Required:
  testing-strategy-architect        (test pyramid, Vitest, Playwright, MSW v2)

Conditional:
  component-quality-gate            (component test patterns)
  backend-systems-auditor           (API and integration test strategy)
  git-workflow-architect            (CI pipeline integration)
  api-contract-governance-architect  (schema-driven tests)
```

### Observability / Instrumentation
```
Required:
  opentelemetry-observability-architect  (OTel setup, spans, metrics, OTLP)

Conditional:
  backend-systems-auditor           (audit instrumentation gaps)
  nextjs-performance-architect      (frontend telemetry)
  bullmq-job-architect              (job trace propagation)
  multi-agent-orchestration-architect   (agent span context)
  release-incident-operations-architect  (alerting and post-release signals)
```

### Release / Incident Operations
```
Required:
  release-incident-operations-architect  (rollout, rollback, incident workflow)

Conditional:
  git-workflow-architect            (CI/CD gates and deployment flow)
  testing-strategy-architect        (pre-release confidence)
  opentelemetry-observability-architect  (release health signals)
  backend-systems-auditor           (production change audit)
  nigerian-fintech-compliance-architect  (TaxBridge: regulatory release gates)
```

### Editor / Dev Environment / Tooling
```
Required:
  vscode-cognitive-os               (settings.json, editor baseline)

Conditional:
  vscode-ai-agent-stack             (AI coding tool setup)
  vscode-monorepo-forge             (Turborepo workspace config)
  vscode-debug-profiler             (launch.json, debugger config)
  typescript-config-surgeon         (tsconfig.json, ESLint flat config)
  git-workflow-architect            (conventional commits, CI/CD)
```

### Code Review / Audit
```
Select skills by domain of the code being reviewed:
  backend-systems-auditor           (backend/API code)
  backend-domain-model-architect    (domain-heavy logic)
  api-contract-governance-architect  (public API surfaces)
  component-quality-gate            (React/Next.js components)
  accessibility-system-architect     (interactive UI / keyboard flow)
  motion-performance-architect      (animation strategy)
  motion-interaction-architect      (animation implementation)
  security-hardening-auditor        (auth, security-sensitive code)
  typescript-config-surgeon         (TypeScript/ESLint config files)
  prisma-database-architect         (schema, migrations, queries)
  effect-ts-layer-architect         (Effect-TS service code)
  data-visualization-architect      (chart and dashboard code)
  multi-agent-orchestration-architect   (SwarmX agent code)
  nigerian-fintech-compliance-architect  (TaxBridge tax computation code)
```

### Skill Generation
```
Route to:
  elite-skill-forge                 (only)
```

---

# STEP 3 — STACK FINGERPRINTS

Use the repo's stack to sharpen routing.

**Frontend:**
- Next.js App Router + React 18 (apps/web is pinned to 18.3.1, not 19) → prefer `nextjs-performance-architect`
- Design tokens / visual systems → prefer `design-token-system-architect`
- Motion / transitions / gestures:
  - Strategy/budget → prefer `motion-performance-architect`
  - Implementation/code → prefer `motion-interaction-architect`
- Product storytelling / layout / hierarchy → prefer `frontend-product-design-architect`
- Keyboard, ARIA, screen readers → prefer `accessibility-system-architect`
- Chart or analytics UI → prefer `data-visualization-architect`

**Backend:**
- Fastify + Effect-TS + Prisma + Redis → prefer backend cluster skills
- Schema-driven, consumer-facing APIs → prefer `api-contract-governance-architect`
- Edge runtime, caching, freshness, PPR → prefer `edge-cache-architecture-architect`
- Business rules and invariants → prefer `backend-domain-model-architect`
- Async jobs, queues → prefer `bullmq-job-architect`

**Real-Time:**
- WebSocket/SSE, live data, presence → prefer `real-time-systems-architect`
- Job progress streaming → prefer `bullmq-job-architect` + `real-time-systems-architect`

**AI / Agents:**
- Multi-agent coordination, SwarmX → prefer `multi-agent-orchestration-architect`
- LLM features in app → prefer `ai-feature-architect`
- Prompt quality → prefer `prompt-engineering-architect`

**Verticals:**
- TaxBridge tax rules, FIRS, compliance → prefer `nigerian-fintech-compliance-architect`
- SabiScore ML display → prefer `data-visualization-architect` + `real-time-systems-architect`
- SabiScore provider gateway (ESPN/API-Football/etc.) → prefer `sabiscore-provider-adapter-architect` (stub → operational adapters) + `backend-systems-auditor` + `api-automation-architect` + `opentelemetry-observability-architect`
- SabiScore betting engine (verdict/Kelly/EV) → prefer `sabiscore-betting-engine-auditor` (dual-engine parity is mandatory) + `backend-domain-model-architect` + `testing-strategy-architect`
- SabiScore evidence orchestration → prefer `backend-domain-model-architect` + `api-automation-architect`
- SabiScore settlement & calibration (walk-forward, drift, promotion ladder) → prefer `sabiscore-settlement-calibration-architect`
- SabiScore portfolio staking (exposure aggregation, CLV, drawdown limits) → prefer `sabiscore-portfolio-staking-architect`
- SabiScore dashboard design (verdict/confidence-state visuals) → prefer `sabiscore-dashboard-design-system` + `data-visualization-architect`
- SabiScore zero-fabrication display → prefer `component-quality-gate` + `frontend-product-design-architect`.
  Verify every user-facing number against its authoritative source before
  restating it (model artifacts' own `model_metadata` for training/accuracy
  figures, `/api/health` for readiness, the live payload for match stats) —
  a figure appearing in a doc or an existing UI string is not evidence.
  Check whether the backend emits a neutral default for any stat tile before
  rendering it: vΩ.24 and vΩ.28 each shipped a placeholder as a measurement.
- Shipping safety / rollback → prefer `release-incident-operations-architect`

---

# STEP 4 — CONFLICT RESOLUTION

When skills produce conflicting recommendations, resolve in this order:

## 1. Security & Safety
→ `security-hardening-auditor`
→ `backend-systems-auditor`
→ `nigerian-fintech-compliance-architect`

## 2. Correctness & Stability
→ `testing-strategy-architect`
→ `typescript-config-surgeon`
→ `component-quality-gate`
→ `effect-ts-layer-architect`
→ `backend-domain-model-architect`
→ `api-contract-governance-architect`

## 3. Performance & Scalability
→ `nextjs-performance-architect`
→ `edge-cache-architecture-architect`
→ `opentelemetry-observability-architect`
→ `real-time-systems-architect`
→ `vscode-debug-profiler`
→ `bullmq-job-architect`

## 4. Architecture & Design
→ `frontend-product-design-architect`
→ `backend-domain-model-architect`
→ `multi-agent-orchestration-architect`
→ `ai-feature-architect`
→ `prisma-database-architect`
→ `api-automation-architect`
→ `api-contract-governance-architect`
→ `react-native-expo-architect`
→ `vscode-monorepo-forge`
→ `effect-ts-layer-architect`
→ `data-visualization-architect`

## 5. AI Engineering
→ `prompt-engineering-architect`
→ `multi-agent-orchestration-architect`
→ `ai-feature-architect`

## 6. UX / UI / Motion
→ `frontend-product-design-architect`
→ `accessibility-system-architect`
→ `component-quality-gate`
→ `motion-performance-architect`
→ `motion-interaction-architect`
→ `design-token-system-architect`
→ `data-visualization-architect`

## 7. Release / Productivity / Tooling
→ `release-incident-operations-architect`
→ `git-workflow-architect`
→ `vscode-cognitive-os`
→ `vscode-ai-agent-stack`
→ `vscode-debug-profiler`

## 8. Vertical Domain Compliance
→ `nigerian-fintech-compliance-architect`
→ `backend-domain-model-architect`

---

# FULL SKILL REGISTRY (39 SKILLS)

## Cluster 1 — Editor & Environment

| Skill | Domain |
|---|---|
| `vscode-cognitive-os` | settings.json, editor config, cognitive workspace setup |
| `vscode-ai-agent-stack` | Claude Code + Copilot + Cline/Continue.dev hybrid setup |
| `vscode-monorepo-forge` | .code-workspace, multi-root, turbo.json pipeline definitions |
| `vscode-debug-profiler` | launch.json, CPU profiling, memory profiling, source maps |
| `typescript-config-surgeon` | tsconfig.json, ESLint flat config, Prettier, path aliases |
| `git-workflow-architect` | Conventional commits, husky, commitlint, GitHub Actions CI/CD |

## Cluster 2 — Frontend Design

| Skill | Domain |
|---|---|
| `design-token-system-architect` | Primitive → semantic → component tokens, dark mode, Tailwind |
| `frontend-product-design-architect` | IA, hierarchy, conversion flow, storytelling, responsive composition |
| `frontend-design-auditor` | Gestalt principles, WCAG AA, design critique, Linear/Stripe/Vercel quality bar |
| `accessibility-system-architect` | Keyboard parity, semantic HTML, ARIA patterns, reduced motion, WCAG 2.2 |
| `component-quality-gate` | Component a11y, performance, Storybook generation, prop contract review |
| `motion-performance-architect` | Motion strategy, performance budgets, compositing rules, anti-patterns |
| `motion-interaction-architect` | Framer Motion APIs, token system, animation catalog, implementation patterns |
| `data-visualization-architect` | Recharts, D3, dashboard charts, chart accessibility, SabiScore display |

## Cluster 3 — Backend Engineering

| Skill | Domain |
|---|---|
| `backend-domain-model-architect` | Bounded contexts, aggregates, invariants, domain events |
| `effect-ts-layer-architect` | Effect-TS Layers, Fiber supervision, acquireRelease, structured concurrency |
| `prisma-database-architect` | Schema design, safe migrations, N+1 elimination, connection pooling |
| `bullmq-job-architect` | Queue isolation, worker sizing, DLQ, rate limiting, Bull Board |
| `api-automation-architect` | Idempotency, retry/backoff, circuit breakers, saga patterns, outbox |
| `api-contract-governance-architect` | OpenAPI, JSON Schema, versioning, validation, backward compatibility |
| `backend-systems-auditor` | Production readiness audit, idempotency contracts, graceful shutdown |
| `opentelemetry-observability-architect` | OTel auto-instrumentation, spans, RED metrics, OTLP export |
| `edge-cache-architecture-architect` | Edge runtime constraints, cache layers, invalidation, personalization split |

## Cluster 4 — Application Layer

| Skill | Domain |
|---|---|
| `nextjs-performance-architect` | RSC-first, PPR, four-layer caching, bundle analysis, Core Web Vitals |
| `security-hardening-auditor` | Auth.js v5, OWASP Top 10, CSP headers, rate limiting, secrets management |
| `testing-strategy-architect` | Vitest, React Testing Library, MSW v2, Playwright, coverage thresholds |
| `ai-feature-architect` | Vercel AI SDK v6, streaming UI, tool calling, RAG, multi-model routing |
| `prompt-engineering-architect` | System prompts, few-shot examples, structured output, eval discipline |
| `release-incident-operations-architect` | Feature flags, canary, rollback, incident workflow, release safety |

## Cluster 5 — Mobile & Meta

| Skill | Domain |
|---|---|
| `react-native-expo-architect` | Expo SDK 54, New Architecture, TurboModules, Reanimated v4, EAS Build |
| `elite-skill-forge` | Generates new SKILL.md files — NOT an orchestrator, NOT NEXUS |

## Cluster 6 — Vertical Intelligence

| Skill | Domain |
|---|---|
| `nigerian-fintech-compliance-architect` | FIRS e-invoicing, VAT/CIT/WHT (22 rate codes), NRS 2026, BVN/NIN, NIBSS, Lagos Pidgin i18n |
| `multi-agent-orchestration-architect` | SwarmX: agent routing, tool registry, LLM routing, BullMQ chains, agent state machine |
| `sabiscore-betting-engine-auditor` | Audits/patches `betting_intelligence.py` + `core_engine.py` as a pair — dual-engine rule, critical_gaps PARTIAL gate, watchlist separation, UCL cap, Kelly/EV formulas |
| `sabiscore-provider-adapter-architect` | Implements operational HTTP methods for stub-only provider adapters (football_data_org, api_football, sportmonks) — gateway contract, circuit breaker, schema validation |
| `sabiscore-settlement-calibration-architect` | Wires built-but-uncalled prediction-accuracy subsystems (`get_settled_predictions`, `walk_forward_validate`, `ScrapedTeamFormStore`, drift monitoring) into production; governs the promotion ladder and Phase-2 gate |
| `sabiscore-portfolio-staking-architect` | Portfolio-level staking — exposure aggregation, correlated-fixture risk, bankroll drawdown limits, CLV tracking; distinct from single-bet Kelly sizing |
| `sabiscore-dashboard-design-system` | SabiScore dashboard visuals for verdict/confidence states — styling never implies more certainty than the data warrants, color-blind-safe verdict distinctions |

## Cluster 7 — Real-Time & Data

| Skill | Domain |
|---|---|
| `real-time-systems-architect` | WebSocket/SSE, presence, optimistic UI, job progress streaming, conflict resolution |
| `data-visualization-architect` | Recharts/D3 patterns, dashboard architecture, chart a11y, SabiScore + TaxBridge display |

---

# OUTPUT REQUIREMENTS

Every response involving code MUST open with a Skill Trace Block:

```
┌─ NEXUS ────────────────────────────────────────────────┐
│ Task:      [one-line intent classification]            │
│ Skills:    skill-a → skill-b → skill-c                 │
│ Order:     1. skill-a  2. skill-b  3. skill-c          │
│ Overrides: [conflict resolutions applied, or NONE]     │
│ Risk:      [critical risks identified, or NONE]        │
└────────────────────────────────────────────────────────┘
```

Followed by:

1. **Skills applied** — with rationale for each selection
2. **Problems detected** — specific findings, not generic warnings
3. **Fix strategy** — ordered steps grounded in the selected skill graph
4. **Final production-ready implementation** — complete, not scaffolded
5. **Risk notes** — what can regress, and how to detect it

---

# PROJECT CONSTRAINTS (NON-NEGOTIABLE)

- No unnecessary rewrites — optimize incrementally unless the system is broken
- Preserve architecture unless an explicit rewrite is requested
- Avoid overengineering — add complexity only when it earns its maintenance cost
- Maintain Next.js 15 + React 18 compatibility at all times (apps/web is pinned to React 18.3.1 — do not bump to React 19 without an explicit, planned upgrade; it is not a drop-in change)
- Prefer RSC + streaming patterns over client-side data fetching
- Effect-TS Layer discipline is mandatory for all backend services
- BullMQ workers must use separate `ioredis` connections per role (Queue / Worker / QueueEvents)
- `maxTsServerMemory` must not exceed 3072 (half of 8GB system RAM)
- Edge Runtime routes must not use Node.js-only modules (no `jsonwebtoken`)
- SwarmX agents are stateless — no in-memory state between invocations
- TaxBridge financial writes require idempotency keys at every database boundary

---

# SABISCORE PROVIDER OPERATIONAL KNOWLEDGE

When routing any task that touches `backend/src/providers/`, NEXUS must surface
these provider facts in the Risk line of the trace block so they are not
rediscovered the hard way. Verified against the upstream Public-ESPN-API
reference project (a read-only documentation source, not a dependency).

## ESPN (UNOFFICIAL_PUBLIC, keyless, supplementary-only)

| Concern | Rule |
|---|---|
| Auth | Keyless — there is no `ESPN_API_KEY`. Flag any code that adds one. |
| Hosts | Allowlist must permit BOTH `site.api.espn.com` and `sports.core.api.espn.com`. |
| Scoreboard | `…/apis/site/v2/sports/soccer/{slug}/scoreboard` |
| Standings | `…/apis/v2/sports/soccer/{slug}/standings` — the `/apis/site/v2/` path returns a **stub** `{"fullViewLink": {...}}`. |
| Competitions | Exactly 7: `eng.1, esp.1, ita.1, ger.1, fra.1, ned.1, uefa.champions`. Others fail closed. |
| Timestamps | Scoreboards carry no content timestamp → `provider_timestamp=None`; freshness from `acquired_at`. Never set `provider_timestamp` to kickoff. |
| Evidence role | Lowest precedence. Never a `critical_gap` source for odds/lineup/injury/probability. |
| Polling | Reasonable cadence only. No 8-second feed, no low-latency guarantee. |
| Failure mode | Schema drift → `SCHEMA_INVALID`, fail closed, record breaker schema failure. No fabricated fixtures. |

## Provider gateway invariants (all providers)

- One application-lifespan `httpx.AsyncClient`, DI'd — never per-request.
- Circuit breaker distinguishes network / rate-limit / auth / client / server /
  schema failures; honors `Retry-After`; half-open recovery; shared across workers.
- Provider status taxonomy: disabled ≠ unconfigured ≠ configured ≠ healthy ≠
  degraded ≠ rate-limited ≠ schema-invalid ≠ unavailable ≠ circuit-open.
  HEALTHY only after a successful probe.
- Standard redacted envelope: trust tier, status, quota, warnings, snapshot hash,
  acquired_at, correlation_id.

---

# OBSERVABILITY RULE

If any system-level change is made:

- Evaluate telemetry impact — does this require new spans or metrics?
- Validate performance implications — does this add latency to the hot path?
- Ensure no silent regressions — what breaks without a visible signal?
- Real-time connections: WebSocket/SSE connection counts must be bounded and metered
- Agent invocations: SwarmX LLM calls must emit token-usage metrics per agent role

---

# VERIFIED COMPONENT STATE (2026-07-06 — override all prior docs)

## Routing implications from verified ground truth

| Verified fact | NEXUS routing implication |
|---|---|
| SPECULATIVE → watchlist fixed in BOTH engines | Betting engine tasks: load `sabiscore-betting-engine-auditor` → always confirms both files |
| Provider gateway lifespan implemented | Provider tasks: use `Depends(get_provider_registry)` in endpoint — never call `build_provider_registry()` directly from endpoints |
| TF.js browser model deleted | Frontend tasks: never re-add any `ml/` browser inference; route model calls to backend |
| The Odds API: per-bookmaker normalization added | Market refresh tasks: `OddsMarketRecord` is the canonical shape; per-bookmaker, never combined |
| Reconciliation REQUIRES_REVIEW added | Fixture identity tasks: handle 4 statuses (VERIFIED/REQUIRES_REVIEW/CONFLICTING/UNKNOWN) |
| api_football is fully operational (injuries/lineups/teams/team_statistics); fdo + sportmonks are code-operational but unverified against live keys | Evidence orchestration tasks: PREMATCH_ENRICHED resolves team_id via `teams()` + `reconcile_team()` before calling `team_statistics()`; non-VERIFIED resolution and fdo/sportmonks's pending live verification still surface as PARTIAL/advisory, not a code stub |
| critical_gaps PARTIAL gate: resolved | Both engines already gate `PARTIAL` on `critical_gaps` (CONFLICTING entries excluded) plus an explicit CONFLICTING-freshness check, tested in both `test_betting_intelligence_engine.py` and `test_core_engine.py`. No patch file exists or is needed — do not re-flag this as open. |
| CORS middleware wires `allow_origin_regex` (vΩ.20, 2026-07-24) | Backend CORS tasks: `setup_middleware` (`api/middleware.py`) now passes both `allow_origins=settings.cors_origins` AND `allow_origin_regex=settings.cors_origin_regex or None`. When editing origins, update BOTH the static `CORS_ORIGINS` list and the `CORS_ORIGIN_REGEX` in `render.yaml` — the regex covers Vercel preview URLs, the static list covers `sabiscore.com` + the canonical `web-lac-theta-42.vercel.app` alias. |
| Production is `web` project only (vΩ.20, 2026-07-24) | Deploy/release-ops tasks: the sole live Vercel project is `web` (alias `https://web-lac-theta-42.vercel.app`); legacy `sabiscore` + `sabiscore-web` projects were deleted. Backend is `https://sabiscore-api-bav1.onrender.com`. `/api/health` carries a `sha` field — probe it to catch stale deployments before "fixing" already-shipped code. Keepalive is the pre-existing `.github/workflows/keep_alive.yml` (14-min), not the daily Vercel cron. |
| ⚠️ GitHub Actions billing-locked (vΩ.20, 2026-07-24) | Release/CI tasks: ALL GitHub Actions runs fail-to-start on an account billing lock (*"account is locked due to a billing issue"*) — CI, secret-scan, and keepalive are dark. Do NOT trust green-CI assumptions; recommend local `make verify` as the gate and surface the billing lock as the top blocker until it clears. |
| Phase-7 insights fail closed with HTTP 422 (vΩ.23, 2026-07-27) | Evidence/betting-engine tasks: `POST /api/v1/insights` returns **422 `INSUFFICIENT_EVIDENCE`** whenever `FeatureTransformer` cannot satisfy required evidence — the normal state during the off-season break. It previously returned 200 with fabricated probabilities and a 35%-of-bankroll Kelly stake. Do NOT "fix" the 422 by restoring a fallback; `insights/engine.py` must re-raise `DataUnavailableError` at all three former swallow sites. `value_analysis.bets[].kelly_stake` is a **fraction** capped by `LeaguePolicy.kelly_cap`, never a currency amount. |
| Zero-fab has a display half (vΩ.24, 2026-07-27) | Intelligence-UI tasks: the backend emits neutral placeholders (`elo_context` 1500/1500, a placeholder `credible_interval`) that are NOT measurements. Any new stat tile on the match dashboard must be gated on `presentation.isReducedEvidenceBaseline` / `predictionAvailable` and render `—` otherwise. Route these tasks to `frontend-product-design-architect` + `component-quality-gate`, and treat "does the backend have a default for this field?" as a required check — `fmt()` will render a placeholder as data without complaint. |
| ⚠️⚠️ The league-vocabulary trap has now fired at THREE boundaries (2026-08-12) | Escalates the vΩ.26 row below — treat this as a **checklist item, not a caution**. `apps/web/src/app/api/upcoming/route.ts` was written *after* the vΩ.26 fix and still shipped a bare `.toUpperCase()` + `Set.has()` check, so La Liga / Serie A / Ligue 1 filters silently returned every league for weeks (`"La Liga".toUpperCase()` is `"LA LIGA"` — space, not underscore). **Routing rule: any task that adds or edits a league-parameterized route, proxy, link, or query MUST (a) call `canonicalLeagueId()` from `apps/web/src/lib/league.ts` — never a raw string comparison, never a local allowlist Set — and (b) include a test case for at least one multi-word league.** Surface both in the Risk line. EPL passes under every broken implementation, so an EPL-only test proves nothing. Load `api-contract-governance-architect` + `testing-strategy-architect` alongside the frontend skills. **As of 2026-08-12 this is machine-enforced by `apps/web/src/lib/league-contract.test.ts`** (repo-wide scan of `app/api/**/route.ts`). If that test fails on your change, the route is wrong — normalize it; do **not** relax the assertion to accommodate a new pattern. Five occurrences of this class shipped before the guard existed. |
| Prediction identity must be real or refused, never minted (2026-08-12) | Any task touching `create_prediction()` / `MatchPredictionLog` / the settlement join: the endpoint now returns HTTP 422 `FIXTURE_IDENTITY_REQUIRED` when `match_id` is absent, instead of synthesizing `f"{home}_{away}_{timestamp}"`. Do **not** "improve" this by back-resolving the fixture from team names + kickoff — that is a second identity heuristic competing with the canonical `reconcile_team()` path, and the same class of duplicate-source-of-truth defect as the two league vocabularies. `get_settled_predictions()` joins `MatchPredictionLog.match_id` to `Match.id`; anything that cannot equal a real `Match.id` corrupts `settled_join_rate` invisibly. Route settlement-adjacent work to `sabiscore-settlement-calibration-architect`. |
| ⚠️ Two league vocabularies — normalize at every boundary (vΩ.26, 2026-07-27) | Any task touching a league-parameterized route, link, or proxy: `apps/web` speaks **display form** (`"La Liga"` — keys `team-data.ts`, `logo-resolver.ts`, `league-colors.ts`) *and* **canonical form** (`LA_LIGA` — sidebar, proxy Zod schemas, `betting-intelligence-api.ts`). Route through `frontend-product-design-architect` + `api-contract-governance-architect`, and surface in the Risk line: **normalize with `canonicalLeagueId()` (`apps/web/src/lib/league.ts`), never compare raw league strings, and never validate a league fix with EPL alone** — EPL is spelled identically in both vocabularies and masked a 400 on every other league through multiple sessions. The helper mirrors `backend/src/core/league_policy.py` `canonical_league_id` rule-for-rule; keep the two in sync if either changes. |
| Loading↔results container parity (vΩ.25, extended vΩ.31 2026-07-30) | Frontend/motion tasks touching `match-loading-experience.tsx`: this layout has now regressed **four** times. The interstitial container, its SSR skeleton, and the `match-selector.tsx` overlay wrapper must all stay at `max-w-6xl` to match `app/match/[id]/page.tsx`. **vΩ.31 adds a fourth variable: the component must add NO padding of its own** — the root `<main>` (`app/layout.tsx:203`) already applies `px-4 py-5 sm:px-6 lg:px-8` and the results page adds none, so a `p-4` here inset loading content 16px per side and snapped it wider on load. The `match-selector.tsx` overlay is the sole usage site with no `<main>` ancestor and therefore carries its own `py-4`. Surface in the Risk line: **check what the parent already supplies before adding padding.** Pinned by `match-loading-experience.test.tsx` — if that test fails, restore parity, do not relax the assertion. |
| Fabricated claims travel in pairs (vΩ.31, 2026-07-30) | Zero-fabrication-display tasks: a corrected claim is not necessarily the only copy of it. vΩ.23 fixed the providers pill's unreachable "live" count but left an identical hardcoded "Live Data · 5 Providers Configured" string in `match-selector.tsx`, contradicting the header on the same page for two further releases. Likewise `EnsembleCard` asserted "baseline values are not displayed" beside a line describing that value's shape. Route to `component-quality-gate` + `frontend-product-design-architect` and **grep the whole of `apps/web/src` for the claim's wording after fixing any one instance** — the provider/readiness numbers now have exactly one source of truth each (`derivePlatformHealth` on `PLATFORM_HEALTH_QUERY_KEY`). |
| Match-page recovery is `router.refresh()` (vΩ.25, 2026-07-27) | Release/UX tasks: never reintroduce `window.location.reload()` in `insights-error-state.tsx`. `page.tsx` mounts `FullAnalysisSection` + `Phase8AnalyticsSection` as independent siblings that render fine when the Phase-7 fetch fails, so a document reload destroys working analysis. Use `useTransition` + `router.refresh()`; `insufficient_evidence` offers no retry at all. |
| ⚠️ Shipped ≠ deployed — verify with a live probe (vΩ.33, 2026-08-04) | Release/incident-ops and any "is this bug still live" task: a complete, tested, committed fix is **not** evidence of production behaviour. The entire WP-0/1/1.0/2/3.1 identity campaign sat on local `master` with `origin/master` four commits behind, so every live probe still reproduced the original defect. Before diagnosing a reported bug as unfixed, run `git rev-list --left-right --count origin/master...master` **and** compare deployed SHAs (`/api/health` `sha` on Vercel, `/health/ready` `checks.migrations.head` on Render) against local HEAD. Route to `release-incident-operations-architect` + `git-workflow-architect`. |
| ⚠️ A broad `except` can misattribute a crash to the wrong subsystem (vΩ.33, 2026-08-04) | Debugging/evidence tasks: `get_full_analysis()` wraps its whole projection dispatch in one `try/except Exception` → `_default_live_vector()`, which reports `fixture_identity_verified: False`. Any downstream failure (Elo, StatsBomb, Phase 8) therefore surfaces as `FIXTURE_IDENTITY_UNVERIFIED` — an identity gap that has nothing to do with identity. vΩ.33's real cause was a tz-aware `match_date` default raising `TypeError` inside `EloEngine._get_pre_and_trend()`. **Before trusting a critical-gap label, check whether the fallback vector produced it**: the fingerprint is *all* canonical features gapped + `staleness_available: false`. Surface in the Risk line for any task touching `full_analysis.py` or `upcoming_match_feature_service.py`. |
| ⚠️ Naive-vs-aware datetime is a recurring asyncpg/pandas trap (vΩ.13, extended vΩ.33) | Any task passing a `match_date` or querying `Match.match_date`: the column is naive `TIMESTAMP WITHOUT TIME ZONE`, the Elo/StatsBomb parquet tables persist naive timestamps, and `datetime.now(timezone.utc)` is aware. Mixing them raises at asyncpg bind time *or* inside pandas comparison. Convention repo-wide is `.replace(tzinfo=None)` at the boundary — `upcoming_match_feature_service.py:124`, `matches.py:123`, `fixtures.py:428`, `repositories/fixtures.py` `get_next_upcoming_fixture`. New query helpers and default arguments must follow it. |
| Season-start dates have ONE source of truth (vΩ.33, 2026-08-04) | Any task touching off-season copy, `next_season_start`, or league calendars: `backend/src/core/season_calendar.py` is authoritative and provider-verified against football-data.org `currentSeason.startDate`. `upcoming_matches.py`, `leagues.py`, and `offseason.py` all import from it — do **not** reintroduce a local table. Three copies had drifted up to 14 days early (EPL promised 08-08 against a real 08-21), telling users fixtures would appear on a date the provider had none. UCL is an explicit annotated estimate until the provider publishes 2026/27. Route to `frontend-product-design-architect` + `component-quality-gate` for the display half and treat any user-visible date as a zero-fabrication surface. |
| Simultaneous 503s on `/api/upcoming`/`/api/value-bet-scan`/`/api/models/status` (2026-08-11) | Debugging tasks: these three Next.js proxy routes fail closed with `retryable: true` whenever the upstream fetch errors, including the ~2–3 minute window a single-instance Render redeploy is unreachable. Before diagnosing this as a code regression, correlate the browser error timestamp against the Render deploy log — if it falls inside a deploy's start/complete window, this is expected behavior, not a bug. None of the three routes are gated on `/health/ready`, so the separate, already-tracked Redis/cache limitation (`docs/DEBT.md` item 15) does not by itself explain them. |
| Readiness ≠ capability (vΩ.33, 2026-08-04) | Observability/health tasks: `/health/ready` carries a `capability` object beside `checks`. `checks` is component liveness only; `capability` is the end-to-end prediction probe (`verified` / `unverified_no_fixtures` / `failed`, 15-min cached, runs `get_full_analysis()` on the next required-league fixture). It is deliberately **excluded** from `status`/503 and from the `ReadinessRing` ready/total ratio. Never "simplify" by folding capability into the ratio or by gating routing on it — a single dyno's model hiccup must not take the service out of rotation, and `unverified_no_fixtures` must never render as an outage. |

## ProviderStatus enum — actual values (use in all code, not documented preferences)

```python
# backend/src/providers/base.py — actual ProviderStatus enum values
ProviderStatus.VERIFIED              # healthy probe succeeded
ProviderStatus.CONFIGURED_UNVERIFIED # enabled + key present, not yet probed
ProviderStatus.UNCONFIGURED          # key required but absent
ProviderStatus.PARTIAL               # ← what docs call DEGRADED
ProviderStatus.UNAVAILABLE           # network error, disabled (+ provider_disabled warning)
ProviderStatus.RATE_LIMITED          # 429 received
ProviderStatus.CIRCUIT_OPEN          # breaker tripped
ProviderStatus.INVALID               # ← what docs call SCHEMA_INVALID
ProviderStatus.CONFLICTING           # provider-level conflict state
# DISABLED does not exist as an enum value
```
