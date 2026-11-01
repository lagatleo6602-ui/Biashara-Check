"""Reads almost any spreadsheet of business figures and turns it into monthly records.

Owners keep records in many shapes, so this module tries hard not to say "wrong file":

- CSV with commas, semicolons, tabs or pipes, in UTF-8 or Windows encoding, or an Excel .xlsx file;
- a title or notes above the header row, empty rows and columns, totals rows;
- one row per month, or one row per sale / expense / transaction (added up per month);
- months down the side, or months across the top (turned around);
- dates as 2025-06, Jun 2025, June-25, 06/2025, 15/06/2025, Excel date numbers, or a separate Year and Month;
- column names in English or Kiswahili, with units such as "(KES)", and costs split over several columns
  (rent, wages, power ...), which are added together;
- amounts like "KES 12,000", "12,000/=", "(1,500)", "12 000", "1.2k";
- figures it can't find are worked out where that is safe (money received = sales if missing, and so on),
  and every assumption is listed for the owner to see.

parse() never raises for a messy file. It returns what it understood, the column mapping, notes,
skipped rows and, if needed, what it still needs from the owner (usually just "which column is sales?").
"""
from __future__ import annotations

import csv
import difflib
import io
import re
from collections import defaultdict
from datetime import date, datetime, timedelta

MAX_BYTES = 5 * 1024 * 1024

FIELDS = ["revenue", "cogs", "operating_expenses", "cash_inflows", "cash_outflows", "mobile_money_receipts",
          "closing_stock", "outstanding_debt", "transaction_count"]
BALANCES = {"closing_stock", "outstanding_debt"}  # a month's value is its last figure, not a sum
LABELS = {"month": "Month", "revenue": "Total sales", "cogs": "Cost of goods sold",
          "operating_expenses": "Running expenses", "cash_inflows": "Money received", "cash_outflows": "Money paid out",
          "mobile_money_receipts": "Received by M-Pesa", "closing_stock": "Stock value", "outstanding_debt": "Money owed",
          "transaction_count": "Number of sales", "total_costs": "Total costs", "profit": "Profit"}

# Names people use. Matched on cleaned headers (lower case, no units, no punctuation).
SYN = {
    "month": ["month", "date", "period", "month year", "year month", "mwezi", "tarehe", "month ending", "for the month"],
    "year": ["year", "mwaka", "yr"],
    "revenue": ["revenue", "sales", "total sales", "income", "turnover", "takings", "gross sales", "sales amount",
                "total revenue", "total income", "mauzo", "jumla ya mauzo", "mapato", "amount sold", "sales revenue",
                "money from sales", "sales kes"],
    "cogs": ["cogs", "cost of goods sold", "cost of goods", "cost of sales", "cost of stock sold", "stock purchases",
             "purchases", "buying cost", "goods bought", "stock bought", "stock purchased", "purchases of stock", "gharama ya bidhaa", "bei ya kununua", "manunuzi",
             "direct costs", "cost of products sold"],
    "operating_expenses": ["operating expenses", "running expenses", "expenses", "opex", "operating costs",
                           "running costs", "overheads", "overhead", "total expenses", "matumizi",
                           "gharama za uendeshaji", "other expenses", "indirect costs", "general expenses"],
    "total_costs": ["total costs", "costs", "cost", "expenditure", "total expenditure", "gharama", "spending",
                    "total spending", "outgoings"],
    "profit": ["profit", "net profit", "profit loss", "profit or loss", "net income", "net", "faida", "pl",
               "net operating result", "gain"],
    "cash_inflows": ["cash inflows", "cash in", "money in", "money received", "inflows", "cash received",
                     "receipts", "total receipts", "pesa iliyoingia", "deposits", "credits", "paid in"],
    "cash_outflows": ["cash outflows", "cash out", "money out", "money paid out", "outflows", "cash paid",
                      "payments", "total payments", "pesa iliyotoka", "withdrawals", "debits", "withdrawn"],
    "mobile_money_receipts": ["mobile money receipts", "mpesa", "m pesa", "mpesa receipts", "mpesa sales",
                              "mpesa income", "received by mpesa", "mobile money", "lipa na mpesa", "till",
                              "paybill", "till receipts", "mpesa till"],
    "closing_stock": ["closing stock", "stock", "stock value", "inventory", "closing inventory", "stock on hand",
                      "bidhaa", "thamani ya bidhaa", "inventory value"],
    "outstanding_debt": ["outstanding debt", "debt", "money owed", "loans", "loan balance", "liabilities",
                         "credit owed", "deni", "madeni", "amount owed", "loan", "creditors"],
    "transaction_count": ["transaction count", "transactions", "number of sales", "sales count", "no of sales",
                          "num sales", "customers", "number of customers", "orders", "receipts count",
                          "idadi ya mauzo", "wateja", "count"],
    "amount": ["amount", "value", "kiasi", "total", "amount kes", "sum"],
    "type": ["type", "category", "kind", "transaction type", "in out", "aina", "class", "description type"],
    "business": ["business code", "business", "business id", "shop", "branch", "biashara"],
}
# Single running costs that add up to running expenses when there is no total column.
EXPENSE_WORDS = ["rent", "wage", "wages", "salary", "salaries", "power", "electricity", "water", "transport", "fuel",
                 "airtime", "internet", "licence", "license", "permit", "tax", "repairs", "repair", "marketing",
                 "security", "cleaning", "kodi", "mshahara", "umeme", "maji", "usafiri", "insurance", "phone",
                 "utilities", "advertising", "packaging", "bank charges", "loan interest", "interest"]
