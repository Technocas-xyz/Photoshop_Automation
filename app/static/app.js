// Design Studio Automation — front-end logic.
// Talks to the FastAPI backend: upload, enqueue job, stream the log over SSE,
// then show the result on a checkerboard / tee-color background.

const OPTIONS = [
  { op: "blackout", icon: "⬛", name: "Blackout",
    desc: "Make black areas transparent" },
  { op: "remove_background", icon: "✨", name: "Remove Background",
    desc: "Make background transparent" },
  { op: "resolution", icon: "📐", name: "Resolution",
    desc: "Change image resolution/size" },
  { op: "ghost_pixel_removal", icon: "🩹", name: "Ghost Pixel Removal",
    desc: "Remove unwanted ghost pixels" },
  { op: "transparent_pixel_cleanup", icon: "💧", name: "Transparent Pixel Cleanup",
    desc: "Fix transparent edges" },
  { op: "semi_pixel_cleanup", icon: "🔵", name: "Semi-Pixel Cleanup",
    desc: "Clean semi-pixels and smooth edges" },
  { op: "color_adjustment", icon: "🎨", name: "Color Adjustment",
    desc: "Adjust brightness, contrast, color" },
  { op: "custom_edit", icon: "⚙️", name: "Custom Edit",
    desc: "Advanced custom editing", disabled: true },
];

const state = {
  file: null,       // { file_id, filename, size, width, height, format }
  op: null,
  jobId: null,
  teeColor: "checker",
  resultUrl: null,
};

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
window.addEventListener("DOMContentLoaded", () => {
  renderOptions();
  wireUpload();
  wireTeeSwatches();
  wireButtons();
  loadConfig();
  startStatusPolling();
});

// ---------------------------------------------------------------------------
// Photoshop connection status pill (green = ready, amber = Chrome not
// reachable, red = logged out). Polls /photoshop/status every 10s.
// ---------------------------------------------------------------------------
function startStatusPolling() {
  refreshStatus();
  setInterval(refreshStatus, 10000);
}

async function refreshStatus() {
  const pill = $("psStatusPill");
  const text = $("psStatusText");
  if (!pill || !text) return;
  try {
    const s = await (await fetch("/photoshop/status")).json();
    pill.classList.remove("status-green", "status-amber", "status-red");
    if (s.demo_mode) {
      pill.classList.add("status-amber");
      text.textContent = "Demo (no Chrome)";
      pill.title = "DEMO_MODE on — Photoshop is not used";
    } else if (!s.connected) {
      pill.classList.add("status-amber");
      text.textContent = "Chrome not reachable";
      pill.title = "Run start_chrome.bat to launch Chrome with debugging";
    } else if (!s.logged_in) {
      pill.classList.add("status-red");
      text.textContent = "Logged out";
      pill.title = "Log in to Adobe in the Chrome window from start_chrome.bat";
    } else {
      pill.classList.add("status-green");
      const sz = s.window_size ? ` · ${s.window_size.width}×${s.window_size.height}` : "";
      text.textContent = "Photoshop ready" + sz;
      pill.title = s.url || "Connected to Photoshop Web";
    }
  } catch (_) {
    pill.classList.remove("status-green", "status-red");
    pill.classList.add("status-amber");
    text.textContent = "Status unavailable";
  }
}

async function loadConfig() {
  try {
    const cfg = await (await fetch("/config")).json();
    const pill = $("modePill");
    const bits = [];
    if (cfg.demo_mode) bits.push("DEMO MODE");
    bits.push(`blackout: ${cfg.blackout_engine}`);
    pill.textContent = bits.join("  •  ");
    pill.hidden = false;
  } catch (_) { /* non-fatal */ }
}

