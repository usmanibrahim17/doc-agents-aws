"use strict";
// No framework, no build step. Everything from the API is rendered with textContent, never as HTML.

const API = window.DOCAGENT_API;
const PENDING = ["uploading", "queued", "processing"];
const STATUS = {
  uploading: "uploading", queued: "queued", processing: "processing", valid: "valid",
  approved: "approved", needs_review: "needs review", rejected: "rejected", failed: "failed",
};
const CATEGORIES = ["Office supplies", "Travel", "Utilities", "Software", "Meals",
  "Professional services", "Other"];
const EDITABLE = [["vendor", "Vendor"], ["invoice_number", "Document number"],
  ["date", "Date (YYYY-MM-DD)"], ["currency", "Currency"], ["subtotal", "Subtotal"],
  ["tax", "Tax"], ["total", "Total"]];

const $ = (id) => document.getElementById(id);
let selected = null;
let timer = null;

function sessionId() {
  let id = localStorage.getItem("docagent-session");
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem("docagent-session", id);
  }
  return id;
}

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children.filter((child) => child !== null && child !== undefined));
  return node;
}

async function api(path, options = {}) {
  const headers = { "x-session-id": sessionId() };
  if (options.body) headers["content-type"] = "application/json";
  const response = await fetch(API + path, { ...options, headers });
  const isJson = (response.headers.get("content-type") || "").includes("json");
  const data = isJson ? await response.json() : await response.blob();
  if (!response.ok) {
    throw new Error(data.error || data.message || `request failed (${response.status})`);
  }
  return data;
}

function say(text) { $("message").textContent = text; }

async function upload(blob, filename) {
  say(`Uploading ${filename}…`);
  const created = await api("/documents", {
    method: "POST",
    body: JSON.stringify({ filename, content_type: blob.type }),
  });
  const form = new FormData();
  Object.entries(created.upload.fields).forEach(([name, value]) => form.append(name, value));
  form.append("file", blob);
  const stored = await fetch(created.upload.url, { method: "POST", body: form });
  if (!stored.ok) throw new Error("the upload was refused (is the file over 5 MB?)");
  say(`${filename} uploaded. The agents are working; results appear below.`);
  await refresh();
}

function money(document, name) {
  const value = document.fields?.[name];
  if (value === null || value === undefined) return "";
  return `${value.toFixed ? value.toFixed(2) : value} ${document.fields.currency || ""}`;
}

function badge(status) {
  return el("span", { className: `status ${status}`, textContent: STATUS[status] || status });
}

// A document that waited on the queue records "intake" twice; show each repeat once.
function steps(agents) {
  return agents.filter((agent, index) => agent !== agents[index - 1]).join(" → ");
}

function renderResults(documents) {
  $("empty").hidden = documents.length > 0;
  $("results").replaceChildren(...documents.map((doc) => {
    const row = el("tr", { tabIndex: 0 },
      el("td", { textContent: doc.filename }),
      el("td", {}, badge(doc.status)),
      el("td", { textContent: (doc.document_type || "").replace("_", " ") }),
      el("td", { textContent: doc.fields?.vendor || "" }),
      el("td", { textContent: doc.category || "" }),
      el("td", { className: "num", textContent: money(doc, "total") }),
      el("td", { className: "agents", textContent: steps(doc.agents_run || []) }));
    row.dataset.id = doc.doc_id;
    const open = () => showDetail(doc.doc_id).catch((error) => say(error.message));
    row.addEventListener("click", open);
    row.addEventListener("keydown", (event) => { if (event.key === "Enter") open(); });
    return row;
  }));
}

function reviewCard(doc) {
  const problems = new Set((doc.issues || []).filter((i) => i.severity === "error")
    .map((i) => i.field));
  const form = el("form");
  for (const [name, label] of EDITABLE) {
    const input = el("input", { name, value: doc.fields?.[name] ?? "" });
    if (problems.has(name)) input.className = "problem";
    form.append(el("label", { textContent: label }, input));
  }
  const category = el("select", { name: "category" },
    ...CATEGORIES.map((value) => el("option", { value, textContent: value })));
  category.value = doc.category || "Other";
  form.append(el("label", { textContent: "Category" }, category));

  const approve = el("button", { type: "submit", className: "primary", textContent: "Approve" });
  const reject = el("button", { type: "button", textContent: "Reject" });
  const view = el("button", { type: "button", textContent: "View document and audit" });
  form.append(el("div", { className: "actions" }, approve, reject, view));

  const decide = async (decision) => {
    approve.disabled = reject.disabled = true;
    const fields = {};
    new FormData(form).forEach((value, name) => { fields[name] = value; });
    try {
      await api(`/reviews/${doc.doc_id}`, {
        method: "POST",
        body: JSON.stringify({ decision, fields: decision === "approved" ? fields : {} }),
      });
      say(`${doc.filename}: ${decision}.`);
      card.remove();
      setTimeout(refresh, 1500);
    } catch (error) {
      say(error.message);
      approve.disabled = reject.disabled = false;
    }
  };
  form.addEventListener("submit", (event) => { event.preventDefault(); decide("approved"); });
  reject.addEventListener("click", () => decide("rejected"));
  view.addEventListener("click", () => showDetail(doc.doc_id).catch((e) => say(e.message)));

  const card = el("div", { className: "card" },
    el("strong", { textContent: doc.filename }),
    el("p", { textContent: doc.explanation || "" }), form);
  card.dataset.id = doc.doc_id;
  return card;
}

