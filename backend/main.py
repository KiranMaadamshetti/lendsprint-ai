"""LendSprint API - FastAPI app serving the credit-officer UI and the AI pipeline."""
import os
import threading
import traceback

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_env():
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

from . import analysis as an  # noqa: E402
from . import brain, db, extraction, llm, pdftext  # noqa: E402

db.init()
app = FastAPI(title="LendSprint - AI Credit Underwriting Copilot")


def actor_of(x_actor):
    return x_actor or "Credit Officer"


# ---------------------------------------------------------------------------------------
class NewApplication(BaseModel):
    borrower_name: str
    business_name: str
    constitution: str = "Proprietorship"
    industry: str = ""
    business_vintage_years: float = 0
    loan_amount: float = Field(gt=0)
    tenure_months: int = Field(gt=0, le=360)
    interest_rate: float = Field(gt=0, lt=40)
    purpose: str = ""
    declared_existing_emi: float = 0


class DocTypeUpdate(BaseModel):
    doc_type: str


class OfficerDecision(BaseModel):
    decision: str
    notes: str = ""
    sanctioned_amount: float | None = None


class ChatIn(BaseModel):
    message: str


# ---------------------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "llm": llm.status()}


@app.get("/api/policy")
def get_policy():
    return {"policy": an.POLICY, "mandatory_docs": an.MANDATORY_DOCS, "severity_bands": an.SEVERITY_BANDS}


@app.get("/api/applications")
def list_applications():
    out = []
    for a in db.list_apps():
        docs = db.list_docs(a["id"])
        latest = (a.get("assessments") or [None])[-1]
        out.append({**{k: a.get(k) for k in ("id", "borrower_name", "business_name", "loan_amount", "tenure_months", "industry", "status", "created")},
                    "documents": len(docs), "readiness": an.readiness(docs),
                    "recommendation": (latest or {}).get("gate", {}).get("system_recommendation"),
                    "risk_grade": ((latest or {}).get("memo") or {}).get("risk_grade"),
                    "open_contradictions": sum(1 for c in (latest or {}).get("analysis", {}).get("contradictions", []) if c["severity"] in ("critical", "high")),
                    "officer_decision": (a.get("officer_decision") or {}).get("decision")})
    return out


@app.post("/api/applications")
def create_application(body: NewApplication, x_actor: str | None = Header(None)):
    aid = db.new_id("app")
    data = {"id": aid, **body.model_dump(), "status": "Documents pending", "created": db.now(), "assessments": []}
    db.put("applications", aid, data)
    db.audit(aid, actor_of(x_actor), "Application created", {"loan_amount": body.loan_amount, "tenure_months": body.tenure_months})
    return data


def _app_or_404(aid):
    a = db.get("applications", aid)
    if not a:
        raise HTTPException(404, "Application not found")
    return a


def _public_doc(d):
    return {k: v for k, v in d.items() if k not in ("pages",)}


@app.get("/api/applications/{aid}")
def get_application(aid: str):
    a = _app_or_404(aid)
    docs = db.list_docs(aid)
    return {"application": a, "documents": [_public_doc(d) for d in docs], "readiness": an.readiness(docs),
            "audit": db.audit_log(aid), "chat": db.chat_history(aid)}


# ---- documents -----------------------------------------------------------------------
def _process(doc_id, actor, classify=True):
    d = db.get("documents", doc_id)
    try:
        pages = d["pages"]
        if classify:
            db.update("documents", doc_id, status="classifying")
            c = extraction.classify(pages)
            d = db.update("documents", doc_id, doc_type=c["doc_type"], type_source="ai", classification=c)
            db.audit(d["app_id"], "Credit Brain (AI)", "Document classified",
                     {"file": d["filename"], "doc_type": c["doc_type"], "confidence": c["confidence"], "reason": c["reason"]})
        db.update("documents", doc_id, status="extracting")
        ext = extraction.run_extraction(d["doc_type"], pages)
        d = db.update("documents", doc_id, extraction=ext, status="extracted" if d["doc_type"] != "other" else "unused")
        detail = {"file": d["filename"], "doc_type": d["doc_type"], "model": ext.get("model"), "latency_ms": ext.get("latency_ms")}
        if d["doc_type"] == "bank_statement":
            detail.update(transactions=len(ext["rows"]), reconciliation_pct=ext["reconciliation"]["pct"])
        fields = ext.get("fields") or {}
        detail["fields_verified"] = f"{sum(1 for f in fields.values() if isinstance(f, dict) and f.get('verified'))}/{len(fields)}"
        db.audit(d["app_id"], "Credit Brain (AI)", "Data extracted", detail)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        db.update("documents", doc_id, status="error", error=str(e)[:500])
        db.audit(d["app_id"], "System", "Extraction failed", {"file": d.get("filename"), "error": str(e)[:300]})


