import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { Collapsible } from "./Collapsible";
import type { EditorObject } from "./editorValue";
import { qualityTiers, readFeeds, type FeedPair, type QualityRow } from "./researchPolicy";

type Errors = Record<string, string>;

/**
 * Dedicated Research section of the selected Content Profile (CF-REQ-607).
 * `limits` is the generic editor for scalar research fields; feeds and publisher tiers
 * get list controls here. Content stays mounted while collapsed so drafts survive.
 */
export function ProfileResearchSection({ research, onChange, qualityRows, onQualityRowsChange, errors, limits }: {
  research: EditorObject;
  onChange: (research: EditorObject) => void;
  qualityRows: QualityRow[];
  onQualityRowsChange: (rows: QualityRow[]) => void;
  errors: Errors;
  limits: ReactNode;
}) {
  return <Collapsible title="Research" level={3} className="settings-group research-group">
    <div className="research-body">
      <p className="field-help">Research limits, RSS feeds and publisher tiers apply only to this Content Profile and are saved with it.</p>
      {limits}
      {["research", "research.selection_weights"].map((path) => errors[path] && <p key={path} className="field-error" role="alert">{errors[path]}</p>)}
      <FeedListEditor feeds={readFeeds(research)} onChange={(feeds) => onChange({ ...research, feeds })} errors={errors} />
      <PublisherQualityEditor rows={qualityRows} onChange={onQualityRowsChange} errors={errors} />
    </div>
  </Collapsible>;
}

function FeedListEditor({ feeds, onChange, errors }: { feeds: FeedPair[]; onChange: (feeds: FeedPair[]) => void; errors: Errors }) {
  const [focusIndex, setFocusIndex] = useState<number | null>(null);
  useEffect(() => {
    if (focusIndex === null) return;
    document.getElementById(`research-feed-${focusIndex}-publisher`)?.focus();
    setFocusIndex(null);
  }, [focusIndex]);
  const update = (index: number, field: 0 | 1, value: string) => onChange(feeds.map((feed, position) => position === index ? (field === 0 ? [value, feed[1]] : [feed[0], value]) : feed));
  return <fieldset className="research-list" aria-describedby="research-feeds-help">
    <legend>Feeds</legend>
    <small id="research-feeds-help">RSS or Atom feeds this profile researches. Each feed needs a publisher name and an http(s) URL.</small>
    {feeds.length === 0 && <p className="empty-state research-empty" role="status">No feeds configured for this profile. Automated research for this profile fails with no_candidates until a feed is added; feeds are never inherited from another profile.</p>}
    {feeds.map(([publisher, url], index) => {
      const base = `research-feed-${index}`;
      const publisherError = errors[`research.feeds.${index}.0`];
      const urlError = errors[`research.feeds.${index}.1`] ?? errors[`research.feeds.${index}`];
      return <div className="research-row" key={index}>
        <div className="field">
          <label htmlFor={`${base}-publisher`}>Feed {index + 1} publisher</label>
          <input id={`${base}-publisher`} value={publisher} aria-invalid={Boolean(publisherError)} aria-describedby={publisherError ? `${base}-publisher-error` : undefined} onChange={(event) => update(index, 0, event.target.value)} />
          {publisherError && <span id={`${base}-publisher-error`} className="field-error" role="alert">{publisherError}</span>}
        </div>
        <div className="field">
          <label htmlFor={`${base}-url`}>Feed {index + 1} URL</label>
          <input id={`${base}-url`} type="url" inputMode="url" value={url} placeholder="https://" aria-invalid={Boolean(urlError)} aria-describedby={urlError ? `${base}-url-error` : undefined} onChange={(event) => update(index, 1, event.target.value)} />
          {urlError && <span id={`${base}-url-error`} className="field-error" role="alert">{urlError}</span>}
        </div>
        <button type="button" className="ghost-button research-remove" aria-label={`Remove feed ${index + 1}`} title={`Remove feed ${index + 1}`} onClick={() => onChange(feeds.filter((_, position) => position !== index))}><Trash2 size={14} aria-hidden="true" />Remove</button>
      </div>;
    })}
    {errors["research.feeds"] && <span className="field-error" role="alert">{errors["research.feeds"]}</span>}
    <button type="button" className="ghost-button" onClick={() => { onChange([...feeds, ["", ""]]); setFocusIndex(feeds.length); }}><Plus size={14} aria-hidden="true" />Add feed</button>
  </fieldset>;
}

function PublisherQualityEditor({ rows, onChange, errors }: { rows: QualityRow[]; onChange: (rows: QualityRow[]) => void; errors: Errors }) {
  const [focusIndex, setFocusIndex] = useState<number | null>(null);
  useEffect(() => {
    if (focusIndex === null) return;
    document.getElementById(`research-quality-${focusIndex}-domain`)?.focus();
    setFocusIndex(null);
  }, [focusIndex]);
  const update = (index: number, change: Partial<QualityRow>) => onChange(rows.map((row, position) => position === index ? { ...row, ...change } : row));
  return <fieldset className="research-list" aria-describedby="research-quality-help">
    <legend>Publisher quality</legend>
    <small id="research-quality-help">Tier by article hostname exactly as it appears in article URLs (for example www.bbc.co.uk). Unlisted hostnames are Standard; Blocked hostnames are excluded.</small>
    {rows.length === 0 && <p className="empty-state research-empty">No publisher tiers set. All publishers use the Standard tier.</p>}
    {rows.map((row, index) => {
      const base = `research-quality-${index}`;
      const error = errors[`research.publisher_quality.${index}`] ?? errors[`research.publisher_quality.${row.domain}`];
      const known = qualityTiers.some((tier) => tier.value === row.tier);
      return <div className="research-row" key={index}>
        <div className="field">
          <label htmlFor={`${base}-domain`}>Publisher {index + 1} hostname</label>
          <input id={`${base}-domain`} value={row.domain} placeholder="www.example.com" aria-invalid={Boolean(error)} aria-describedby={error ? `${base}-error` : undefined} onChange={(event) => update(index, { domain: event.target.value })} />
          {error && <span id={`${base}-error`} className="field-error" role="alert">{error}</span>}
        </div>
        <div className="field">
          <label htmlFor={`${base}-tier`}>Publisher {index + 1} tier</label>
          <select id={`${base}-tier`} value={row.tier} onChange={(event) => update(index, { tier: event.target.value })}>
            {!known && <option value={row.tier}>{row.tier || "Not set"} (unrecognized)</option>}
            {qualityTiers.map((tier) => <option key={tier.value} value={tier.value}>{tier.label}</option>)}
          </select>
        </div>
        <button type="button" className="ghost-button research-remove" aria-label={`Remove publisher tier ${index + 1}`} title={`Remove publisher tier ${index + 1}`} onClick={() => onChange(rows.filter((_, position) => position !== index))}><Trash2 size={14} aria-hidden="true" />Remove</button>
      </div>;
    })}
    {errors["research.publisher_quality"] && <span className="field-error" role="alert">{errors["research.publisher_quality"]}</span>}
    <button type="button" className="ghost-button" onClick={() => { onChange([...rows, { domain: "", tier: "standard" }]); setFocusIndex(rows.length); }}><Plus size={14} aria-hidden="true" />Add publisher tier</button>
  </fieldset>;
}
