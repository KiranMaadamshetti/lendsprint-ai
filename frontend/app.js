/* LendSprint credit-officer UI (vanilla JS, no build step). */
const S = { apps: [], current: null, tab: "overview", poll: null, busy: {} };
const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const inr = (v, d = 0) => (v === null || v === undefined || v === "" || isNaN(v)) ? "-" : "₹" + Number(v).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
const lakh = (v) => (v === null || v === undefined || isNaN(v)) ? "-" : (Math.abs(v) >= 1e7 ? `₹${(v / 1e7).toFixed(2)} Cr` : `₹${(v / 1e5).toFixed(2)} L`);
const pct = (v, d = 1) => (v === null || v === undefined) ? "-" : `${(v * 100).toFixed(d)}%`;
const DOC_LABEL = { bank_statement: "Bank Statement", itr: "ITR", gst_return: "GST Returns", other: "Other" };
const REC_LABEL = { APPROVE: "Approve", APPROVE_WITH_CONDITIONS: "Approve with conditions", REFER: "Refer to credit committee", DECLINE: "Decline" };

function actor() { return $("#actor").value; }
async function api(path, opts = {}) {
  const headers = { "X-Actor": actor(), ...(opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}) };
  const r = await fetch(path, { ...opts, headers: { ...headers, ...(opts.headers || {}) } });
  const txt = await r.text();
  let data; try { data = JSON.parse(txt); } catch { data = txt; }
  if (!r.ok) { const e = new Error((data && data.detail) ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : r.statusText); e.data = data; e.status = r.status; throw e; }
  return data;
}
function toast(msg, err = false) {
  const t = document.createElement("div"); t.className = "toast" + (err ? " err" : ""); t.textContent = msg;
  document.body.appendChild(t); setTimeout(() => t.remove(), err ? 6000 : 3000);
}

