import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
import { AgentPersonas } from "./AgentPersonas";
import type { ContentProfileItem, RunEvent, RunSummary } from "./api/client";

const clip = { id: "clip-1", run_id: "run-1", status: "approved", story_title: "News fixture", created_at: "2026-10-01T10:00:00Z", cost_total: "0.1", social_metadata: {}, publications: [{ id: "pub-1", platform: "youtube", status: "published", mode: "live" }], preview: { duration_seconds: 60, width: 720, height: 1280, fps: 30, media_url: "/media/fixture.mp4" } };
const profile = { name: "News", category: "general", language: "en", platforms: ["youtube"], duration: { min_seconds: 60, target_seconds: 70, max_seconds: 90 }, output: { width: 720, height: 1280, fps: 30 }, schedule: { local_time: "05:00", timezone: "UTC" }, research: { min_sources: 2, preferred_independent_sources: 3, max_candidate_articles: 20 } };
const run: RunSummary = { run_id: "run-1", trigger: "run_now", status: "queued", attempt: 1, revision_retries_used: 0, cost_total: "0", created_at: "2026-10-01T10:00:00Z" };
function event(sequence: number, stage: string, type: string): RunEvent { return { sequence, stage, type, attempt: 1, level: "info", message: type, payload: {}, created_at: run.created_at }; }
function response(value: unknown, status = 200) { return new Response(status === 204 ? null : JSON.stringify(value), { status }); }
function page(path: string) { return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>); }
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("CF-REQ-610 paginates Clips by 20 and resets offset across All, Published and Failed tabs", async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith("/api/clips?")) return response({ items: [clip], total: 41 });
    return response({ currency: "EUR" });
  });
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup(); page("/clips");
  await screen.findByText("News fixture");
  expect(screen.getByRole("tab", { name: "All" })).toHaveAttribute("aria-selected", "true");
  await user.click(screen.getByRole("button", { name: "Next" }));
  await screen.findByText("Page 2 of 3 · 41 Clips");
  expect(fetchMock).toHaveBeenCalledWith("/api/clips?limit=20&offset=20&filter=all", expect.anything());
  await user.click(screen.getByRole("button", { name: "Previous" }));
  await screen.findByText("Page 1 of 3 · 41 Clips");
  await user.click(screen.getByRole("tab", { name: "Published" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/clips?limit=20&offset=0&filter=published", expect.anything()));
  await screen.findByText("News fixture");
  await user.click(screen.getByRole("button", { name: "Next" }));
  await screen.findByText("Page 2 of 3 · 41 Clips");
  await user.click(screen.getByRole("tab", { name: "Failed" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/clips?limit=20&offset=0&filter=failed", expect.anything()));
  await screen.findByText("Page 1 of 3 · 41 Clips");
  expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
});

it.each(["/clips", "/publishes", "/assets"])("CF-REQ-605 CF-REQ-610 CF-REQ-613 %s gracefully handles an unavailable total", async (path) => {
  vi.stubGlobal("fetch", vi.fn(async () => response({ items: [], currency: "EUR" })));
  page(path);
  await screen.findByText(/Page 1 of 1/);
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
});

it("CF-REQ-613 names the workspace Review Board and paginates one Clip per row", async () => {
  const fetchMock = vi.fn(async () => response({ items: [clip], total: 21 }));
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup(); page("/publishes");
  expect(screen.getByRole("heading", { name: "Review Board" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Review Board" })).toHaveAttribute("href", "/publishes");
  await screen.findByRole("article", { name: "Review News fixture" });
  expect(screen.getByText("21 AWAITING")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Next" }));
  await screen.findByText(/Page 2 of 2/);
  expect(fetchMock).toHaveBeenCalledWith("/api/clips/pending-approval?limit=20&offset=20", expect.anything());
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
});

it("CF-REQ-605 paginates Assets by 20 and resets the page on status changes", async () => {
  const fetchMock = vi.fn(async () => response({ items: [], total: 25 }));
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup(); page("/assets");
  await screen.findByText(/Page 1 of 2/);
  await user.click(screen.getByRole("button", { name: "Next" }));
  await screen.findByText(/Page 2 of 2/);
  expect(fetchMock).toHaveBeenCalledWith("/api/assets?limit=20&offset=20&status=active", expect.anything());
  await user.click(screen.getByRole("button", { name: "retired" }));
  await screen.findByText(/Page 1 of 2/);
  expect(fetchMock).toHaveBeenCalledWith("/api/assets?limit=20&offset=0&status=retired", expect.anything());
});

it("CF-REQ-606 collapses settings groups using labelled buttons and aria-expanded", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => response(String(input) === "/api/settings" ? { providers: [], settings: { environment: { llm_model: "writer" }, publishing: { mode: "dry_run" } } } : {})));
  const user = userEvent.setup(); page("/settings");
  await screen.findByLabelText("Llm Model");
  for (const name of ["Environment", "Publishing", "Providers", "Schedule"]) {
    const button = screen.getByRole("button", { name });
    expect(button).toHaveAttribute("aria-expanded", "true");
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "false");
    const content = document.getElementById(button.getAttribute("aria-controls")!);
    expect(content).not.toBeVisible();
    await user.click(button);
    expect(content).toBeVisible();
  }
});

it("CF-REQ-610 uses the green Published status class on approved Clips and detail Publications", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => response(String(input).includes("/api/clips?") ? { items: [clip] } : String(input).includes("/api/clips/") ? clip : { currency: "EUR" })));
  const user = userEvent.setup(); page("/clips");
  await screen.findByRole("link", { name: "News fixture" });
  expect(screen.getByText("Published", { selector: ".table-status" })).toHaveClass("published");
  await user.click(screen.getByRole("link", { name: "News fixture" }));
  expect(await screen.findByText("Published")).toHaveClass("table-status", "published");
});

it("CF-REQ-607 selects, renames, saves content, creates, activates and confirms deletion of profiles", async () => {
  let items: ContentProfileItem[] = [{ id: "one", name: "Daily", is_active: true, updated_at: run.created_at, profile }, { id: "two", name: "Weekend", is_active: false, updated_at: run.created_at, profile }];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/content-profile") return response(profile);
    if (!init?.method) return response({ items });
    if (init.method === "POST" && url === "/api/content-profiles") {
      const body = JSON.parse(String(init.body)) as { name: string; profile: ContentProfileItem["profile"] };
      const created = { ...body, id: "three", is_active: false, updated_at: run.created_at };
      items = [...items, created]; return response(created, 201);
    }
    const id = url.split("/")[3];
    if (init.method === "DELETE") { items = items.filter((item) => item.id !== id); return response(null, 204); }
    if (url.endsWith("/activate")) items = items.map((item) => ({ ...item, is_active: item.id === id }));
    else items = items.map((item) => item.id === id ? { ...item, ...JSON.parse(String(init.body)) as Partial<ContentProfileItem> } : item);
    return response(items.find((item) => item.id === id));
  });
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup(); page("/profile");
  await screen.findByLabelText("Saved profiles");
  expect(screen.getByRole("button", { name: "Delete profile" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Activate selected profile" })).toBeDisabled();
  await user.selectOptions(screen.getByLabelText("Saved profiles"), "two");
  await user.clear(screen.getByLabelText("Profile name")); await user.type(screen.getByLabelText("Profile name"), "Weekly");
  await user.clear(screen.getByLabelText("Language")); await user.type(screen.getByLabelText("Language"), "pt");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByText("Content Profile saved.");
  await waitFor(() => expect(screen.getByLabelText("Profile name")).toHaveValue("Weekly"));
  expect(items[1]?.profile.language).toBe("pt");
  await user.type(screen.getByLabelText("New profile name"), "Special");
  await user.click(screen.getByRole("button", { name: "Save as new profile" }));
  await waitFor(() => expect(screen.getByLabelText("Profile name")).toHaveValue("Special"));
  expect(items[2]?.profile.language).toBe("pt");
  await user.click(screen.getByRole("button", { name: "Activate selected profile" }));
  await screen.findByText(/Content Profile activated/);
  await screen.findByText("Active profile");
  expect(screen.getByRole("button", { name: "Delete profile" })).toBeDisabled();
  await user.selectOptions(screen.getByLabelText("Saved profiles"), "two");
  await user.click(screen.getByRole("button", { name: "Delete profile" }));
  expect(screen.getByRole("alertdialog")).toHaveTextContent("Delete Weekly?");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(items).toHaveLength(3);
  await user.click(screen.getByRole("button", { name: "Delete profile" }));
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Confirm delete" }));
  await screen.findByText("Content Profile deleted.");
  await screen.findByText("Active profile");
  expect(screen.queryByRole("option", { name: "Weekly" })).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith("/api/content-profiles/two", expect.objectContaining({ method: "DELETE" }));
});

it("CF-REQ-607 reports name conflicts without discarding the profile draft", async () => {
  vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === "POST" ? response({ error: { code: "profile_name_conflict", message: "A profile with this name already exists." } }, 409) : response({ items: [{ id: "one", name: "Daily", is_active: true, updated_at: run.created_at, profile }] })));
  const user = userEvent.setup(); page("/profile");
  await screen.findByLabelText("New profile name");
  await user.type(screen.getByLabelText("New profile name"), "Daily");
  await user.click(screen.getByRole("button", { name: "Save as new profile" }));
  await screen.findByText("A profile with this name already exists.");
  expect(screen.getByLabelText("New profile name")).toHaveValue("Daily");
});

