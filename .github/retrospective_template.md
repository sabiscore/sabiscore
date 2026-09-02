# 🔍 Session Retrospective: [Blocker ID / Short Title]

- **Date:** [YYYY-MM-DD]
- **Target Branch:** [e.g., main or integration/sabi-phase-1]
- **Primary P0 Fixed:** [Brief summary of the resolved critical blocker]
- **Session Status:** [Success / Blocked on Context / Surfaced Product Question]

---

### 1. 🧬 Root Cause & Pattern Analysis
- **Core Defect:** [What was broken or missing in the codebase?]
- **Underlying Pattern:** [Is this a recurring pattern, e.g., missing database index, unhandled Redis timeout, BullMQ job lock leak, memory leak?]
- **Prevention Rule:** [What pattern or rule can prevent this in future commits?]

### 2. ⚡ Resource & Memory Audit (8GB RAM Constraint)
- **Local Environment Impact:** [Did running tests/linting approach or breach local memory limits?]
- **Bottlenecks Identified:** [Heavy test suites, unoptimized backend workers, high concurrency issues.]
- **Mitigation Applied:** [Targeted pytest flags, reduced worker concurrency, trimmed payload sizes.]

### 3. 📑 Tech Debt & Architectural Log
- **Debt Introduced:** [Any temporary hacks or deferred refactors needed to keep the fix safe and small?]
- **Debt Items Logged:** [Links or references to issues added to the debt tracker.]

### 4. 🛠️ Agent & Prompt Execution Feedback
- **Workflow Friction:** [Did the agent encounter ambiguous instructions or missing workspace context?]
- **Prompt Refinement Note:** [Specific adjustment to add to `INSTRUCTIONS.md` or `.cursorrules` to streamline future automated sessions.]