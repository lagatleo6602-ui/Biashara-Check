"""CSV upload of monthly records (proposal 1.8: records are entered or uploaded as CSV)."""
import io
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import business_for, current_user
from ..contacts import audit
from ..database import get_db
from ..models import MonthlyRecord, User
from .. import risk
from ..schemas import RecordCreate

router = APIRouter(tags=["csv upload"])

TEMPLATE = Path(__file__).resolve().parents[2] / "data" / "templates" / "sme_records_template.csv"
REQUIRED = ["month", "revenue", "cogs", "operating_expenses", "cash_inflows", "cash_outflows"]
OPTIONAL = ["mobile_money_receipts", "closing_stock", "outstanding_debt", "transaction_count"]
MAX_BYTES = 2 * 1024 * 1024
LABELS = {"month": "month", "revenue": "total sales", "cogs": "cost of goods sold",
          "operating_expenses": "running expenses", "cash_inflows": "money received",
          "cash_outflows": "money paid out", "mobile_money_receipts": "M-Pesa receipts",
          "closing_stock": "stock value", "outstanding_debt": "money owed",
          "transaction_count": "number of sales"}


def _plain(err: dict) -> str:
    kind = err.get("type", "")
    if kind == "missing":
        return "is empty"
    if kind == "greater_than_equal":
        return "can't be negative"
    if kind.startswith(("float", "int")):
        return f"'{err.get('input')}' is not a number"
    if kind == "value_error":
        return err["msg"].replace("Value error, ", "")
    if kind.startswith("date"):
        return f"'{err.get('input')}' is not a month, write it like 2026-01"
    return err["msg"]  # 2 MB is far more than 36 months of records


@router.get("/template.csv", summary="Download the blank CSV template")
def download_template():
    return FileResponse(TEMPLATE, media_type="text/csv", filename="sme_records_template.csv")


# Other names people (and other tools) use for the same columns. Matched after lower-casing, dropping
# anything in brackets such as "(KES)", and turning spaces, dashes and dots into underscores.
ALIASES = {
    "month": ["date", "period", "month_year", "year_month"],
    "revenue": ["sales", "total_sales", "sales_kes", "income", "turnover", "revenue_kes", "total_revenue"],
    "cogs": ["cost_of_goods_sold", "cost_of_goods", "cost_of_sales", "goods_cost", "purchases_sold"],
    "operating_expenses": ["opex", "expenses", "running_expenses", "operating_costs", "running_costs", "overheads"],
    "cash_inflows": ["cash_in", "money_received", "money_in", "inflows", "cash_received"],
    "cash_outflows": ["cash_out", "money_paid_out", "money_out", "outflows", "cash_paid"],
    "mobile_money_receipts": ["mpesa", "m_pesa", "mpesa_receipts", "m_pesa_receipts", "received_by_mpesa", "mobile_money"],
    "closing_stock": ["stock", "stock_value", "inventory", "closing_inventory"],
    "outstanding_debt": ["debt", "money_owed", "loans", "liabilities"],
    "transaction_count": ["transactions", "number_of_sales", "sales_count", "num_sales", "customers"],
}
_ALIAS = {a: col for col, names in ALIASES.items() for a in names}


def _norm_col(c: str) -> str:
    import re
    c = re.sub(r"\(.*?\)|\[.*?\]", "", str(c)).strip().lower()
    c = re.sub(r"[\s\-./]+", "_", c).strip("_")
    return _ALIAS.get(c, c)


def _read_csv(raw: bytes) -> pd.DataFrame:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    first = text.splitlines()[0] if text.strip() else ""
    sep = ";" if first.count(";") > first.count(",") else ","  # Excel in some regions saves with ;
    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, sep=sep, skip_blank_lines=True)
    except Exception as exc:  # unreadable / not a CSV
        raise HTTPException(400, f"Could not read the file as CSV: {exc}") from exc
    found = [str(c).strip() for c in df.columns]
    df.columns = [_norm_col(c) for c in df.columns]
    df = df.dropna(how="all")
    lower = [c.lower() for c in found]
    if any("paid in" in c for c in lower) and any("receipt" in c or "completion" in c for c in lower):
        raise HTTPException(400, "This looks like an M-Pesa statement, not your monthly records. "
                                 "Statements go in the M-Pesa tab.")
    if "business_code" in df.columns and df["business_code"].nunique(dropna=True) > 1:
        raise HTTPException(400, f"This file has figures for {df['business_code'].nunique()} different businesses. "
                                 "Upload a file with one business's months only. (A training file with many "
                                 "businesses goes in Admin, Risk model, Import training CSV.)")
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        shown = ", ".join(found[:12]) + (" ..." if len(found) > 12 else "")
        raise HTTPException(400, f"Missing column(s): {', '.join(missing)}. The file's first row has: {shown}. "
                                 "The first row must hold the column names from the template "
                                 "(month, revenue, cogs, operating_expenses, cash_inflows, cash_outflows). "
                                 "Download the template and copy your figures into it.")
    if df.empty:
        raise HTTPException(400, "The file has no data rows.")
    return df


def _clean_row(row: pd.Series) -> dict:
    data = {}
    for col in REQUIRED + OPTIONAL:
        if col not in row or pd.isna(row[col]) or str(row[col]).strip() == "":
            continue
        value = str(row[col]).strip()
        if col == "month":
            if len(value) == 7:  # "2026-01" -> "2026-01-01"
                value += "-01"
        else:
            value = value.replace(",", "").replace("KES", "").replace("Ksh", "").strip()
        data[col] = value
    return data


