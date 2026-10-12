import { ArrowUpRight, BarChart3, Check, ExternalLink, RefreshCw, Save, Settings2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NavLink, useParams } from "react-router-dom";

import { ApiError, decideApproval, retryPublications, type BudgetSummary, type Clip, type ClipList, type JsonObject, updateContentProfile, updateSettings, createContentProfile, saveContentProfile, activateContentProfile, deleteContentProfile, type ContentProfileItem, type ContentProfileList } from "./api/client";
import { Collapsible } from "./Collapsible";
import { Pagination } from "./Pagination";
import { useResource } from "./hooks/useResource";

type EditorValue = string | number | boolean | null | EditorValue[] | { [key: string]: EditorValue };

export function AnalyticsPage() {
  const [period, setPeriod] = useState("7d");
  const [resource, reload] = useResource<unknown>(`/api/analytics/summary?period=${period}`);
  const [publicationId, setPublicationId] = useState("");
  const [selectedPublication, setSelectedPublication] = useState("");
  const [snapshots] = useResource<unknown>(selectedPublication ? `/api/analytics/publications/${encodeURIComponent(selectedPublication)}/snapshots` : null);
  const items = resource.status === "success" ? objectArray(record(resource.data).items) : [];

  return <Page title="Analytics" eyebrow="PERFORMANCE / 05" lede="Latest Metric Snapshots by platform and reporting period." action={<IconButton label="Refresh analytics" onClick={reload} />}>
    <div className="filter-row" role="group" aria-label="Analytics period">
      {["7d", "30d", "all"].map((value) => <button key={value} className={`filter-button${period === value ? " selected" : ""}`} onClick={() => setPeriod(value)}>{value === "all" ? "All time" : value}</button>)}
    </div>
    {resource.status === "loading" ? <Loading /> : resource.status === "error" ? <ErrorMessage message={resource.message} /> : <section className="metric-grid" aria-label="Analytics summary">
      {items.length ? items.map((item) => <article className="section-block metric-card" key={text(item.platform)}>
        <div className="section-head"><span className="eyebrow">{text(item.platform).toUpperCase()}</span><BarChart3 size={16} /></div>
        <div className="metric-list">
          {(["views", "likes", "comments", "shares", "watch_time_seconds"] as const).map((metric) => <Metric key={metric} label={humanize(metric)} value={item[metric]} />)}
          <Metric label="Average retention" value={item.average_retention_ratio} suffix="%" multiplier={100} />
          <EstimatedRevenue value={item.estimated_revenue} currency={item.revenue_currency} basis={item.revenue_by_basis} />
        </div>
      </article>) : <Empty message="No Metric Snapshots are available for this period." />}
    </section>}
    <section className="section-block form-section snapshot-section">
      <div className="section-head"><div><div className="eyebrow">TIME SERIES</div><h2>Publication snapshots</h2></div></div>
      <form className="lookup-form" onSubmit={(event) => { event.preventDefault(); setSelectedPublication(publicationId.trim()); }}>
        <label htmlFor="publication-id">Publication ID</label>
        <div><input id="publication-id" value={publicationId} onChange={(event) => setPublicationId(event.target.value)} required placeholder="UUID" /><button className="command-button" type="submit">Load</button></div>
      </form>
      {selectedPublication && (snapshots.status === "loading" ? <Loading /> : snapshots.status === "error" ? <ErrorMessage message={snapshots.message} /> : <SnapshotTable items={objectArray(record(snapshots.data).items)} />)}
    </section>
  </Page>;
}

export function ProfilePage() {
  const [resource, reload] = useResource<ContentProfileList>("/api/content-profiles");
  const [active] = useResource<JsonObject>("/api/content-profile");
  const [selectedId, setSelectedId] = useState("");
  const [message, setMessage] = useState("");
  const items = resource.status === "success" ? resource.data.items : [];
  const selected = items.find((item) => item.id === selectedId) ?? items.find((item) => item.is_active) ?? items[0];
  return <Page title="Content Profile" eyebrow="EDITORIAL / 06" lede="Manage saved editorial policies. Only the active profile is used by subsequent Runs." action={<IconButton label="Refresh Content Profile" onClick={reload} />}>
    {message && <p className="form-message" role="status">{message}</p>}
    {resource.status === "loading" ? <Loading /> : resource.status === "error" ? <ErrorMessage message={resource.message} /> : <>
      <div className="profile-selector field"><label htmlFor="saved-profile">Saved profiles</label><select id="saved-profile" value={selected?.id ?? ""} onChange={(event) => { setSelectedId(event.target.value); setMessage(""); }}>{!items.length && <option value="">No saved profiles</option>}{items.map((item) => <option key={item.id} value={item.id}>{item.name}{item.is_active ? " (active)" : ""}</option>)}</select></div>
      {selected || active.status === "success" ? <ProfileEditor key={selected?.id ?? "new"} item={selected} initial={selected?.profile ?? (active.status === "success" ? active.data : {})} onSaved={(item, notice) => { setSelectedId(item?.id ?? ""); setMessage(notice); reload(); }} /> : active.status === "error" ? <ErrorMessage message={active.message} /> : <Loading />}
    </>}
  </Page>;
}

