import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
import type { ContentProfileItem, RunSummary } from "./api/client";

const clip = { id: "clip-1", run_id: "run-1", status: "approved", story_title: "News fixture", created_at: "2026-10-01T10:00:00Z", cost_total: "0.1", social_metadata: {}, publications: [{ id: "pub-1", platform: "youtube", status: "published", mode: "live" }], preview: { duration_seconds: 60, width: 720, height: 1280, fps: 30, media_url: "/media/fixture.mp4" } };
const profile: ContentProfileItem["profile"] = { name: "News", is_active: true, category: "general", language: "en", platforms: ["youtube"], duration: { min_seconds: 60, target_seconds: 70, max_seconds: 90 }, output: { width: 720, height: 1280, fps: 30 }, schedule: { enabled: true, local_time: "05:00", timezone: "UTC" }, research: { min_sources: 2, preferred_independent_sources: 3, max_candidate_articles: 20, max_article_age_hours: 24, max_article_bytes: 5000000, story_novelty_window_hours: 48, near_duplicate_threshold: 0.8, max_additional_sources: 5 } };
const run: RunSummary = { run_id: "run-1", trigger: "run_now", status: "queued", attempt: 1, revision_retries_used: 0, cost_total: "0", created_at: "2026-10-01T10:00:00Z" };
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

it.each(["/clips", "/assets"])("CF-REQ-605 CF-REQ-610 %s gracefully handles an unavailable total", async (path) => {
  vi.stubGlobal("fetch", vi.fn(async () => response({ items: [], currency: "EUR" })));
  page(path);
  await screen.findByText(/Page 1 of 1/);
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
});

it("CF-REQ-613 provides Goals workspace tab displaying platform monetization milestones and update button", async () => {
  const goalResponse = {
    goal: {
      id: "monetization",
      title: "Obtain Monetization",
      description: "Milestones and policy restrictions",
      updated_at: "2026-10-01T10:00:00Z",
      platforms: [
        {
          platform: "youtube",
          name: "YouTube",
          program: "YouTube Partner Program (Shorts)",
          status: "in_progress",
          published_clips: 5,
          progress_pct: 25.5,
          metrics: [
            { id: "subscribers", label: "Subscribers", current: 255, target: 1000, unit: "subscribers", pct: 25.5 },
          ],
          restrictions: [
            { id: "ai_disclosure", title: "EU AI Content Disclosure", description: "On-screen AI disclosure tag", status: "compliant" },
          ],
        },
      ],
    },
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    if (String(input) === "/api/goals") return response(goalResponse);
    return response({ currency: "EUR" });
  });
  vi.stubGlobal("fetch", fetchMock);
  page("/goals");
  expect(screen.getByRole("heading", { name: "Obtain Monetization" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Goals" })).toHaveAttribute("href", "/goals");
  await screen.findByRole("article", { name: "YouTube Monetization Goal" });
  expect(screen.getByText("YouTube Partner Program (Shorts)")).toBeInTheDocument();
  expect(screen.getByText("EU AI Content Disclosure")).toBeInTheDocument();
  expect(screen.getByText("Compliant")).toBeInTheDocument();
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
  expect(screen.queryByRole("button", { name: "Schedule" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Provider readiness" })).not.toBeInTheDocument();
  for (const name of ["Environment", "Publishing"]) {
    const button = screen.getByRole("button", { name });
    const content = document.getElementById(button.getAttribute("aria-controls")!);
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(content).not.toBeVisible();
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(content).toBeVisible();
    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "false");
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
  const status = await screen.findByText("Published");
  expect(status).toHaveClass("table-status", "published");
  expect(status.querySelector("span")).toBeInTheDocument();
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
  expect(screen.getByRole("checkbox", { name: "YouTube" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "TikTok" })).not.toBeChecked();
  await user.click(screen.getByRole("checkbox", { name: "Facebook" }));
  await user.click(screen.getByRole("checkbox", { name: "YouTube" }));
  await user.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByText("Content Profile saved.");
  await waitFor(() => expect(screen.getByLabelText("Profile name")).toHaveValue("Weekly"));
  expect(items[1]?.profile.language).toBe("pt");
  expect(items[1]?.profile.platforms).toEqual(["facebook"]);
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

it("CF-REQ-607 shows an active-profile deletion conflict without removing the saved profile", async () => {
  vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === "DELETE" ? response({ error: { code: "active_profile_delete_forbidden", message: "The active profile cannot be deleted." } }, 409) : response({ items: [{ id: "one", name: "Daily", is_active: false, updated_at: run.created_at, profile }] })));
  const user = userEvent.setup(); page("/profile");
  await user.click(await screen.findByRole("button", { name: "Delete profile" }));
  await user.click(screen.getByRole("button", { name: "Confirm delete" }));
  await screen.findByText("The active profile cannot be deleted.");
  expect(screen.getByLabelText("Profile name")).toHaveValue("Daily");
});
