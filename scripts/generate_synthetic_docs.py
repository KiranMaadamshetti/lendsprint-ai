"""
Generate SYNTHETIC borrower documents (bank statement, ITR, GST returns) as PDFs.

All names, account numbers, PAN/GSTIN values and figures are fictitious and exist
only to demo LendSprint. Nothing here is read by the app at runtime -- the app only
sees the PDFs, exactly as it would see a real upload.

Usage:  python scripts/generate_synthetic_docs.py   (writes to sample_docs/)
"""
import os
import random
from datetime import date, timedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

OUT = os.path.join(os.path.dirname(__file__), "..", "sample_docs")
MONTHS = [(2026, m) for m in range(3, 9)]  # Mar-Aug 2026
MONTH_NAMES = {3: "Mar", 4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug"}
STYLES = getSampleStyleSheet()
FOOTER = "SYNTHETIC DOCUMENT - generated for the LendSprint demo. Not a real person, business or bank record."


def inr(x: float) -> str:
    """Indian digit grouping: 1234567.5 -> 12,34,567.50"""
    neg = x < 0
    x = abs(x)
    whole, frac = f"{x:.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if neg else "") + whole + "." + frac


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica-Oblique", 7)
    canvas.setFillColor(colors.grey)
    canvas.drawString(15 * mm, 10 * mm, FOOTER)
    canvas.drawRightString(195 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


# --------------------------------------------------------------------------------------
# Borrower profiles (inputs to the *document generator* only)
# --------------------------------------------------------------------------------------
BORROWERS = [
    {
        "slug": "arvind_textiles",
        "name": "Arvind Textiles",
        "proprietor": "Arvind Kumar Ramasamy",
        "pan": "AKRPR4821K",
        "gstin": "33AKRPR4821K1Z7",
        "address": "14, Kumaran Road, Tiruppur, Tamil Nadu 641601",
        "bank": "Coastal Co-operative Bank",
        "acct": "50200071234581",
        "ifsc": "CCBK0000412",
        "opening": 1250000,
        "receipts": (1350000, 1650000), "n_receipts": 6,
        "customers": ["KNIT WORLD EXPORTS", "SARAVANA GARMENTS", "BLUE THREAD APPAREL", "VIJAY HOSIERY", "GLOBAL FABRIC HOUSE"],
        "cash_dep": (0, 60000),
        "emis": [("NACH DR HDFCX FINANCE LN8812", 45200)],
        "bounces": [],
        "loan_disbursal": None,
        "own_transfer_in": None,
        "supplier_ratio": 0.66,
        "salaries": 185000, "rent": 55000,
        "gst_ratio": 1.04,
        "itr": {"ay": "2026-27", "fy": "2025-26", "gross": 17850000, "np": 2215000, "other": 42000, "tax": 486000},
    },
    {
        "slug": "sri_lakshmi_traders",
        "name": "Sri Lakshmi Traders",
        "proprietor": "Lakshmi Narayana Bhat",
        "pan": "BLNPB7730M",
        "gstin": "29BLNPB7730M1ZQ",
        "address": "88, APMC Yard, Hubballi, Karnataka 580025",
        "bank": "Deccan Commercial Bank",
        "acct": "004611998230",
        "ifsc": "DCBL0000461",
        "opening": 640000,
        "receipts": (700000, 860000), "n_receipts": 6,
        "customers": ["SHREE BALAJI STORES", "MAHALAXMI KIRANA", "NAVODAYA SUPERMART", "RAYAR PROVISIONS", "SAI AGENCIES"],
        "cash_dep": (40000, 90000),
        "emis": [("NACH DR BAJAJ FIN LN44120", 30500)],
        "bounces": [(6, "NACH RTN INSUFF FUNDS BAJAJ FIN LN44120")],
        "loan_disbursal": None,
        "own_transfer_in": (5, "IMPS CR SELF A/C 00461177 LAKSHMI N BHAT", 250000),
        "supplier_ratio": 0.78,
        "salaries": 64000, "rent": 28000,
        "gst_ratio": 1.28,
        "itr": {"ay": "2026-27", "fy": "2025-26", "gross": 11480000, "np": 1105000, "other": 18000, "tax": 172000},
    },
    {
        "slug": "bluepeak_logistics",
        "name": "BluePeak Logistics",
        "proprietor": "Rohit Deshmukh",
        "pan": "CRDPD2215H",
        "gstin": "27CRDPD2215H1Z2",
        "address": "Plot 7, MIDC Transport Nagar, Nagpur, Maharashtra 440026",
        "bank": "Vidarbha Urban Bank",
        "acct": "112080045567",
        "ifsc": "VUBK0001120",
        "opening": 520000,
        "receipts": (520000, 680000), "n_receipts": 5,
        "customers": ["ORANGECITY AGRO", "METRO CEMENT DEPOT", "SAHYADRI STEELS", "WARDHA COTTON MILLS"],
        "cash_dep": (10000, 30000),
        "emis": [("NACH DR TATA CAP VEH LN7781", 52400), ("NACH DR ABC FINSERV BL0921", 33100)],
        "bounces": [(4, "NACH RTN INSUFF FUNDS TATA CAP VEH LN7781"), (5, "CHQ RTN 000451 FUNDS INSUFFICIENT"),
                    (7, "NACH RTN INSUFF FUNDS ABC FINSERV BL0921"), (8, "NACH RTN INSUFF FUNDS TATA CAP VEH LN7781")],
        "loan_disbursal": (6, "NEFT CR LOAN DISB QUICKCASH NBFC", 300000),
        "own_transfer_in": None,
        "supplier_ratio": 0.62,
        "salaries": 96000, "rent": 42000,
        "gst_ratio": 1.42,
        "itr": {"ay": "2026-27", "fy": "2025-26", "gross": 10790000, "np": 1420000, "other": 0, "tax": 238000},
    },
]


def build_transactions(b, rng):
    """Returns list of (date, narration, debit, credit) and per-month business receipts."""
    txns, monthly_receipts = [], {}
    for (y, m) in MONTHS:
        month_txns = []
        receipts_total = 0
        n = b["n_receipts"]
        target = rng.uniform(*b["receipts"])
        splits = [rng.uniform(0.6, 1.4) for _ in range(n)]
        s = sum(splits)
        for i, sp in enumerate(splits):
            amt = round(target * sp / s, -2)
            cust = rng.choice(b["customers"])
            mode = rng.choice(["NEFT CR", "RTGS CR", "IMPS CR", "UPI CR"])
            month_txns.append((date(y, m, min(3 + i * 5 + rng.randint(0, 2), 28)), f"{mode} {cust}", 0, amt))
            receipts_total += amt
        cash = round(rng.uniform(*b["cash_dep"]), -2)
        if cash:
            month_txns.append((date(y, m, rng.randint(10, 26)), "CASH DEPOSIT BRANCH", 0, cash))
            receipts_total += cash
        monthly_receipts[(y, m)] = receipts_total

        bounced = {nar for (mm_, nar) in b["bounces"] if mm_ == m}
        for (nar, emi) in b["emis"]:
            loan_id = nar.split()[-1]
            if any(loan_id in bn for bn in bounced):
                continue  # EMI not honoured this month
            month_txns.append((date(y, m, 5), nar, emi, 0))
        for bn in bounced:
            month_txns.append((date(y, m, 6), bn, 0, 0))
            month_txns.append((date(y, m, 6), "RTN CHGS " + bn.split()[0] + " RETURN CHARGES + GST", 590, 0))

        if b["loan_disbursal"] and b["loan_disbursal"][0] == m:
            month_txns.append((date(y, m, 12), b["loan_disbursal"][1], 0, b["loan_disbursal"][2]))
        if b["own_transfer_in"] and b["own_transfer_in"][0] == m:
            month_txns.append((date(y, m, 18), b["own_transfer_in"][1], 0, b["own_transfer_in"][2]))

        sup_total = receipts_total * b["supplier_ratio"]
        for i in range(3):
            amt = round(sup_total / 3 * rng.uniform(0.85, 1.15), -2)
            month_txns.append((date(y, m, 8 + i * 7), f"NEFT DR SUPPLIER {rng.choice(['PAY', 'INV'])}{rng.randint(1000, 9999)}", amt, 0))
        month_txns.append((date(y, m, 1), "SALARY BULK TRF STAFF", b["salaries"], 0))
        month_txns.append((date(y, m, 2), "IMPS DR SHOP RENT LANDLORD", b["rent"], 0))
        month_txns.append((date(y, m, 20), "GST PAYMENT CBIC CHALLAN", round(receipts_total * 0.035, -2), 0))
        month_txns.append((date(y, m, 24), "ATM CASH WDL", round(rng.uniform(15000, 40000), -3), 0))
        month_txns.sort(key=lambda t: t[0])
        txns.extend(month_txns)
    return txns, monthly_receipts


def bank_statement(b, txns, path):
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=18 * mm)
    el = [Paragraph(f"<b>{b['bank']}</b> - Statement of Account", STYLES["Title"]),
          Paragraph(f"Account Holder: <b>{b['name']}</b> (Prop. {b['proprietor']})<br/>"
                    f"Address: {b['address']}<br/>Account No: {b['acct']} &nbsp; IFSC: {b['ifsc']} &nbsp; Type: Current Account<br/>"
                    f"Statement Period: 01-Mar-2026 to 31-Aug-2026", STYLES["Normal"]),
          Spacer(1, 6 * mm)]
    bal = b["opening"]
    rows = [["Date", "Narration", "Debit (INR)", "Credit (INR)", "Balance (INR)"],
            ["01-03-2026", "OPENING BALANCE", "", "", inr(bal)]]
    for (d, nar, dr, cr) in txns:
        bal = bal - dr + cr
        rows.append([d.strftime("%d-%m-%Y"), nar, inr(dr) if dr else "", inr(cr) if cr else "", inr(bal)])
    t = Table(rows, colWidths=[22 * mm, 78 * mm, 26 * mm, 26 * mm, 28 * mm], repeatRows=1)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 7.5),
                           ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dde4ee")),
                           ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b8c2d0"))]))
    el += [t, Spacer(1, 4 * mm), Paragraph(f"Closing Balance as on 31-08-2026: INR {inr(bal)}", STYLES["Normal"])]
    doc.build(el, onFirstPage=footer, onLaterPages=footer)