function ProfileEditor({ initial, item, onSaved }: { initial: JsonObject; item?: ContentProfileItem; onSaved: (item: ContentProfileItem | undefined, notice: string) => void }) {
  const [draft, setDraft] = useState(initial as { [key: string]: EditorValue });
  const [name, setName] = useState(item?.name ?? "");
  const [newName, setNewName] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const deleteButton = useRef<HTMLButtonElement>(null);

  async function perform(action: "save" | "create" | "activate" | "delete") {
    setMessage("");
    const validation = action === "save" || action === "create" ? validateProfile(draft) : {};
    if ((action === "create" && !newName.trim()) || (action === "save" && item && !name.trim())) validation.form = "Enter a profile name.";
    setErrors(validation);
    if (Object.keys(validation).length) return;
    setSaving(true);
    try {
      let saved: ContentProfileItem | undefined = item;
      if (action === "create") saved = await createContentProfile({ name: newName.trim(), profile: draft as JsonObject });
      if (action === "save") {
        if (item) saved = await saveContentProfile(item.id, { name: name.trim(), profile: draft as JsonObject });
        else await updateContentProfile(draft as JsonObject);
      }
      if (action === "activate" && item) saved = await activateContentProfile(item.id);
      if (action === "delete" && item) { await deleteContentProfile(item.id); saved = undefined; }
      onSaved(saved, action === "activate" ? "Content Profile activated. New Runs will use this profile." : action === "delete" ? "Content Profile deleted." : "Content Profile saved.");
    } catch (error: unknown) {
      setErrors(Object.fromEntries(Object.entries(serverErrors(error)).map(([path, value]) => [path.replace(/^profile\./, ""), value])));
      setMessage(error instanceof Error ? error.message : "Content Profile could not be updated");
    } finally { setSaving(false); setConfirmDelete(false); }
  }

  return <section className="section-block form-section">
    {item && <div className="profile-management">
      <div className="field"><label htmlFor="profile-name">Profile name</label><input id="profile-name" value={name} onChange={(event) => setName(event.target.value)} /></div>
      <span className={`table-status ${item.is_active ? "active" : "queued"}`}>{item.is_active ? "Active profile" : "Saved profile"}</span>
      <button className="command-button" disabled={saving || item.is_active} onClick={() => void perform("activate")}>Activate selected profile</button>
      <button ref={deleteButton} className="danger-button" disabled={saving || item.is_active} title={item.is_active ? "The active profile cannot be deleted" : "Delete this saved profile"} onClick={() => setConfirmDelete(true)}>Delete profile</button>
    </div>}
    <ObjectEditor value={draft} onChange={setDraft} errors={errors} />
    {errors.form && <p className="field-error" role="alert">{errors.form}</p>}
    <FormFooter saving={saving} message={message} onSave={() => void perform("save")} />
    <div className="profile-create"><div className="field"><label htmlFor="new-profile-name">New profile name</label><input id="new-profile-name" value={newName} onChange={(event) => setNewName(event.target.value)} /></div><button className="ghost-button" disabled={saving} onClick={() => void perform("create")}>Save as new profile</button></div>
    {confirmDelete && <div className="profile-confirm" role="alertdialog" aria-modal="false" aria-labelledby="delete-profile-title"><h3 id="delete-profile-title">Delete {item?.name}?</h3><p>This removes the saved profile and cannot be undone.</p><button className="danger-button" autoFocus disabled={saving} onClick={() => void perform("delete")}>Confirm delete</button><button className="ghost-button" disabled={saving} onClick={() => { setConfirmDelete(false); deleteButton.current?.focus(); }}>Cancel</button></div>}
  </section>;
}

export function SettingsPage() {
  const [resource, reload] = useResource<unknown>("/api/settings");
  const payload = resource.status === "success" ? record(resource.data) : {};
  const providers = objectArray(payload.providers);
  const settings = record(payload.settings);
  return <Page title="Settings" eyebrow="SYSTEM / 07" lede="Runtime policy and provider readiness. Credentials remain environment-only." action={<IconButton label="Refresh settings" onClick={reload} />}>
    {resource.status === "loading" ? <Loading /> : resource.status === "error" ? <ErrorMessage message={resource.message} /> : <>
      <Collapsible title="Schedule"><ScheduleSection /></Collapsible>
      <Collapsible title="Providers"><section className="section-block provider-section">
        <div className="section-head"><div><div className="eyebrow">CREDENTIAL PRESENCE</div><h2>Providers</h2></div><span className="privacy-note">VALUES NEVER DISPLAYED</span></div>
        <div className="provider-grid">{providers.map((provider) => <div className="provider-row" key={text(provider.provider)}><span>{humanize(text(provider.provider))}</span><span className={`credential ${provider.credentials_configured === true ? "configured" : "missing"}`}>{provider.credentials_configured === true ? <Check size={13} /> : <X size={13} />}{provider.credentials_configured === true ? "Configured" : "Not configured"}</span></div>)}</div>
      </section></Collapsible>
      <div className="settings-stack">{Object.entries(settings).filter(([, value]) => isEditorObject(value)).sort(([left], [right]) => Number(right === "environment") - Number(left === "environment")).map(([section, value]) => <Collapsible key={section} title={humanize(section)}><SettingsSection name={section} initial={record(value)} onSaved={reload} /></Collapsible>)}</div>
    </>}
  </Page>;
}

