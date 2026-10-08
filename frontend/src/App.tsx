import { Activity, ArrowDownRight, ArrowUpRight, BarChart3, Clock3, FileVideo2, Images, Play, RefreshCw, Send, Settings2, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { useEffect, useState, type CSSProperties } from "react";
import { NavLink, Route, Routes, useParams } from "react-router-dom";

import type { components } from "./api/schema";
import { continueRun, patchAsset, startManualURL, startRunNow, stopRun } from "./api/client";
import { useResource } from "./hooks/useResource";
import { useRunEvents } from "./hooks/useRunEvents";
import { AnalyticsPage, ApprovalPage, ClipDetailPage, ClipsPage, PendingApprovals, ProfilePage, SettingsPage } from "./ProductionPages";
import { QualityReviewPage } from "./QualityReview";

type RunSummary = components["schemas"]["RunSummaryResponse"];
type RunDetail = components["schemas"]["RunDetailResponse"];
type Health = components["schemas"]["HealthResponse"];
type Asset = components["schemas"]["AssetResponse"];
type AssetStatus = components["schemas"]["AssetStatus"];
type BudgetSummary = components["schemas"]["BudgetSummaryResponse"];
type DashboardSummary = components["schemas"]["DashboardSummaryResponse"];

const navigation = [
  { to: "/", label: "Overview", icon: Activity, end: true },
  { to: "/runs", label: "Runs", icon: Clock3, end: false },
  { to: "/clips", label: "Clips", icon: FileVideo2, end: false },
  { to: "/analytics", label: "Analytics", icon: BarChart3, end: false },
  { to: "/assets", label: "Assets", icon: Images, end: false },
  { to: "/profile", label: "Profile", icon: SlidersHorizontal, end: false },
  { to: "/settings", label: "Settings", icon: Settings2, end: false },
];

export default function App() {
  return (
    <div className="app-frame">
      <aside className="rail">
        <a className="brand" href="/" aria-label="ClipFactory overview">
          <span className="brand-mark">CF</span>
          <span className="brand-name">ClipFactory</span>
        </a>
        <div className="rail-label">WORKSPACE</div>
        <nav className="rail-nav" aria-label="Primary navigation">
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `rail-link${isActive ? " active" : ""}`}>
              <Icon size={17} strokeWidth={1.8} aria-hidden="true" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="rail-bottom">
          <div className="signal"><span className="signal-dot" /> LOCAL INSTANCE</div>
          <span className="rail-version">v1.0.0 · SINGLE USER</span>
        </div>
      </aside>

      <main className="main-column">
        <header className="topbar">
          <div className="breadcrumb"><span>CLIPFACTORY</span><span className="crumb-slash">/</span><span>OPERATIONS</span></div>
          <div className="topbar-right"><span className="environment"><span /> DEVELOPMENT</span></div>
        </header>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:runId" element={<RunPage />} />
          <Route path="/clips" element={<ClipsPage />} />
          <Route path="/review/:revisionId" element={<QualityReviewPage />} />
          <Route path="/clips/approval" element={<ApprovalPage />} />
          <Route path="/clips/:clipId/approval" element={<ApprovalPage />} />
          <Route path="/clips/:clipId" element={<ClipDetailPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/assets" element={<AssetsPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
        <footer className="footer"><span>CLIPFACTORY OPERATIONS</span><span>LOCAL · PRIVATE</span></footer>
      </main>
    </div>
  );
}

function Dashboard() {
  const [health, reloadHealth] = useResource<Health>("/api/health");
  const [activeRun, reloadActive] = useResource<RunSummary | null>("/api/runs/active", { intervalMs: 2000 });
  const [runs, reloadRuns] = useResource<{ items: RunSummary[] }>("/api/runs?limit=10", { intervalMs: 5000 });
  const [summary, reloadSummary] = useResource<DashboardSummary>("/api/dashboard/summary");
  const [budget, reloadBudget] = useResource<BudgetSummary>("/api/budget");
  const [manualUrl, setManualUrl] = useState("");
  const [starting, setStarting] = useState<"run" | "url" | null>(null);
  const [startMessage, setStartMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const refresh = () => {
    reloadHealth();
    reloadActive();
    reloadRuns();
    reloadSummary();
    reloadBudget();
  };

  async function createRun(kind: "run" | "url") {
    setStarting(kind);
    setStartMessage(null);
    try {
      const created = kind === "run" ? await startRunNow() : await startManualURL({ url: manualUrl });
      setStartMessage({ kind: "success", text: `Run ${shortId(created.run_id)} queued` });
      if (kind === "url") setManualUrl("");
      reloadActive();
      reloadRuns();
    } catch (error: unknown) {
      setStartMessage({ kind: "error", text: error instanceof Error ? error.message : "Run could not be started" });
    } finally {
      setStarting(null);
    }
  }

  return (
    <section className="page-wrap">
      <div className="page-heading">
        <div>
          <div className="eyebrow">OPERATIONS / 01</div>
          <h1>Production desk</h1>
          <p className="page-lede">Daily signal, execution state, and recent work.</p>
        </div>
        <button className="icon-button" onClick={refresh} title="Refresh dashboard" aria-label="Refresh dashboard">
          <RefreshCw size={17} />
        </button>
      </div>

      <section className="execution-bar" aria-labelledby="execution-title">
        <div><div className="eyebrow">EXECUTION</div><h2 id="execution-title">Start a Run</h2></div>
        <button className="command-button" disabled={starting !== null} onClick={() => void createRun("run")}>
          <Play size={15} fill="currentColor" />{starting === "run" ? "Starting" : "Run Now"}
        </button>
        <form className="manual-url-form" onSubmit={(event) => { event.preventDefault(); void createRun("url"); }}>
          <label htmlFor="manual-url">Manual Source URL</label>
          <div><input id="manual-url" type="url" required maxLength={2048} value={manualUrl} onChange={(event) => setManualUrl(event.target.value)} placeholder="https://publisher.example/story" /><button className="icon-button" type="submit" disabled={starting !== null} title="Start Manual URL Run" aria-label="Start Manual URL Run"><Send size={15} /></button></div>
        </form>
        {startMessage && <div className={`start-message ${startMessage.kind}`} role="status">{startMessage.text}</div>}
      </section>

      <div className="overview-grid">
        <section className="section-block run-focus">
          <div className="section-head"><span className="eyebrow">CURRENT RUN</span><span className="section-index">01—A</span></div>
          {activeRun.status === "loading" ? <LoadingLine /> : activeRun.status === "error" ? <InlineError message={activeRun.message} /> : activeRun.data ? <ActiveRun key={activeRun.data.run_id} run={activeRun.data} /> : <IdleState />}
        </section>
        <section className="section-block system-health">
          <div className="section-head"><span className="eyebrow">SYSTEM HEALTH</span><span className="section-index">01—B</span></div>
          {health.status === "loading" ? <LoadingLine /> : health.status === "error" ? <InlineError message={health.message} /> : <HealthReadout status={health.data.status} checks={health.data.checks} />}
        </section>
      </div>

      <section className="dashboard-data-grid" aria-label="Seven day performance and budget">
        <section className="section-block dashboard-summary">
          <div className="section-head"><div><div className="eyebrow">LAST 7 DAYS</div><h2>Performance</h2></div><span className="section-index">01—C</span></div>
          {summary.status === "loading" ? <LoadingLine /> : summary.status === "error" ? <InlineError message={summary.message} /> : <DashboardKpis summary={summary.data} />}
        </section>
        <section className="section-block budget-summary">
          <div className="section-head"><div><div className="eyebrow">COST CONTROL</div><h2>Budget</h2></div><span className="section-index">01—D</span></div>
          {budget.status === "loading" ? <LoadingLine /> : budget.status === "error" ? <InlineError message={budget.message} /> : <BudgetReadout budget={budget.data} />}
        </section>
      </section>

      <PendingApprovals />

      <section className="section-block recent-section">
        <div className="section-head"><div><div className="eyebrow">EXECUTION LOG</div><h2>Recent Runs</h2></div><NavLink className="text-link" to="/runs">All Runs <ArrowUpRight size={14} /></NavLink></div>
        {runs.status === "loading" ? <LoadingLine /> : runs.status === "error" ? <InlineError message={runs.message} /> : runs.data.items.length ? <RunTable runs={runs.data.items} /> : <EmptyState />}
      </section>
    </section>
  );
}

function DashboardKpis({ summary }: { summary: DashboardSummary }) {
  return <div className="dashboard-kpis">
    <Meta label="CLIPS APPROVED" value={summary.clips_approved.toLocaleString("en-GB")} />
    <Meta label="PUBLICATIONS" value={summary.publications.toLocaleString("en-GB")} />
    <Meta label="VIEWS" value={summary.views.toLocaleString("en-GB")} />
    <div className="meta-item estimated-kpi"><span>Estimated revenue</span><strong>{summary.estimated_revenue_currency ? `${summary.estimated_revenue_currency} ${summary.estimated_revenue}` : "n/a"}</strong></div>
    <Meta label="NEXT SCHEDULED RUN" value={summary.next_scheduled_run_at ? formatDate(summary.next_scheduled_run_at) : "n/a"} />
  </div>;
}

function BudgetReadout({ budget }: { budget: BudgetSummary }) {
  return <div className="budget-readout">
    <strong>{budget.currency} {Number(budget.month_to_date_spend).toFixed(2)} of {budget.currency} {Number(budget.monthly_limit).toFixed(2)} this month</strong>
    <span>{budget.currency} {Number(budget.monthly_remaining).toFixed(2)} remaining</span>
    <span>{budget.currency} {Number(budget.per_clip_limit).toFixed(2)} per Clip limit</span>
  </div>;
}

function RunsPage() {
  const [status, setStatus] = useState("");
  const query = new URLSearchParams({ limit: "100" });
  if (status) query.set("status", status);
  const [resource, reload] = useResource<{ items: RunSummary[] }>(`/api/runs?${query.toString()}`);
  return (
    <section className="page-wrap">
      <div className="page-heading">
        <div><div className="eyebrow">OPERATIONS / 02</div><h1>Run history</h1><p className="page-lede">Research and production attempts recorded by this instance.</p></div>
        <button className="icon-button" onClick={reload} title="Refresh Runs" aria-label="Refresh Runs"><RefreshCw size={17} /></button>
      </div>
      <div className="filter-row" role="group" aria-label="Filter Runs by status">
        {["", "queued", "running", "completed", "failed"].map((value) => (
          <button key={value || "all"} className={`filter-button${status === value ? " selected" : ""}`} onClick={() => setStatus(value)}>
            {value || "All"}
          </button>
        ))}
      </div>
      <section className="section-block recent-section">
        {resource.status === "loading" ? <LoadingLine /> : resource.status === "error" ? <InlineError message={resource.message} /> : resource.data.items.length ? <RunTable runs={resource.data.items} /> : <EmptyState />}
      </section>
    </section>
  );
}

function RunPage() {
  const { runId = "" } = useParams();
  const [resource, reload] = useResource<RunDetail>(`/api/runs/${encodeURIComponent(runId)}`, { intervalMs: 1000, while: (run) => !terminalStatuses.has(run.status) });
  return (
    <section className="page-wrap">
      <div className="page-heading">
        <div><div className="eyebrow">OPERATIONS / RUN DETAIL</div><h1>Run record</h1><p className="page-lede mono-id">{runId}</p></div>
        <button className="icon-button" onClick={reload} title="Refresh Run" aria-label="Refresh Run"><RefreshCw size={17} /></button>
      </div>
      {resource.status === "loading" ? <LoadingLine /> : resource.status === "error" ? <InlineError message={resource.message} /> : <RunDetailView key={`${runId}:${resource.data.events.filter((event) => event.type === "run_resumed").at(-1)?.sequence ?? 0}`} run={resource.data} reload={reload} />}
    </section>
  );
}

function AssetsPage() {
  const [status, setStatus] = useState<AssetStatus | "all">("active");
  const [mediaType, setMediaType] = useState("all");
  const [origin, setOrigin] = useState("all");
  const [provider, setProvider] = useState("all");
  const query = new URLSearchParams({ limit: "500" });
  if (status !== "all") query.set("status", status);
  const [resource, reload] = useResource<{ items: Asset[] }>(`/api/assets?${query.toString()}`);
  const [updating, setUpdating] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const assets = resource.status === "success" ? resource.data.items : [];
  const providers = [...new Set(assets.map((asset) => String(asset.provenance.provider ?? "unknown")))].sort();
  const providerOptions = provider !== "all" && !providers.includes(provider) ? [...providers, provider].sort() : providers;
  const visibleAssets = assets.filter((asset) =>
    (mediaType === "all" || asset.media_type === mediaType)
    && (origin === "all" || asset.provenance.origin === origin)
    && (provider === "all" || String(asset.provenance.provider ?? "unknown") === provider));
  const selected = visibleAssets.find((asset) => asset.id === selectedId);

  async function changeStatus(assetId: string, nextStatus: AssetStatus) {
    setUpdating(assetId);
    setActionError(null);
    try {
      await patchAsset(assetId, { status: nextStatus });
      reload();
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : "Asset update failed");
    } finally {
      setUpdating(null);
    }
  }

  return (
    <section className="page-wrap">
      <div className="page-heading">
        <div><div className="eyebrow">LIBRARY / 03</div><h1>Asset ledger</h1><p className="page-lede">Reusable media and provenance recorded by ClipFactory.</p></div>
        <button className="icon-button" onClick={reload} title="Refresh Assets" aria-label="Refresh Assets"><RefreshCw size={17} /></button>
      </div>
      <div className="filter-row" role="group" aria-label="Filter Assets by status">
        {(["active", "quarantined", "retired", "all"] as const).map((value) => <button key={value} className={`filter-button${status === value ? " selected" : ""}`} onClick={() => setStatus(value)}>{value}</button>)}
      </div>
      <div className="asset-filters" role="group" aria-label="Filter loaded Assets">
        <label>Media type<select value={mediaType} onChange={(event) => setMediaType(event.target.value)}><option value="all">All media</option>{["video", "image", "audio"].map((value) => <option key={value} value={value}>{humanize(value)}</option>)}</select></label>
        <label>Origin<select value={origin} onChange={(event) => setOrigin(event.target.value)}><option value="all">All origins</option>{["generated", "external", "imported", "rendered"].map((value) => <option key={value} value={value}>{humanize(value)}</option>)}</select></label>
        <label>Provider<select value={provider} onChange={(event) => setProvider(event.target.value)}><option value="all">All providers</option>{providerOptions.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}</select></label>
        <button className="filter-button" onClick={() => { setMediaType("all"); setOrigin("all"); setProvider("all"); }}>Reset filters</button>
      </div>
      {actionError && <InlineError message={actionError} />}
      {selected && <AssetPreview key={selected.id} asset={selected} onClose={() => setSelectedId(null)} />}
      <section className="section-block asset-section">
        <div className="section-head"><div><div className="eyebrow">CONTENT-ADDRESSED FILES</div><h2>Stored Assets</h2></div><span className="event-count">{resource.status === "success" ? `${visibleAssets.length} OF ${assets.length} LOADED` : "—"}</span></div>
        {assets.length === 500 && <p className="form-message">Showing the latest 500 Assets for this status. Filters apply to these loaded Assets.</p>}
        {resource.status === "loading" ? <LoadingLine /> : resource.status === "error" ? <InlineError message={resource.message} /> : visibleAssets.length ? <AssetTable assets={visibleAssets} updating={updating} onStatus={changeStatus} onPreview={setSelectedId} /> : <EmptyState message="No Assets match the selected filters." />}
      </section>
    </section>
  );
}

function AssetPreview({ asset, onClose }: { asset: Asset; onClose: () => void }) {
  const [failed, setFailed] = useState(false);
  const url = `/api/assets/${encodeURIComponent(asset.id)}/file`;
  const location = asset.storage_path ?? asset.storage_key;
  const slash = location.lastIndexOf("/");
  return <section className="section-block asset-preview" aria-label="Asset preview">
    <div className="section-head"><div><div className="eyebrow">ASSET PREVIEW</div><h2>{asset.description || "Untitled Asset"}</h2></div><button className="filter-button" onClick={onClose}>Close preview</button></div>
    <div className="asset-preview-grid">
      <div className="asset-preview-media">
        {asset.media_type === "video" ? <video aria-label={asset.description || "Asset video"} className="clip-preview" controls preload="metadata" src={url} onError={() => setFailed(true)} />
          : asset.media_type === "image" ? <img className="asset-preview-image" src={url} alt={asset.description || "Asset image"} onError={() => setFailed(true)} />
          : asset.media_type === "audio" ? <audio aria-label={asset.description || "Asset audio"} controls preload="metadata" src={url} onError={() => setFailed(true)} />
          : <InlineError message="Preview is unavailable for this media type." />}
        {failed && <div role="alert"><InlineError message="Asset media could not be loaded. The file may be missing or unsupported by your browser." /></div>}
      </div>
      <div className="asset-preview-info">
        <dl className="asset-location"><dt>{asset.storage_path ? "Local folder" : "Folder relative to DATA_DIR"}</dt><dd>{slash < 0 ? "." : location.slice(0, slash)}</dd><dt>Filename</dt><dd>{location.slice(slash + 1)}</dd><dt>Storage key</dt><dd>{asset.storage_key}</dd></dl>
        <div className="run-meta-grid"><Meta label="TYPE" value={`${asset.media_type} / ${asset.category}`} /><Meta label="PROVIDER" value={String(asset.provenance.provider ?? "n/a")} /><Meta label="LICENCE" value={String(asset.provenance.license ?? "n/a")} /><Meta label="SIZE" value={`${(asset.size_bytes / 1024 / 1024).toFixed(2)} MB`} /></div>
        {typeof asset.width === "number" && typeof asset.height === "number" && <p>{asset.width} × {asset.height}</p>}
        {typeof asset.duration_seconds === "number" && <p>{asset.duration_seconds.toFixed(2)} seconds</p>}
        {typeof asset.provenance.attribution_text === "string" && <p>{asset.provenance.attribution_text}</p>}
        <a className="inline-action" href={url} target="_blank" rel="noreferrer">Open media file <ArrowUpRight size={15} /></a>
      </div>
    </div>
  </section>;
}

function AssetTable({ assets, updating, onStatus, onPreview }: { assets: Asset[]; updating: string | null; onStatus: (assetId: string, status: AssetStatus) => Promise<void>; onPreview: (assetId: string) => void }) {
  return (
    <div className="run-table-wrap">
      <table className="run-table asset-table"><thead><tr><th>ASSET</th><th>TYPE</th><th>STATUS</th><th>LICENCE</th><th>USES</th><th>ACTIONS</th></tr></thead>
        <tbody>{assets.map((asset) => <tr key={asset.id}><td><strong className="asset-title">{asset.description}</strong><span className="asset-hash">{asset.sha256.slice(0, 12)} · {String(asset.provenance.provider ?? "unknown")}</span><span className="asset-storage-key">{asset.storage_key}</span></td><td>{asset.media_type} / {asset.category}</td><td><span className={`table-status ${asset.status}`}><span />{asset.status}</span></td><td>{String(asset.provenance.license ?? "unknown")}</td><td>{asset.usage_count}</td><td className="asset-actions"><button onClick={() => onPreview(asset.id)} aria-label={`Preview ${asset.description || "Asset"}`}>Preview</button>{asset.status === "active" && <><button disabled={updating === asset.id} onClick={() => void onStatus(asset.id, "quarantined")}>Quarantine</button><button disabled={updating === asset.id} onClick={() => void onStatus(asset.id, "retired")}>Retire</button></>}</td></tr>)}</tbody>
      </table>
    </div>
  );
}

function ActiveRun({ run }: { run: RunSummary }) {
  const { events } = useRunEvents(run.run_id);
  const now = useNow();
  const started = Date.parse(run.started_at ?? run.created_at);
  const latest = events.filter((event) => event.payload.generation_phase !== "heartbeat").at(-1);
  return (
    <div className="active-run-body">
      <div className="run-title-line"><span className={`status-mark ${run.status}`} /><span className="run-state">{run.status}</span><span className="run-attempt">ATTEMPT {run.attempt}</span></div>
      <div className="active-run-id">{run.run_id}</div>
      <div className="run-meta-grid"><Meta label="TRIGGER" value={run.trigger} /><Meta label="STAGE" value={latestStage(events) ?? run.current_stage ?? "Queued"} /><Meta label="STARTED" value={formatDate(run.started_at ?? run.created_at)} /><Meta label="ELAPSED" value={Number.isNaN(started) ? "—" : formatElapsed(now - started)} /></div>
      {latest && <p className="active-run-message" role="status"><strong>{humanize(latest.type)}</strong> {latest.message}</p>}
      <NavLink to={`/runs/${run.run_id}`} className="inline-action">Inspect Run <ArrowUpRight size={15} /></NavLink>
    </div>
  );
}

function HealthReadout({ status, checks }: { status: string; checks: Record<string, boolean | string | null> }) {
  const entries = Object.entries(checks);
  return (
    <div className="health-body">
      <div className="health-summary"><span className={`health-icon ${status === "healthy" ? "ok" : "warn"}`}><ShieldCheck size={19} /></span><div><strong>{status === "healthy" ? "All systems nominal" : "Service degraded"}</strong><span>Application checks</span></div></div>
      <div className="health-list">{entries.map(([name, value]) => <div key={name} className="health-item"><span>{humanize(name)}</span><span className={`health-value ${value === true ? "ok-text" : "warn-text"}`}>{value === true ? "READY" : value === false ? "CHECK" : String(value ?? "N/A")}</span></div>)}</div>
    </div>
  );
}

function RunTable({ runs }: { runs: RunSummary[] }) {
  return (
    <div className="run-table-wrap">
      <table className="run-table"><thead><tr><th>RUN</th><th>STATUS</th><th>TRIGGER</th><th>STAGE</th><th>CREATED</th><th aria-label="Open" /></tr></thead>
        <tbody>{runs.map((run) => <tr key={run.run_id}><td><NavLink to={`/runs/${run.run_id}`} className="table-run-id">{shortId(run.run_id)}</NavLink></td><td><span className={`table-status ${run.status}`}><span />{run.status}</span>{run.failure_code && <span className="table-failure" title={run.failure_message ?? undefined}>{run.failure_code}</span>}</td><td>{run.trigger}</td><td>{run.current_stage ?? "—"}</td><td className="table-date">{formatDate(run.created_at)}</td><td><NavLink aria-label={`Open Run ${shortId(run.run_id)}`} to={`/runs/${run.run_id}`} className="row-open"><ArrowDownRight size={15} /></NavLink></td></tr>)}</tbody>
      </table>
    </div>
  );
}

function RunDetailView({ run, reload }: { run: RunDetail; reload: () => void }) {
  const now = useNow();
  const { events, connectionState } = useRunEvents(run.run_id, run.events);
  const displayEvents = events.filter((event) => event.payload.generation_phase !== "heartbeat").sort((left, right) => right.sequence - left.sequence);
  const started = run.started_at ? Date.parse(run.started_at) : NaN;
  const currentEvents = resumedEvents(events);
  const visual = currentEvents.filter((event) => event.stage === "select_assets" && event.attempt === run.attempt
    && event.payload.generation_phase !== "heartbeat"
    && typeof event.payload.segment_index === "number" && Number.isInteger(event.payload.segment_index)
    && typeof event.payload.segment_count === "number" && Number.isInteger(event.payload.segment_count)
    && event.payload.segment_index >= 0 && event.payload.segment_index < event.payload.segment_count).at(-1)?.payload;
  const visuals = visual && typeof visual.segment_index === "number" ? `${visual.segment_index + 1} / ${visual.segment_count}` : "n/a";
  const terminal = currentEvents.filter((event) => ["run_completed", "run_failed"].includes(event.type)).at(-1);
  const ended = run.finished_at ?? terminal?.created_at;
  const duration = (ended ? Date.parse(ended) : terminalStatuses.has(run.status) ? NaN : now) - started;
  const elapsed = Number.isNaN(duration) ? "n/a" : formatElapsed(duration);
  const llm = run.settings_snapshot.environment;
  const model = llm && typeof llm === "object" && "llm_model" in llm && typeof llm.llm_model === "string" ? llm.llm_model : "n/a";
  const evaluationModel = llm && typeof llm === "object" && "llm_model_evaluation" in llm && typeof llm.llm_model_evaluation === "string" ? llm.llm_model_evaluation : model;
  return (
    <div className="detail-grid">
      <section className="section-block detail-summary"><div className="section-head"><span className="eyebrow">EXECUTION</span><RunControls run={run} events={events} reload={reload} /></div><div className="run-meta-grid"><Meta label="TRIGGER" value={run.trigger} /><Meta label="ATTEMPT" value={String(run.attempt)} /><Meta label="CURRENT STAGE" value={latestStage(events) ?? run.current_stage ?? "—"} /><Meta label="VISUALS" value={visuals} /><Meta label="OUTCOME" value={run.outcome ?? "—"} /><Meta label="ELAPSED TIME" value={elapsed} /><Meta label="LLM MODEL" value={model} /><Meta label="EVALUATION MODEL" value={evaluationModel} /></div><RunProgress run={run} events={events} /><GenerationActivity run={run} events={events} />{run.failure_code && <div className="failure-box"><strong>{run.failure_code}{run.failure_stage ? ` · stage ${run.failure_stage}` : ""}</strong><p>{run.failure_message ?? "No failure message was recorded."}</p></div>}</section>
      <section className="section-block detail-events"><div className="section-head"><div><div className="eyebrow">EVENT STREAM · {connectionState.toUpperCase()}</div><h2>Run Events</h2></div><span className="event-count">{displayEvents.length} EVENTS</span></div>{displayEvents.length ? <ol className="event-list" aria-label="Run Events, newest first">{displayEvents.map((event) => <li key={event.sequence}><span className="event-sequence">{String(event.sequence).padStart(3, "0")}</span><span className="event-spine" /><div className="event-content"><div className="event-top"><strong>{humanize(event.type)}</strong><time>{formatDate(event.created_at)}</time></div><p>{event.message}</p><EventDetails payload={event.payload} />{event.stage && <span className="event-stage">{event.stage} · attempt {event.attempt}</span>}</div></li>)}</ol> : <EmptyState />}</section>
    </div>
  );
}

function RunControls({ run, events, reload }: { run: RunDetail; events: RunDetail["events"]; reload: () => void }) {
  const [confirming, setConfirming] = useState<"continue" | "stop" | null>(null);
  const [busy, setBusy] = useState(false);
  const [stopRequested, setStopRequested] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeEvents = resumedEvents(events);
  const stopping = !terminalStatuses.has(run.status) && (stopRequested || activeEvents.some((event) => event.type === "run_stop_requested"));
  async function act() {
    if (!confirming) return;
    setBusy(true);
    setError(null);
    try {
      if (confirming === "continue") {
        await continueRun(run.run_id);
        setConfirming(null);
        reload();
      } else {
        await stopRun(run.run_id);
        setStopRequested(true);
        setConfirming(null);
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : "Run action failed");
    } finally {
      setBusy(false);
    }
  }
  return <div className="run-controls">
    <div className="run-control-buttons"><span className={`table-status ${run.status}`}><span />{stopping ? "stopping" : run.status}</span>
      {run.status === "failed" && <button className="filter-button" disabled={busy} onClick={() => setConfirming("continue")}>Continue Run</button>}
      {["queued", "running"].includes(run.status) && <button className="filter-button stop-button" disabled={busy || stopping} onClick={() => setConfirming("stop")}>{stopping ? "Stopping…" : "Stop"}</button>}
    </div>
    {confirming && <div className="run-control-confirmation"><p>{confirming === "continue" ? "Continue from the saved checkpoint using current application settings? Completed work, Content Profile and retry limits are preserved. Normal approval rules still apply." : "Stop this Run now? Unfinished generation may be lost. Already imported Assets remain saved. Active GPU steps or downloads may need to return before stopping."}</p><button className="filter-button" disabled={busy} onClick={() => void act()}>{busy ? "Submitting…" : confirming === "continue" ? "Confirm Continue" : "Confirm Stop"}</button><button className="filter-button" disabled={busy} onClick={() => setConfirming(null)}>Cancel</button></div>}
    {error && <InlineError message={error} />}
  </div>;
}

function GenerationActivity({ run, events }: { run: RunDetail; events: RunDetail["events"] }) {
  events = resumedEvents(events);
  const event = events.filter((item) => typeof item.payload.generation_phase === "string" && item.payload.generation_phase !== "heartbeat").at(-1);
  if (!event) return null;
  const phase = String(event.payload.generation_phase);
  const later = events.filter((item) => item.sequence > event.sequence);
  const stopping = !terminalStatuses.has(run.status) && later.some((item) => item.type === "run_stop_requested");
  const stopped = stopping || terminalStatuses.has(run.status) || later.some((item) => ["run_failed", "run_completed", "stage_failed"].includes(item.type) || item.type === "stage_started");
  const active = !stopped && !["completed", "failed", "skipped"].includes(phase);
  const { step, total_steps: total } = event.payload;
  const counted = active && ["inference", "rendering"].includes(phase) && typeof step === "number" && typeof total === "number" && total > 0;
  const fraction = event.payload.progress_fraction;
  const renderProgress = active && phase === "rendering" && !counted && typeof fraction === "number" && Number.isFinite(fraction) && fraction >= 0 && fraction <= 1;
  return <div className={`generation-activity ${active ? "active" : ""}`} role="status" aria-label="Media generation">
    <div className="eyebrow">MEDIA GENERATION · {stopping ? "Stopping" : active ? humanize(phase) : ["completed", "failed", "skipped"].includes(phase) ? humanize(phase) : "Stopped"}</div>
    <p>{event.message}</p>
    <div className="generation-meta">{typeof event.payload.provider === "string" && <span>{event.payload.provider}</span>}{typeof event.payload.model === "string" && <span>{event.payload.model}</span>}{typeof event.payload.template === "string" && <span>{humanize(event.payload.template)}</span>}{typeof event.payload.segment_index === "number" && <span>Visual {event.payload.segment_index + 1}</span>}</div>
    {phase === "loading_model" && active && <p>Loading model weights from the shared local cache.</p>}
    {phase === "downloading_model" && active && <p>Local model files are missing or incomplete; downloading required files. Download percentage is unavailable.</p>}
    {counted && <><progress aria-label={phase === "rendering" ? "Graphics rendering" : "Generation inference"} max={total} value={step} /><span>{phase === "rendering" ? "Frame" : "Step"} {step} / {total}</span></>}
    {renderProgress && <><progress aria-label="Graphics rendering" max={1} value={fraction} /><span>{Math.round(fraction * 100)}% rendered</span></>}
  </div>;
}

const terminalStatuses = new Set(["completed", "failed"]);
function EventDetails({ payload }: { payload: Record<string, unknown> }) {
  const sections = [["Model reasoning", payload.reasoning], ["Model response", payload.response]].filter((entry): entry is [string, string] => typeof entry[1] === "string" && entry[1].length > 0);
  if (!sections.length) return null;
  return <div className="event-details">{sections.map(([label, text]) => <details key={label}><summary>{label}</summary><pre>{text}</pre></details>)}</div>;
}
const stages = ["research", "ingest_url", "cluster_stories", "select_story", "gather_sources", "extract_claims", "build_story_package", "write_script", "plan_visuals", "select_assets", "generate_narration", "transcribe_narration", "build_captions", "compose_clip", "validate_clip", "evaluate_clip", "plan_retry", "publish"];
function RunProgress({ run, events }: { run: RunDetail; events: RunDetail["events"] }) {
  events = resumedEvents(events);
  const sequence = stages.filter((stage) => run.trigger === "manual_url" ? !["research", "cluster_stories", "select_story"].includes(stage) : stage !== "ingest_url");
  const latest = events.filter((event) => event.stage).at(-1);
  const stage = latest?.stage ?? run.current_stage ?? run.failure_stage;
  const lifecycle = events.filter((event) => event.stage === stage && ["stage_started", "stage_completed", "stage_failed", "stage_skipped"].includes(event.type)).at(-1);
  const terminal = events.filter((event) => event.type === "run_completed" || event.type === "run_failed").at(-1);
  const status = terminal?.type === "run_completed" ? "completed" : terminal?.type === "run_failed" ? "failed" : run.status;
  const state = status === "failed" || lifecycle?.type === "stage_failed" ? "failed" : status === "completed" || lifecycle?.type === "stage_completed" ? "done" : lifecycle?.type === "stage_skipped" ? "skipped" : stage ? "running" : "pending";
  const index = sequence.indexOf(stage ?? "");
  const generation = events.filter((event) => event.stage === stage && event.attempt === (latest?.attempt ?? run.attempt) && typeof event.payload.generation_phase === "string" && event.payload.generation_phase !== "heartbeat").at(-1)?.payload;
  let stageFraction = state === "done" || state === "skipped" ? 1 : 0.5;
  if (stage === "select_assets" && state === "running" && generation) {
    const count = generation.segment_count;
    const shot = generation.segment_index;
    if (typeof count === "number" && count > 0 && typeof shot === "number") {
      const step = generation.step;
      const total = generation.total_steps;
      const rendering = generation.progress_fraction;
      const measured = typeof rendering === "number" && Number.isFinite(rendering) && rendering >= 0 && rendering <= 1 ? rendering : typeof step === "number" && typeof total === "number" && total > 0 ? Math.min(1, Math.max(0, step / total)) : 0;
      const fraction = generation.generation_phase === "completed" ? 1 : generation.generation_phase === "validating" ? 0.98 : generation.generation_phase === "encoding" || generation.generation_phase === "saving_frames" ? 0.95 : measured * 0.9;
      stageFraction = Math.min(0.99, Math.max(0, (shot + fraction) / count));
    }
  }
  const rawPercentage = (index + stageFraction) / sequence.length * 100;
  const percentage = status === "completed" ? 100 : index < 0 ? 0 : generation && state === "running" ? Math.round(rawPercentage * 10) / 10 : Math.round(rawPercentage);
  const label = status === "completed" ? "Completed" : stage ? humanize(stage) : "Queued";
  const attempt = latest?.attempt ?? run.attempt;
  const description = stage && status !== "completed" ? `${label} · ${state} · Attempt ${attempt}` : label;
  return (
    <div className={`run-progress ${state}`} style={{ "--progress": `${percentage}%` } as CSSProperties}>
      <div className="progress-bubble" aria-hidden="true">{label}</div>
      <div className="progress-pointer" aria-hidden="true" />
      <div className="progress-track" role="progressbar" aria-label="Run progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percentage} aria-valuetext={description}>
        <div className="progress-fill" />
      </div>
      <div className="progress-caption"><span>{state} · Attempt {attempt}</span><span>{percentage}% · stage progress</span></div>
    </div>
  );
}
function resumedEvents(events: RunDetail["events"]): RunDetail["events"] {
  const resumed = events.filter((event) => event.type === "run_resumed").at(-1)?.sequence ?? 0;
  return events.filter((event) => event.sequence >= resumed);
}
function latestStage(events: components["schemas"]["RunEventResponse"][]): string | null { return resumedEvents(events).filter((event) => event.stage).at(-1)?.stage ?? null; }

function Meta({ label, value }: { label: string; value: string }) {
  return <div className="meta-item"><span>{label}</span><strong>{value}</strong></div>;
}

function LoadingLine() { return <div className="loading-line"><span />Loading operational data</div>; }
function InlineError({ message }: { message: string }) { return <div className="inline-error">{message}</div>; }
function EmptyState({ message = "No Runs recorded yet" }: { message?: string }) { return <div className="empty-state"><FileVideo2 size={21} /><span>{message}</span></div>; }
function IdleState() { return <div className="idle-state"><span className="idle-ring"><Activity size={18} /></span><strong>Idle</strong><span>No active Run</span></div>; }
function NotFound() { return <section className="page-wrap"><div className="eyebrow">404 / NOT FOUND</div><h1>Unknown route</h1><NavLink to="/" className="text-link">Return to overview</NavLink></section>; }

function shortId(value: string): string { return value.slice(0, 8).toUpperCase(); }
function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(date);
}
function humanize(value: string): string { return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase()); }
function formatElapsed(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  if (hours) return `${hours}h ${String(minutes % 60).padStart(2, "0")}m ${String(seconds % 60).padStart(2, "0")}s`;
  return minutes ? `${minutes}m ${String(seconds % 60).padStart(2, "0")}s` : `${seconds}s`;
}
function useNow(): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  return now;
}