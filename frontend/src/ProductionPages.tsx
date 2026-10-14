import { AlertCircle, ArrowUpRight, BarChart3, Check, Clock, ExternalLink, Plus, RefreshCw, Save, Settings2, ShieldCheck, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NavLink, useParams } from "react-router-dom";

import { ApiError, decideApproval, retryPublications, deleteClip, refreshGoals, type BudgetSummary, type Clip, type ClipList, type GoalsResponse, type PlatformGoal, type JsonObject, updateContentProfile, updateSettings, createContentProfile, saveContentProfile, activateContentProfile, deleteContentProfile, toggleActiveProfile, addProfileScheduleRule, updateProfileScheduleRule, deleteProfileScheduleRule, type ProfileScheduleItem, type ContentProfileItem, type ContentProfileList } from "./api/client";
import { Collapsible } from "./Collapsible";
import { isEditorObject, type EditorObject, type EditorValue } from "./editorValue";
import { ProfileResearchSection } from "./ProfileResearch";
import { composeProfile, readQualityRows, researchListKeys, validateResearch, type QualityRow } from "./researchPolicy";
import { Pagination } from "./Pagination";
import { useResource } from "./hooks/useResource";

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
  return <Page title="Content Profile" eyebrow="EDITORIAL / 06" lede="Manage saved editorial policies and centralized automation schedules. Multiple profiles can be active simultaneously, each running at its designated time." action={<IconButton label="Refresh Content Profile" onClick={reload} />}>
    {message && <p className="form-message" role="status">{message}</p>}
    <CentralizedSchedulerSection key={items.map((item) => item.updated_at).join(",")} onScheduleChange={reload} />
    {resource.status === "loading" ? <Loading /> : resource.status === "error" ? <ErrorMessage message={resource.message} /> : <>
      <div className="profile-selector field"><label htmlFor="saved-profile">Saved profiles</label><select id="saved-profile" value={selected?.id ?? ""} onChange={(event) => { setSelectedId(event.target.value); setMessage(""); }}>{!items.length && <option value="">No saved profiles</option>}{items.map((item) => <option key={item.id} value={item.id}>{item.name}{item.is_active ? " (active)" : ""}</option>)}</select></div>
      {selected || active.status === "success" ? <ProfileEditor key={`${selected?.id ?? "new"}-${selected?.updated_at ?? ""}`} item={selected} initial={selected?.profile ?? (active.status === "success" ? active.data : {})} onSaved={(item, notice) => { setSelectedId(item?.id ?? ""); setMessage(notice); reload(); }} /> : active.status === "error" ? <ErrorMessage message={active.message} /> : <Loading />}
    </>}
  </Page>;
}

function CentralizedSchedulerSection({ onScheduleChange }: { onScheduleChange?: () => void }) {
  const [schedulesResource, reloadSchedules] = useResource<{ items: ProfileScheduleItem[] }>("/api/schedules", { intervalMs: 30_000 });
  const rawItems = schedulesResource.status === "success" && Array.isArray(schedulesResource.data?.items) ? schedulesResource.data.items : [];
  const items = rawItems.filter(Boolean);

  // Group items by profile_id
  const profilesMap: Record<string, { profile_id: string; profile_name: string; is_active: boolean; rules: ProfileScheduleItem[] }> = {};
  for (const item of items) {
    const pid = item.profile_id;
    if (!profilesMap[pid]) {
      profilesMap[pid] = {
        profile_id: pid,
        profile_name: item.profile_name,
        is_active: item.is_active,
        rules: [],
      };
    }
    profilesMap[pid].rules.push(item);
  }

  return <section className="section-block form-section schedule-section" style={{ marginBottom: "2rem" }}>
    <div className="section-head">
      <div>
        <div className="eyebrow">AUTOMATION & DISPATCH</div>
        <h2>Centralized Schedules</h2>
      </div>
      <span className="privacy-note">LOCAL TIME · MULTI-DISPATCH</span>
    </div>
    <p className="form-message" style={{ margin: "0 0 1rem" }}>
      Dynamic execution schedules for all profiles in your local system time. Add multiple daily dispatch runs per profile or toggle/remove them at any time.
    </p>
    {schedulesResource.status === "loading" ? <Loading /> : schedulesResource.status === "error" ? <ErrorMessage message={schedulesResource.message} /> : (
      <div className="profile-schedules-list" style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
        {Object.keys(profilesMap).length === 0 ? <p className="privacy-note">No profiles configured.</p> : Object.values(profilesMap).map((group) => {
          return (
            <ProfileScheduleGroupCard
              key={group.profile_id}
              group={group}
              onSaved={() => { reloadSchedules(); onScheduleChange?.(); }}
            />
          );
        })}
      </div>
    )}
  </section>;
}

