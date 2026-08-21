# AI Engineering Control System — GitHub Copilot
# SabiScore · TaxBridge · Hashablanca · SwarmX (Polyglot Monorepo)

> **Mandatory workflow for all code tasks:**
> Invoke `/nexus` (or attach `#file:.github/prompts/nexus.prompt.md`) BEFORE any
> implementation begins. NEXUS classifies intent, selects the minimum skill graph,
> and opens every code response with a Skill Trace Block.

---

## SKILL SYSTEM

Skills live in `.ai/skills/` — a 39-skill domain suite. Load skills by attaching
them to your Copilot Chat message:

```
#file:.ai/skills/<skill-name>/SKILL.md
```

Never blind-load the full suite. NEXUS selects only what the task requires.

### Full Skill Registry

| Cluster | Skills |
|---|---|
| **1 · Editor & Env** | `vscode-cognitive-os` · `vscode-ai-agent-stack` · `vscode-monorepo-forge` · `vscode-debug-profiler` · `typescript-config-surgeon` · `git-workflow-architect` |
| **2 · Frontend Design** | `design-token-system-architect` · `frontend-product-design-architect` · `accessibility-system-architect` · `component-quality-gate` · `motion-performance-architect` · `motion-interaction-architect` · `data-visualization-architect` |
| **3 · Backend Engineering** | `backend-domain-model-architect` · `effect-ts-layer-architect` · `prisma-database-architect` · `bullmq-job-architect` · `api-automation-architect` · `api-contract-governance-architect` · `backend-systems-auditor` · `opentelemetry-observability-architect` · `edge-cache-architecture-architect` |
| **4 · Application Layer** | `nextjs-performance-architect` · `security-hardening-auditor` · `testing-strategy-architect` · `ai-feature-architect` · `prompt-engineering-architect` · `release-incident-operations-architect` |
| **5 · Mobile & Meta** | `react-native-expo-architect` · `elite-skill-forge` |
| **6 · Vertical Intelligence** | `nigerian-fintech-compliance-architect` · `multi-agent-orchestration-architect` |
| **7 · Real-Time & Data** | `real-time-systems-architect` · `data-visualization-architect` |
| **SabiScore Domain** | `sabiscore-betting-engine-auditor` · `sabiscore-provider-adapter-architect` |

### Motion Skill Disambiguation

| Skill | Role |
|---|---|
| `motion-performance-architect` | **Strategy** — motion budget, compositor rules, anti-patterns (load FIRST) |
| `motion-interaction-architect` | **Implementation** — Framer Motion APIs, animation catalog |

Always load `motion-performance-architect` before `motion-interaction-architect`.

---

## MANDATORY ENTRY POINT

All tasks MUST begin with NEXUS. Invoke it one of three ways:

```
1. Type `/nexus` in Copilot Chat (prompt file must be in .github/prompts/)
2. Attach #file:.github/prompts/nexus.prompt.md to your request
3. Start your message with: "Run NEXUS on: <task description>"
```

NEXUS is responsible for: task intent classification · skill selection from the
39-skill registry · dependency graph resolution · execution ordering ·
conflict resolution.

No other skill may be invoked before NEXUS has run.

**Skill Trace Block — required on every code response:**

```
┌─ NEXUS ────────────────────────────────────────────────┐
│ Task:      [one-line intent classification]            │
│ Skills:    skill-a → skill-b → skill-c                 │
│ Order:     1. skill-a  2. skill-b  3. skill-c          │
│ Overrides: [conflict resolutions applied, or NONE]     │
│ Risk:      [critical risks identified, or NONE]        │
└────────────────────────────────────────────────────────┘
```

---

## PROJECT STACK (IMMUTABLE CONSTANTS)

This is a polyglot monorepo. Product verticals use different stacks — never conflate them.

| Layer | SabiScore | TaxBridge · Hashablanca · SwarmX |
|---|---|---|
| Backend | **Python 3.11 production (FastAPI 0.104.1); Python 3.14 local compatibility (FastAPI 0.115.x)** | Fastify 5, Effect-TS |
| ORM / Migrations | **SQLAlchemy 2, Alembic** | Prisma 5 |
| Async HTTP | **httpx.AsyncClient** | Native fetch / undici |
| Job Queue | Redis (direct) + optional BullMQ bridge | BullMQ, ioredis |
| DB | **PostgreSQL 16+** | PostgreSQL 16+ |
| Cache | **Redis 7+** | Redis 7+ |
| Frontend | **Next.js 15, React 18, Tailwind v4** | Next.js 15, React 19 |
| Mobile | — | Expo SDK 54, Reanimated v4, EAS |
| Monorepo | **Turborepo, pnpm workspaces** | Turborepo, pnpm workspaces |
| Auth | Next.js middleware + JWT (HS256, server-only) | Auth.js v5 |
| Observability | **structlog, OpenTelemetry** | OTel, OTLP |
| AI / Agents | **Vercel AI SDK v6, Ollama (local), SwarmX** | SwarmX |