@app.post("/api/applications/{aid}/documents")
async def upload_documents(aid: str, files: list[UploadFile] = File(...), x_actor: str | None = Header(None)):
    _app_or_404(aid)
    if not llm.status()["configured"]:
        raise HTTPException(503, "No LLM API key configured - AI extraction is unavailable. Add a key to .env and restart.")
    created = []
    for f in files:
        raw = await f.read()
        if not raw[:5] == b"%PDF-":
            raise HTTPException(400, f"{f.filename}: only PDF files are supported")
        doc_id = db.new_id("doc")
        path = os.path.join(db.UPLOAD_DIR, f"{doc_id}.pdf")
        with open(path, "wb") as fh:
            fh.write(raw)
        pages = pdftext.extract_pages(raw)
        doc = {"id": doc_id, "app_id": aid, "filename": f.filename, "path": path, "pages": pages, "n_pages": len(pages),
               "doc_type": "other", "type_source": None, "status": "uploaded", "created": db.now()}
        if not pdftext.has_text(pages):
            doc.update(status="error", error="No text layer found (scanned image?). OCR is on the roadmap - upload a text PDF.")
        db.put("documents", doc_id, doc, aid)
        db.audit(aid, actor_of(x_actor), "Document uploaded", {"file": f.filename, "pages": len(pages)})
        if doc["status"] != "error":
            threading.Thread(target=_process, args=(doc_id, actor_of(x_actor)), daemon=True).start()
        created.append(_public_doc(doc))
    return created


@app.patch("/api/documents/{doc_id}")
def set_doc_type(doc_id: str, body: DocTypeUpdate, x_actor: str | None = Header(None)):
    d = db.get("documents", doc_id)
    if not d:
        raise HTTPException(404)
    if body.doc_type not in extraction.DOC_TYPES:
        raise HTTPException(400, "unknown doc_type")
    old = d["doc_type"]
    db.update("documents", doc_id, doc_type=body.doc_type, type_source="officer", status="extracting", extraction=None)
    db.audit(d["app_id"], actor_of(x_actor), "Document type corrected", {"file": d["filename"], "from": old, "to": body.doc_type})
    threading.Thread(target=_process, args=(doc_id, actor_of(x_actor), False), daemon=True).start()
    return {"ok": True}


@app.delete("/api/documents/{doc_id}")
def delete_doc(doc_id: str, x_actor: str | None = Header(None)):
    d = db.get("documents", doc_id)
    if not d:
        raise HTTPException(404)
    db.delete_doc(doc_id)
    db.audit(d["app_id"], actor_of(x_actor), "Document removed", {"file": d["filename"]})
    return {"ok": True}


@app.get("/api/documents/{doc_id}/file")
def doc_file(doc_id: str):
    d = db.get("documents", doc_id)
    if not d:
        raise HTTPException(404)
    return FileResponse(d["path"], media_type="application/pdf", filename=d["filename"])


@app.get("/api/documents/{doc_id}/text")
def doc_text(doc_id: str):
    d = db.get("documents", doc_id)
    if not d:
        raise HTTPException(404)
    return {"pages": d["pages"]}