function ProfileScheduleGroupCard({
  group,
  onSaved,
}: {
  group: { profile_id: string; profile_name: string; is_active: boolean; rules: ProfileScheduleItem[] };
  onSaved: () => void;
}) {
  const [isActive, setIsActive] = useState(Boolean(group.is_active));
  const [saving, setSaving] = useState(false);
  const [newTime, setNewTime] = useState("06:00");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function handleToggleActive() {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const nextActive = !isActive;
      await toggleActiveProfile(group.profile_id, nextActive);
      setIsActive(nextActive);
      setMessage(nextActive ? "Profile activated." : "Profile deactivated.");
      onSaved();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to toggle profile activation");
    } finally {
      setSaving(false);
    }
  }

  async function handleAddRule() {
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(newTime)) {
      setError("Use HH:MM in 24-hour time.");
      return;
    }
    setSaving(true);
    setError("");
    setMessage("");
    try {
      await addProfileScheduleRule(group.profile_id, { local_time: newTime, enabled: true });
      setMessage(`Added run at ${newTime}.`);
      onSaved();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to add schedule run");
    } finally {
      setSaving(false);
    }
  }

  async function handleUpdateRule(ruleId: string, updates: { local_time?: string; enabled?: boolean }) {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      await updateProfileScheduleRule(group.profile_id, ruleId, updates);
      setMessage("Schedule updated.");
      onSaved();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to update schedule rule");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteRule(ruleId: string) {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      await deleteProfileScheduleRule(group.profile_id, ruleId);
      setMessage("Schedule run removed.");
      onSaved();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to remove schedule run");
    } finally {
      setSaving(false);
    }
  }

  return <div style={{ border: "1px solid var(--border-color, #2a2e39)", borderRadius: "8px", padding: "1.25rem", background: "var(--card-bg, rgba(255,255,255,0.02))" }}>
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem", flexWrap: "wrap", gap: "0.5rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
        <strong style={{ fontSize: "1.1rem" }}>{group.profile_name}</strong>
        <span className={`table-status ${isActive ? "active" : "queued"}`}>{isActive ? "Active" : "Inactive"}</span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <button className={isActive ? "ghost-button" : "command-button"} style={{ fontSize: "0.8rem", padding: "4px 10px" }} disabled={saving} onClick={() => void handleToggleActive()}>
          {isActive ? "Deactivate Profile" : "Activate Profile"}
        </button>
      </div>
    </div>

    <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
      {group.rules.filter((rule) => rule.rule_id).map((rule) => {
        const ruleId = rule.rule_id!;
        const timeVal = rule.local_time ?? "";
        const isEnabled = rule.enabled;
        return (
          <ScheduleRuleRow
            key={`${ruleId}-${timeVal}-${isEnabled}`}
            label={`${group.profile_name} ${timeVal}`}
            timeVal={timeVal}
            isEnabled={isEnabled}
            dueAt={rule.due_at}
            isActive={isActive}
            disabled={saving}
            onUpdate={(updates) => void handleUpdateRule(ruleId, updates)}
            onDelete={() => void handleDeleteRule(ruleId)}
          />
        );
      })}
    </div>

    <div style={{ marginTop: "1rem", paddingTop: "0.75rem", borderTop: "1px solid var(--border-color, rgba(255,255,255,0.06))", display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
      <span style={{ fontSize: "0.85rem", opacity: 0.85 }}>Add Run Time:</span>
      <input aria-label={`New Run time for ${group.profile_name}`} type="time" step={60} value={newTime} disabled={saving} onChange={(e) => setNewTime(e.target.value.slice(0, 5))} style={{ padding: "4px 8px", fontSize: "0.85rem" }} />
      <button aria-label={`Add schedule for ${group.profile_name}`} className="command-button" style={{ fontSize: "0.8rem", padding: "4px 10px", display: "flex", alignItems: "center", gap: "4px" }} disabled={saving} onClick={() => void handleAddRule()}>
        <Plus size={14} /> Add Schedule
      </button>
      {message && <span style={{ color: "#4ade80", fontSize: "0.85rem", marginLeft: "auto" }}>{message}</span>}
      {error && <span role="alert" style={{ color: "#f87171", fontSize: "0.85rem", marginLeft: "auto" }}>{error}</span>}
    </div>
  </div>;
}

function ScheduleRuleRow({
  label,
  timeVal,
  isEnabled,
  dueAt,
  isActive,
  disabled,
  onUpdate,
  onDelete,
}: {
  label: string;
  timeVal: string;
  isEnabled: boolean;
  dueAt: string | null;
  isActive: boolean;
  disabled: boolean;
  onUpdate: (updates: { local_time?: string; enabled?: boolean }) => void;
  onDelete: () => void;
}) {
  const [currentTime, setCurrentTime] = useState(timeVal);
  const [error, setError] = useState("");

  return <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", background: "rgba(255,255,255,0.03)", padding: "0.5rem 0.75rem", borderRadius: "6px", gap: "1rem", flexWrap: "wrap" }}>
    <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
      <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.88rem", cursor: "pointer" }}>
        <input aria-label={`Enable schedule ${label}`} type="checkbox" checked={isEnabled} disabled={disabled} onChange={(e) => onUpdate({ enabled: e.target.checked })} />
        Enabled
      </label>
      <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
        <Clock size={15} style={{ opacity: 0.7 }} />
        <input aria-label={`Run time ${label}`} type="time" step={60} value={currentTime} disabled={disabled} onChange={(e) => { setCurrentTime(e.target.value.slice(0, 5)); setError(""); }} style={{ padding: "3px 6px", fontSize: "0.85rem" }} />
        <button className="ghost-button" aria-label={`Save time ${label}`} disabled={disabled || currentTime === timeVal} onClick={() => {
          if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(currentTime)) { setError("Use HH:MM in 24-hour time."); return; }
          onUpdate({ local_time: currentTime });
        }}>Save time</button>
        {error && <span className="field-error" role="alert">{error}</span>}
      </div>
      <span style={{ fontSize: "0.8rem", color: "var(--muted-color, #888)" }}>
        {dueAt && isEnabled && isActive ? `Next: ${formatDate(dueAt)}` : "Inactive or Disabled"}
      </span>
    </div>
    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
      <button className="icon-button" aria-label={`Delete schedule ${label}`} title="Delete this schedule run" disabled={disabled} onClick={onDelete} style={{ color: "var(--danger-color, #f87171)" }}>
        <Trash2 size={15} />
      </button>
    </div>
  </div>;
}

