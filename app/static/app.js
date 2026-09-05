const state = {
  file: null,
  mode: "reel",
  jobId: null,
  pollTimer: null,
  reelSources: [],
  reelSourceSequence: 0,
};
const processingStatuses = new Set([
  "INGESTING",
  "ACQUIRING",
  "TRANSCRIBING",
  "ANALYZING",
  "SCRIPTING",
  "SYNTHESIZING",
  "ASSEMBLING",
  "COMPOSING",
  "RENDERING",
]);
const themeStorageKey = "clipfactory-theme";

const elements = {
  clipCount: document.querySelector("#clip-count"),
  decreaseClips: document.querySelector("#decrease-clips"),
  form: document.querySelector("#job-form"),
  formError: document.querySelector("#form-error"),
  processButton: document.querySelector("#process-button"),
  progressBar: document.querySelector("#progress-bar"),
  progressMessage: document.querySelector("#progress-message"),
  progressNumber: document.querySelector("#progress-number"),
  progressTrack: document.querySelector(".progress-track"),
  processPanel: document.querySelector(".process-panel"),
  processButtonLabel: document.querySelector("#process-button-label"),
  workflowTitle: document.querySelector("#workflow-title"),
  jobState: document.querySelector("#job-state"),
  refreshJobs: document.querySelector("#refresh-jobs"),
  results: document.querySelector("#results"),
  resultsTitle: document.querySelector("#results-title"),
  runtimeStatus: document.querySelector("#runtime-status"),
  clipRunOptions: document.querySelector("#clip-run-options"),
  reelSource: document.querySelector("#reel-source"),
  reelSourceBar: document.querySelector("#reel-source-bar"),
  reelFileInput: document.querySelector("#reel-video-files"),
  reelSourcePicker: document.querySelector("#reel-source-picker"),
  reelUrl: document.querySelector("#reel-url"),
  addUrlSource: document.querySelector("#add-url-source"),
  reelSourceList: document.querySelector("#reel-source-list"),
  reelSourceCount: document.querySelector("#reel-source-count"),
  themeToggle: document.querySelector("#theme-toggle"),
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

function clampClipCount(value) {
  const parsed = Number.parseInt(value, 10);
  return Math.min(10, Math.max(1, Number.isNaN(parsed) ? 5 : parsed));
}

function setError(message = "") {
  elements.formError.textContent = message;
  elements.formError.hidden = !message;
}

function setMode(mode) {
  state.mode = mode;
  elements.clipRunOptions.hidden = true;
  elements.workflowTitle.textContent = "Sources";
  elements.processButtonLabel.textContent = "Generate reel";
  setError();
}

function setSelectedFile(file) {
  state.file = file;
  elements.fileName.textContent = file ? file.name : "Choose a video";
}

function addReelSource(source) {
  state.reelSourceSequence += 1;
  state.reelSources.push({ id: `source-${state.reelSourceSequence}`, ...source });
  renderReelSources();
  setError();
  return true;
}

function addReelFiles(files) {
  for (const file of Array.from(files || [])) {
    const alreadyAdded = state.reelSources.some(
      (source) =>
        source.kind === "video_file" &&
        source.file.name === file.name &&
        source.file.size === file.size &&
        source.file.lastModified === file.lastModified,
    );
    if (!alreadyAdded && !addReelSource({ kind: "video_file", file, label: file.name })) {
      break;
    }
  }
  elements.reelFileInput.value = "";
}

function addUrlSource(input, kind, label) {
  const value = input.value.trim();
  if (!value) {
    setError("Enter a URL before adding it to the reel.");
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
  if (addReelSource({ kind, value, label: `${label}: ${value}` })) {
    input.value = "";
  }
}

function renderReelSources() {
  elements.reelSourceCount.textContent = state.reelSources.length
    ? `${state.reelSources.length} added`
    : "No sources yet";
  if (!state.reelSources.length) {
    elements.reelSourceList.innerHTML = '<li class="reel-source-empty">Add a URL or local video.</li>';
    return;
  }
  const metadata = {
    video_file: { icon: "film", label: "Local video" },
    url: { icon: "link", label: "URL" },
  };
  elements.reelSourceList.innerHTML = state.reelSources
    .map((source) => {
      const detail = metadata[source.kind];
      return `
        <li class="reel-source-item">
          <div class="reel-source-info">
            <span class="reel-source-kind"><i data-lucide="${detail.icon}"></i>${detail.label}</span>
            <strong title="${escapeHtml(source.label)}">${escapeHtml(source.label)}</strong>
          </div>
          <button class="icon-button remove-source-button" type="button" data-remove-reel-source="${source.id}"
            aria-label="Remove ${escapeHtml(detail.label)} source" title="Remove source">
            <i data-lucide="x"></i>
          </button>
        </li>`;
    })
    .join("");
  initializeIcons();
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

  const stageOrder = ["ACQUIRING", "TRANSCRIBING", "ANALYZING", "RENDERING"];
  const currentIndex = stageOrder.indexOf(job.status);
  document.querySelectorAll(".pipeline-steps li").forEach((item) => {
    const itemIndex = stageOrder.indexOf(item.dataset.stage);
    item.classList.toggle("is-active", itemIndex === currentIndex);
    item.classList.toggle("is-complete", currentIndex > itemIndex || job.status === "COMPLETED");
  });
}

function resetProgress() {
  updateProgress({ status: "CREATED", progress: 0, current_step: "Queued" });
  elements.workflowTitle.textContent = "Sources";
  elements.processButtonLabel.textContent = "Generate reel";
  elements.jobState.textContent = "Ready when you are";
  elements.progressMessage.textContent = "Pick a source to begin a run.";
}

function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const minutes = Math.floor(value / 60);
  const remaining = Math.round(value % 60).toString().padStart(2, "0");
  return `${minutes}:${remaining}`;
}

function renderResults(job) {
  if (job?.reel) {
    const jobId = encodeURIComponent(job.id);
    const reelUrl = `/api/jobs/${jobId}/reel`;
    elements.resultsTitle.textContent = "Generated reel";
    elements.results.innerHTML = `
      <article class="clip-card reel-card">
        <video controls preload="metadata" src="${reelUrl}"></video>
        <div class="clip-details">
          <div class="clip-topline">
            <span>REEL · ${formatDuration(job.reel.duration)}</span>
            <span class="clip-score">${escapeHtml(String(job.reel.source_count))} sources</span>
          </div>
          <h3>${escapeHtml(job.reel.title)}</h3>
          <a href="${reelUrl}?download=true" download="reel.mp4">
            <i data-lucide="download"></i><span>Download</span>
          </a>
        </div>
      </article>`;
    initializeIcons();
    return;
  }
  if (!job?.clips?.length) {
    elements.resultsTitle.textContent = "Generated output";
    elements.results.innerHTML = `
      <div class="empty-results">
        <i data-lucide="video"></i>
        <p>Completed videos will appear here.</p>
      </div>`;
    initializeIcons();
    return;
  }

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
              <span>CLIP ${String(index + 1).padStart(2, "0")} · ${formatDuration(clip.end - clip.start)}</span>
              <span class="clip-score">${escapeHtml(String(clip.score))}/100</span>
            </div>
            <h3>${escapeHtml(clip.title)}</h3>
            <p>${escapeHtml(clip.reason)}</p>
            <a href="${clipUrl}?download=true" download="${escapeHtml(clip.filename)}">
              <i data-lucide="download"></i><span>Download MP4</span>
            </a>
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
      renderResults(job);
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
    setError(error.message || "Lost connection to the local server.");
  }
}

