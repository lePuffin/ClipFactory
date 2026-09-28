const state = {
  jobId: null,
  pollTimer: null,
  sources: [],
  sourceSequence: 0,
};

const processingStatuses = new Set([
  "INGESTING",
  "ACQUIRING",
  "EXTRACTING",
  "TRANSCRIBING",
  "ANALYZING",
  "STORY_SELECTING",
  "SCRIPTING",
  "PLANNING",
  "SYNTHESIZING",
  "RENDERING",
]);
const themeStorageKey = "clipfactory-theme";
const imageExtensions = new Set(["jpg", "jpeg", "png", "webp"]);
const videoExtensions = new Set(["mp4", "mov", "mkv", "webm", "avi", "m4v", "mpeg", "mpg"]);

const elements = {
  addArticleSource: document.querySelector("#add-article-source"),
  addUrlSource: document.querySelector("#add-url-source"),
  form: document.querySelector("#job-form"),
  formError: document.querySelector("#form-error"),
  jobState: document.querySelector("#job-state"),
  localFiles: document.querySelector("#clip-local-files"),
  narrationControls: document.querySelector("#narration-controls"),
  processButton: document.querySelector("#process-button"),
  processButtonLabel: document.querySelector("#process-button-label"),
  processPanel: document.querySelector(".process-panel"),
  progressBar: document.querySelector("#progress-bar"),
  progressMessage: document.querySelector("#progress-message"),
  progressNumber: document.querySelector("#progress-number"),
  progressTrack: document.querySelector(".progress-track"),
  clipArticleText: document.querySelector("#clip-article-text"),
  clipSourceBar: document.querySelector("#clip-source-bar"),
  clipSourceCount: document.querySelector("#clip-source-count"),
  clipSourceList: document.querySelector("#clip-source-list"),
  clipSourcePicker: document.querySelector("#clip-source-picker"),
  clipUrl: document.querySelector("#clip-url"),
  refreshJobs: document.querySelector("#refresh-jobs"),
  results: document.querySelector("#results"),
  resultsTitle: document.querySelector("#results-title"),
  runtimeStatus: document.querySelector("#runtime-status"),
  themeToggle: document.querySelector("#theme-toggle"),
  ttsEnabled: document.querySelector("#tts-enabled"),
  ttsLanguage: document.querySelector("#tts-language"),
  ttsProvider: document.querySelector("#tts-provider"),
  ttsSpeed: document.querySelector("#tts-speed"),
  ttsVoice: document.querySelector("#tts-voice"),
  workflowTitle: document.querySelector("#workflow-title"),
};

function initializeIcons() {
  if (window.lucide) {
    window.lucide.createIcons();
  }
}

function escapeHtml(value) {
  const element = document.createElement("div");
  element.textContent = value ?? "";
  return element.innerHTML;
}

function formatClipTerminology(value) {
  return value.replace(/\breels?\b/gi, (term) => {
    const replacement = term.length === 5 ? "clips" : "clip";
    return term === term.toUpperCase() ? replacement.toUpperCase() : replacement;
  });
}

function setError(message = "") {
  elements.formError.textContent = message;
  elements.formError.hidden = !message;
}

function updateNarrationControls() {
  const enabled = elements.ttsEnabled.checked;
  const supportsNamedVoice = elements.ttsProvider.value === "pyttsx3";
  elements.narrationControls.classList.toggle("is-disabled", !enabled);
  [elements.ttsProvider, elements.ttsLanguage, elements.ttsSpeed].forEach((control) => {
    control.disabled = !enabled;
  });
  elements.ttsVoice.disabled = !enabled || !supportsNamedVoice;
  elements.ttsVoice.placeholder = supportsNamedVoice
    ? "Installed system voice ID (optional)"
    : "Not available for Chatterbox Turbo";
  elements.ttsVoice.title = supportsNamedVoice
    ? "Optional exact ID of an installed local system voice"
    : "Chatterbox Turbo does not provide named voice selection";
  if (!supportsNamedVoice) {
    elements.ttsVoice.value = "";
  }
}

