# Frontend Architecture

Requirements: [15-ui-and-dashboard.md](../15-ui-and-dashboard.md).

## Stack

| Concern | Choice | Reason |
| --- | --- | --- |
| Language | TypeScript, `strict` | CF-NFR-022 |
| Framework / build | React + Vite | Brief |
| Styling | Tailwind CSS, dark theme tokens in `tailwind.config` | Brief |
| Routing | React Router | Eight pages need client routing |
| Server state | TanStack Query | Caching, refetch and mutation state without hand-written stores (Provisional; plain hooks acceptable if simpler) |
| API types | Generated from the backend OpenAPI schema with `openapi-typescript` into `src/api/schema.ts` | Prevents contract drift |
| Charts | One small charting library (Provisional: Recharts) | Analytics page |
| Tests | Vitest + Testing Library; Playwright (+ axe-core) | Brief, CF-NFR-040 |

No global state library (Redux etc.) and no UI component framework beyond
Tailwind and small local components.

## Structure

```text
frontend/src/
├── api/          # fetch client, generated schema types, SSE helper
├── components/   # reusable presentational components (Button, Card, StageStepper, EstimatedValue…)
├── features/     # feature modules: runs, clips, analytics, assets, profile, settings
├── pages/        # route components composing features
├── hooks/        # useRunEvents (SSE), useActiveRun, …
└── types/        # UI-only types (API types come from api/schema.ts)
```

## Live progress

- `useRunEvents(runId)` wraps `EventSource` on
  `/api/runs/{id}/events/stream` (same-origin cookie auth), tracks the last
  `sequence`, and relies on the browser's `Last-Event-ID` reconnection.
- The stage stepper derives stage states from events using the canonical
  stage list shipped in the generated API types (enum).

## Rules

- Render external text as text only; `dangerouslySetInnerHTML` is forbidden by lint (CF-REQ-611).
- Revenue values render through one `EstimatedRevenue` component that always
  shows the "Estimated" label and basis (CF-REQ-603).
- Missing metrics render "n/a" (CF-REQ-502).
- Forms mirror server validation but treat the server as authoritative.
- In production the SPA is served by FastAPI at `/`; in development Vite
  proxies `/api` to the backend.