SALES_PARTS = ["cash sales", "credit sales", "mpesa sales", "card sales", "online sales", "sales cash",
               "sales mpesa", "till sales"]

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MONTHS.update({"sept": 9, "january": 1, "february": 2, "march": 3, "april": 4, "june": 6, "july": 7, "august": 8,
               "september": 9, "october": 10, "november": 11, "december": 12,
               # Kiswahili
               "januari": 1, "februari": 2, "machi": 3, "aprili": 4, "mei": 5, "juni": 6, "julai": 7,
               "agosti": 8, "septemba": 9, "oktoba": 10, "novemba": 11, "desemba": 12, "mac": 3, "ago": 8,
               "okt": 10, "des": 12})
IN_WORDS = ["in", "income", "sale", "sales", "credit", "receipt", "received", "deposit", "revenue", "mauzo", "paid in", "inflow"]
OUT_WORDS = ["out", "expense", "expenses", "cost", "debit", "payment", "paid", "purchase", "withdrawal", "matumizi",
             "gharama", "outflow", "bought"]


# ---------- reading the file into a grid of text ----------
def read_grid(raw: bytes, filename: str = "") -> tuple[list[list[str]], str]:
    """Returns (rows of cell text, a note about how it was read)."""
    name = (filename or "").lower()
    if raw[:5] == b"%PDF-":
        raise ValueError("This is a PDF. If it's an M-Pesa statement, use the M-Pesa tab. For other records, "
                         "save them from Excel or Google Sheets as CSV or Excel (.xlsx) and upload that.")
    if raw[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1") or raw[:3] == b"\xff\xd8\xff":
        raise ValueError("This is a picture. Biashara Check can't read photos of a sales book yet: type the months "
                         "in with Add a month, or put them in a spreadsheet and upload that.")
    if name.endswith((".xlsx", ".xlsm")) or raw[:2] == b"PK":
        try:
            return _read_xlsx(raw)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("This file couldn't be opened as an Excel workbook. If it's a Word or other document, "
                             "copy the figures into Excel or Google Sheets and save as CSV or .xlsx.") from exc
    if name.endswith(".xls") or raw[:4] == b"\xd0\xcf\x11\xe0":
        raise ValueError("This is an old Excel file (.xls). In Excel choose File, Save As, and pick "
                         "\"Excel Workbook (.xlsx)\" or \"CSV UTF-8\", then upload that.")
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            if enc == "utf-16" and not raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                continue
            break
        except UnicodeDecodeError:
            continue
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    sample = "\n".join(text.splitlines()[:30])
    try:
        sep = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in ",;\t|"}
        sep = max(counts, key=counts.get) if any(counts.values()) else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=sep))
    return [[(c or "").strip() for c in r] for r in rows], ""