async function submitJob(event) {
  event.preventDefault();
  setError();

  let response;
  try {
    elements.processButton.disabled = true;
    if (state.mode === "reel") {
      response = await submitReelJob();
    } else if (state.mode === "upload") {
      const clipCount = clampClipCount(elements.clipCount.value);
      elements.clipCount.value = String(clipCount);
      if (!state.file) {
        throw new Error("Choose a local video file first.");
      }
      const formData = new FormData();
      formData.append("file", state.file);
      formData.append("clip_count", String(clipCount));
      response = await fetch("/api/jobs/upload", { method: "POST", body: formData });
    } else if (state.mode === "url") {
      const clipCount = clampClipCount(elements.clipCount.value);
      elements.clipCount.value = String(clipCount);
      const url = elements.sourceUrl.value.trim();
      if (!url) {
        throw new Error("Enter a URL first.");
      }
      response = await fetch("/api/jobs/youtube", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, clip_count: clipCount }),
      });
    } else {
      throw new Error("Choose a source type first.");
    }

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "The job could not be created.");
    }
    state.jobId = payload.id;
    updateProgress(payload);
    stopPolling();
    pollJob();
  } catch (error) {
    elements.processButton.disabled = false;
    setError(error.message || "The job could not be created.");
  }
}

async function submitReelJob() {
  if (!state.reelSources.length) {
    throw new Error("Add at least one video or article source first.");
  }
  const formData = new FormData();
  for (const source of state.reelSources) {
    if (source.kind === "video_file") {
      formData.append("video_files", source.file);
    } else if (source.kind === "url") {
      formData.append("urls", source.value);
    } else if (source.kind === "article_text") {
      formData.append("article_texts", source.value);
    }
  }
  return fetch("/api/jobs/reel", { method: "POST", body: formData });
}

