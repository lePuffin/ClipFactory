import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

type Json = Record<string, unknown>;

function research(overrides: Json = {}): Json {
  return {
    max_candidate_articles: 20, min_sources: 1, preferred_independent_sources: 3, max_article_age_hours: 24,
    allowed_publishers: null, blocked_publishers: [],
    feeds: [["World Wire", "https://world.example/rss.xml"], ["Globe Desk", "https://globe.example/feed"]],
    publisher_quality: { "world.example": "high" },
    max_article_bytes: 5000000, story_novelty_window_hours: 48, near_duplicate_threshold: 0.8, max_additional_sources: 5,
    selection_weights: { profile_relevance: 0.3, newsworthiness: 0.25, independent_sources: 0.2, source_quality: 0.15, recency: 0.1 },
    ...overrides,
  };
}

function profile(name: string, researchPolicy: Json): Json {
  return {
    name, category: "general", language: "en", platforms: ["youtube"],
    duration: { min_seconds: 60, target_seconds: 70, max_seconds: 90 },
    output: { width: 720, height: 1280, fps: 30 },
    schedule: { enabled: false, local_time: "05:00", timezone: "UTC" },
    research: researchPolicy,
  };
}

function mockProfiles(items: Json[], saveStatus = 200, saveBody: unknown = undefined) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "PUT") {
      const id = url.split("/").pop();
      const body = JSON.parse(String(init.body)) as Json;
      const existing = items.find((item) => item.id === id) ?? {};
      return new Response(JSON.stringify(saveBody ?? { ...existing, ...body, updated_at: "2026-10-13T12:00:00Z" }), { status: saveStatus });
    }
    if (url === "/api/content-profiles") return new Response(JSON.stringify({ items }), { status: 200 });
    if (url === "/api/schedules") return new Response(JSON.stringify({ items: [] }), { status: 200 });
    return new Response(JSON.stringify(items[0]?.profile ?? {}), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function puts(fetchMock: ReturnType<typeof mockProfiles>) {
  return fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT").map(([url, init]) => ({ url: String(url), body: JSON.parse(String(init?.body)) as { name: string; profile: Json } }));
}

const world = { id: "world-id", name: "World", is_active: true, updated_at: "2026-10-13", profile: profile("World", research()) };
const football = {
  id: "football-id", name: "Football", is_active: false, updated_at: "2026-10-13",
  profile: profile("Football", research({ feeds: [["Pitch Report", "https://pitch.example/rss"]], publisher_quality: {}, story_novelty_window_hours: 24 })),
};

function renderAt(path: string) { return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>); }