function applyNarrationDefaults(narration) {
  if (!narration) {
    return;
  }
  elements.ttsEnabled.checked = Boolean(narration.enabled);
  elements.ttsProvider.value = narration.provider || "chatterbox";
  elements.ttsVoice.value = narration.voice || "";
  elements.ttsLanguage.value = narration.language || "en";
  elements.ttsSpeed.value = String(narration.speed || 1);
  updateNarrationControls();
}

function setTheme(theme) {
  const isDark = theme === "dark";
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]').setAttribute("content", isDark ? "#111714" : "#f4f0e7");
  elements.themeToggle.setAttribute("aria-pressed", String(isDark));
  elements.themeToggle.setAttribute("aria-label", isDark ? "Switch to light theme" : "Switch to dark theme");
  elements.themeToggle.setAttribute("title", isDark ? "Switch to light theme" : "Switch to dark theme");
  elements.themeToggle.innerHTML = `<i data-lucide="${isDark ? "sun" : "moon"}"></i>`;
  initializeIcons();
  try {
    localStorage.setItem(themeStorageKey, theme);
  } catch {
    // The selected theme still applies when storage is unavailable.
  }
}

function initializeTheme() {
  let theme;
  try {
    theme = localStorage.getItem(themeStorageKey);
  } catch {
    theme = null;
  }
  if (theme !== "dark" && theme !== "light") {
    theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  setTheme(theme);
}

function sourceKindForFile(file) {
  const extension = file.name.split(".").pop()?.toLowerCase() || "";
  if (file.type.startsWith("image/") || imageExtensions.has(extension)) {
    return "image_file";
  }
  if (file.type.startsWith("video/") || videoExtensions.has(extension)) {
    return "video_file";
  }
  return null;
}

function addSource(source) {
  state.sourceSequence += 1;
  state.sources.push({ id: `source-${state.sourceSequence}`, ...source });
  renderSources();
  setError();
}

function addLocalFiles(files) {
  for (const file of Array.from(files || [])) {
    const kind = sourceKindForFile(file);
    if (!kind) {
      setError("Choose a supported video or image file.");
      continue;
    }
    const exists = state.sources.some(
      (source) =>
        source.kind === kind &&
        source.file.name === file.name &&
        source.file.size === file.size &&
        source.file.lastModified === file.lastModified,
    );
    if (!exists) {
      addSource({ kind, file, label: file.name });
    }
  }
  elements.localFiles.value = "";
}

function addUrlSource() {
  const value = elements.clipUrl.value.trim();
  if (!value) {
    setError("Enter a URL before adding it to the clip.");
    return;
  }
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      throw new Error();
    }
  } catch {
    setError("Enter a valid http or https URL.");
    return;
  }
  addSource({ kind: "url", value, label: value });
  elements.clipUrl.value = "";
}

function addArticleSource() {
  const value = elements.clipArticleText.value.trim();
  if (value.length < 120) {
    setError("Pasted article text must contain at least 120 characters.");
    return;
  }
  addSource({ kind: "article_text", value, label: value.slice(0, 100) });
  elements.clipArticleText.value = "";
}

function renderSources() {
  elements.clipSourceCount.textContent = state.sources.length
    ? `${state.sources.length} added`
    : "No sources yet";
  if (!state.sources.length) {
    elements.clipSourceList.innerHTML = "<li class=\"clip-source-empty\">Add a URL, local video or image, or article text.</li>";
    return;
  }
  const metadata = {
    article_text: { icon: "file-text", label: "Article text" },
    image_file: { icon: "image", label: "Local image" },
    url: { icon: "link", label: "URL" },
    video_file: { icon: "film", label: "Local video" },
  };
  elements.clipSourceList.innerHTML = state.sources
    .map((source) => {
      const detail = metadata[source.kind];
      return `
        <li class="clip-source-item">
          <div class="clip-source-info">
            <span class="clip-source-kind"><i data-lucide="${detail.icon}"></i>${detail.label}</span>
            <strong title="${escapeHtml(source.label)}">${escapeHtml(source.label)}</strong>
          </div>
          <button class="icon-button remove-source-button" type="button" data-remove-source="${source.id}"
            aria-label="Remove ${escapeHtml(detail.label)} source" title="Remove source">
            <i data-lucide="x"></i>
          </button>
        </li>`;
    })
    .join("");
  initializeIcons();
}

