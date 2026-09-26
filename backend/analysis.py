"""Deterministic, auditable layer on top of the AI extraction:
metrics -> cross-document contradiction checks -> credit-policy rules.

Thresholds live in POLICY so a credit-risk team can tune them; every result records its inputs
and the evidence it came from, which is what feeds the Decision Trace in the UI.
"""
import re
from collections import defaultdict

MANDATORY_DOCS = ["bank_statement", "itr", "gst_return"]

POLICY = {
    "foir_max": 0.60,           # (existing + proposed EMI) / monthly income
    "dscr_min": 1.25,           # monthly operating cash surplus / total EMI
    "bounces_max": 2,           # inward NACH/cheque returns in statement window
    "abb_emi_min": 1.5,         # average balance / proposed EMI
    "loan_to_turnover_max": 0.25,
    "min_extraction_reconciliation_pct": 95.0,
}
SEVERITY_BANDS = [(0.35, "critical"), (0.20, "high"), (0.10, "medium")]  # abs variance thresholds

OPERATING_OUT = {"supplier_payment", "salary", "rent", "tax_payment", "utility_other", "other_debit", "cash_withdrawal", "bounce_charge"}
BUSINESS_IN = {"business_receipt", "cash_deposit"}


def emi(principal, annual_rate_pct, months):
    r = annual_rate_pct / 1200
    if r == 0:
        return principal / months
    return principal * r * (1 + r) ** months / ((1 + r) ** months - 1)


def fval(doc, name):
    f = (doc or {}).get("fields", {}).get(name) or {}
    return f.get("value") if isinstance(f, dict) else None


def _month(d):
    m = re.match(r"(\d{4})-(\d{2})", str(d or ""))
    return f"{m.group(1)}-{m.group(2)}" if m else None


# ---------------------------------------------------------------------------------------
def readiness(docs):
    present = {d["doc_type"] for d in docs if d.get("status") == "extracted"}
    pending = {d["doc_type"] for d in docs if d.get("status") in ("uploaded", "ocr", "extracting")}
    unidentified = any(d.get("status") in ("uploaded", "ocr", "classifying") for d in docs)  # type not known yet
    items = [{"doc_type": t, "present": t in present, "pending": t not in present and (t in pending or unidentified)} for t in MANDATORY_DOCS]
    missing = [i["doc_type"] for i in items if not i["present"]]
    return {"items": items, "missing": missing, "ready": not missing}


def bank_metrics(bank):
    rows = bank.get("rows", [])
    by_month = defaultdict(lambda: defaultdict(float))
    bounces, emi_lenders = [], defaultdict(float)
    per_acct = defaultdict(list)
    for r in rows:
        m = _month(r["date"])
        cat = r["category"]
        if r["balance"] and cat not in ("opening_balance", "closing_balance"):
            per_acct[r.get("source", "account")].append(r["balance"])
        if not m or cat in ("opening_balance", "closing_balance"):
            continue
        amt = r["credit"] or r["debit"]
        by_month[m][cat] += amt
        if cat == "bounce_return":
            bounces.append({"date": r["date"], "narration": r["narration"], "counterparty": r.get("counterparty", ""), "page": r["page"]})
        if cat == "emi_debit":
            emi_lenders[r.get("counterparty") or r["narration"]] += r["debit"]
    months = sorted(by_month)
    n = max(len(months), 1)
    monthly = []
    for m in months:
        c = by_month[m]
        biz = sum(c[k] for k in BUSINESS_IN)
        ops = sum(c[k] for k in OPERATING_OUT)
        monthly.append({"month": m, "business_credits": biz, "cash_deposits": c["cash_deposit"],
                        "non_business_credits": c["loan_disbursal"] + c["own_transfer_in"] + c["refund_reversal"] + c["other_credit"] + c["interest_credit"],
                        "emi_debits": c["emi_debit"], "operating_outflows": ops, "bounces": c.get("bounce_return", 0) and 1})
    tot_biz = sum(x["business_credits"] for x in monthly)
    excluded = defaultdict(float)
    for m in months:
        for k in ("loan_disbursal", "own_transfer_in", "refund_reversal"):
            excluded[k] += by_month[m][k]
    lenders = [{"lender": k, "avg_monthly": round(v / n, 2)} for k, v in emi_lenders.items()]
    return {
        "months": months,
        "monthly": monthly,
        "avg_monthly_business_credits": round(tot_biz / n, 2),
        "annualised_business_credits": round(tot_biz / n * 12, 2),
        "cash_deposit_share": round(sum(x["cash_deposits"] for x in monthly) / tot_biz, 4) if tot_biz else 0,
        "avg_monthly_operating_outflows": round(sum(x["operating_outflows"] for x in monthly) / n, 2),
        "observed_monthly_emi": round(sum(x["emi_debits"] for x in monthly) / n, 2),
        "emi_lenders": lenders,
        "bounces": bounces,
        "accounts": [{"source": k, "average_balance": round(sum(v) / len(v), 2), "min_balance": min(v), "overdrawn": sum(v) / len(v) < 0}
                     for k, v in per_acct.items() if v],
        # ABB: sum of average balances of accounts in credit; overdrawn CC/OD accounts are shown separately
        "average_balance": round(sum(sum(v) / len(v) for v in per_acct.values() if v and sum(v) >= 0), 2),
        "min_balance": min((min(v) for v in per_acct.values() if v and sum(v) >= 0), default=0),
        "excluded_non_business_credits": {k: v for k, v in excluded.items() if v},
    }