function ProfileEditor({ initial, item, onSaved }: { initial: JsonObject; item?: ContentProfileItem; onSaved: (item: ContentProfileItem | undefined, notice: string) => void }) {
  const brandingFolder = text(initial.branding_folder);
  const [draft, setDraft] = useState({ ...initial, env_prefix: initial.env_prefix ?? null } as EditorObject);
  const [hadQuality] = useState(() => isEditorObject(initial.research) && "publisher_quality" in initial.research);
  const [qualityRows, setQualityRows] = useState<QualityRow[]>(() => readQualityRows(initial.research as EditorValue | undefined));
  const [name, setName] = useState(item?.name ?? "");
  const [newName, setNewName] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const deleteButton = useRef<HTMLButtonElement>(null);
  const research = isEditorObject(draft.research) ? draft.research : {};

  async function perform(action: "save" | "create" | "activate" | "deactivate" | "delete") {
    setMessage("");
    const profile = composeProfile(draft, qualityRows, hadQuality);
    const validation = action === "save" || action === "create" ? { ...validateProfile(draft), ...validateResearch(draft.research, qualityRows) } : {};
    if ((action === "create" && !newName.trim()) || (action === "save" && item && !name.trim())) validation.form = "Enter a profile name.";
    setErrors(validation);
    if (Object.keys(validation).length) return;
    setSaving(true);
    try {
      let saved: ContentProfileItem | undefined = item;
      if (action === "create") saved = await createContentProfile({ name: newName.trim(), profile: profile as JsonObject });
      if (action === "save") {
        if (item) saved = await saveContentProfile(item.id, { name: name.trim(), profile: profile as JsonObject });
        else await updateContentProfile(profile as JsonObject);
      }
      if (action === "activate" && item) saved = await activateContentProfile(item.id);
      if (action === "deactivate" && item) saved = await toggleActiveProfile(item.id, false);
      if (action === "delete" && item) { await deleteContentProfile(item.id); saved = undefined; }
      onSaved(saved, action === "activate" ? "Content Profile activated. New Runs will use this profile." : action === "deactivate" ? "Content Profile deactivated." : action === "delete" ? "Content Profile deleted." : "Content Profile saved.");
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
    {item && brandingFolder && <div className="field">
      <label htmlFor="profile-branding-folder">Branding folder</label>
      <input id="profile-branding-folder" value={`branding/${brandingFolder}`} readOnly />
      <small>Generate this profile's branding from the repository root: <code>uv run clipfactory branding branding/{brandingFolder}</code></small>
    </div>}
    <ObjectEditor value={Object.fromEntries(Object.entries(draft).filter(([key]) => !profileOwnedElsewhere.has(key)))} onChange={(next) => setDraft({ ...draft, ...next })} errors={errors} />
    <ProfileResearchSection
      research={research}
      onChange={(next) => setDraft({ ...draft, research: next })}
      qualityRows={qualityRows}
      onQualityRowsChange={setQualityRows}
      errors={errors}
      limits={<ObjectEditor value={Object.fromEntries(Object.entries(research).filter(([key]) => !(researchListKeys as readonly string[]).includes(key)))} onChange={(next) => setDraft({ ...draft, research: { ...research, ...next } })} errors={errors} prefix="research" />}
    />
    {errors.form && <p className="field-error" role="alert">{errors.form}</p>}
    <FormFooter saving={saving} message={message} onSave={() => void perform("save")} />
    <div className="profile-create"><div className="field"><label htmlFor="new-profile-name">New profile name</label><input id="new-profile-name" value={newName} onChange={(event) => setNewName(event.target.value)} /></div><button className="ghost-button" disabled={saving} onClick={() => void perform("create")}>Save as new profile</button></div>
    {confirmDelete && <div className="profile-confirm" role="alertdialog" aria-modal="false" aria-labelledby="delete-profile-title"><h3 id="delete-profile-title">Delete {item?.name}?</h3><p>This removes the saved profile and cannot be undone.</p><button className="danger-button" autoFocus disabled={saving} onClick={() => void perform("delete")}>Confirm delete</button><button className="ghost-button" disabled={saving} onClick={() => { setConfirmDelete(false); deleteButton.current?.focus(); }}>Cancel</button></div>}
  </section>;
}

/** Profile keys edited by dedicated controls (schedules, read-only branding, Research section). */
const profileOwnedElsewhere = new Set(["schedule", "schedules", "branding_folder", "research"]);
/** Settings sections that belong to the selected Content Profile and are never offered here. */
const profileOwnedSettings = new Set(["research"]);

export function SettingsPage() {
  const [resource, reload] = useResource<unknown>("/api/settings");
  const payload = resource.status === "success" ? record(resource.data) : {};
  const settings = record(payload.settings);
  return <Page title="Settings" eyebrow="SYSTEM / 07" lede="Runtime policy and configuration. Credentials remain environment-only." action={<IconButton label="Refresh settings" onClick={reload} />}>
    {resource.status === "loading" ? <Loading /> : resource.status === "error" ? <ErrorMessage message={resource.message} /> : <>
      <div className="settings-stack">{Object.entries(settings).filter(([section, value]) => isEditorObject(value) && !profileOwnedSettings.has(section)).sort(([left], [right]) => Number(right === "environment") - Number(left === "environment")).map(([section, value]) => <Collapsible key={section} title={humanize(section)}><SettingsSection name={section} initial={record(value)} onSaved={reload} /></Collapsible>)}</div>
    </>}
  </Page>;
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
    <ObjectEditor value={draft} onChange={setDraft} errors={errors} prefix={name} collapsibleGroups />
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
    <div id="clip-results" role="tabpanel" aria-labelledby={`clip-tab-${filter}`}>{clips.status === "loading" ? <Loading /> : clips.status === "error" ? <ErrorMessage message={clips.message} /> : clips.data.items.length ? <div className="clip-list">{clips.data.items.map((clip) => <ClipCard key={clip.id} clip={clip} currency={currency} onModified={reload} />)}</div> : <Empty message="No Clips match this filter." />}</div>
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
      <div className="pending-copy"><h3>{clip.story_title || "Untitled Clip"}</h3><p>{metadataSummary(clip.social_metadata)}</p><PublicationBadges clip={clip} />{canApproveClip(clip) && <><Countdown dueAt={clip.auto_publish_due_at} /><div className="approval-actions"><button className="command-button" disabled={busy === clip.id} aria-label={`Approve ${clip.story_title || "Clip"}`} onClick={() => void decide(clip, "approve")}><Check size={15} />Approve</button><button className="danger-button" disabled={busy === clip.id} aria-label={`Reject ${clip.story_title || "Clip"}`} onClick={() => void decide(clip, "reject")}><X size={15} />Reject</button></div></>}</div>
    </article>)}</div> : <Empty message="No Clips are awaiting approval." />}
  </section>;
}

