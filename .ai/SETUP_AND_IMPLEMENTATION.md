# SCAR Skill Suite v2.0 — Setup & Implementation Guide
**34 Elite Production Skills | Claude.ai**

---

## Part 1 — Installation

### Method A: Individual Install (Recommended for selective adoption)

1. Open **Claude.ai** → Settings → **Skills**
2. Click **"Install from file"**
3. Drag in any `.skill` file
4. Repeat for each skill you want active

### Method B: Bulk Install

Install all 34 at once by dragging all `.skill` files into the Skills panel simultaneously.
Claude.ai accepts batch uploads.

### Verify Installation

After installing, open a new conversation and type:

```
What skills do you have active?
```

Claude will list all installed skills. Confirm you see the expected names.

---

## Part 2 — The 39-Skill Map

### Cluster 1 — Editor & Environment (install first)

| Skill | Install order | First trigger |
|---|---|---|
| `vscode-cognitive-os` | 1 | "Optimize my VS Code for Next.js + TypeScript" |
| `vscode-ai-agent-stack` | 2 | "Set up Claude Code and Copilot in VS Code" |
| `vscode-monorepo-forge` | 3 | "Generate a .code-workspace for my Turborepo" |
| `vscode-debug-profiler` | 4 | "Set up launch.json for Fastify debugging" |
| `typescript-config-surgeon` | 5 | "Generate tsconfig.json and ESLint flat config for Next.js 15" |
| `git-workflow-architect` | 6 | "Set up conventional commits and GitHub Actions CI" |

### Cluster 2 — Frontend Design (install second)

| Skill | Install order | First trigger |
|---|---|---|
| `design-token-system-architect` | 7 | "Design a token system for my fintech dashboard" |
| `frontend-product-design-architect` | 8 | "Shape the information architecture for my landing page" |
| `accessibility-system-architect` | 10 | "Make this flow keyboard and screen-reader friendly" |
| `component-quality-gate` | 11 | "Review this React component for production readiness" |
| `motion-performance-architect` | 12 | "Audit my animation performance and set the motion budget" |
| `motion-interaction-architect` | 13 | "Add page transitions and micro-interactions with Framer Motion" |
| `data-visualization-architect` | 14 | "Build a recharts dashboard for my analytics data" |

### Cluster 3 — Backend Engineering (install third)

| Skill | Install order | First trigger |
|---|---|---|
| `backend-domain-model-architect` | 15 | "Model this business workflow as a backend domain with Effect-TS" |
| `effect-ts-layer-architect` | 16 | "Model a database service with Effect-TS layers" |
| `prisma-database-architect` | 17 | "Design a Prisma schema for invoice management" |
| `bullmq-job-architect` | 18 | "Design a BullMQ queue for email dispatch" |
| `api-automation-architect` | 19 | "Make my Stripe integration resilient with retry and circuit breaker" |
| `api-contract-governance-architect` | 20 | "Define a contract-first API with OpenAPI" |
| `backend-systems-auditor` | 21 | "Audit my Fastify service for production readiness" |
| `opentelemetry-observability-architect` | 22 | "Add OpenTelemetry tracing to my Fastify + Prisma app" |
| `edge-cache-architecture-architect` | 23 | "Design the cache strategy for edge and PPR" |

### Cluster 4 — Application Layer (install fourth)

| Skill | Install order | First trigger |
|---|---|---|
| `nextjs-performance-architect` | 24 | "Audit my Next.js app for RSC and caching issues" |
| `security-hardening-auditor` | 25 | "Set up Auth.js v5 and security headers for Next.js" |
| `testing-strategy-architect` | 26 | "Set up Vitest, Testing Library, MSW, and Playwright" |
| `ai-feature-architect` | 27 | "Add streaming chat to my Next.js app with Vercel AI SDK v6" |
| `prompt-engineering-architect` | 28 | "Write a production system prompt for my invoice extraction feature" |
| `release-incident-operations-architect` | 29 | "Create a safe rollout plan with rollback and canary" |

### Cluster 5 — Mobile & Meta (install fifth)

| Skill | Install order | First trigger |
|---|---|---|
| `react-native-expo-architect` | 30 | "Set up Expo SDK 54 with New Architecture and Reanimated v4" |
| `elite-skill-forge` | 31 | "Generate a skill for my new product vertical" |

### Cluster 6 — Vertical Intelligence (install sixth)

| Skill | Install order | First trigger |
|---|---|---|
| `nigerian-fintech-compliance-architect` | 32 | "Implement FIRS e-invoicing and VAT computation for TaxBridge" |
| `multi-agent-orchestration-architect` | 33 | "Design the SwarmX agent routing and tool dispatch system" |

### Cluster 7 — Real-Time & Data (install seventh)

| Skill | Install order | First trigger |
|---|---|---|
| `real-time-systems-architect` | 34 | "Stream BullMQ job progress to my SwarmX dashboard via SSE" |

> **Note:** `data-visualization-architect` is included in Cluster 2 (install order 14) because it
> serves frontend design — charts are part of the UI system, not a separate concern.

---

## Part 3 — Motion Skill Disambiguation

Two motion skills exist with distinct, non-overlapping roles. Always use them in order:

| Order | Skill | Role |
|---|---|---|
| 1st | `motion-performance-architect` | **Strategy**: sets the motion budget, permitted properties, anti-patterns |
| 2nd | `motion-interaction-architect` | **Implementation**: Framer Motion APIs, token system, animation code |

When NEXUS selects motion skills, it always lists `motion-performance-architect` first.

---

## Part 4 — Skill Chain Recipes

These are the highest-leverage multi-skill sequences. Run them in order.

