"""Makes two FICTIONAL M-Pesa statements for testing the Pro statement import.
Not real statements: every receipt, amount and number is made up.

    pip install reportlab pypdf
    python data/samples/make_mpesa_samples.py

Writes:
  mpesa_statement_SAMPLE.pdf   (password: 12345678), laid out like the M-Pesa statement table
  mpesa_business_SAMPLE.csv    the same transactions, like a business-portal CSV export
"""
import csv
import io
import random
import string
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
PASSWORD = "12345678"


def transactions():
    rnd = random.Random(2026)
    t = datetime(2026, 5, 6, 8, 0, 0)
    end = datetime(2026, 9, 30, 20, 0, 0)
    balance = 4_250.00
    rows = []
    while t < end:
        t += timedelta(minutes=rnd.randint(40, 600))
        if t.hour < 7 or t.hour > 21:
            continue
        r = rnd.random()
        if r < 0.70:
            amt = round(rnd.choice([50, 80, 100, 120, 150, 200, 250, 300, 450, 600, 1200]) * rnd.uniform(0.9, 1.6), 0)
            details, sign = "Merchant Customer Payment from 2547XXX" + str(rnd.randint(100, 999)), 1
        elif r < 0.85:
            amt = float(rnd.choice([1500, 2500, 4000, 6000]))
            details, sign = "Pay Bill to 8875XX - Supplier Goods Acc. STOCK", -1
        elif r < 0.95:
            amt = float(rnd.choice([500, 1000, 2000]))
            details, sign = "Customer Transfer to 2547XXX" + str(rnd.randint(100, 999)) + " Wages", -1
        else:
            amt = float(rnd.choice([30, 53]))
            details, sign = "Pay Merchant Charge", -1
        if sign < 0 and balance - amt < 0:
            continue
        balance = round(balance + sign * amt, 2)
        rc = rnd.choice("STU") + rnd.choice(string.ascii_uppercase) + "".join(rnd.choice(string.ascii_uppercase + string.digits) for _ in range(7)) + str(rnd.randint(0, 9))
        status = "Completed" if rnd.random() > 0.03 else "Failed"
        if status == "Failed":
            balance = round(balance - sign * amt, 2)
        rows.append({"rc": rc, "when": t, "details": details, "status": status,
                     "in": amt if sign > 0 else 0, "out": amt if sign < 0 else 0, "balance": balance})
    return rows


def money(x):
    return f"{x:,.2f}"


def write_csv(rows):
    with open(HERE / "mpesa_business_SAMPLE.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["SAMPLE - fictional test data for Biashara Check. Not a real statement."])
        w.writerow([])
        w.writerow(["Receipt No.", "Completion Time", "Initiation Time", "Details", "Transaction Status",
                    "Paid In", "Withdrawn", "Balance", "Reason Type"])
        for r in reversed(rows):
            w.writerow([r["rc"], r["when"].strftime("%d-%m-%Y %H:%M:%S"), r["when"].strftime("%d-%m-%Y %H:%M:%S"),
                        r["details"], r["status"], money(r["in"]) if r["in"] else "",
                        "-" + money(r["out"]) if r["out"] else "", money(r["balance"]), ""])


def write_pdf(rows):
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=7.5, leading=9)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24)
    story = [Paragraph("SAMPLE MOBILE MONEY STATEMENT - fictional test data for Biashara Check. Not a real statement.", styles["Heading3"]),
             Paragraph(f"Statement period: {rows[0]['when']:%d %b %Y} - {rows[-1]['when']:%d %b %Y}", small),
             Spacer(1, 8)]
    data = [["Receipt No.", "Completion Time", "Details", "Transaction Status", "Paid In", "Withdrawn", "Balance"]]
    for r in reversed(rows):  # newest first, like the real thing
        data.append([r["rc"], r["when"].strftime("%Y-%m-%d %H:%M:%S"), Paragraph(r["details"], small), r["status"],
                     money(r["in"]) if r["in"] else "", "-" + money(r["out"]) if r["out"] else "", money(r["balance"])])
    t = Table(data, colWidths=[70, 100, 250, 85, 70, 70, 80], repeatRows=1)
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7.5), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEE9")),
                           ("ALIGN", (4, 1), (-1, -1), "RIGHT")]))
    story.append(t)
    doc.build(story)
    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(buf.getvalue())).pages:
        writer.add_page(page)
    writer.encrypt(user_password=PASSWORD, owner_password=None, algorithm="AES-128")
    with open(HERE / "mpesa_statement_SAMPLE.pdf", "wb") as f:
        writer.write(f)


if __name__ == "__main__":
    rows = transactions()
    write_csv(rows)
    write_pdf(rows)
    done = [r for r in rows if r["status"] == "Completed"]
    print(f"{len(rows)} transactions ({len(done)} completed), {rows[0]['when']:%Y-%m-%d} to {rows[-1]['when']:%Y-%m-%d}")
