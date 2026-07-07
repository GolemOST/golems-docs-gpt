/* Docs GPT — front-end logic. Vanilla JS, no build step. */
"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  library: [],
  pendingFile: null, // { name, dataB64 }
  lastAnswer: null,
  config: { mode: "local", has_env_key: false, has_saved_key: false },
  workspace: null, // browser-minted UUID, online mode only
};

const KEY_STORAGE = "docsgpt_api_key";
const WS_STORAGE = "docsgpt_workspace";

/* ---------------- utilities ---------------- */

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, 3500);
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.workspace) headers["X-Workspace"] = state.workspace;
  const browserKey = localStorage.getItem(KEY_STORAGE);
  if (browserKey) headers["X-Api-Key"] = browserKey;
  const response = await fetch(path, { headers, ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.error || `Request failed (${response.status})`);
  }
  return body;
}

/* ---------------- config + workspace + key ---------------- */

async function loadConfig() {
  try {
    state.config = await api("/api/config");
  } catch (err) {
    toast(`Config error: ${err.message}`);
  }
  if (state.config.mode === "online") {
    let ws = localStorage.getItem(WS_STORAGE);
    if (!ws) {
      ws = crypto.randomUUID();
      localStorage.setItem(WS_STORAGE, ws);
    }
    state.workspace = ws;
    $("online-banner").hidden = false;
  }
  updateKeyStatus();
}

function keySource() {
  if (localStorage.getItem(KEY_STORAGE)) return "browser";
  if (state.config.has_saved_key) return "this PC";
  if (state.config.has_env_key) {
    return state.config.mode === "online" ? "site-provided" : "server env";
  }
  return null;
}

function updateKeyStatus() {
  const pill = $("key-status");
  const source = keySource();
  pill.hidden = false;
  pill.textContent = source ? `🔑 key: ${source}` : "🔑 no key — open Settings";
  pill.classList.toggle("missing", !source);
}

function wireSettings() {
  const overlay = $("settings-overlay");
  const isLocal = () => state.config.mode === "local";
  $("settings-btn").addEventListener("click", () => {
    $("key-save-device").hidden = !isLocal();
    $("settings-online-line").hidden = isLocal();
    $("settings-note").textContent = isLocal()
      ? (state.config.has_env_key || state.config.has_saved_key
        ? "A key is already configured on this PC — you only need one here to override it."
        : "Paste your Anthropic API key to enable question answering.")
      : (state.config.has_env_key
        ? "This site provides a key — asking already works. Paste your own to bill your account instead."
        : "Paste your Anthropic API key. It stays in this browser and is sent only with your questions.");
    overlay.hidden = false;
    $("api-key-input").focus();
  });
  $("settings-close").addEventListener("click", () => { overlay.hidden = true; });
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) overlay.hidden = true;
  });

  $("key-save-browser").addEventListener("click", () => {
    const key = $("api-key-input").value.trim();
    if (!key) { toast("Paste a key first."); return; }
    localStorage.setItem(KEY_STORAGE, key);
    $("api-key-input").value = "";
    overlay.hidden = true;
    updateKeyStatus();
    toast("Key saved in this browser.");
  });

  $("key-save-device").addEventListener("click", async () => {
    const key = $("api-key-input").value.trim();
    if (!key) { toast("Paste a key first."); return; }
    try {
      await api("/api/config/key", { method: "POST", body: JSON.stringify({ key }) });
      state.config.has_saved_key = true;
      $("api-key-input").value = "";
      overlay.hidden = true;
      updateKeyStatus();
      toast("Key saved on this PC (~/.docsgpt/config.json).");
    } catch (err) {
      toast(`Save failed: ${err.message}`);
    }
  });

  $("key-clear").addEventListener("click", async () => {
    localStorage.removeItem(KEY_STORAGE);
    if (isLocal() && state.config.has_saved_key) {
      try {
        await api("/api/config/key", { method: "POST", body: JSON.stringify({ key: "" }) });
        state.config.has_saved_key = false;
      } catch (err) {
        toast(`Clear failed: ${err.message}`);
      }
    }
    $("api-key-input").value = "";
    updateKeyStatus();
    toast("Key cleared.");
  });
}

/* ---------------- library ---------------- */

async function loadLibrary() {
  try {
    const body = await api("/api/library");
    state.library = body.documents;
    renderLibrary();
  } catch (err) {
    toast(`Library error: ${err.message}`);
  }
}