function updateProgress(job) {
  const progress = Math.max(0, Math.min(100, Number(job.progress) || 0));
  const isProcessing = processingStatuses.has(job.status);
  elements.progressBar.style.width = `${progress}%`;
  elements.progressNumber.textContent = `${progress}%`;
  elements.progressTrack.setAttribute("aria-valuenow", String(progress));
  elements.progressTrack.classList.toggle("is-processing", isProcessing);
  elements.processPanel.classList.toggle("is-processing", isProcessing);
  elements.jobState.textContent = job.status === "FAILED" ? "Run failed" : job.current_step;
  elements.progressMessage.textContent = job.error || job.current_step;

  const stageOrder = [
    "ACQUIRING",
    "EXTRACTING",
    "TRANSCRIBING",
    "ANALYZING",
    "STORY_SELECTING",
    "SCRIPTING",
    "PLANNING",
    "SYNTHESIZING",
    "RENDERING",
  ];
  const currentIndex = stageOrder.indexOf(job.status);
  document.querySelectorAll(".pipeline-steps li").forEach((item) => {
    const itemIndex = stageOrder.indexOf(item.dataset.stage);
    item.classList.toggle("is-active", itemIndex === currentIndex);
    item.classList.toggle("is-complete", currentIndex > itemIndex || job.status === "COMPLETED");
  });
}

function resetProgress() {
  updateProgress({ status: "CREATED", progress: 0, current_step: "Queued" });
  elements.workflowTitle.textContent = "Rough clip";
  elements.processButtonLabel.textContent = "Generate rough clip";
  elements.jobState.textContent = "Ready when you are";
  elements.progressMessage.textContent = "Add related sources to begin a clip.";
}

function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(value / 60);
  const remaining = Math.round(value % 60).toString().padStart(2, "0");
  return `${minutes}:${remaining}`;
}

function formatScore(score) {
  const value = Number(score);
  return Number.isFinite(value) ? value.toFixed(2) : "Unavailable";
}

function formatEvidence(evidence) {
  return (evidence || [])
    .map((reference) => reference.segment_id || reference.asset_id || reference.source_id)
    .map((reference) => escapeHtml(reference))
    .join(" · ");
}

function renderEmptyResults() {
  elements.resultsTitle.textContent = "Generated output";
  elements.results.innerHTML = `
    <div class="empty-results">
      <i data-lucide="video"></i>
      <p>Completed videos will appear here.</p>
    </div>`;
  initializeIcons();
}

async function renderResults(job) {
  if (job?.reel) {
    await renderClipResult(job);
    return;
  }
  if (job?.clip) {
    renderLegacyManagedClip(job);
    return;
  }
  if (job?.clips?.length) {
    renderLegacyClips(job);
    return;
  }
  renderEmptyResults();
}