def _severity(v):
    for thr, sev in SEVERITY_BANDS:
        if abs(v) >= thr:
            return sev
    return None


def contradictions(app, bank, bm, itr, gst, bureau=None):
    out = []
    # 0. Bureau EMIs vs declared EMIs
    b_emi = fval(bureau, "total_monthly_emi")
    if b_emi:
        declared = float(app.get("declared_existing_emi") or 0)
        b_emi = float(b_emi)
        if b_emi > declared * 1.10 + 1000:
            v = (b_emi - declared) / declared if declared else 1.0
            out.append({"id": "C-BUREAU", "title": "Declared EMIs vs EMIs on credit bureau", "severity": _severity(v) or "medium",
                        "variance_pct": round(v * 100, 1), "lhs": {"label": "Bureau total EMI (active loans)", "value": b_emi},
                        "rhs": {"label": "Declared in application", "value": declared},
                        "explain": "The bureau shows obligations the borrower did not declare."})
    # 1. GST invoice value (taxable + tax, i.e. what customers actually pay) vs bank business credits, same months only
    if bank and gst and bm["months"]:
        gst_by_m, taxed = {}, 0
        for p in gst.get("periods", []):
            tv = float(p.get("taxable_value") or 0)
            tax = float(p.get("total_tax") or 0)
            taxed += 1 if tax else 0
            gst_by_m[p.get("period")] = tv + tax
        common = [m for m in bm["months"] if m in gst_by_m]
        if common:
            g = sum(gst_by_m[m] for m in common)
            b = sum(x["business_credits"] for x in bm["monthly"] if x["month"] in common)
            v = (g - b) / b if b else 0
            sev = _severity(v)
            label = "GST invoice value incl. tax" if taxed else "GST taxable value"
            out.append({"id": "C-TURNOVER", "title": "GST-declared turnover vs banking turnover", "severity": sev or "ok",
                        "variance_pct": round(v * 100, 1), "lhs": {"label": f"{label} ({len(common)} months)", "value": g},
                        "rhs": {"label": "Bank business credits (same months)", "value": b}, "months": common,
                        "explain": "GST turnover exceeding banked receipts can mean unbanked cash sales, receipts routed to another account, or inflated GST filings." if v > 0
                        else "Banked receipts exceed GST turnover: possible under-reporting to GST or non-business credits mis-tagged."})
    # 2. ITR gross receipts vs annualised bank business credits
    gross = fval(itr, "gross_receipts")
    if bank and gross and bm["annualised_business_credits"]:
        b = bm["annualised_business_credits"]
        v = (gross - b) / b
        out.append({"id": "C-INCOME", "title": "ITR turnover vs annualised banking turnover", "severity": _severity(v) or "ok",
                    "variance_pct": round(v * 100, 1), "lhs": {"label": f"ITR gross receipts (FY {fval(itr, 'financial_year') or '?'})", "value": gross},
                    "rhs": {"label": "Bank business credits x 12/n", "value": b},
                    "explain": "Different periods (ITR is the last full FY) so moderate variance is normal; large gaps need an explanation."})
    # 3. Identity: PAN embedded in GSTIN must match ITR PAN
    pan, gstin = fval(itr, "pan"), fval(gst, "gstin")
    if pan and gstin:
        embedded = str(gstin)[2:12].upper()
        match = embedded == str(pan).upper()
        out.append({"id": "C-IDENTITY", "title": "PAN in GSTIN vs PAN on ITR", "severity": "ok" if match else "critical",
                    "variance_pct": None, "lhs": {"label": "PAN inside GSTIN", "value": embedded}, "rhs": {"label": "ITR PAN", "value": pan},
                    "explain": "GSTIN characters 3-12 are the holder's PAN; a mismatch means the documents may belong to different entities."})
    # 4. Declared existing EMI vs EMIs actually seen in the bank statement
    if bank:
        declared = float(app.get("declared_existing_emi") or 0)
        observed = bm["observed_monthly_emi"] + bm.get("personal_monthly_emi", 0)
        if observed > declared * 1.10 + 1000:
            v = (observed - declared) / declared if declared else 1.0
            out.append({"id": "C-DEBT", "title": "Declared EMIs vs EMIs observed in bank", "severity": _severity(v) or "medium",
                        "variance_pct": round(v * 100, 1), "lhs": {"label": "Observed avg monthly EMI", "value": observed},
                        "rhs": {"label": "Declared in application", "value": declared},
                        "explain": "Borrower may have undisclosed obligations."})
        disb = bm["excluded_non_business_credits"].get("loan_disbursal")
        if disb:
            out.append({"id": "C-NEWDEBT", "title": "Fresh loan disbursal credited during statement window", "severity": "high",
                        "variance_pct": None, "lhs": {"label": "Loan disbursals credited", "value": disb}, "rhs": {"label": "Excluded from turnover", "value": disb},
                        "explain": "New borrowing shortly before applying can signal liquidity stress; confirm with bureau and ask for sanction letter."})
    return out