export function GoalsPage() {
  const [resource, reload] = useResource<GoalsResponse>("/api/goals");
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function handleRefresh() {
    setRefreshing(true);
    setMessage(null);
    try {
      await refreshGoals();
      reload();
      setMessage("Monetization goals refreshed.");
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "Failed to refresh goals");
    } finally {
      setRefreshing(false);
    }
  }

  const goal = resource.status === "success" ? resource.data.goal : null;

  return (
    <Page
      title="Obtain Monetization"
      eyebrow="TARGETS / 06"
      lede="Milestones and policy restrictions required to unlock monetization across eligible platforms."
      action={
        <div className="board-head-actions">
          {goal && <span className="event-count">UPDATED {formatDate(goal.updated_at)}</span>}
          <button
            className="icon-button"
            onClick={() => void handleRefresh()}
            disabled={refreshing}
            title="Update goals"
            aria-label="Update goals"
          >
            <RefreshCw size={17} className={refreshing ? "spinning" : ""} />
          </button>
        </div>
      }
    >
      {message && <p className="form-message" role="status">{message}</p>}
      {resource.status === "loading" ? (
        <Loading />
      ) : resource.status === "error" ? (
        <ErrorMessage message={resource.message} />
      ) : goal ? (
        <div className="goals-board">
          <div className="goals-grid">
            {goal.platforms.map((platform) => (
              <PlatformGoalCard key={platform.platform} platform={platform} />
            ))}
          </div>
        </div>
      ) : (
        <Empty message="No monetization goals configured." />
      )}
    </Page>
  );
}