// ---------------------------------------------------------------------------
// Option grid + param panels
// ---------------------------------------------------------------------------
function renderOptions() {
  const grid = $("optionGrid");
  grid.innerHTML = "";
  OPTIONS.forEach((o) => {
    const el = document.createElement("div");
    el.className = "option" + (o.disabled ? " disabled" : "");
    el.dataset.op = o.op;
    el.innerHTML = `
      <div class="op-icon">${o.icon}</div>
      <div class="op-name">${o.name}</div>
      <div class="op-desc">${o.desc}</div>`;
    if (!o.disabled) el.addEventListener("click", () => selectOp(o.op));
    grid.appendChild(el);
  });
}

function selectOp(op) {
  state.op = op;
  document.querySelectorAll(".option").forEach((el) =>
    el.classList.toggle("active", el.dataset.op === op));
  renderParams(op);
  refreshStartBtn();
}

function renderParams(op) {
  const panel = $("paramPanel");
  let html = "";
  if (op === "blackout") {
    html = sliderRow("Softness", "softness", 0, 60, 20,
      "Also removes near-black pixels (JPG artifacts)");
  } else if (op === "resolution") {
    html = `
      <div class="param-row"><label>Width (px)</label>
        <input type="number" id="p_width" placeholder="auto" min="1"></div>
      <div class="param-row"><label>Height (px)</label>
        <input type="number" id="p_height" placeholder="auto" min="1"></div>
      <div class="param-row"><label>Scale (%)</label>
        <input type="number" id="p_scale" placeholder="e.g. 50" min="1"></div>
      <div class="param-row"><label>DPI</label>
        <input type="number" id="p_dpi" placeholder="72" min="1"></div>`;
  } else if (op === "semi_pixel_cleanup") {
    html = sliderRow("Low threshold", "low", 0, 255, 40) +
           sliderRow("High threshold", "high", 0, 255, 215);
  } else if (op === "ghost_pixel_removal") {
    html = `<div class="param-row"><label>Min area (px)</label>
        <input type="number" id="p_min_area" value="12" min="1"></div>`;
  } else if (op === "transparent_pixel_cleanup") {
    html = `<div class="param-row">
        <label>Edge defringe</label>
        <input type="checkbox" id="p_defringe" checked></div>`;
  } else if (op === "color_adjustment") {
    html = sliderRow("Brightness", "brightness", -100, 100, 0) +
           sliderRow("Contrast", "contrast", -100, 100, 0) +
           sliderRow("Saturation", "saturation", -100, 100, 0);
  }
  panel.innerHTML = html;
  panel.hidden = html === "";
  // wire range value readouts
  panel.querySelectorAll('input[type="range"]').forEach((r) => {
    const out = panel.querySelector(`#val_${r.dataset.key}`);
    r.addEventListener("input", () => { if (out) out.textContent = r.value; });
  });
}

function sliderRow(label, key, min, max, def, hint) {
  return `
    <div class="param-row">
      <label>${label}</label>
      <input type="range" data-key="${key}" id="p_${key}"
             min="${min}" max="${max}" value="${def}">
      <span class="range-val" id="val_${key}">${def}</span>
    </div>
    ${hint ? `<div class="param-row"><span class="muted">${hint}</span></div>` : ""}`;
}

function collectParams() {
  const op = state.op;
  const num = (id) => { const v = $(id)?.value; return v === "" || v == null ? null : Number(v); };
  if (op === "blackout") return { softness: num("p_softness") ?? 20 };
  if (op === "resolution") {
    const p = {};
    if (num("p_width")) p.width = num("p_width");
    if (num("p_height")) p.height = num("p_height");
    if (num("p_scale")) p.scale = num("p_scale");
    if (num("p_dpi")) p.dpi = num("p_dpi");
    return p;
  }
  if (op === "semi_pixel_cleanup") return { low: num("p_low"), high: num("p_high") };
  if (op === "ghost_pixel_removal") return { min_area: num("p_min_area") ?? 12 };
  if (op === "transparent_pixel_cleanup") return { defringe: $("p_defringe")?.checked ?? true };
  if (op === "color_adjustment")
    return { brightness: num("p_brightness") ?? 0, contrast: num("p_contrast") ?? 0,
             saturation: num("p_saturation") ?? 0 };
  return {};
}

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------
function wireUpload() {
  const dz = $("dropzone");
  const input = $("fileInput");
  dz.addEventListener("click", () => input.click());
  dz.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
  });
  input.addEventListener("change", () => { if (input.files[0]) uploadFile(input.files[0]); });

  ["dragover", "dragenter"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files[0];
    if (f) uploadFile(f);
  });

  $("removeFile").addEventListener("click", clearFile);
}

