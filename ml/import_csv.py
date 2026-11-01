"""Import business-months from a CSV for training the risk model.

The CSV uses the layout of Admin > Download all records (one row per business-month):

    business_code, sector, month, revenue, cogs, operating_expenses, cash_inflows, cash_outflows
    and optionally: mobile_money_receipts, closing_stock, outstanding_debt, transaction_count

Other columns (is_synthetic, net_operating_result, loss_next_3m, trajectory ...) are ignored.
Months are written 2025-06 or 2025-06-01.

Imported businesses are always flagged synthetic: no login, counted apart from the real
participants everywhere, and removed with "Remove all synthetic businesses". (Real participants'
figures come only from the owners themselves; a database backup restores them.) A business
code that already exists is skipped, so importing the same file twice is safe.

    python -m ml.import_csv data/training/biashara_training_data.csv
"""
import argparse
import csv
import io
import re
from datetime import date

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

REQUIRED = ["business_code", "sector", "month", "revenue", "cogs", "operating_expenses", "cash_inflows", "cash_outflows"]
OPTIONAL = ["mobile_money_receipts", "closing_stock", "outstanding_debt", "transaction_count"]
MAX_ROWS = 200_000
CODE_RE = re.compile(r"^[A-Z0-9-]{3,20}$")
MONTH_RE = re.compile(r"^(\d{4})-(\d{2})(?:-\d{2})?$")


class ImportError_(ValueError):
    pass


def _num(v: str, col: str, line: int, integer: bool = False) -> float:
    v = (v or "").strip().replace(",", "")
    if v == "":
        return 0
    try:
        x = float(v)
    except ValueError:
        raise ImportError_(f"Row {line}: {col} is not a number ({v!r}).")
    if x < 0:
        raise ImportError_(f"Row {line}: {col} can't be negative.")
    return int(round(x)) if integer else round(x, 2)


def parse(text: str) -> dict[str, dict]:
    """Checks the whole file first. Returns {code: {"sector": ..., "rows": [...]}} or raises ImportError_."""
    from app.sectors import SECTORS

    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    cols = [c.strip() for c in (reader.fieldnames or [])]
    reader.fieldnames = cols
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        raise ImportError_("The file is missing these columns: " + ", ".join(missing) + ".")
    out: dict[str, dict] = {}
    seen: set[tuple[str, date]] = set()
    for line, row in enumerate(reader, start=2):
        if line - 1 > MAX_ROWS:
            raise ImportError_(f"The file has more than {MAX_ROWS:,} rows. Split it into smaller files.")
        if not any((v or "").strip() for v in row.values()):
            continue
        code = (row["business_code"] or "").strip().upper()
        if not CODE_RE.match(code):
            raise ImportError_(f"Row {line}: business_code {code!r} must be 3-20 letters, numbers or dashes.")
        m = MONTH_RE.match((row["month"] or "").strip())
        if not m or not 1 <= int(m.group(2)) <= 12:
            raise ImportError_(f"Row {line}: month {row['month']!r} should look like 2025-06.")
        month = date(int(m.group(1)), int(m.group(2)), 1)
        if (code, month) in seen:
            raise ImportError_(f"Row {line}: {code} has {month:%Y-%m} twice.")
        seen.add((code, month))
        sector = (row["sector"] or "").strip().lower()
        sector = sector if sector in SECTORS else "other"
        rec = {"month": month}
        for c in REQUIRED[3:]:
            rec[c] = _num(row.get(c), c, line)
        for c in OPTIONAL:
            rec[c] = _num(row.get(c), c, line, integer=c == "transaction_count")
        b = out.setdefault(code, {"sector": sector, "rows": []})
        b["rows"].append(rec)
    if not out:
        raise ImportError_("The file has no rows.")
    return out


def import_text(db: Session, text: str) -> dict:
    from app.models import Business, MonthlyRecord

    data = parse(text)
    existing = set(db.scalars(select(Business.code).where(Business.code.in_(list(data)))).all())
    added = months = 0
    for code, b in data.items():
        if code in existing:
            continue
        rows = sorted(b["rows"], key=lambda r: r["month"])
        biz = Business(code=code, sector=b["sector"], start_date=rows[0]["month"], is_synthetic=True)
        db.add(biz)
        db.flush()
        db.execute(insert(MonthlyRecord), [{"business_id": biz.id, **r} for r in rows])
        added += 1
        months += len(rows)
    db.commit()
    return {"businesses_added": added, "business_months_added": months,
            "skipped_existing": sorted(existing)}


if __name__ == "__main__":
    from app.database import Base, SessionLocal, engine

    ap = argparse.ArgumentParser(description="Import business-months from a CSV for training.")
    ap.add_argument("file")
    a = ap.parse_args()
    Base.metadata.create_all(bind=engine)
    with open(a.file, encoding="utf-8-sig") as f, SessionLocal() as s:
        try:
            r = import_text(s, f.read())
        except ImportError_ as e:
            raise SystemExit(str(e))
    print(f"Added {r['businesses_added']} businesses with {r['business_months_added']} business-months"
          " (marked synthetic). Skipped {len(r['skipped_existing'])} that already existed.")
    print("Now train: venv\\Scripts\\python -m ml.train")