async function renderClipResult(job) {
  const jobId = encodeURIComponent(job.id);
  const clipUrl = `/api/jobs/${jobId}/story-clip`;
  const planUrl = `/api/jobs/${jobId}/story-clip/plan`;
  const storyClip = job.reel;
  let plan = null;
  try {
    const response = await fetch(planUrl);
    if (response.ok) {
      plan = await response.json();
    }
  } catch {
    plan = null;
  }
  const story = plan?.story;
  const sources = story?.source_ids || [];
  const sections = plan?.script?.sections || [];
  const scenes = plan?.scenes || [];
  const sourceMaterials = plan?.sources || [];
  const editorial = plan?.editorial;
  const selectedAngle = editorial?.selected_angle;
  const selectedHook = editorial?.selected_hook;
  const narration = plan?.narration;
  const narrationRequest = job.narration_request;
  const narrationOptions = narration?.options || narrationRequest?.options;
  const narrationEnabled = narration ? true : narrationRequest?.enabled;
  elements.resultsTitle.textContent = "Generated rough clip";
  elements.results.innerHTML = `
    <article class="clip-result">
      <div class="clip-preview">
        <video controls preload="metadata" src="${clipUrl}"></video>
        <div class="clip-details">
          <div class="clip-topline">
            <span>ROUGH CLIP ${formatDuration(storyClip.duration)}</span>
            <span class="clip-score">${narrationEnabled ? `VOICE ${formatDuration(narration?.duration || storyClip.narration_duration)}` : "SILENT"}</span>
          </div>
          <h3>${escapeHtml(storyClip.title)}</h3>
          <div class="artifact-links">
            <a href="${clipUrl}?download=true" download="story_01.mp4"><i data-lucide="download"></i><span>MP4</span></a>
            <a href="${planUrl}?download=true" download="story_01.json"><i data-lucide="file-down"></i><span>JSON</span></a>
          </div>
        </div>
      </div>
      <section class="clip-inspector" aria-label="Clip plan">
        <div class="story-summary">
          <span class="section-label">SELECTED STORY</span>
          <h3>${escapeHtml(story?.title || storyClip.title)}</h3>
          <p class="story-summary-copy">${escapeHtml(story?.summary || "A source-grounded rough clip.")}</p>
          <div class="decision-grid">
            <div><span>Story score</span><strong>${escapeHtml(formatScore(story?.overall_score))}</strong></div>
            <div><span>Angle score</span><strong>${escapeHtml(formatScore(selectedAngle?.overall_score))}</strong></div>
          </div>
          <details class="selection-details">
            <summary>Why selected</summary>
            <p>${escapeHtml(formatClipTerminology(story?.selection_reason || "Story plan is loading."))}</p>
          </details>
          ${selectedAngle ? `
            <div class="angle-summary">
              <span class="section-label">SELECTED ANGLE</span>
              <strong>${escapeHtml(selectedAngle.angle)}</strong>
              <p>${escapeHtml(selectedAngle.selection_reason || selectedAngle.rationale)}</p>
            </div>` : ""}
          <div class="source-pills">${sources.map((source) => `<span>${escapeHtml(source)}</span>`).join("")}</div>
        </div>
        <details class="plan-details">
          <summary>Script</summary>
          <div class="hook-callout">
            <span>Hook</span>
            <p>${escapeHtml(selectedHook?.text || plan?.script?.hook || "Script plan is unavailable.")}</p>
          </div>
          <ol class="script-list">${sections.map((section) => `
            <li>
              <span>${escapeHtml(`${section.role}${section.statement_type ? ` · ${section.statement_type}` : ""}`)}</span>
              <p>${escapeHtml(section.text)}</p>
              <small>${formatEvidence(section.evidence)}</small>
              ${section.visual_intent ? `<small class="visual-intent">${escapeHtml(section.visual_intent)}</small>` : ""}
            </li>`).join("") || "<li><p>Script plan is unavailable.</p></li>"}</ol>
        </details>
        <details class="plan-details">
          <summary>Sources</summary>
          <ul class="source-list">${sourceMaterials.map((material) => `
            <li>
              <strong>${escapeHtml(material.source?.name || material.source?.id || "Source")}</strong>
              <small>${escapeHtml(`${material.source?.id || ""} · ${material.source?.type || ""}`)}</small>
            </li>`).join("") || "<li><p>Source plan is unavailable.</p></li>"}</ul>
        </details>
        <details class="plan-details">
          <summary>Scenes</summary>
          <ol class="scene-list">${scenes.map((scene) => `
            <li>
              <span>${escapeHtml(scene.visual.type.replaceAll("_", " "))}</span>
              <p>${escapeHtml(scene.narration)}</p>
              <small>${escapeHtml(scene.visual.reason || scene.visual.source_id || "Text card")}</small>
              <small class="visual-intent">${escapeHtml(scene.visual_intent || "")}</small>
              <small>${formatEvidence(scene.evidence)}</small>
            </li>`).join("") || "<li><p>Scene plan is unavailable.</p></li>"}</ol>
        </details>
        <details class="plan-details">
          <summary>Narration</summary>
          <div class="narration-diagnostics">
            <div><span>Status</span><strong>${narrationEnabled ? "Generated" : "Disabled"}</strong></div>
            <div><span>Provider</span><strong>${escapeHtml(narration?.provider || narrationRequest?.provider || "Unavailable")}</strong></div>
            <div><span>Voice</span><strong>${escapeHtml(narrationOptions?.voice || "Default")}</strong></div>
            <div><span>Language</span><strong>${escapeHtml(narrationOptions?.language || "en")}</strong></div>
            <div><span>Speed</span><strong>${escapeHtml(String(narrationOptions?.speed || 1))}</strong></div>
            <div><span>Duration</span><strong>${formatDuration(narration?.duration || storyClip.narration_duration)}</strong></div>
          </div>
          ${narration?.segments?.length ? `<ol class="narration-segment-list">${narration.segments.map((segment) => `
            <li><span>${escapeHtml(segment.id)}</span><strong>${formatDuration(segment.duration)}</strong><small>${escapeHtml(segment.scene_id)} · ${escapeHtml(segment.script_section_id)}</small></li>`).join("")}</ol>` : ""}
        </details>
      </section>
    </article>`;
  initializeIcons();
}