it.each([
  ["waiting", { ...run }, []],
  ["working", { ...run, status: "running", current_stage: "write_script" }, [event(1, "write_script", "stage_started")]],
  ["success", { ...run, status: "running", current_stage: "plan_visuals" }, [event(1, "plan_visuals", "stage_completed")]],
  ["failure", { ...run, status: "failed", failure_stage: "write_script" }, [event(1, "write_script", "stage_failed")]],
] as const)("CF-REQ-601 CF-REQ-602 Scribe has a distinct %s persona mood", (mood, summary, events) => {
  render(<AgentPersonas run={summary} events={[...events]} />);
  const persona = screen.getByRole("article", { name: /^Scribe:/ });
  expect(persona).toHaveClass(mood);
  expect(persona.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  expect(persona).toHaveTextContent("Script & visual plan");
  const state = { waiting: "Waiting", working: "Working", success: "Success", failure: "Failure" }[mood];
  expect(persona).toHaveAccessibleName(`Scribe: ${state}`);
  expect(persona.querySelector("small")).toHaveTextContent(new RegExp(`^${state}$`));
  expect(persona.querySelector(".persona-role")?.nextElementSibling).toBe(persona.querySelector("small"));
  expect(persona).not.toHaveTextContent(/eager|focused|committed|happy|sad/i);
  expect(persona.querySelector("svg")).toHaveAttribute("focusable", "false");
});

it("CF-REQ-601 CF-REQ-602 updates persona moods on stage events and resets stale failures on continuation", () => {
  const { rerender } = render(<AgentPersonas run={{ ...run, status: "running", current_stage: "select_assets" }} events={[event(1, "write_script", "stage_completed"), event(2, "select_assets", "stage_started")]} />);
  expect(screen.getByRole("article", { name: /^Scribe:/ })).toHaveClass("success");
  expect(screen.getByRole("article", { name: /^Pixel:/ })).toHaveClass("working");
  rerender(<AgentPersonas run={{ ...run, status: "running", current_stage: "select_assets" }} events={[event(1, "select_assets", "stage_failed"), event(2, "select_assets", "run_resumed"), event(3, "select_assets", "stage_started")]} />);
  expect(screen.getByRole("article", { name: /^Pixel:/ })).toHaveClass("working");
  expect(screen.getByRole("article", { name: /^Relay:/ })).toHaveClass("waiting");
  rerender(<AgentPersonas run={run} events={[event(4, "publish", "run_completed")]} />);
  expect(screen.getAllByRole("article").every((item) => item.classList.contains("success"))).toBe(true);
});

it("CF-REQ-601 shows every persona eagerly waiting when no Run is active", () => {
  render(<AgentPersonas run={null} events={[]} />);
  const personas = screen.getAllByRole("article");
  expect(personas).toHaveLength(8);
  expect(personas.every((item) => item.classList.contains("waiting"))).toBe(true);
  for (const name of ["Scout", "Sage", "Scribe", "Pixel", "Echo", "Frame", "Guard", "Relay"]) {
    expect(screen.getByRole("article", { name: `${name}: Waiting` })).toBeInTheDocument();
  }
  expect(new Set(personas.map((item) => item.querySelector("svg")?.innerHTML)).size).toBe(8);
  expect(screen.getByRole("region", { name: "Agent Roles" })).not.toHaveTextContent(/eager|focused|committed|happy|sad/i);
});

it.each([
  ["Scout", "research"], ["Scout", "ingest_url"], ["Scout", "cluster_stories"], ["Scout", "select_story"],
  ["Sage", "gather_sources"], ["Sage", "extract_claims"], ["Sage", "build_story_package"],
  ["Scribe", "write_script"], ["Scribe", "plan_visuals"], ["Pixel", "select_assets"],
  ["Echo", "generate_narration"], ["Echo", "transcribe_narration"], ["Echo", "build_captions"],
  ["Frame", "compose_clip"], ["Guard", "validate_clip"], ["Guard", "evaluate_clip"], ["Guard", "plan_retry"], ["Relay", "publish"],
])("CF-REQ-601 CF-REQ-602 maps %s to the canonical %s stage", (name, stage) => {
  const { rerender } = render(<AgentPersonas run={{ ...run, status: "running", current_stage: stage }} events={[event(1, stage, "stage_started")]} />);
  expect(screen.getByRole("article", { name: new RegExp(`^${name}:`) })).toHaveClass("working");
  rerender(<AgentPersonas run={{ ...run, status: "running", current_stage: stage }} events={[event(1, stage, "stage_started"), event(2, stage, "stage_skipped")]} />);
  expect(screen.getByRole("article", { name: new RegExp(`^${name}:`) })).toHaveClass("success");
});

it("CF-REQ-607 shows an active-profile deletion conflict without removing the saved profile", async () => {
  vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === "DELETE" ? response({ error: { code: "active_profile_delete_forbidden", message: "The active profile cannot be deleted." } }, 409) : response({ items: [{ id: "one", name: "Daily", is_active: false, updated_at: run.created_at, profile }] })));
  const user = userEvent.setup(); page("/profile");
  await user.click(await screen.findByRole("button", { name: "Delete profile" }));
  await user.click(screen.getByRole("button", { name: "Confirm delete" }));
  await screen.findByText("The active profile cannot be deleted.");
  expect(screen.getByLabelText("Profile name")).toHaveValue("Daily");
});