/** Research starts collapsed like every other group (CF-REQ-606/607); open it as the owner would. */
async function openResearch(user: ReturnType<typeof userEvent.setup>) {
  const toggle = await screen.findByRole("button", { name: "Research" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  await user.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  return toggle;
}

describe("Content Profile Research and Settings groups", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("CF-REQ-607 CF-REQ-100 shows one dedicated Research section with limits, feeds, publisher tiers, novelty and byte controls", async () => {
    mockProfiles([world, football]);
    const user = userEvent.setup();
    renderAt("/profile");
    const toggle = await screen.findByRole("button", { name: "Research" });
    const section = document.getElementById(toggle.getAttribute("aria-controls")!)!;
    expect(section).not.toBeVisible();
    await openResearch(user);
    expect(section).toBeVisible();
    const scoped = within(section);
    for (const label of ["Min Sources", "Preferred Independent Sources", "Max Candidate Articles", "Max Article Age Hours", "Max Article Bytes", "Story Novelty Window Hours", "Near Duplicate Threshold", "Max Additional Sources", "Profile Relevance"]) {
      expect(scoped.getByLabelText(label)).toBeInTheDocument();
      // Not duplicated by the generic profile editor.
      expect(screen.getAllByLabelText(label)).toHaveLength(1);
    }
    expect(scoped.getByLabelText("Feed 1 publisher")).toHaveValue("World Wire");
    expect(scoped.getByLabelText("Feed 1 URL")).toHaveValue("https://world.example/rss.xml");
    expect(scoped.getByLabelText("Feed 2 publisher")).toHaveValue("Globe Desk");
    expect(scoped.getByLabelText("Publisher 1 hostname")).toHaveValue("world.example");
    expect(scoped.getByRole("combobox", { name: "Publisher 1 tier" })).toHaveValue("high");
    expect(scoped.getByLabelText("Story Novelty Window Hours")).toHaveAttribute("max", "2160");
    expect(screen.queryByDisplayValue("[object Object]")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue(/World Wire, https/)).not.toBeInTheDocument();
  });

  it("CF-REQ-607 CF-REQ-100 edits and saves the selected profile's Research without touching another profile", async () => {
    const fetchMock = mockProfiles([world, football]);
    const user = userEvent.setup();
    renderAt("/profile");
    await user.selectOptions(await screen.findByLabelText("Saved profiles"), "football-id");
    await openResearch(user);
    expect(screen.getByLabelText("Feed 1 publisher")).toHaveValue("Pitch Report");
    expect(screen.queryByLabelText("Feed 2 publisher")).not.toBeInTheDocument();
    await user.clear(screen.getByLabelText("Feed 1 URL"));
    await user.type(screen.getByLabelText("Feed 1 URL"), "https://pitch.example/news.xml");
    await user.click(screen.getByRole("button", { name: "Add feed" }));
    expect(screen.getByLabelText("Feed 2 publisher")).toHaveFocus();
    await user.type(screen.getByLabelText("Feed 2 publisher"), "Terrace Times");
    await user.type(screen.getByLabelText("Feed 2 URL"), "https://terrace.example/rss");
    await user.click(screen.getByRole("button", { name: "Add publisher tier" }));
    await user.type(screen.getByLabelText("Publisher 1 hostname"), "pitch.example");
    await user.selectOptions(screen.getByRole("combobox", { name: "Publisher 1 tier" }), "high");
    await user.clear(screen.getByLabelText("Story Novelty Window Hours")); await user.type(screen.getByLabelText("Story Novelty Window Hours"), "72");
    await user.clear(screen.getByLabelText("Max Article Bytes")); await user.type(screen.getByLabelText("Max Article Bytes"), "2000000");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(puts(fetchMock)).toHaveLength(1));
    const [save] = puts(fetchMock);
    expect(save?.url).toBe("/api/content-profiles/football-id");
    expect(save?.body.profile.research).toEqual(research({
      feeds: [["Pitch Report", "https://pitch.example/news.xml"], ["Terrace Times", "https://terrace.example/rss"]],
      publisher_quality: { "pitch.example": "high" },
      story_novelty_window_hours: 72, max_article_bytes: 2000000,
    }));
    expect(fetchMock.mock.calls.some(([url, init]) => init?.method === "PUT" && String(url).includes("world-id"))).toBe(false);
    expect(fetchMock.mock.calls.some(([url, init]) => init?.method === "PUT" && String(url).startsWith("/api/settings"))).toBe(false);
  });

  it("CF-REQ-607 isolates Research drafts per selected profile", async () => {
    const fetchMock = mockProfiles([world, football]);
    const user = userEvent.setup();
    renderAt("/profile");
    await user.selectOptions(await screen.findByLabelText("Saved profiles"), "football-id");
    await openResearch(user);
    await user.click(screen.getByRole("button", { name: "Remove feed 1" }));
    await user.selectOptions(screen.getByLabelText("Saved profiles"), "world-id");
    await openResearch(user);
    expect(screen.getByLabelText("Feed 1 publisher")).toHaveValue("World Wire");
    expect(screen.getByLabelText("Feed 2 publisher")).toHaveValue("Globe Desk");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(fetchMock)).toHaveLength(1));
    const [save] = puts(fetchMock);
    expect(save?.url).toBe("/api/content-profiles/world-id");
    expect(save?.body.profile.research).toEqual(research());
  });

  it("CF-REQ-607 CF-REQ-100 saves a deliberately empty feed list instead of inheriting feeds", async () => {
    const fetchMock = mockProfiles([world, football]);
    const user = userEvent.setup();
    renderAt("/profile");
    await openResearch(user);
    await user.click(screen.getByRole("button", { name: "Remove feed 2" }));
    await user.click(screen.getByRole("button", { name: "Remove feed 1" }));
    await user.click(screen.getByRole("button", { name: "Remove publisher tier 1" }));
    expect(screen.getByText(/No feeds configured for this profile/)).toHaveTextContent("never inherited from another profile");
    expect(screen.getByText(/No publisher tiers set/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(fetchMock)).toHaveLength(1));
    const research_ = puts(fetchMock)[0]?.body.profile.research;
    expect(research_).toHaveProperty("feeds", []);
    expect(research_).toHaveProperty("publisher_quality", {});
  });

  it("CF-REQ-607 CF-REQ-100 adds a first feed to a profile saved with an empty feed list", async () => {
    const empty = { ...football, profile: profile("Football", research({ feeds: [], publisher_quality: {} })) };
    const fetchMock = mockProfiles([empty]);
    const user = userEvent.setup();
    renderAt("/profile");
    await openResearch(user);
    expect(screen.getByText(/No feeds configured for this profile/)).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Add feed" }));
    await user.type(screen.getByLabelText("Feed 1 publisher"), "Pitch Report");
    await user.type(screen.getByLabelText("Feed 1 URL"), "https://pitch.example/rss");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(fetchMock)).toHaveLength(1));
    expect(puts(fetchMock)[0]?.body.profile.research).toHaveProperty("feeds", [["Pitch Report", "https://pitch.example/rss"]]);
  });

  it("CF-REQ-551 CF-REQ-607 shows labelled Research validation errors and does not submit", async () => {
    const fetchMock = mockProfiles([world]);
    const user = userEvent.setup();
    renderAt("/profile");
    await openResearch(user);
    await user.click(screen.getByRole("button", { name: "Add feed" }));
    await user.type(screen.getByLabelText("Feed 3 URL"), "ftp://files.example/feed");
    await user.clear(screen.getByLabelText("Feed 2 URL")); await user.type(screen.getByLabelText("Feed 2 URL"), "https://reader:secret@globe.example/feed");
    await user.click(screen.getByRole("button", { name: "Add publisher tier" }));
    await user.type(screen.getByLabelText("Publisher 2 hostname"), "world.example");
    await user.clear(screen.getByLabelText("Story Novelty Window Hours")); await user.type(screen.getByLabelText("Story Novelty Window Hours"), "2161");
    await user.clear(screen.getByLabelText("Max Article Bytes")); await user.type(screen.getByLabelText("Max Article Bytes"), "0");
    await user.clear(screen.getByLabelText("Recency")); await user.type(screen.getByLabelText("Recency"), "0.5");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(screen.getByLabelText("Feed 3 publisher")).toHaveAccessibleDescription("Enter the publisher name.");
    expect(screen.getByLabelText("Feed 3 URL")).toHaveAccessibleDescription("Enter an http:// or https:// feed URL.");
    expect(screen.getByLabelText("Feed 3 URL")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Feed 2 URL")).toHaveAccessibleDescription("Feed URLs cannot contain credentials.");
    expect(screen.getByLabelText("Publisher 2 hostname")).toHaveAccessibleDescription("This hostname already has a tier.");
    expect(screen.getByLabelText("Publisher 1 hostname")).not.toHaveAccessibleDescription();
    expect(screen.getByLabelText("Story Novelty Window Hours")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Story novelty window must be a whole number of hours from 0 to 2160.")).toBeInTheDocument();
    expect(screen.getByText("Maximum article size must be a whole number of bytes, at least 1.")).toBeInTheDocument();
    expect(screen.getByText(/Selection weights must add up to 1.0/)).toBeInTheDocument();
    expect(puts(fetchMock)).toHaveLength(0);
  });

  it("CF-REQ-551 CF-REQ-607 applies only backend Research rules and sends values without normalization", async () => {
    const fetchMock = mockProfiles([world]);
    const user = userEvent.setup();
    renderAt("/profile");
    await openResearch(user);
    await user.clear(screen.getByLabelText("Feed 2 URL")); await user.type(screen.getByLabelText("Feed 2 URL"), "https://world.example/rss.xml");
    await user.clear(screen.getByLabelText("Publisher 1 hostname")); await user.type(screen.getByLabelText("Publisher 1 hostname"), "World.Example");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts(fetchMock)).toHaveLength(1));
    const saved = puts(fetchMock)[0]?.body.profile.research;
    expect(saved).toHaveProperty("feeds", [["World Wire", "https://world.example/rss.xml"], ["Globe Desk", "https://world.example/rss.xml"]]);
    expect(saved).toHaveProperty("publisher_quality", { "World.Example": "high" });
  });

  it("CF-REQ-551 CF-REQ-607 shows server Research validation next to the feed field", async () => {
    const error = { error: { code: "profile_validation_failed", message: "Content Profile validation failed", details: { errors: [{ loc: ["body", "profile", "research", "feeds", 0, 1], msg: "URL must use http or https" }] } } };
    mockProfiles([world], 422, error);
    const user = userEvent.setup();
    renderAt("/profile");
    await openResearch(user);
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByLabelText("Feed 1 URL")).toHaveAccessibleDescription("URL must use http or https"));
    expect(screen.getByText("Content Profile validation failed")).toBeInTheDocument();
  });

  it("CF-REQ-607 keeps unsaved Research drafts while the section is collapsed with the keyboard", async () => {
    mockProfiles([world]);
    const user = userEvent.setup();
    renderAt("/profile");
    const toggle = await screen.findByRole("button", { name: "Research" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const publisher = screen.getByLabelText("Feed 1 publisher");
    await user.clear(publisher); await user.type(publisher, "Edited Wire");
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByLabelText("Feed 1 publisher")).not.toBeVisible();
    await user.keyboard(" ");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("Feed 1 publisher")).toHaveValue("Edited Wire");
  });

  it("CF-REQ-606 starts Settings policy and nested groups collapsed, and never offers Research or Provider readiness", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      providers: [{ provider: "youtube", credentials_configured: true }],
      settings: {
        environment: { llm_model: "writer" },
        publishing: { mode: "dry_run" },
        llm: { budgets: { requests_per_minute: 20 } },
        providers: { timeout_seconds: 30 },
        research: { feeds: [["Legacy Wire", "https://legacy.example/rss"]], max_article_bytes: 5000000, story_novelty_window_hours: 48 },
      },
    }), { status: 200 })));
    const user = userEvent.setup();
    renderAt("/settings");
    await screen.findByRole("button", { name: "Providers" });
    expect(screen.getAllByRole("button", { name: "Providers" })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Provider readiness" })).not.toBeInTheDocument();
    const groups = ["Providers", "Environment", "Publishing", "Llm"].map((name) => screen.getByRole("button", { name }));
    for (const button of groups) {
      expect(button).toHaveAttribute("aria-expanded", "false");
      expect(document.getElementById(button.getAttribute("aria-controls")!)).not.toBeVisible();
    }
    expect(screen.queryByText("Configured")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Research" })).not.toBeInTheDocument();
    expect(screen.queryByText("Research")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue(/legacy\.example/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Max Article Bytes")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Llm" }));
    const nested = screen.getByRole("button", { name: "Budgets" });
    expect(nested).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByLabelText("Requests Per Minute")).not.toBeVisible();
    nested.focus();
    await user.keyboard(" ");
    expect(screen.getByLabelText("Requests Per Minute")).toBeVisible();
  });

  it("CF-REQ-606 expands Environment, keeps unsaved edits across collapse and saves them", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PUT") return new Response("{}", { status: 200 });
      return new Response(JSON.stringify({ providers: [], settings: { environment: { llm_model: "writer", wan_fps: 16 } } }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAt("/settings");
    const environment = await screen.findByRole("button", { name: "Environment" });
    expect(environment).toHaveAttribute("aria-expanded", "false");
    await user.click(environment);
    const model = screen.getByRole("textbox", { name: "Llm Model" });
    await user.clear(model); await user.type(model, "writer-2");
    await user.click(environment);
    expect(model).not.toBeVisible();
    await user.click(environment);
    expect(screen.getByRole("textbox", { name: "Llm Model" })).toHaveValue("writer-2");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(true));
    const update = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(update?.[0]).toBe("/api/settings/environment");
    expect(JSON.parse(String(update?.[1]?.body))).toEqual({ llm_model: "writer-2", wan_fps: 16 });
  });
});