def _read_xlsx(raw: bytes) -> tuple[list[list[str]], str]:
    try:
        import openpyxl
    except ImportError as exc:
        raise ValueError("Reading Excel files isn't installed on this server yet. Save the file as "
                         "\"CSV UTF-8\" in Excel and upload that instead.") from exc
    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    best, best_score, best_name = [], -1, ""
    for ws in wb.worksheets:
        rows = []
        for r in ws.iter_rows(values_only=True):
            rows.append([_cell_text(c) for c in r])
            if len(rows) > 20000:
                break
        score = sum(1 for r in rows for c in r if _num(c) is not None)
        if score > best_score:
            best, best_score, best_name = rows, score, ws.title
    note = f"Read the sheet \"{best_name}\"." if len(wb.worksheets) > 1 else ""
    return best, note


def _cell_text(c) -> str:
    if c is None:
        return ""
    if isinstance(c, datetime):
        return c.strftime("%Y-%m-%d")
    if isinstance(c, date):
        return c.isoformat()
    if isinstance(c, float) and c.is_integer():
        return str(int(c))
    return str(c).strip()


# ---------- small parsers ----------
_NUM_JUNK = re.compile(r"(?i)\b(kes|ksh|kshs|sh|shs|tsh|usd)\b\.?|/=|/-|\s")


def _num(s) -> float | None:
    """'KES 12,000' -> 12000; '(1,500)' -> -1500; '1.2k' -> 1200; '' / '-' -> None."""
    if s is None:
        return None
    t = str(s).strip()
    if not t or t in {"-", "--", "–", "n/a", "na", "N/A", "#N/A", "nil"}:
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    t = _NUM_JUNK.sub("", t)
    mult = 1
    if t[-1:].lower() == "k":
        mult, t = 1000, t[:-1]
    elif t[-1:].lower() == "m" and re.match(r"^-?[\d.,]+m$", t, re.I):
        mult, t = 1_000_000, t[:-1]
    if t.count(",") and t.count("."):
        t = t.replace(",", "")  # 12,000.50
    elif t.count(",") == 1 and re.match(r"^-?\d+,\d{1,2}$", t):
        t = t.replace(",", ".")  # 12000,50 (decimal comma)
    else:
        t = t.replace(",", "")
    t = t.replace("%", "")
    try:
        v = float(t) * mult
    except ValueError:
        return None
    return -v if neg else v


def _month(s, dayfirst=True, serial_ok=False) -> date | None:
    """Many ways of writing a month -> the first of that month. Excel day numbers only when serial_ok
    (a column named like a date), so that sales of 45,000 are never read as a date."""
    if s is None:
        return None
    t = str(s).strip().lower().replace(",", " ")
    if not t:
        return None
    # Excel serial date
    if re.fullmatch(r"\d{5}(\.\d+)?", t):
        if not serial_ok:
            return None
        n = float(t)
        if 20000 < n < 80000:
            d = date(1899, 12, 30) + timedelta(days=int(n))
            return date(d.year, d.month, 1)
        return None
    m = re.fullmatch(r"(\d{4})[-/. ](\d{1,2})(?:[-/. ](\d{1,2}))?(?:[ t].*)?", t)  # 2025-06, 2025/06/15
    if m and 1 <= int(m.group(2)) <= 12:
        return date(int(m.group(1)), int(m.group(2)), 1)
    m = re.fullmatch(r"(\d{1,2})[-/. ](\d{4})", t)  # 06/2025
    if m and 1 <= int(m.group(1)) <= 12:
        return date(int(m.group(2)), int(m.group(1)), 1)
    m = re.fullmatch(r"(\d{1,2})[-/. ](\d{1,2})[-/. ](\d{2,4})(?:[ t].*)?", t)  # 15/06/2025 (day first in Kenya)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        day, mon = (a, b) if dayfirst else (b, a)
        if mon > 12 and day <= 12:
            day, mon = mon, day
        if 1 <= mon <= 12 and 1 <= day <= 31:
            return date(y, mon, 1)
        return None
    words = re.findall(r"[a-z]+|\d+", t)
    mon = next((MONTHS[w] for w in words if w in MONTHS), None)
    nums = [int(w) for w in words if w.isdigit()]
    year = next((n for n in nums if 1990 <= n <= 2100), None)
    if year is None:
        short = [n for n in nums if n < 100 and not (n <= 31 and len(nums) > 1 and n == nums[0])]
        if short:
            year = 2000 + short[-1]
    if mon and year:
        return date(year, mon, 1)
    return None


