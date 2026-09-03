---
name: teamwork
description: Decompose a large, multi-file engineering task and execute it with a coordinated team of Claude Code teammates (architect, implementer, qa-verifier, debugger) built on native Agent Teams — shared task list, direct teammate messaging, quality-gate hooks. Manual invocation only.
disable-model-invocation: true
argument-hint: "<task description>"
effort: high
---

# Teamwork — Multi-Agent Task Execution

You are the team lead for a native Claude Code Agent Team. This skill only
orchestrates; it does not implement anything itself.

## 0. Ground truth first

- Agent Teams flag: !`echo "${CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS:-unset}"`
- Working tree state: !`git status --short 2>/dev/null || echo "not a git repo"`
- Diff shape: !`git diff --stat 2>/dev/null | tail -5`

If the flag above printed anything other than `1`, stop and tell the user to set
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in `.claude/settings.json` and restart the
session. Do not silently degrade to ordinary subagents and call it a team — that
changes the coordination model entirely (no shared task-list visibility across
workers, no direct worker-to-worker messaging), and reporting success anyway would
misrepresent what actually ran.

## 1. Decompose

Task: $ARGUMENTS

Break it into 2–5 independent workstreams, each owning a disjoint set of files or
directories. If the task can't be partitioned without file overlap, don't force a
team — say so plainly and offer to do it as a single session instead. Read
[verification-protocol.md](verification-protocol.md) now; it defines the done-criteria
you hold every teammate to.

## 2. Spawn order

1. Spawn one teammate named `architect`, using the `architect` agent type, with the
   full task description and the git state above. Wait for its plan before spawning
   anyone else.
2. On plan approval, spawn one `implementer` teammate per workstream (name each
   `impl-<workstream>`) plus one `qa-verifier` teammate. Give every teammate: the
   specific files it owns, the interface contract and acceptance criteria from the
   architect's plan, and an explicit instruction not to touch files outside its
   partition.
3. Keep `debugger` unspawned. Spawn it only when `qa-verifier` reports a failure it
   can't attribute to a single implementer's own diff — cross-cutting breakage,
   environment/config issues, or a fix that already failed once.

## 3. Coordinate, don't implement

- Let teammates self-claim tasks from the shared list once the architect's plan is
  broken into tasks.
- Don't start implementing yourself while teammates are working — a documented
  failure mode is the lead jumping in instead of waiting.
- Answer teammate permission prompts and questions as they surface; they route to
  you.
- If a teammate goes idle with unclaimed dependent tasks still pending, verify it
  actually finished before nudging it.

## 4. Synthesize

When the shared task list is empty and every teammate has reported, produce one
summary: what changed, by whom, what `qa-verifier` confirmed, and any follow-up
you're deferring. Shut down teammates by name once you have their final report —
don't leave them running.

## Activation

Manual only: `/teamwork <task description>`. Not auto-triggered — see
`disable-model-invocation` in the frontmatter and the cost note in `SETUP.md`.
