---
name: elite-skill-forge
description: >
  Generates elite, production-ready Claude skills (SKILL.md files) from a domain, workflow, or intent description.
  Use this skill whenever a user wants to create a new Claude skill, capture a workflow as a reusable skill, turn a
  complex prompt into a skill, generate a suite of skills for a domain, or asks phrases like "make a skill for X",
  "turn this into a skill", "create a Claude skill that does Y", "I need a skill to automate Z", or "generate skills
  for my team". Also triggers when a user describes a repeatable Claude workflow they want to package and reuse.
  Always use this skill — don't improvise skill generation without it.
---

# Elite Skill Forge

Transform any domain, workflow, or intent into fully-formed, production-ready Claude skills —
each a self-contained SKILL.md file that Claude can load and execute immediately.

## What a Skill Is

A Claude skill is a SKILL.md file (with optional bundled resources) that gives Claude deep,
specialized instructions for a specific task domain:

```
skill-name/
├── SKILL.md          ← required: frontmatter + instructions
└── references/       ← optional: docs, templates, schemas
```

**SKILL.md structure:**
```markdown
---
name: skill-identifier
description: >
  When to trigger (specific phrases, contexts). What it does.
  Be explicit and a little "pushy" — Claude undertriggers skills,
  so the description should push toward use.
---

# Skill Title

[Instructions for Claude when this skill is active]
```

---

## Skill Generation Protocol

### Step 1 — Capture Intent

**If the user pasted an existing prompt or document**, run the Ingestion Protocol first (see below).

Otherwise, clarify only what isn't already clear:
1. **What domain or workflow?** What should the skill enable Claude to do?
2. **Single skill or a suite?** One focused skill, or a family of related skills?
3. **Output format?** What does success look like (files, prompts, configs, analyses)?

Default to generating immediately if intent is inferable. Ask at most one clarifying question — never a list. If the request is genuinely ambiguous (no domain, no workflow, no example), ask: *"What's the one thing this skill should reliably do?"*

### Ingestion Protocol (for pasted prompts / existing documents)

When the user shares an existing system prompt, persona, or complex document:

1. **Extract the discrete workflows**: What repeatable tasks does this prompt perform?
2. **Identify the primary job**: Which workflow is most load-bearing / most frequently triggered?
3. **Detect scope creep**: Multi-role mega-prompts should be decomposed into focused skills — one per distinct job. Flag this to the user.
4. **Confirm before generating**: Present your decomposition unless the user already said "all of it."
5. **Preserve signal, discard noise**: Extract concrete instructions, protocols, and output formats. Strip identity declarations, motivational framing, and redundant persona language.

### Step 2 — Generate Skills

For each skill, produce:

#### A. Frontmatter (trigger-optimized)
- `name`: lowercase-hyphenated, memorable, specific
- `description`: covers *when* to use AND *what* it does. Include example trigger phrases.
  Err toward being explicit and slightly pushy to avoid undertriggering.

#### B. Skill Body
Structure the body with:
- **Role declaration**: What Claude does when this skill is active (behaviors, not identity)
- **Core protocol**: Step-by-step instructions for the primary workflow
- **Output format**: Exact structure Claude should produce
- **Quality gates**: Concrete, checkable criteria for what "done well" means
- **Edge case handling**: What to do when inputs are ambiguous or incomplete

#### C. Activation Triggers (required section)
List 8–12 example phrases that should invoke this skill. Be specific.

### Step 3 — Output Format

Present each skill as a complete, copyable SKILL.md block. If generating a suite, present them in priority order (most broadly useful first). After each skill, provide:
- **One-line purpose**: What it does in plain language
- **Best paired with**: Other skills it works well alongside

---

## Quality Standards

Every skill must be:
- **Self-contained**: No dependencies on context outside the skill body
- **Immediately usable**: Copy-paste ready, no placeholders left unfilled
- **Precisely scoped**: Does one thing excellently, not many things adequately
- **Trigger-optimized**: Description written so Claude uses it when it should
- **Format-aware**: Output format is explicit, not left to interpretation
- **Code-grounded**: If the skill generates code, it must include at least one concrete example

---

## Generating a Suite (3+ Skills)

