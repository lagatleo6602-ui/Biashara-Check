"""Reads an M-Pesa statement and turns it into monthly totals.

Privacy (Data Protection Act 2019): the file is read in memory and thrown away. Only monthly
totals leave this module: no names, phone numbers, receipt numbers or details are kept.
The PDF password is used once to open the file and never stored.

Supported:
- the M-Pesa statement PDF (usually password-protected), with columns
  Receipt No. | Completion Time | Details | Transaction Status | Paid In | Withdrawn | Balance
- a CSV export from the M-Pesa business portal with "Paid In" and "Withdrawn" columns
"""
import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime

import logging

from fastapi import HTTPException

log = logging.getLogger("uvicorn.error")

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 300

RECEIPT = r"(?=[A-Z0-9]{10}\b)(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z0-9]{10}"
ROW = re.compile(rf"^\s*(?P<rc>{RECEIPT})\s+(?P<dt>\d{{4}}-\d{{2}}-\d{{2}}\s+\d{{1,2}}:\d{{2}}(?::\d{{2}})?)\s+(?P<rest>.*)$")
MONEY = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})*(?:\.\d{2})(?![\d])|(?<![\w.,])-?\d+\.\d{2}(?![\d])")
STATUS = re.compile(r"\b(Completed|Failed|Cancelled|Canceled|Reversed|Pending|Declined)\b", re.I)
OUT_WORDS = ("payment to", "pay bill", "paybill", "customer transfer to", "withdrawal", "merchant payment to",
             "buy goods", "charge", "airtime purchase", "send money", "transfer to", "b2c", "fuliza repayment",
             "overdraft repayment", "business payment to")
IN_WORDS = ("funds received", "received from", "deposit", "payment from", "customer payment", "c2b",
            "merchant payment from", "transfer from", "reversal of")


def _money(s: str) -> float:
    return float(s.replace(",", ""))


def _when(s: str) -> datetime:
    s = re.sub(r"\s+", " ", s.strip())
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
                "%d-%m-%Y %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise ValueError(s)


def _guess_direction(details: str) -> int:
    d = details.lower()
    if any(w in d for w in IN_WORDS):
        return 1
    if any(w in d for w in OUT_WORDS):
        return -1
    return 0


# ---------- PDF ----------
def _pdf_rows(raw: bytes, password: str) -> tuple[list[dict], int]:
    try:
        import pdfplumber
        from pdfminer.pdfdocument import PDFPasswordIncorrect
        from pdfminer.pdfparser import PDFSyntaxError
    except ImportError as exc:
        raise HTTPException(503, "Reading PDF statements isn't installed on this server yet. Stop the server, run "
                                 "venv\\Scripts\\pip install pdfplumber==0.11.4 and start it again. "
                                 "(A CSV statement works without it.)") from exc

    rows, skipped = [], 0
    try:
        with pdfplumber.open(io.BytesIO(raw), password=password or "") as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise HTTPException(400, f"That statement has {len(pdf.pages)} pages. Use a shorter period (up to {MAX_PAGES} pages).")
            for page in pdf.pages:
                for line in (page.extract_text() or "").splitlines():
                    m = ROW.match(line)
                    if not m:
                        continue
                    rest = m.group("rest")
                    st = STATUS.search(rest)
                    if st and st.group(1).lower() != "completed":
                        continue
                    nums = MONEY.findall(rest[st.end():] if st else rest)
                    details = rest[:st.start()] if st else MONEY.split(rest)[0]
                    if len(nums) < 2:
                        skipped += 1
                        continue
                    balance = _money(nums[-1])
                    hint = 0
                    if len(nums) >= 3:  # Paid In, Withdrawn and Balance all printed
                        pin, wd = _money(nums[-3]), _money(nums[-2])
                        amount, hint = (abs(pin), 1) if abs(pin) > 0 else (abs(wd), -1)
                    else:
                        amount = _money(nums[-2])
                        if amount < 0:
                            hint = -1
                        amount = abs(amount)
                    try:
                        when = _when(m.group("dt"))
                    except ValueError:
                        skipped += 1
                        continue
                    rows.append({"when": when, "amount": amount, "balance": balance,
                                 "hint": hint or _guess_direction(details)})
    except PDFPasswordIncorrect as exc:
        raise HTTPException(400, "That statement is locked. Enter its password (for M-Pesa statements it's "
                                 "usually your ID number, sent with the statement)." if not password
                            else "That password didn't open the statement. Check it and try again.") from exc
    except HTTPException:
        raise
    except (PDFSyntaxError, ValueError, KeyError) as exc:
        raise HTTPException(400, "Couldn't read that file as a PDF statement.") from exc
    except Exception as exc:  # unusual encryption or a damaged file: explain instead of crashing
        log.exception("M-Pesa statement PDF could not be read")
        raise HTTPException(400, "Couldn't open this PDF statement (" + exc.__class__.__name__ + "). Check the "
                                 "password, or download the statement again. A CSV statement also works.") from exc
    out = _directions_from_balance(rows)
    return out, skipped + len(rows) - len(out)