### Recipe 1 — "Zero to Elite Dev Machine" (Editor cluster)
```
1. vscode-cognitive-os        → "Optimize my VS Code for Next.js + TypeScript + Fastify"
2. vscode-ai-agent-stack      → "Set up Claude Code + Copilot hybrid"
3. vscode-monorepo-forge      → "Generate workspace config for my Turborepo"
4. typescript-config-surgeon   → "Generate strict tsconfig.json and ESLint flat config"
5. git-workflow-architect      → "Set up conventional commits and CI"
```
**Result**: A fully configured development environment from scratch in one session.

### Recipe 2 — "World-Class Frontend Experience" (Design cluster)
```
1. frontend-product-design-architect  → "Shape the information architecture for [screen]"
2. design-token-system-architect      → "Create the semantic token system"
3. accessibility-system-architect     → "Make the flow inclusive by design"
4. motion-performance-architect       → "Set the motion budget and compositor rules"
5. motion-interaction-architect       → "Implement the Framer Motion animation system"
6. data-visualization-architect       → "Design the chart and analytics layer"
7. component-quality-gate             → "Run the production readiness gate"
```
**Result**: A premium, accessible, motion-aware UI with data visualization that ships cleanly.

### Recipe 3 — "Production Backend" (Backend cluster)
```
1. backend-domain-model-architect            → "Model [service] as business domains with Effect-TS"
2. effect-ts-layer-architect                 → "Build the typed service boundaries"
3. prisma-database-architect                 → "Design the schema and migration strategy"
4. api-contract-governance-architect         → "Lock down the API contract"
5. bullmq-job-architect                      → "Add async processing with DLQ"
6. backend-systems-auditor                   → "Audit the full service"
7. opentelemetry-observability-architect     → "Instrument everything"
```
**Result**: A backend that is maintainable, observable, and safe to evolve.

### Recipe 4 — "TaxBridge Feature End-to-End" (Vertical + Full Stack)
```
1. nigerian-fintech-compliance-architect → "Model the VAT computation rules and FIRS constraints"
2. backend-domain-model-architect        → "Shape TaxComputation as a bounded context"
3. effect-ts-layer-architect             → "Build the tax computation service layer"
4. prisma-database-architect             → "Design the filing and audit trail schema"
5. security-hardening-auditor            → "NDPR compliance, BVN handling, FIRS auth"
6. frontend-product-design-architect     → "Design the VAT filing UX (₦ formatting, Pidgin)"
7. data-visualization-architect          → "Build the tax trend charts and compliance dashboard"
8. testing-strategy-architect            → "Write test cases for all 22 rate codes"
```
**Result**: A compliant, tested, well-designed TaxBridge feature from domain model to UI.

### Recipe 5 — "SwarmX Agent Pipeline" (Multi-Agent)
```
1. multi-agent-orchestration-architect → "Design the agent registry, routing, and BullMQ chains"
2. prompt-engineering-architect        → "Write system prompts for each agent role"
3. bullmq-job-architect                → "Design the agent job queue with DLQ and retry"
4. real-time-systems-architect         → "Stream agent progress to the SwarmX dashboard"
5. opentelemetry-observability-architect → "Instrument agent spans and token metrics"
6. security-hardening-auditor          → "Prompt injection defense, API key rotation"
7. backend-systems-auditor             → "Production readiness for the agent control plane"
```
**Result**: A production-grade multi-agent system that is observable, safe, and live-streamed.

### Recipe 6 — "SabiScore Live Dashboard" (Real-Time + Data)
```
1. frontend-product-design-architect  → "Design the analytics dashboard IA (analysts as primary persona)"
2. data-visualization-architect       → "Build match prediction charts and ML confidence displays"
3. real-time-systems-architect        → "Add live match event streaming via SSE"
4. design-token-system-architect      → "Define the SabiScore color system and chart tokens"
5. accessibility-system-architect     → "Add screen reader equivalents and table fallbacks for charts"
6. nextjs-performance-architect       → "Optimize RSC rendering for the live data dashboard"
```
**Result**: A live sports ML intelligence dashboard that is fast, accessible, and real-time.

### Recipe 7 — "Safe Ship" (Release cluster)
```
1. release-incident-operations-architect  → "Create the rollout / rollback plan"
2. testing-strategy-architect              → "Add confidence gates"
3. opentelemetry-observability-architect   → "Confirm release telemetry"
4. git-workflow-architect                  → "Wire CI/CD and promotion rules"
```
**Result**: Shipping becomes repeatable instead of risky.

---

## Part 5 — Why This Map Works

**Cluster 2 now has 8 skills** because frontend quality is genuinely multi-dimensional:
- Composition and hierarchy → `frontend-product-design-architect`
- Token system → `design-token-system-architect`
- Accessibility → `accessibility-system-architect`
- Motion strategy → `motion-performance-architect`
- Motion implementation → `motion-interaction-architect`
- Data display → `data-visualization-architect`
- Design critique → `frontend-product-design-architect`
- Component gate → `component-quality-gate`

**Cluster 6 (Vertical Intelligence)** captures product-specific knowledge that is too
domain-specific for general skills but too important to leave implicit:
- Nigerian tax law changes with every Finance Act — `nigerian-fintech-compliance-architect` tracks it
- SwarmX agent orchestration has unique concurrency, routing, and safety requirements

**Cluster 7 (Real-Time & Data)** separates concerns that cross clusters:
- Real-time data is not a backend skill or a frontend skill — it bridges both
- Data visualization belongs semantically to frontend design but is complex enough to need a dedicated skill

The suite stays modular so every task routes to the smallest useful graph. NEXUS resolves the
composition; skills execute their specific expertise.