function renderLegacyManagedClip(job) {
  const jobId = encodeURIComponent(job.id);
  const clipUrl = `/api/jobs/${jobId}/clip`;
  elements.resultsTitle.textContent = "Generated clip";
  elements.results.innerHTML = `
    <article class="clip-card">
      <video controls preload="metadata" src="${clipUrl}"></video>
      <div class="clip-details">
        <div class="clip-topline">
          <span>CLIP ${formatDuration(job.clip.duration)}</span>
          <span class="clip-score">${escapeHtml(String(job.clip.source_count))} sources</span>
        </div>
        <h3>${escapeHtml(job.clip.title)}</h3>
        <a href="${clipUrl}?download=true" download="clip.mp4"><i data-lucide="download"></i><span>Download</span></a>
      </div>
    </article>`;
  initializeIcons();
}

function renderLegacyClips(job) {
  const jobId = encodeURIComponent(job.id);
  elements.resultsTitle.textContent = "Generated clips";
  elements.results.innerHTML = job.clips
    .map((clip, index) => {
      const filename = encodeURIComponent(clip.filename);
      const clipUrl = `/api/jobs/${jobId}/clips/${filename}`;
      return `
        <article class="clip-card">
          <video controls preload="metadata" src="${clipUrl}"></video>
          <div class="clip-details">
            <div class="clip-topline">
              <span>CLIP ${String(index + 1).padStart(2, "0")} ${formatDuration(clip.end - clip.start)}</span>
              <span class="clip-score">${escapeHtml(String(clip.score))}/100</span>
            </div>
            <h3>${escapeHtml(clip.title)}</h3>
            <p>${escapeHtml(clip.reason)}</p>
            <a href="${clipUrl}?download=true" download="${escapeHtml(clip.filename)}"><i data-lucide="download"></i><span>MP4</span></a>
          </div>
        </article>`;
    })
    .join("");
  initializeIcons();
}

function stopPolling() {
  if (state.pollTimer) {
    window.clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }
}