---

## SABISCORE CANONICAL PRODUCTION SHAPE

These three entrypoints are the ONLY production-authorised services.
Never reference `apps/api/` or `frontend/` in production scripts, CI, or runbooks.

```
backend/src/api/main.py   ← FastAPI: providers, evidence, analysis, verdicts, EV, Kelly
apps/web                  ← Next.js: public frontend and backend proxy routes ONLY
apps/scraper              ← Permitted batch acquisition, raw snapshots, manifests
```

### Backend Authority (FastAPI is the ONLY source of truth for)
- Provider credentials and authenticated provider requests
- Fixture identity and reconciliation
- Evidence criticality and gap classification
- Feature construction and model inference
- Calibration, uncertainty, and market de-vigging
- Edge, expected value, Kelly stake sizing
- Verdict generation and decision persistence

### Frontend Constraints (Next.js `apps/web` MUST NOT)
- Call provider hosts directly — all traffic proxied via `SABISCORE_BACKEND_URL`
- Import TensorFlow.js or execute models in the browser
- Receive or expose provider API secrets
- Calculate verdicts, stake sizes, or EV independently
- Use `NEXT_PUBLIC_*` prefixes on any provider key variable

### Scraper Constraints (`apps/scraper` MUST NOT)
- Calculate probabilities, verdicts, EV, Kelly stakes, or user-facing recommendations
- Call authenticated provider APIs (scraper is open/batch-only)

---

## CONDENSED NEXUS ROUTING TABLE

Use `/nexus` for the full dependency graph. This table guides fast classification:

| Intent Signals | Primary Skill Graph |
|---|---|
| "add X", "build Y", "implement Z" | `ai-feature-architect` → `testing-strategy-architect` |
| "slow", "memory leak", "profile", "why is this crashing" | `vscode-debug-profiler` → `opentelemetry-observability-architect` |
| "bundle size", "LCP", "Core Web Vitals", "RSC", "PPR" | `nextjs-performance-architect` → `component-quality-gate` |
| "CSP", "auth", "OWASP", "rate limit", "XSS", "CORS" | `security-hardening-auditor` → `backend-systems-auditor` |
| "model this", "design the system", "bounded context" | `backend-domain-model-architect` → `backend-systems-auditor` |
| "FastAPI", "FastAPI", "Alembic", "SQLAlchemy" | `backend-domain-model-architect` → `backend-systems-auditor` |
| "Fastify", "Prisma", "BullMQ", "Effect-TS", "worker" | `backend-domain-model-architect` → `effect-ts-layer-architect` → `prisma-database-architect` |
| "component", "design", "accessibility", "animation" | `frontend-product-design-architect` → `accessibility-system-architect` |
| "page transitions", "micro-interactions", "Framer Motion" | `motion-performance-architect` → `motion-interaction-architect` |
| "edge runtime", "cache tags", "revalidate", "CDN" | `edge-cache-architecture-architect` |
| "OpenAPI", "schema", "webhook", "idempotency" | `api-contract-governance-architect` |
| "streaming", "RAG", "tool calling", "LLM", "embeddings" | `prompt-engineering-architect` → `ai-feature-architect` |
| "SwarmX", "agent", "orchestrator", "LLM routing" | `multi-agent-orchestration-architect` |
| "WebSocket", "SSE", "live updates", "presence" | `real-time-systems-architect` |
| "chart", "graph", "recharts", "D3" | `data-visualization-architect` |
| "TaxBridge", "FIRS", "VAT", "CIT", "NRS 2026" | `nigerian-fintech-compliance-architect` |
| **"verdict", "HIGH_CONVICTION", "Kelly", "SPECULATIVE", "watchlist"** | **`sabiscore-betting-engine-auditor` (BOTH engines)** |
| **"ESPN", "provider health", "circuit breaker", "scoreboard"** | **`backend-systems-auditor` + `api-automation-architect`** |
| **"evidence profile", "DISCOVERY", "critical gap", "PARTIAL"** | **`backend-domain-model-architect` + `api-automation-architect`** |
| "Expo", "React Native", "EAS", "Reanimated" | `react-native-expo-architect` |
| "test", "Vitest", "Playwright", "MSW", "coverage" | `testing-strategy-architect` |
| "OTel", "trace", "span", "metrics", "Grafana" | `opentelemetry-observability-architect` |
| "rollback", "feature flag", "canary", "incident" | `release-incident-operations-architect` |
| "make a skill", "generate a skill" | `elite-skill-forge` ONLY — stop, do not route elsewhere |

