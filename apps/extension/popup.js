const DEFAULT_API = "http://127.0.0.1:8000";

const statusEl = document.getElementById("status");
const formEl = document.getElementById("form");
const fieldsEl = document.getElementById("fields");

let extracted = [];

async function apiBase() {
  const { apiBase } = await chrome.storage.local.get("apiBase");
  return (apiBase || DEFAULT_API).replace(/\/$/, "");
}

function say(message, kind = "count") {
  statusEl.innerHTML = `<div class="${kind}">${message}</div>`;
}

async function run(mode) {
  formEl.hidden = true;
  say("Reading the page…");
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url?.includes("joinhandshake.com")) {
    say("Open a Handshake job page first.", "err");
    return;
  }
  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world: "MAIN",
      func: (m) => {
        window.__TRELLIS_MODE__ = m;
      },
      args: [mode],
    });
    void result;
    const [{ result: payload }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["content.js"],
    });
    const items = (payload?.items ?? []).filter((j) => j.title);
    if (items.length === 0) {
      say(
        "Nothing readable found. If this is a search page, open a job first — the fields we need are on the job page.",
        "err",
      );
      return;
    }
    extracted = items;
    render();
  } catch (error) {
    say(`Could not read the page: ${error.message}`, "err");
  }
}

function field(label, value, key, index, multiline = false) {
  const id = `f-${index}-${key}`;
  const shown = value ?? "";
  const control = multiline
    ? `<textarea id="${id}" data-i="${index}" data-k="${key}">${escapeHtml(shown)}</textarea>`
    : `<input id="${id}" data-i="${index}" data-k="${key}" value="${escapeHtml(shown)}" />`;
  const hint = value === null ? ' <span class="muted">not found on the page</span>' : "";
  return `<label for="${id}">${label}${hint}</label>${control}`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}

function render() {
  fieldsEl.innerHTML = extracted
    .map(
      (job, i) => `
      <div style="border-top:1px solid #eee;padding-top:8px;margin-top:8px">
        ${field("Title", job.title, "title", i)}
        ${field("Employer", job.employer, "employer", i)}
        ${field("Location", job.location, "location", i)}
        ${field("Job type", job.job_type, "job_type", i)}
        ${field("Pay", job.pay, "pay", i)}
        ${field("Apply by", job.apply_by, "apply_by", i)}
        ${extracted.length === 1 ? field("Description", job.description, "description", i, true) : ""}
      </div>`,
    )
    .join("");
  say(`${extracted.length} job(s) read. Check them, then import.`);
  formEl.hidden = false;
}

fieldsEl.addEventListener("input", (e) => {
  const el = e.target;
  const i = Number(el.dataset.i);
  const k = el.dataset.k;
  if (Number.isInteger(i) && k) extracted[i][k] = el.value.trim() || null;
});

formEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  document.getElementById("submit").disabled = true;
  say("Importing…");
  try {
    const res = await fetch(`${await apiBase()}/api/import/handshake`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: extracted, captured_at: new Date().toISOString() }),
    });
    if (!res.ok) throw new Error(`Trellis returned ${res.status}`);
    const data = await res.json();
    say(
      `Imported: ${data.created} new, ${data.updated} updated, ${data.unchanged} unchanged.`,
      "ok",
    );
    formEl.hidden = true;
  } catch (error) {
    say(`Import failed: ${error.message}. Is Trellis running?`, "err");
  } finally {
    document.getElementById("submit").disabled = false;
  }
});

document.getElementById("cancel").addEventListener("click", () => {
  extracted = [];
  formEl.hidden = true;
  say("Discarded. Nothing was sent.");
});

document.getElementById("read-job").addEventListener("click", () => run("job"));
document.getElementById("read-list").addEventListener("click", () => run("list"));
