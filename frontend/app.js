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
  $("#new-app-btn").onclick = () => { $("#new-app-form").reset(); delete $("#new-app-form").dataset.slug; $("#new-app-dialog").showModal(); };
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
    const a = await api("/api/applications", { method: "POST", body: JSON.stringify(body) });
    if (f.dataset.slug) a._slug = f.dataset.slug;
    S.demoSlug = { ...(S.demoSlug || {}), [a.id]: f.dataset.slug };
    $("#new-app-dialog").close();
    await loadApps(); openApp(a.id);
  } catch (e) { toast(e.message, true); }
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
        ${!a.readiness.ready ? `<span class="pill warn">${a.readiness.missing.length} doc${a.readiness.missing.length > 1 ? "s" : ""} missing</span>` : ""}
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
  if (prevId !== id) S.tab = "overview";
  render();
  loadApps();
  const processing = () => S.current.documents.some((d) => ["uploaded", "classifying", "extracting"].includes(d.status));
  if (processing()) {
    S.poll = setInterval(async () => {
      if (S.current?.application.id !== id) return clearInterval(S.poll);
      S.current = await api(`/api/applications/${id}`);
      if (!processing()) { clearInterval(S.poll); loadApps(); toast("Document processing complete"); }
      render();
    }, 2500);
  }
}

// ---------------------------------------------------------------- render
const TABS = [["overview", "Overview & documents"], ["extraction", "AI extraction"], ["cashflow", "Cash-flow"], ["contradictions", "Contradictions"],
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
  const fn = { overview: tabOverview, extraction: tabExtraction, cashflow: tabCashflow, contradictions: tabContradictions, assessment: tabAssessment, trace: tabTrace, ask: tabAsk, audit: tabAudit }[S.tab];
  $("#tab-body").innerHTML = fn();
  if (S.tab === "overview") wireUpload();
  if (S.tab === "ask") { const c = $(".chat"); if (c) c.scrollTop = c.scrollHeight; }
}
function setTab(t) { S.tab = t; render(); }

// ---------------------------------------------------------------- overview
function statusPill(d) {
  const m = { uploaded: ["grey", "Queued"], classifying: ["ai", "AI classifying"], extracting: ["ai", "AI extracting"], extracted: ["ok", "Extracted"], error: ["bad", "Error"], unused: ["grey", "Not used"] }[d.status] || ["grey", d.status];
  const spin = ["classifying", "extracting"].includes(d.status) ? `<span class="spinner"></span>` : "";
  return `<span class="pill ${m[0]}">${spin}${m[1]}</span>`;
}
function tabOverview() {
  const { documents: docs, readiness: r, application: a } = S.current;
  const slug = (S.demoSlug || {})[a.id] || guessSlug(a);
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
    ${slug ? `<div class="flex" style="margin-top:10px"><span class="small muted">Synthetic sample files for this case:</span>
      ${["bank_statement", "itr", "gst_returns"].map((t) => `<button class="btn small" onclick="uploadSample('${slug}_${t}.pdf')">+ ${t.replace("_", " ")}</button>`).join("")}
      <button class="btn small" onclick="uploadSample(null,'${slug}')">+ all three</button></div>` : ""}
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
function guessSlug(a) { const n = (a.business_name || "").toLowerCase(); return n.includes("arvind") ? "arvind_textiles" : n.includes("lakshmi") ? "sri_lakshmi_traders" : n.includes("bluepeak") ? "bluepeak_logistics" : null; }
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
async function uploadSample(name, slug) {
  const names = name ? [name] : ["bank_statement", "itr", "gst_returns"].map((t) => `${slug}_${t}.pdf`);
  const files = await Promise.all(names.map(async (n) => new File([await (await fetch(`/api/demo/sample/${n}`)).blob()], n, { type: "application/pdf" })));
  uploadFiles(files);
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