function renderLibrary() {
  const list = $("library-list");
  if (!state.library.length) {
    list.innerHTML = '<p class="evidence-hint">No documents yet — add your first SOP above.</p>';
    return;
  }
  list.innerHTML = state.library.map((doc) => {
    const superseded = doc.status === "superseded";
    return `
      <div class="doc-card ${superseded ? "superseded" : ""}" data-id="${doc.id}">
        <div class="doc-title" data-open="${doc.id}" title="Open document">${escapeHtml(doc.title)}</div>
        <div class="doc-meta">
          ${doc.rev ? `<span class="pill rev">Rev ${escapeHtml(doc.rev)}</span>` : ""}
          <span class="pill clickable ${superseded ? "superseded-pill" : "current"}"
                data-toggle="${doc.id}" data-status="${doc.status}"
                title="Click to mark ${superseded ? "current" : "superseded"}">
            ${superseded ? "Superseded" : "Current"}
          </span>
          <span class="doc-chars">${(doc.chars / 1000).toFixed(1)}k chars</span>
        </div>
      </div>`;
  }).join("");

  list.querySelectorAll("[data-toggle]").forEach((pill) => {
    pill.addEventListener("click", () => toggleStatus(pill.dataset.toggle, pill.dataset.status));
  });
  list.querySelectorAll("[data-open]").forEach((title) => {
    title.addEventListener("click", () => openViewer(title.dataset.open, null, null));
  });
}

async function toggleStatus(docId, currentStatus) {
  const next = currentStatus === "current" ? "superseded" : "current";
  try {
    await api(`/api/doc/${docId}/status`, { method: "POST", body: JSON.stringify({ status: next }) });
    toast(`Marked ${next}.`);
    await loadLibrary();
  } catch (err) {
    toast(`Status error: ${err.message}`);
  }
}

/* ---------------- upload ---------------- */

function wireUpload() {
  $("pick-file").addEventListener("click", () => $("file-input").click());
  $("file-input").addEventListener("change", () => {
    const file = $("file-input").files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      state.pendingFile = { name: file.name, dataB64: reader.result.split(",", 2)[1] };
      $("up-title").value = file.name.replace(/\.[^.]+$/, "");
      $("upload-form").hidden = false;
      $("pick-file").hidden = true;
    };
    reader.onerror = () => toast("Could not read that file.");
    reader.readAsDataURL(file);
  });
  $("up-cancel").addEventListener("click", resetUploadForm);
  $("upload-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.pendingFile) return;
    const button = $("upload-form").querySelector("button[type=submit]");
    button.disabled = true;
    try {
      await api("/api/upload", {
        method: "POST",
        body: JSON.stringify({
          filename: state.pendingFile.name,
          data_b64: state.pendingFile.dataB64,
          title: $("up-title").value,
          rev: $("up-rev").value,
          status: $("up-status").value,
        }),
      });
      toast("Document added.");
      resetUploadForm();
      await loadLibrary();
    } catch (err) {
      toast(`Upload failed: ${err.message}`);
    } finally {
      button.disabled = false;
    }
  });
}

function resetUploadForm() {
  state.pendingFile = null;
  $("file-input").value = "";
  $("up-rev").value = "";
  $("upload-form").hidden = true;
  $("pick-file").hidden = false;
}

/* ---------------- ask + answer ---------------- */

function setStatus(message, isError = false) {
  const line = $("status-line");
  line.hidden = !message;
  line.textContent = message || "";
  line.classList.toggle("error", isError);
}

async function ask() {
  const question = $("question").value.trim();
  if (!question) { toast("Type a question first."); return; }
  if (state.config.mode === "online" && !localStorage.getItem(KEY_STORAGE)
      && !state.config.has_env_key) {
    toast("Paste your Anthropic API key first — it's your key, your usage.");
    $("settings-btn").click();
    return;
  }
  const button = $("ask-btn");
  button.disabled = true;
  $("answer-card").hidden = true;
  setStatus("Searching your documents…");
  try {
    const result = await api("/api/ask", {
      method: "POST",
      body: JSON.stringify({
        question,
        include_superseded: $("include-superseded").checked,
      }),
    });
    state.lastAnswer = result;
    setStatus("");
    renderAnswer(result);
  } catch (err) {
    setStatus(`Error: ${err.message}`, true);
  } finally {
    button.disabled = false;
  }
}