### Conflict Resolution Priority
`Security` > `Correctness` > `Performance` > `Architecture` > `AI` > `UX/Motion` > `Release` > `Vertical`

---

## SABISCORE INTENT TYPES (for NEXUS classification)

| Intent | Key Signals |
|---|---|
| **Provider Gateway** | "provider health", "ESPN adapter", "ESPN standings", "ESPN slug", "scoreboard", "API-Football", "Sportmonks", "football-data.org", "The Odds API", "circuit breaker", "egress allowlist" |
| **Evidence Orchestration** | "evidence profile", "DISCOVERY", "PREMATCH_STANDARD", "PREMATCH_ENRICHED", "LINEUP_REFRESH", "MARKET_REFRESH", "evidence criticality", "critical gap", "advisory gap" |
| **Fixture Identity** | "canonical fixture", "fixture reconciliation", "fixture identity", "team alias", "VERIFIED/UNKNOWN/CONFLICTING/REQUIRES_REVIEW" |
| **Betting Engine** | "verdict", "HIGH_CONVICTION", "ACTIONABLE", "SPECULATIVE", "HOLD", "PARTIAL", "NO_BET", "Kelly sizing", "edge", "expected value", "de-vig", "overround" |
| **Intelligence UI** | "/intelligence page", "decision card", "evidence rail", "evidence passport", "odds snapshot", "model-vs-market" |
| **ML / Model** | "model artifact", "calibration", "feature registry", "prediction pipeline", "shadow mode", "xG features", "pi-ratings", "Dixon-Coles", "SHAP" |

---

## NON-NEGOTIABLE CONSTRAINTS

### Universal
- No unnecessary rewrites — optimize incrementally unless the system is broken
- Preserve architecture unless an explicit rewrite is requested
- Avoid overengineering — add complexity only when it earns its maintenance cost
- `apps/web` is pinned to **React 18.3.1** — do NOT bump to React 19 without an explicit planned upgrade
- `maxTsServerMemory` ≤ 3072 (half of 8 GB system RAM)
- Prefer RSC + streaming patterns over client-side data fetching

### SabiScore Backend (Python / FastAPI)
- **Alembic is the ONLY schema management authority** — NEVER call `Base.metadata.create_all()` at app startup or in migrations
- SQLite fallback requires explicit `ALLOW_SQLITE_FALLBACK=true` — never activate silently
- Provider gateway: single application-lifespan `httpx.AsyncClient`, DI'd — never per-request
- Circuit breaker must distinguish: network / rate-limit / auth / client / server / schema failures
- All provider requests are HTTPS-only; egress through an explicit allowlist
- `evaluation_at` is required by every verdict — never call `datetime.now()` inside pure betting logic
- UCL fixtures cannot reach `HIGH_CONVICTION` — hard cap at `ACTIONABLE`
- `SPECULATIVE` verdicts → `watchlist` ONLY — never `top_opportunities`
- Only `critical_gaps` force `PARTIAL` — advisory gaps reduce confidence only

### DUAL-ENGINE RULE (NON-NEGOTIABLE)
`betting_intelligence.py` and `core_engine.py` are independent implementations.
**Any change to verdict gates, Kelly, rankings, or watchlist MUST be applied to BOTH.**

```bash
# Verify after any engine change:
git diff --name-only | grep -E "betting_intelligence|core_engine"
# Must show BOTH files
```

### SabiScore Frontend (Next.js)
- All provider traffic proxied via `SABISCORE_BACKEND_URL` — zero direct provider calls
- CSP set per-request in `apps/web/src/middleware.ts` with `script-src` nonce + `'strict-dynamic'` — NEVER move to static `next.config.js`
- `Cache-Control: no-store` on all evidence and decision endpoints
- CSP must not contain `'unsafe-eval'` in production
- Validate all proxy parameters with Zod before forwarding to backend
- Prohibited UI terms: `lock` · `banker` · `guaranteed` · `sure bet` · `free money` · `execute immediately`

### TypeScript Verticals (TaxBridge / SwarmX)
- Effect-TS Layer discipline mandatory for all backend services
- BullMQ workers use separate `ioredis` connections per role (Queue / Worker / QueueEvents)
- Edge Runtime routes must NOT use Node.js-only modules (no `jsonwebtoken`)
- SwarmX agents are stateless between turns — no in-memory state persistence
- TaxBridge financial writes require idempotency keys at every database boundary

### Credential Safety (ABSOLUTE)
- Zero provider secrets in source control — Gitleaks runs in CI, no `|| true` suppressions
- Zero `NEXT_PUBLIC_*` provider key variables
- ESPN is keyless — NO `ESPN_API_KEY` variable exists or should be created
- Redact auth headers, API-key query params, DSNs, and passwords from all logs and traces