def policy(app, bm, itr, contra, recon_pct, bureau=None):
    amount, rate, tenure = float(app["loan_amount"]), float(app["interest_rate"]), int(app["tenure_months"])
    new_emi = emi(amount, rate, tenure)
    bureau_emi = float(fval(bureau, "total_monthly_emi") or 0)
    observed = (bm["observed_monthly_emi"] + bm.get("personal_monthly_emi", 0)) if bm else 0
    existing = max(float(app.get("declared_existing_emi") or 0), observed, bureau_emi)
    np_ = fval(itr, "net_profit")
    rules = []

    def rule(id_, name, value, threshold, status, inputs, fmt="ratio"):
        rules.append({"id": id_, "name": name, "value": value, "threshold": threshold, "status": status, "inputs": inputs, "fmt": fmt})

    if np_:
        income = float(np_) / 12
        foir = (existing + new_emi) / income if income else 9.99
        rule("P-FOIR", "FOIR (existing + proposed EMI / monthly ITR income)", round(foir, 3), f"<= {POLICY['foir_max']:.0%}",
             "pass" if foir <= POLICY["foir_max"] else ("warn" if foir <= POLICY["foir_max"] + 0.1 else "fail"),
             {"existing_emi": existing, "proposed_emi": round(new_emi, 2), "monthly_income": round(income, 2)}, "pct")
    if bm:
        surplus = bm["avg_monthly_business_credits"] - bm["avg_monthly_operating_outflows"]
        dscr = surplus / (existing + new_emi) if existing + new_emi else 9.99
        rule("P-DSCR", "Cash-flow DSCR (operating surplus / total EMI)", round(dscr, 2), f">= {POLICY['dscr_min']}",
             "pass" if dscr >= POLICY["dscr_min"] else ("warn" if dscr >= 1.0 else "fail"),
             {"monthly_business_credits": bm["avg_monthly_business_credits"], "monthly_operating_outflows": bm["avg_monthly_operating_outflows"],
              "total_emi": round(existing + new_emi, 2)}, "x")
        nb = len(bm["bounces"])
        rule("P-BOUNCE", "Inward cheque / NACH returns in statement window", nb, f"<= {POLICY['bounces_max']}",
             "pass" if nb == 0 else ("warn" if nb <= POLICY["bounces_max"] else "fail"), {"bounces": bm["bounces"]}, "int")
        abb = bm["average_balance"] / new_emi if new_emi else 0
        rule("P-ABB", "Average balance / proposed EMI", round(abb, 2), f">= {POLICY['abb_emi_min']}",
             "pass" if abb >= POLICY["abb_emi_min"] else "fail", {"average_balance": bm["average_balance"], "proposed_emi": round(new_emi, 2)}, "x")
        ltt = amount / bm["annualised_business_credits"] if bm["annualised_business_credits"] else 9.99
        rule("P-LTT", "Loan amount / annual banking turnover", round(ltt, 3), f"<= {POLICY['loan_to_turnover_max']:.0%}",
             "pass" if ltt <= POLICY["loan_to_turnover_max"] else "fail", {"loan_amount": amount, "annual_turnover": bm["annualised_business_credits"]}, "pct")
    score = fval(bureau, "credit_score")
    if score:
        try:
            score = float(score)
            dpd = float(fval(bureau, "max_dpd_last_12_months") or 0)
            st = "fail" if score < 650 or dpd > 60 else ("warn" if score < 700 or dpd > 0 else "pass")
            rule("P-BUREAU", "Bureau score / recent DPD", score, ">= 700 and no DPD", st, {"score": score, "max_dpd_12m": dpd}, "int")
        except (TypeError, ValueError):
            pass
    crit = [c["id"] for c in contra if c["severity"] == "critical"]
    high = [c["id"] for c in contra if c["severity"] == "high"]
    rule("P-INTEGRITY", "Cross-document data integrity", len(crit) + len(high), "no critical contradictions",
         "fail" if crit else ("warn" if high else "pass"), {"critical": crit, "high": high}, "int")
    if recon_pct is not None:
        rule("P-EXTRACT", "Bank extraction reconciliation (rows matching running balance)", recon_pct,
             f">= {POLICY['min_extraction_reconciliation_pct']}%",
             "pass" if recon_pct >= POLICY["min_extraction_reconciliation_pct"] else "warn", {}, "pctval")
    return {"proposed_emi": round(new_emi, 2), "existing_emi_used": existing, "rules": rules,
            "summary": {s: sum(1 for r in rules if r["status"] == s) for s in ("pass", "warn", "fail")}}


