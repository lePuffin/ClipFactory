---
description: "Use when writing or editing the ClipFactory frontend: React, TypeScript, Vite, Tailwind CSS, API client, SSE hooks, pages and components."
applyTo: "frontend/**/*.{ts,tsx,css,html}"
---
# Frontend rules

Canonical references: [15-ui-and-dashboard](../../doc/specifications/15-ui-and-dashboard.md),
[frontend-architecture](../../doc/specifications/architecture/frontend-architecture.md).

- TypeScript `strict`; no `any` unless justified in a comment.
- React function components and hooks. Server state via the chosen query
  layer; no global state library.
- API types come only from the generated `src/api/schema.ts` (OpenAPI). Do
  not hand-write duplicates of backend models. Regenerate after API changes.
- Styling with Tailwind utility classes and the dark-theme tokens; keep
  components small and accessible (labels, focus states, keyboard support,
  WCAG AA contrast).
- Render all external text as text. `dangerouslySetInnerHTML` is forbidden.
- Revenue is always displayed through the `EstimatedRevenue` component
  ("Estimated revenue" + basis). Missing metrics display "n/a", never 0.
- Live progress uses the SSE hook (`useRunEvents`); do not add polling loops
  or WebSockets.
- Use canonical terms in UI copy: Clip, Story, Source, Claim, Run, Asset,
  Content Profile, Publication. Platforms are YouTube, Instagram, TikTok, Facebook.
- Every behaviour change has Vitest tests; user journeys have Playwright tests
  titled with requirement IDs.
- Validate with `npm run lint`, `npm run typecheck`, `npm run test`, `npm run build`.
