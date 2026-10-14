# ADR-004 — LangGraph as the workflow engine, kept at the edge

- **Status:** Proposed

## Context

A Run is a multi-stage, stateful process with conditional routing (story
fallback, gates, targeted retry), bounded loops, observability and
resumption after restart. The brief mandates LangGraph for the workflow but
forbids letting it become the application's architecture.

## Decision

- Use LangGraph `StateGraph` with a PostgreSQL checkpointer (`thread_id = run_id`).
- One graph node per canonical `Stage`; nodes are thin wrappers calling one
  application use case each.
- Workflow state holds only identifiers and control data (CF-REQ-658).
- `langgraph` may be imported only in `workflow/` and the composition root.
- No LangGraph agents, tools or LLM-driven routing: edges are code conditions.

## Consequences

- The workflow can be replaced (e.g. by a hand-written state machine)
  without touching use cases or domain.
- Nodes must be idempotent with respect to persisted outputs so resumption is safe.
- Checkpoint tables live in the same PostgreSQL database.

## Alternatives considered

- Hand-written state machine: viable, but the brief selected LangGraph and it provides checkpointing.
- Temporal / Celery canvas: distributed infrastructure, prohibited (CF-NFR-002).
- Agent frameworks with autonomous tool use: unpredictable control flow; contradicts deterministic routing.
