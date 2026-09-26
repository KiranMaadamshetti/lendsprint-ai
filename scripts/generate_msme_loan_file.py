"""
Generate a complete SYNTHETIC MSME loan file (36 documents) for one borrower + co-applicant.

Every person, business, bank, identifier and number here is fictitious. All pages carry a
"SYNTHETIC - DEMO ONLY" watermark. The figures are internally consistent across documents
(bank <-> GST <-> ITR <-> financials <-> bureau) with a few deliberate red flags an underwriter
should catch:
  * co-applicant has an undisclosed personal loan (bureau + her bank statement, not in the form)
  * the collateral property is already mortgaged to another bank (EC + legal report)
  * one inward cheque return in the cash-credit account
  * valuation report built-up area differs from the approved plan

Usage:  python scripts/generate_msme_loan_file.py   -> sample_docs/msme_loan_file/
"""
import os
import random
from datetime import date, timedelta

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image as RLImage, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

OUT = os.path.join(os.path.dirname(__file__), "..", "sample_docs", "msme_loan_file")
ST = getSampleStyleSheet()
SMALL = ParagraphStyle("small", parent=ST["Normal"], fontSize=8.5, leading=11)
BODY = ParagraphStyle("body", parent=ST["Normal"], fontSize=9.5, leading=13)
H = ST["Heading3"]
FOOT = "SYNTHETIC DOCUMENT - LendSprint demo. All names, numbers and institutions are fictitious."
R = random.Random(20260926)

# ---------------------------------------------------------------- the case
A = dict(name="Kolluri Venkata Ramana", father="Kolluri Satyanarayana", dob="14-06-1980", pan="AKVPK6612R",
         aadhaar="XXXX XXXX 4821", mobile="98XXXX4417", email="kvramana.synthetic@example.com")
C = dict(name="Kolluri Lalitha", father="Pydi Raju Gollapudi", dob="02-11-1985", pan="BKLPK3390N",
         aadhaar="XXXX XXXX 7306", mobile="97XXXX2250", relation="Spouse")
BIZ = dict(name="Sai Durga Precision Engineering", const="Proprietorship", gstin="36AKVPK6612R1Z4",
           udyam="UDYAM-TS-20-0047815", since="12-04-2016", nic="29301 - Manufacture of parts and accessories for motor vehicles",
           addr="Plot No. 41, IDA Balanagar, Hyderabad, Telangana 500037", employees=24)
RES = "H.No. 8-3-167/12, Kalyan Nagar Phase-III, Kukatpally, Hyderabad, Telangana 500072"
LOAN = dict(amount=3500000, tenure=60, rate=12.25, purpose="Purchase of CNC Vertical Machining Centre (VMC 850)")
CUSTOMERS = ["AXLETECH COMPONENTS PVT LTD", "NOVA AUTO PARTS LTD", "SRI VENKATESWARA FORGINGS", "BHARAT GEAR SYSTEMS PVT LTD"]
SUPPLIERS = ["SRI SAI STEELS", "HYD TOOLING SOLUTIONS", "DECCAN ALLOYS AND METALS", "PRAGATHI CUTTING TOOLS"]
MONTHS = [(2026, m) for m in range(3, 9)]
GST_MONTHS = [(2025, m) for m in range(9, 13)] + [(2026, m) for m in range(1, 9)]
MN = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def inr(x):
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


_WM = None