def _clean_header(h: str) -> str:
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", str(h).lower())
    t = re.sub(r"\b(kes|ksh|kshs|shs|amount|amt|total of|in kes|per month|monthly|this month|the)\b", " ", t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t.replace("-", " ").replace("_", " "))
    return re.sub(r"\s+", " ", t).strip()


def _score(header: str, key: str) -> float:
    h = _clean_header(header)
    raw = re.sub(r"[^a-z0-9 ]+", " ", str(header).lower().replace("_", " ").replace("-", " "))
    raw = re.sub(r"\s+", " ", raw).strip()
    if not h and not raw:
        return 0
    best = 0.0
    for syn in SYN[key]:
        if h == syn or raw == syn:
            return 1.0
        if re.search(rf"\b{re.escape(syn)}\b", h) and len(syn) >= 4:
            best = max(best, 0.8 if len(syn.split()) > 1 else 0.7)
        r = difflib.SequenceMatcher(None, h, syn).ratio()
        if r >= 0.86:
            best = max(best, r * 0.85)
    return best


# ---------- the main entry ----------
def parse(raw: bytes, filename: str = "", mapping: dict | None = None, own_code: str = "",
          last_month: date | None = None) -> dict:
    """Never raises: an unreadable file comes back as status "error" with a plain message."""
    try:
        return _parse(raw, filename, mapping, own_code, last_month)
    except Exception:  # a file shape nobody thought of: say so kindly, and keep the details for the log
        import logging
        logging.getLogger("uvicorn.error").exception("Import could not read %s", filename)
        return _fail("We couldn't make sense of this file. Open it in Excel or Google Sheets, check that it has a row "
                     "of column names and one row per month (or per sale), save it as CSV or .xlsx and try again. "
                     "You can also download our template and copy your figures into it.")


