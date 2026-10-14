import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";

import App from "./App";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("CF-REQ-614 CF-REQ-417 shows exact revision preview and labels without publication approval", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    revision_id: "revision-1", status: "pending_review", template_version: "modern-news-v1", openrouter_calls: 0, tts_calls: 0,
    request: { base_clip_id: "clip-1", overlays: [{ kind: "place", text: "Mokha, Yemen", secondary: "Red Sea port", start_seconds: 5, end_seconds: 10 }] },
    sources: ["BBC News: https://bbc.example/story"], credits: ["Archive photograph, CC BY 4.0"],
  }), { status: 200 })));
  render(<MemoryRouter initialEntries={["/review/revision-1"]}><App /></MemoryRouter>);
  expect(await screen.findByDisplayValue("Mokha, Yemen")).toBeInTheDocument();
  expect(screen.getByText("Pending quality review")).toBeInTheDocument();
  expect(screen.getByText("Not approved for publication")).toBeInTheDocument();
  expect(screen.getByLabelText("Rendered Clip preview")).toHaveAttribute("src", "/api/render-revisions/revision-1/media");
  expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Render revision" })).toBeInTheDocument();
});