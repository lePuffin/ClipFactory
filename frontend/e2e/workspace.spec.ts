import { test, expect, type Page, type TestInfo } from "@playwright/test";
import type { ContentProfileItem } from "../src/api/client";

const profile = { name: "News", category: "general", language: "en", platforms: ["youtube"], duration: { min_seconds: 60, target_seconds: 70, max_seconds: 90 }, output: { width: 720, height: 1280, fps: 30 }, schedule: { enabled: true, local_time: "05:00", timezone: "UTC" }, research: { min_sources: 2, preferred_independent_sources: 3, max_candidate_articles: 20 } };
const clip = { id: "clip-1", run_id: "run-1", status: "approved", story_title: "Solar breakthrough", cost_total: "0.1", created_at: "2026-10-11T10:00:00Z", social_metadata: { description: "A grounded briefing on new solar research.", hashtags: ["Science"], source_attributions: ["Original source attribution"] }, publications: [{ id: "pub-1", platform: "youtube", status: "published", mode: "live" }], preview: { duration_seconds: 60, width: 720, height: 1280, fps: 30, media_url: "/media/fixture.mp4" } };
async function mocks(page: Page) {
  let profiles: ContentProfileItem[] = [{ id: "daily", name: "Daily", profile, is_active: true, updated_at: "2026-10-11T10:00:00Z" }, { id: "weekly", name: "Weekly", profile, is_active: false, updated_at: "2026-10-11T10:00:00Z" }];
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname !== "127.0.0.1") return route.abort();
    if (!url.pathname.startsWith("/api/")) return route.continue();
    const request = route.request();
    const method = request.method();
    let payload: unknown = { items: [] };
    if (url.pathname === "/api/content-profile") payload = profile;
    if (url.pathname === "/api/content-profiles") {
      if (method === "POST") { const body = request.postDataJSON() as { name: string; profile: ContentProfileItem["profile"] }; const saved = { ...body, id: "new", is_active: false, updated_at: "2026-10-11T10:00:00Z" }; profiles.push(saved); payload = saved; }
      else payload = { items: profiles };
    }
    if (url.pathname.startsWith("/api/content-profiles/")) {
      const id = url.pathname.split("/")[3];
      if (method === "DELETE") { profiles = profiles.filter((item) => item.id !== id); return route.fulfill({ status: 204 }); }
      if (url.pathname.endsWith("/activate")) profiles = profiles.map((item) => ({ ...item, is_active: item.id === id }));
      else { const body = request.postDataJSON() as Partial<ContentProfileItem>; profiles = profiles.map((item) => item.id === id ? { ...item, ...body } : item); }
      payload = profiles.find((item) => item.id === id);
    }
    if (url.pathname === "/api/clips" || url.pathname === "/api/clips/pending-approval") payload = { items: Array.from({ length: url.searchParams.get("offset") === "20" ? 1 : 20 }, (_, i) => ({ ...clip, id: `clip-${i}`, story_title: `Solar breakthrough ${i + 1}` })), total: 21 };
    if (url.pathname === "/api/assets") payload = { items: [], total: 21 };
    if (url.pathname === "/api/settings") payload = { providers: [{ provider: "youtube", credentials_configured: true }], settings: { publishing: { mode: "dry_run" }, environment: { llm_model: "writer" } } };
    if (url.pathname === "/api/runs/active") payload = { run_id: "run-1", status: "running", trigger: "run_now", attempt: 1, revision_retries_used: 0, cost_total: "0", created_at: "2026-10-11T10:00:00Z", current_stage: "extract_claims" };
    if (url.pathname === "/api/runs/run-1/events") payload = { items: [{ sequence: 1, stage: "select_story", type: "stage_completed", message: "Story selected", payload: {}, attempt: 1, created_at: "2026-10-11T10:00:01Z" }, { sequence: 2, stage: "extract_claims", type: "stage_started", message: "Verifying claims", payload: {}, attempt: 1, created_at: "2026-10-11T10:00:02Z" }] };
    if (url.pathname.endsWith("/events/stream")) return route.fulfill({ contentType: "text/event-stream", body: ": connected\n\n" });
    if (url.pathname === "/api/dashboard/summary") payload = { clips_approved: 4, publications: 6, views: 12500, estimated_revenue: "8.40", estimated_revenue_currency: "EUR", next_scheduled_run_at: "2026-10-12T05:00:00Z" };
    if (url.pathname === "/api/budget") payload = { currency: "EUR", month_to_date_spend: "12.40", monthly_limit: "30", monthly_remaining: "17.60", per_clip_limit: "1" };
    await route.fulfill({ json: payload });
  });
}
async function visual(page: Page, info: TestInfo, name: string) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath(`${name}.png`), fullPage: true });
}
test.beforeEach(async ({ page }) => mocks(page));