def _parse(raw: bytes, filename: str, mapping: dict | None, own_code: str, last_month: date | None) -> dict:
    mapping = mapping or {}
    notes: list[str] = []
    try:
        grid, how = read_grid(raw, filename)
    except ValueError as e:
        return _fail(str(e))
    if how:
        notes.append(how)
    grid = [r for r in grid if any(c.strip() for c in r)]
    if not grid:
        return _fail("The file is empty.")
    width = max(len(r) for r in grid)
    grid = [r + [""] * (width - len(r)) for r in grid]
    keep = [j for j in range(width) if any(r[j].strip() for r in grid)]
    grid = [[r[j] for j in keep] for r in grid]

    text = " ".join(" ".join(r) for r in grid[:15]).lower()
    if "paid in" in text and ("receipt no" in text or "completion time" in text):
        return _fail("This looks like an M-Pesa statement, not your monthly records. Statements go in the M-Pesa tab.",
                     kind="mpesa")

    wide = _try_wide(grid, filename or "", last_month)
    if wide:
        grid = wide
        notes.append("Your months run across the top, so the table was turned around.")
    hi = _header_row(grid)
    if hi > 0:
        notes.append(f"Started reading at row {hi + 1}, where the column names are.")
    header = [h or f"Column {j + 1}" for j, h in enumerate(grid[hi])]
    seen: dict[str, int] = {}
    for j, h in enumerate(header):  # make names unique
        if h in seen:
            seen[h] += 1
            header[j] = f"{h} ({seen[h]})"
        else:
            seen[h] = 1
    body = grid[hi + 1:]
    cols = {h: [r[j] for r in body] for j, h in enumerate(header)}

    # numeric share of each column
    def numeric_share(h):
        vals = [v for v in cols[h] if v.strip()]
        return sum(_num(v) is not None for v in vals) / len(vals) if vals else 0

    def date_share(h):
        vals = [v for v in cols[h] if v.strip()]
        ok = _score(h, "month") >= 0.5
        return sum(_month(v, serial_ok=ok) is not None for v in vals) / len(vals) if vals else 0

    if not body or not any(numeric_share(h) >= 0.5 for h in header):
        return _fail("We couldn't find any figures in this file. It should have a row of column names (such as Month, "
                     "Sales, Expenses) and then one row per month or per sale. You can also download our template and "
                     "copy your figures into it.")

    # ---- one business only
    bcol = mapping.get("business_column") or _best(header, "business", min_score=0.7)
    business_note = None
    if bcol and bcol in cols:
        codes = sorted({v.strip() for v in cols[bcol] if v.strip()})
        if len(codes) > 1:
            pick = mapping.get("business_value") or next((c for c in codes if c.upper() == own_code.upper()), None)
            if pick and pick in codes:
                rows_keep = [i for i, v in enumerate(cols[bcol]) if v.strip() == pick]
                body = [body[i] for i in rows_keep]
                cols = {h: [r[j] for r in body] for j, h in enumerate(header)}
                business_note = f"Your file has {len(codes)} businesses; only the rows for {pick} were used."
            else:
                return {**_fail("", kind="choose_business"), "businesses": codes[:200], "business_column": bcol,
                        "columns": _col_info(header, cols)}

    # ---- the month
    used: set[str] = set()
    month_col = mapping.get("month")
    if month_col is None:
        cands = [(date_share(h), -numeric_share(h) if date_share(h) < 0.95 else 0, h) for h in header]
        cands = [c for c in cands if c[0] >= 0.6]
        named = _best(header, "month", min_score=0.7)
        if named and date_share(named) >= 0.6:
            month_col = named
        elif cands:
            month_col = max(cands)[2]
    year_col = None
    months_list: list[date | None] = []
    if month_col and month_col in cols:
        used.add(month_col)
        months_list = [_month(v, serial_ok=True) for v in cols[month_col]]
        if sum(m is not None for m in months_list) < max(1, 0.3 * len(months_list)):
            # maybe "Jan" + a Year column
            year_col = _best(header, "year", min_score=0.7)
            if year_col:
                used.add(year_col)
                months_list = [_month(f"{m} {y}") for m, y in zip(cols[month_col], cols[year_col])]
    elif month_col != "":
        year_col = _best(header, "year", min_score=0.7)
        mcol = _best(header, "month", min_score=0.5)
        if year_col and mcol:
            month_col = mcol
            used |= {year_col, mcol}
            months_list = [_month(f"{m} {y}") for m, y in zip(cols[mcol], cols[year_col])]
    start = mapping.get("start_month")
    no_dates = not months_list or not any(months_list)
    if no_dates:
        if start:
            s0 = _month(start)
            months_list, k = [], 0
            for r in body:
                if any(_num(c) is not None for c in r):
                    months_list.append(date(s0.year + (s0.month - 1 + k) // 12, (s0.month - 1 + k) % 12 + 1, 1))
                    k += 1
                else:
                    months_list.append(None)
            notes.append(f"No dates in the file, so the rows were taken as consecutive months from {s0:%b %Y}.")
        else:
            return {**_fail("", kind="need_start"), "columns": _col_info(header, cols),
                    "mapping": {"month": ""}, "notes": notes}

    # ---- find the figures
    m: dict[str, list[str]] = {}

    def take(key, h):
        m.setdefault(key, []).append(h)
        used.add(h)

    numeric_cols = [h for h in header if h not in used and numeric_share(h) >= 0.5]
    overrides = {k: v for k, v in mapping.items() if k in FIELDS + ["total_costs", "profit"]}
    for key, src in overrides.items():
        srcs = [s for s in ([src] if isinstance(src, str) else src) if s and s in cols]
        m[key] = srcs
        used |= set(srcs)
    # several sales columns (cash sales + M-Pesa sales ...) and no plain total -> add them up
    if "revenue" not in overrides and not any(_score(h, "revenue") >= 1.0 for h in numeric_cols if h not in used):
        parts = [h for h in numeric_cols if h not in used and any(p in _clean_header(h) for p in SALES_PARTS)]
        if len(parts) >= 2:
            for h in parts:
                take("revenue", h)
            notes.append("Total sales = " + " + ".join(f'"{h}"' for h in parts) + ".")
            mp = [h for h in parts if "mpesa" in _clean_header(h) or "till" in _clean_header(h)]
            if mp and "mobile_money_receipts" not in overrides:
                m["mobile_money_receipts"] = mp
    # each column goes to the field it matches best, strongest matches first
    keys = [k for k in FIELDS + ["total_costs", "profit"] if k not in overrides and k not in m]
    pairs = sorted(((_score(h, k), -keys.index(k), k, h) for k in keys for h in numeric_cols if h not in used),
                   reverse=True)
    for sc, _, key, h in pairs:
        if sc < 0.66:
            break
        if key in m or h in used:
            continue
        take(key, h)
    # single running costs -> add up
    if "operating_expenses" not in overrides and "operating_expenses" not in m:
        parts = [h for h in numeric_cols if h not in used
                 and any(re.search(rf"\b{w}\b", _clean_header(h)) for w in EXPENSE_WORDS)]
        if parts:
            for h in parts:
                take("operating_expenses", h)
            notes.append("Running expenses = " + " + ".join(f'"{h}"' for h in parts) + ".")

    # ---- transaction lists: one amount column with a type, or money in / money out columns
    amount_col = type_col = None
    if "revenue" not in m and "cash_inflows" not in m:
        amount_col = mapping.get("amount") or _best([h for h in numeric_cols if h not in used], "amount", min_score=0.66)
        if amount_col:
            type_col = mapping.get("type") or _best([h for h in header if h not in used and numeric_share(h) < 0.5],
                                                    "type", min_score=0.66)
            if not type_col:  # any text column whose values look like in / out
                for h in header:
                    if h in used or numeric_share(h) >= 0.5:
                        continue
                    vals = {_clean_header(v) for v in cols[h] if v.strip()}
                    if vals and len(vals) <= 12 and any(_dir(v) for v in vals):
                        type_col = h
                        break

    # ---- build rows
    per: dict[date, dict] = defaultdict(lambda: defaultdict(float))
    counts: dict[date, int] = defaultdict(int)
    last_seen: dict[date, dict] = defaultdict(dict)
    skipped: list[dict] = []
    last = last_month
    for i, r in enumerate(body):
        mo = months_list[i] if i < len(months_list) else None
        rowtext = " ".join(r).lower()
        if mo is None:
            if any(_num(c) is not None for c in r) and not re.search(r"\b(total|jumla|sum|grand)\b", rowtext):
                skipped.append({"row": hi + i + 2, "reason": "no month could be read"})
            continue
        if last and mo > last:
            skipped.append({"row": hi + i + 2, "reason": f"{mo:%b %Y} hasn't finished yet"})
            continue
        got = False
        for key, srcs in m.items():
            vals = [_num(cols[h][i]) for h in srcs]
            vals = [v for v in vals if v is not None]
            if not vals:
                continue
            got = True
            v = sum(vals)
            if key in BALANCES:
                last_seen[mo][key] = abs(v)
            else:
                per[mo][key] += v
        if amount_col:
            v = _num(cols[amount_col][i])
            if v is not None:
                got = True
                per[mo]["revenue"] += 0
                d = _dir(_clean_header(cols[type_col][i])) if type_col else ("in" if v >= 0 else "out")
                if d == "in" or (d is None and v > 0 and not type_col):
                    per[mo]["revenue"] += abs(v)
                    per[mo]["cash_inflows"] += abs(v)
                    counts[mo] += 1
                elif d == "out" or v < 0:
                    per[mo]["operating_expenses"] += abs(v)
                    per[mo]["cash_outflows"] += abs(v)
        if got:
            counts.setdefault(mo, 0)
            if not amount_col:
                counts[mo] += 1
        elif any(_num(c) is not None for c in r):
            skipped.append({"row": hi + i + 2, "reason": "no figures in the matched columns"})
    if amount_col:
        notes.append(f"Your file lists single transactions, so they were added up per month "
                     f"(\"{amount_col}\"" + (f", split by \"{type_col}\" into money in and out)." if type_col else
                                              ", positive amounts as money in and negative as money out)."))
        m.setdefault("revenue", [amount_col])
    multi = [mo for mo, n in counts.items() if n > 1]
    if multi and not amount_col:
        notes.append(f"Some months appear on several rows ({len(multi)} months), so their figures were added up "
                     "(stock and money owed take the last figure of the month).")
        if "transaction_count" not in m and len(multi) >= max(1, len(counts) // 2):
            for mo in counts:
                per[mo]["transaction_count"] = counts[mo]
            notes.append("Number of sales = the number of rows in each month.")
    for mo, vals in last_seen.items():
        per[mo].update(vals)

    # ---- fill the gaps safely, and say so
    assumed: set[str] = set()
    records = []
    for mo in sorted(per):
        v = per[mo]
        if "revenue" not in v and "profit" in v and ("total_costs" in v or "cogs" in v or "operating_expenses" in v):
            v["revenue"] = v["profit"] + v.get("total_costs", 0) + v.get("cogs", 0) + v.get("operating_expenses", 0)
            assumed.add("revenue_from_profit")
        if "total_costs" in v:
            tc = abs(v.pop("total_costs"))
            if "cogs" in v and "operating_expenses" not in v:
                v["operating_expenses"] = max(0.0, tc - abs(v["cogs"]))
                assumed.add("opex_from_total")
            elif "operating_expenses" in v and "cogs" not in v:
                v["cogs"] = max(0.0, tc - abs(v["operating_expenses"]))
                assumed.add("cogs_from_total")
            elif "cogs" not in v and "operating_expenses" not in v:
                v["operating_expenses"] = tc
                assumed.add("all_costs_running")
        if "revenue" in v and "profit" in v:
            rest = v["revenue"] - v["profit"]
            if "cogs" not in v and "operating_expenses" in v:
                v["cogs"] = max(0.0, rest - abs(v["operating_expenses"]))
                assumed.add("cogs_from_profit")
            elif "operating_expenses" not in v and "cogs" in v:
                v["operating_expenses"] = max(0.0, rest - abs(v["cogs"]))
                assumed.add("opex_from_profit")
            elif "cogs" not in v and "operating_expenses" not in v:
                v["operating_expenses"] = max(0.0, rest)
                assumed.add("costs_from_profit")
        v.pop("profit", None)
        if "revenue" not in v:
            continue
        for k in ("cogs", "operating_expenses"):
            if k not in v:
                v[k] = 0.0
                assumed.add(f"no_{k}")
        for k in ("revenue", "cogs", "operating_expenses", "cash_inflows", "cash_outflows", "mobile_money_receipts",
                  "transaction_count"):
            if k in v:
                v[k] = abs(v[k])
        if "cash_inflows" not in v:
            v["cash_inflows"] = v["revenue"]
            assumed.add("cash_in")
        if "cash_outflows" not in v:
            v["cash_outflows"] = v["cogs"] + v["operating_expenses"]
            assumed.add("cash_out")
        if v.get("mobile_money_receipts", 0) > v["cash_inflows"]:
            v["cash_inflows"] = v["mobile_money_receipts"]
        rec = {"month": f"{mo:%Y-%m}"}
        for k in FIELDS:
            if k in v:
                rec[k] = int(round(v[k])) if k == "transaction_count" else round(v[k], 2)
        records.append(rec)

    text_for = {
        "revenue_from_profit": "Total sales were worked out as profit + costs.",
        "opex_from_total": "Running expenses = total costs minus cost of goods sold.",
        "cogs_from_total": "Cost of goods sold = total costs minus running expenses.",
        "all_costs_running": "Your file has one figure for costs, so all of it is counted as running expenses.",
        "costs_from_profit": "Costs were worked out as sales minus profit, and counted as running expenses.",
        "cogs_from_profit": "Cost of goods sold was worked out from sales, profit and running expenses.",
        "opex_from_profit": "Running expenses were worked out from sales, profit and cost of goods sold.",
        "no_cogs": "No cost of goods sold in the file, so it is set to 0.",
        "no_operating_expenses": "No running expenses in the file, so they are set to 0.",
        "cash_in": "No \"money received\" column, so money received = total sales.",
        "cash_out": "No \"money paid out\" column, so money paid out = cost of goods + running expenses.",
    }
    notes += [text_for[k] for k in text_for if k in assumed]
    if business_note:
        notes.insert(0, business_note)

    shown_map = {"month": month_col or ""}
    if year_col:
        shown_map["year"] = year_col
    for k in FIELDS + ["total_costs", "profit"]:
        if k in m:
            shown_map[k] = m[k] if len(m[k]) > 1 else m[k][0]
    if amount_col:
        shown_map["amount"] = amount_col
        if type_col:
            shown_map["type"] = type_col
    status = "ok" if records else "need_sales"
    return {"status": status, "records": records, "mapping": shown_map, "notes": notes,
            "skipped": skipped[:100], "skipped_count": len(skipped), "columns": _col_info(header, cols),
            "message": "" if records else "We couldn't tell which column has your sales. Choose it below."}


def _dir(v: str) -> str | None:
    v = v.strip()
    if not v:
        return None
    if any(re.search(rf"\b{w}\b", v) for w in OUT_WORDS):
        return "out"
    if any(re.search(rf"\b{w}\b", v) for w in IN_WORDS):
        return "in"
    return None


def _best(headers, key, min_score=0.66):
    sc = sorted(((_score(h, key), h) for h in headers), reverse=True)
    return sc[0][1] if sc and sc[0][0] >= min_score else None


def _header_row(grid) -> int:
    """The first row that looks like column names: mostly text, followed by rows with numbers."""
    for i, r in enumerate(grid[:25]):
        filled = [c for c in r if c.strip()]
        if len(filled) < 2:
            continue
        texty = sum(_num(c) is None and _month(c) is None for c in filled)
        if texty >= max(2, 0.5 * len(filled)):
            nxt = grid[i + 1:i + 4]
            if any(sum(_num(c) is not None for c in n) >= 1 for n in nxt):
                return i
    return 0


def _bare_months(cells, hint_text, last_month):
    """Jan, Feb, Mar ... with no year: take a year from the title, else the latest year that isn't in the future."""
    nums = [MONTHS.get(c.strip().lower()[:9]) or MONTHS.get(c.strip().lower()[:3]) if c.strip() else None for c in cells]
    if sum(n is not None for n in nums) < 3:
        return None
    yrs = re.findall(r"\b(19[9]\d|20\d\d)\b", hint_text)
    last = last_month or date.today()
    year = int(yrs[-1]) if yrs else last.year
    out, prev, y = [], None, year
    seq = [n for n in nums if n]
    if not yrs and date(year, seq[-1], 1) > last:  # e.g. Jan..Dec this year not finished: last year
        y = year - 1
    for n in nums:
        if n is None:
            out.append(None)
            continue
        if prev and n < prev:
            y += 1
        out.append(date(y, n, 1))
        prev = n
    return out


def _try_wide(grid, hint_text="", last_month=None):
    """Months across the top and figures down the side -> one row per month."""
    for i, r in enumerate(grid[:15]):
        cells = r[1:]
        ms = [_month(c) for c in cells]
        if sum(x is not None for x in ms) < 3:
            ms = _bare_months(cells, hint_text + " " + " ".join(" ".join(g) for g in grid[:i]), last_month) or ms
        good = sum(x is not None for x in ms)
        if good >= 3 and good >= 0.6 * len([c for c in cells if c.strip()]) and _month(r[0]) is None:
            out = [["Month"] + [row[0] or f"Row {k}" for k, row in enumerate(grid[i + 1:], start=i + 2)]]
            for j, mo in enumerate(ms, start=1):
                if mo is None:
                    continue
                out.append([f"{mo:%Y-%m}"] + [row[j] if j < len(row) else "" for row in grid[i + 1:]])
            return out
    return None


def _col_info(header, cols):
    return [{"name": h, "sample": [v for v in cols[h] if v.strip()][:3]} for h in header]


def _fail(msg: str, kind: str = "error") -> dict:
    return {"status": kind, "message": msg, "records": [], "mapping": {}, "notes": [], "skipped": [],
            "skipped_count": 0, "columns": []}
