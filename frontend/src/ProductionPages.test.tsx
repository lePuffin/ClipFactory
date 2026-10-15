import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

/** Settings groups start collapsed (CF-REQ-606); open the named groups as the owner would. */
async function expandSettings(user: ReturnType<typeof userEvent.setup>, ...names: string[]) {
  for (const name of names) {
    const button = await screen.findByRole("button", { name });
    expect(button).toHaveAttribute("aria-expanded", "false");
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
  }
}

describe("ClipFactory production pages", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("CF-REQ-360 CF-REQ-607 shows the selected profile's stable branding folder and command", async () => {
    const world = { id: "world-id", name: "World", is_active: true, updated_at: "2026-10-13", profile: { name: "World", language: "en", branding_folder: "global-news-english" } };
    const profiles = [
      world,
      { id: "football-id", name: "Football", is_active: false, updated_at: "2026-10-13", profile: { name: "Football", language: "en", branding_folder: "football-news-english" } },
    ];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => new Response(JSON.stringify(
      String(input) === "/api/content-profiles" ? { items: profiles } :
      String(input) === "/api/schedules" ? { items: [] } : world.profile
    ), { status: 200 })));
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/profile"]}><App /></MemoryRouter>);
    const folder = await screen.findByLabelText("Branding folder");
    expect(folder).toHaveValue("branding/global-news-english");
    expect(folder).toHaveAttribute("readonly");
    expect(screen.getByText("uv run clipfactory branding branding/global-news-english")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Saved profiles"), "football-id");
    expect(screen.getByLabelText("Branding folder")).toHaveValue("branding/football-news-english");
    expect(screen.getByText("uv run clipfactory branding branding/football-news-english")).toBeInTheDocument();
    expect(screen.queryByText("uv run clipfactory branding branding/global-news-english")).not.toBeInTheDocument();
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

  it("CF-REQ-606 CF-REQ-753 omits provider readiness and credential presence without secret inputs", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      providers: [
        { provider: "google_tts", credentials_configured: true },
        { provider: "youtube", credentials_configured: false },
      ],
      settings: { publishing: { mode: "dry_run", approval_required: false, auto_publish_after_minutes: 10 } },
    }), { status: 200 })));
    render(<MemoryRouter initialEntries={["/settings"]}><App /></MemoryRouter>);

    await screen.findByRole("button", { name: "Publishing" });
    expect(screen.queryByText("Google Tts")).not.toBeInTheDocument();
    expect(screen.queryByText("Configured")).not.toBeInTheDocument();
    expect(screen.queryByText("Not configured")).not.toBeInTheDocument();
    expect(screen.queryByText(/provider readiness/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Credential status")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/api key|secret|access token/i)).not.toBeInTheDocument();
    expect(screen.queryByText("VALUES NEVER DISPLAYED")).not.toBeInTheDocument();
  });

  it("CF-REQ-550 CF-REQ-551 saves an account prefix without exposing credentials", async () => {
    const profile = {
      name: "Football", category: "sports", language: "en", platforms: ["instagram"],
      duration: { min_seconds: 60, target_seconds: 70, max_seconds: 90 },
      output: { width: 720, height: 1280, fps: 30 },
      schedule: { enabled: true, local_time: "06:00", timezone: "Europe/Lisbon" },
      schedules: [], research: { min_sources: 1, preferred_independent_sources: 3, max_candidate_articles: 20 },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PUT") return new Response("{}", { status: 200 });
      if (String(input) === "/api/content-profiles" || String(input) === "/api/schedules") return new Response('{"items":[]}', { status: 200 });
      return new Response(JSON.stringify(profile), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/profile"]}><App /></MemoryRouter>);
    const prefix = await screen.findByLabelText("Account Env Prefix");
    await user.type(prefix, "football");
    expect(prefix).toHaveValue("FOOTBALL");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(true));
    const saved = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(JSON.parse(String(saved?.[1]?.body))).toEqual({ ...profile, env_prefix: "FOOTBALL" });
    expect(screen.queryByLabelText(/access token|password|secret/i)).not.toBeInTheDocument();
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
    await expandSettings(user, "Environment");
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

  it("CF-REQ-550 CF-REQ-651 adds, edits, disables and deletes independent local schedules", async () => {
    const profile = {
      name: "Football", category: "sports", language: "en",
      schedule: { enabled: true, local_time: "05:00", timezone: "Europe/Lisbon" },
    };
    let rules = [{ rule_id: "rule-1", local_time: "06:00", enabled: true }];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("/api/content-profiles/profile-1/schedules") && init?.method) {
        const payload = init.body ? JSON.parse(String(init.body)) : {};
        if (init.method === "POST") rules.push({ rule_id: "rule-2", ...payload });
        if (init.method === "PUT") rules = rules.map((rule) => url.endsWith(rule.rule_id) ? { ...rule, ...payload } : rule);
        if (init.method === "DELETE") rules = rules.filter((rule) => !url.endsWith(rule.rule_id));
        return init.method === "DELETE" ? new Response(null, { status: 204 }) : new Response("{}", { status: 200 });
      }
      if (url === "/api/schedules") return new Response(JSON.stringify({ items: rules.map((rule) => ({
        ...rule, profile_id: "profile-1", profile_name: "Football", is_active: true,
        schedule: {}, task_id: null, due_at: null, status: "idle",
      })) }), { status: 200 });
      if (url === "/api/content-profiles") return new Response(JSON.stringify({ items: [{
        id: "profile-1", name: "Football", is_active: true, updated_at: "2026-10-13", profile,
      }] }), { status: 200 });
      if (url === "/api/content-profile") return new Response(JSON.stringify(profile), { status: 200 });
      return new Response("{}", { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/profile"]}><App /></MemoryRouter>);
    const time = await screen.findByLabelText("Run time Football 06:00");
    expect(screen.queryByLabelText("Timezone")).not.toBeInTheDocument();
    fireEvent.change(time, { target: { value: "07:30" } });
    await user.click(screen.getByRole("button", { name: "Save time Football 06:00" }));
    await screen.findByLabelText("Run time Football 07:30");
    const update = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(update?.[0]).toBe("/api/content-profiles/profile-1/schedules/rule-1");
    expect(JSON.parse(String(update?.[1]?.body))).toEqual({ local_time: "07:30" });
    fireEvent.change(screen.getByLabelText("New Run time for Football"), { target: { value: "18:00" } });
    await user.click(screen.getByRole("button", { name: "Add schedule for Football" }));
    await screen.findByLabelText("Run time Football 18:00");
    await user.click(screen.getByRole("checkbox", { name: "Enable schedule Football 18:00" }));
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Enable schedule Football 18:00" })).not.toBeChecked());
    await user.click(screen.getByRole("button", { name: "Delete schedule Football 07:30" }));
    await waitFor(() => expect(screen.queryByLabelText("Run time Football 07:30")).not.toBeInTheDocument());
    expect(screen.getByLabelText("Run time Football 18:00")).toBeInTheDocument();
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
    await expandSettings(user, "Environment", "Publishing");
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
    await expandSettings(user, "Publishing");
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
    await expandSettings(user, "Environment");
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
    await expandSettings(user, "Environment");
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
    await expandSettings(user, "Environment");
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

  it("CF-REQ-613 provides individual clip approve, reject, and delete actions on each clip", async () => {
    let deleted = false;
    const clip = {
      id: "clip-9", run_id: "run-9", status: "approved", story_title: "Board fixture", created_at: "2026-10-01T10:00:00Z", cost_total: "0.10",
      social_metadata: { description: "Leaders met to agree a ceasefire.", hashtags: ["Ceasefire", "#WorldNews"], source_attributions: ["Reuters: https://reuters.example/a"] },
      preview: { media_url: "/api/clips/clip-9/media", mime_type: "video/mp4", duration_seconds: 64.4, width: 720, height: 1280, fps: 30, size_bytes: 1024 },
      auto_publish_due_at: null, publications: [{ id: "pub-9", platform: "instagram", status: "awaiting_approval", mode: "live" }],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "DELETE") { deleted = true; return new Response(null, { status: 204 }); }
      if (init?.method === "POST") { return new Response(JSON.stringify({ clip_id: "clip-9", decision: "approve", already_resolved: false }), { status: 200 }); }
      if (String(input).startsWith("/api/clips?")) return new Response(JSON.stringify({ items: deleted ? [] : [clip], total: deleted ? 0 : 1 }), { status: 200 });
      return new Response(JSON.stringify({ currency: "EUR" }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/clips"]}><App /></MemoryRouter>);

    await screen.findByRole("link", { name: "Board fixture" });
    expect(screen.getByRole("button", { name: "Approve Board fixture" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject Board fixture" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete Board fixture" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete Board fixture" })).toHaveTextContent("");
    expect(screen.getByRole("button", { name: "Delete Board fixture" })).toHaveClass("clip-delete");

    await user.click(screen.getByRole("button", { name: "Approve Board fixture" }));
    expect(await screen.findByText("Board fixture approved.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/clips/clip-9/approval", expect.objectContaining({ method: "POST" }));

    await user.click(screen.getByRole("button", { name: "Delete Board fixture" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/clips/clip-9", expect.objectContaining({ method: "DELETE" })));
  });

  it.each(["/clips", "/clips/clip-9", "/clips/approval"])("CF-REQ-610 CF-REQ-613 hides decisions for published Clips at %s", async (route) => {
    const clip = {
      id: "clip-9", run_id: "run-9", status: "approved", story_title: "Published fixture",
      created_at: "2026-10-13T06:00:00Z", cost_total: "0.1", social_metadata: {},
      preview: { media_url: "/api/clips/clip-9/media", duration_seconds: 60, width: 720, height: 1280, fps: 30 },
      publications: [
        { id: "pub-1", platform: "youtube", status: "published", mode: "live" },
        { id: "pub-2", platform: "instagram", status: "awaiting_approval", mode: "live" },
      ],
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return new Response(JSON.stringify(url === "/api/budget" ? { currency: "EUR" } :
        url === "/api/clips/clip-9" ? clip : { items: [clip], total: 1 }), { status: 200 });
    }));
    render(<MemoryRouter initialEntries={[route]}><App /></MemoryRouter>);
    await screen.findByLabelText("Preview Published fixture");
    expect(screen.queryByRole("button", { name: "Approve Published fixture" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject Published fixture" })).not.toBeInTheDocument();
    if (route !== "/clips/approval") {
      expect(screen.getByRole("button", { name: "Delete Published fixture" })).toHaveTextContent("");
    }
  });

  it.each(["/clips", "/clips/clip-9", "/clips/approval"])("CF-REQ-457 CF-REQ-610 shows only red Not Configured without failure details at %s", async (route) => {
    const clip = {
      id: "clip-9", run_id: "run-9", status: "approved", story_title: "Unconfigured fixture",
      created_at: "2026-10-14", cost_total: "0", social_metadata: {},
      preview: { media_url: "/api/clips/clip-9/media", duration_seconds: 69.033333, width: 720, height: 1280, fps: 30 },
      publications: [{ id: "pub-1", platform: "tiktok", status: "failed", mode: "live", error_code: "not_configured", error_message: "tiktok publisher is not configured" }],
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => new Response(JSON.stringify(
      String(input) === "/api/budget" ? { currency: "EUR" } : String(input) === "/api/clips/clip-9" ? clip : { items: [clip], total: 1 }
    ), { status: 200 })));
    render(<MemoryRouter initialEntries={[route]}><App /></MemoryRouter>);
    expect(await screen.findByText(route === "/clips/approval" ? "TikTok · Not Configured" : "Not Configured")).toHaveClass("not-configured");
    expect(screen.queryByText("tiktok publisher is not configured")).not.toBeInTheDocument();
    expect(screen.queryByText("Metrics n/a")).not.toBeInTheDocument();
    expect(screen.queryByText("Awaiting Approval")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve Unconfigured fixture" })).not.toBeInTheDocument();
  });

  it.each([
    ["/clips", 69.033333, "69 sec"], ["/clips/clip-9", 69.033333, "69 sec"],
    ["/clips", 77.4, "77 sec"], ["/clips/clip-9", 77.4, "77 sec"],
    ["/clips", 77.6, "78 sec"],
  ])("CF-REQ-610 rounds duration %s %s to %s", async (route, duration, expected) => {
    const clip = {
      id: "clip-9", run_id: "run-9", status: "approved", story_title: "Duration fixture",
      created_at: "2026-10-14", cost_total: "0", social_metadata: {}, publications: [],
      preview: { media_url: "/api/clips/clip-9/media", duration_seconds: duration, width: 720, height: 1280, fps: 30 },
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => new Response(JSON.stringify(
      String(input) === "/api/budget" ? { currency: "EUR" } : String(input) === "/api/clips/clip-9" ? clip : { items: [clip], total: 1 }
    ), { status: 200 })));
    render(<MemoryRouter initialEntries={[route]}><App /></MemoryRouter>);
    expect(await screen.findByText(route === "/clips" ? expected : `${expected} · 720×1280 · 30 fps`)).toBeInTheDocument();
    expect(screen.queryByText(`${duration} sec`)).not.toBeInTheDocument();
  });

  it("CF-REQ-214 CF-REQ-610 retains rejected Run links without requesting a deleted video", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => new Response(JSON.stringify(
      String(input) === "/api/budget" ? { currency: "EUR" } : { items: [{
        id: "clip-rejected", run_id: "run-rejected", status: "rejected", story_title: "Rejected candidate",
        created_at: "2026-10-15", cost_total: "0", publications: [],
        preview: { media_url: "/api/clips/clip-rejected/media", duration_seconds: 60, width: 720, height: 1280, fps: 30 },
      }], total: 1 }), { status: 200 })));
    const { container } = render(<MemoryRouter initialEntries={["/clips"]}><App /></MemoryRouter>);
    expect(await screen.findByText("Rejected by evaluation. No video is retained; Run and error records remain available.")).toBeInTheDocument();
    expect(container.querySelector("video")).toBeNull();
    expect(screen.getByRole("link", { name: "Rejected candidate" })).toHaveAttribute("href", "/clips/clip-rejected");
  });

  it("CF-REQ-610 reports unavailable Clip media and clears the error when metadata loads", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => new Response(JSON.stringify(
      String(input) === "/api/budget" ? { currency: "EUR" } : { items: [{
        id: "clip-9", run_id: "run-9", status: "approved", story_title: "Missing media",
        created_at: "2026-10-13", cost_total: "0", publications: [],
        preview: { media_url: "/api/clips/clip-9/media", duration_seconds: 60, width: 720, height: 1280, fps: 30 },
      }], total: 1 }), { status: 200 })));
    render(<MemoryRouter initialEntries={["/clips"]}><App /></MemoryRouter>);
    const video = await screen.findByLabelText("Preview Missing media");
    fireEvent.error(video);
    expect(screen.getByRole("alert")).toHaveTextContent("Clip video could not be loaded");
    fireEvent.loadedMetadata(video);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve Missing media" })).not.toBeInTheDocument();
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
    expect(screen.getByText("72 sec · 720×1280 · 30 fps")).toBeInTheDocument();
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