// ---------------------------------------------------------------- boot
async function boot() {
  try {
    const h = await api("/api/health");
    const el = $("#llm-status");
    if (h.llm.configured) { el.textContent = `AI: ${h.llm.provider} / ${h.llm.model}`; el.className = "pill ok"; }
    else { el.textContent = "AI not configured - add API key"; el.className = "pill bad"; }
  } catch { }
  const cases = await api("/api/demo/cases");
  const sel = $("#prefill");
  cases.forEach((c) => sel.insertAdjacentHTML("beforeend", `<option value="${c.slug}">${esc(c.business_name)} (synthetic)</option>`));
  sel.onchange = () => {
    const c = cases.find((x) => x.slug === sel.value); const f = $("#new-app-form");
    if (!c) return;
    for (const [k, v] of Object.entries(c)) if (f.elements[k]) f.elements[k].value = v;
    f.dataset.slug = c.slug;
  };
  $("#new-app-btn").onclick = () => { $("#new-app-form").reset(); delete $("#new-app-form").dataset.slug; S.newFiles = []; renderNewFiles(); $("#new-app-dialog").showModal(); };
  const ndz = $("#new-dropzone"), nfi = $("#new-files");
  const addFiles = (fl) => { for (const f of fl) if (f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf")) S.newFiles.push(f); renderNewFiles(); };
  nfi.onchange = () => { addFiles(nfi.files); nfi.value = ""; };
  ndz.ondragover = (e) => { e.preventDefault(); ndz.classList.add("drag"); };
  ndz.ondragleave = () => ndz.classList.remove("drag");
  ndz.ondrop = (e) => { e.preventDefault(); ndz.classList.remove("drag"); addFiles(e.dataTransfer.files); };
  $("#cancel-new").onclick = () => $("#new-app-dialog").close();
  $("#new-app-form").onsubmit = createApp;
  await loadApps();
  if (S.apps[0]) openApp(S.apps[0].id); else renderEmpty();
}

async function createApp(ev) {
  ev.preventDefault();
  const f = ev.target; const body = {};
  for (const el of f.elements) if (el.name) body[el.name] = ["loan_amount", "tenure_months", "interest_rate", "business_vintage_years", "declared_existing_emi"].includes(el.name) ? Number(el.value || 0) : el.value;
  try {
    $("#create-btn").disabled = true;
    const a = await api("/api/applications", { method: "POST", body: JSON.stringify(body) });
    if (S.newFiles.length) {
      const fd = new FormData(); S.newFiles.forEach((x) => fd.append("files", x));
      await api(`/api/applications/${a.id}/documents`, { method: "POST", body: fd });
    }
    $("#new-app-dialog").close();
    S.tab = "live"; S.forceTab = "live";
    await loadApps(); openApp(a.id);
  } catch (e) { toast(e.message, true); }
  $("#create-btn").disabled = false;
}
function renderNewFiles() {
  $("#new-file-list").innerHTML = (S.newFiles || []).map((f, i) => `<span class="chip">📄 ${esc(f.name)} <span class="muted">${(f.size / 1024).toFixed(0)} KB</span><button type="button" onclick="S.newFiles.splice(${i},1);renderNewFiles()">✕</button></span>`).join("");
  $("#create-btn").textContent = S.newFiles.length ? `Create & analyse ${S.newFiles.length} document${S.newFiles.length > 1 ? "s" : ""}` : "Create application";
}

async function loadApps() {
  S.apps = await api("/api/applications");
  $("#app-list").innerHTML = S.apps.map((a) => `
    <div class="app-item ${S.current?.application.id === a.id ? "active" : ""}" onclick="openApp('${a.id}')">
      <div class="name">${esc(a.business_name)}</div>
      <div class="meta">${lakh(a.loan_amount)} · ${a.tenure_months}m · ${esc(a.status)}</div>
      <div class="meta">
        ${a.risk_grade ? `<span class="pill grey">Grade ${esc(a.risk_grade)}</span>` : ""}
        ${a.recommendation ? `<span class="pill ${recClass(a.recommendation)}">${esc(REC_LABEL[a.recommendation] || a.recommendation)}</span>` : ""}
        ${a.open_contradictions ? `<span class="pill high">${a.open_contradictions} flag${a.open_contradictions > 1 ? "s" : ""}</span>` : ""}
        ${!a.readiness.ready && !a.readiness.items.some((i) => i.pending) ? `<span class="pill warn">${a.readiness.missing.length} doc${a.readiness.missing.length > 1 ? "s" : ""} missing</span>` : ""}
      </div>
    </div>`).join("") || `<div class="muted small">No applications yet.</div>`;
}
function recClass(r) { return r === "DECLINE" ? "bad" : r === "REFER" ? "warn" : "ok"; }

function renderEmpty() {
  $("#main").innerHTML = `<div class="empty"><h2>Welcome to LendSprint</h2>
    <p>Create an application, upload the borrower's bank statement, ITR and GST returns,<br/>and Credit Brain will read them, cross-check them and draft a credit assessment.</p>
    <button class="btn primary" onclick="$('#new-app-btn').click()">+ New application</button></div>`;
}

async function openApp(id) {
  clearInterval(S.poll);
  const prevId = S.current?.application.id;
  S.current = await api(`/api/applications/${id}`);
  const processing = () => S.current.documents.some((d) => ["uploaded", "classifying", "extracting"].includes(d.status))
    || ["documents", "crosscheck", "reasoning"].includes(S.current.application.live?.stage);
  if (S.forceTab) { S.tab = S.forceTab; delete S.forceTab; }
  else if (prevId !== id) S.tab = processing() || !latest() ? "live" : "assessment";
  render();
  loadApps();
  if (processing()) {
    S.poll = setInterval(async () => {
      if (S.current?.application.id !== id) return clearInterval(S.poll);
      S.current = await api(`/api/applications/${id}`);
      if (!processing()) {
        clearInterval(S.poll); loadApps();
        const st = S.current.application.live?.stage;
        toast(st === "done" ? "Credit Brain assessment ready" : st === "blocked" ? "Decision blocked - mandatory documents missing" : "Processing finished", st === "blocked" || st === "error");
      }
      if (S.tab === "live" || S.tab === "overview") render();
    }, 1500);
  }
}

// ---------------------------------------------------------------- render
const TABS = [["live", "Live analysis"], ["overview", "Documents"], ["extraction", "AI extraction"], ["cashflow", "Cash-flow"], ["contradictions", "Contradictions"],
  ["assessment", "Credit assessment"], ["trace", "Decision trace"], ["ask", "Ask Credit Brain"], ["audit", "Audit log"]];

function latest() { const a = S.current.application.assessments || []; return a[a.length - 1]; }

function render() {
  const { application: a } = S.current;
  const L = latest();
  $("#main").innerHTML = `
    <div class="header-row">
      <div><h1>${esc(a.business_name)}</h1>
        <div class="sub">${esc(a.borrower_name)} · ${esc(a.constitution)} · ${esc(a.industry || "")} · ${a.business_vintage_years} yrs vintage</div>
        <div class="sub">Requested <b>${inr(a.loan_amount)}</b> for ${a.tenure_months} months @ ${a.interest_rate}% · ${esc(a.purpose || "")}</div></div>
      <div class="flex">
        ${L ? `<span class="pill ${recClass(L.gate.system_recommendation)}">${esc(REC_LABEL[L.gate.system_recommendation])}</span>` : ""}
        <span class="pill grey">${esc(a.status)}</span>
      </div>
    </div>
    <div class="tabs">${TABS.map(([k, l]) => `<div class="tab ${S.tab === k ? "active" : ""}" onclick="setTab('${k}')">${l}</div>`).join("")}</div>
    <div id="tab-body"></div>`;
  const fn = { live: tabLive, overview: tabOverview, extraction: tabExtraction, cashflow: tabCashflow, contradictions: tabContradictions, assessment: tabAssessment, trace: tabTrace, ask: tabAsk, audit: tabAudit }[S.tab];
  $("#tab-body").innerHTML = fn();
  if (S.tab === "overview" || S.tab === "live") wireUpload();
  if (S.tab === "ask") { const c = $(".chat"); if (c) c.scrollTop = c.scrollHeight; }
}
function setTab(t) { S.tab = t; render(); }


// ---------------------------------------------------------------- live analysis
function fv(ext, k) { const f = ext?.fields?.[k]; return f && typeof f === "object" ? f.value : undefined; }
function docFacts(d) {
  const e = d.extraction; if (!e) return [];
  const out = [];
  const push = (l, v) => { if (v !== undefined && v !== null && v !== "") out.push([l, v]); };
  if (d.doc_type === "bank_statement") {
    push("Account holder", fv(e, "account_holder")); push("Bank", fv(e, "bank_name"));
    const months = new Set((e.rows || []).map((r) => String(r.date).slice(0, 7)).filter((m) => /^\d{4}-\d{2}$/.test(m)));
    push("Transactions read", (e.rows || []).length); push("Months covered", months.size);
    push("Bounces spotted", (e.rows || []).filter((r) => r.category === "bounce_return").length);
    push("Reconciles to balance", `${e.reconciliation?.pct ?? 0}%`);
  } else if (d.doc_type === "itr") {
    push("Taxpayer", fv(e, "taxpayer_name")); push("PAN", fv(e, "pan"));
    push("Turnover", fv(e, "gross_receipts") != null ? lakh(fv(e, "gross_receipts")) : undefined);
    push("Net profit", fv(e, "net_profit") != null ? lakh(fv(e, "net_profit")) : undefined);
    push("Financial year", fv(e, "financial_year")); push("Tax paid", fv(e, "tax_paid") != null ? inr(fv(e, "tax_paid")) : undefined);
  } else if (d.doc_type === "gst_return") {
    push("GSTIN", fv(e, "gstin")); push("Trade name", fv(e, "trade_name"));
    const ps = e.periods || [];
    push("Periods filed", ps.length);
    push("Declared turnover", ps.length ? lakh(ps.reduce((a, p) => a + Number(p.taxable_value || 0), 0)) : undefined);
  }
  const f = Object.values(e.fields || {}).filter((x) => x && typeof x === "object" && x.value != null);
  if (f.length) push("Evidence verified", `${f.filter((x) => x.verified).length}/${f.length}`);
  return out;
}
function docCard(d) {
  const st = d.status;
  const fin = ["extracted", "unused"].includes(st);
  const states = [
    "done",
    fin || st === "extracting" ? "done" : st === "error" && !d.classification ? "fail" : "run",
    fin ? "done" : st === "extracting" ? "run" : st === "error" && d.classification ? "fail" : "",
    st === "extracted" ? "done" : "",
  ];
  const step = (i, label, sub = "") => {
    const cls = states[i];
    return `<li class="${cls}"><span class="ic">${cls === "done" ? "✓" : cls === "fail" ? "!" : cls === "run" ? '<span class="spinner" style="width:9px;height:9px"></span>' : ""}</span><div>${label}${sub ? `<div class="small muted">${sub}</div>` : ""}</div></li>`;
  };
  const p = d.progress || {};
  const extractSub = st === "extracting" && d.doc_type === "bank_statement" && p.pages_total
    ? `Page ${p.pages_done}/${p.pages_total} · ${p.rows} transactions read<div class="progress"><i style="width:${Math.max(6, (p.pages_done / p.pages_total) * 100)}%"></i></div>`
    : st === "extracting" ? `<div class="progress"><i class="pulse" style="width:60%"></i></div>` : "";
  const typeSub = d.classification ? `${Math.round(d.classification.confidence * 100)}% confident · ${esc(d.classification.reason)}` : "";
  const cls = st === "error" ? "err" : ["extracted", "unused"].includes(st) ? "done" : "active";
  const facts = docFacts(d);
  return `<div class="doc-live ${cls}">
    <div class="flex between"><span class="fname">📄 ${esc(d.filename)}</span>${d.doc_type !== "other" || d.classification ? `<span class="pill ${d.doc_type === "other" ? "grey" : "ai"}">${DOC_LABEL[d.doc_type]}</span>` : ""}</div>
    <ul class="steps">
      ${step(0, `PDF read · ${d.n_pages} page${d.n_pages > 1 ? "s" : ""}`)}
      ${step(1, states[1] === "done" ? `AI identified: <b>${DOC_LABEL[d.doc_type]}</b>` : "AI identifying document type", typeSub)}
      ${step(2, "AI extracting figures with evidence", extractSub)}
      ${step(3, "Verified against the PDF")}
    </ul>
    ${d.error ? `<div class="small" style="color:var(--bad);margin-top:6px">${esc(d.error)}</div>` : ""}
    ${facts.length ? `<div class="facts">${facts.map(([l, v]) => `<div class="fact"><div class="l">${esc(l)}</div><div class="v">${esc(v)}</div></div>`).join("")}</div>` : ""}
  </div>`;
}
function tabLive() {
  const { documents: docs, readiness: r, application: a } = S.current;
  const live = a.live || {}; const L = latest();
  const busyDocs = docs.some((d) => ["uploaded", "classifying", "extracting"].includes(d.status));
  const stage = live.stage || (L ? "done" : busyDocs ? "documents" : "idle");
  const analysis = stage === "reasoning" ? live.analysis : (stage === "done" && L ? L.analysis : null);
  const S_ = (name) => {
    const seq = ["documents", "crosscheck", "reasoning", "done"];
    const cur = seq.indexOf(stage), me = seq.indexOf(name);
    if (stage === "blocked" && name !== "documents") return "";
    if (stage === "blocked" && name === "documents") return "fail";
    if (stage === "error" && name === "reasoning") return "fail";
    return cur > me ? "done" : cur === me ? "run" : "";
  };
  const ic = (cls, n) => `<div class="stage-ic ${cls}">${cls === "done" ? "✓" : cls === "fail" ? "!" : cls === "run" ? '<span class="spinner"></span>' : n}</div>`;
  const contra = analysis ? analysis.contradictions : [];
  const flagged = contra.filter((c) => c.severity !== "ok");
  const pol = analysis?.policy;
  const verdict = stage === "done" && L ? `
    <div class="verdict"><div class="grade ${esc(L.memo.risk_grade)}">${esc(L.memo.risk_grade)}</div>
      <div style="flex:1"><div class="small muted">Credit Brain recommendation${L.gate.gate_applied ? " (after policy gate)" : ""}</div>
        <div class="rec ${L.gate.system_recommendation}">${esc(REC_LABEL[L.gate.system_recommendation])}</div>
        <div style="margin-top:4px">${esc(L.memo.headline || "")}</div>
        ${L.gate.gate_applied ? `<div class="small" style="color:var(--warn);margin-top:4px">AI suggested ${esc(REC_LABEL[L.memo.recommendation] || L.memo.recommendation)}, capped by policy gate</div>` : ""}</div>
      <div class="flex" style="flex-direction:column;align-items:stretch"><button class="btn primary" onclick="setTab('assessment')">Full assessment →</button><button class="btn" onclick="setTab('trace')">Decision trace</button><button class="btn" onclick="setTab('ask')">Ask Credit Brain</button></div></div>` : "";
  return `
  ${verdict}
  <div class="card" style="margin-top:${verdict ? "16px" : "0"}"><div class="flex between"><h2>Documents</h2>
    <span class="small muted">${docs.filter((d) => d.status === "extracted").length}/${docs.length} processed</span></div>
    ${docs.length ? `<div class="live-grid">${docs.map(docCard).join("")}</div>` : ""}
    ${!docs.length || stage === "blocked" ? `<div class="dropzone" id="dropzone" style="margin-top:12px">${stage === "blocked" ? `<b>Missing: ${r.missing.map((m) => DOC_LABEL[m]).join(", ")}</b>. ` : ""}Drop PDFs here or <label class="browse">browse<input type="file" id="file-input" accept="application/pdf" multiple hidden></label></div>` : ""}
  </div>
  <div class="card"><h2>Credit Brain pipeline</h2>
    <div class="stage-row">${ic(S_("documents"), 1)}<div><b>Mandatory documents</b>
      <div class="checklist" style="margin-top:6px">${r.items.map((i) => `<div class="check ${i.present ? "ok" : i.pending ? "pending" : "missing"}">${i.present ? "✓" : i.pending ? '<span class="spinner"></span>' : "✕"} ${DOC_LABEL[i.doc_type]}</div>`).join("")}</div>
      ${stage === "blocked" ? `<div class="small" style="color:var(--bad);margin-top:6px">Decision blocked and logged: upload the missing document above and the analysis resumes automatically.</div>` : ""}</div></div>
    <div class="stage-row">${ic(S_("crosscheck"), 2)}<div><b>Cross-document checks</b>
      <div class="small" style="margin-top:4px">${analysis ? (flagged.length ? flagged.map((c) => `<span class="pill ${c.severity}">${esc(c.title)}${c.variance_pct != null ? ` ${c.variance_pct > 0 ? "+" : ""}${c.variance_pct}%` : ""}</span>`).join(" ") : `<span class="pill ok">All documents consistent</span>`) : S_("crosscheck") === "run" ? `<span class="pulse">Comparing GST, ITR and bank figures...</span>` : `<span class="muted">Waiting for documents</span>`}</div></div></div>
    <div class="stage-row">${ic(analysis ? (pol.summary.fail ? "fail" : pol.summary.warn ? "warn" : "done") : "", 3)}<div><b>Credit policy</b>
      <div class="small" style="margin-top:4px">${pol ? pol.rules.map((x) => `<span class="pill ${x.status}">${esc(x.name.split(" (")[0])}: ${fmtRule(x)}</span>`).join(" ") + `<div class="muted" style="margin-top:4px">Proposed EMI ${inr(pol.proposed_emi)} · existing EMIs ${inr(pol.existing_emi_used)}</div>` : `<span class="muted">Waiting</span>`}</div></div></div>
    <div class="stage-row">${ic(S_("reasoning"), 4)}<div><b>Credit Brain reasoning (LLM)</b>
      <div class="small" style="margin-top:4px">${stage === "reasoning" ? `<span class="pulse">Weighing evidence and writing the credit memo...</span>` : stage === "done" && L ? `Grade ${esc(L.memo.risk_grade)} · confidence ${Math.round((L.memo.confidence || 0) * 100)}% · ${L.grounding.citations - L.grounding.unresolved}/${L.grounding.citations} citations grounded · ${esc(L.llm.model)} in ${(L.llm.latency_ms / 1000).toFixed(1)}s` : stage === "error" ? `<span style="color:var(--bad)">${esc(live.message || "Failed")}</span> <button class="btn small" onclick="runAssessment()">Retry</button>` : `<span class="muted">Waiting</span>`}</div></div></div>
  </div>
  ${stage === "done" && L ? `<div class="grid2"><div class="card"><h3 style="color:var(--ok)">Strengths</h3><ul class="clean">${(L.memo.strengths || []).map((x) => `<li>${esc(x.point)}</li>`).join("")}</ul></div>
    <div class="card"><h3 style="color:var(--bad)">Risks</h3><ul class="clean">${(L.memo.risks || []).map((x) => `<li><span class="pill ${esc(x.severity)}">${esc(x.severity)}</span> ${esc(x.point)}</li>`).join("")}</ul></div></div>` : ""}`;
}

// ---------------------------------------------------------------- overview
function statusPill(d) {
  const m = { uploaded: ["grey", "Queued"], classifying: ["ai", "AI classifying"], extracting: ["ai", "AI extracting"], extracted: ["ok", "Extracted"], error: ["bad", "Error"], unused: ["grey", "Not used"] }[d.status] || ["grey", d.status];
  const spin = ["classifying", "extracting"].includes(d.status) ? `<span class="spinner"></span>` : "";
  return `<span class="pill ${m[0]}">${spin}${m[1]}</span>`;
}
function tabOverview() {
  const { documents: docs, readiness: r, application: a } = S.current;
  return `
  <div class="card">
    <div class="flex between"><h2>Document readiness</h2>
      <button class="btn primary" onclick="runAssessment()" ${S.busy.assess ? "disabled" : ""}>${S.busy.assess ? `<span class="spinner"></span> Credit Brain is analysing...` : "Run Credit Brain assessment"}</button></div>
    <div class="checklist">${r.items.map((i) => `<div class="check ${i.present ? "ok" : i.pending ? "pending" : "missing"}">
      ${i.present ? "✓" : i.pending ? '<span class="spinner"></span>' : "✕"} <b>${DOC_LABEL[i.doc_type]}</b> <span class="small muted">${i.present ? "received" : i.pending ? "processing" : "mandatory - missing"}</span></div>`).join("")}</div>
    ${!r.ready ? `<p class="small muted">A decision cannot be generated until all mandatory documents are received and extracted. Attempts are blocked and audited.</p>` : ""}
  </div>
  <div class="card">
    <h2>Documents</h2>
    <div class="dropzone" id="dropzone">Drop PDF files here or <label style="display:inline;color:var(--brand);cursor:pointer">browse<input type="file" id="file-input" accept="application/pdf" multiple hidden></label>
      <div class="small" style="margin-top:6px">Credit Brain identifies each document type automatically - no need to label files.</div></div>
    <table style="margin-top:14px"><thead><tr><th>File</th><th>Type (AI-detected)</th><th>Status</th><th>Quality</th><th></th></tr></thead><tbody>
    ${docs.map((d) => `<tr>
      <td><a href="/api/documents/${d.id}/file" target="_blank">${esc(d.filename)}</a><div class="small muted">${d.n_pages} page(s)</div></td>
      <td><select onchange="setDocType('${d.id}', this.value)" style="width:auto">${Object.entries(DOC_LABEL).map(([k, l]) => `<option value="${k}" ${d.doc_type === k ? "selected" : ""}>${l}</option>`).join("")}</select>
        <div class="small muted">${d.type_source === "ai" && d.classification ? `AI ${(d.classification.confidence * 100).toFixed(0)}%: ${esc(d.classification.reason)}` : d.type_source === "officer" ? "set by officer" : ""}</div></td>
      <td>${statusPill(d)}${d.error ? `<div class="small" style="color:var(--bad)">${esc(d.error)}</div>` : ""}</td>
      <td class="small">${docQuality(d)}</td>
      <td><button class="btn small" onclick="deleteDoc('${d.id}')">Remove</button></td></tr>`).join("") || `<tr><td colspan="5" class="muted">No documents yet.</td></tr>`}
    </tbody></table>
  </div>`;
}
function docQuality(d) {
  const e = d.extraction; if (!e) return "";
  const f = Object.values(e.fields || {}).filter((x) => x && typeof x === "object");
  const ver = f.filter((x) => x.verified).length;
  let s = f.length ? `${ver}/${f.length} fields evidence-verified` : "";
  if (e.reconciliation) s += `<br/>${e.rows.length} txns · ${e.reconciliation.pct}% reconcile`;
  if (e.periods) s += `<br/>${e.periods.length} GST periods`;
  return s;
}
function wireUpload() {
  const dz = $("#dropzone"); const fi = $("#file-input");
  if (!dz) return;
  fi.onchange = () => uploadFiles([...fi.files]);
  dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("drag"); };
  dz.ondragleave = () => dz.classList.remove("drag");
  dz.ondrop = (e) => { e.preventDefault(); dz.classList.remove("drag"); uploadFiles([...e.dataTransfer.files]); };
}
async function uploadFiles(files) {
  if (!files.length) return;
  const fd = new FormData(); files.forEach((f) => fd.append("files", f));
  try { await api(`/api/applications/${S.current.application.id}/documents`, { method: "POST", body: fd }); toast(`Uploaded ${files.length} file(s) - AI is reading them`); openApp(S.current.application.id); }
  catch (e) { toast(e.message, true); }
}
async function setDocType(id, t) { await api(`/api/documents/${id}`, { method: "PATCH", body: JSON.stringify({ doc_type: t }) }); openApp(S.current.application.id); }
async function deleteDoc(id) { await api(`/api/documents/${id}`, { method: "DELETE" }); openApp(S.current.application.id); }

async function runAssessment() {
  S.busy.assess = true; render();
  try {
    await api(`/api/applications/${S.current.application.id}/assess`, { method: "POST" });
    S.busy.assess = false; S.tab = "assessment"; await openApp(S.current.application.id); toast("Assessment ready");
  } catch (e) {
    S.busy.assess = false;
    if (e.status === 400 && e.data?.missing) toast(`Decision blocked - missing: ${e.data.missing.map((m) => DOC_LABEL[m]).join(", ")}`, true);
    else toast(e.message, true);
    openApp(S.current.application.id);
  }
}

// ---------------------------------------------------------------- extraction
function fieldRows(fields) {
  return Object.entries(fields || {}).filter(([, f]) => f && typeof f === "object").map(([k, f]) => `
    <tr><td><b>${esc(k.replace(/_/g, " "))}</b></td>
      <td>${typeof f.value === "number" ? inr(f.value) : esc(f.value ?? "-")}${f.evidence ? `<div class="evidence">"${esc(f.evidence)}" <span class="muted">p.${esc(f.page ?? "?")}</span></div>` : ""}</td>
      <td><span class="conf"><i style="width:${Math.round((f.confidence || 0) * 100)}%"></i></span> <span class="small">${Math.round((f.confidence || 0) * 100)}%</span></td>
      <td>${f.value == null ? `<span class="pill grey">not found</span>` : f.verified ? `<span class="pill ok">✓ verified in PDF</span>` : `<span class="pill warn">unverified</span>`}</td></tr>`).join("");
}
function tabExtraction() {
  const docs = S.current.documents.filter((d) => d.extraction);
  if (!docs.length) return `<div class="card empty">Upload documents to see what Credit Brain extracted.</div>`;
  return docs.map((d) => {
    const e = d.extraction;
    let extra = "";
    if (d.doc_type === "gst_return" && e.periods) extra = `<h3 style="margin-top:14px">Monthly declared turnover</h3><table><thead><tr><th>Period</th><th class="num">Taxable value</th><th>Filed</th><th>Evidence</th><th></th></tr></thead><tbody>
      ${e.periods.map((p) => `<tr><td>${esc(p.period)}</td><td class="num">${inr(p.taxable_value)}</td><td>${esc(p.filing_date || "-")}</td><td><div class="evidence">${esc(p.evidence || "")}</div></td><td>${p.verified ? `<span class="pill ok">✓</span>` : `<span class="pill warn">?</span>`}</td></tr>`).join("")}</tbody></table>`;
    if (d.doc_type === "bank_statement" && e.rows) {
      const rc = e.reconciliation;
      extra = `<div class="flex" style="margin:14px 0 8px"><h3 style="margin:0">Transactions read & classified by AI (${e.rows.length})</h3>
        <span class="pill ${rc.pct >= 95 ? "ok" : "warn"}">Arithmetic check: ${rc.rows_reconciled}/${rc.rows_checked} rows reconcile to running balance (${rc.pct}%)</span></div>
        ${rc.breaks.length ? `<div class="small" style="color:var(--bad);margin-bottom:6px">Breaks: ${rc.breaks.map((b) => `${esc(b.date)} ${esc(b.narration)} (expected ${inr(b.expected, 2)}, read ${inr(b.extracted, 2)})`).join("; ")}</div>` : ""}
        <div class="scroll"><table><thead><tr><th>Date</th><th>Narration</th><th class="num">Debit</th><th class="num">Credit</th><th class="num">Balance</th><th>AI category</th><th>Counterparty</th></tr></thead><tbody>
        ${e.rows.map((r) => `<tr><td class="mono">${esc(r.date)}</td><td class="small">${esc(r.narration)}</td><td class="num">${r.debit ? inr(r.debit) : ""}</td><td class="num">${r.credit ? inr(r.credit) : ""}</td><td class="num">${inr(r.balance)}</td>
          <td><span class="pill ${catClass(r.category)}">${esc(r.category)}</span></td><td class="small">${esc(r.counterparty || "")}</td></tr>`).join("")}</tbody></table></div>`;
    }
    return `<div class="card"><div class="flex between"><h2>${DOC_LABEL[d.doc_type]} <span class="muted small">· ${esc(d.filename)}</span></h2><span class="pill ai">${esc(e.model || "")} · ${((e.latency_ms || 0) / 1000).toFixed(1)}s</span></div>
      <table><thead><tr><th>Field</th><th>Value & verbatim evidence</th><th>Model confidence</th><th>Grounding</th></tr></thead><tbody>${fieldRows(e.fields)}</tbody></table>
      ${e.notes ? `<p class="small"><b>AI notes:</b> ${esc(e.notes)}</p>` : ""}${extra}</div>`;
  }).join("");
}
function catClass(c) { return ["bounce_return", "bounce_charge", "loan_disbursal"].includes(c) ? "bad" : c === "emi_debit" ? "warn" : ["business_receipt", "cash_deposit"].includes(c) ? "ok" : "grey"; }

// ---------------------------------------------------------------- cashflow
function tabCashflow() {
  const L = latest(); const bm = L?.analysis.bank_metrics;
  if (!bm) return `<div class="card empty">Run the assessment to see cash-flow analytics.</div>`;
  const gstDoc = S.current.documents.find((d) => d.doc_type === "gst_return" && d.extraction);
  const gst = Object.fromEntries((gstDoc?.extraction.periods || []).map((p) => [p.period, Number(p.taxable_value || 0)]));
  const max = Math.max(...bm.monthly.map((m) => Math.max(m.business_credits, gst[m.month] || 0)), 1);
  return `<div class="card"><h2>Banking summary (${bm.months.length} months)</h2><div class="kpis">
    ${kpi("Avg monthly business credits", lakh(bm.avg_monthly_business_credits))}${kpi("Annualised turnover", lakh(bm.annualised_business_credits))}
    ${kpi("Avg operating outflows / m", lakh(bm.avg_monthly_operating_outflows))}${kpi("Observed EMIs / m", inr(bm.observed_monthly_emi))}
    ${kpi("Average balance", lakh(bm.average_balance))}${kpi("Minimum balance", lakh(bm.min_balance))}
    ${kpi("Cash deposit share", pct(bm.cash_deposit_share))}${kpi("Bounces", bm.bounces.length)}</div></div>
  <div class="card"><h2>Bank business credits vs GST-declared turnover</h2>
    <div class="bars">${bm.monthly.map((m) => `<div class="bargroup" title="${m.month}: bank ${inr(m.business_credits)} / GST ${inr(gst[m.month])}">
      <div class="bar bank" style="height:${(m.business_credits / max) * 100}%"></div><div class="bar gst" style="height:${((gst[m.month] || 0) / max) * 100}%"></div></div>`).join("")}</div>
    <div class="barlabels">${bm.monthly.map((m) => `<span>${m.month}</span>`).join("")}</div>
    <div class="legend"><span><i style="background:#1f4fd1"></i>Bank business credits</span><span><i style="background:#f59e0b"></i>GST taxable value</span></div></div>
  <div class="grid2">
    <div class="card"><h3>EMIs detected by AI in bank statement</h3>${bm.emi_lenders.length ? `<table><tbody>${bm.emi_lenders.map((l) => `<tr><td>${esc(l.lender)}</td><td class="num">${inr(l.avg_monthly)}/m avg</td></tr>`).join("")}</tbody></table>` : `<p class="muted">None</p>`}
      <p class="small muted">Declared in application: ${inr(S.current.application.declared_existing_emi)}/m</p></div>
    <div class="card"><h3>Bounces & excluded credits</h3>
      ${bm.bounces.length ? `<ul class="clean">${bm.bounces.map((b) => `<li><span class="mono">${esc(b.date)}</span> ${esc(b.narration)} <span class="cite">p.${b.page}</span></li>`).join("")}</ul>` : `<p class="muted">No bounces found.</p>`}
      ${Object.keys(bm.excluded_non_business_credits).length ? `<p class="small"><b>Excluded from turnover:</b> ${Object.entries(bm.excluded_non_business_credits).map(([k, v]) => `${k.replace(/_/g, " ")} ${inr(v)}`).join(", ")}</p>` : ""}</div>
  </div>
  <div class="card"><h3>Monthly detail</h3><table><thead><tr><th>Month</th><th class="num">Business credits</th><th class="num">Cash deposits</th><th class="num">Non-business credits</th><th class="num">EMIs</th><th class="num">Operating outflows</th></tr></thead><tbody>
    ${bm.monthly.map((m) => `<tr><td>${m.month}</td><td class="num">${inr(m.business_credits)}</td><td class="num">${inr(m.cash_deposits)}</td><td class="num">${inr(m.non_business_credits)}</td><td class="num">${inr(m.emi_debits)}</td><td class="num">${inr(m.operating_outflows)}</td></tr>`).join("")}</tbody></table></div>`;
}
const kpi = (l, v) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div></div>`;

// ---------------------------------------------------------------- contradictions
function tabContradictions() {
  const L = latest();
  if (!L) return `<div class="card empty">Run the assessment to cross-check documents.</div>`;
  const cs = L.analysis.contradictions;
  const fmt = (x) => typeof x.value === "number" ? inr(x.value) : esc(x.value);
  return `<div class="card"><h2>Contradictions & data integrity</h2><p class="small muted">Figures extracted by AI from different documents are compared against each other. Severity bands: ≥10% medium, ≥20% high, ≥35% critical. A critical flag prevents an automatic approval.</p>
    ${cs.map((c) => `<div class="contra ${c.severity}"><div class="flex between"><b>${esc(c.title)}</b><span class="flex"><span class="cite">${c.id}</span><span class="pill ${c.severity === "ok" ? "ok" : c.severity}">${c.severity === "ok" ? "consistent" : c.severity}</span></span></div>
      <div class="vs"><div class="side"><span class="small muted">${esc(c.lhs.label)}</span><b>${fmt(c.lhs)}</b></div><div class="muted">${c.variance_pct != null ? `${c.variance_pct > 0 ? "+" : ""}${c.variance_pct}%` : "vs"}</div><div class="side"><span class="small muted">${esc(c.rhs.label)}</span><b>${fmt(c.rhs)}</b></div></div>
      <div class="small muted">${esc(c.explain)}</div></div>`).join("") || `<p class="muted">No cross-checks possible yet.</p>`}</div>`;
}

// ---------------------------------------------------------------- assessment
function tabAssessment() {
  const L = latest(); const a = S.current.application;
  if (!L) return `<div class="card empty">No assessment yet.<br/><br/><button class="btn primary" onclick="runAssessment()">Run Credit Brain assessment</button></div>`;
  const m = L.memo; const p = L.analysis.policy; const od = a.officer_decision;
  return `
  <div class="card"><div class="flex between">
    <div class="flex"><div class="grade ${esc(m.risk_grade)}">${esc(m.risk_grade)}</div>
      <div><div class="small muted">System recommendation (after policy gate)</div><div class="rec ${L.gate.system_recommendation}">${esc(REC_LABEL[L.gate.system_recommendation])}</div>
      <div class="small muted">AI recommended: <b>${esc(REC_LABEL[m.recommendation] || m.recommendation)}</b> · confidence ${Math.round((m.confidence || 0) * 100)}% · ${esc(L.llm.model)} · v${L.version}</div></div></div>
    <button class="btn" onclick="runAssessment()" ${S.busy.assess ? "disabled" : ""}>${S.busy.assess ? `<span class="spinner"></span> Re-running...` : "Re-run"}</button></div>
    ${L.gate.gate_applied ? `<div class="contra high" style="margin-top:12px"><b>Policy gate applied.</b> ${L.gate.gate_reasons.map(esc).join(" ")}</div>` : ""}
    <p style="margin-top:12px"><b>${esc(m.headline)}</b></p><p>${esc(m.summary)}</p>
    ${m.suggested_amount ? `<p class="small"><b>AI-suggested safer amount:</b> ${inr(m.suggested_amount)}</p>` : ""}
    <p class="small muted">Grounding: ${L.grounding.citations - L.grounding.unresolved}/${L.grounding.citations} evidence citations resolve to real data points.</p></div>
  <div class="grid2">
    <div class="card"><h3 style="color:var(--ok)">Strengths</h3><ul class="clean">${(m.strengths || []).map((s) => `<li>${esc(s.point)} ${cites(s)}</li>`).join("")}</ul></div>
    <div class="card"><h3 style="color:var(--bad)">Risks</h3><ul class="clean">${(m.risks || []).map((s) => `<li><span class="pill ${esc(s.severity)}">${esc(s.severity)}</span> ${esc(s.point)} ${cites(s)}</li>`).join("")}</ul></div>
  </div>
  <div class="card"><h2>Policy rules <span class="small muted">(${p.summary.pass} pass · ${p.summary.warn} warn · ${p.summary.fail} fail) · proposed EMI ${inr(p.proposed_emi)}</span></h2>
    <table><thead><tr><th>Rule</th><th class="num">Value</th><th>Threshold</th><th>Result</th><th>Inputs</th></tr></thead><tbody>
    ${p.rules.map((r) => `<tr><td><span class="cite">${r.id}</span> ${esc(r.name)}</td><td class="num"><b>${fmtRule(r)}</b></td><td>${esc(r.threshold)}</td><td><span class="pill ${r.status}">${r.status}</span></td><td class="small muted">${ruleInputs(r)}</td></tr>`).join("")}</tbody></table></div>
  <div class="grid2">
    <div class="card"><h3>Conditions</h3><ul class="clean">${(m.conditions || []).map((c) => `<li>${esc(c)}</li>`).join("") || "<li class='muted'>None</li>"}</ul>
      <h3>What would change the decision</h3><p>${esc(m.what_would_change_decision || "")}</p></div>
    <div class="card"><h3>Questions for the borrower</h3><ul class="clean">${(m.questions_for_borrower || []).map((c) => `<li>${esc(c)}</li>`).join("")}</ul></div>
  </div>
  <div class="card"><h2>Officer decision</h2>
    ${od ? `<p><b>${esc(REC_LABEL[od.decision] || od.decision)}</b> by ${esc(od.by)} at ${esc(od.ts)} ${od.override ? `<span class="pill warn">override of ${esc(REC_LABEL[od.system_recommendation])}</span>` : `<span class="pill ok">agrees with system</span>`}</p><p class="small">${esc(od.notes)}</p>` : ""}
    <div class="grid3">
      <label>Decision<select id="od-decision">${Object.entries(REC_LABEL).map(([k, l]) => `<option value="${k}" ${k === L.gate.system_recommendation ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label>Sanctioned amount (INR)<input id="od-amount" type="number" value="${m.suggested_amount || a.loan_amount}"></label>
      <label>&nbsp;<button class="btn primary" onclick="submitDecision()">Record decision</button></label></div>
    <label style="margin-top:10px">Notes / justification (required when overriding the system)<textarea id="od-notes" rows="2"></textarea></label></div>`;
}
function cites(s) { return (s.evidence || []).map((e) => `<span class="cite ${s.evidence_valid === false ? "bad" : ""}">${esc(e)}</span>`).join(""); }
function fmtRule(r) { return r.fmt === "pct" ? pct(r.value) : r.fmt === "x" ? `${r.value}x` : r.fmt === "pctval" ? `${r.value}%` : esc(r.value); }
function ruleInputs(r) {
  return Object.entries(r.inputs || {}).map(([k, v]) => Array.isArray(v) ? (v.length ? `${k}: ${v.length && typeof v[0] === "object" ? v.length : v.join(", ")}` : "") : `${k.replace(/_/g, " ")}: ${typeof v === "number" ? inr(v) : esc(v)}`).filter(Boolean).join("<br/>");
}
async function submitDecision() {
  try {
    await api(`/api/applications/${S.current.application.id}/decision`, { method: "POST", body: JSON.stringify({ decision: $("#od-decision").value, notes: $("#od-notes").value, sanctioned_amount: Number($("#od-amount").value) || null }) });
    toast("Decision recorded"); openApp(S.current.application.id);
  } catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------- trace
function tabTrace() {
  const L = latest(); const docs = S.current.documents; const a = S.current.application;
  if (!L) return `<div class="card empty">Run the assessment to see the decision trace.</div>`;
  const ex = docs.filter((d) => d.extraction && d.status === "extracted");
  const f = ex.flatMap((d) => Object.values(d.extraction.fields || {})).filter((x) => x && typeof x === "object" && x.value != null);
  const bank = ex.find((d) => d.doc_type === "bank_statement")?.extraction;
  const cs = L.analysis.contradictions.filter((c) => c.severity !== "ok");
  const pol = L.analysis.policy;
  const worst = cs.some((c) => c.severity === "critical") ? "bad" : cs.length ? "warn" : "ok";
  const node = (n, cls, title, body) => `<div class="node"><div class="dot ${cls}">${n}</div><div class="body"><b>${title}</b><div class="small" style="margin-top:4px">${body}</div></div></div>`;
  return `<div class="card"><h2>Decision trace - how this recommendation was reached</h2><div class="trace">
    ${node(1, "ok", "Documents received", ex.map((d) => `${DOC_LABEL[d.doc_type]} (${esc(d.filename)}, ${d.type_source === "ai" ? `AI-classified ${Math.round(d.classification.confidence * 100)}%` : "officer-set"})`).join(" · "))}
    ${node(2, "ok", "AI extraction", `${f.length} fields extracted with verbatim evidence${bank ? ` · ${bank.rows.length} bank transactions read and classified` : ""}. Models: ${[...new Set(ex.map((d) => d.extraction.model))].map(esc).join(", ")}`)}
    ${node(3, f.every((x) => x.verified) && (!bank || bank.reconciliation.pct >= 95) ? "ok" : "warn", "Verification (non-AI)", `${f.filter((x) => x.verified).length}/${f.length} evidence snippets found verbatim in the PDFs${bank ? ` · ${bank.reconciliation.rows_reconciled}/${bank.reconciliation.rows_checked} transactions reconcile to the running balance` : ""}`)}
    ${node(4, worst, "Cross-document contradictions", cs.length ? cs.map((c) => `<span class="pill ${c.severity}">${c.id} ${c.variance_pct != null ? c.variance_pct + "%" : ""}</span>`).join(" ") : "All cross-checks consistent")}
    ${node(5, pol.summary.fail ? "bad" : pol.summary.warn ? "warn" : "ok", "Policy engine", pol.rules.map((r) => `<span class="pill ${r.status}">${r.id}: ${fmtRule(r)}</span>`).join(" "))}
    ${node(6, "", "Credit Brain reasoning (LLM)", `Recommended <b>${esc(REC_LABEL[L.memo.recommendation] || L.memo.recommendation)}</b>, grade ${esc(L.memo.risk_grade)}, confidence ${Math.round((L.memo.confidence || 0) * 100)}% · ${L.grounding.citations - L.grounding.unresolved}/${L.grounding.citations} citations grounded · ${esc(L.llm.model)} in ${(L.llm.latency_ms / 1000).toFixed(1)}s`)}
    ${node(7, L.gate.gate_applied ? "warn" : "ok", "Policy gate", L.gate.gate_applied ? L.gate.gate_reasons.map(esc).join(" ") : `No override needed → <b>${esc(REC_LABEL[L.gate.system_recommendation])}</b>`)}
    ${node(8, "human", "Human decision", a.officer_decision ? `${esc(REC_LABEL[a.officer_decision.decision])} by ${esc(a.officer_decision.by)}${a.officer_decision.override ? " (override, justified)" : ""}` : "Awaiting credit officer")}
  </div></div>`;
}

// ---------------------------------------------------------------- ask
function tabAsk() {
  const chat = S.current.chat;
  const sugg = ["Why is this case not a straight approve?", "List every bounce with dates and pages", "What loan amount keeps FOIR under 60%?", "Which customers contribute most of the credits?", "Draft 3 questions for the borrower's call"];
  return `<div class="card"><h2>Ask Credit Brain</h2><p class="small muted">Answers are generated live by the LLM from this applicant's extracted data only, with citations.</p>
    <div class="chat">${chat.map((m) => `<div class="msg ${m.role}">${esc(m.content)}</div>`).join("") || `<div class="muted small">Ask anything about this case.</div>`}
      ${S.busy.chat ? `<div class="msg assistant"><span class="spinner"></span> thinking...</div>` : ""}</div>
    <div class="chat-input"><input id="chat-in" placeholder="e.g. Why did the GST check fail?" onkeydown="if(event.key==='Enter')sendChat()"><button class="btn primary" onclick="sendChat()" ${S.busy.chat ? "disabled" : ""}>Ask</button></div>
    <div class="suggest">${sugg.map((s) => `<button class="btn small" onclick="sendChat(${esc(JSON.stringify(s))})">${esc(s)}</button>`).join("")}</div></div>`;
}
async function sendChat(q) {
  q = q || $("#chat-in").value.trim(); if (!q) return;
  S.current.chat.push({ role: "user", content: q }); S.busy.chat = true; render();
  try { await api(`/api/applications/${S.current.application.id}/chat`, { method: "POST", body: JSON.stringify({ message: q }) }); }
  catch (e) { toast(e.message, true); }
  S.busy.chat = false; await openApp(S.current.application.id);
}

// ---------------------------------------------------------------- audit
function tabAudit() {
  return `<div class="card"><h2>Audit log</h2><table><thead><tr><th>Time (UTC)</th><th>Actor</th><th>Action</th><th>Detail</th></tr></thead><tbody>
    ${S.current.audit.map((r) => `<tr><td class="mono">${esc(r.ts.replace("T", " ").slice(0, 19))}</td><td>${r.actor.includes("AI") ? `<span class="pill ai">${esc(r.actor)}</span>` : esc(r.actor)}</td><td><b>${esc(r.action)}</b></td>
      <td class="small mono">${esc(Object.entries(r.detail).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join("  ")).slice(0, 400)}</td></tr>`).join("")}</tbody></table></div>`;
}

boot();
