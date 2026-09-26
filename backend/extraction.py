"""AI document understanding: classify each upload, then extract structured facts with evidence.

Every extracted value carries the verbatim evidence snippet + page the model read it from.
We then *verify* that evidence against the actual PDF text (grounding check), and for bank
statements we arithmetically reconcile every extracted row against the running balance.
Nothing here is borrower-specific: the same prompts run on any upload.
"""
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import llm

DOC_TYPES = {
    "bank_statement": "Bank Statement",
    "itr": "Income Tax Return (ITR)",
    "gst_return": "GST Returns",
    "bureau_report": "Credit Bureau Report (CIBIL)",
    "other": "Other / Supporting",
}

CREDIT_CATEGORIES = ["business_receipt", "cash_deposit", "loan_disbursal", "own_transfer_in", "refund_reversal", "interest_credit", "other_credit"]
DEBIT_CATEGORIES = ["emi_debit", "bounce_charge", "supplier_payment", "salary", "rent", "tax_payment", "cash_withdrawal",
                    "own_transfer_out", "utility_other", "other_debit"]
EVENT_CATEGORIES = ["bounce_return", "opening_balance", "closing_balance"]


# ---------------------------------------------------------------------------------------
SUPPORT_CATEGORIES = ["application", "kyc", "business_proof", "financials", "property", "trade", "loan", "other"]


def classify(pages: list[str]) -> dict:
    """Identify the document; for supporting documents also pull key facts and red flags in the same call."""
    sample = "\n".join(pages)[:9000]
    out, meta = llm.chat_json(
        "You are a document-intake analyst in the credit department of an Indian bank processing MSME loan files. "
        "You identify each document and note what a credit officer must know from it. Never invent facts.",
        f"""Identify this document. doc_type must be exactly one of:
- bank_statement: a bank account statement with transactions (current, cash credit/OD or savings)
- itr: an Indian Income Tax Return / ITR acknowledgement / computation of income
- gst_return: GST RETURNS filed (GSTR-3B / GSTR-1 / annual return) with period-wise turnover. A GST *registration certificate* is NOT a return -> other
- bureau_report: a credit bureau report (consumer or commercial) with score/rank and loan accounts
- other: anything else - application form, KYC (PAN/Aadhaar), Udyam/MSME certificate, GST registration, licences, lease,
  utility bills, audited financials, property papers (sale deed, EC, tax receipt, plan, valuation, legal report),
  invoices, stock statement, ageing, sanction letters, quotations, business profile

Return JSON:
{{"doc_type": "...",
 "label": "short name of what this document actually is, e.g. 'Encumbrance certificate', 'PAN card - co-applicant', 'Current account statement'",
 "category": one of {SUPPORT_CATEGORIES} (for doc_type other; else ""),
 "confidence": 0.0-1.0,
 "reason": "one short sentence citing what in the text told you",
 "summary": "for doc_type other: 1-2 sentences on what the document establishes for the loan",
 "key_facts": [ for doc_type other only: up to 10 facts a credit officer needs (names, PAN, dates, amounts, areas, owners, charges, limits, declarations),
               {{"name": "...", "value": "...", "evidence": "<exact verbatim snippet from the text>", "page": n, "confidence": 0-1}} ],
 "flags": [ for doc_type other only: concerns visible IN THIS document (e.g. existing mortgage, overdue debtors, deviation from plan, declaration that may be false); [] if none ]
}}

DOCUMENT TEXT:
{sample}""", max_tokens=3000)
    dt = out.get("doc_type") if out.get("doc_type") in DOC_TYPES else "other"
    res = {"doc_type": dt, "label": out.get("label") or DOC_TYPES[dt], "confidence": float(out.get("confidence") or 0),
           "reason": out.get("reason", ""), "model": meta["model"], "latency_ms": meta["latency_ms"]}
    if dt == "other":
        facts = {}
        for i, f in enumerate(out.get("key_facts") or []):
            if isinstance(f, dict) and f.get("name"):
                key = str(f["name"]).strip().lower().replace(" ", "_")[:40] or f"fact_{i}"
                facts[key if key not in facts else f"{key}_{i}"] = {k: f.get(k) for k in ("value", "evidence", "page", "confidence")}
        res["support"] = {"category": out.get("category") or "other", "summary": out.get("summary", ""),
                          "fields": facts, "flags": [str(x) for x in (out.get("flags") or []) if x]}
    return res