# ---- assessment ----------------------------------------------------------------------
@app.post("/api/applications/{aid}/assess")
def assess(aid: str, x_actor: str | None = Header(None)):
    a = _app_or_404(aid)
    docs = db.list_docs(aid)
    ready = an.readiness(docs)
    if any(d.get("status") in ("uploaded", "classifying", "extracting") for d in docs):
        raise HTTPException(409, "Documents are still being processed - try again in a few seconds.")
    if not ready["ready"]:
        db.audit(aid, actor_of(x_actor), "Decision blocked", {"missing": ready["missing"]})
        db.update("applications", aid, status="Documents pending")
        return JSONResponse(status_code=400, content={"detail": "Mandatory documents missing", "missing": ready["missing"]})
    result = an.analyse(a, docs)
    ctx = brain.case_context(a, docs, result)
    memo, meta = brain.credit_memo(a, docs, result)
    grounding = brain.ground_check(memo, result, ctx)
    g = brain.gate(memo.get("recommendation"), result)
    version = len(a.get("assessments") or []) + 1
    record = {"version": version, "ts": db.now(), "by": actor_of(x_actor), "analysis": result, "memo": memo, "gate": g,
              "grounding": grounding, "llm": {"model": meta["model"], "latency_ms": meta["latency_ms"], "usage": meta.get("usage")}}
    a["assessments"] = (a.get("assessments") or []) + [record]
    a["status"] = "Assessed"
    db.put("applications", aid, a)
    db.audit(aid, "Credit Brain (AI)", "Assessment generated",
             {"version": version, "ai_recommendation": memo.get("recommendation"), "system_recommendation": g["system_recommendation"],
              "risk_grade": memo.get("risk_grade"), "gate_applied": g["gate_applied"], "model": meta["model"]})
    return record


@app.post("/api/applications/{aid}/decision")
def officer_decision(aid: str, body: OfficerDecision, x_actor: str | None = Header(None)):
    a = _app_or_404(aid)
    latest = (a.get("assessments") or [None])[-1]
    if not latest:
        raise HTTPException(400, "Run the assessment first")
    sys_rec = latest["gate"]["system_recommendation"]
    override = body.decision != sys_rec
    if override and len(body.notes.strip()) < 15:
        raise HTTPException(400, "Overriding the system recommendation requires a written justification (min 15 chars).")
    a["officer_decision"] = {**body.model_dump(), "by": actor_of(x_actor), "ts": db.now(), "override": override,
                             "system_recommendation": sys_rec, "assessment_version": latest["version"]}
    a["status"] = "Decided"
    db.put("applications", aid, a)
    db.audit(aid, actor_of(x_actor), "Officer decision" + (" (OVERRIDE)" if override else ""), a["officer_decision"])
    return a["officer_decision"]


@app.post("/api/applications/{aid}/chat")
def chat(aid: str, body: ChatIn, x_actor: str | None = Header(None)):
    a = _app_or_404(aid)
    latest = (a.get("assessments") or [None])[-1]
    docs = db.list_docs(aid)
    result = latest["analysis"] if latest else an.analyse(a, docs)
    history = db.chat_history(aid)
    res = brain.ask(a, docs, result, (latest or {}).get("memo"), history, body.message)
    db.add_chat(aid, "user", body.message)
    db.add_chat(aid, "assistant", res["text"])
    db.audit(aid, actor_of(x_actor), "Asked Credit Brain", {"question": body.message[:200], "model": res["model"], "latency_ms": res["latency_ms"]})
    return {"answer": res["text"], "model": res["model"]}


# ---- demo seeding (synthetic) --------------------------------------------------------
DEMO_CASES = [
    ("arvind_textiles", dict(borrower_name="Arvind Kumar Ramasamy", business_name="Arvind Textiles", industry="Textiles - knitwear",
                             business_vintage_years=9, loan_amount=2500000, tenure_months=60, interest_rate=11.5,
                             purpose="Two knitting machines + working capital", declared_existing_emi=45200)),
    ("sri_lakshmi_traders", dict(borrower_name="Lakshmi Narayana Bhat", business_name="Sri Lakshmi Traders", industry="FMCG wholesale",
                                 business_vintage_years=6, loan_amount=1500000, tenure_months=48, interest_rate=12.5,
                                 purpose="Festive-season inventory", declared_existing_emi=30500)),
    ("bluepeak_logistics", dict(borrower_name="Rohit Deshmukh", business_name="BluePeak Logistics", industry="Road logistics",
                                business_vintage_years=4, loan_amount=4000000, tenure_months=60, interest_rate=13.0,
                                purpose="Purchase of two trucks", declared_existing_emi=52400)),
]


@app.get("/api/demo/cases")
def demo_cases():
    return [{"slug": s, **c} for s, c in DEMO_CASES]


@app.get("/api/demo/sample/{name}")
def sample_file(name: str):
    path = os.path.join(ROOT, "sample_docs", os.path.basename(name))
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path, media_type="application/pdf", filename=os.path.basename(name))


app.mount("/", StaticFiles(directory=os.path.join(ROOT, "frontend"), html=True), name="ui")
