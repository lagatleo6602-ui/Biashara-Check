from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import business_for, current_user, require_admin
from ..contacts import audit
from ..database import get_db
from ..models import Business, MonthlyRecord, User
from .. import risk
from ..schemas import BusinessCreate, BusinessOut, RecordCreate, RecordOut

router = APIRouter(prefix="/businesses", tags=["businesses"])


@router.post("", response_model=BusinessOut, status_code=201)
def create_business(payload: BusinessCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Admins only. Owners create their business through /auth/register."""
    code = payload.code.strip().upper()
    if db.scalar(select(Business).where(Business.code == code)):
        raise HTTPException(409, "Business code already exists")
    business = Business(**payload.model_dump(exclude={"code"}), code=code)
    db.add(business)
    db.commit()
    db.refresh(business)
    return business


@router.get("", response_model=list[BusinessOut])
def list_businesses(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Admins see every business; an owner sees only their own."""
    query = select(Business).order_by(Business.code)
    if user.role != "admin":
        query = query.where(Business.id == user.business_id)
    return db.scalars(query).all()


@router.post("/{code}/records", response_model=RecordOut, status_code=201)
def add_record(code: str, payload: RecordCreate, request: Request, background: BackgroundTasks,
               db: Session = Depends(get_db), user: User = Depends(current_user)):
    business = business_for(code, user, db)
    exists = db.scalar(
        select(MonthlyRecord).where(
            MonthlyRecord.business_id == business.id, MonthlyRecord.month == payload.month
        )
    )
    if exists:
        raise HTTPException(409, f"Record for {payload.month:%Y-%m} already exists")
    record = MonthlyRecord(business_id=business.id, **payload.model_dump())
    db.add(record)
    audit(db, request, user, "record.added", target=business.code, detail=f"{payload.month:%Y-%m}")
    db.commit()
    db.refresh(record)
    from ..notify import after_month_added
    background.add_task(after_month_added, business.id, record.month)
    return record


@router.get("/{code}/records", response_model=list[RecordOut])
def list_records(code: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return business_for(code, user, db).records


def _month(value: str):
    """Accepts 2025-06 or 2025-06-01."""
    from datetime import date
    try:
        y, m = value[:7].split("-")
        return date(int(y), int(m), 1)
    except ValueError:
        raise HTTPException(400, "Month must look like 2025-06")


def _record(db: Session, business: Business, month) -> MonthlyRecord:
    rec = db.scalar(select(MonthlyRecord).where(MonthlyRecord.business_id == business.id,
                                                MonthlyRecord.month == month))
    if not rec:
        raise HTTPException(404, f"No record for {month:%Y-%m}")
    return rec


@router.put("/{code}/records/{month}", response_model=RecordOut)
def update_record(code: str, month: str, payload: RecordCreate, request: Request, background: BackgroundTasks,
                  db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Fix a month that was typed wrongly. The month itself can't change; delete and re-add for that."""
    business = business_for(code, user, db)
    rec = _record(db, business, _month(month))
    changed = [f for f, v in payload.model_dump(exclude={"month"}).items() if float(getattr(rec, f) or 0) != float(v or 0)]
    for field, value in payload.model_dump(exclude={"month"}).items():
        setattr(rec, field, value)
    audit(db, request, user, "record.edited", target=business.code,
          detail=f"{rec.month:%Y-%m}: " + (", ".join(changed) if changed else "no change"))
    db.commit()
    db.refresh(rec)
    background.add_task(risk.refresh, business.id)
    return rec


@router.delete("/{code}/records/{month}")
def delete_record(code: str, month: str, request: Request, background: BackgroundTasks,
                  db: Session = Depends(get_db), user: User = Depends(current_user)):
    business = business_for(code, user, db)
    m = _month(month)
    db.delete(_record(db, business, m))
    audit(db, request, user, "record.deleted", target=business.code, detail=f"{m:%Y-%m}")
    db.commit()
    background.add_task(risk.refresh, business.id)
    return {"deleted": f"{m:%Y-%m}"}


@router.get("/{code}/records.csv")
def download_my_records(code: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The owner's own figures as a CSV, in the same layout as the upload template."""
    import csv
    import io

    from fastapi.responses import StreamingResponse

    business = business_for(code, user, db)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["month", "revenue", "cogs", "operating_expenses", "cash_inflows", "cash_outflows",
                "mobile_money_receipts", "closing_stock", "outstanding_debt", "transaction_count"])
    for r in business.records:
        w.writerow([f"{r.month:%Y-%m}", r.revenue, r.cogs, r.operating_expenses, r.cash_inflows, r.cash_outflows,
                    r.mobile_money_receipts, r.closing_stock, r.outstanding_debt, r.transaction_count])
    audit(db, request, user, "records.downloaded", target=business.code)
    db.commit()
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{business.code}_records.csv"'})


@router.get("/{code}/risk")
def get_risk(code: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The model's 90-day loss risk for the latest month, with its top reasons (SHAP).
    source = "rules" when no model is trained yet: the dashboard then uses its simple rules."""
    business = business_for(code, user, db)
    lang = user.language or "en"
    r = risk.compute(db, business, lang=lang) if risk.model_ready() else None
    distress = risk.compute_distress(db, business, lang=lang) if risk.model_ready() else None
    if r is None:
        return {"source": "rules", "model_ready": risk.model_ready(), "history": risk.history(db, business),
                "distress": distress}
    risk.save(db, business, r)
    db.commit()
    return {**r, "history": risk.history(db, business), "distress": distress}


@router.get("/{code}/outlook")
def outlook(code: str, months: int = Query(3, ge=1, le=12), db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The risk of at least one loss month over the next 1-12 months (owner's choice), the curve for every
    horizon, the reasons for the chosen one, and how well predictions that far ahead have tested."""
    business = business_for(code, user, db)
    if len(business.records) < 3:
        return {"ready": False, "reason": "few_months", "months_needed": 3 - len(business.records)}
    if not (risk.model_ready() and risk.outlook_ready()):
        return {"ready": False, "reason": "no_model"}
    r = risk.compute_outlook(db, business, months, lang=user.language or "en")
    if r is None:
        return {"ready": False, "reason": "error"}
    return {"ready": True, **r}


@router.get("/{code}/figures")
def figures(code: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Gross profit, margins, cash flow, break-even and the other figures, each with its formula and the
    owner's own numbers worked through; rule-based warning checks; data-integrity checks; and how past
    risk checks for this business turned out."""
    from .. import finance
    business = business_for(code, user, db)
    out = finance.summary(business.records) or {}
    return {**out, "integrity": finance.integrity(db, business), "track_record": risk.track_record(db, business)}


# ---------- PDF reports ----------
def _pdf(data: bytes, filename: str):
    from fastapi.responses import Response
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/{code}/report.pdf")
def monthly_report(code: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Monthly business report: risk check, key figures, charts and the last 12 months."""
    from datetime import date

    from ..reports import monthly_report as build
    business = business_for(code, user, db)
    data = build(db, business)
    audit(db, request, user, "report.downloaded", target=business.code, detail="monthly report")
    db.commit()
    return _pdf(data, f"Biashara-Check-{business.code}-{date.today():%Y-%m}.pdf")


@router.get("/{code}/business-report.pdf")
def business_report(code: str, request: Request, months: int = 12, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    """Biashara Pro: the full business report for a period, with charts of profit, costs, cash, debt,
    M-Pesa and sales, the risk check and its history, highlights and a month-by-month table.
    months = 6, 12, 24, or 0 for every month."""
    from datetime import date

    from .. import pro
    from ..reports import PERIODS, business_report as build
    if months not in PERIODS:
        raise HTTPException(422, "Choose 6, 12 or 24 months, or 0 for all months.")
    business = business_for(code, user, db)
    pro.require_pro(business, user)
    data = build(db, business, months)
    audit(db, request, user, "report.downloaded", target=business.code, detail=f"business report, {PERIODS[months].lower()}")
    db.commit()
    return _pdf(data, f"Business-report-{business.code}-{date.today():%Y-%m-%d}.pdf")


class EmailReportIn(BaseModel):
    kind: Literal["monthly", "business", "loan"]
    months: int = 12


EMAILS_PER_DAY = 10


@router.post("/{code}/reports/email")
def email_report(code: str, payload: EmailReportIn, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    """Sends a report as a PDF to the logged-in user's own confirmed email (never to anyone else)."""
    from datetime import date, timedelta

    from .. import mailer, pro
    from ..auth import utcnow
    from ..contacts import contact_of
    from ..crypto import decrypt
    from ..models import AuditLog
    from ..reports import PERIODS, business_report, loan_report, monthly_report
    business = business_for(code, user, db)
    if payload.kind != "monthly":
        pro.require_pro(business, user)
    if payload.kind == "business" and payload.months not in PERIODS:
        raise HTTPException(422, "Choose 6, 12 or 24 months, or 0 for all months.")
    c = contact_of(db, user)
    if not c or not c.email_verified_at:
        raise HTTPException(400, "Confirm your email first (Account page), then we can send reports to it.")
    sent_today = db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.action == "report.emailed_by_owner", AuditLog.target == business.code,
        AuditLog.at >= utcnow() - timedelta(days=1)))
    if sent_today >= EMAILS_PER_DAY:
        raise HTTPException(429, f"You've emailed {EMAILS_PER_DAY} reports in the last 24 hours. Download it instead, or try tomorrow.")
    if payload.kind == "monthly":
        data, title, name = monthly_report(db, business), "Monthly summary", "Monthly-report"
    elif payload.kind == "business":
        data, title, name = business_report(db, business, payload.months), f"Business report ({PERIODS[payload.months].lower()})", "Business-report"
    else:
        data, title, name = loan_report(db, business), "Summary for lenders", "Summary-for-lenders"
    fname = f"{name}-{business.code}-{date.today():%Y-%m-%d}.pdf"
    body = (f"Hello,\n\nHere is the {title.lower()} for {business.code} that you asked for in Biashara Check. "
            "It's attached as a PDF.\n\nBiashara Check is decision support, not a guarantee. "
            "Your figures are never shared with lenders or anyone else unless you send them yourself.")
    try:
        mailer.send(decrypt(c.email_enc), f"Your Biashara Check {title.lower()}: {business.code}", body,
                    attachments=[(fname, data, "application/pdf")])
    except Exception as exc:
        raise HTTPException(502, "Couldn't send the email just now. Download the report instead, or try again later.") from exc
    audit(db, request, user, "report.emailed_by_owner", target=business.code, detail=title)
    db.commit()
    from ..contacts import mask_email
    return {"sent_to": mask_email(decrypt(c.email_enc)), "mode": mailer.mode()}


@router.get("/{code}/loan-report.pdf")
def loan_report(code: str, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Biashara Pro: a business performance summary to take to a lender, SACCO or supplier."""
    from datetime import date

    from .. import pro
    from ..reports import loan_report as build
    business = business_for(code, user, db)
    pro.require_pro(business, user)
    data = build(db, business)
    audit(db, request, user, "report.downloaded", target=business.code, detail="loan-readiness report")
    db.commit()
    return _pdf(data, f"Business-summary-{business.code}-{date.today():%Y-%m-%d}.pdf")