// Cards are only added or removed, so a refresh never wipes what someone is typing.
function renderReviews(documents) {
  const waiting = documents.filter((doc) => doc.status === "needs_review");
  const box = $("reviews");
  const wanted = new Set(waiting.map((doc) => doc.doc_id));
  [...box.children].forEach((card) => { if (!wanted.has(card.dataset.id)) card.remove(); });
  const shown = new Set([...box.children].map((card) => card.dataset.id));
  waiting.filter((doc) => !shown.has(doc.doc_id)).forEach((doc) => box.append(reviewCard(doc)));
  $("review-section").hidden = waiting.length === 0;
  $("review-count").textContent = waiting.length;
}

function table(headings, rows) {
  return el("table", {},
    el("thead", {}, el("tr", {}, ...headings.map((h) => el("th", { textContent: h })))),
    el("tbody", {}, ...rows.map((row) =>
      el("tr", {}, ...row.map((cell) => el("td", { textContent: cell ?? "—" }))))));
}

async function showDetail(id) {
  const { document: doc, audit, file_url: fileUrl } = await api(`/documents/${id}`);
  selected = { id, status: doc.status };
  $("detail").hidden = false;
  $("detail-title").textContent = `${doc.filename} (${STATUS[doc.status] || doc.status})`;
  $("detail-file").href = fileUrl;
  $("detail-reason").textContent = doc.explanation && doc.status === "needs_review"
    ? doc.explanation : doc.reason || "";
  const parts = [];
  if (doc.fields) {
    parts.push(table(["Field", "Value"],
      [...EDITABLE.map(([name, label]) => [label, doc.fields[name]]), ["Category", doc.category]]));
    parts.push(el("h3", { textContent: "Line items" }),
      table(["Description", "Qty", "Unit price", "Amount"], (doc.fields.line_items || [])
        .map((line) => [line.description, line.quantity, line.unit_price, line.amount])));
  }
  if (doc.issues?.length) {
    parts.push(el("h3", { textContent: "Issues and corrections" }),
      el("ul", {}, ...doc.issues.map((i) => el("li", { textContent: i.message }))));
  }
  $("detail-fields").replaceChildren(...parts);
  $("audit").replaceChildren(...audit.map((entry) => {
    const details = entry.details || {};
    const notes = [details.reason, ...(details.issues || []), ...(details.tried || []),
      details.input_tokens !== undefined
        ? `${details.model}: ${details.input_tokens} tokens in, ${details.output_tokens} out` : null];
    return el("li", {},
      el("b", { textContent: entry.agent }), ` ${entry.decision}`,
      el("small", { textContent: new Date(entry.timestamp).toLocaleTimeString() }),
      ...notes.filter(Boolean).map((note) => el("small", { textContent: note })));
  }));
}

async function refresh() {
  clearTimeout(timer);
  let pending = false;
  try {
    const { documents } = await api("/documents");
    renderResults(documents);
    renderReviews(documents);
    pending = documents.some((doc) => PENDING.includes(doc.status));
    const current = selected && documents.find((doc) => doc.doc_id === selected.id);
    if (current && current.status !== selected.status) await showDetail(selected.id);
  } catch (error) {
    say(`Could not refresh: ${error.message}`);
  }
  timer = setTimeout(refresh, pending ? 3000 : 20000);
}

async function loadSamples() {
  const samples = await (await fetch("samples/index.json")).json();
  $("samples").replaceChildren(...samples.map((sample) => {
    const button = el("button", { type: "button", textContent: sample.label });
    button.dataset.sample = sample.file;
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const blob = await (await fetch(`samples/${sample.file}`)).blob();
        await upload(blob, sample.file);
      } catch (error) {
        say(error.message);
      } finally {
        button.disabled = false;
      }
    });
    return button;
  }));
}

$("file").addEventListener("change", async (event) => {
  const [file] = event.target.files;
  if (!file) return;
  try {
    if (file.size > 5 * 1024 * 1024) throw new Error("that file is over 5 MB");
    await upload(file, file.name);
  } catch (error) {
    say(error.message);
  }
  event.target.value = "";
});

$("export").addEventListener("click", async () => {
  try {
    const url = URL.createObjectURL(await api("/export.csv"));
    el("a", { href: url, download: "documents.csv" }).click();
    URL.revokeObjectURL(url);
  } catch (error) {
    say(error.message);
  }
});

loadSamples().catch(() => say("Could not load the sample list."));
refresh();