---

## SAFE DEFAULTS (PRODUCTION FAIL-CLOSED)

```env
DEBUG=false
MOCK_MODE=false
ENABLE_LEGACY_INFERENCE=false
SCRAPER_ALLOW_INSECURE_FALLBACK=false
ALLOW_SQLITE_FALLBACK=false
PROVIDER_LIVE_TESTS=false
USE_PHASE9_CANDIDATE_FEATURES=false
PHASE9_SHADOW_ONLY=true
```

---

## PROVIDERSTAT US — ACTUAL ENUM (always grep `base.py` before pattern-matching)

| Documented | Actual code value |
|---|---|
| `DISABLED` | Does not exist — disabled → `UNAVAILABLE` + `provider_disabled` warning |
| `DEGRADED` | `PARTIAL` |
| `SCHEMA_INVALID` | `INVALID` |
| All others | Match exactly |

---

## ESPN PROVIDER — OPERATIONAL KNOWLEDGE

- **Trust tier:** `UNOFFICIAL_PUBLIC` — **keyless** (no `ESPN_API_KEY`)
- **Evidence role:** lowest precedence — can NEVER alone establish critical odds, lineup, injury, or probability evidence. A missing ESPN response is at most `advisory_gap`, never `critical`.
- **Two egress hosts:** `site.api.espn.com` AND `sports.core.api.espn.com` (both must be allowlisted)
- **Standings gotcha:** soccer standings live at `…/apis/v2/sports/soccer/{slug}/standings` NOT at `/apis/site/v2/` (which returns only a stub `{"fullViewLink": {…}}`)
- **Exactly 7 competitions:** `eng.1 · esp.1 · ita.1 · ger.1 · fra.1 · ned.1 · uefa.champions` — fail closed on anything else (`UnsupportedCompetitionError`)
- **Timestamps:** `kickoff_utc` from `event.date`; `provider_timestamp = None` (never set to kickoff); freshness from `acquired_at`

---

## OBSERVABILITY RULE

For any system-level change, evaluate all three:
1. Does this require new spans or metrics?
2. Does this add latency to the hot path?
3. What breaks without a visible signal?

SabiScore-specific telemetry requirements:
- Provider health, latency, circuit state, quota — metered per provider
- Evidence freshness, critical gap rate, advisory gap rate — tracked per fixture
- Prediction latency, model artifact validity — tracked per inference
- Verdict distribution (time-series)
- Fixture reconciliation success/failure/REQUIRES_REVIEW rate

---

## RELEASE GATE (`make verify`)

All gates must pass. No bypass with `|| true`. No live provider quota in default CI.

```
secret scanner (Gitleaks)          web lint (no || true)
backend unit tests                 web type-check
backend integration tests          web unit/component tests
provider gateway tests             web production build
strict engine tests                Docker Compose validation
provider CLI doctor                Docker image build
Alembic upgrade + schema check     Playwright desktop smoke (/intelligence)
OpenAPI generation + diff          Playwright mobile smoke (/intelligence)
scraper tests + manifest validation
```

---

## KNOWN LEGACY SURFACES (DO NOT REFERENCE IN PRODUCTION)

| Path | Status |
|---|---|
| `apps/api/` | Legacy API skeleton — absent from CI, Docker, scripts |
| `frontend/` | Legacy Vite app — absent from CI, Docker, scripts |
| `npm lockfile` | Stale — `pnpm-lock.yaml` is canonical |
| `Base.metadata.create_all()` | Replace with Alembic migrations |
| Direct browser odds fetching | Route through backend proxy |
| `ESPN_API_KEY` variable | ESPN is keyless — remove entirely |

---

## COPILOT PROMPT COMMANDS

| Command | File | Purpose |
|---|---|---|
| `/nexus` | `.github/prompts/nexus.prompt.md` | Full NEXUS task orchestration — **run before every task** |
| `/audit` | `.github/prompts/audit.prompt.md` | Production readiness audit across all domain clusters |
| `/forge` | `.github/prompts/forge.prompt.md` | Generate a new SKILL.md via `elite-skill-forge` |

**Load skill files in chat:**
```
#file:.ai/skills/security-hardening-auditor/SKILL.md
#file:.ai/skills/backend-systems-auditor/SKILL.md
```

**Context-specific instruction files auto-apply by file type:**
- Python files (`*.py`) → `.github/instructions/python-sabiscore.instructions.md`
- TypeScript/React (`*.ts`, `*.tsx`) → `.github/instructions/typescript-nextjs.instructions.md`
- Test files → `.github/instructions/testing.instructions.md`