def gst_returns(b, monthly_receipts, rng, path):
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=18 * mm)
    el = [Paragraph("GSTR-3B Summary of Returns Filed", STYLES["Title"]),
          Paragraph(f"GSTIN: <b>{b['gstin']}</b><br/>Legal Name: {b['proprietor']}<br/>Trade Name: {b['name']}<br/>"
                    f"Principal Place of Business: {b['address']}<br/>Return periods: March 2026 to August 2026", STYLES["Normal"]),
          Spacer(1, 6 * mm)]
    rows = [["Tax Period", "ARN", "Filing Date", "Taxable value of outward supplies (INR)", "IGST", "CGST", "SGST"]]
    for (y, m) in MONTHS:
        # receipts are tax-inclusive: invoice value (taxable + 6% tax here) = receipts x ratio
        tv = round(monthly_receipts[(y, m)] * b["gst_ratio"] / 1.06 * rng.uniform(0.97, 1.03), -2)
        igst = round(tv * 0.03, 2)
        cs = round(tv * 0.015, 2)
        fd = date(y, m, 28) + timedelta(days=rng.randint(19, 24))
        rows.append([f"{MONTH_NAMES[m]}-{y}", f"AA{b['gstin'][:2]}{m:02d}26{rng.randint(1000000, 9999999)}",
                     fd.strftime("%d-%m-%Y"), inr(tv), inr(igst), inr(cs), inr(cs)])
    rows[0][3] = Paragraph("<font size=7><b>Taxable value of outward supplies (INR)</b></font>", STYLES["Normal"])
    t = Table(rows, colWidths=[20 * mm, 36 * mm, 20 * mm, 40 * mm, 22 * mm, 20 * mm, 20 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 7.5),
                           ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6efe3")),
                           ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b8c2d0"))]))
    el += [t, Spacer(1, 5 * mm),
           Paragraph("Declaration: The taxpayer has self-declared the above values while filing GSTR-3B. "
                     "Figures are exclusive of tax.", STYLES["Italic"])]
    doc.build(el, onFirstPage=footer, onLaterPages=footer)


def itr(b, path):
    i = b["itr"]
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    gti = i["np"] + i["other"]
    ded = 150000
    el = [Paragraph("INDIAN INCOME TAX RETURN ACKNOWLEDGEMENT", STYLES["Title"]),
          Paragraph(f"Form: ITR-3 &nbsp;&nbsp; Assessment Year: {i['ay']} (Financial Year {i['fy']})", STYLES["Normal"]),
          Spacer(1, 4 * mm),
          Paragraph(f"Name: <b>{b['proprietor']}</b><br/>PAN: {b['pan']}<br/>Status: Individual (Proprietor of {b['name']})<br/>"
                    f"Address: {b['address']}", STYLES["Normal"]),
          Spacer(1, 6 * mm),
          Paragraph("<b>Computation of Total Income</b>", STYLES["Heading3"])]
    rows = [["Particulars", "Amount (INR)"],
            ["Gross receipts / turnover of business (Sch. BP)", inr(i["gross"])],
            ["Net profit from business or profession", inr(i["np"])],
            ["Income from other sources (interest)", inr(i["other"])],
            ["Gross Total Income", inr(gti)],
            ["Deductions under Chapter VI-A", inr(ded)],
            ["Total Income", inr(gti - ded)],
            ["Total tax, cess and interest paid", inr(i["tax"])]]
    t = Table(rows, colWidths=[110 * mm, 50 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                           ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#efe6dc")),
                           ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b8c2d0"))]))
    el += [t, Spacer(1, 6 * mm),
           Paragraph(f"Date of filing: 28-07-2026 &nbsp;&nbsp; Acknowledgement No: 7{random.Random(b['pan']).randint(10**13, 10**14 - 1)}",
                     STYLES["Normal"]),
           Paragraph("This return has been verified electronically.", STYLES["Italic"])]
    doc.build(el, onFirstPage=footer, onLaterPages=footer)


def main():
    os.makedirs(OUT, exist_ok=True)
    for b in BORROWERS:
        rng = random.Random(b["slug"])
        txns, monthly = build_transactions(b, rng)
        bank_statement(b, txns, os.path.join(OUT, f"{b['slug']}_bank_statement.pdf"))
        gst_returns(b, monthly, rng, os.path.join(OUT, f"{b['slug']}_gst_returns.pdf"))
        itr(b, os.path.join(OUT, f"{b['slug']}_itr.pdf"))
        print(f"{b['name']}: {len(txns)} transactions")


if __name__ == "__main__":
    main()
