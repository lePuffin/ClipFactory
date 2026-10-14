import type { components } from "./api/schema";
import { isEditorObject, type EditorObject, type EditorValue } from "./editorValue";

type ResearchPolicy = components["schemas"]["ResearchPolicy"];
/** A research feed as stored on ContentProfile.research.feeds: `[publisher, url]`. */
export type FeedPair = NonNullable<ResearchPolicy["feeds"]>[number];
type PublisherTier = NonNullable<ResearchPolicy["publisher_quality"]>[string];
/** Editable row for ContentProfile.research.publisher_quality (`hostname → tier`); unknown saved tiers stay visible. */
export type QualityRow = { domain: string; tier: string };

export const qualityTiers: readonly { value: PublisherTier; label: string }[] = [
  { value: "high", label: "High" },
  { value: "standard", label: "Standard" },
  { value: "low", label: "Low" },
  { value: "blocked", label: "Blocked" },
];

/** Keys rendered by dedicated controls instead of the generic research limits editor. */
export const researchListKeys = ["feeds", "publisher_quality"] as const;

export function readFeeds(research: EditorValue | undefined): FeedPair[] {
  if (!isEditorObject(research) || !Array.isArray(research.feeds)) return [];
  return research.feeds.map((feed) => Array.isArray(feed) ? [stringOf(feed[0]), stringOf(feed[1])] : ["", ""]);
}

export function readQualityRows(research: EditorValue | undefined): QualityRow[] {
  if (!isEditorObject(research) || !isEditorObject(research.publisher_quality)) return [];
  return Object.entries(research.publisher_quality).map(([domain, tier]) => ({ domain, tier: stringOf(tier) }));
}

/**
 * Returns the profile to submit: the draft with publisher quality rows folded back into
 * `research.publisher_quality`. Hostnames are sent exactly as typed (no normalization). The
 * mapping is only written when the profile already had one or the owner added rows, so
 * unrelated saves do not introduce new keys.
 */
export function composeProfile(draft: EditorObject, rows: QualityRow[], hadQuality: boolean): EditorObject {
  if (!hadQuality && !rows.length) return draft;
  const research = isEditorObject(draft.research) ? draft.research : {};
  const publisherQuality: EditorObject = Object.fromEntries(rows.map((row) => [row.domain, row.tier]));
  return { ...draft, research: { ...research, publisher_quality: publisherQuality } };
}

/**
 * Client-side research checks mirroring the backend ResearchControls/ResearchPolicy validators
 * exactly (server remains authoritative). Error keys match server `loc` paths without `profile.`.
 */
export function validateResearch(research: EditorValue | undefined, rows: QualityRow[]): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!isEditorObject(research)) research = {};
  readFeeds(research).forEach(([publisher, url], index) => {
    // Backend: publisher must not be blank after stripping whitespace.
    if (!publisher.trim()) errors[`research.feeds.${index}.0`] = "Enter the publisher name.";
    // Backend: pydantic HttpUrl (http/https with a host, at most 2083 characters) without credentials.
    if (!isHttpUrl(url)) errors[`research.feeds.${index}.1`] = "Enter an http:// or https:// feed URL.";
    else if (hasCredentials(url)) errors[`research.feeds.${index}.1`] = "Feed URLs cannot contain credentials.";
  });
  // A JSON object cannot hold the same hostname twice; flag it instead of silently dropping a row.
  const seenDomains = new Set<string>();
  rows.forEach((row, index) => {
    if (seenDomains.has(row.domain)) errors[`research.publisher_quality.${index}`] = "This hostname already has a tier.";
    else if (!qualityTiers.some((tier) => tier.value === row.tier)) errors[`research.publisher_quality.${index}`] = "Choose High, Standard, Low or Blocked.";
    seenDomains.add(row.domain);
  });
  if ("max_article_bytes" in research) {
    const bytes = research.max_article_bytes;
    if (typeof bytes !== "number" || !Number.isInteger(bytes) || bytes < 1) errors["research.max_article_bytes"] = "Maximum article size must be a whole number of bytes, at least 1.";
  }
  if ("story_novelty_window_hours" in research) {
    const hours = research.story_novelty_window_hours;
    if (typeof hours !== "number" || !Number.isInteger(hours) || hours < 0 || hours > 2160) errors["research.story_novelty_window_hours"] = "Story novelty window must be a whole number of hours from 0 to 2160.";
  }
  if ("near_duplicate_threshold" in research) {
    const threshold = research.near_duplicate_threshold;
    if (typeof threshold !== "number" || !Number.isFinite(threshold) || threshold < 0.5 || threshold > 1) errors["research.near_duplicate_threshold"] = "Near-duplicate threshold must be between 0.5 and 1.0.";
  }
  if ("max_additional_sources" in research) {
    const sources = research.max_additional_sources;
    if (typeof sources !== "number" || !Number.isInteger(sources) || sources < 0 || sources > 20) errors["research.max_additional_sources"] = "Additional Sources must be a whole number from 0 to 20.";
  }
  if (isEditorObject(research.selection_weights)) {
    const weights = Object.entries(research.selection_weights);
    weights.forEach(([key, weight]) => {
      if (typeof weight !== "number" || !Number.isFinite(weight) || weight < 0 || weight > 1) errors[`research.selection_weights.${key}`] = "Each weight must be between 0 and 1.";
    });
    const total = weights.reduce((sum, [, weight]) => sum + (typeof weight === "number" ? weight : 0), 0);
    if (weights.length && Math.abs(total - 1) > 1e-9) errors["research.selection_weights"] = `Selection weights must add up to 1.0 (currently ${Number(total.toFixed(4))}).`;
  }
  return errors;
}

function isHttpUrl(value: string): boolean {
  if (!value || value.length > 2083) return false;
  try {
    const url = new URL(value);
    return (url.protocol === "http:" || url.protocol === "https:") && Boolean(url.hostname);
  } catch {
    return false;
  }
}

function hasCredentials(value: string): boolean {
  const url = new URL(value);
  return Boolean(url.username || url.password);
}

function stringOf(value: EditorValue | undefined): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}
