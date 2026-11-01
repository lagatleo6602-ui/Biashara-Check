"""Biashara Pro: fill in M-Pesa figures from an M-Pesa statement."""
from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import pro, risk
from ..auth import business_for, current_user
from ..contacts import audit
from ..database import get_db
from ..models import MonthlyRecord, User
from ..statements import MAX_BYTES, read_statement

router = APIRouter(prefix="/businesses", tags=["M-Pesa statement (Pro)"])


def _saved_months(db: Session, business_id: int) -> set[str]:
    return {f"{m:%Y-%m}" for m in db.scalars(select(MonthlyRecord.month).where(MonthlyRecord.business_id == business_id))}


@router.post("/{code}/mpesa-statement")
async def preview_statement(code: str, request: Request, file: UploadFile = File(...), password: str = Form(""),
                            db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Reads the statement and shows monthly totals. Nothing is saved until you press Update."""
    b = business_for(code, user, db)
    pro.require_pro(b, user)
    raw = await file.read(MAX_BYTES + 1)
    try:
        result = read_statement(raw, file.filename or "", password)
    except HTTPException:
        raise
    except Exception as exc:  # never show a bare "error 500" for a statement we can't parse
        import logging
        logging.getLogger("uvicorn.error").exception("M-Pesa statement could not be read")
        raise HTTPException(400, "Couldn't read this statement. If it's an M-Pesa PDF, check the password; "
                                 "otherwise try the CSV from the M-Pesa business portal.") from exc
    del raw  # the statement itself is never stored
    saved = _saved_months(db, b.id)
    for m in result["months"]:
        m["saved"] = m["month"] in saved
    audit(db, request, user, "mpesa.statement_read", target=b.code,
          detail=f"{result['transactions']} transactions, {result['from']} to {result['to']} (file not kept)")
    db.commit()
    return result


class MonthIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    received: float = Field(ge=0)
    count: int = Field(ge=0)


class ApplyIn(BaseModel):
    months: list[MonthIn] = Field(min_length=1, max_length=120)


@router.post("/{code}/mpesa-statement/apply")
def apply_statement(code: str, payload: ApplyIn, request: Request, background: BackgroundTasks, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    """Puts M-Pesa received and number of payments into months you've already saved."""
    b = business_for(code, user, db)
    pro.require_pro(b, user)
    this_month = f"{date.today():%Y-%m}"
    updated, missing = [], []
    for m in payload.months:
        if m.month >= this_month:
            continue
        rec = db.scalar(select(MonthlyRecord).where(MonthlyRecord.business_id == b.id,
                                                    MonthlyRecord.month == date.fromisoformat(m.month + "-01")))
        if not rec:
            missing.append(m.month)
            continue
        rec.mobile_money_receipts, rec.transaction_count = round(m.received, 2), m.count
        updated.append(m.month)
    if not updated and not missing:
        raise HTTPException(400, "Pick at least one finished month.")
    if updated:
        audit(db, request, user, "mpesa.statement_applied", target=b.code,
              detail="M-Pesa received and payments count for " + ", ".join(updated))
    db.commit()
    if updated:
        background.add_task(risk.refresh, b.id)
    return {"updated": updated, "missing": missing}