async function refreshJobs() {
  try {
    const response = await fetch("/api/jobs");
    if (!response.ok) {
      return;
    }
    const jobs = await response.json();
    const completed = jobs.find(
      (job) => job.status === "COMPLETED" && (job.reel || job.clips?.length),
    );
    if (completed) {
      renderResults(completed);
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

elements.reelSourcePicker.addEventListener("click", () => elements.reelFileInput.click());
elements.reelSourceBar.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    elements.reelFileInput.click();
  }
});
elements.reelFileInput.addEventListener("change", () => addReelFiles(elements.reelFileInput.files));
["dragenter", "dragover"].forEach((eventName) => {
  elements.reelSourceBar.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.reelSourceBar.classList.add("is-dragging");
  });
});
["dragleave", "drop"].forEach((eventName) => {
  elements.reelSourceBar.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.reelSourceBar.classList.remove("is-dragging");
  });
});
elements.reelSourceBar.addEventListener("drop", (event) => addReelFiles(event.dataTransfer.files));
elements.addUrlSource.addEventListener("click", () => {
  addUrlSource(elements.reelUrl, "url", "URL");
});
elements.reelSourceList.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) {
    return;
  }
  const button = event.target.closest("[data-remove-reel-source]");
  if (!button) {
    return;
  }
  state.reelSources = state.reelSources.filter(
    (source) => source.id !== button.dataset.removeReelSource,
  );
  renderReelSources();
  setError();
});

elements.decreaseClips.addEventListener("click", () => {
  elements.clipCount.value = String(clampClipCount(Number(elements.clipCount.value) - 1));
});
document.querySelector("#increase-clips").addEventListener("click", () => {
  elements.clipCount.value = String(clampClipCount(Number(elements.clipCount.value) + 1));
});
elements.clipCount.addEventListener("change", () => {
  elements.clipCount.value = String(clampClipCount(elements.clipCount.value));
});
elements.form.addEventListener("submit", submitJob);
elements.refreshJobs.addEventListener("click", refreshJobs);
elements.themeToggle.addEventListener("click", () => {
  const currentTheme = document.documentElement.dataset.theme;
  setTheme(currentTheme === "dark" ? "light" : "dark");
});

initializeIcons();
initializeTheme();
resetProgress();
loadHealth();
refreshJobs();