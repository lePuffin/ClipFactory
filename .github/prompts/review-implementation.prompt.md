---
description: "Critically review ClipFactory implementation changes against the specification (read-only)."
agent: "reviewer"
argument-hint: "Scope: files, phase, or requirement IDs"
---
Review the implementation of **${input:scope}** against the specification.

1. Determine the requirement IDs in scope ([traceability.md](../../doc/specifications/traceability.md)).
2. For each ID: is the behaviour implemented as written? Are acceptance
   criteria covered by tagged tests that assert behaviour?
3. Apply the reviewer checklist in [reviewer.agent.md](../agents/reviewer.agent.md):
   architecture, provider coupling, tests, complexity, security, correctness,
   terminology, documentation/code consistency.
4. Run the validation commands from [AGENTS.md](../../AGENTS.md) for the
   affected parts and report actual results.

Do not modify files. Produce the verdict (APPROVE / CHANGES REQUIRED /
BLOCKED) with evidence-backed findings.