def transcribe(raw: bytes, mime: str) -> list[str]:
    """OCR for scanned PDFs / photos: the multimodal LLM reads the file and returns page-marked text."""
    res = llm.chat(
        "You are a meticulous OCR engine for Indian banking documents. You transcribe exactly what is printed and never summarise.",
        [{"role": "user", "content": [
            {"type": "file", "mime": mime, "data": raw},
            {"type": "text", "text": "Transcribe this document completely. Start each page with a line '[PAGE n]'. "
                                     "Render every table row as cells separated by ' | ', keeping column order and all numbers exactly as printed. "
                                     "Output only the transcription."}]}],
        max_tokens=32000)
    text = res["text"]
    chunks = re.split(r"(?=\[PAGE \d+\])", text)
    pages = [c.strip() for c in chunks if c.strip()]
    if not pages or not pages[0].startswith("[PAGE"):
        pages = [f"[PAGE 1]\n{text.strip()}"]
    return pages


# ---------------------------------------------------------------------------------------
FIELD_RULES = """For every field return an object {"value": <number|string|null>, "evidence": "<exact verbatim snippet copied from the text that contains the value>", "page": <page number>, "confidence": 0.0-1.0}.
Numbers must be plain numbers in rupees (e.g. 1,07,90,000.00 -> 10790000). If a field is not present, use value null and confidence 0 - never guess."""


def extract_itr(pages):
    text = "\n\n".join(pages)
    out, meta = llm.chat_json(
        "You extract data from Indian Income Tax Returns for credit underwriting. You are precise and never invent values.",
        f"""Extract these fields from the ITR below.
Fields: taxpayer_name, pan, form_type, assessment_year, financial_year, business_name,
gross_receipts (business turnover), net_profit (business income), other_income, gross_total_income, total_income, tax_paid, filing_date.
{FIELD_RULES}
Return JSON: {{"fields": {{"<field>": {{...}}, ...}}, "notes": "anything unusual a credit officer should know"}}

ITR TEXT:
{text}""", max_tokens=2500)
    return {"fields": out.get("fields", {}), "notes": out.get("notes", ""), "model": meta["model"], "latency_ms": meta["latency_ms"]}


def extract_gst(pages):
    text = "\n\n".join(pages)
    out, meta = llm.chat_json(
        "You extract data from Indian GST returns for credit underwriting. You are precise and never invent values.",
        f"""Extract header fields and the monthly declared turnover from these GST returns.
Header fields: gstin, legal_name, trade_name, return_type.
{FIELD_RULES}
Also extract "periods": one entry per tax period:
{{"period": "YYYY-MM", "taxable_value": <number>, "total_tax": <IGST+CGST+SGST+cess for the period, number|null>, "filing_date": "YYYY-MM-DD"|null, "evidence": "<verbatim row text>", "page": n, "confidence": 0-1}}
Return JSON: {{"fields": {{...}}, "periods": [...], "notes": "e.g. late filings, nil returns, anything unusual"}}

GST TEXT:
{text}""", max_tokens=3000)
    return {"fields": out.get("fields", {}), "periods": out.get("periods", []), "notes": out.get("notes", ""),
            "model": meta["model"], "latency_ms": meta["latency_ms"]}


def extract_bureau(pages):
    text = "\n\n".join(pages)
    out, meta = llm.chat_json(
        "You extract data from Indian credit bureau reports (CIBIL, Experian, Equifax, CRIF) for underwriting. Never invent values.",
        f"""Extract header fields: subject_name, pan, bureau, report_date, credit_score,
total_active_accounts, total_current_balance, total_overdue_amount, total_monthly_emi (sum of EMIs of ACTIVE loans if EMIs are shown),
max_dpd_last_12_months (highest days-past-due in last 12 months, 0 if none), enquiries_last_6_months, written_off_or_settled_accounts.
{FIELD_RULES}
Also list active loan accounts in "accounts": [{{"lender": "...", "type": "...", "sanctioned": n, "current_balance": n, "emi": n|null, "overdue": n, "dpd_recent": "..."}}]
Return JSON: {{"fields": {{...}}, "accounts": [...], "notes": "credit-relevant observations"}}

BUREAU REPORT TEXT:
{text[:60000]}""", max_tokens=6000)
    return {"fields": out.get("fields", {}), "accounts": out.get("accounts", []), "notes": out.get("notes", ""),
            "model": meta["model"], "latency_ms": meta["latency_ms"]}


def _bank_page(page_text, first):
    header_part = f"""Also return "fields" for the account header: account_holder, bank_name, account_number, account_type, period_from, period_to.
{FIELD_RULES}""" if first else 'Return "fields": {} for this page.'
    out, meta = llm.chat_json(
        "You are a bank-statement analyst in an Indian lender's credit team. You transcribe transactions exactly and "
        "classify each one by reading its narration the way an experienced underwriter would.",
        f"""Transcribe EVERY transaction row on this bank-statement page, in order, as compact arrays:
["YYYY-MM-DD", "narration (verbatim)", debit_amount, credit_amount, balance_after, "category", "counterparty"]
- Amounts are plain numbers in rupees; use 0 when the column is empty. Balance is the balance column on that row.
- category for credits: {", ".join(CREDIT_CATEGORIES)}
- category for debits: {", ".join(DEBIT_CATEGORIES)}
- use "bounce_return" for a row recording a returned/dishonoured cheque or NACH/ECS mandate (even if amounts are 0),
  "opening_balance" / "closing_balance" for balance-only rows.
- Judge by meaning: e.g. a lender name + NACH/ECS debit = emi_debit; a credit from a lender/NBFC marked disbursal = loan_disbursal;
  transfers from the holder's own other account = own_transfer_in. Customer payments = business_receipt.
- counterparty: the lender for emi_debit/loan_disbursal/bounce_return, else the other party if obvious, else "".
{header_part}
Return JSON: {{"fields": {{...}}, "rows": [[...], ...]}}

PAGE TEXT:
{page_text}""", max_tokens=16000)
    return out, meta