function ScheduleSection() {
  const [resource, reload] = useResource<unknown>("/api/content-profile");
  const profile = resource.status === "success" ? record(resource.data) : {};
  if (!isEditorObject(profile.schedule)) return null;
  return <ScheduleEditor key={JSON.stringify(profile.schedule)} profile={profile} onSaved={reload} />;
}

function timezoneOptions(current: string): string[] {
  const supported = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.("timeZone") ?? [];
  return [...new Set([current, "UTC", ...supported].filter(Boolean))].sort((left, right) => left.localeCompare(right));
}

function ScheduleEditor({ profile, onSaved }: { profile: JsonObject; onSaved: () => void }) {
  const initial = record(profile.schedule);
  const [enabled, setEnabled] = useState(initial.enabled !== false);
  const [localTime, setLocalTime] = useState(text(initial.local_time) || "05:00");
  const [timezone, setTimezone] = useState(text(initial.timezone) || "Europe/Lisbon");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [summary, reloadSummary] = useResource<{ next_scheduled_run_at?: string | null }>("/api/dashboard/summary", { intervalMs: 30_000 });
  const next = summary.status === "success" ? summary.data.next_scheduled_run_at : null;

  async function save() {
    const validation: Record<string, string> = {};
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(localTime)) validation["schedule.local_time"] = "Use HH:MM in 24-hour time.";
    setErrors(validation); setMessage("");
    if (Object.keys(validation).length) return;
    setSaving(true);
    try {
      await updateContentProfile({ ...profile, schedule: { ...initial, enabled, local_time: localTime, timezone } });
      setMessage(enabled ? `Daily Run set for ${localTime} (${timezone}). The next Run updates within 30 seconds.` : "Daily Run disabled.");
      onSaved(); reloadSummary();
    } catch (error: unknown) {
      setErrors(serverErrors(error));
      setMessage(error instanceof Error ? error.message : "Schedule could not be saved");
    } finally { setSaving(false); }
  }

  return <section className="section-block form-section schedule-section">
    <div className="section-head"><div><div className="eyebrow">AUTOMATION</div><h2>Schedule</h2></div><span className="privacy-note">NEXT RUN {next ? formatDate(next).toUpperCase() : "N/A"}</span></div>
    <div className="object-editor">
      <div className="field"><label htmlFor="schedule-enabled">Daily Run</label><input id="schedule-enabled" type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /></div>
      <div className="field">
        <label htmlFor="schedule-local-time">Run Time</label>
        <input id="schedule-local-time" type="time" step={60} value={localTime} disabled={!enabled} aria-invalid={Boolean(errors["schedule.local_time"])} onChange={(event) => setLocalTime(event.target.value.slice(0, 5))} />
        {errors["schedule.local_time"] && <span className="field-error" role="alert">{errors["schedule.local_time"]}</span>}
      </div>
      <div className="field">
        <label htmlFor="schedule-timezone">Timezone</label>
        <select id="schedule-timezone" value={timezone} disabled={!enabled} aria-invalid={Boolean(errors["schedule.timezone"])} onChange={(event) => setTimezone(event.target.value)}>
          {timezoneOptions(timezone).map((zone) => <option key={zone} value={zone}>{zone.replaceAll("_", " ")}</option>)}
        </select>
        {errors["schedule.timezone"] && <span className="field-error" role="alert">{errors["schedule.timezone"]}</span>}
      </div>
    </div>
    <FormFooter saving={saving} message={message} onSave={() => void save()} />
  </section>;
}

function SettingsSection({ name, initial, onSaved }: { name: string; initial: JsonObject; onSaved: () => void }) {
  const [draft, setDraft] = useState(initial as { [key: string]: EditorValue });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  async function save() {
    if (name === "environment" && "wan_max_generations_per_run" in draft) {
      const limit = draft.wan_max_generations_per_run;
      if (typeof limit !== "number" || !Number.isInteger(limit) || limit < 0 || limit > 100) {
        setErrors({ "environment.wan_max_generations_per_run": "Enter a whole number from 0 to 100." });
        setMessage("");
        return;
      }
    }
    setSaving(true); setMessage(""); setErrors({});
    try {
      await updateSettings(name, draft as JsonObject);
      setMessage(`${humanize(name)} settings saved.`); onSaved();
    } catch (error: unknown) {
      setErrors(serverErrors(error, name)); setMessage(error instanceof Error ? error.message : "Settings could not be saved");
    } finally { setSaving(false); }
  }
  return <section className={`section-block form-section${name === "publishing" ? " prominent" : ""}`}>
    <div className="section-head"><div><div className="eyebrow">SETTINGS SECTION</div><h2>{humanize(name)}</h2></div>{name === "publishing" && <Settings2 size={18} />}</div>
    {name === "environment" && <p className="form-message">Defaults come from .env. Saved changes, including Wan FPS and inference steps, apply to new Runs and Continue Run; credentials and endpoints stay in .env.</p>}
    <ObjectEditor value={draft} onChange={setDraft} errors={errors} prefix={name} />
    <FormFooter saving={saving} message={message} onSave={() => void save()} />
  </section>;
}