async function uploadFile(file) {
  const okTypes = ["image/jpeg", "image/png", "image/webp"];
  if (!okTypes.includes(file.type)) { addLog("error", `Unsupported type: ${file.type}`); return; }
  if (file.size > 10 * 1024 * 1024) { addLog("error", "File exceeds 10MB limit"); return; }

  addLog("info", `Uploading ${file.name}...`);
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await fetch("/upload", { method: "POST", body: fd });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const meta = await res.json();
    state.file = meta;
    showFilePreview(file, meta);
    addLog("success", "Image uploaded successfully");
    refreshStartBtn();
  } catch (err) {
    addLog("error", `Upload failed: ${err.message}`);
  }
}

function showFilePreview(file, meta) {
  const url = URL.createObjectURL(file);
  $("thumb").src = url;
  $("fileName").textContent = meta.filename;
  $("fileSize").textContent = humanSize(meta.size);
  $("filePreview").hidden = false;

  const img = $("origImg");
  img.src = url;
  img.classList.add("show");
  $("origEmpty").style.display = "none";
  $("mOrigName").textContent = meta.filename;
  $("mOrigDim").textContent = meta.width && meta.height ? `${meta.width} × ${meta.height}` : "—";
  $("mOrigFmt").textContent = meta.format || "—";
  $("mOrigSize").textContent = humanSize(meta.size);
}

function clearFile() {
  state.file = null;
  $("fileInput").value = "";
  $("filePreview").hidden = true;
  $("origImg").classList.remove("show");
  $("origEmpty").style.display = "";
  ["mOrigName", "mOrigDim", "mOrigFmt", "mOrigSize"].forEach((id) => $(id).textContent = "—");
  refreshStartBtn();
}

// ---------------------------------------------------------------------------
// Start processing + SSE
// ---------------------------------------------------------------------------
function refreshStartBtn() {
  $("startBtn").disabled = !(state.file && state.op);
}

function wireButtons() {
  $("startBtn").addEventListener("click", startJob);
  $("clearLog").addEventListener("click", () => { $("logList").innerHTML = ""; });
  $("historyBtn").addEventListener("click", openHistory);
  $("closeHistory").addEventListener("click", () => $("historyModal").hidden = true);
  $("previewBtn").addEventListener("click", openLightbox);
  $("closeLightbox").addEventListener("click", () => $("lightbox").hidden = true);
  $("zoomResult").addEventListener("click", openLightbox);
  $("zoomOrig").addEventListener("click", () => {
    const src = $("origImg").src;
    if (!src) return;
    $("lightboxImg").src = src;
    $("lightbox").hidden = false;
  });
}

async function startJob() {
  if (!state.file || !state.op) return;
  $("startBtn").disabled = true;
  resetResult();
  addLog("info", `Queuing job: ${state.op}`);

  try {
    const res = await fetch("/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        file_id: state.file.file_id,
        filename: state.file.filename,
        op: state.op,
        params: collectParams(),
      }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const { job_id } = await res.json();
    state.jobId = job_id;
    streamLog(job_id);
  } catch (err) {
    addLog("error", `Could not start job: ${err.message}`);
    refreshStartBtn();
  }
}

function streamLog(jobId) {
  const es = new EventSource(`/jobs/${jobId}/events`);
  es.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.type === "end") { es.close(); refreshStartBtn(); return; }
    if (data.type === "status") {
      if (data.status === "done") onJobDone(jobId);
      return;
    }
    addLog(data.type, data.message, data.ts);
  };
  es.onerror = () => { es.close(); refreshStartBtn(); };
}