def extract_bank(pages, progress=None):
    results = [None] * len(pages)
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_bank_page, p, i == 0): i for i, p in enumerate(pages)}
        done = rows_so_far = 0
        for fut in as_completed(futs):
            results[futs[fut]] = fut.result()
            done += 1
            rows_so_far += len(results[futs[fut]][0].get("rows", []) or [])
            if progress:
                progress({"pages_done": done, "pages_total": len(pages), "rows": rows_so_far})
    fields, rows, latency, model = {}, [], 0, None
    for i, (out, meta) in enumerate(results):
        if i == 0:
            fields = out.get("fields", {}) or {}
        for r in out.get("rows", []):
            if isinstance(r, list) and len(r) >= 6:
                rows.append({"date": r[0], "narration": r[1], "debit": _num(r[2]), "credit": _num(r[3]),
                             "balance": _num(r[4]), "category": r[5], "counterparty": r[6] if len(r) > 6 else "",
                             "page": i + 1})
        latency = max(latency, meta["latency_ms"])
        model = meta["model"]
    return {"fields": fields, "rows": rows, "reconciliation": reconcile(rows), "model": model, "latency_ms": latency}


# ---------------------------------------------------------------------------------------
def _num(v):
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d.\-]", "", str(v))
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def reconcile(rows):
    """Check each extracted row: previous balance - debit + credit == balance. Catches extraction errors."""
    checked = ok = 0
    breaks = []
    prev = None
    for r in rows:
        if r["category"] == "opening_balance":
            prev = r["balance"]
            continue
        if r["category"] in ("bounce_return", "closing_balance") and not r["debit"] and not r["credit"]:
            continue
        if prev is not None and r["balance"]:
            checked += 1
            expected = round(prev - r["debit"] + r["credit"], 2)
            if abs(expected - r["balance"]) <= 1.0:
                ok += 1
            else:
                breaks.append({"date": r["date"], "narration": r["narration"], "expected": expected, "extracted": r["balance"]})
        if r["balance"]:
            prev = r["balance"]
    return {"rows_checked": checked, "rows_reconciled": ok, "pct": round(100 * ok / checked, 1) if checked else 0.0, "breaks": breaks[:10]}


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _digits(s):
    return re.sub(r"[^\d]", "", str(s or ""))


def verify_evidence(fields: dict, pages: list[str]):
    """Grounding check: does the quoted evidence really appear in the document, and does it contain the value?"""
    full = _norm(" ".join(pages))
    full_compact = re.sub(r"[\s|]", "", full)
    for name, f in fields.items():
        if not isinstance(f, dict):
            continue
        ev = _norm(f.get("evidence"))
        found = bool(ev) and (ev in full or re.sub(r"[\s|]", "", ev) in full_compact)
        val = f.get("value")
        if isinstance(val, (int, float)) and val:
            whole = _digits(f"{val:.2f}")
            value_in_ev = whole in _digits(ev) or _digits(int(val)) in _digits(ev)
        elif val:
            value_in_ev = _norm(val) in ev or _digits(val) and _digits(val) in _digits(ev)
        else:
            value_in_ev = False
        f["verified"] = bool(found and value_in_ev)
    return fields


def verify_periods(periods, pages):
    full_digits = _digits(" ".join(pages))
    for p in periods:
        v = p.get("taxable_value")
        p["verified"] = bool(v) and _digits(f"{float(v):.2f}") in full_digits
    return periods


def run_extraction(doc_type, pages, progress=None):
    if doc_type == "bank_statement":
        res = extract_bank(pages, progress)
        verify_evidence(res["fields"], pages)
    elif doc_type == "itr":
        res = extract_itr(pages)
        verify_evidence(res["fields"], pages)
    elif doc_type == "gst_return":
        res = extract_gst(pages)
        verify_evidence(res["fields"], pages)
        verify_periods(res["periods"], pages)
    elif doc_type == "bureau_report":
        res = extract_bureau(pages)
        verify_evidence(res["fields"], pages)
    else:
        return {"fields": {}, "notes": "Supporting document."}
    return res