When generating a domain skill suite:
1. Map the domain into discrete, non-overlapping workflows
2. One skill per workflow — never combine two distinct jobs
3. Define how skills chain (output of skill A feeds skill B)
4. Present a **Skill Map** showing the relationships and execution order

---

## Skill Body Principles

- **Concrete over abstract**: Specific formats, code examples, and criteria over vague guidance
- **Positive instructions**: "Respond only in JSON" beats "don't use markdown"
- **Progressive disclosure**: Front-load the most important instructions; edge cases at the end
- **Fail gracefully**: Always specify what to do when the request is ambiguous
- **Persona-free**: Skills are instruction sets, not identity declarations. Remove "you are a world-class X" framing; replace with behavioral protocols.
- **Decomposed from mega-prompts**: Multi-role source prompts become multiple focused skills

---

## Quality Gates

Every generated skill must pass before delivery:
- [ ] `name` is lowercase-hyphenated, specific, and memorable
- [ ] `description` covers both *when* to trigger AND *what* it produces — minimum 5 trigger phrases
- [ ] Body has: behavioral role, core protocol, explicit output format, quality gates, activation triggers
- [ ] No vague phrases like "handle appropriately" — every instruction is concrete
- [ ] Code-generating skills include at least one working code example
- [ ] Ingested mega-prompts are decomposed into ≥ 2 focused skills before output
- [ ] Each skill ends with `## Activation Triggers` with 8+ phrases minimum

---

## The 39-Skill Suite Map

After generating a new skill, suggest the most relevant existing skills to pair it with from the 39-skill suite. Clusters:

| Cluster | Skills |
|---|---|
| Editor & Environment | vscode-cognitive-os, vscode-ai-agent-stack, vscode-monorepo-forge, vscode-debug-profiler, typescript-config-surgeon, git-workflow-architect |
| Frontend Design | design-token-system-architect, frontend-product-design-architect, accessibility-system-architect, component-quality-gate, motion-performance-architect, motion-interaction-architect, data-visualization-architect |
| Backend Engineering | backend-domain-model-architect, effect-ts-layer-architect, prisma-database-architect, bullmq-job-architect, api-automation-architect, api-contract-governance-architect, backend-systems-auditor, opentelemetry-observability-architect, edge-cache-architecture-architect |
| Application Layer | nextjs-performance-architect, security-hardening-auditor, testing-strategy-architect, ai-feature-architect, prompt-engineering-architect, release-incident-operations-architect |
| Mobile & Meta | react-native-expo-architect, elite-skill-forge |
| Vertical Intelligence | nigerian-fintech-compliance-architect, multi-agent-orchestration-architect |
| Real-Time & Data | real-time-systems-architect, data-visualization-architect |

---

## Creative Combinations

**The "Bespoke Consultant" pattern**: Use `elite-skill-forge` to generate domain-specific skills for a product vertical, then chain with `backend-domain-model-architect` to embed domain language and invariants. Result: a skill that generates code AND enforces business rules.

**The "Living Documentation" pattern**: Generate a `docs-architect` skill with `elite-skill-forge`, pair with `git-workflow-architect` to auto-run docs generation on every commit, and `opentelemetry-observability-architect` to trace which docs are read. Documentation that stays alive.

**The "Vertical Sovereignty" pattern**: For TaxBridge / SabiScore / Hashablanca — generate one skill per product vertical, each deeply scoped to that vertical's domain logic, regulatory context, and stack. Chain them with `backend-systems-auditor` as the shared production gate. Three products, one quality standard.

**The "SwarmX Agent Suite" pattern**: Use `elite-skill-forge` to generate one skill per SwarmX agent role (Strategist, Evaluator, Planner, Executor), then chain all through `multi-agent-orchestration-architect` for routing discipline. Each agent has a focused skill; NEXUS routes between them.

---

## Activation Triggers

- "Make a skill for [task / domain]"
- "Create a Claude skill that [does X]"
- "Turn this workflow / prompt into a skill"
- "I need a skill for my team that handles [task]"
- "Generate a suite of skills for [domain]"
- "Package this as a reusable skill"
- "What skills would help me automate [workflow]?"
- "Upgrade / refine this existing skill"
- "Generate a vertical-specific skill for TaxBridge / SabiScore"
- "Create a SwarmX agent skill"
- "Turn this system prompt into a skill file"
- "Decompose this mega-prompt into focused skills"