function onJobDone(jobId) {
  const url = `/results/${jobId}.png?t=${Date.now()}`;
  state.resultUrl = url;
  const img = $("resultImg");
  img.onload = () => {
    img.classList.add("show");
    $("resultEmpty").style.display = "none";
    $("mResName").textContent = baseName(state.file.filename) + "_edited.png";
    $("mResDim").textContent = `${img.naturalWidth} × ${img.naturalHeight}`;
    $("mResFmt").textContent = "PNG";
    $("mResSize").textContent = "ready";
  };
  img.src = url;
  const dl = $("downloadBtn");
  dl.href = url;
  dl.setAttribute("download", baseName(state.file.filename) + "_edited.png");
}

function resetResult() {
  $("resultImg").classList.remove("show");
  $("resultEmpty").style.display = "";
  ["mResName", "mResDim", "mResFmt", "mResSize"].forEach((id) => $(id).textContent = "—");
}

// ---------------------------------------------------------------------------
// Tee color preview
// ---------------------------------------------------------------------------
function wireTeeSwatches() {
  const stage = $("resultStage");
  $("teeSwatches").querySelectorAll(".tee").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      if (btn.classList.contains("custom")) return; // handled by input
      setTee(btn.dataset.color, btn);
    });
  });
  $("teeCustom").addEventListener("input", (e) => {
    const customBtn = $("teeCustom").closest(".tee");
    setTee(e.target.value, customBtn);
  });

  function setTee(color, btn) {
    $("teeSwatches").querySelectorAll(".tee").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.teeColor = color;
    if (color === "checker") {
      stage.classList.add("checkerboard");
      stage.style.background = "";
    } else {
      stage.classList.remove("checkerboard");
      stage.style.background = color;
    }
  }
}

// ---------------------------------------------------------------------------
// History + lightbox
// ---------------------------------------------------------------------------
async function openHistory() {
  $("historyModal").hidden = false;
  const list = $("historyList");
  list.innerHTML = `<div class="history-empty">Loading…</div>`;
  try {
    const jobs = await (await fetch("/history")).json();
    if (!jobs.length) { list.innerHTML = `<div class="history-empty">No jobs yet.</div>`; return; }
    list.innerHTML = "";
    jobs.forEach((j) => {
      const row = document.createElement("div");
      row.className = "history-item";
      const when = new Date(j.time * 1000).toLocaleString();
      row.innerHTML = `
        <div>
          <div><b>${j.filename}</b></div>
          <div class="hi-op">${j.op} · ${when}</div>
        </div>
        <span class="badge ${j.status}">${j.status}</span>
        <span>${j.result_path
          ? `<a class="btn btn-ghost btn-sm" href="${j.result_path}" target="_blank">Open</a>`
          : ""}</span>`;
      list.appendChild(row);
    });
  } catch (err) {
    list.innerHTML = `<div class="history-empty">Failed to load history.</div>`;
  }
}

function openLightbox() {
  if (!state.resultUrl) return;
  $("lightboxImg").src = state.resultUrl;
  $("lightbox").hidden = false;
}

// ---------------------------------------------------------------------------
// Log + helpers
// ---------------------------------------------------------------------------
function addLog(level, message, ts) {
  const list = $("logList");
  const time = ts ? new Date(ts * 1000) : new Date();
  const hh = time.toLocaleTimeString("en-GB", { hour12: false });
  const mark = level === "error" ? "✕" : level === "success" ? "✓" : "•";
  const line = document.createElement("div");
  line.className = `log-line ${level}`;
  line.innerHTML =
    `<span class="mark">${mark}</span>` +
    `<span class="lt">${hh}</span>` +
    `<span class="lm"></span>`;
  line.querySelector(".lm").textContent = message;
  list.appendChild(line);
  list.scrollTop = list.scrollHeight;
}

function humanSize(bytes) {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function baseName(name) {
  return (name || "image").replace(/\.[^.]+$/, "");
}
