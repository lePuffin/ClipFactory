import { Film, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { renderSavedNews, type RenderRevision, type SavedRenderRecipe } from "./api/client";
import { useResource } from "./hooks/useResource";

export function QualityReviewPage() {
  const { revisionId } = useParams();
  const [resource, reload] = useResource<RenderRevision>(revisionId ? `/api/render-revisions/${encodeURIComponent(revisionId)}` : null);
  return <section className="page-wrap">
    <div className="page-heading"><div><div className="eyebrow">EDITORIAL REVIEW</div><h1>Quality review</h1></div>
      <button className="icon-button" onClick={reload} aria-label="Refresh quality review" title="Refresh quality review"><RefreshCw size={17} /></button>
    </div>
    {resource.status === "loading" ? <p role="status">Loading revision</p> : resource.status === "error" ? <p role="alert">{resource.message}</p> :
      <RevisionEditor key={resource.data.revision_id} revision={resource.data} />}
  </section>;
}

function RevisionEditor({ revision }: { revision: RenderRevision }) {
  const [draft, setDraft] = useState<SavedRenderRecipe>(revision.request);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const navigate = useNavigate();
  const cues = draft.overlays ?? [];

  async function rerender() {
    if (cues.some((cue) => !cue.text.trim() || cue.end_seconds <= cue.start_seconds)) {
      setMessage("Each label needs text and an end time after its start.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const result = await renderSavedNews(draft);
      navigate(`/review/${result.revision_id}`);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "Render could not be completed");
    } finally { setBusy(false); }
  }

  function editCue(index: number, field: "text" | "secondary" | "start_seconds" | "end_seconds", value: string) {
    setDraft({ ...draft, overlays: cues.map((cue, cueIndex) => cueIndex === index ? { ...cue, [field]: field.endsWith("seconds") ? Number(value) : value } : cue) });
  }

  return <>
    <div className="review-status" role="status"><span className="credential missing">Pending quality review</span><span>Not approved for publication</span></div>
    <div className="quality-review-layout">
      <section className="quality-player-column">
        <video className="quality-review-video" controls playsInline preload="metadata" aria-label="Rendered Clip preview" src={`/api/render-revisions/${revision.revision_id}/media`} />
        <dl className="quality-version-info"><dt>Revision</dt><dd>{revision.revision_id}</dd><dt>Template</dt><dd>{revision.template_version}</dd><dt>LLM / TTS calls</dt><dd>{revision.openrouter_calls} / {revision.tts_calls}</dd></dl>
        <h2>Sources</h2><ul className="quality-credits">{revision.sources.map((source) => <li key={source}>{source}</li>)}</ul>
        <h2>Media credits</h2><ul className="quality-credits">{revision.credits.length ? revision.credits.map((credit) => <li key={credit}>{credit}</li>) : <li>No attribution-required media</li>}</ul>
      </section>
      <section className="quality-label-column"><div className="section-head"><h2>Editorial labels</h2><span>{cues.length}</span></div>
        {cues.map((cue, index) => <fieldset className="quality-cue" key={index}><legend>{index + 1}. {cue.kind}</legend>
          <label>Label<input value={cue.text} maxLength={200} onChange={(event) => editCue(index, "text", event.target.value)} /></label>
          <label>Context<input value={cue.secondary ?? ""} maxLength={100} onChange={(event) => editCue(index, "secondary", event.target.value)} /></label>
          <div className="quality-cue-times"><label>Start<input type="number" min={0} step={0.1} value={cue.start_seconds} onChange={(event) => editCue(index, "start_seconds", event.target.value)} /></label>
            <label>End<input type="number" min={0} step={0.1} value={cue.end_seconds} onChange={(event) => editCue(index, "end_seconds", event.target.value)} /></label></div>
        </fieldset>)}
        <button className="command-button" disabled={busy} onClick={() => void rerender()}><Film size={16} />{busy ? "Rendering revision" : "Render revision"}</button>
        {message && <p role="alert">{message}</p>}
      </section>
    </div>
  </>;
}