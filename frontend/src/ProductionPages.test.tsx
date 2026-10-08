import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

describe("ClipFactory production pages", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("CF-REQ-502 CF-REQ-503 CF-REQ-504 CF-REQ-505 CF-REQ-603 renders analytics without inventing missing metrics", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      period: "7d",
      items: [{
        platform: "youtube", views: 1200, likes: 42, comments: null, shares: null,
        watch_time_seconds: 3400, average_retention_ratio: null, estimated_revenue: "1.25",
        revenue_currency: "USD", revenue_by_basis: { rpm_estimate: "1.25" },
      }],
    }), { status: 200 })));

    render(<MemoryRouter initialEntries={["/analytics"]}><App /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Analytics" })).toBeInTheDocument();
    expect(screen.getAllByText("n/a")).toHaveLength(3);
    expect(screen.getByText("Estimated revenue")).toBeInTheDocument();
    expect(screen.getByText("USD 1.25")).toBeInTheDocument();
    expect(screen.getByText(/Rpm Estimate: 1.25/)).toBeInTheDocument();
  });

  it("CF-REQ-551 CF-REQ-607 rejects min 90 / max 60 before submitting", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PUT") return new Response(JSON.stringify({}), { status: 200 });
      return new Response(JSON.stringify({
        name: "Global News", language: "en", category: "general", topics: [], platforms: ["youtube"],
        duration: { min_seconds: 60, target_seconds: 70, max_seconds: 90 },
        output: { width: 720, height: 1280, fps: 30 },
        schedule: { enabled: true, local_time: "05:00", timezone: "Europe/Lisbon" },
      }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/profile"]}><App /></MemoryRouter>);

    const minimum = await screen.findByLabelText("Min Seconds");
    const maximum = screen.getByLabelText("Max Seconds");
    await user.clear(minimum); await user.type(minimum, "90");
    await user.clear(maximum); await user.type(maximum, "60");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("0 < min ≤ target ≤ max");
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });

  it("CF-REQ-606 CF-REQ-753 shows credential presence without secret inputs", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      providers: [
        { provider: "google_tts", credentials_configured: true },
        { provider: "youtube", credentials_configured: false },
      ],
      settings: { publishing: { mode: "dry_run", approval_required: false, auto_publish_after_minutes: 10 } },
    }), { status: 200 })));
    render(<MemoryRouter initialEntries={["/settings"]}><App /></MemoryRouter>);

    expect(await screen.findByText("Google Tts")).toBeInTheDocument();
    expect(screen.getByText("Configured")).toBeInTheDocument();
    expect(screen.getByText("Not configured")).toBeInTheDocument();
    expect(screen.queryByLabelText(/api key|secret|access token/i)).not.toBeInTheDocument();
    expect(screen.getByText("VALUES NEVER DISPLAYED")).toBeInTheDocument();
  });

  it("CF-REQ-759 saves Wan FPS and inference steps as numeric settings", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PUT") return new Response(JSON.stringify({}), { status: 200 });
      return new Response(JSON.stringify({
        providers: [],
        settings: { environment: { wan_fps: 16, wan_inference_steps: 50 } },
      }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/settings"]}><App /></MemoryRouter>);
    const steps = await screen.findByLabelText("Wan Inference Steps");
    const fps = screen.getByLabelText("Wan Fps");
    await user.clear(steps); await user.type(steps, "25");
    await user.clear(fps); await user.type(fps, "8");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(true));
    const update = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(update?.[0]).toBe("/api/settings/environment");
    expect(JSON.parse(String(update?.[1]?.body))).toEqual({ wan_fps: 8, wan_inference_steps: 25 });
  });

  it.each([0, 1, 5, 100])("CF-REQ-266 CF-REQ-606 saves the adjustable Wan limit %i as a number", async (limit) => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PUT") return new Response(JSON.stringify({}), { status: 200 });
      return new Response(JSON.stringify({
        providers: [],
        settings: { environment: { wan_max_generations_per_run: 2 } },
      }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/settings"]}><App /></MemoryRouter>);
    const cap = await screen.findByLabelText("Wan Max Generations Per Run");
    expect(cap).toHaveValue(2);
    expect(cap).toHaveAttribute("min", "0");
    expect(cap).toHaveAttribute("max", "100");
    expect(cap).toHaveAttribute("step", "1");
    expect(cap).toHaveAccessibleDescription(/0 disables new Wan calls/);
    await user.clear(cap); await user.type(cap, String(limit));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(true));
    const update = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(update?.[0]).toBe("/api/settings/environment");
    expect(JSON.parse(String(update?.[1]?.body))).toEqual({ wan_max_generations_per_run: limit });
  });

  it.each(["-1", "2.5", "101"])("CF-REQ-266 rejects invalid Wan limit %s without submitting", async (limit) => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input; void init;
      return new Response(JSON.stringify({
        providers: [],
        settings: { environment: { wan_max_generations_per_run: 2 } },
      }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/settings"]}><App /></MemoryRouter>);
    const cap = await screen.findByLabelText("Wan Max Generations Per Run");
    await user.clear(cap); await user.type(cap, limit);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a whole number from 0 to 100.");
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });

  it("CF-REQ-459 CF-REQ-613 submits an approval decision for a known Clip", async () => {
    let pending = true;
    const clip = {
      id: "clip-1", run_id: "run-1", status: "approved", story_title: "Approval fixture", created_at: "2026-10-01T10:00:00Z", cost_total: "0.20",
      preview: { media_url: "/api/clips/clip-1/media", mime_type: "video/mp4", duration_seconds: 60, width: 720, height: 1280, fps: 30, size_bytes: 1024 },
      auto_publish_due_at: "2099-10-01T10:10:00Z", publications: [{ id: "pub-1", platform: "youtube", status: "awaiting_approval", mode: "live" }],
    };
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") { pending = false; return new Response(JSON.stringify({ clip_id: "clip-1", decision: "approve", already_resolved: false }), { status: 200 }); }
      return new Response(JSON.stringify({ items: pending ? [clip] : [] }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/clips/clip-1/approval"]}><App /></MemoryRouter>);

    await user.click(await screen.findByRole("button", { name: "Approve Approval fixture" }));
    expect(await screen.findByText("Approval fixture approved.")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/clips/clip-1/approval", expect.objectContaining({ method: "POST", body: JSON.stringify({ decision: "approve" }) })));
  });

  it("CF-REQ-610 CF-REQ-612 lists Clips with previews, cost, Publications, links, and metrics", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => new Response(JSON.stringify(String(input) === "/api/budget" ? {
      currency: "EUR", month_to_date_spend: "12.40", monthly_limit: "30.00", monthly_remaining: "17.60", per_clip_limit: "1.00",
    } : { items: [{
      id: "11111111-1111-1111-1111-111111111111", run_id: "22222222-2222-2222-2222-222222222222",
      status: "approved", story_title: "Ocean heat record", created_at: "2026-09-30T12:00:00Z",
      cost_total: "0.83", preview: { media_url: "/api/clips/11111111-1111-1111-1111-111111111111/media", mime_type: "video/mp4", duration_seconds: 72, width: 720, height: 1280, fps: 30, size_bytes: 4096 },
      publications: [
        { id: "pub-youtube", platform: "youtube", status: "published", mode: "live", platform_url: "https://youtube.example/watch/1", latest_metrics: { offset_label: "24h", scheduled_for: "2026-10-01T12:00:00Z", captured_at: "2026-10-01T12:01:00Z", platform: "youtube", views: 3200, likes: 88 } },
        { id: "pub-instagram", platform: "instagram", status: "failed", mode: "live", error_code: "upload_failed", error_message: "Provider rejected upload", latest_metrics: null },
      ],
    }] }), { status: 200 })));
    render(<MemoryRouter initialEntries={["/clips"]}><App /></MemoryRouter>);

    expect(await screen.findByText("Ocean heat record")).toBeInTheDocument();
    expect(screen.getByLabelText("Preview Ocean heat record")).toHaveAttribute("src", "/api/clips/11111111-1111-1111-1111-111111111111/media");
    expect(screen.getByText("EUR 0.83")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open YouTube Publication" })).toHaveAttribute("href", "https://youtube.example/watch/1");
    expect(screen.getByText("3,200 views")).toBeInTheDocument();
    expect(screen.getByText("Metrics n/a")).toBeInTheDocument();
    expect(screen.getByText("TikTok · deferred")).toBeInTheDocument();
  });

  it("CF-REQ-610 opens a real Clip detail route", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/budget") return new Response(JSON.stringify({ currency: "EUR", month_to_date_spend: "12.40", monthly_limit: "30.00", monthly_remaining: "17.60", per_clip_limit: "1.00" }), { status: 200 });
      expect(String(input)).toBe("/api/clips/11111111-1111-1111-1111-111111111111");
      return new Response(JSON.stringify({
        id: "11111111-1111-1111-1111-111111111111", run_id: "22222222-2222-2222-2222-222222222222",
        status: "approved", story_title: "Ocean heat record", created_at: "2026-09-30T12:00:00Z", cost_total: "0.83",
        preview: { media_url: "/api/clips/11111111-1111-1111-1111-111111111111/media", mime_type: "video/mp4", duration_seconds: 72, width: 720, height: 1280, fps: 30, size_bytes: 4096 },
        publications: [],
      }), { status: 200 });
    }));
    render(<MemoryRouter initialEntries={["/clips/11111111-1111-1111-1111-111111111111"]}><App /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Ocean heat record" })).toBeInTheDocument();
    expect(screen.getByText("72s · 720×1280 · 30 fps")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open source Run" })).toHaveAttribute("href", "/runs/22222222-2222-2222-2222-222222222222");
  });
});