import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { RunDetail, RunEvent } from "./api/client";

class RunEventSource {
  static current: RunEventSource;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  constructor() { RunEventSource.current = this; }
  addEventListener() {}
  removeEventListener() {}
  close() {}
  emit(event: RunEvent) { this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(event) })); }
}

function runEvent(sequence: number, stage: string, type = "stage_started", attempt = 1): RunEvent {
  return { sequence, stage, type, attempt, level: "info", message: `Event ${sequence}`, payload: {}, created_at: "2026-10-07T10:00:00Z" };
}

function renderRun(overrides: Partial<RunDetail> = {}) {
  const run: RunDetail = {
    run_id: "run-1", trigger: "run_now", status: "running", attempt: 1,
    revision_retries_used: 0, cost_total: "0.00", created_at: "2026-10-07T10:00:00Z",
    profile_snapshot: {}, settings_snapshot: {}, events: [], evaluations: [], ...overrides,
  };
  vi.stubGlobal("EventSource", RunEventSource);
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(run), { status: 200 })));
  return render(<MemoryRouter initialEntries={["/runs/run-1"]}><App /></MemoryRouter>);
}

describe("ClipFactory operational frontend", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it.each(["video", "image", "audio"])("CF-REQ-605 previews %s Assets with their folder and filename", async (mediaType) => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ items: [{
      id: "asset-1", media_type: mediaType, category: "broll", storage_key: "assets/ab/example.mp4",
      storage_path: "/srv/clipfactory/assets/ab/example.mp4", sha256: "a".repeat(64), mime_type: `${mediaType}/mp4`,
      size_bytes: 1048576, description: "Generated grid", tags: ["generated"], subjects: [],
      provenance: { provider: "wan_local", license: "Apache-2.0" }, reusable: true, status: "active", usage_count: 0,
      width: 720, height: 1280, duration_seconds: 6.5,
    }] }), { status: 200 })));
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/assets"]}><App /></MemoryRouter>);
    await user.click(await screen.findByRole("button", { name: "Preview Generated grid" }));
    const preview = screen.getByRole("region", { name: "Asset preview" });
    expect(within(preview).getByText("/srv/clipfactory/assets/ab")).toBeInTheDocument();
    expect(within(preview).getByText("example.mp4")).toBeInTheDocument();
    expect(within(preview).getByRole("link", { name: "Open media file" })).toHaveAttribute("href", "/api/assets/asset-1/file");
    const media = preview.querySelector(mediaType === "image" ? "img" : mediaType);
    expect(media).toHaveAttribute("src", "/api/assets/asset-1/file");
    if (mediaType !== "image") expect(media).toHaveAttribute("controls");
    act(() => media?.dispatchEvent(new Event("error")));
    expect(within(preview).getByRole("alert")).toHaveTextContent("Asset media could not be loaded");
    await user.click(screen.getByRole("button", { name: "Close preview" }));
    expect(screen.queryByRole("region", { name: "Asset preview" })).not.toBeInTheDocument();
  });

  it("CF-REQ-605 combines media, origin and provider filters and resets them", async () => {
    const base = { category: "broll", storage_key: "assets/ab/example.mp4", sha256: "a".repeat(64),
      mime_type: "video/mp4", size_bytes: 100, tags: [], subjects: [], reusable: true, status: "active", usage_count: 0 };
    const assets = [
      { ...base, id: "one", description: "Wan grid", media_type: "video", provenance: { origin: "generated", provider: "wan_local", license: "Apache-2.0" } },
      { ...base, id: "two", description: "Pixabay grid", media_type: "image", provenance: { origin: "external", provider: "pixabay", license: "CC0" } },
      { ...base, id: "three", description: "Imported grid", media_type: "video", provenance: { origin: "imported", provider: "manual", license: "CC0" } },
    ];
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ items: assets }), { status: 200 })));
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/assets"]}><App /></MemoryRouter>);
    await screen.findByText("Wan grid");
    await user.selectOptions(screen.getByLabelText("Media type"), "video");
    expect(screen.queryByText("Pixabay grid")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Origin"), "generated");
    expect(screen.queryByText("Imported grid")).not.toBeInTheDocument();
    expect(screen.getByText("1 OF 3 LOADED")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Provider"), "pixabay");
    expect(screen.getByText("No Assets match the selected filters.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(screen.getByText("3 OF 3 LOADED")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Provider"), "pixabay");
    expect(screen.getByText("Pixabay grid")).toBeInTheDocument();
    expect(screen.queryByText("Wan grid")).not.toBeInTheDocument();
  });

  it("CF-REQ-604 shows snapshotted models and frozen elapsed time for a finished Run", async () => {
    renderRun({ status: "completed", started_at: "2026-10-07T10:00:00Z", finished_at: "2026-10-07T10:02:05Z",
      settings_snapshot: { environment: { llm_model: "writer-model", llm_model_evaluation: "vision-model" } } });
    await screen.findByText("ELAPSED TIME");
    expect(screen.getByText("2m 05s")).toBeInTheDocument();
    expect(screen.getByText("writer-model")).toBeInTheDocument();
    expect(screen.getByText("vision-model")).toBeInTheDocument();
  });

  it("CF-REQ-604 updates elapsed time locally and freezes on a terminal SSE event", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.setSystemTime(new Date("2026-10-07T10:00:10Z"));
    renderRun({ started_at: "2026-10-07T10:00:00Z" });
    await screen.findByText("10s");
    act(() => vi.advanceTimersByTime(2000));
    expect(screen.getByText("12s")).toBeInTheDocument();
    act(() => RunEventSource.current.emit({ ...runEvent(1, "publish", "run_completed"), created_at: "2026-10-07T10:00:12Z" }));
    act(() => vi.advanceTimersByTime(5000));
    expect(screen.getByText("12s")).toBeInTheDocument();
  });

  it("CF-REQ-604 shows and updates current Visual / total in Execution", async () => {
    const visual = { ...runEvent(1, "select_assets", "progress"), payload: { segment_index: 0, segment_count: 11 } };
    renderRun({ events: [visual] });
    const label = await screen.findByText("VISUALS");
    expect(label.parentElement).toHaveTextContent("1 / 11");
    act(() => RunEventSource.current.emit({ ...visual, sequence: 2, payload: { ...visual.payload, segment_index: 9, generation_phase: "inference" } }));
    expect(label.parentElement).toHaveTextContent("10 / 11");
    act(() => RunEventSource.current.emit({ ...visual, sequence: 3, payload: { ...visual.payload, generation_phase: "heartbeat" } }));
    expect(label.parentElement).toHaveTextContent("10 / 11");
  });

  it("CF-REQ-604 does not show stale Visual counts after continuation", async () => {
    renderRun({ events: [
      { ...runEvent(1, "select_assets", "progress"), payload: { segment_index: 9, segment_count: 11 } },
      runEvent(2, "select_assets", "run_resumed"),
    ] });
    expect((await screen.findByText("VISUALS")).parentElement).toHaveTextContent("n/a");
  });

  it.each([
    ["2026-10-07T10:59:59Z", "59m 59s"],
    ["2026-10-07T11:00:00Z", "1h 00m 00s"],
    ["2026-10-07T11:05:09Z", "1h 05m 09s"],
    ["2026-10-08T12:00:01Z", "26h 00m 01s"],
  ])("CF-REQ-604 formats elapsed time ending at %s as %s", async (finishedAt, expected) => {
    renderRun({ status: "completed", started_at: "2026-10-07T10:00:00Z", finished_at: finishedAt });
    expect(await screen.findByText(expected)).toBeInTheDocument();
  });

  it("CF-REQ-604 displays live generation steps and failures", async () => {
    const loading = { ...runEvent(1, "select_assets", "progress"), message: "Loading Wan", payload: { generation_phase: "loading_model", provider: "wan_local", model: "wan-model" } };
    renderRun({ events: [loading] });
    const panel = await screen.findByRole("status", { name: "Media generation" });
    expect(panel).toHaveTextContent("Loading Model");
    expect(panel).toHaveTextContent("shared local cache");
    expect(panel).not.toHaveTextContent("Download percentage");
    act(() => RunEventSource.current.emit({ ...loading, sequence: 2, message: "Fetching model files", payload: { ...loading.payload, generation_phase: "downloading_model" } }));
    expect(panel).toHaveTextContent("Download percentage is unavailable");
    act(() => RunEventSource.current.emit({ ...loading, sequence: 3, message: "Inference", payload: { ...loading.payload, generation_phase: "inference", step: 3, total_steps: 50 } }));
    expect(within(panel).getByRole("progressbar", { name: "Generation inference" })).toHaveAttribute("value", "3");
    expect(panel).toHaveTextContent("Step 3 / 50");
    act(() => RunEventSource.current.emit({ ...loading, sequence: 4, message: "Insufficient VRAM", payload: { ...loading.payload, generation_phase: "failed" } }));
    expect(panel).toHaveTextContent("Failed");
    expect(panel).toHaveTextContent("Insufficient VRAM");
    expect(within(panel).queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it.each(["hyperframes", "manim"])("CF-REQ-604 shows %s rendering activity without model-loading claims", async (provider) => {
    const rendering = { ...runEvent(1, "select_assets", "progress"), message: "Rendering planned graphic",
      payload: { provider, generation_phase: "rendering", segment_index: 2, segment_count: 11, template: "comparison" } };
    renderRun({ events: [rendering] });
    const panel = await screen.findByRole("status", { name: "Media generation" });
    expect(panel).toHaveTextContent(provider);
    expect(panel).toHaveTextContent("Visual 3");
    expect(panel).toHaveTextContent("Comparison");
    expect(within(panel).queryByRole("progressbar")).not.toBeInTheDocument();
    expect(panel).not.toHaveTextContent("model weights");
    act(() => RunEventSource.current.emit({ ...rendering, sequence: 2, payload: { ...rendering.payload, progress_fraction: 0.5 } }));
    expect(within(panel).getByRole("progressbar", { name: "Graphics rendering" })).toHaveAttribute("value", "0.5");
    expect(panel).toHaveTextContent("50% rendered");
    act(() => RunEventSource.current.emit({ ...rendering, sequence: 3, payload: { ...rendering.payload, step: 15, total_steps: 30 } }));
    expect(panel).toHaveTextContent("Frame 15 / 30");
    act(() => RunEventSource.current.emit({ ...rendering, sequence: 4, message: "Renderer unavailable", payload: { ...rendering.payload, generation_phase: "failed" } }));
    expect(panel).toHaveTextContent("Renderer unavailable");
  });

  it("CF-REQ-602 advances Execution progress with actual Wan steps without heartbeat resets", async () => {
    const event = { ...runEvent(1, "select_assets", "progress"), payload: {
      generation_phase: "inference", segment_index: 0, segment_count: 1, step: 0, total_steps: 50,
    } };
    renderRun({ events: [event] });
    const bar = await screen.findByRole("progressbar", { name: "Run progress" });
    const initial = Number(bar.getAttribute("aria-valuenow"));
    act(() => RunEventSource.current.emit({ ...event, sequence: 2, payload: { ...event.payload, step: 40 } }));
    const progressed = Number(bar.getAttribute("aria-valuenow"));
    expect(progressed).toBeGreaterThan(initial);
    act(() => RunEventSource.current.emit({ ...event, sequence: 3, payload: { generation_phase: "heartbeat" } }));
    expect(Number(bar.getAttribute("aria-valuenow"))).toBe(progressed);
    expect(progressed).toBeLessThan(10 / 17 * 100);
  });

  it("CF-REQ-604 shows unavailable metadata and does not animate interrupted generation after reload", async () => {
    renderRun({ status: "failed", events: [{ ...runEvent(1, "select_assets", "progress"),
      payload: { generation_phase: "inference", step: 3, total_steps: 50 } }] });
    const panel = await screen.findByRole("status", { name: "Media generation" });
    expect(panel).toHaveTextContent("Stopped");
    expect(within(panel).queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getAllByText("n/a")).toHaveLength(4);
  });

  it("CF-REQ-657 confirms continuation and reloads the same Run without stale failed progress", async () => {
    const user = userEvent.setup();
    renderRun({ status: "failed", failure_code: "stage_timeout", events: [runEvent(1, "select_assets", "run_failed")] });
    await user.click(await screen.findByRole("button", { name: "Continue Run" }));
    expect(screen.getByRole("button", { name: "Continue Run" }).closest(".section-head")).toHaveTextContent("EXECUTION");
    expect(screen.getByText(/current application settings/)).toBeInTheDocument();
    const fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") return new Response(JSON.stringify({ run_id: "run-1" }), { status: 202 });
      return new Response(JSON.stringify({
        run_id: "run-1", trigger: "run_now", status: "queued", current_stage: "select_assets", attempt: 1,
        revision_retries_used: 0, cost_total: "0", created_at: "2026-10-07T10:00:00Z",
        profile_snapshot: {}, settings_snapshot: {}, evaluations: [],
        events: [runEvent(1, "select_assets", "run_failed"), runEvent(2, "select_assets", "run_resumed")],
      }));
    });
    vi.stubGlobal("fetch", fetch);
    await user.click(screen.getByRole("button", { name: "Confirm Continue" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Continue Run" })).not.toBeInTheDocument());
    expect(fetch).toHaveBeenCalledWith("/api/runs/run-1/continue", expect.objectContaining({ method: "POST" }));
    await waitFor(() => expect(screen.getByRole("progressbar", { name: "Run progress" }).parentElement).not.toHaveClass("failed"));
  });

  it("CF-REQ-657 displays an actionable continuation rejection", async () => {
    const user = userEvent.setup();
    renderRun({ status: "failed" });
    await user.click(await screen.findByRole("button", { name: "Continue Run" }));
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { message: "No matching checkpoint" } }), { status: 409 })));
    await user.click(screen.getByRole("button", { name: "Confirm Continue" }));
    expect(await screen.findByText("No matching checkpoint")).toBeInTheDocument();
  });

  it("CF-REQ-657 confirms immediate Stop beside status and shows stopping until terminal event", async () => {
    const user = userEvent.setup();
    renderRun();
    const stop = await screen.findByRole("button", { name: "Stop" });
    expect(stop.closest(".section-head")).toHaveTextContent("running");
    await user.click(stop);
    expect(screen.getByText(/Unfinished generation may be lost/)).toBeInTheDocument();
    const fetch = vi.fn(async () => new Response(JSON.stringify({ run_id: "run-1" }), { status: 202 }));
    vi.stubGlobal("fetch", fetch);
    await user.click(screen.getByRole("button", { name: "Confirm Stop" }));
    expect(await screen.findByRole("button", { name: "Stopping…" })).toBeDisabled();
    expect(fetch).toHaveBeenCalledWith("/api/runs/run-1/stop", expect.objectContaining({ method: "POST" }));
  });

  it("CF-REQ-602 CF-REQ-604 embeds live progress in Execution and shows newest events first", async () => {
    renderRun({ events: [runEvent(1, "research", "stage_completed"), runEvent(2, "write_script")] });
    const bar = await screen.findByRole("progressbar", { name: "Run progress" });
    expect(bar.closest("section")).toHaveTextContent("EXECUTION");
    expect(screen.queryByText("LIVE PROGRESS")).not.toBeInTheDocument();
    expect(bar).toHaveAttribute("aria-valuenow", "38");
    expect(bar).toHaveAttribute("aria-valuetext", "Write Script · running · Attempt 1");
    const stream = screen.getByRole("list", { name: "Run Events, newest first" });
    expect(within(stream).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      expect.stringContaining("Event 2"), expect.stringContaining("Event 1"),
    ]);
    await waitFor(() => expect(RunEventSource.current).toBeDefined());
    act(() => RunEventSource.current.emit(runEvent(3, "compose_clip")));
    expect(bar).toHaveAttribute("aria-valuenow", "74");
    expect(bar).toHaveAttribute("aria-valuetext", "Compose Clip · running · Attempt 1");
    expect(within(stream).getAllByRole("listitem")[0]).toHaveTextContent("Event 3");
    act(() => RunEventSource.current.emit(runEvent(4, "write_script", "stage_started", 2)));
    expect(bar).toHaveAttribute("aria-valuenow", "38");
    expect(bar).toHaveAttribute("aria-valuetext", "Write Script · running · Attempt 2");
    act(() => RunEventSource.current.emit(runEvent(4, "write_script", "stage_started", 2)));
    expect(within(stream).getAllByRole("listitem")).toHaveLength(4);
    act(() => RunEventSource.current.emit(runEvent(5, "write_script", "stage_completed", 2)));
    expect(bar).toHaveAttribute("aria-valuenow", "41");
    expect(bar).toHaveAttribute("aria-valuetext", "Write Script · done · Attempt 2");
  });

  it("CF-REQ-604 hides stored and live watchdog heartbeats from Run Events and counts", async () => {
    const heartbeat = { ...runEvent(2, "select_assets", "progress"), message: "Wan generation worker is active", payload: { generation_phase: "heartbeat" } };
    renderRun({ events: [runEvent(1, "select_assets"), heartbeat] });
    const stream = await screen.findByRole("list", { name: "Run Events, newest first" });
    expect(within(stream).getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText("1 EVENTS")).toBeInTheDocument();
    expect(screen.queryByText(heartbeat.message)).not.toBeInTheDocument();
    act(() => RunEventSource.current.emit({ ...heartbeat, sequence: 3 }));
    expect(within(stream).getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText("1 EVENTS")).toBeInTheDocument();
    act(() => RunEventSource.current.emit(runEvent(4, "select_assets", "progress")));
    expect(within(stream).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("2 EVENTS")).toBeInTheDocument();
  });

  it.each([
    { status: "queued", current_stage: null, expected: "0", text: "Queued" },
    { status: "completed", current_stage: "publish", expected: "100", text: "Completed" },
    { status: "failed", current_stage: "write_script", expected: "38", text: "Write Script · failed · Attempt 1" },
    { status: "running", trigger: "manual_url", current_stage: "ingest_url", expected: "3", text: "Ingest Url · running · Attempt 1" },
  ])("CF-REQ-602 renders $status progress for $current_stage", async ({ expected, text, ...run }) => {
    renderRun(run);
    const bar = await screen.findByRole("progressbar", { name: "Run progress" });
    expect(bar).toHaveAttribute("aria-valuenow", expected);
    expect(bar).toHaveAttribute("aria-valuetext", text);
    if (run.status === "failed") expect(bar.parentElement).toHaveClass("failed");
  });

  it("CF-REQ-601 CF-REQ-612 shows dashboard KPIs, schedule, and budget", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/health")) {
          return new Response(JSON.stringify({ status: "healthy", version: "1.0.0", checks: { database: true } }), { status: 200 });
        }
        if (url.endsWith("/api/runs/active")) return new Response(null, { status: 204 });
        if (url.endsWith("/api/dashboard/summary")) return new Response(JSON.stringify({
          period: "7d", clips_approved: 4, publications: 9, views: 12500,
          estimated_revenue: "8.40", estimated_revenue_currency: "EUR",
          next_scheduled_run_at: "2026-10-02T05:00:00Z",
        }), { status: 200 });
        if (url.endsWith("/api/budget")) return new Response(JSON.stringify({
          currency: "EUR", month_to_date_spend: "12.403789", monthly_limit: "30",
          monthly_remaining: "17.596211", per_clip_limit: "1.000000",
        }), { status: 200 });
        return new Response(JSON.stringify({ items: [] }), { status: 200 });
      }),
    );
    render(<MemoryRouter><App /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Production desk" })).toBeInTheDocument();
    expect(await screen.findByText("All systems nominal")).toBeInTheDocument();
    expect(await screen.findByText("No Runs recorded yet")).toBeInTheDocument();
    expect(screen.getByText("12,500")).toBeInTheDocument();
    expect(screen.getByText("Estimated revenue")).toBeInTheDocument();
    expect(screen.getByText("EUR 8.40")).toBeInTheDocument();
    expect(screen.getByText("EUR 12.40 of EUR 30.00 this month")).toBeInTheDocument();
    expect(screen.getByText("EUR 17.60 remaining")).toBeInTheDocument();
    expect(screen.getByText("EUR 1.00 per Clip limit")).toBeInTheDocument();
    expect(screen.getByText(/02 Oct/)).toBeInTheDocument();
  });

  it("CF-REQ-459 CF-REQ-460 CF-REQ-613 approves a pending Clip and removes it", async () => {
    let pending = true;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/clips/pending-approval?limit=100")) return new Response(JSON.stringify({ items: pending ? [{
        id: "11111111-1111-1111-1111-111111111111", run_id: "22222222-2222-2222-2222-222222222222",
        status: "approved", story_title: "Solar breakthrough", created_at: "2026-10-01T10:00:00Z",
        cost_total: "0.72", social_metadata: { title: "Solar in sixty seconds", description: "A sourced briefing" },
        preview: { media_url: "/api/clips/11111111-1111-1111-1111-111111111111/media", mime_type: "video/mp4", duration_seconds: 68, width: 720, height: 1280, fps: 30, size_bytes: 2048 },
        auto_publish_due_at: "2099-10-01T10:10:00Z",
        publications: [{ id: "pub-1", platform: "youtube", status: "awaiting_approval", mode: "live" }],
      }] : [] }), { status: 200 });
      if (url.endsWith("/approval") && init?.method === "POST") {
        pending = false;
        return new Response(JSON.stringify({ clip_id: "11111111-1111-1111-1111-111111111111", decision: "approve", already_resolved: false }), { status: 200 });
      }
      if (url.endsWith("/api/runs/active")) return new Response(null, { status: 204 });
      if (url.endsWith("/api/health")) return new Response(JSON.stringify({ status: "healthy", version: "1.0.0", checks: {} }), { status: 200 });
      if (url.endsWith("/api/dashboard/summary")) return new Response(JSON.stringify({ period: "7d", clips_approved: 0, publications: 0, views: 0, estimated_revenue: "0.00" }), { status: 200 });
      if (url.endsWith("/api/budget")) return new Response(JSON.stringify({ currency: "EUR", month_to_date_spend: "0.00", monthly_limit: "30.00", monthly_remaining: "30.00", per_clip_limit: "1.00" }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter><App /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Pending approval" })).toBeInTheDocument();
    expect(screen.getByText("Solar breakthrough")).toBeInTheDocument();
    expect(screen.getByText(/YouTube · Awaiting Approval/)).toBeInTheDocument();
    expect(screen.getByText(/Auto-publishes in/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approve Solar breakthrough" }));
    expect(await screen.findByText("No Clips are awaiting approval.")).toBeInTheDocument();
  });

  it("CF-REQ-856 explains when the API is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Internal Server Error", { status: 500 })));
    render(<MemoryRouter><App /></MemoryRouter>);
    expect(await screen.findAllByText("ClipFactory API is unavailable. Start the backend and retry.")).toHaveLength(6);
  });

  it("CF-REQ-605 retires an Asset and filters it by status", async () => {
    let assetStatus = "active";
    const asset = {
      id: "asset-1",
      media_type: "image",
      category: "photo",
      storage_key: "assets/ab/example.png",
      sha256: "abcdef0123456789",
      mime_type: "image/png",
      size_bytes: 123,
      description: "Parliament exterior",
      tags: ["parliament"],
      subjects: ["UK Parliament"],
      provenance: { provider: "wikimedia_commons", license: "CC BY 4.0", attribution_text: "Photographer / CC BY 4.0" },
      reusable: true,
      status: "active",
      usage_count: 2,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.startsWith("/api/assets/") && init?.method === "PATCH") {
          assetStatus = JSON.parse(String(init.body)).status as string;
          return new Response(JSON.stringify({ ...asset, status: assetStatus }), { status: 200 });
        }
        if (url.startsWith("/api/assets")) {
          const requestedStatus = new URL(url, "http://local").searchParams.get("status");
          return new Response(JSON.stringify({ items: requestedStatus === "all" || requestedStatus === assetStatus ? [{ ...asset, status: assetStatus }] : [] }), { status: 200 });
        }
        return new Response("missing", { status: 404 });
      }),
    );
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/assets"]}><App /></MemoryRouter>);
    expect(await screen.findByText("Parliament exterior")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retire" }));
    await waitFor(() => expect(screen.getByText("No Assets match the selected filters.")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "retired" }));
    expect(await screen.findByText("Parliament exterior")).toBeInTheDocument();
    expect(screen.getAllByText("retired")).toHaveLength(2);
  });

  it("CF-REQ-608 CF-REQ-609 starts Run Now and Manual URL Runs", async () => {
    const posts: Array<{ url: string; body: string | undefined }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (init?.method === "POST") {
          posts.push({ url, body: init.body?.toString() });
          return new Response(JSON.stringify({ run_id: "12345678-1234-1234-1234-123456789abc" }), { status: 202 });
        }
        if (url.endsWith("/api/runs/active")) return new Response(null, { status: 204 });
        if (url.endsWith("/api/health")) return new Response(JSON.stringify({ status: "healthy", version: "1.0.0", checks: {} }), { status: 200 });
        if (url.endsWith("/api/dashboard/summary")) return new Response(JSON.stringify({ period: "7d", clips_approved: 0, publications: 0, views: 0, estimated_revenue: "0.00" }), { status: 200 });
        if (url.endsWith("/api/budget")) return new Response(JSON.stringify({ currency: "EUR", month_to_date_spend: "0.00", monthly_limit: "30.00", monthly_remaining: "30.00", per_clip_limit: "1.00" }), { status: 200 });
        return new Response(JSON.stringify({ items: [] }), { status: 200 });
      }),
    );
    const user = userEvent.setup();
    render(<MemoryRouter><App /></MemoryRouter>);

    await user.click(await screen.findByRole("button", { name: "Run Now" }));
    expect(await screen.findByText("Run 12345678 queued")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Manual Source URL"), "https://news.example/article");
    await user.click(screen.getByRole("button", { name: "Start Manual URL Run" }));

    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[0]).toEqual({ url: "/api/runs", body: undefined });
    expect(posts[1]).toEqual({ url: "/api/runs/manual-url", body: JSON.stringify({ url: "https://news.example/article" }) });
  });

  it("CF-REQ-602 CF-REQ-604 refreshes the Run record until it fails and shows the failure", async () => {
    vi.stubGlobal("EventSource", class { close() {} addEventListener() {} removeEventListener() {} });
    const runId = "fba93c4a-4b77-4138-9d8c-89a5ff4a7bc6";
    const base = { run_id: runId, trigger: "run_now", attempt: 1, revision_retries_used: 0, cost_total: "0.00", created_at: "2026-10-02T10:00:00Z", profile_snapshot: {}, settings_snapshot: {}, events: [], evaluations: [] };
    let detailCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith(`/api/runs/${runId}`)) {
        detailCalls += 1;
        return new Response(JSON.stringify(detailCalls === 1
          ? { ...base, status: "running", current_stage: "research" }
          : { ...base, status: "failed", current_stage: "research", failure_stage: "research", failure_code: "llm_unavailable", failure_message: "LLM request failed with HTTP 404 from openrouter.ai for model 'm'" }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter initialEntries={[`/runs/${runId}`]}><App /></MemoryRouter>);

    expect(await screen.findByText("llm_unavailable · stage research", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByText(/for model 'm'/)).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 1200));
    expect(detailCalls).toBe(2);
  });
});