def _directions_from_balance(rows: list[dict]) -> list[dict]:
    """Statements don't always show which column a number was in once the text is extracted.
    The running balance tells us: if it went up by the amount, money came in."""
    if not rows:
        return rows
    if rows[0]["when"] > rows[-1]["when"]:
        rows = rows[::-1]  # M-Pesa lists the newest first
    out = []
    for i, r in enumerate(rows):
        sign = 0
        if i > 0:
            diff = round(r["balance"] - rows[i - 1]["balance"], 2)
            if abs(diff - r["amount"]) < 0.015:
                sign = 1
            elif abs(diff + r["amount"]) < 0.015:
                sign = -1
        sign = sign or r["hint"]  # first row, or same-second rows out of order: printed sign or wording
        if sign:
            out.append({"when": r["when"], "in": r["amount"] if sign > 0 else 0.0,
                        "out": r["amount"] if sign < 0 else 0.0})
    return out


# ---------- CSV (M-Pesa business portal export) ----------
def _norm(h: str) -> str:
    return re.sub(r"[^a-z ]", "", (h or "").lower()).strip()


def _csv_rows(raw: bytes) -> tuple[list[dict], int]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    table = list(csv.reader(io.StringIO(text)))
    head_i = next((i for i, r in enumerate(table[:30]) if any(_norm(c) == "paid in" for c in r)), None)
    if head_i is None:
        raise HTTPException(400, "Couldn't find the 'Paid In' column. Export the statement from the M-Pesa "
                                 "business portal as CSV, or upload the PDF statement.")
    head = [_norm(c) for c in table[head_i]]

    def col(*names):
        return next((head.index(n) for n in names if n in head), None)

    c_when = col("completion time", "completion date", "transaction date", "date", "initiation time")
    c_in, c_out = col("paid in"), col("withdrawn", "paid out", "withdrawal")
    c_status = col("transaction status", "status")
    if c_when is None or c_out is None:
        raise HTTPException(400, "The CSV needs 'Completion Time', 'Paid In' and 'Withdrawn' columns.")
    rows, skipped = [], 0
    for r in table[head_i + 1:]:
        if len(r) <= max(c_when, c_in, c_out) or not r[c_when].strip():
            continue
        if c_status is not None and len(r) > c_status and r[c_status].strip() and r[c_status].strip().lower() != "completed":
            continue
        try:
            when = _when(r[c_when])
            pin = abs(_money(r[c_in])) if r[c_in].strip() else 0.0
            wd = abs(_money(r[c_out])) if r[c_out].strip() else 0.0
        except ValueError:
            skipped += 1
            continue
        if pin or wd:
            rows.append({"when": when, "in": pin, "out": wd})
    return rows, skipped


# ---------- monthly totals ----------
def summarise(rows: list[dict], skipped: int, today: date | None = None) -> dict:
    today = today or date.today()
    if not rows:
        raise HTTPException(400, "No completed M-Pesa transactions were found in that file. "
                                 "Check it's an M-Pesa statement, not a mini-statement screenshot.")
    by_month: dict[str, dict] = defaultdict(lambda: {"received": 0.0, "paid_out": 0.0, "count_in": 0, "count_out": 0})
    for r in rows:
        m = by_month[f"{r['when']:%Y-%m}"]
        if r["in"]:
            m["received"] += r["in"]; m["count_in"] += 1
        if r["out"]:
            m["paid_out"] += r["out"]; m["count_out"] += 1
    first, last = min(r["when"] for r in rows), max(r["when"] for r in rows)
    this_month = f"{today:%Y-%m}"
    months = []
    for key in sorted(by_month):
        v = by_month[key]
        note = ""
        if key >= this_month:
            note = "This month isn't over yet"
        elif key == f"{first:%Y-%m}" and first.day > 3:
            note = f"Statement starts on the {first.day}{_th(first.day)}, so this month may be incomplete"
        elif key == f"{last:%Y-%m}" and last.day < 26:
            note = f"Statement ends on the {last.day}{_th(last.day)}, so this month may be incomplete"
        months.append({"month": key, "received": round(v["received"], 2), "paid_out": round(v["paid_out"], 2),
                       "count_in": v["count_in"], "count_out": v["count_out"], "note": note,
                       "usable": key < this_month})
    return {"from": f"{first:%Y-%m-%d}", "to": f"{last:%Y-%m-%d}", "transactions": len(rows),
            "skipped": skipped, "months": months}


def _th(n: int) -> str:
    return "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def read_statement(raw: bytes, filename: str, password: str = "", today: date | None = None) -> dict:
    if not raw:
        raise HTTPException(400, "The file is empty.")
    if len(raw) > MAX_BYTES:
        raise HTTPException(400, "That file is over 10 MB. Download a shorter period.")
    is_pdf = raw[:5] == b"%PDF-" or filename.lower().endswith(".pdf")
    rows, skipped = _pdf_rows(raw, password) if is_pdf else _csv_rows(raw)
    return summarise(rows, skipped, today)