export function ClipsPage() {
  const [filter, setFilter] = useState<"all" | "published" | "failed">("all");
  const [offset, setOffset] = useState(0);
  const [clips, reload] = useResource<ClipList>(`/api/clips?limit=20&offset=${offset}&filter=${filter}`);
  const [budget] = useResource<BudgetSummary>("/api/budget");
  const currency = budget.status === "success" ? budget.data.currency : null;
  return <Page title="Clips" headingExtra={<div className="clip-tabs" role="tablist" aria-label="Clip status">{(["all", "published", "failed"] as const).map((value) => <button id={`clip-tab-${value}`} key={value} role="tab" tabIndex={filter === value ? 0 : -1} onKeyDown={(event) => { const keys = ["ArrowLeft", "ArrowRight", "Home", "End"]; if (!keys.includes(event.key)) return; event.preventDefault(); const values = ["all", "published", "failed"] as const; const index = values.indexOf(value); const next = event.key === "Home" ? 0 : event.key === "End" ? 2 : (index + (event.key === "ArrowRight" ? 1 : 2)) % 3; const chosen = values[next]!; setFilter(chosen); setOffset(0); document.getElementById(`clip-tab-${chosen}`)?.focus(); }} aria-selected={filter === value} aria-controls="clip-results" className={`filter-button${filter === value ? " selected" : ""}`} onClick={() => { setFilter(value); setOffset(0); }}>{humanize(value)}</button>)}</div>} eyebrow="PUBLISHING / 04" lede="Approved Clips and platform Publications." action={<IconButton label="Refresh Clips" onClick={reload} />}>
    <div id="clip-results" role="tabpanel" aria-labelledby={`clip-tab-${filter}`}>{clips.status === "loading" ? <Loading /> : clips.status === "error" ? <ErrorMessage message={clips.message} /> : clips.data.items.length ? <div className="clip-list">{clips.data.items.map((clip) => <ClipCard key={clip.id} clip={clip} currency={currency} />)}</div> : <Empty message="No Clips match this filter." />}</div>
    {clips.status === "success" && <Pagination offset={offset} total={clips.data.total ?? clips.data.items.length} onChange={setOffset} label="Clips" />}
    <div className="platform-strip" aria-label="Supported publication platforms"><span>YouTube</span><span>Instagram</span><span>Facebook</span><span className="deferred">TikTok · deferred</span></div>
  </Page>;
}

export function ClipDetailPage() {
  const { clipId = "" } = useParams();
  const [clip, reload] = useResource<Clip>(`/api/clips/${encodeURIComponent(clipId)}`);
  const [budget] = useResource<BudgetSummary>("/api/budget");
  return <Page title={clip.status === "success" ? clip.data.story_title || "Untitled Clip" : "Clip detail"} eyebrow="PUBLISHING / CLIP" lede={clipId} action={<IconButton label="Refresh Clip" onClick={reload} />}>
    {clip.status === "loading" ? <Loading /> : clip.status === "error" ? <ErrorMessage message={clip.message} /> : <ClipDetail clip={clip.data} currency={budget.status === "success" ? budget.data.currency : null} onChanged={reload} />}
  </Page>;
}

export function PendingApprovals() {
  const [resource, reload] = useResource<ClipList>("/api/clips/pending-approval?limit=100");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  async function decide(clip: Clip, decision: "approve" | "reject") {
    setBusy(clip.id); setMessage("");
    try {
      await decideApproval(clip.id, { decision });
      setMessage(`${clip.story_title || "Clip"} ${decision === "approve" ? "approved" : "rejected"}.`);
      reload();
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "Approval decision failed");
    } finally { setBusy(null); }
  }
  return <section className="section-block pending-approvals">
    <div className="section-head"><div><div className="eyebrow">PUBLISHING GATE</div><h2>Pending approval</h2></div>{resource.status === "success" && <span className="event-count">{resource.data.items.length} CLIPS</span>}</div>
    {message && <p className="form-message" role="status">{message}</p>}
    {resource.status === "loading" ? <Loading /> : resource.status === "error" ? <ErrorMessage message={resource.message} /> : resource.data.items.length ? <div className="pending-list">{resource.data.items.map((clip) => <article className="pending-item" key={clip.id}>
      <ClipPreview clip={clip} />
      <div className="pending-copy"><h3>{clip.story_title || "Untitled Clip"}</h3><p>{metadataSummary(clip.social_metadata)}</p><PublicationBadges clip={clip} /><Countdown dueAt={clip.auto_publish_due_at} /><div className="approval-actions"><button className="command-button" disabled={busy === clip.id} aria-label={`Approve ${clip.story_title || "Clip"}`} onClick={() => void decide(clip, "approve")}><Check size={15} />Approve</button><button className="danger-button" disabled={busy === clip.id} aria-label={`Reject ${clip.story_title || "Clip"}`} onClick={() => void decide(clip, "reject")}><X size={15} />Reject</button></div></div>
    </article>)}</div> : <Empty message="No Clips are awaiting approval." />}
  </section>;
}

