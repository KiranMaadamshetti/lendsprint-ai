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
1. Click **+ New application**. Fill in the loan details, or prefill a synthetic case, then drop the borrower's PDFs into the same form and click **Create & analyse**.
2. The **Live analysis** screen opens. For each document you see it read, identified by AI, extracted page by page (transactions counted live), and verified against the PDF, with key figures appearing as they're found.
3. Once every document is in, the pipeline continues on its own: mandatory-document check, cross-document contradictions, credit policy, and Credit Brain reasoning. It finishes with the recommendation card.
4. **Blocked-decision demo:** create *Sri Lakshmi Traders* with only the bank statement and GST returns. The pipeline stops at "Mandatory documents", and the block is audited. Drop the ITR onto the live screen and the analysis resumes automatically.
5. Drill in with **AI extraction** (evidence, verified badges, AI-classified transactions), **Contradictions**, **Credit assessment**, and **Decision trace**.
6. **Ask Credit Brain**: "What loan amount keeps FOIR under 60%?"
7. Record the officer decision. An override without a justification is rejected. Then show the **Audit log**.

### Full MSME loan file (37 documents)
`sample_docs/msme_loan_file/` holds a complete synthetic loan file for **Sai Durga Precision Engineering** (applicant Kolluri Venkata Ramana,
co-applicant Kolluri Lalitha), which asks for a ₹35 lakh term loan to buy a CNC machine against their house. It contains: the application form, business profile,
Udyam, GST registration, shop licence (vintage), lease, utility bills, 2 ITRs, audited financials, GSTR-3B (12 months), GSTR-1,
current account + cash-credit account + 2 personal savings statements, 2 consumer CIBIL-style reports + commercial report,
PAN/Aadhaar images for both applicants (these go through AI OCR), sale deed, encumbrance certificate, a scanned tax receipt (OCR), approved plan,
valuation report, legal report, sales and purchase invoices, stock statement, debtor/creditor ageing, existing sanction letter and machine quotation.
In the New application form, choose *Sai Durga Precision Engineering* and drop the whole folder.
Red flags planted for the AI to find: an undisclosed co-applicant personal loan, the collateral already mortgaged to another bank,
one cheque return in the CC account, and a built-up area that deviates from the approved plan. Regenerate the file with `python scripts/generate_msme_loan_file.py`.

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