PERSONAL_HINTS = ("saving", "sb ", "personal", "salary")


def _is_personal(ext):
    t = str(fval(ext, "account_type") or "").lower()
    return any(h in t for h in PERSONAL_HINTS)


def _merge_bank(docs_):
    rows, checked, ok, breaks = [], 0, 0, []
    for d in docs_:
        e = d["extraction"]
        rows += [{**r, "source": d["filename"]} for r in e.get("rows", [])]
        rc = e.get("reconciliation") or {}
        checked += rc.get("rows_checked", 0); ok += rc.get("rows_reconciled", 0); breaks += rc.get("breaks", [])
    rows.sort(key=lambda r: str(r.get("date")))
    return {"fields": docs_[0]["extraction"].get("fields", {}), "rows": rows, "accounts": len(docs_),
            "account_names": [d["filename"] for d in docs_],
            "reconciliation": {"rows_checked": checked, "rows_reconciled": ok, "pct": round(100 * ok / checked, 1) if checked else 0.0, "breaks": breaks[:10]}}


def _merge_bureau(exts):
    """Several reports (applicant, co-applicant, commercial): de-duplicate loan accounts, sum EMIs, take the weakest score."""
    accts, seen = [], set()
    for e in exts:
        for ac in e.get("accounts") or []:
            key = (str(ac.get("lender", "")).lower()[:18], str(ac.get("type", "")).lower()[:10], str(ac.get("sanctioned")))
            if key not in seen:
                seen.add(key)
                accts.append(ac)
    def num(v):
        try:
            return float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            return 0.0
    emi_accts = sum(num(a.get("emi")) for a in accts)
    emi_fields = sum(num(fval(e, "total_monthly_emi")) for e in exts)
    scores = [num(fval(e, "credit_score")) for e in exts if num(fval(e, "credit_score")) >= 300]
    dpd = max([num(fval(e, "max_dpd_last_12_months")) for e in exts] or [0])
    enq = sum(num(fval(e, "enquiries_last_6_months")) for e in exts)
    reports = [{"subject": fval(e, "subject_name"), "score": fval(e, "credit_score"), "emi": fval(e, "total_monthly_emi")} for e in exts]
    return {"fields": {"credit_score": {"value": min(scores) if scores else None}, "total_monthly_emi": {"value": emi_accts or emi_fields or None},
                       "max_dpd_last_12_months": {"value": dpd}, "enquiries_last_6_months": {"value": enq}},
            "accounts": accts, "reports": reports}


