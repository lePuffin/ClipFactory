---
description: "Investigate why a ClipFactory Run, stage, test or integration failed and propose a root-cause fix."
agent: "agent"
argument-hint: "Run ID, failing test, or symptom"
---
Investigate the failure: **${input:symptom}**.

Follow the [debugging skill](../skills/debugging/SKILL.md):

1. Gather evidence (Run detail, events, Evaluations, LLM audit files, logs,
   failing test output). Quote the relevant parts.
2. Map the failure code/issue code to the specification
   ([16](../../doc/specifications/16-scheduling-and-runs.md),
   [11](../../doc/specifications/11-evaluation-and-retry.md),
   [20](../../doc/specifications/20-observability.md)).
3. Decide whether it is: a configuration problem, a provider/environment
   problem, a code defect, or a specification gap/conflict.
4. For a code defect: write a failing regression test tagged with the
   requirement ID, fix the root cause, run validation.
5. For a specification gap: do not patch around it; describe it and propose a
   specification change (see the update-specification prompt).

Report: root cause, evidence, fix (or proposed spec change), validation results.