export function PublishesPage() {
  const [offset, setOffset] = useState(0);
  const [resource, reload] = useResource<ClipList>(`/api/clips/pending-approval?limit=20&offset=${offset}`);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  async function decide(clip: Clip, decision: "approve" | "reject") {
    setBusy(clip.id); setMessage("");
    try {
      await decideApproval(clip.id, { decision });
      setMessage(`${clip.story_title || "Clip"} ${decision === "approve" ? "approved for publication" : "rejected"}.`);
      setOffset(0); reload();
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "Approval decision failed");
    } finally { setBusy(null); }
  }
  const count = resource.status === "success" ? (resource.data.total ?? resource.data.items.length) : null;
  return <Page title="Review Board" eyebrow="PUBLISHING / REVIEW BOARD" lede="Clips awaiting your decision before they are published to the enabled platforms." action={<div className="board-head-actions">{count !== null && <span className="event-count">{count} AWAITING</span>}<button className="ghost-button" onClick={reload} aria-label="Refresh review board"><RefreshCw size={14} />Refresh</button></div>}>
    {message && <p className="form-message" role="status">{message}</p>}
    {resource.status === "loading" ? <Loading /> : resource.status === "error" ? <ErrorMessage message={resource.message} /> : resource.data.items.length ? <div className="review-board">{resource.data.items.map((clip) => <ReviewCard key={clip.id} clip={clip} busy={busy === clip.id} onDecide={(decision) => void decide(clip, decision)} />)}</div> : <div className="section-block"><Empty message="Nothing to review. Clips awaiting approval will appear here." /></div>}
    {resource.status === "success" && <Pagination offset={offset} total={resource.data.total ?? resource.data.items.length} onChange={setOffset} label="Clips awaiting approval" />}
  </Page>;
}