it("CF-REQ-601 expresses all four moods through distinct face and pose art without mood labels", () => {
  const { rerender } = render(<AgentPersonas run={null} events={[]} />);
  const art = () => screen.getByRole("article", { name: /^Scribe:/ }).querySelector("svg")!.innerHTML;
  const portraits = [art()];
  for (const type of ["stage_started", "stage_completed", "stage_failed"]) {
    rerender(<AgentPersonas run={{ ...run, status: "running", current_stage: "write_script" }} events={[event(1, "write_script", type)]} />);
    portraits.push(art());
  }
  expect(new Set(portraits).size).toBe(4);
});

it("CF-REQ-601 CF-REQ-602 terminal failure marks the failing role and keeps handed-off and untouched states", () => {
  render(<AgentPersonas run={{ ...run, status: "running", current_stage: "write_script" }} events={[event(1, "research", "stage_completed"), event(2, "write_script", "stage_started"), event(3, "select_assets", "run_failed")]} />);
  expect(screen.getByRole("article", { name: "Scout: Success" })).toHaveClass("success");
  expect(screen.getByRole("article", { name: "Scribe: Success" })).toHaveClass("success");
  expect(screen.getByRole("article", { name: "Pixel: Failure" })).toHaveClass("failure");
  expect(screen.getByRole("article", { name: "Relay: Waiting" })).toHaveClass("waiting");
});

it("CF-REQ-601 CF-REQ-602 shows Success for roles whose Stages handed off when only stage_started events exist", () => {
  const started = ["research", "select_story", "gather_sources", "write_script", "plan_visuals", "select_assets"].map((stage, index) => event(index + 1, stage, "stage_started"));
  render(<AgentPersonas run={{ ...run, status: "running", current_stage: "select_assets" }} events={started} />);
  for (const name of ["Scout", "Sage", "Scribe"]) expect(screen.getByRole("article", { name: `${name}: Success` })).toHaveClass("success");
  expect(screen.getByRole("article", { name: "Pixel: Working" })).toHaveClass("working");
  for (const name of ["Echo", "Frame", "Guard", "Relay"]) expect(screen.getByRole("article", { name: `${name}: Waiting` })).toHaveClass("waiting");
});