test("CF-REQ-600 CF-REQ-601 CF-REQ-602 Overview expands Current Run with compact human personas and removes obsolete sections", async ({ page }, info) => {
  await page.goto("/");
  await expect(page.getByRole("article", { name: "Sage: Working" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Scout: Success" })).toBeVisible();
  await expect(page.getByRole("article", { name: "Scribe: Waiting" })).toBeVisible();
  await expect(page.getByText("SYSTEM HEALTH")).toHaveCount(0);
  await expect(page.getByText("PUBLISHING GATE")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Recent Runs" })).toHaveCount(0);
  expect(await page.locator(".persona-body").first().evaluate((node) => getComputedStyle(node).animationName)).toBe("none");
  const personas = page.locator(".persona");
  await expect(personas).toHaveCount(8);
  await expect(page.locator(".persona-grid")).not.toContainText(/eager|focused|committed|happy|sad/i);
  const boxes = await personas.evaluateAll((nodes) => nodes.map((node) => {
    const { x, y, width, height } = node.getBoundingClientRect();
    return { x, y, width, height };
  }));
  expect(new Set(boxes.map((box) => box.y)).size).toBe(info.project.name === "desktop" ? 1 : 4);
  expect(await page.locator(".persona-grid").evaluate((node) => getComputedStyle(node).gridTemplateColumns.split(" ").length)).toBe(info.project.name === "desktop" ? 8 : 2);
  for (const persona of await personas.all()) {
    const gap = await persona.evaluate((node) => node.querySelector("small")!.getBoundingClientRect().top - node.querySelector(".persona-role")!.getBoundingClientRect().bottom);
    expect(gap).toBeLessThanOrEqual(2);
    expect((await persona.locator("svg").boundingBox())!.height).toBeLessThanOrEqual(82);
  }
  await visual(page, info, "overview");
  await page.route("**/api/runs/run-1/events", (route) => route.fulfill({ json: { items: [{ sequence: 3, stage: "extract_claims", type: "stage_failed", message: "Verification failed", payload: {}, attempt: 1, created_at: "2026-10-11T10:00:03Z" }] } }));
  await page.reload();
  await expect(page.getByRole("article", { name: "Sage: Failure" })).toBeVisible();
  await visual(page, info, "persona-failure");
  await page.route("**/api/runs/active", (route) => route.fulfill({ status: 204 }));
  await page.reload();
  await expect(page.getByText("No active Run", { exact: true })).toBeVisible();
  await expect(page.getByRole("article", { name: /: Waiting$/ })).toHaveCount(8);
  await visual(page, info, "persona-idle");
});

test("CF-REQ-600 CF-REQ-605 CF-REQ-610 CF-REQ-613 navigates tabs and paginated Clips, Review Board and Assets", async ({ page }, info) => {
  await page.goto("/clips");
  await expect(page.locator(".clip-card")).toHaveCount(20);
  await expect(page.locator(".table-status.published").first()).toHaveCSS("color", "rgb(134, 227, 164)");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.locator(".clip-card")).toHaveCount(1);
  await page.getByRole("tab", { name: "Published", exact: true }).click();
  await expect(page.getByText("Page 1 of 2 · 21 Clips", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Published", exact: true }).press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Failed" })).toBeFocused();
  await visual(page, info, "clips");
  await page.getByRole("link", { name: "Review Board", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Review Board" })).toBeVisible();
  await expect(page.locator(".review-card")).toHaveCount(20);
  expect(await page.locator(".review-board").evaluate((node) => getComputedStyle(node).gridTemplateColumns.split(" ").length)).toBe(1);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.locator(".review-card")).toHaveCount(1);
  await visual(page, info, "review-board");
  await page.getByRole("link", { name: "Assets", exact: true }).click();
  await expect(page.getByText("Page 1 of 2 · 21 Assets")).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("Page 2 of 2 · 21 Assets")).toBeVisible();
  await visual(page, info, "assets");
});

test("CF-REQ-600 CF-REQ-606 collapses and reopens Settings groups with keyboard controls", async ({ page }, info) => {
  await page.goto("/settings");
  const button = page.getByRole("button", { name: "Environment", exact: true });
  await expect(page.getByLabel("Llm Model")).toBeVisible();
  await button.focus(); await button.press("Enter");
  await expect(button).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByLabel("Llm Model")).toBeHidden();
  await button.press("Space");
  await expect(page.getByLabel("Llm Model")).toBeVisible();
  await visual(page, info, "settings");
});

test("CF-REQ-600 CF-REQ-607 manages named profiles, activation and confirmed deletion", async ({ page }, info) => {
  await page.goto("/profile");
  await expect(page.getByRole("button", { name: "Delete profile", exact: true })).toBeDisabled();
  await page.getByLabel("Saved profiles").selectOption("weekly");
  await page.getByLabel("Profile name", { exact: true }).fill("Renamed");
  await page.getByLabel("Language", { exact: true }).fill("pt");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("option", { name: "Renamed", exact: true })).toHaveCount(1);
  await page.getByLabel("New profile name", { exact: true }).fill("Special");
  await page.getByRole("button", { name: "Save as new profile", exact: true }).click();
  await expect(page.getByLabel("Profile name", { exact: true })).toHaveValue("Special");
  await page.getByRole("button", { name: "Activate selected profile" }).click();
  await expect(page.getByText("Active profile", { exact: true })).toBeVisible();
  await page.getByLabel("Saved profiles").selectOption("weekly");
  await page.getByRole("button", { name: "Delete profile", exact: true }).click();
  await expect(page.getByRole("alertdialog")).toBeVisible();
  await page.getByRole("button", { name: "Confirm delete", exact: true }).click();
  await expect(page.getByRole("option", { name: "Renamed", exact: true })).toHaveCount(0);
  await expect(page.getByText("Active profile", { exact: true })).toBeVisible();
  await visual(page, info, "profile");
});
