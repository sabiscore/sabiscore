# Verification Protocol

Held by `qa-verifier`, referenced by the lead. A workstream is done only when all of
the following hold. The lead does not mark the overall task complete until
`qa-verifier` has confirmed every item for every workstream.

1. **Build passes.** Run the project's actual build command — check
   `package.json`/`turbo.json` rather than assuming a command name. In a Turborepo
   monorepo this is almost certainly `turbo run build --filter=<package>`, not a
   bare `npm run build`.
2. **Existing tests still pass.** Run the suite scoped to the touched package(s),
   not the whole monorepo, unless the change touches a shared package.
3. **New behavior has a test.** If the workstream added or changed behavior,
   `qa-verifier` writes or extends the test — not the implementer. This is why
   implementation and QA are separate teammates: an implementer verifying its own
   change is a weaker check than an independent one.
4. **No new lint/type errors.** Existing TypeScript strict-mode and ESLint config
   pass clean on every touched file.
5. **Public interface unchanged unless the task explicitly asked for a breaking
   change.** Grep for external consumers of any touched exported symbol before
   declaring done.

If any item fails, `qa-verifier` reports the specific failure to the relevant
`impl-*` teammate by name — not to the lead first. Escalate to the lead only when:
(a) the same item fails twice after a fix attempt, or (b) the failure isn't
attributable to one implementer's diff.