function ReviewCard({ clip, busy, onDecide }: { clip: Clip; busy: boolean; onDecide: (decision: "approve" | "reject") => void }) {
  const metadata = record(clip.social_metadata);
  const description = text(metadata.description);
  const hashtags = Array.isArray(metadata.hashtags) ? metadata.hashtags.map(text).filter(Boolean) : [];
  const sources = Array.isArray(metadata.source_attributions) ? metadata.source_attributions.map(text).filter(Boolean) : [];
  const title = clip.story_title || "Untitled Clip";
  return <article className="review-card" aria-label={`Review ${title}`}>
    <div className="review-media"><ClipPreview clip={clip} /></div>
    <div className="review-body">
      <div className="review-meta"><span>{Math.round(clip.preview.duration_seconds)}s</span><span>{formatDate(clip.created_at)}</span></div>
      <h2>{title}</h2>
      <p className="review-caption">{description || "No caption recorded."}</p>
      {hashtags.length > 0 && <div className="review-tags" aria-label="Hashtags">{hashtags.map((tag) => <span key={tag}>#{tag.replace(/^#/, "")}</span>)}</div>}
      {sources.length > 0 && <details className="review-sources"><summary>{sources.length} {sources.length === 1 ? "Source" : "Sources"}</summary><ul>{sources.map((source) => <li key={source}>{source}</li>)}</ul></details>}
      <div className="review-platforms">{clip.publications.length ? clip.publications.map((publication) => <span key={publication.id}>{platformLabel(publication.platform)} · {humanize(publication.mode ?? "")}</span>) : <span>No platform targets</span>}</div>
      {clip.auto_publish_due_at ? <Countdown dueAt={clip.auto_publish_due_at} /> : <span className="approval-countdown">Awaiting your decision</span>}
      <div className="review-actions">
        <button className="command-button" disabled={busy} aria-label={`Approve ${title}`} onClick={() => onDecide("approve")}><Check size={15} />Approve</button>
        <button className="danger-button" disabled={busy} aria-label={`Reject ${title}`} onClick={() => onDecide("reject")}><X size={15} />Reject</button>
        <NavLink className="text-link" to={`/runs/${clip.run_id}`}>Run <ArrowUpRight size={14} /></NavLink>
      </div>
    </div>
  </article>;
}

function ClipCard({ clip, currency }: { clip: Clip; currency: string | null }) {
  return <article className="section-block clip-card"><ClipPreview clip={clip} /><div className="clip-card-copy"><div className="section-head"><div><span className={`table-status ${clip.status}`}>{humanize(clip.status)}</span><h2><NavLink to={`/clips/${clip.id}`}>{clip.story_title || "Untitled Clip"}</NavLink></h2></div><span className="table-date">{formatDate(clip.created_at)}</span></div><div className="clip-facts"><span>{formatCost(clip.cost_total, currency)}</span><span>{clip.preview.duration_seconds}s</span><span>{clip.preview.width}×{clip.preview.height}</span></div><PublicationList clip={clip} /></div></article>;
}

function ClipDetail({ clip, currency, onChanged }: { clip: Clip; currency: string | null; onChanged: () => void }) {
  return <div className="clip-detail"><section className="section-block clip-detail-preview"><ClipPreview clip={clip} /><div className="clip-facts"><span>{formatCost(clip.cost_total, currency)}</span><span>{clip.preview.duration_seconds}s · {clip.preview.width}×{clip.preview.height} · {clip.preview.fps} fps</span><NavLink className="text-link" to={`/runs/${clip.run_id}`}>Open source Run <ArrowUpRight size={14} /></NavLink></div></section><section className="section-block publication-panel"><div className="section-head"><div><div className="eyebrow">DISTRIBUTION</div><h2>Publications</h2></div><RetryPublishButton clip={clip} onRetried={onChanged} /></div><PublicationList clip={clip} /></section></div>;
}

function RetryPublishButton({ clip, onRetried }: { clip: Clip; onRetried: () => void }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  if (clip.status !== "approved" || !clip.publications.some((publication) => publication.status === "failed")) return null;
  async function retry() {
    setBusy(true); setMessage("");
    try {
      await retryPublications(clip.id);
      setMessage("Publish retry finished.");
      onRetried();
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "Publish retry failed");
    } finally { setBusy(false); }
  }
  return <div className="retry-publish"><button className="command-button" disabled={busy} onClick={() => void retry()}><RefreshCw size={15} />{busy ? "Retrying…" : "Retry publish"}</button>{message && <p className="form-message" role="status">{message}</p>}</div>;
}

function ClipPreview({ clip }: { clip: Clip }) {
  return <video className="clip-preview" aria-label={`Preview ${clip.story_title || "Clip"}`} controls preload="metadata" src={clip.preview.media_url} />;
}

function PublicationList({ clip }: { clip: Clip }) {
  if (!clip.publications.length) return <Empty message="No Publications recorded for this Clip." />;
  return <div className="publication-list">{clip.publications.map((publication) => <div className="publication-row" key={publication.id}><div><strong>{platformLabel(publication.platform)}</strong><span className={`table-status ${publication.status}`}><span />{humanize(publication.status)}</span></div><div className="publication-metrics">{publication.latest_metrics ? <><span>{displayMetric(publication.latest_metrics.views)} views</span><span>{displayMetric(publication.latest_metrics.likes)} likes</span></> : <span>Metrics n/a</span>}</div>{publication.platform_url && <a className="row-open" href={publication.platform_url} target="_blank" rel="noreferrer" aria-label={`Open ${platformLabel(publication.platform)} Publication`}><ExternalLink size={15} /></a>}{publication.error_message && <small>{publication.error_message}</small>}</div>)}</div>;
}

function PublicationBadges({ clip }: { clip: Clip }) {
  return <div className="publication-badges">{clip.publications.map((publication) => <span key={publication.id} className={`table-status ${publication.status}`}>{platformLabel(publication.platform)} · {humanize(publication.status)}</span>)}</div>;
}

function Countdown({ dueAt }: { dueAt?: string | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  if (!dueAt) return <span className="approval-countdown">Auto-publish time n/a</span>;
  const remaining = new Date(dueAt).getTime() - now;
  if (!Number.isFinite(remaining)) return <span className="approval-countdown">Auto-publish time n/a</span>;
  if (remaining <= 0) return <span className="approval-countdown due">Auto-publish due now</span>;
  const totalSeconds = Math.ceil(remaining / 1000);
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const value = days ? `${days}d ${hours}h` : hours ? `${hours}h ${minutes}m` : `${minutes}m ${seconds}s`;
  return <span className="approval-countdown">Auto-publishes in {value} · {formatDate(dueAt)}</span>;
}

export function ApprovalPage() {
  return <Page title="Pending approvals" eyebrow="PUBLISHING / REVIEW" lede="Review approved Clips before platform publication.">
    <PendingApprovals />
  </Page>;
}

const outputModeOptions = [
  { value: "json_schema", label: "Strict schema (default)" },
  { value: "json_object", label: "JSON mode + schema instructions" },
  { value: "prompt_json", label: "Prompt-only JSON" },
];
const settingOptions: Record<string, { value: string; label: string }[]> = {
  "environment.llm_output_mode": outputModeOptions,
  "environment.llm_output_mode_evaluation": outputModeOptions,
  "environment.llm_output_mode_evaluation_fallback": outputModeOptions,
  "environment.whisper_device": [
    { value: "auto", label: "Automatic" }, { value: "cpu", label: "CPU" }, { value: "cuda", label: "CUDA (GPU)" },
  ],
  "publishing.mode": [
    { value: "disabled", label: "Disabled" }, { value: "dry_run", label: "Dry run" }, { value: "live", label: "Live" },
  ],
};

function ObjectEditor({ value, onChange, errors, prefix = "" }: { value: { [key: string]: EditorValue }; onChange: (value: { [key: string]: EditorValue }) => void; errors: Record<string, string>; prefix?: string }) {
  return <div className="object-editor">{Object.entries(value).map(([key, item]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (isEditorObject(item)) return <fieldset key={key}><legend>{humanize(key)}</legend><ObjectEditor value={item} onChange={(next) => onChange({ ...value, [key]: next })} errors={errors} prefix={path} /></fieldset>;
    const id = `field-${path.replaceAll(".", "-")}`;
    const options = settingOptions[path];
    if (options) {
      const current = typeof item === "string" ? item : "";
      const outputMode = path.startsWith("environment.llm_output_mode");
      return <div className="field" key={key}>
        <label htmlFor={id}>{humanize(key)}</label>
        <select id={id} value={current} aria-describedby={outputMode ? `${id}-help` : undefined} aria-invalid={Boolean(errors[path])} onChange={(event) => onChange({ ...value, [key]: event.target.value })}>
          {!options.some((option) => option.value === current) && <option value={current}>{current || "Not set"} (unrecognized)</option>}
          {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        {outputMode && <small id={`${id}-help`}>Strict schema asks the provider to enforce the schema; JSON mode enforces JSON syntax; prompt-only uses instructions without response_format. Local schema validation and bounded repairs apply in every mode. Visual review still requires an image-capable model.</small>}
        {errors[path] && <span className="field-error" role="alert">{errors[path]}</span>}
      </div>;
    }
    if (path === "environment.wan_max_generations_per_run") {
      return <div className="field" key={key}>
        <label htmlFor={id}>{humanize(key)}</label>
        <input id={id} type="number" min={0} max={100} step={1} value={typeof item === "number" ? item : ""} aria-describedby={`${id}-help`} aria-invalid={Boolean(errors[path])} onChange={(event) => onChange({ ...value, [key]: event.target.value === "" ? null : Number(event.target.value) })} />
        <small id={`${id}-help`}>0 disables new Wan calls. Failed or stopped starts count; Retry and Continue retain usage. Additional Visuals use suitable HyperFrames/Manim graphics or refined free-media searches.</small>
        {errors[path] && <span className="field-error" role="alert">{errors[path]}</span>}
      </div>;
    }
    return <div className="field" key={key}><label htmlFor={id}>{humanize(key)}</label>{typeof item === "boolean" ? <input id={id} type="checkbox" checked={item} onChange={(event) => onChange({ ...value, [key]: event.target.checked })} /> : <input id={id} type={typeof item === "number" ? "number" : "text"} value={Array.isArray(item) ? item.join(", ") : item ?? ""} onChange={(event) => onChange({ ...value, [key]: parseInput(event.target.value, item) })} />} {errors[path] && <span className="field-error" role="alert">{errors[path]}</span>}</div>;
  })}</div>;
}

function FormFooter({ saving, message, onSave }: { saving: boolean; message: string; onSave: () => void }) {
  return <div className="form-footer"><button className="command-button" disabled={saving} onClick={onSave}><Save size={14} />{saving ? "Saving" : "Save"}</button>{message && <span className="form-message" role="status">{message}</span>}</div>;
}

function SnapshotTable({ items }: { items: JsonObject[] }) {
  if (!items.length) return <Empty message="No Metric Snapshots recorded for this Publication." />;
  return <div className="run-table-wrap"><table className="run-table"><thead><tr><th>CAPTURED</th><th>OFFSET</th><th>PLATFORM</th><th>VIEWS</th><th>LIKES</th><th>COMMENTS</th><th>SHARES</th><th>ESTIMATED REVENUE</th></tr></thead><tbody>{items.map((item, index) => <tr key={`${text(item.captured_at)}-${index}`}><td>{formatDate(item.captured_at)}</td><td>{display(item.offset_label)}</td><td>{display(item.platform)}</td><td>{displayMetric(item.views)}</td><td>{displayMetric(item.likes)}</td><td>{displayMetric(item.comments)}</td><td>{displayMetric(item.shares)}</td><td>{item.estimated_revenue == null ? "n/a" : `${display(item.revenue_currency)} ${display(item.estimated_revenue)} · Estimated (${humanize(text(item.revenue_basis) || "basis unavailable")})`}</td></tr>)}</tbody></table></div>;
}

function Metric({ label, value, suffix = "", multiplier = 1 }: { label: string; value: unknown; suffix?: string; multiplier?: number }) {
  const number = typeof value === "number" ? value * multiplier : typeof value === "string" && value.trim() ? Number(value) * multiplier : null;
  return <div><span>{label}</span><strong>{number == null || Number.isNaN(number) ? "n/a" : `${new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 }).format(number)}${suffix}`}</strong></div>;
}

function EstimatedRevenue({ value, currency, basis }: { value: unknown; currency: unknown; basis: unknown }) {
  const breakdown = record(basis);
  return <div className="revenue"><span>Estimated revenue</span><strong>{value == null ? "n/a" : `${text(currency) || ""} ${text(value)}`.trim()}</strong><small>{Object.keys(breakdown).length ? Object.entries(breakdown).map(([name, amount]) => `${humanize(name)}: ${text(amount)}`).join(" · ") : "basis unavailable"}</small></div>;
}

function Page({ title, eyebrow, lede, action, headingExtra, children }: { title: string; eyebrow: string; lede: string; action?: React.ReactNode; headingExtra?: React.ReactNode; children: React.ReactNode }) { return <section className="page-wrap"><div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><div className="heading-with-tabs"><h1>{title}</h1>{headingExtra}</div><p className="page-lede">{lede}</p></div>{action}</div>{children}</section>; }
function IconButton({ label, onClick }: { label: string; onClick: () => void }) { return <button className="icon-button" onClick={onClick} title={label} aria-label={label}><RefreshCw size={17} /></button>; }
function Loading() { return <div className="loading-line"><span />Loading operational data</div>; }
function ErrorMessage({ message }: { message: string }) { return <div className="inline-error" role="alert">{message}</div>; }
function Empty({ message }: { message: string }) { return <div className="empty-state">{message}</div>; }

function validateProfile(profile: { [key: string]: EditorValue }): Record<string, string> {
  const errors: Record<string, string> = {};
  const categories = ["general", "technology", "ai", "finance", "business", "science", "gaming", "sports", "entertainment", "politics"];
  if (!categories.includes(text(profile.category))) errors.category = "Choose a supported category.";
  try { new Intl.Locale(text(profile.language)); } catch { errors.language = "Use a valid BCP 47 language tag."; }
  const platforms = Array.isArray(profile.platforms) ? profile.platforms : [];
  if (platforms.some((platform) => !["youtube", "instagram", "tiktok", "facebook"].includes(text(platform)))) errors.platforms = "Choose only supported platforms.";
  const duration = isEditorObject(profile.duration) ? profile.duration : {};
  const min = number(duration.min_seconds); const target = number(duration.target_seconds); const max = number(duration.max_seconds);
  if (!(min > 0 && min <= target && target <= max)) errors["duration.min_seconds"] = "Duration must satisfy 0 < min ≤ target ≤ max.";
  const output = isEditorObject(profile.output) ? profile.output : {};
  const width = number(output.width); const height = number(output.height); const fps = number(output.fps);
  if (width % 2 || height % 2 || width * 16 !== height * 9) errors["output.width"] = "Output must use even 9:16 dimensions.";
  if (fps < 24 || fps > 60) errors["output.fps"] = "FPS must be between 24 and 60.";
  const schedule = isEditorObject(profile.schedule) ? profile.schedule : {};
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(text(schedule.local_time))) errors["schedule.local_time"] = "Use HH:MM in 24-hour time.";
  try { new Intl.DateTimeFormat("en", { timeZone: text(schedule.timezone) }).format(); } catch { errors["schedule.timezone"] = "Use a valid IANA timezone."; }
  const research = isEditorObject(profile.research) ? profile.research : {};
  const minSources = number(research.min_sources); const preferredSources = number(research.preferred_independent_sources); const candidates = number(research.max_candidate_articles);
  if (minSources < 1 || minSources > preferredSources) errors["research.min_sources"] = "Minimum Sources must be at least 1 and no greater than preferred independent Sources.";
  if (candidates < 1 || candidates > 50) errors["research.max_candidate_articles"] = "Candidate articles must be between 1 and 50.";
  return errors;
}

function serverErrors(error: unknown, prefix = ""): Record<string, string> {
  if (!(error instanceof ApiError)) return {};
  const details = record(error.details);
  const errors = Array.isArray(details.errors) ? details.errors : [];
  return Object.fromEntries(errors.map((item) => { const entry = record(item); const location = Array.isArray(entry.loc) ? entry.loc.map(String).filter((part) => part !== "body").join(".") : "form"; return [prefix && !location.startsWith(`${prefix}.`) ? `${prefix}.${location}` : location, text(entry.msg) || error.message]; }));
}
function record(value: unknown): JsonObject { return typeof value === "object" && value !== null && !Array.isArray(value) ? value as JsonObject : {}; }
function objectArray(value: unknown): JsonObject[] { return Array.isArray(value) ? value.map(record) : []; }
function isEditorObject(value: unknown): value is { [key: string]: EditorValue } { return typeof value === "object" && value !== null && !Array.isArray(value); }
function parseInput(value: string, previous: EditorValue): EditorValue { if (typeof previous === "number") return Number(value); if (Array.isArray(previous)) return value.split(",").map((item) => item.trim()).filter(Boolean); return value; }
function number(value: EditorValue | undefined): number { return typeof value === "number" ? value : Number(value); }
function text(value: unknown): string { return typeof value === "string" || typeof value === "number" ? String(value) : ""; }
function display(value: unknown): string { return value == null || value === "" ? "n/a" : text(value) || "n/a"; }
function displayMetric(value: unknown): string { return typeof value === "number" ? value.toLocaleString("en-GB") : value == null ? "n/a" : display(value); }
function humanize(value: string): string { return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase()); }
function platformLabel(value: string): string { return value.toLowerCase() === "youtube" ? "YouTube" : value.toLowerCase() === "tiktok" ? "TikTok" : humanize(value); }
function formatDate(value: unknown): string { const date = new Date(text(value)); return Number.isNaN(date.getTime()) ? "n/a" : new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(date); }
function formatCost(value: string, currency: string | null): string { return currency ? `${currency} ${value}` : value; }
function metadataSummary(value: JsonObject | null | undefined): string {
  const metadata = record(value);
  return text(metadata.description) || text(metadata.title) || "No platform metadata recorded.";
}