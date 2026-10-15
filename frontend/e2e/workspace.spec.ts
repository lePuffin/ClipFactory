import { test, expect, type Page, type TestInfo } from "@playwright/test";
import type { ContentProfileItem } from "../src/api/client";

const profile = { name: "News", category: "general", language: "en", platforms: ["youtube"], duration: { min_seconds: 60, target_seconds: 70, max_seconds: 90 }, output: { width: 720, height: 1280, fps: 30 }, schedule: { enabled: true, local_time: "05:00", timezone: "UTC" }, research: { min_sources: 2, preferred_independent_sources: 3, max_candidate_articles: 20 } };
const clip = { id: "clip-1", run_id: "run-1", status: "approved", story_title: "Solar breakthrough", cost_total: "0.1", created_at: "2026-10-11T10:00:00Z", social_metadata: { description: "A grounded briefing on new solar research.", hashtags: ["Science"], source_attributions: ["Original source attribution"] }, publications: [{ id: "pub-1", platform: "youtube", status: "published", mode: "live" }], preview: { duration_seconds: 60, width: 720, height: 1280, fps: 30, media_url: "/media/fixture.mp4" } };
/** Clip approve/reject/delete requests captured by the mocked API for the current test. */
let clipDecisions: { id: string; method: string; body: unknown }[] = [];
async function mocks(page: Page) {
  clipDecisions = [];
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
    if (url.pathname === "/api/clips" || url.pathname === "/api/clips/pending-approval") payload = { items: Array.from({ length: url.searchParams.get("offset") === "20" ? 1 : 20 }, (_, i) => ({ ...clip, id: `clip-${i}`, story_title: `Solar breakthrough ${i + 1}`, ...(i === 0 ? { publications: [{ id: "pub-0", platform: "youtube", status: "awaiting_approval", mode: "live" }] } : {}) })), total: 21 };
    const clipAction = /^\/api\/clips\/(clip-\d+)(\/approval)?$/.exec(url.pathname);
    if (clipAction && (method === "POST" || method === "DELETE")) {
      clipDecisions.push({ id: clipAction[1]!, method, body: method === "POST" ? request.postDataJSON() : null });
      return method === "DELETE" ? route.fulfill({ status: 204 }) : route.fulfill({ json: {} });
    }
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

test("CF-REQ-652 queues Run Now and Manual URL while the current Run keeps executing", async ({ page }, info) => {
  const orders: { path: string; body: unknown }[] = [];
  await page.route(/\/api\/runs(?:\/manual-url)?$/, async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    orders.push({ path: new URL(route.request().url()).pathname, body: route.request().postDataJSON() });
    return route.fulfill({ status: 202, json: { run_id: "12345678-1234-1234-1234-123456789abc", status: "queued" } });
  });
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Inspect Run" })).toBeVisible();
  await page.getByLabel("Content Profile", { exact: true }).selectOption("weekly");
  await expect(page.getByRole("button", { name: "Add to queue", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Add to queue", exact: true }).click();
  await expect(page.getByText("Run 12345678 queued", { exact: true })).toBeVisible();
  await page.getByLabel("Manual Source URL").fill("https://news.example/article");
  await page.getByRole("button", { name: "Start Manual URL Run" }).click();
  await expect.poll(() => orders.length).toBe(2);
  expect(orders).toEqual([
    { path: "/api/runs", body: { profile_id: "weekly" } },
    { path: "/api/runs/manual-url", body: { url: "https://news.example/article", profile_id: "weekly" } },
  ]);
  await expect(page.getByRole("link", { name: "Inspect Run" })).toHaveAttribute("href", "/runs/run-1");
  await page.route("**/api/runs/active", (route) => route.fulfill({ status: 204 }));
  await page.reload();
  await expect(page.getByRole("button", { name: "Run Now", exact: true })).toBeVisible();
  await visual(page, info, "queued-orders");
});

test("CF-REQ-214 shows rejected candidate history without loading its discarded video", async ({ page }, info) => {
  await page.route("**/api/clips/clip-1", (route) => route.fulfill({
    json: { ...clip, status: "rejected", publications: [] },
  }));
  let mediaRequests = 0;
  await page.route("**/media/fixture.mp4", (route) => {
    mediaRequests += 1;
    return route.abort();
  });
  await page.goto("/clips/clip-1");
  await expect(page.getByText("Rejected by evaluation. No video is retained; Run and error records remain available.")).toBeVisible();
  await expect(page.locator("video")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Open source Run" })).toHaveAttribute("href", "/runs/run-1");
  expect(mediaRequests).toBe(0);
  await visual(page, info, "discarded-rejected-video");
});

test("CF-REQ-610 aligns platform names, dots and Published or Not Configured labels", async ({ page }, info) => {
  const fixture = { ...clip, publications: [...["facebook", "instagram", "youtube"].map((platform) => ({
    id: platform, platform, status: "published", mode: "live",
  })), { id: "tiktok", platform: "tiktok", status: "failed", mode: "live", error_code: "not_configured" }] };
  await page.route("**/api/clips/clip-1", (route) => route.fulfill({ json: fixture }));
  await page.goto("/clips/clip-1");
  const dots = page.locator(".publication-row .published > span");
  await expect(dots).toHaveCount(3);
  await expect(dots.first()).toHaveCSS("background-color", "rgb(134, 227, 164)");
  await expect(page.locator(".not-configured > span")).toHaveCSS("background-color", "rgb(244, 141, 115)");
  const positions = await page.locator(".publication-row > div:first-child").evaluateAll((rows) => rows.map((row) => {
    const platform = row.querySelector("strong")!.getBoundingClientRect();
    const status = row.querySelector(".table-status")!.getBoundingClientRect();
    const dot = row.querySelector(".table-status > span")!.getBoundingClientRect();
    return { platformX: platform.x, dotX: dot.x, statusX: status.x,
      platformY: platform.y + platform.height / 2, dotY: dot.y + dot.height / 2,
      statusY: status.y + status.height / 2 };
  }));
  for (const position of positions) {
    expect(position.platformX).toBe(positions[0]!.platformX);
    expect(position.dotX).toBe(positions[0]!.dotX);
    expect(position.statusX).toBe(positions[0]!.statusX);
    expect(Math.abs(position.platformY - position.dotY)).toBeLessThan(1);
    expect(Math.abs(position.statusY - position.dotY)).toBeLessThan(1);
  }
  await visual(page, info, "aligned-publications");
});

test("CF-REQ-457 CF-REQ-610 displays compact unconfigured platforms and whole-second Clip durations", async ({ page }, info) => {
  const fixture = {
    ...clip,
    preview: { ...clip.preview, duration_seconds: 69.033333 },
    publications: [
      { id: "pub-1", platform: "youtube", status: "awaiting_approval", mode: "live" },
      { id: "pub-2", platform: "tiktok", status: "failed", mode: "live", error_code: "not_configured", error_message: "tiktok publisher is not configured" },
    ],
  };
  await page.route("**/api/clips?*", (route) => route.fulfill({ json: { items: [fixture], total: 1 } }));
  await page.route("**/api/clips/clip-1", (route) => route.fulfill({ json: fixture }));
  await page.goto("/clips");
  await expect(page.getByText("69 sec", { exact: true })).toBeVisible();
  const missing = page.locator(".publication-row").filter({ has: page.getByText("TikTok", { exact: true }) });
  await expect(missing).toHaveText("TikTokNot Configured");
  await expect(missing.locator(".not-configured")).toHaveCSS("color", "rgb(244, 141, 115)");
  await expect(page.getByText("tiktok publisher is not configured")).toHaveCount(0);
  await page.getByRole("link", { name: "Solar breakthrough", exact: true }).click();
  await expect(page.getByText("69 sec · 720×1280 · 30 fps", { exact: true })).toBeVisible();
  await expect(missing).toHaveText("TikTokNot Configured");
  await visual(page, info, "compact-publications");
});

test("CF-REQ-600 CF-REQ-601 Overview retains Current Run without deprecated agent visuals", async ({ page }, info) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Inspect Run" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Agent Roles" })).toHaveCount(0);
  await expect(page.locator(".persona")).toHaveCount(0);
  await expect(page.getByText("SYSTEM HEALTH")).toHaveCount(0);
  await expect(page.getByText("PUBLISHING GATE")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Recent Runs" })).toHaveCount(0);
  await visual(page, info, "overview");
  await page.route("**/api/runs/active", (route) => route.fulfill({ status: 204 }));
  await page.reload();
  await expect(page.getByText("No active Run", { exact: true })).toBeVisible();
  await expect(page.locator(".persona")).toHaveCount(0);
  await visual(page, info, "overview-idle");
});

test("CF-REQ-600 CF-REQ-605 CF-REQ-610 CF-REQ-613 navigates tabs and paginated Clips with per-Clip approval actions, and Assets", async ({ page }, info) => {
  const decisions = clipDecisions;
  await page.goto("/clips");
  await expect(page.locator(".clip-card")).toHaveCount(20);
  // The former Review Board is folded into Clips: no separate navigation entry remains.
  await expect(page.getByRole("link", { name: "Review Board", exact: true })).toHaveCount(0);
  const awaiting = page.getByRole("button", { name: "Approve Solar breakthrough 1", exact: true });
  await expect(awaiting).toBeVisible();
  await expect(page.getByRole("button", { name: "Reject Solar breakthrough 1", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve Solar breakthrough 2", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Delete Solar breakthrough 2", exact: true })).toBeVisible();
  await awaiting.click();
  await expect.poll(() => decisions.length).toBe(1);
  expect(decisions[0]).toEqual({ id: "clip-0", method: "POST", body: { decision: "approve" } });
  await page.getByRole("button", { name: "Reject Solar breakthrough 1", exact: true }).click();
  await expect.poll(() => decisions.length).toBe(2);
  expect(decisions[1]).toEqual({ id: "clip-0", method: "POST", body: { decision: "reject" } });
  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: "Delete Solar breakthrough 2", exact: true }).click();
  await expect.poll(() => decisions.length).toBe(3);
  expect(decisions[2]).toEqual({ id: "clip-1", method: "DELETE", body: null });
  await expect(page.locator(".table-status.published").first()).toHaveCSS("color", "rgb(134, 227, 164)");
  await expect(page.locator(".table-status.published").first()).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  await expect(page.locator(".table-status.published > span").first()).toHaveCSS("background-color", "rgb(134, 227, 164)");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.locator(".clip-card")).toHaveCount(1);
  await page.getByRole("tab", { name: "Published", exact: true }).click();
  await expect(page.getByText("Page 1 of 2 · 21 Clips", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Published", exact: true }).press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Failed" })).toBeFocused();
  await visual(page, info, "clips");
  await page.getByRole("link", { name: "Assets", exact: true }).click();
  await expect(page.getByText("Page 1 of 2 · 21 Assets")).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("Page 2 of 2 · 21 Assets")).toBeVisible();
  await visual(page, info, "assets");
});