def _watermark_png():
    """Watermark drawn as an image (not text) so it never pollutes the PDF's text layer."""
    global _WM
    if _WM is None:
        img = Image.new("RGBA", (1400, 1400), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((80, 640), "SYNTHETIC - DEMO ONLY", font=font(118, True), fill=(210, 50, 50, 26))
        _WM = os.path.join(OUT, "_wm.png")
        img.rotate(35).save(_WM)
    return _WM


def _decor(canvas, doc):
    canvas.saveState()
    canvas.drawImage(_watermark_png(), 15 * mm, 60 * mm, width=180 * mm, height=180 * mm, mask="auto")
    canvas.restoreState()
    canvas.saveState()
    canvas.setFont("Helvetica-Oblique", 7)
    canvas.setFillColor(colors.grey)
    canvas.drawString(15 * mm, 9 * mm, FOOT)
    canvas.drawRightString(195 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def pdf(fname, story):
    path = os.path.join(OUT, fname)
    SimpleDocTemplate(path, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=15 * mm,
                      bottomMargin=16 * mm).build(story, onFirstPage=_decor, onLaterPages=_decor)
    return path


def title(t, sub=None):
    out = [Paragraph(t, ST["Title"])]
    if sub:
        out.append(Paragraph(sub, BODY))
    out.append(Spacer(1, 4 * mm))
    return out


def kv(rows, widths=(62 * mm, 116 * mm)):
    t = Table([[Paragraph(f"<b>{k}</b>", SMALL), Paragraph(str(v), SMALL)] for k, v in rows], colWidths=widths)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b8c2d0")),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f4f8")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return [t, Spacer(1, 3 * mm)]


def grid(rows, widths, num_from=None, head="#dde4ee", fs=7.8):
    cell = ParagraphStyle("cell", parent=ST["Normal"], fontSize=fs, leading=fs + 2)
    cell_r = ParagraphStyle("cellr", parent=cell, alignment=2)
    wrapped = []
    for ri, row in enumerate(rows):
        out = []
        for ci, v in enumerate(row):
            if isinstance(v, str) and ri > 0 and len(v) > 14:
                out.append(Paragraph(v, cell_r if num_from is not None and ci >= num_from else cell))
            else:
                out.append(v)
        wrapped.append(out)
    rows = wrapped
    t = Table(rows, colWidths=widths, repeatRows=1)
    style = [("FONT", (0, 0), (-1, -1), "Helvetica", fs), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", fs),
             ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(head)), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b8c2d0")),
             ("VALIGN", (0, 0), (-1, -1), "TOP")]
    if num_from is not None:
        style.append(("ALIGN", (num_from, 1), (-1, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return [t, Spacer(1, 3 * mm)]


def p(text, style=BODY):
    return Paragraph(text, style)


# ---------------------------------------------------------------- bank statements
def statement(fname, bank, holder, acct, ifsc, acc_type, opening, month_fn, extra_head=""):
    txns = []
    for (y, m) in MONTHS:
        txns += sorted(month_fn(y, m), key=lambda t: t[0])
    bal = opening
    rows = [["Date", "Narration", "Chq/Ref", "Debit", "Credit", "Balance"], ["01-03-2026", "OPENING BALANCE", "", "", "", inr(bal)]]
    for (d, nar, dr, cr) in txns:
        bal = round(bal - dr + cr, 2)
        rows.append([d.strftime("%d-%m-%Y"), nar, f"{R.randint(100000, 999999)}", inr(dr) if dr else "", inr(cr) if cr else "", inr(bal)])
    story = title(f"{bank}", "Statement of Account")
    story += kv([("Account holder", holder), ("Account number", acct), ("Account type", acc_type), ("IFSC", ifsc),
                 ("Statement period", "01-03-2026 to 31-08-2026")] + ([("Facility", extra_head)] if extra_head else []))
    story += grid(rows, [20 * mm, 70 * mm, 17 * mm, 23 * mm, 23 * mm, 25 * mm], num_from=3, fs=7.2)
    story.append(p(f"Closing balance as on 31-08-2026: INR {inr(bal)}"))
    pdf(fname, story)


def spread(total, n):
    w = [R.uniform(0.7, 1.3) for _ in range(n)]
    s = sum(w)
    return [round(total * x / s, -2) for x in w]


MONTHLY_CA = {m: R.uniform(1480000, 1620000) for m in range(3, 9)}
MONTHLY_CC = {m: R.uniform(560000, 620000) for m in range(3, 9)}


def ca_month(y, m):
    t = []
    for i, amt in enumerate(spread(MONTHLY_CA[m], 6)):
        t.append((date(y, m, 3 + i * 4), f"{R.choice(['NEFT CR', 'RTGS CR'])} {CUSTOMERS[i % 4]}", 0, amt))
    sup = MONTHLY_CA[m] * 0.52
    for i, amt in enumerate(spread(sup, 4)):
        t.append((date(y, m, 6 + i * 5), f"NEFT DR {SUPPLIERS[i]}", amt, 0))
    t += [(date(y, m, 1), "SALARY BULK UPLOAD STAFF (24)", 290000, 0),
          (date(y, m, 5), "IMPS DR LEASE RENT FACTORY SHED P41", 65000, 0),
          (date(y, m, 14), "BILLDESK DR ELECTRICITY SC NO 41-IDA", R.randint(44000, 52000), 0),
          (date(y, m, 20), "GST CHALLAN CPIN 36" + str(R.randint(10**9, 10**10)), R.randint(42000, 58000), 0),
          (date(y, m, 25), "TRF TO CC A/C 0417 SAI DURGA PRECISION", 150000, 0),
          (date(y, m, 27), "IMPS DR SELF K V RAMANA SB 5541", 120000, 0),
          (date(y, m, 28), "ATM CASH WDL", R.choice([20000, 25000, 30000]), 0)]
    return t


def cc_month(y, m):
    t = []
    for i, amt in enumerate(spread(MONTHLY_CC[m], 3)):
        t.append((date(y, m, 4 + i * 8), f"NEFT CR {CUSTOMERS[(i + 1) % 4]}", 0, amt))
    t += [(date(y, m, 26), "TRF FROM CA 5002 SAI DURGA PRECISION", 0, 150000),
          (date(y, m, 5), "TERM LOAN EMI RECOVERY TL/0921/20L", 34850, 0),
          (date(y, m, 30 if m != 2 else 28), "INTEREST ON CC LIMIT", R.randint(19000, 23500), 0)]
    for i, amt in enumerate(spread(MONTHLY_CC[m] * 1.05, 2)):
        t.append((date(y, m, 9 + i * 9), f"CHQ PAID {SUPPLIERS[(i + 2) % 4]}", amt, 0))
    if m == 6:
        t += [(date(y, m, 18), "INWARD CHQ RTN 004512 FUNDS INSUFFICIENT - SRI SAI STEELS", 0, 0),
              (date(y, m, 18), "CHQ RETURN CHARGES + GST", 590, 0)]
    return t


def sb_app(y, m):
    return [(date(y, m, 28), "IMPS CR SAI DURGA PRECISION ENGG", 0, 120000),
            (date(y, m, 7), "NACH DR METRO AUTO FINANCE CAR LN MA88213", 17250, 0),
            (date(y, m, 10), "SIP DR MUTUAL FUND FOLIO 7741", 10000, 0),
            (date(y, m, 12), "UPI DR SCHOOL FEES", 18500 if m in (4, 6) else 0, 0),
            (date(y, m, 15), "UPI DR GROCERY / HOUSEHOLD", R.randint(22000, 30000), 0),
            (date(y, m, 18), "IMPS DR K LALITHA SB 1180", 40000, 0),
            (date(y, m, 22), "LIC PREMIUM POLICY 5519", 6200 if m in (3, 9) else 0, 0),
            (date(y, m, 30 if m != 2 else 28), "SB INTEREST", 0, R.randint(300, 700))]


def sb_co(y, m):
    return [(date(y, m, 18), "IMPS CR K V RAMANA", 0, 40000),
            (date(y, m, 3), "NEFT CR TUITION CLASSES FEES", 0, R.randint(9000, 14000)),
            (date(y, m, 7), "NACH DR QUICKFIN NBFC PL/2291/26", 14800, 0),
            (date(y, m, 16), "UPI DR SHOPPING", R.randint(6000, 12000), 0),
            (date(y, m, 24), "UPI DR MEDICAL", R.randint(1500, 5000), 0)]


def clean(fn):
    return lambda y, m: [t for t in fn(y, m) if t[2] or t[3] or "RTN" in t[1]]


# ---------------------------------------------------------------- KYC images
def font(size, bold=False):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def id_card(fname, heading, lines, color):
    img = Image.new("RGB", (1000, 620), (248, 247, 242))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1000, 110], fill=color)
    d.text((40, 30), heading, font=font(38, True), fill="white")
    d.rectangle([40, 150, 250, 400], outline=(120, 120, 120), width=3)
    d.text((80, 260), "PHOTO", font=font(28), fill=(150, 150, 150))
    y = 150
    for k, v in lines:
        d.text((290, y), k, font=font(22), fill=(90, 90, 90))
        d.text((290, y + 28), v, font=font(30, True), fill=(20, 20, 20))
        y += 78
    d.text((40, 560), "SYNTHETIC SPECIMEN - NOT A GOVERNMENT DOCUMENT - LENDSPRINT DEMO", font=font(22, True), fill=(200, 40, 40))
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    od.text((170, 250), "SYNTHETIC", font=font(120, True), fill=(220, 50, 50, 55))
    img = Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")
    img.save(os.path.join(OUT, fname), quality=88)


def scanned_pdf(fname, lines_fn):
    """A text-less, image-only PDF (simulates a scanned receipt) to exercise AI OCR."""
    img = Image.new("RGB", (1240, 1754), (250, 249, 244))
    d = ImageDraw.Draw(img)
    lines_fn(d)
    img = img.rotate(0.6, fillcolor=(250, 249, 244))
    tmp = os.path.join(OUT, "_scan.png")
    img.save(tmp)
    story = [RLImage(tmp, width=178 * mm, height=252 * mm)]
    SimpleDocTemplate(os.path.join(OUT, fname), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                      topMargin=12 * mm, bottomMargin=12 * mm).build(story)
    os.remove(tmp)


# ---------------------------------------------------------------- documents
def build():
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        os.remove(os.path.join(OUT, f))
    global _WM
    _WM = None
    emi_new = LOAN["amount"] * (LOAN["rate"] / 1200) * (1 + LOAN["rate"] / 1200) ** 60 / ((1 + LOAN["rate"] / 1200) ** 60 - 1)

    # 01 application form
    s = title("MSME Term Loan - Application Form", f"Application No. MSME/HYD/2026/00871 &nbsp; Date: 22-09-2026 &nbsp; Branch: Balanagar, Hyderabad")
    s += [p("<b>A. Loan requested</b>")] + kv([("Facility", "Term Loan (MSME) - secured"), ("Amount requested", f"INR {inr(LOAN['amount'])}"),
                                               ("Tenure", f"{LOAN['tenure']} months"), ("Indicative rate", f"{LOAN['rate']}% p.a. (floating)"),
                                               ("Purpose", LOAN["purpose"]), ("Promoter margin", "INR 3,94,000 (own funds)"),
                                               ("Collateral offered", f"Residential house at {RES} (jointly owned)")])
    s += [p("<b>B. Business details</b>")] + kv([("Name of enterprise", BIZ["name"]), ("Constitution", BIZ["const"]), ("GSTIN", BIZ["gstin"]),
                                                 ("Udyam registration", BIZ["udyam"]), ("Date of commencement", BIZ["since"]),
                                                 ("Activity", BIZ["nic"]), ("Business address", BIZ["addr"]), ("Premises", "Leased factory shed"),
                                                 ("Employees", BIZ["employees"]), ("Turnover FY 2025-26", "INR 2,46,30,000")])
    s += [p("<b>C. Applicant</b>")] + kv([("Name", A["name"]), ("Father's name", A["father"]), ("Date of birth", A["dob"]), ("PAN", A["pan"]),
                                         ("Aadhaar", A["aadhaar"]), ("Mobile", A["mobile"]), ("Residence", RES), ("Residence type", "Owned")])
    s += [p("<b>D. Co-applicant</b>")] + kv([("Name", C["name"]), ("Relationship", C["relation"]), ("Date of birth", C["dob"]),
                                            ("PAN", C["pan"]), ("Aadhaar", C["aadhaar"]), ("Occupation", "Home tutor (self-employed)")])
    s += [p("<b>E. Existing loans / obligations (declared)</b>")]
    s += grid([["Borrower", "Lender", "Facility", "Sanctioned", "Outstanding", "EMI / month"],
               ["Business", "Coastal Co-operative Bank", "Term loan (2021, 84m)", "20,00,000.00", "9,62,400.00", "34,850.00"],
               ["Business", "Coastal Co-operative Bank", "Cash credit (limit)", "25,00,000.00", "21,40,000.00", "Interest only"],
               ["Applicant", "Metro Auto Finance", "Car loan (2023)", "8,50,000.00", "4,12,000.00", "17,250.00"],
               ["Co-applicant", "Sri Lakshmi Gold Loans", "Gold loan (bullet)", "2,40,000.00", "2,40,000.00", "Nil (bullet)"],
               ["", "", "", "", "Total EMI", "52,100.00"]], [24 * mm, 42 * mm, 36 * mm, 26 * mm, 26 * mm, 24 * mm], num_from=3)
    s += [p("<b>F. Declaration</b>"), p("We declare that the particulars given above are true and complete, that we have no other borrowings, "
                                         "and that the property offered as security is free from all encumbrances.", SMALL),
          Spacer(1, 8 * mm), p("Signature of Applicant: ______________ &nbsp;&nbsp;&nbsp; Signature of Co-applicant: ______________")]
    pdf("01_Loan_Application_Form.pdf", s)

    # 02 business profile
    s = title("Business Profile", BIZ["name"])
    s += [p(f"{BIZ['name']} is a proprietorship concern of {A['name']}, engaged in precision machining of automotive components "
            "(gear blanks, axle flanges, hub bores) for Tier-1 and Tier-2 auto suppliers in Hyderabad and Chennai. "
            f"The unit commenced operations on {BIZ['since']} with two conventional lathes and today runs 3 CNC turning centres, "
            "1 VMC, 6 conventional machines and an inspection room with CMM. It employs 24 people in two shifts."), Spacer(1, 3 * mm)]
    s += kv([("Promoter experience", "22 years (14 years as production supervisor at an auto-components company before starting the unit)"),
             ("Key customers", ", ".join(CUSTOMERS)), ("Key suppliers", ", ".join(SUPPLIERS)),
             ("Installed capacity utilisation", "about 82% (two shifts)"),
             ("Reason for loan", "New VMC 850 to execute a confirmed schedule from AXLETECH COMPONENTS for flange machining (approx. INR 18 lakh/month additional billing from Q1 FY27)"),
             ("Turnover history", "FY 2023-24: 1.71 Cr | FY 2024-25: 2.09 Cr | FY 2025-26: 2.46 Cr")])
    pdf("02_Business_Profile.pdf", s)

    # 03 Udyam
    s = title("UDYAM REGISTRATION CERTIFICATE", "Ministry-format certificate (synthetic reproduction for demo)")
    s += kv([("Udyam Registration Number", BIZ["udyam"]), ("Type of enterprise", "MICRO (2025-26)"), ("Major activity", "Manufacturing"),
             ("Name of enterprise", BIZ["name"].upper()), ("Social category", "General"), ("Name of owner", A["name"].upper()),
             ("PAN", A["pan"]), ("Official address", BIZ["addr"]), ("Date of incorporation / commencement", BIZ["since"]),
             ("Date of Udyam registration", "18-08-2020"), ("NIC code", BIZ["nic"])])
    pdf("03_Udyam_MSME_Registration_Certificate.pdf", s)

    # 04 GST REG-06
    s = title("FORM GST REG-06 - Registration Certificate")
    s += kv([("Registration Number (GSTIN)", BIZ["gstin"]), ("Legal name", A["name"].upper()), ("Trade name", BIZ["name"].upper()),
             ("Constitution of business", "Proprietorship"), ("Address of principal place of business", BIZ["addr"]),
             ("Date of liability", "01-07-2017"), ("Period of validity", "From 01-07-2017 to Not applicable"),
             ("Type of registration", "Regular"), ("Approving authority", "Jurisdictional GST officer (synthetic)")])
    pdf("04_GST_Registration_Certificate.pdf", s)

    # 05 Shop & establishment
    s = title("Registration Certificate of Establishment", "Shops & Establishments Act - Form C (synthetic)")
    s += kv([("Registration No.", "SEA/HYD/BLN/2016/118842"), ("Name of establishment", BIZ["name"]), ("Name of employer", A["name"]),
             ("Nature of business", "Engineering workshop - machining of components"), ("Address", BIZ["addr"]),
             ("Date of commencement", BIZ["since"]), ("Date of registration", "25-04-2016"), ("Valid up to", "31-12-2030"),
             ("Number of employees at registration", "4")])
    pdf("05_Shop_Establishment_Licence_Vintage_Proof.pdf", s)

    # 06 Lease agreement
    s = title("Lease Deed - Industrial Shed", "Executed on 01-04-2024 at Hyderabad (renewal of lease dated 01-04-2016)")
    s += [p(f"This lease deed is made between <b>Smt. B. Anuradha</b> (Lessor) and <b>{A['name']}</b>, proprietor of {BIZ['name']} (Lessee). "
            f"The Lessor lets the industrial shed of 4,200 sq ft at {BIZ['addr']} for a period of 60 months from 01-04-2024 "
            "at a monthly rent of INR 65,000 (Rupees Sixty Five Thousand only) payable on or before the 5th of every month, "
            "with 5% escalation every 24 months. Security deposit: INR 3,90,000. The premises have been in the Lessee's continuous "
            "occupation since 01-04-2016 under the earlier lease."), Spacer(1, 10 * mm),
          p("Lessor: ______________ &nbsp;&nbsp; Lessee: ______________ &nbsp;&nbsp; Witnesses: 1. ________ 2. ________")]
    pdf("06_Factory_Lease_Agreement.pdf", s)

    # 07 electricity business
    s = title("Electricity Bill - LT Industrial (Category III)", "Distribution company (synthetic)")
    s += kv([("Service connection no.", "41-IDA-BLN-00917"), ("Consumer name", BIZ["name"]), ("Address", BIZ["addr"]),
             ("Bill month", "August 2026"), ("Connected load", "75 HP"), ("Units consumed", "5,640 kWh"),
             ("Energy charges", "44,556.00"), ("Fixed charges + duty", "4,150.00"), ("Total amount due", "48,706.00"),
             ("Due date", "14-09-2026"), ("Last payment", "INR 47,920.00 on 14-08-2026")])
    pdf("07_Electricity_Bill_Business_Premises.pdf", s)

    # 08-09 ITR
    for fname, ay, fy, gross, np_, tax, filed in [("08_ITR_AY_2026-27.pdf", "2026-27", "2025-26", 24630000, 2962000, 612400, "24-07-2026"),
                                                  ("09_ITR_AY_2025-26.pdf", "2025-26", "2024-25", 20870000, 2386000, 448300, "29-07-2025")]:
        s = title("INDIAN INCOME TAX RETURN ACKNOWLEDGEMENT", f"Form ITR-3 &nbsp; Assessment Year {ay} (Financial Year {fy})")
        s += kv([("Name", A["name"]), ("PAN", A["pan"]), ("Status", f"Individual (Proprietor of {BIZ['name']})"), ("Address", RES)])
        s += grid([["Particulars", "Amount (INR)"], ["Gross receipts / turnover of business (Sch. BP)", inr(gross)],
                   ["Net profit from business or profession", inr(np_)], ["Income from other sources (interest)", inr(8400)],
                   ["Gross Total Income", inr(np_ + 8400)], ["Deductions under Chapter VI-A", inr(150000)],
                   ["Total Income", inr(np_ + 8400 - 150000)], ["Total tax, cess and interest paid", inr(tax)]],
                  [120 * mm, 58 * mm], num_from=1)
        s += [p(f"Date of filing: {filed} &nbsp; Acknowledgement No: 7{R.randint(10**13, 10**14 - 1)} &nbsp; Verified electronically.")]
        pdf(fname, s)

    # 10 audited financials
    s = title("Audited Financial Statements - FY 2025-26", f"{BIZ['name']} (Prop. {A['name']}) &nbsp; Tax audit u/s 44AB by a Chartered Accountant firm (synthetic)")
    s += [p("<b>Profit and Loss Account for the year ended 31-03-2026</b>")]
    s += grid([["Particulars", "FY 2025-26 (INR)", "FY 2024-25 (INR)"],
               ["Revenue from operations (net of GST)", inr(24630000), inr(20870000)], ["Other income", inr(8400), inr(6100)],
               ["Cost of materials consumed", inr(14285000), inr(12272000)], ["Employee costs", inr(3420000), inr(2980000)],
               ["Power and fuel", inr(566000), inr(498000)], ["Rent", inr(780000), inr(744000)],
               ["Finance costs", inr(398000), inr(421000)], ["Depreciation", inr(612000), inr(548000)],
               ["Other expenses", inr(1595400), inr(1027000)], ["Net profit", inr(2962000), inr(2386000)]],
              [90 * mm, 44 * mm, 44 * mm], num_from=1)
    s += [p("<b>Balance Sheet as at 31-03-2026</b>")]
    s += grid([["Liabilities", "INR", "Assets", "INR"],
               ["Proprietor's capital", inr(7845000), "Plant & machinery (net)", inr(6420000)],
               ["Term loan - Coastal Co-op Bank", inr(1124000), "Inventories", inr(3150000)],
               ["Cash credit - Coastal Co-op Bank", inr(2140000), "Trade receivables", inr(3820000)],
               ["Trade payables", inr(1960000), "Cash & bank balances", inr(612000)],
               ["Other current liabilities", inr(1323000), "Security deposit (lease) & others", inr(390000)],
               ["Total", inr(14392000), "Total", inr(14392000)]], [58 * mm, 31 * mm, 58 * mm, 31 * mm], num_from=1)
    s += [p("Key ratios: Net profit margin 12.0% | Current ratio 1.84 | Debt / Equity 0.42 | Debtor days 57 | Inventory days 80.", SMALL)]
    pdf("10_Audited_Financials_FY2025-26.pdf", s)

    # 11 GSTR-3B 12 months
    s = title("GSTR-3B - Summary of Returns Filed (12 months)", f"GSTIN {BIZ['gstin']} &nbsp; Trade name: {BIZ['name']}")
    rows = [["Tax period", "ARN", "Filed on", "Taxable value of outward supplies", "IGST", "CGST", "SGST", "ITC availed"]]
    for (y, m) in GST_MONTHS:
        if (y, m) in MONTHS:
            tv = round((MONTHLY_CA[m] + MONTHLY_CC[m]) / 1.18 * R.uniform(1.00, 1.04), -2)
        else:
            tv = round(R.uniform(1720000, 1880000), -2)
        cs = round(tv * 0.09 * 0.55, 2)
        ig = round(tv * 0.18 * 0.45, 2)
        fd = date(y + (m == 12), m % 12 + 1, R.randint(17, 20))
        rows.append([f"{MN[m]}-{y}", f"AA36{m:02d}{str(y)[2:]}{R.randint(1000000, 9999999)}", fd.strftime("%d-%m-%Y"), inr(tv), inr(ig), inr(cs), inr(cs), inr(round(tv * 0.13, 2))])
    rows[0][3] = Paragraph("<font size=7><b>Taxable value of outward supplies</b></font>", SMALL)
    s += grid(rows, [17 * mm, 32 * mm, 18 * mm, 30 * mm, 21 * mm, 20 * mm, 20 * mm, 21 * mm], num_from=3, head="#e6efe3", fs=7)
    s += [p("All 12 returns filed within due date +/- 2 days. Figures exclude tax.", SMALL)]
    pdf("11_GSTR-3B_Returns_12_Months.pdf", s)

    # 12 GSTR-1 customer summary
    s = title("GSTR-1 - B2B Outward Supplies, Recipient-wise Summary", f"GSTIN {BIZ['gstin']} &nbsp; Period: April 2026 to August 2026")
    ytd = sum(round((MONTHLY_CA[m] + MONTHLY_CC[m]) / 1.18, -2) for m in range(4, 9))
    shares = [0.38, 0.27, 0.21, 0.14]
    s += grid([["Recipient", "GSTIN of recipient", "No. of invoices", "Taxable value (INR)"]] +
              [[c, f"36AAC{c[:1]}X{R.randint(1000, 9999)}Q1Z{R.randint(1, 9)}", str(R.randint(18, 44)), inr(round(ytd * sh, -2))] for c, sh in zip(CUSTOMERS, shares)] +
              [["Total", "", "", inr(sum(round(ytd * sh, -2) for sh in shares))]], [64 * mm, 50 * mm, 26 * mm, 38 * mm], num_from=2)
    s += [p("Top customer concentration: AXLETECH COMPONENTS PVT LTD 38% of B2B supplies.", SMALL)]
    pdf("12_GSTR-1_Customer_Summary.pdf", s)

    # 13-16 bank statements
    statement("13_Current_Account_Statement_Deccan_Commercial_Bank.pdf", "Deccan Commercial Bank", f"{BIZ['name']} (Prop. {A['name']})",
              "5002 0419 8871", "DCBL0000211", "Current Account", 845000, clean(ca_month))
    statement("14_Cash_Credit_Account_Statement_Coastal_Coop_Bank.pdf", "Coastal Co-operative Bank", f"{BIZ['name']} (Prop. {A['name']})",
              "0417 1200 3356", "CCBK0000417", "Cash Credit Account (Overdraft)", -2084000, clean(cc_month),
              "Cash credit limit INR 25,00,000 against hypothecation of stock and book debts")
    statement("15_Savings_Account_Statement_Applicant.pdf", "Deccan Commercial Bank", A["name"], "5541 0077 2190", "DCBL0000211",
              "Savings Account (personal)", 186000, clean(sb_app))
    statement("16_Savings_Account_Statement_Co-applicant.pdf", "Andhra Urban Co-operative Bank", C["name"], "1180 4402 6617", "AUCB0000118",
              "Savings Account (personal)", 64000, clean(sb_co))

    # 17-19 bureau reports
    def bureau(fname, who, pan, dob, score, accounts, enquiries, dpd_note):
        s = title("Consumer Credit Information Report", "Bureau-format report (synthetic) &nbsp; Report date: 20-09-2026 &nbsp; Control No. " + str(R.randint(10**9, 10**10)))
        s += kv([("Name", who), ("PAN", pan), ("Date of birth", dob), ("Credit score", f"<b>{score}</b> (range 300-900)"),
                 ("Active accounts", str(sum(1 for a in accounts if a[5] != "Closed"))), ("Enquiries in last 6 months", str(enquiries)),
                 ("Written-off / settled accounts", "0")])
        s += grid([["Lender", "Account type", "Opened", "Sanctioned", "Current balance", "Status", "EMI", "DPD last 12m"]] + accounts,
                  [34 * mm, 26 * mm, 17 * mm, 21 * mm, 23 * mm, 15 * mm, 18 * mm, 24 * mm], num_from=3, fs=7)
        s += [p(dpd_note, SMALL)]
        pdf(fname, s)

    bureau("17_CIBIL_Report_Applicant.pdf", A["name"], A["pan"], A["dob"], 742,
           [["Coastal Co-operative Bank", "Business loan (term)", "03-2021", "20,00,000", "9,62,400", "Active", "34,850", "000 000 000 000"],
            ["Coastal Co-operative Bank", "Cash credit", "03-2021", "25,00,000", "21,40,000", "Active", "-", "000 000 000 000"],
            ["Metro Auto Finance", "Auto loan", "05-2023", "8,50,000", "4,12,000", "Active", "17,250", "000 000 030 000"],
            ["Deccan Commercial Bank", "Credit card", "08-2019", "1,50,000", "38,400", "Active", "-", "000 000 000 000"],
            ["Unity Housing Finance", "Housing loan", "06-2014", "22,00,000", "0", "Closed", "-", "Closed 2022"]], 2,
           "Remark: 30 days past due on Metro Auto Finance account in March 2026, regularised in April 2026.")
    bureau("18_CIBIL_Report_Co-applicant.pdf", C["name"], C["pan"], C["dob"], 718,
           [["Sri Lakshmi Gold Loans", "Gold loan", "02-2026", "2,40,000", "2,40,000", "Active", "-", "000 000 000 000"],
            ["QuickFin NBFC", "Personal loan", "01-2026", "5,50,000", "4,79,300", "Active", "14,800", "000 000 000 000"]], 4,
           "4 enquiries in the last 6 months (personal loan and gold loan).")
    s = title("Commercial Credit Report - MSME", "Bureau-format report (synthetic) &nbsp; Report date: 20-09-2026")
    s += kv([("Enterprise", BIZ["name"]), ("GSTIN / PAN", f"{BIZ['gstin']} / {A['pan']}"), ("MSME rank", "<b>CMR-4</b> (scale 1-10, 1 = lowest risk)"),
             ("Credit facilities", "2 active (term loan, cash credit) - both Standard"), ("Total exposure", "INR 31,02,400"),
             ("Overdue", "Nil"), ("Delinquency history", "One instance of 1-30 days overdue on term loan (Nov 2024)")])
    pdf("19_Commercial_Credit_Report_MSME.pdf", s)

    # 20-23 KYC images
    id_card("20_PAN_Card_Applicant.jpg", "PERMANENT ACCOUNT NUMBER (SPECIMEN)", [("Name", A["name"].upper()), ("Father's name", A["father"].upper()),
                                                                               ("Date of birth", A["dob"]), ("PAN", A["pan"])], (40, 70, 140))
    id_card("21_Aadhaar_Applicant_Masked.jpg", "RESIDENT ID - AADHAAR FORMAT (SPECIMEN)", [("Name", A["name"]), ("DOB", A["dob"]), ("Gender", "Male"),
                                                                                       ("Number (masked)", A["aadhaar"])], (180, 90, 30))
    id_card("22_PAN_Card_Co-applicant.jpg", "PERMANENT ACCOUNT NUMBER (SPECIMEN)", [("Name", C["name"].upper()), ("Father's name", C["father"].upper()),
                                                                                  ("Date of birth", C["dob"]), ("PAN", C["pan"])], (40, 70, 140))
    id_card("23_Aadhaar_Co-applicant_Masked.jpg", "RESIDENT ID - AADHAAR FORMAT (SPECIMEN)", [("Name", C["name"]), ("DOB", C["dob"]), ("Gender", "Female"),
                                                                                          ("Number (masked)", C["aadhaar"])], (180, 90, 30))

    # 24 residence electricity bill
    s = title("Electricity Bill - Domestic (Category I)", "Distribution company (synthetic) - used as residence address proof")
    s += kv([("Service connection no.", "KKP-8-3-167-12"), ("Consumer name", A["name"]), ("Address", RES), ("Bill month", "August 2026"),
             ("Units consumed", "412 kWh"), ("Total amount due", "3,184.00"), ("Due date", "12-09-2026")])
    pdf("24_Electricity_Bill_Residence_Address_Proof.pdf", s)

    # 25 sale deed
    s = title("Sale Deed", "Document No. 4417/2014, Sub-Registrar Office Kukatpally (synthetic)")
    s += [p(f"This deed of absolute sale is executed on 19-06-2014 by <b>Sri M. Narasimha Rao</b> (Vendor) in favour of <b>{A['name']}</b> and "
            f"<b>{C['name']}</b> (Vendees, jointly). For a total consideration of INR 38,00,000 (Rupees Thirty Eight Lakh only), the Vendor conveys "
            "the residential house bearing H.No. 8-3-167/12 on Plot No. 12, Survey No. 112/A, Kukatpally village, admeasuring <b>200 square yards</b> "
            "(167.2 sq m), together with the ground + first floor structure of plinth area 1,650 sq ft, bounded North: 30 ft road, South: Plot 17, "
            "East: Plot 11, West: Plot 13. The Vendor covenants that the property is free from encumbrances, charges and litigation."),
          Spacer(1, 4 * mm), p("Stamp duty paid: INR 2,28,000. Registration fee: INR 19,000."), Spacer(1, 10 * mm),
          p("Vendor: ______________ &nbsp;&nbsp; Vendees: ______________ / ______________")]
    pdf("25_Property_Sale_Deed.pdf", s)

    # 26 EC
    s = title("Encumbrance Certificate", "Statement of encumbrances on property, 01-01-2013 to 15-09-2026 (synthetic)")
    s += kv([("Property", "Plot No. 12, Sy. No. 112/A, Kukatpally village, 200 sq yds, H.No. 8-3-167/12"), ("Search period", "01-01-2013 to 15-09-2026")])
    s += grid([["Sl", "Date", "Document no.", "Nature of transaction", "Executant", "Claimant", "Consideration"],
               ["1", "19-06-2014", "4417/2014", "Sale deed", "M. Narasimha Rao", "K. V. Ramana & K. Lalitha", "38,00,000"],
               ["2", "24-06-2014", "4502/2014", "Mortgage by deposit of title deeds", "K. V. Ramana & K. Lalitha", "Unity Housing Finance", "22,00,000"],
               ["3", "11-08-2022", "6120/2022", "Release of mortgage", "Unity Housing Finance", "K. V. Ramana & K. Lalitha", "-"],
               ["4", "17-03-2021", "2231/2021", "Mortgage by deposit of title deeds (collateral for TL + CC)", "K. V. Ramana & K. Lalitha", "Coastal Co-operative Bank", "45,00,000"]],
              [8 * mm, 17 * mm, 19 * mm, 44 * mm, 32 * mm, 36 * mm, 22 * mm], fs=7)
    s += [p("No release of the mortgage at Sl. 4 is recorded up to the end of the search period.", SMALL)]
    pdf("26_Encumbrance_Certificate_13_Years.pdf", s)

    # 27 property tax - scanned
    def tax_lines(d):
        f1, f2 = font(34, True), font(26)
        d.text((80, 80), "MUNICIPAL CORPORATION - PROPERTY TAX RECEIPT", font=f1, fill=(30, 30, 30))
        d.text((80, 130), "(synthetic, scanned copy)", font=f2, fill=(90, 90, 90))
        y = 230
        for k, v in [("Receipt No.", "PTR/KKP/2026/558812"), ("PTIN", "1150 0871 4412"), ("Owner", "KOLLURI VENKATA RAMANA & KOLLURI LALITHA"),
                     ("Property address", "8-3-167/12, Kalyan Nagar Ph-III, Kukatpally"), ("Plinth area assessed", "1,650 sq ft (G+1, RCC)"),
                     ("Financial year", "2026-27 (both half-years)"), ("Amount paid", "Rs. 9,846.00"), ("Date of payment", "28-05-2026"),
                     ("Mode", "Online"), ("Arrears", "NIL")]:
            d.text((80, y), f"{k}:", font=f2, fill=(60, 60, 60))
            d.text((470, y), v, font=font(26, True), fill=(20, 20, 20))
            y += 62
        d.text((80, 1000), "PAID", font=font(90, True), fill=(40, 120, 60))
        d.text((80, 1600), "SYNTHETIC - LENDSPRINT DEMO - NOT A REAL RECEIPT", font=font(24, True), fill=(200, 40, 40))
    scanned_pdf("27_Property_Tax_Receipt_Scanned.pdf", tax_lines)

    # 28 building permission
    s = title("Building Permission / Approved Plan", "Planning authority (synthetic) &nbsp; Permit No. BP/KKP/2014/3371")
    s += kv([("Owner", f"{A['name']} & {C['name']}"), ("Property", "Plot No. 12, Sy. No. 112/A, Kukatpally"), ("Plot area", "200 sq yds (167.2 sq m)"),
             ("Permitted floors", "Ground + 1"), ("Permitted built-up area", "1,650 sq ft"), ("Setbacks", "Front 3.0 m, rear 1.5 m, sides 1.0 m"),
             ("Date of permission", "02-09-2014"), ("Occupancy certificate", "Issued 10-11-2015")])
    pdf("28_Approved_Building_Plan.pdf", s)

    # 29 valuation
    s = title("Valuation Report - Residential Property", "By an empanelled valuer (synthetic) &nbsp; Date of inspection: 16-09-2026")
    s += kv([("Owners", f"{A['name']} & {C['name']}"), ("Property", RES), ("Land area", "200 sq yds"),
             ("Built-up area (as measured)", "<b>1,720 sq ft</b> (G+1)"), ("Approved built-up area", "1,650 sq ft"),
             ("Deviation", "70 sq ft (4.2%) - enclosed balcony on first floor, within compoundable limits"),
             ("Age of building", "11 years; residual life 49 years"),
             ("Land value", "200 sq yds x INR 32,000 = INR 64,00,000"), ("Building value (depreciated)", "1,650 sq ft x INR 1,800 = INR 29,70,000"),
             ("Fair market value", "<b>INR 93,70,000</b>"), ("Realisable value (90%)", "INR 84,33,000"), ("Distress value (80%)", "INR 74,96,000"),
             ("Marketability", "Good - residential locality with 30 ft road access")])
    pdf("29_Property_Valuation_Report.pdf", s)

    # 30 legal
    s = title("Legal Scrutiny / Title Search Report", "By panel advocate (synthetic) &nbsp; Date: 18-09-2026")
    s += [p("Documents perused: Sale deed 4417/2014, link documents from 1986, encumbrance certificate 2013-2026, property tax receipts, approved plan."),
          Spacer(1, 3 * mm),
          p(f"<b>Opinion:</b> The title of {A['name']} and {C['name']} to the scheduled property is clear and marketable, "
            "<b>subject to the subsisting equitable mortgage in favour of Coastal Co-operative Bank (Doc. 2231/2021) securing the term loan and cash credit.</b> "
            "A valid first charge can be created only after (a) closure of those facilities and release of mortgage with NOC, or "
            "(b) a pari-passu / second charge arrangement with the existing lender's consent."),
          Spacer(1, 3 * mm), p("<b>Documents to be deposited:</b> original sale deed 4417/2014 (presently with Coastal Co-operative Bank), link documents, latest tax receipt.")]
    pdf("30_Legal_Title_Search_Report.pdf", s)

    # 31 sales invoices
    s = []
    for i in range(6):
        cust = CUSTOMERS[i % 4]
        qty = R.randint(800, 2400)
        rate = R.choice([185, 240, 312, 420])
        taxable = qty * rate
        s += title("TAX INVOICE", f"{BIZ['name']} &nbsp; GSTIN {BIZ['gstin']} &nbsp; {BIZ['addr']}")
        s += kv([("Invoice no.", f"SDPE/26-27/{410 + i * 7}"), ("Date", f"{5 + i * 4:02d}-08-2026"), ("Buyer", cust), ("Place of supply", "Telangana (36)")])
        s += grid([["Description", "HSN", "Qty", "Rate", "Taxable value"], [R.choice(["Axle flange machined", "Gear blank 42T", "Hub bore sleeve"]), "8708", str(qty), inr(rate), inr(taxable)],
                   ["CGST 9%", "", "", "", inr(taxable * 0.09)], ["SGST 9%", "", "", "", inr(taxable * 0.09)], ["Invoice total", "", "", "", inr(taxable * 1.18)]],
                  [70 * mm, 20 * mm, 22 * mm, 26 * mm, 40 * mm], num_from=2)
        if i < 5:
            s.append(PageBreak())
    pdf("31_Sales_Invoices_Sample_Aug2026.pdf", s)

    # 32 purchase invoices
    s = []
    for i in range(5):
        sup = SUPPLIERS[i % 4]
        taxable = R.randint(180000, 420000)
        s += title("TAX INVOICE (Purchase)", f"Supplier: {sup} &nbsp; GSTIN 36AAF{sup[:1]}S{R.randint(1000, 9999)}K1Z{R.randint(1, 9)}")
        s += kv([("Invoice no.", f"{sup[:3]}/{R.randint(1000, 9999)}"), ("Date", f"{3 + i * 5:02d}-08-2026"), ("Bill to", f"{BIZ['name']}, GSTIN {BIZ['gstin']}")])
        s += grid([["Description", "HSN", "Taxable value", "GST 18%", "Total"],
                   [R.choice(["EN8 steel round bars", "Carbide inserts", "Alloy steel forgings", "Cutting oil"]), R.choice(["7228", "8209", "7326"]),
                    inr(taxable), inr(taxable * 0.18), inr(taxable * 1.18)]], [60 * mm, 20 * mm, 34 * mm, 30 * mm, 34 * mm], num_from=2)
        if i < 4:
            s.append(PageBreak())
    pdf("32_Purchase_Invoices_Sample_Aug2026.pdf", s)

    # 33 stock statement
    s = title("Stock & Book-Debt Statement (for Cash Credit)", "As on 31-08-2026, submitted to Coastal Co-operative Bank")
    s += grid([["Item", "Amount (INR)", "Margin", "Drawing power (INR)"],
               ["Raw material (steel, forgings)", inr(1480000), "25%", inr(1110000)], ["Work in progress", inr(915000), "25%", inr(686250)],
               ["Finished goods", inr(985000), "25%", inr(738750)], ["Book debts < 90 days", inr(3690000), "40%", inr(2214000)],
               ["Less: creditors for goods", inr(-1840000), "", inr(-1840000)], ["Total drawing power", "", "", inr(2909000)],
               ["Sanctioned limit", "", "", inr(2500000)], ["Available DP (lower of the two)", "", "", inr(2500000)]],
              [70 * mm, 36 * mm, 22 * mm, 42 * mm], num_from=1)
    pdf("33_Stock_Statement_Aug2026.pdf", s)

    # 34 debtors / creditors ageing
    s = title("Debtors and Creditors Ageing", "As on 31-08-2026")
    s += grid([["Debtor", "0-30 days", "31-60", "61-90", ">90", "Total"],
               [CUSTOMERS[0], inr(812000), inr(604000), inr(0), inr(0), inr(1416000)], [CUSTOMERS[1], inr(522000), inr(318000), inr(96000), inr(0), inr(936000)],
               [CUSTOMERS[2], inr(410000), inr(212000), inr(118000), inr(0), inr(740000)], [CUSTOMERS[3], inr(286000), inr(158000), inr(154000), inr(212000), inr(810000)],
               ["Total", inr(2030000), inr(1292000), inr(368000), inr(212000), inr(3902000)]], [58 * mm, 24 * mm, 24 * mm, 22 * mm, 22 * mm, 28 * mm], num_from=1)
    s += grid([["Creditor", "0-30 days", "31-60", "61-90", ">90", "Total"],
               [SUPPLIERS[0], inr(462000), inr(318000), inr(0), inr(0), inr(780000)], [SUPPLIERS[1], inr(214000), inr(96000), inr(0), inr(0), inr(310000)],
               [SUPPLIERS[2], inr(388000), inr(142000), inr(0), inr(0), inr(530000)], [SUPPLIERS[3], inr(154000), inr(66000), inr(0), inr(0), inr(220000)],
               ["Total", inr(1218000), inr(622000), inr(0), inr(0), inr(1840000)]], [58 * mm, 24 * mm, 24 * mm, 22 * mm, 22 * mm, 28 * mm], num_from=1)
    s += [p(f"Note: INR 2,12,000 from {CUSTOMERS[3]} is overdue beyond 90 days (disputed quality claim).", SMALL)]
    pdf("34_Debtors_Creditors_Ageing.pdf", s)

    # 35 existing sanction letter
    s = title("Sanction Letter - Existing Facilities", "Coastal Co-operative Bank, Balanagar branch (synthetic) &nbsp; Ref: CCB/BLN/ADV/2021/117 &nbsp; Renewed 15-03-2025")
    s += kv([("Borrower", f"{BIZ['name']} (Prop. {A['name']})"), ("Facility 1", "Term loan INR 20,00,000 for machinery, 84 months, EMI INR 34,850, ROI 11.5%"),
             ("Facility 2", "Cash credit INR 25,00,000 against stock and book debts, renewable annually, ROI 11.75%"),
             ("Primary security", "Hypothecation of machinery, stock and book debts"),
             ("Collateral security", f"Equitable mortgage of residential property at {RES} (owners: {A['name']} & {C['name']})"),
             ("Guarantor", C["name"]), ("Special condition", "No further borrowing against the mortgaged property without the bank's prior written consent")])
    pdf("35_Existing_Loan_Sanction_Letter.pdf", s)

    # 36 machine quotation
    s = title("Proforma Invoice / Quotation", "Precimax Machine Tools Pvt Ltd (synthetic) &nbsp; Quotation No. PMT/Q/2026/0914 &nbsp; Date: 10-09-2026")
    s += kv([("To", f"{BIZ['name']}, {BIZ['addr']}"), ("Validity", "60 days")])
    s += grid([["Item", "Qty", "Amount (INR)"], ["CNC Vertical Machining Centre VMC 850 with 24-tool ATC, 4th axis ready", "1", inr(3120000)],
               ["Installation, commissioning & training", "1", inr(80000)], ["Tooling kit", "1", inr(100000)],
               ["Taxable value", "", inr(3300000)], ["IGST 18%", "", inr(594000)], ["Total", "", inr(3894000)]], [120 * mm, 16 * mm, 42 * mm], num_from=1)
    s += [p("Payment terms: 10% advance, 90% before dispatch. Delivery: 6 weeks from advance.", SMALL)]
    pdf("36_Machinery_Quotation_CNC_VMC.pdf", s)

    # 00 checklist (index)
    files = sorted(f for f in os.listdir(OUT) if not f.startswith(("00", "_")))
    s = title("Document Checklist - MSME Term Loan", f"{BIZ['name']} &nbsp; Application MSME/HYD/2026/00871 &nbsp; Loan INR 35,00,000")
    s += grid([["#", "Document", "Category"]] + [[f[:2], f[3:].rsplit(".", 1)[0].replace("_", " "), cat(f)] for f in files], [10 * mm, 120 * mm, 48 * mm], fs=7.5)
    s += [p(f"Proposed EMI at {LOAN['rate']}% for {LOAN['tenure']} months: INR {inr(round(emi_new, 2))}", SMALL)]
    pdf("00_Document_Checklist.pdf", s)
    return files


def cat(f):
    n = int(f[:2])
    return ("Application" if n <= 2 else "Business / vintage" if n <= 7 else "Financials & tax" if n <= 12 else "Banking" if n <= 16
            else "Credit bureau" if n <= 19 else "KYC" if n <= 24 else "Property / collateral" if n <= 30 else "Trade & working capital" if n <= 34 else "Loan-specific")


if __name__ == "__main__":
    fs = build()
    if _WM and os.path.exists(_WM):
        os.remove(_WM)
    print(len(fs) + 1, "documents written to", os.path.abspath(OUT))
