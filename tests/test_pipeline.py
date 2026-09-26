"""Offline pipeline test.

The LLM is replaced by a TEST-ONLY stub that parses the sample PDFs' tables, so the deterministic
layers (PDF text, reconciliation, evidence verification, metrics, contradictions, policy, gate, API
flow) can be tested without network access. The real app always calls the configured LLM.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["LENDSPRINT_DATA"] = os.path.join(ROOT, "data_test")
os.environ["GEMINI_API_KEY"] = "test"
os.environ["LLM_PROVIDER"] = "gemini"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import llm  # noqa: E402


def _n(s):
    return float(s.replace(",", "")) if s else 0.0


def _date(d):
    dd, mm, yy = d.split("-")
    return f"{yy}-{mm}-{dd}"


def fake_chat(system, messages, max_tokens=4000, json_mode=False):
    text = messages[-1]["content"]
    if not isinstance(text, str):  # OCR request
        return {"text": "[PAGE 1]\nGovernment of India - identity card (scanned)", "model": "stub", "latency_ms": 1, "usage": {}}
    if "Identify this document" in text:
        text = text.split("DOCUMENT TEXT:")[-1]
        t = ("bank_statement" if "Statement of Account" in text else "itr" if "INCOME TAX" in text
             else "bureau_report" if ("Credit Information Report" in text or "Commercial Credit Report" in text)
             else "gst_return" if ("GSTR-3B" in text or "GSTR3B" in text.replace("-", "")) and "Registration Certificate" not in text else "other")
        out = {"doc_type": t, "confidence": 0.97, "reason": "stub", "label": t,
               "key_facts": [{"name": "Holder", "value": "identity card", "evidence": "identity card", "page": 1}] if t == "other" else [],
               "flags": ["stub flag"] if t == "other" else []}
    elif "Transcribe EVERY transaction" in text:
        rows = []
        for line in text.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 6:
                parts = parts[:2] + parts[3:]
            if len(parts) == 5 and re.match(r"\d{2}-\d{2}-\d{4}", parts[0]):
                nar = parts[1]
                cat = ("opening_balance" if "OPENING" in nar else "bounce_return" if "RTN" in nar and "CHGS" not in nar and "CHARGES" not in nar
                       else "bounce_charge" if ("RTN CHGS" in nar or "RETURN CHARGES" in nar) else "emi_debit" if ("NACH DR" in nar or "EMI" in nar) else "loan_disbursal" if "LOAN DISB" in nar
                       else "own_transfer_in" if "TRF FROM" in nar else "own_transfer_out" if ("TRF TO" in nar or "DR SELF" in nar)
                       else "other_debit" if "INTEREST ON CC" in nar
                       else "own_transfer_in" if "SELF" in nar else "cash_deposit" if "CASH DEPOSIT" in nar
                       else "business_receipt" if " CR " in f" {nar} " else "supplier_payment" if "SUPPLIER" in nar
                       else "salary" if "SALARY" in nar else "rent" if "RENT" in nar else "tax_payment" if "GST" in nar
                       else "cash_withdrawal" if "ATM" in nar else "other_debit")
                cp = " ".join(nar.split()[2:4]) if cat in ("emi_debit", "bounce_return") else ""
                rows.append([_date(parts[0]), nar, _n(parts[2]), _n(parts[3]), _n(parts[4]), cat, cp])
        fields = {}
        at = re.search(r"Account type \| ([^\n|]+)", text)
        if at:
            fields["account_type"] = {"value": at.group(1).strip(), "evidence": at.group(1).strip(), "page": 1, "confidence": 0.9}
        if "Account Holder" in text:
            m = re.search(r"Account Holder: (.+?) \(", text)
            fields["account_holder"] = {"value": m.group(1), "evidence": m.group(0)[:-2], "page": 1, "confidence": 0.95}
        out = {"fields": fields, "rows": rows}
    elif "ITR below" in text:
        def grab(label):
            m = re.search(re.escape(label) + r"[^|\n]*\|\s*([\d,\.]+)", text)
            return {"value": _n(m.group(1)), "evidence": m.group(0), "page": 1, "confidence": 0.95} if m else {"value": None}
        pan = re.search(r"PAN\s*[:|]\s*(\w{10})", text)
        out = {"fields": {"gross_receipts": grab("Gross receipts"), "net_profit": grab("Net profit"),
                          "pan": {"value": pan.group(1), "evidence": pan.group(0), "page": 1, "confidence": 0.99},
                          "financial_year": {"value": "2025-26", "evidence": "Financial Year 2025-26", "page": 1, "confidence": 0.9}}}
    elif "GST returns" in text:
        months = {m: f"{i:02d}" for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
        periods = []
        for line in text.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) in (7, 8) and re.match(r"\w{3}-\d{4}", parts[0]):
                mon, yr = parts[0].split("-")
                periods.append({"period": f"{yr}-{months[mon]}", "taxable_value": _n(parts[3]), "total_tax": sum(_n(x) for x in parts[4:7]), "evidence": line, "page": 1, "confidence": 0.95})
        g = re.search(r"GSTIN:?\s*(\w{15})", text)
        out = {"fields": {"gstin": {"value": g.group(1), "evidence": g.group(0), "page": 1, "confidence": 0.99}}, "periods": periods}
    elif "credit bureau reports" in system:
        sc = re.search(r"Credit score \| (\d+)", text)
        accts = []
        for line in text.splitlines():
            ps = [x.strip() for x in line.split("|")]
            if len(ps) == 8 and ps[5] in ("Active", "Closed") and ps[0] != "Lender":
                accts.append({"lender": ps[0], "type": ps[1], "sanctioned": _n(ps[3]), "current_balance": _n(ps[4]) if ps[4][0].isdigit() else 0,
                              "emi": _n(ps[6]) if ps[6][:1].isdigit() else None, "status": ps[5]})
        accts = [a for a in accts if a["status"] == "Active"]
        out = {"fields": {"credit_score": {"value": int(sc.group(1)) if sc else None, "evidence": sc.group(0) if sc else "", "page": 1},
                          "total_monthly_emi": {"value": sum(a["emi"] or 0 for a in accts), "evidence": "", "page": 1}}, "accounts": accts}
    elif "Write the credit assessment" in text:
        out = {"recommendation": "APPROVE", "risk_grade": "B", "confidence": 0.7, "headline": "stub", "summary": "stub",
               "strengths": [{"point": "x", "evidence": ["P-FOIR"]}], "risks": [{"point": "y", "severity": "low", "evidence": ["made-up-id"]}],
               "conditions": [], "questions_for_borrower": [], "what_would_change_decision": "", "suggested_amount": None}
    else:
        return {"text": "stub answer", "model": "stub", "latency_ms": 1, "usage": {}}
    return {"text": json.dumps(out), "model": "stub", "latency_ms": 1, "usage": {}}


@pytest.fixture(scope="module")
def client():
    import shutil
    shutil.rmtree(os.environ["LENDSPRINT_DATA"], ignore_errors=True)
    llm.chat = fake_chat
    from backend import main
    import types
    import threading as _t
    main.threading = types.SimpleNamespace(Thread=_SyncThread, Lock=_t.Lock)
    return TestClient(main.app)


class _SyncThread:
    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


CASES = {
    "arvind_textiles": dict(loan_amount=2500000, tenure_months=60, interest_rate=11.5, declared_existing_emi=45200),
    "sri_lakshmi_traders": dict(loan_amount=1500000, tenure_months=48, interest_rate=12.5, declared_existing_emi=30500),
    "bluepeak_logistics": dict(loan_amount=4000000, tenure_months=60, interest_rate=13.0, declared_existing_emi=52400),
}


def _create(client, slug):
    a = client.post("/api/applications", json={"borrower_name": "X", "business_name": slug, **CASES[slug]}).json()
    return a["id"]


def _upload(client, aid, slug, kinds=("bank_statement", "itr", "gst_returns")):
    files = [("files", (f"{slug}_{k}.pdf", open(os.path.join(ROOT, "sample_docs", f"{slug}_{k}.pdf"), "rb"), "application/pdf")) for k in kinds]
    r = client.post(f"/api/applications/{aid}/documents", files=files)
    assert r.status_code == 200, r.text


def test_blocked_when_docs_missing(client):
    aid = _create(client, "sri_lakshmi_traders")
    _upload(client, aid, "sri_lakshmi_traders", ("bank_statement", "gst_returns"))
    r = client.post(f"/api/applications/{aid}/assess")
    assert r.status_code == 400 and r.json()["missing"] == ["itr"]
    assert any(e["action"] == "Decision blocked" for e in client.get(f"/api/applications/{aid}").json()["audit"])


@pytest.mark.parametrize("slug", list(CASES))
def test_full_pipeline(client, slug):
    aid = _create(client, slug)
    _upload(client, aid, slug)
    docs = client.get(f"/api/applications/{aid}").json()["documents"]
    assert {d["doc_type"] for d in docs} == {"bank_statement", "itr", "gst_return"}
    bank = next(d for d in docs if d["doc_type"] == "bank_statement")["extraction"]
    assert bank["reconciliation"]["pct"] == 100.0, bank["reconciliation"]
    r = client.post(f"/api/applications/{aid}/assess")
    assert r.status_code == 200, r.text
    rec = r.json()
    contra = {c["id"]: c for c in rec["analysis"]["contradictions"]}
    rules = {x["id"]: x for x in rec["analysis"]["policy"]["rules"]}
    print(slug, {k: (v["severity"], v["variance_pct"]) for k, v in contra.items()},
          {k: (v["value"], v["status"]) for k, v in rules.items()}, rec["gate"])
    assert rec["grounding"]["unresolved"] == 1  # the stub's made-up id is caught
    if slug == "arvind_textiles":
        assert contra["C-TURNOVER"]["severity"] == "ok" and contra["C-IDENTITY"]["severity"] == "ok"
        assert rec["gate"]["system_recommendation"] == "APPROVE"
    if slug == "bluepeak_logistics":
        assert contra["C-TURNOVER"]["severity"] == "critical"
        assert "C-NEWDEBT" in contra and "C-DEBT" in contra
        assert len(rec["analysis"]["bank_metrics"]["bounces"]) == 4
        assert rec["gate"]["gate_applied"] and rec["gate"]["system_recommendation"] == "REFER"
    # override needs justification
    assert client.post(f"/api/applications/{aid}/decision", json={"decision": "DECLINE", "notes": ""}).status_code in (200, 400)
    assert client.post(f"/api/applications/{aid}/chat", json={"message": "why?"}).status_code == 200


def test_mixed_batch_does_not_fail(client):
    """A bad file in a batch must not break the upload; scans go through OCR; supporting docs are kept."""
    aid = _create(client, "arvind_textiles")
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    files = [("files", ("broken.pdf", b"%PDF-1.4 garbage", "application/pdf")),
             ("files", ("aadhaar.png", png, "image/png")),
             ("files", ("notes.txt", b"hello", "text/plain")),
             ("files", ("bank.pdf", open(os.path.join(ROOT, "sample_docs", "arvind_textiles_bank_statement.pdf"), "rb"), "application/pdf"))]
    r = client.post(f"/api/applications/{aid}/documents", files=files)
    assert r.status_code == 200, r.text
    docs = {d["filename"]: d for d in client.get(f"/api/applications/{aid}").json()["documents"]}
    assert docs["notes.txt"]["status"] == "error"
    assert docs["aadhaar.png"]["status"] == "extracted" and docs["aadhaar.png"]["ocr_done"]
    assert docs["aadhaar.png"]["extraction"]["flags"] == ["stub flag"]
    assert docs["aadhaar.png"]["extraction"]["fields"]["holder"]["verified"]
    assert docs["bank.pdf"]["status"] == "extracted"
    app = client.get(f"/api/applications/{aid}").json()["application"]
    assert app["live"]["stage"] == "blocked"


def test_msme_loan_file(client):
    """The full synthetic MSME file: 37 documents incl. scans and images, personal + business accounts, 3 bureau reports."""
    folder = os.path.join(ROOT, "sample_docs", "msme_loan_file")
    a = client.post("/api/applications", json={"borrower_name": "Kolluri Venkata Ramana", "business_name": "Sai Durga Precision Engineering",
                                               "loan_amount": 3500000, "tenure_months": 60, "interest_rate": 12.25,
                                               "declared_existing_emi": 52100}).json()
    files = [("files", (f, open(os.path.join(folder, f), "rb"), "application/octet-stream")) for f in sorted(os.listdir(folder))]
    assert len(files) >= 30
    assert client.post(f"/api/applications/{a['id']}/documents", files=files).status_code == 200
    d = client.get(f"/api/applications/{a['id']}").json()
    assert not [x["filename"] for x in d["documents"] if x["status"] != "extracted"]
    rec = d["application"]["assessments"][-1]
    bm = rec["analysis"]["bank_metrics"]
    assert len(bm["business_accounts"]) == 2 and len(bm["personal_accounts"]) == 2
    assert bm["personal_monthly_emi"] > 30000          # car loan + co-applicant's personal loan
    assert len(bm["bounces"]) == 1                     # the CC cheque return
    ids = {c["id"]: c for c in rec["analysis"]["contradictions"]}
    assert ids["C-TURNOVER"]["severity"] == "ok", ids["C-TURNOVER"]
    assert "C-BUREAU" in ids and ids["C-BUREAU"]["rhs"]["value"] == 52100
    assert any(r["id"] == "P-BUREAU" for r in rec["analysis"]["policy"]["rules"])
    print({k: (v["severity"], v["variance_pct"]) for k, v in ids.items()},
          {r["id"]: (r["value"], r["status"]) for r in rec["analysis"]["policy"]["rules"]})