test("CF-REQ-600 CF-REQ-606 collapses and reopens Settings groups with keyboard controls", async ({ page }, info) => {
  await page.goto("/settings");
  const button = page.getByRole("button", { name: "Environment", exact: true });
  await expect(page.getByText("Provider readiness", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Credential status", { exact: true })).toHaveCount(0);
  for (const name of ["Environment", "Publishing"]) await expect(page.getByRole("button", { name, exact: true })).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("button", { name: "Research", exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Llm Model")).toBeHidden();
  await button.focus(); await button.press("Enter");
  await expect(button).toHaveAttribute("aria-expanded", "true");
  await page.getByLabel("Llm Model").fill("writer-draft");
  await button.press("Space");
  await expect(button).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByLabel("Llm Model")).toBeHidden();
  await button.press("Enter");
  await expect(page.getByLabel("Llm Model")).toHaveValue("writer-draft");
  await visual(page, info, "settings");
});

test("CF-REQ-600 CF-REQ-607 manages named profiles, activation and confirmed deletion", async ({ page }, info) => {
  await page.goto("/profile");
  await expect(page.getByRole("button", { name: "Delete profile", exact: true })).toBeDisabled();
  await page.getByLabel("Saved profiles").selectOption("weekly");
  await page.getByLabel("Profile name", { exact: true }).fill("Renamed");
  await page.getByLabel("Language", { exact: true }).fill("pt");
  await expect(page.getByRole("checkbox", { name: "YouTube", exact: true })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: "TikTok", exact: true })).not.toBeChecked();
  await page.getByRole("checkbox", { name: "Facebook", exact: true }).check();
  await page.getByRole("checkbox", { name: "YouTube", exact: true }).uncheck();
  const saving = page.waitForRequest((request) => request.method() === "PUT" && request.url().endsWith("/api/content-profiles/weekly"));
  await page.getByRole("button", { name: "Save", exact: true }).click();
  expect((await saving).postDataJSON().profile.platforms).toEqual(["facebook"]);
  await expect(page.getByRole("option", { name: "Renamed", exact: true })).toHaveCount(1);
  await expect(page.getByRole("checkbox", { name: "Facebook", exact: true })).toBeChecked();
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

test("CF-REQ-100 CF-REQ-607 edits Research feeds on the selected profile only", async ({ page }, info) => {
  await page.goto("/profile");
  await page.getByLabel("Saved profiles").selectOption("weekly");
  const research = page.getByRole("button", { name: "Research", exact: true });
  await expect(research).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("button", { name: "Add feed", exact: true })).toBeHidden();
  await research.focus(); await research.press("Enter");
  await expect(research).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByText(/No feeds configured for this profile/)).toBeVisible();
  await page.getByRole("button", { name: "Add feed", exact: true }).click();
  await expect(page.getByLabel("Feed 1 publisher", { exact: true })).toBeFocused();
  await page.getByLabel("Feed 1 publisher", { exact: true }).fill("Pitch Report");
  await page.getByLabel("Feed 1 URL", { exact: true }).fill("https://pitch.example/rss");
  await research.press("Enter");
  await expect(page.getByLabel("Feed 1 URL", { exact: true })).toBeHidden();
  await research.press("Space");
  await expect(page.getByLabel("Feed 1 URL", { exact: true })).toHaveValue("https://pitch.example/rss");
  await visual(page, info, "profile-research");
  const saved = page.waitForRequest((request) => request.method() === "PUT" && request.url().endsWith("/api/content-profiles/weekly"));
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const body = (await saved).postDataJSON() as { profile: { research: { feeds: string[][] } } };
  expect(body.profile.research.feeds).toEqual([["Pitch Report", "https://pitch.example/rss"]]);
  await page.getByLabel("Saved profiles").selectOption("daily");
  await page.getByRole("button", { name: "Research", exact: true }).click();
  await expect(page.getByText(/No feeds configured for this profile/)).toBeVisible();
});