function renderAnswer(result) {
  const card = $("answer-card");
  card.hidden = false;
  card.classList.toggle("refusal", result.not_found);
  $("refusal-banner").hidden = !result.not_found;

  $("answer-body").innerHTML = result.segments.map((segment) => {
    const numbers = [...new Set(segment.citations.map((c) => c.n))];
    const markers = numbers
      .map((n) => `<sup class="cite" data-n="${n}" title="Show evidence [${n}]">[${n}]</sup>`)
      .join("");
    return escapeHtml(segment.text) + markers;
  }).join("");

  $("answer-body").querySelectorAll("sup.cite").forEach((sup) => {
    sup.addEventListener("click", () => flashEvidence(sup.dataset.n));
  });

  const chips = result.searched.map((doc) =>
    `<span class="chip ${doc.cited ? "cited" : ""}">${doc.cited ? "✓ " : ""}${escapeHtml(doc.title)}</span>`,
  ).join("");
  const droppedNote = result.dropped.length
    ? ` · <strong>${result.dropped.length} doc(s) skipped for size</strong> (least relevant to this question)`
    : "";
  $("assembled-line").innerHTML =
    `How this was assembled: searched ${result.searched.length} document(s) · ` +
    `${result.evidence.length} supporting passage(s)${droppedNote}<br>${chips}`;

  renderEvidence(result.evidence);
}

function renderEvidence(evidence) {
  $("evidence-hint").hidden = evidence.length > 0;
  $("evidence-list").innerHTML = evidence.map((cite) => `
    <div class="evidence-card" id="evidence-${cite.n}">
      <div class="evidence-doc">
        <span class="evidence-n">${cite.n}</span>${escapeHtml(cite.doc_title)}
        ${cite.rev ? `— Rev ${escapeHtml(cite.rev)}` : ""}
        ${cite.status === "superseded" ? " ⚠ superseded" : ""}
      </div>
      <div class="evidence-quote">“${escapeHtml(truncate(cite.cited_text, 320))}”</div>
      <button class="evidence-open" data-doc="${cite.doc_id}" data-start="${cite.start}" data-end="${cite.end}">
        Open in document →
      </button>
    </div>`).join("");

  $("evidence-list").querySelectorAll(".evidence-open").forEach((btn) => {
    btn.addEventListener("click", () =>
      openViewer(btn.dataset.doc, Number(btn.dataset.start), Number(btn.dataset.end)));
  });
}

function truncate(text, max) {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function flashEvidence(n) {
  const card = $(`evidence-${n}`);
  if (!card) return;
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.classList.add("flash");
  setTimeout(() => card.classList.remove("flash"), 1600);
}

/* ---------------- viewer ---------------- */

async function openViewer(docId, start, end) {
  try {
    const body = await api(`/api/doc/${docId}`);
    const doc = body.document;
    $("viewer-title").textContent = doc.title;
    $("viewer-meta").textContent =
      `${doc.rev ? `Rev ${doc.rev} · ` : ""}${doc.status} · ${doc.filename}`;
    const pre = $("viewer-text");
    if (start !== null && end !== null && end > start && end <= doc.text.length) {
      pre.innerHTML =
        escapeHtml(doc.text.slice(0, start)) +
        `<mark id="viewer-mark">${escapeHtml(doc.text.slice(start, end))}</mark>` +
        escapeHtml(doc.text.slice(end));
    } else {
      pre.innerHTML = escapeHtml(doc.text);
    }
    $("viewer-overlay").hidden = false;
    const mark = document.getElementById("viewer-mark");
    if (mark) setTimeout(() => mark.scrollIntoView({ behavior: "smooth", block: "center" }), 60);
    else pre.scrollTop = 0;
  } catch (err) {
    toast(`Cannot open document: ${err.message}`);
  }
}

function wireViewer() {
  $("viewer-close").addEventListener("click", () => { $("viewer-overlay").hidden = true; });
  $("viewer-overlay").addEventListener("click", (event) => {
    if (event.target === $("viewer-overlay")) $("viewer-overlay").hidden = true;
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") $("viewer-overlay").hidden = true;
  });
}

/* ---------------- init ---------------- */

async function init() {
  wireUpload();
  wireViewer();
  wireSettings();
  $("ask-btn").addEventListener("click", ask);
  $("question").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      ask();
    }
  });
  await loadConfig();
  loadLibrary();
}

document.addEventListener("DOMContentLoaded", init);
