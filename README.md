# LendSprint: AI Credit Underwriting Copilot

> BITSoM Vertex BFSI AI Buildathon, Day 1. **All borrowers and documents in this repo are synthetic.**

**Problem.** How can a lender make better credit decisions from complex or incomplete information?
An MSME credit officer at an Indian bank or NBFC spends 1 to 3 days per file reading bank statements, ITRs
and GST returns by hand. They re-key numbers into spreadsheets and try to spot mismatches between documents.
Decisions are slow and inconsistent, and they are hard to explain to a credit committee or an auditor.

**Solution.** LendSprint reads the borrower's documents with an LLM and cross-checks them. It applies
transparent credit policy and drafts an evidence-cited credit memo. A human officer makes the final call,
and every step is traced and audited.

## How the AI is used (and where it is not)

| Step | What happens | AI or deterministic |
|---|---|---|
| 1. Classify | Each uploaded PDF is identified as Bank Statement / ITR / GST Return, with a reason | **LLM** |
| 2. Extract | Fields such as turnover, net profit, PAN and GSTIN are extracted with a verbatim evidence quote, page and confidence. Every bank transaction is transcribed and **classified by meaning** (business receipt, EMI, bounce, loan disbursal, own-account transfer...) | **LLM** |
| 3. Verify | Evidence quotes are checked verbatim against the PDF text. Every extracted transaction is **reconciled against the running balance** to catch extraction errors | Deterministic |
| 4. Cross-check | GST turnover vs bank credits, ITR turnover vs annualised bank credits, PAN inside GSTIN vs ITR PAN, declared vs observed EMIs, fresh loan disbursals | Deterministic, on AI-extracted data |
| 5. Policy | FOIR, cash-flow DSCR, bounces, ABB/EMI, loan-to-turnover, data integrity, with configurable thresholds | Deterministic |
| 6. Reason | Credit memo: recommendation, risk grade, strengths/risks **citing evidence ids**, conditions, borrower questions, "what would change the decision" | **LLM** |
| 7. Guardrail | The AI can never auto-approve a case with a failed hard rule or a critical contradiction. Such cases are capped at *Refer*. Cited evidence ids are checked to be real | Deterministic |
| 8. Ask | "Ask Credit Brain" chat, grounded only in this applicant's extracted data, with citations and what-if maths | **LLM** |
| 9. Decide | The officer records the decision. Overriding the system needs a written justification. Everything goes to the audit log | Human |

No borrower-specific logic or canned outputs exist. The same prompts run on any uploaded PDF, and every number
on screen comes from the documents. Missing mandatory documents **block** the decision, and the blocked attempt is audited.

## Run it

Requires Python 3.10+.

```bash
pip install -r requirements.txt
cp .env.example .env        # then paste your API key into .env
python -m uvicorn backend.main:app --port 8000
# open http://localhost:8000
```

On Windows you can double-click `run.bat` instead.

The LLM provider is chosen from whichever key is set: `GEMINI_API_KEY`, `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.
You can override it with `LLM_PROVIDER` and `LLM_MODEL`.

### Demo flow (7 minutes)
1. **+ New application**, then prefill *Sri Lakshmi Traders (synthetic)*, then Create.
2. Upload only the bank statement and GST returns, then click **Run Credit Brain assessment**. The decision is **blocked** because the ITR is missing, and the attempt is audited.
3. Upload the ITR. Credit Brain classifies and extracts it live.
4. **AI extraction** tab: evidence quotes, "verified in PDF" badges, transactions classified by AI, and the reconciliation check.
5. Run the assessment. Show **Contradictions** (GST vs bank +28%), the **Credit assessment** and the **Decision trace**.
6. **Ask Credit Brain**: "What loan amount keeps FOIR under 60%?"
7. Record an officer decision. An override without a justification is rejected. Then show the **Audit log**.
8. Contrast with *Arvind Textiles* (clean case) and *BluePeak Logistics* (critical contradictions, bounces and a fresh NBFC loan).

### Synthetic data
`scripts/generate_synthetic_docs.py` generates the PDFs in `sample_docs/`: 3 fictitious borrowers, each with a
6-month bank statement, GSTR-3B summary and ITR. The generator is only used to create the test documents. The app never
reads it and only sees the PDFs.

### Tests
```bash
python -m pytest -q
```
The tests run offline. The LLM is replaced by a test-only stub, so the verification, cross-checks, policy, gate and API flow
can be tested without network access.

## Assumptions
- The target user is an MSME credit officer. The documents are text-based PDFs (no scanned images yet).
- Bank "business credits" = customer receipts + cash deposits. Loan disbursals, own-account transfers and reversals are excluded.
- The GST vs bank comparison uses taxable value for the same months. The ITR comparison annualises bank credits (the periods differ, so moderate variance is expected).
- Monthly income for FOIR = ITR net profit / 12. The existing EMI = max(declared, observed in the bank statement).
- The policy thresholds in `backend/analysis.py` (`POLICY`) are illustrative and meant to be tuned by a credit-risk team.

## What we'd build next
OCR and vision for scanned statements. Account Aggregator, bureau and GST API pulls instead of PDFs. A calibrated PD model trained on the lender's
outcome data. Policy versioning and replay. A credit-committee workflow with maker-checker. A portfolio-level data-integrity dashboard.

## Structure
```
backend/   FastAPI app: llm.py (provider-agnostic client), pdftext.py, extraction.py (AI + verification),
           analysis.py (metrics, contradictions, policy), brain.py (credit memo, gate, chat), db.py (SQLite + audit)
frontend/  Single-page UI (vanilla JS, no build step)
scripts/   Synthetic document generator
sample_docs/  Synthetic PDFs for 3 borrowers
tests/     Offline pipeline tests
docs/      One-slide pitch (LendSprint_pitch_slide.pptx)
```