function PlatformGoalCard({ platform }: { platform: PlatformGoal }) {
  return (
    <article className="section-block goal-card" aria-label={`${platform.name} Monetization Goal`}>
      <div className="goal-card-header">
        <div>
          <div className="eyebrow">{platform.name.toUpperCase()}</div>
          <h2>{platform.program}</h2>
        </div>
        <span className={`table-status ${platform.status === "deferred" ? "deferred" : "published"}`}>
          {platform.status === "deferred" ? "Deferred" : `${platform.progress_pct}% Complete`}
        </span>
      </div>

      <div className="goal-overall-progress">
        <div className="goal-progress-bar">
          <div
            className="goal-progress-fill"
            style={{ width: `${Math.min(100, Math.max(0, platform.progress_pct))}%` }}
          />
        </div>
        <div className="goal-progress-meta">
          <span>{platform.published_clips} {platform.published_clips === 1 ? "Clip published" : "Clips published"}</span>
          <span>{platform.progress_pct}% toward partner qualification</span>
        </div>
      </div>

      <div className="goal-metrics-section">
        <div className="section-subhead">Milestones & Requirements</div>
        <div className="goal-metrics-grid">
          {platform.metrics.map((metric) => (
            <div className="goal-metric-box" key={metric.id}>
              <div className="metric-header">
                <span className="metric-label">{metric.label}</span>
                <span className="metric-fraction">
                  {displayMetric(metric.current)} / {displayMetric(metric.target)} {metric.unit}
                </span>
              </div>
              <div className="goal-mini-bar">
                <div
                  className="goal-mini-fill"
                  style={{ width: `${Math.min(100, Math.max(0, metric.pct))}%` }}
                />
              </div>
              <div className="metric-footer">
                <span>{metric.pct}%</span>
                {metric.target_tier1 ? (
                  <span className="tier1-hint">Tier 1: {displayMetric(metric.target_tier1)}</span>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="goal-restrictions-section">
        <div className="section-subhead">Restrictions & Policy Checklist</div>
        <ul className="goal-restrictions-list">
          {platform.restrictions.map((restriction) => (
            <li className="goal-restriction-item" key={restriction.id}>
              <div className="restriction-status-col">
                {restriction.status === "compliant" && (
                  <span className="badge-compliant" title="Compliant"><ShieldCheck size={16} /></span>
                )}
                {restriction.status === "verified" && (
                  <span className="badge-verified" title="Verified"><Check size={16} /></span>
                )}
                {restriction.status === "pending_action" && (
                  <span className="badge-pending" title="Action Required"><AlertCircle size={16} /></span>
                )}
                {restriction.status === "deferred" && (
                  <span className="badge-deferred" title="Deferred"><Clock size={16} /></span>
                )}
              </div>
              <div className="restriction-copy">
                <strong>{restriction.title}</strong>
                <p>{restriction.description}</p>
              </div>
              <div className="restriction-badge-col">
                <span className={`restriction-badge ${restriction.status}`}>
                  {restriction.status === "compliant"
                    ? "Compliant"
                    : restriction.status === "verified"
                    ? "Verified"
                    : restriction.status === "pending_action"
                    ? "Action Needed"
                    : "Deferred"}
                </span>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </article>
  );
}

function canApproveClip(clip: Clip): boolean {
  return clip.status === "approved"
    && clip.publications.some((publication) => publication.status === "awaiting_approval")
    && !clip.publications.some((publication) => publication.status === "published");
}

function ClipActions({ clip, onModified }: { clip: Clip; onModified?: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const canDecide = canApproveClip(clip);

  async function handleDecision(decision: "approve" | "reject") {
    setBusy(decision);
    setMessage(null);
    try {
      await decideApproval(clip.id, { decision });
      setMessage(`${clip.story_title || "Clip"} ${decision === "approve" ? "approved" : "rejected"}.`);
      onModified?.();
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "Approval decision failed");
    } finally {
      setBusy(null);
    }
  }

  async function handleDelete() {
    if (!window.confirm(`Are you sure you want to delete "${clip.story_title || "Untitled Clip"}"?`)) {
      return;
    }
    setBusy("delete");
    setMessage(null);
    try {
      await deleteClip(clip.id);
      onModified?.();
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "Delete failed");
      setBusy(null);
    }
  }

  return (
    <div className={`clip-actions-bar${canDecide || message ? "" : " delete-only"}`} aria-label={`Actions for ${clip.story_title || "Clip"}`}>
      {canDecide && <div className="clip-actions-buttons">
        <button
          className="command-button action-approve"
          disabled={busy !== null}
          aria-label={`Approve ${clip.story_title || "Clip"}`}
          onClick={() => void handleDecision("approve")}
        >
          <Check size={14} />Approve
        </button>
        <button
          className="danger-button action-reject"
          disabled={busy !== null}
          aria-label={`Reject ${clip.story_title || "Clip"}`}
          onClick={() => void handleDecision("reject")}
        >
          <X size={14} />Reject
        </button>
      </div>}
      <button
          className="icon-button clip-delete"
          disabled={busy !== null}
          aria-label={`Delete ${clip.story_title || "Clip"}`}
          title={`Delete ${clip.story_title || "Clip"}`}
          onClick={() => void handleDelete()}
        >
          <Trash2 size={16} />
        </button>
      {message && <span className="clip-action-feedback" role="status">{message}</span>}
    </div>
  );
}

function ClipCard({ clip, currency, onModified }: { clip: Clip; currency: string | null; onModified?: () => void }) {
  return <article className="section-block clip-card"><ClipPreview clip={clip} /><div className="clip-card-copy"><div className="section-head"><div><span className={`table-status ${clip.status}`}>{humanize(clip.status)}</span><h2><NavLink to={`/clips/${clip.id}`}>{clip.story_title || "Untitled Clip"}</NavLink></h2></div><span className="table-date">{formatDate(clip.created_at)}</span></div><div className="clip-facts"><span>{formatCost(clip.cost_total, currency)}</span><span>{Math.round(clip.preview.duration_seconds)} sec</span><span>{clip.preview.width}×{clip.preview.height}</span></div><PublicationList clip={clip} /><ClipActions clip={clip} onModified={onModified} /></div></article>;
}

function ClipDetail({ clip, currency, onChanged }: { clip: Clip; currency: string | null; onChanged: () => void }) {
  return <div className="clip-detail"><section className="section-block clip-detail-preview"><ClipPreview clip={clip} /><div className="clip-facts"><span>{formatCost(clip.cost_total, currency)}</span><span>{Math.round(clip.preview.duration_seconds)} sec · {clip.preview.width}×{clip.preview.height} · {clip.preview.fps} fps</span><NavLink className="text-link" to={`/runs/${clip.run_id}`}>Open source Run <ArrowUpRight size={14} /></NavLink></div></section><section className="section-block publication-panel"><div className="section-head"><div><div className="eyebrow">DISTRIBUTION</div><h2>Publications</h2></div><RetryPublishButton clip={clip} onRetried={onChanged} /></div><PublicationList clip={clip} /><ClipActions clip={clip} onModified={onChanged} /></section></div>;
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
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  return <div className="clip-preview-container">
    <video key={clip.preview.media_url} className="clip-preview" aria-label={`Preview ${clip.story_title || "Clip"}`} controls preload="metadata" src={clip.preview.media_url} onError={() => setFailedUrl(clip.preview.media_url)} onLoadedMetadata={() => setFailedUrl(null)} />
    {failedUrl === clip.preview.media_url && <p className="form-message" role="alert">Clip video could not be loaded. Check that the media exists in the configured storage directory, then refresh.</p>}
  </div>;
}

function PublicationList({ clip }: { clip: Clip }) {
  if (!clip.publications.length) return <Empty message="No Publications recorded for this Clip." />;
  return <div className="publication-list">{clip.publications.map((publication) => {
    const unconfigured = publication.error_code === "not_configured";
    return <div className="publication-row" key={publication.id}><div><strong>{platformLabel(publication.platform)}</strong><span className={`table-status ${unconfigured ? "not-configured" : publication.status}`}><span aria-hidden="true" />{unconfigured ? "Not Configured" : humanize(publication.status)}</span></div>{!unconfigured && <><div className="publication-metrics">{publication.latest_metrics ? <><span>{displayMetric(publication.latest_metrics.views)} views</span><span>{displayMetric(publication.latest_metrics.likes)} likes</span></> : <span>Metrics n/a</span>}</div>{publication.platform_url && <a className="row-open" href={publication.platform_url} target="_blank" rel="noreferrer" aria-label={`Open ${platformLabel(publication.platform)} Publication`}><ExternalLink size={15} /></a>}{publication.error_message && <small>{publication.error_message}</small>}</>}</div>;
  })}</div>;
}

function PublicationBadges({ clip }: { clip: Clip }) {
  return <div className="publication-badges">{clip.publications.map((publication) => <span key={publication.id} className={`table-status ${publication.error_code === "not_configured" ? "not-configured" : publication.status}`}>{platformLabel(publication.platform)} · {publication.error_code === "not_configured" ? "Not Configured" : humanize(publication.status)}</span>)}</div>;
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

/** Bounds and guidance for numeric fields whose ranges are specified (18-configuration, CF-REQ-551). */
const hints: Record<string, { min?: number; max?: number; step?: number; help?: string }> = {
  "research.max_candidate_articles": { min: 1, max: 50, step: 1 },
  "research.min_sources": { min: 1, step: 1 },
  "research.preferred_independent_sources": { min: 1, step: 1 },
  "research.max_article_age_hours": { min: 1, step: 1 },
  "research.max_article_bytes": { min: 1, step: 1, help: "Largest article download accepted, in bytes." },
  "research.story_novelty_window_hours": { min: 0, max: 2160, step: 1, help: "Hours during which a previously covered Story is not selected again (0–2160)." },
  "research.near_duplicate_threshold": { min: 0.5, max: 1, step: 0.01, help: "Similarity from 0.5 to 1.0 above which articles count as the same Story." },
  "research.max_additional_sources": { min: 0, max: 20, step: 1, help: "Extra Sources gathered for the selected Story (0–20)." },
};

/** Comma-separated list fields that may be null; the value is what an empty list is saved as. */
const listFields: Record<string, EditorValue> = {
  "research.allowed_publishers": null,
  "research.blocked_publishers": [],
};

function ObjectEditor({ value, onChange, errors, prefix = "", collapsibleGroups = false }: { value: EditorObject; onChange: (value: EditorObject) => void; errors: Record<string, string>; prefix?: string; collapsibleGroups?: boolean }) {
  return <div className="object-editor">{Object.entries(value).map(([key, item]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (isEditorObject(item)) {
      const nested = <ObjectEditor value={item} onChange={(next) => onChange({ ...value, [key]: next })} errors={errors} prefix={path} collapsibleGroups={collapsibleGroups} />;
      // Nested Settings groups start collapsed like their parent sections (CF-REQ-606).
      return collapsibleGroups ? <Collapsible key={key} title={humanize(key)} level={3} className="settings-group nested-group">{nested}</Collapsible> : <fieldset key={key}><legend>{humanize(key)}</legend>{nested}</fieldset>;
    }
    const id = `field-${path.replaceAll(".", "-")}`;
    if (path === "platforms") {
      const selected = Array.isArray(item) ? item : [];
      return <fieldset key={key} className="platform-options"><legend>Platforms</legend>
        {(["youtube", "instagram", "facebook", "tiktok"] as const).map((platform) => <label className="checkbox-field" key={platform}>
          <input type="checkbox" checked={selected.includes(platform)} onChange={(event) => onChange({ ...value, [key]: event.target.checked ? [...selected, platform] : selected.filter((entry) => entry !== platform) })} />
          {platformLabel(platform)}
        </label>)}
        {errors[path] && <span className="field-error" role="alert">{errors[path]}</span>}
      </fieldset>;
    }
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
    if (path === "env_prefix") {
      return <div className="field" key={key}>
        <label htmlFor={id}>Account Env Prefix</label>
        <input
          id={id}
          type="text"
          value={typeof item === "string" ? item : ""}
          placeholder="e.g. FOOTBALL (optional)"
          aria-describedby={`${id}-help`}
          onChange={(event) => {
            const val = event.target.value.trim().toUpperCase();
            onChange({ ...value, [key]: val || null });
          }}
        />
        <small id={`${id}-help`}>Account scope (e.g. <code>FOOTBALL_INSTAGRAM_ACCESS_TOKEN</code>). A configured prefix uses only its own credentials. Leave blank for the default accounts.</small>
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
    return <div className="field" key={key}><label htmlFor={id}>{humanize(key)}</label>{typeof item === "boolean" ? <input id={id} type="checkbox" checked={item} onChange={(event) => onChange({ ...value, [key]: event.target.checked })} /> : <input id={id} type={typeof item === "number" ? "number" : "text"} min={hints[path]?.min} max={hints[path]?.max} step={typeof item === "number" ? hints[path]?.step ?? "any" : undefined} aria-invalid={errors[path] ? true : undefined} aria-describedby={hints[path]?.help ? `${id}-help` : undefined} value={Array.isArray(item) ? item.join(", ") : item ?? ""} onChange={(event) => onChange({ ...value, [key]: path in listFields ? parseList(event.target.value, listFields[path] ?? null) : parseInput(event.target.value, item) })} />}{hints[path]?.help && <small id={`${id}-help`}>{hints[path]?.help}</small>} {errors[path] && <span className="field-error" role="alert">{errors[path]}</span>}</div>;
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

function validateProfile(profile: EditorObject): Record<string, string> {
  const errors: Record<string, string> = {};
  if (text(profile.env_prefix) && !/^[A-Z][A-Z0-9_]{0,63}$/.test(text(profile.env_prefix))) errors.env_prefix = "Use letters, digits and underscores, starting with a letter (up to 64 characters).";
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
function parseInput(value: string, previous: EditorValue): EditorValue { if (typeof previous === "number") return Number(value); if (Array.isArray(previous)) return value.split(",").map((item) => item.trim()).filter(Boolean); return value; }
function parseList(value: string, empty: EditorValue): EditorValue { const items = value.split(",").map((item) => item.trim()).filter(Boolean); return items.length ? items : empty; }
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