def _combine(docs):
    """Merge multi-document evidence: business bank accounts (current / CC / OD), personal accounts, GST periods,
    latest ITR, all bureau reports."""
    ext = {t: [d for d in docs if d.get("status") == "extracted" and d["doc_type"] == t and d.get("extraction")]
           for t in MANDATORY_DOCS + ["bureau_report"]}
    bank = personal = None
    if ext["bank_statement"]:
        biz = [d for d in ext["bank_statement"] if not _is_personal(d["extraction"])]
        pers = [d for d in ext["bank_statement"] if _is_personal(d["extraction"])]
        if not biz:  # only savings accounts supplied: treat them as the business accounts
            biz, pers = pers, []
        bank = _merge_bank(biz)
        personal = _merge_bank(pers) if pers else None
    gst = None
    if ext["gst_return"]:
        periods = {}
        for d in ext["gst_return"]:
            for p in d["extraction"].get("periods", []):
                if p.get("period") and p.get("taxable_value"):
                    periods.setdefault(p.get("period"), p)
        fields = next((d["extraction"].get("fields") for d in ext["gst_return"] if fval(d["extraction"], "gstin")), {})
        gst = {"fields": fields, "periods": [periods[k] for k in sorted(periods)]}
    itr = None
    if ext["itr"]:
        itr = max((d["extraction"] for d in ext["itr"]), key=lambda e: str(fval(e, "assessment_year") or fval(e, "financial_year") or ""))
    bureau = _merge_bureau([d["extraction"] for d in ext["bureau_report"]]) if ext["bureau_report"] else None
    sources = {t: [d["id"] for d in v] for t, v in ext.items() if v}
    return bank, itr, gst, bureau, sources, personal


def analyse(app, docs):
    bank, itr, gst, bureau, sources, personal = _combine(docs)
    bm = bank_metrics(bank) if bank else None
    if bm is not None:
        pm = bank_metrics(personal) if personal else None
        bm["personal_accounts"] = (personal or {}).get("account_names", [])
        bm["personal_monthly_emi"] = pm["observed_monthly_emi"] if pm else 0
        bm["personal_emi_lenders"] = pm["emi_lenders"] if pm else []
        bm["business_accounts"] = bank.get("account_names", [])
    contra = contradictions(app, bank, bm, itr, gst, bureau)
    recon = bank["reconciliation"]["pct"] if bank else None
    pol = policy(app, bm, itr, contra, recon, bureau)
    return {"bank_metrics": bm, "contradictions": contra, "policy": pol, "sources": sources,
            "bank_accounts": (bank or {}).get("accounts", 0), "bureau_reports": (bureau or {}).get("reports", [])}