@router.post("/businesses/{code}/upload-csv", summary="Upload monthly records from a CSV file")
async def upload_csv(code: str, request: Request, background: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(get_db),
                     user: User = Depends(current_user)):
    business = business_for(code, user, db)
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(400, "Please upload a .csv file (in Excel: File → Save As → CSV UTF-8).")

    raw = await file.read()
    if len(raw) > MAX_BYTES:
        raise HTTPException(400, "File is larger than 2 MB.")
    df = _read_csv(raw)

    # 1. Validate every row first; save nothing if any row is wrong.
    records, errors, seen = [], [], set()
    for i, row in df.iterrows():
        line = i + 2  # +1 for header, +1 because spreadsheets count from 1
        data = _clean_row(row)
        month_key = str(data.get("month", ""))[:7]
        if month_key and month_key in seen:
            errors.append(f"Row {line}: {month_key} appears twice in the file")
            continue
        seen.add(month_key)
        try:
            records.append(RecordCreate(**data))
        except ValidationError as exc:
            for err in exc.errors():
                field = err["loc"][0] if err["loc"] else "row"
                errors.append(f"Row {line}, {LABELS.get(field, field)}: {_plain(err)}")

    if errors:
        raise HTTPException(422, {"message": "Nothing was saved. Fix these rows and upload again.",
                                  "errors": errors[:50]})

    # 2. Skip months already in the database, insert the rest in one transaction.
    existing = set(db.scalars(
        select(MonthlyRecord.month).where(MonthlyRecord.business_id == business.id)
    ).all())
    new = [r for r in records if r.month not in existing]
    skipped = sorted(f"{r.month:%Y-%m}" for r in records if r.month in existing)

    db.add_all(MonthlyRecord(business_id=business.id, **r.model_dump()) for r in new)
    if new:
        audit(db, request, user, "records.uploaded", target=business.code,
              detail=f"{len(new)} months from {file.filename}"[:255])
    db.commit()
    if new:
        from ..notify import after_month_added
        background.add_task(after_month_added, business.id, max(r.month for r in new))

    months = sorted(r.month for r in new)
    return {
        "business": code,
        "inserted": len(new),
        "skipped_existing_months": skipped,
        "first_month": f"{months[0]:%Y-%m}" if months else None,
        "last_month": f"{months[-1]:%Y-%m}" if months else None,
    }


# ---------- any spreadsheet: preview, then import ----------
def _smart(raw: bytes, filename: str, mapping: str | None, business) -> dict:
    import json

    from ..notify import last_full_month
    from ..smart_import import MAX_BYTES as SMART_MAX, parse
    if len(raw) > SMART_MAX:
        raise HTTPException(400, "The file is larger than 5 MB. Split it into smaller files, for example one per year.")
    try:
        mp = json.loads(mapping) if mapping else {}
        if not isinstance(mp, dict):
            mp = {}
    except ValueError:
        mp = {}
    return parse(raw, filename, mapping=mp, own_code=business.code, last_month=last_full_month())


@router.post("/businesses/{code}/import/preview", summary="Read any spreadsheet and show how it would be imported")
async def import_preview(code: str, file: UploadFile = File(...), mapping: str | None = Form(None),
                         db: Session = Depends(get_db), user: User = Depends(current_user)):
    business = business_for(code, user, db)
    out = _smart(await file.read(), file.filename or "", mapping, business)
    existing = {f"{m:%Y-%m}" for m in db.scalars(
        select(MonthlyRecord.month).where(MonthlyRecord.business_id == business.id)).all()}
    for r in out["records"]:
        r["saved"] = r["month"] in existing
    out["new_months"] = sum(not r["saved"] for r in out["records"])
    from ..smart_import import LABELS as FIELD_LABELS
    out["labels"] = FIELD_LABELS
    return out


@router.post("/businesses/{code}/import", summary="Import the months found in any spreadsheet")
async def import_file(code: str, request: Request, background: BackgroundTasks, file: UploadFile = File(...),
                      mapping: str | None = Form(None), replace: bool = Form(False), db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    """replace=true also overwrites months already saved with the file's figures (each change is logged)."""
    business = business_for(code, user, db)
    out = _smart(await file.read(), file.filename or "", mapping, business)
    if out["status"] != "ok":
        raise HTTPException(400, out["message"] or "Choose which column has your sales first.")
    saved = {r.month: r for r in db.scalars(select(MonthlyRecord).where(MonthlyRecord.business_id == business.id)).all()}
    existing = set(saved)
    new, problems, updated = [], [], 0
    for r in out["records"]:
        data = {k: v for k, v in r.items() if k != "saved"}
        data["month"] = data["month"] + "-01"
        try:
            rec = RecordCreate(**data)
        except ValidationError as exc:
            problems.append(f"{r['month']}: {_plain(exc.errors()[0])}")
            continue
        if rec.month not in existing:
            new.append(rec)
        elif replace:
            row = saved[rec.month]
            for k, v in rec.model_dump().items():
                if k != "month":
                    setattr(row, k, v)
            updated += 1
    db.add_all(MonthlyRecord(business_id=business.id, **r.model_dump()) for r in new)
    if new or updated:
        audit(db, request, user, "records.uploaded", target=business.code,
              detail=f"{len(new)} new and {updated} updated months from {file.filename}"[:255])
    db.commit()
    if new:
        from ..notify import after_month_added
        background.add_task(after_month_added, business.id, max(r.month for r in new))
    elif updated:
        background.add_task(risk.refresh, business.id)
    months = sorted(r.month for r in new)
    return {"inserted": len(new), "updated": updated,
            "skipped_existing": len(out["records"]) - len(new) - len(problems) - updated,
            "problems": problems, "first_month": f"{months[0]:%Y-%m}" if months else None,
            "last_month": f"{months[-1]:%Y-%m}" if months else None}
