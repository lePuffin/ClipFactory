import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/content-profiles") return new Response(JSON.stringify({ items: [] }), { status: 200 });
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

  it("CF-REQ-606 CF-REQ-651 edits the daily Run schedule and preserves the rest of the profile", async () => {
    const profile = {
      niche: "world news", tone: "calm",
      schedule: { enabled: true, local_time: "05:00", timezone: "Europe/Lisbon" },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PUT") return new Response(JSON.stringify({}), { status: 200 });
      const url = String(input);
      if (url === "/api/content-profile") return new Response(JSON.stringify(profile), { status: 200 });
      if (url === "/api/dashboard/summary") return new Response(JSON.stringify({ next_scheduled_run_at: "2026-10-08T04:00:00Z" }), { status: 200 });
      return new Response(JSON.stringify({ providers: [], settings: {} }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/settings"]}><App /></MemoryRouter>);
    const time = await screen.findByLabelText("Run Time");
    expect(time).toHaveValue("05:00");
    expect(screen.getByRole("combobox", { name: "Timezone" })).toHaveValue("Europe/Lisbon");
    expect(await screen.findByText(/NEXT RUN 8 OCT 2026/)).toBeInTheDocument();
    fireEvent.change(time, { target: { value: "07:30" } });
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(true));
    const update = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(update?.[0]).toBe("/api/content-profile");
    expect(JSON.parse(String(update?.[1]?.body))).toEqual({
      ...profile, schedule: { enabled: true, local_time: "07:30", timezone: "Europe/Lisbon" },
    });
    expect(await screen.findByText(/Daily Run set for 07:30/)).toBeInTheDocument();
  });

  it("CF-REQ-606 CF-REQ-752 uses fixed-choice dropdowns and preserves open-ended settings", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PUT") return new Response(JSON.stringify({}), { status: 200 });
      return new Response(JSON.stringify({
        providers: [],
        settings: {
          environment: { whisper_device: "cpu", whisper_compute_type: "custom-type", llm_model: "custom/model" },
          publishing: { mode: "dry_run", approval_required: true },
        },
      }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/settings"]}><App /></MemoryRouter>);
    const device = await screen.findByRole("combobox", { name: "Whisper Device" });
    const mode = screen.getByRole("combobox", { name: "Mode" });
    expect([...device.querySelectorAll("option")].map((option) => option.value)).toEqual(["auto", "cpu", "cuda"]);
    expect([...mode.querySelectorAll("option")].map((option) => option.value)).toEqual(["disabled", "dry_run", "live"]);
    expect(screen.getByRole("textbox", { name: "Llm Model" })).toHaveValue("custom/model");
    expect(screen.getByRole("textbox", { name: "Whisper Compute Type" })).toHaveValue("custom-type");
    await user.selectOptions(device, "cuda");
    await user.selectOptions(mode, "disabled");
    for (const save of screen.getAllByRole("button", { name: "Save" })) await user.click(save);
    await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(2));
    const updates = fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT");
    expect(JSON.parse(String(updates[0]?.[1]?.body))).toEqual({
      whisper_device: "cuda", whisper_compute_type: "custom-type", llm_model: "custom/model",
    });
    expect(JSON.parse(String(updates[1]?.[1]?.body))).toEqual({ mode: "disabled", approval_required: true });
  });

  it("CF-REQ-606 preserves unrecognized saved dropdown values without silently changing them", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PUT") return new Response(JSON.stringify({}), { status: 200 });
      return new Response(JSON.stringify({
        providers: [], settings: { publishing: { mode: "future-mode" } },
      }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/settings"]}><App /></MemoryRouter>);
    const mode = await screen.findByRole("combobox", { name: "Mode" });
    expect(mode).toHaveValue("future-mode");
    expect(screen.getByRole("option", { name: "future-mode (unrecognized)" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    const update = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(JSON.parse(String(update?.[1]?.body))).toEqual({ mode: "future-mode" });
  });

  it("CF-REQ-758 CF-REQ-759 saves independent main/evaluation output modes from dropdowns", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PUT") return new Response(JSON.stringify({}), { status: 200 });
      return new Response(JSON.stringify({
        providers: [],
        settings: { environment: { llm_output_mode: "json_schema", llm_output_mode_evaluation: "json_schema" } },
      }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/settings"]}><App /></MemoryRouter>);
    const main = await screen.findByRole("combobox", { name: "Llm Output Mode" });
    const evaluation = screen.getByRole("combobox", { name: "Llm Output Mode Evaluation" });
    expect(main).toHaveValue("json_schema");
    expect(evaluation).toHaveValue("json_schema");
    expect(evaluation).toHaveAccessibleDescription(/Local schema validation and bounded repairs apply in every mode/);
    await user.selectOptions(main, "json_object");
    await user.selectOptions(evaluation, "prompt_json");
    expect(main).toHaveValue("json_object");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(true));
    const update = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(update?.[0]).toBe("/api/settings/environment");
    expect(JSON.parse(String(update?.[1]?.body))).toEqual({
      llm_output_mode: "json_object", llm_output_mode_evaluation: "prompt_json",
    });
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

  it("CF-REQ-613 shows only Clips awaiting approval on the Review Board and removes a decided Clip", async () => {
    let pending = true;
    const clip = {
      id: "clip-9", run_id: "run-9", status: "approved", story_title: "Board fixture", created_at: "2026-10-01T10:00:00Z", cost_total: "0.10",
      social_metadata: { description: "Leaders met to agree a ceasefire.", hashtags: ["Ceasefire", "#WorldNews"], source_attributions: ["Reuters: https://reuters.example/a"] },
      preview: { media_url: "/api/clips/clip-9/media", mime_type: "video/mp4", duration_seconds: 64.4, width: 720, height: 1280, fps: 30, size_bytes: 1024 },
      auto_publish_due_at: null, publications: [{ id: "pub-9", platform: "instagram", status: "awaiting_approval", mode: "live" }],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") { pending = false; return new Response(JSON.stringify({ clip_id: "clip-9", decision: "reject", already_resolved: false }), { status: 200 }); }
      if (String(input) === "/api/clips/pending-approval?limit=20&offset=0") return new Response(JSON.stringify({ items: pending ? [clip] : [] }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/publishes"]}><App /></MemoryRouter>);

    expect(screen.getByRole("link", { name: /Review Board/ })).toHaveAttribute("href", "/publishes");
    const card = await screen.findByRole("article", { name: "Review Board fixture" });
    expect(card).toHaveTextContent("Leaders met to agree a ceasefire.");
    expect(card).toHaveTextContent("#Ceasefire");
    expect(card).toHaveTextContent("#WorldNews");
    expect(card).toHaveTextContent("Instagram · Live");
    expect(card).toHaveTextContent("Awaiting your decision");
    expect(card).toHaveTextContent("64s");
    expect(screen.getByText("1 AWAITING")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reject Board fixture" }));
    expect(await screen.findByText("Board fixture rejected.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/clips/clip-9/approval", expect.objectContaining({ method: "POST", body: JSON.stringify({ decision: "reject" }) }));
    expect(await screen.findByText("Nothing to review. Clips awaiting approval will appear here.")).toBeInTheDocument();
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
    expect(screen.queryByRole("button", { name: "Retry publish" })).not.toBeInTheDocument();
  });

  it("CF-REQ-462 retries failed Publications from the Clip detail", async () => {
    let retried = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/budget") return new Response(JSON.stringify({ currency: "EUR", month_to_date_spend: "1.00", monthly_limit: "30.00", monthly_remaining: "29.00", per_clip_limit: "1.00" }), { status: 200 });
      if (url.endsWith("/publications/retry") && init?.method === "POST") { retried = true; return new Response(JSON.stringify({ retried: ["instagram"], outcome: "published" }), { status: 200 }); }
      return new Response(JSON.stringify({
        id: "clip-9", run_id: "run-9", status: "approved", story_title: "Rally remarks", created_at: "2026-10-11T12:00:00Z", cost_total: "0.10",
        preview: { media_url: "/api/clips/clip-9/media", mime_type: "video/mp4", duration_seconds: 70, width: 720, height: 1280, fps: 30, size_bytes: 4096 },
        publications: [{ id: "pub-ig", platform: "instagram", status: retried ? "published" : "failed", mode: "live", error_code: "publish_failed", error_message: retried ? null : "Publisher HTTP request failed with status 400", latest_metrics: null }],
      }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/clips/clip-9"]}><App /></MemoryRouter>);

    await user.click(await screen.findByRole("button", { name: "Retry publish" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/clips/clip-9/publications/retry", expect.objectContaining({ method: "POST" })));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Retry publish" })).not.toBeInTheDocument());
  });
});