"""Credit Brain: LLM reasoning over the extracted evidence -> credit memo, plus grounded Q&A.

The model sees only what was extracted from this applicant's documents and the policy results.
Its recommendation is then passed through a policy gate (workflow rule): the AI can never
auto-approve a case that fails a hard policy rule or has a critical contradiction; it can only
refer it to a human. The officer makes and signs the final decision.
"""
import json

from . import llm

ORDER = ["APPROVE", "APPROVE_WITH_CONDITIONS", "REFER", "DECLINE"]


def _fmt_fields(ext):
    if not ext:
        return None
    return {k: v.get("value") if isinstance(v, dict) else v for k, v in (ext.get("fields") or {}).items()}


def case_context(app, docs, analysis, include_txns=False):
    by_type = {d["doc_type"]: d for d in docs if d.get("status") == "extracted"}
    bank = (by_type.get("bank_statement") or {}).get("extraction")
    ctx = {
        "application": {k: app.get(k) for k in ("borrower_name", "business_name", "constitution", "industry", "business_vintage_years",
                                                 "loan_amount", "tenure_months", "interest_rate", "purpose", "declared_existing_emi")},
        "itr": _fmt_fields((by_type.get("itr") or {}).get("extraction")),
        "gst": {"header": _fmt_fields((by_type.get("gst_return") or {}).get("extraction")),
                "periods": [{k: p.get(k) for k in ("period", "taxable_value", "filing_date")}
                            for p in ((by_type.get("gst_return") or {}).get("extraction") or {}).get("periods", [])]},
        "bank_header": _fmt_fields(bank),
        "bank_metrics": analysis.get("bank_metrics"),
        "extraction_quality": {"bank_reconciliation": (bank or {}).get("reconciliation")},
        "contradictions": analysis.get("contradictions"),
        "policy": analysis.get("policy"),
    }
    if include_txns and bank:
        ctx["bank_transactions"] = [[r["date"], r["narration"], r["debit"], r["credit"], r["balance"], r["category"]] for r in bank["rows"]]
    return ctx


MEMO_SYSTEM = """You are the Credit Brain of an Indian bank's MSME lending desk, writing for a credit officer.
Reason like a seasoned underwriter: triangulate bank, GST and ITR evidence, weigh policy results and contradictions,
and be explicit about uncertainty. Use ONLY the facts provided - never invent numbers. Amounts are INR.
Every strength and risk must cite evidence ids from the provided data: policy rule ids (e.g. P-FOIR), contradiction ids
(e.g. C-TURNOVER) or data paths (e.g. bank_metrics.bounces, itr.net_profit, gst.periods)."""


def credit_memo(app, docs, analysis):
    ctx = case_context(app, docs, analysis)
    out, meta = llm.chat_json(MEMO_SYSTEM, f"""CASE DATA (JSON):
{json.dumps(ctx, default=str)}

Write the credit assessment. Return JSON:
{{
 "recommendation": "APPROVE" | "APPROVE_WITH_CONDITIONS" | "REFER" | "DECLINE",
 "risk_grade": "A" | "B" | "C" | "D" | "E",   (A = lowest risk)
 "confidence": 0.0-1.0,   (your confidence in this recommendation given data quality)
 "headline": "one sentence verdict",
 "summary": "3-4 sentence narrative a credit committee can read",
 "strengths": [{{"point": "...", "evidence": ["id", ...]}}],
 "risks": [{{"point": "...", "severity": "low|medium|high|critical", "evidence": ["id", ...]}}],
 "conditions": ["pre-disbursement / sanction conditions, if any"],
 "questions_for_borrower": ["specific questions to resolve open issues"],
 "what_would_change_decision": "the specific facts that would move this to a better or worse outcome",
 "suggested_amount": number | null   (a safer loan amount if the requested one is too high, else null)
}}""", max_tokens=3000)
    return out, meta


def gate(ai_rec, analysis):
    """Workflow guardrail: hard policy failures / critical contradictions cap the outcome at REFER."""
    rec = ai_rec if ai_rec in ORDER else "REFER"
    reasons = []
    fails = [r["id"] for r in analysis["policy"]["rules"] if r["status"] == "fail"]
    crit = [c["id"] for c in analysis["contradictions"] if c["severity"] == "critical"]
    if rec in ("APPROVE", "APPROVE_WITH_CONDITIONS") and (fails or crit):
        reasons.append(f"AI recommended {rec} but hard checks failed ({', '.join(fails + crit)}); capped at REFER for human review.")
        rec = "REFER"
    return {"system_recommendation": rec, "gate_applied": bool(reasons), "gate_reasons": reasons}


def ground_check(memo, analysis, ctx):
    """Verify the evidence ids the model cited actually exist in the case data."""
    valid = {r["id"] for r in analysis["policy"]["rules"]} | {c["id"] for c in analysis["contradictions"]}
    top = set(ctx.keys())
    cited = unknown = 0
    for section in ("strengths", "risks"):
        for item in memo.get(section, []) or []:
            ok = []
            for e in item.get("evidence", []) or []:
                cited += 1
                if e in valid or str(e).split(".")[0] in top or str(e).split(".")[0] in ("bank", "itr", "gst"):
                    ok.append(e)
                else:
                    unknown += 1
            item["evidence_valid"] = len(ok) == len(item.get("evidence", []) or [])
    return {"citations": cited, "unresolved": unknown}


CHAT_SYSTEM = """You are Credit Brain, an assistant to a credit officer reviewing ONE loan application.
Answer only from the case data provided (extracted from the applicant's documents, plus policy and contradiction results).
Cite where each fact comes from in brackets, e.g. [bank statement p.2, 06-04-2026], [ITR: net_profit], [P-FOIR], [C-TURNOVER].
If the data cannot answer the question, say so and suggest what document or check would. Be concise and numerate; use INR with Indian grouping.
You may run simple what-if arithmetic (e.g. EMI at a different amount/tenure) and show the formula."""


def ask(app, docs, analysis, memo, history, question):
    ctx = case_context(app, docs, analysis, include_txns=True)
    ctx["credit_memo"] = memo
    msgs = [{"role": "user", "content": f"CASE DATA (JSON):\n{json.dumps(ctx, default=str)}"},
            {"role": "assistant", "content": "Understood. I have the case data and will answer only from it."}]
    for h in history[-10:]:
        msgs.append({"role": h["role"], "content": h["content"]})
    msgs.append({"role": "user", "content": question})
    res = llm.chat(CHAT_SYSTEM, msgs, max_tokens=1500)
    return res