async function pollJob() {
  if (!state.jobId) {
    return;
  }
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(state.jobId)}`);
    if (!response.ok) {
      throw new Error("Unable to retrieve the current job.");
    }
    const job = await response.json();
    updateProgress(job);
    if (job.status === "COMPLETED") {
      stopPolling();
      elements.processButton.disabled = false;
      await renderResults(job);
      return;
    }
    if (job.status === "FAILED") {
      stopPolling();
      elements.processButton.disabled = false;
      setError(job.error || "The job could not be completed.");
      return;
    }
    state.pollTimer = window.setTimeout(pollJob, 1400);
  } catch (error) {
    stopPolling();
    elements.processButton.disabled = false;
    setError(error instanceof Error ? error.message : "Lost connection to the local server.");
  }
}

async function submitJob(event) {
  event.preventDefault();
  setError();
  if (!state.sources.length) {
    setError("Add at least one video, image, or article source first.");
    return;
  }
  try {
    elements.processButton.disabled = true;
    const formData = new FormData();
    for (const source of state.sources) {
      if (source.kind === "video_file") {
        formData.append("video_files", source.file);
      } else if (source.kind === "image_file") {
        formData.append("image_files", source.file);
      } else if (source.kind === "url") {
        formData.append("urls", source.value);
      } else if (source.kind === "article_text") {
        formData.append("article_texts", source.value);
      }
    }
    formData.append("tts_enabled", String(elements.ttsEnabled.checked));
    formData.append("tts_provider", elements.ttsProvider.value);
    formData.append("tts_voice", elements.ttsVoice.value.trim());
    formData.append("tts_language", elements.ttsLanguage.value.trim());
    formData.append("tts_speed", elements.ttsSpeed.value);
    const response = await fetch("/api/jobs/story-clip", { method: "POST", body: formData });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "The clip job could not be created.");
    }
    state.jobId = payload.id;
    updateProgress(payload);
    stopPolling();
    void pollJob();
  } catch (error) {
    elements.processButton.disabled = false;
    setError(error instanceof Error ? error.message : "The clip job could not be created.");
  }
}

async function refreshJobs() {
  try {
    const response = await fetch("/api/jobs");
    if (!response.ok) {
      return;
    }
    const jobs = await response.json();
    const completed = jobs.find(
      (job) => job.status === "COMPLETED" && (job.reel || job.clip || job.clips?.length),
    );
    if (completed) {
      await renderResults(completed);
    }
  } catch {
    // The health status communicates a server that is unavailable.
  }
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    if (!response.ok) {
      throw new Error();
    }
    const health = await response.json();
    applyNarrationDefaults(health.tts);
    const missing = [];
    if (!health.ffmpeg_available) {
      missing.push("FFmpeg");
    }
    if (!health.llm_configured) {
      missing.push("OpenRouter token");
    }
    elements.runtimeStatus.classList.toggle("is-ready", missing.length === 0);
    elements.runtimeStatus.classList.toggle("is-warning", missing.length > 0);
    elements.runtimeStatus.querySelector("span:last-child").textContent = missing.length
      ? `Missing: ${missing.join(", ")}`
      : "Local tools ready";
  } catch {
    elements.runtimeStatus.classList.add("is-warning");
    elements.runtimeStatus.querySelector("span:last-child").textContent = "Server unavailable";
  }
}

elements.clipSourcePicker.addEventListener("click", () => elements.localFiles.click());
elements.clipSourceBar.addEventListener("keydown", (event) => {
  if (event.target !== elements.clipSourceBar) {
    return;
  }
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    elements.localFiles.click();
  }
});
elements.localFiles.addEventListener("change", () => addLocalFiles(elements.localFiles.files));
["dragenter", "dragover"].forEach((eventName) => {
  elements.clipSourceBar.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.clipSourceBar.classList.add("is-dragging");
  });
});
["dragleave", "drop"].forEach((eventName) => {
  elements.clipSourceBar.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.clipSourceBar.classList.remove("is-dragging");
  });
});
elements.clipSourceBar.addEventListener("drop", (event) => addLocalFiles(event.dataTransfer.files));
elements.addUrlSource.addEventListener("click", addUrlSource);
elements.addArticleSource.addEventListener("click", addArticleSource);
elements.clipArticleText.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    addArticleSource();
  }
});
elements.clipSourceList.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) {
    return;
  }
  const button = event.target.closest("[data-remove-source]");
  if (!button) {
    return;
  }
  state.sources = state.sources.filter((source) => source.id !== button.dataset.removeSource);
  renderSources();
  setError();
});
elements.form.addEventListener("submit", submitJob);
elements.ttsEnabled.addEventListener("change", updateNarrationControls);
elements.ttsProvider.addEventListener("change", updateNarrationControls);
elements.refreshJobs.addEventListener("click", () => void refreshJobs());
elements.themeToggle.addEventListener("click", () => {
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
});

initializeIcons();
initializeTheme();
updateNarrationControls();
resetProgress();
void loadHealth();
void refreshJobs();