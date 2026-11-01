"""Researcher / admin tools: overview, accounts, data export."""
import csv
import io
from datetime import date
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..auth import hash_password, require_admin, temp_password, utcnow
from ..contacts import audit, clean_email, clean_phone, contact_of, contact_summary, save_contact
from .. import mpesa, pro
from ..database import get_db
from ..sectors import SECTORS, Sector
from ..erase import anonymise_activity, erase_business
from ..models import AuditLog, Business, Contact, LoginSession, MonthlyRecord, OneTimeCode, Prediction, User

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _net(r: MonthlyRecord) -> float:
    return float(r.revenue) - float(r.cogs) - float(r.operating_expenses)


def _owner(db: Session, business_id: int) -> User | None:
    return db.scalar(select(User).where(User.business_id == business_id, User.role == "owner"))


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    businesses = db.scalars(select(Business)).all()
    records = db.scalars(select(MonthlyRecord)).all()
    real = [r for r in records if not r.business.is_synthetic]
    by_sector = {s: n for s in SECTORS if (n := sum(1 for b in businesses if b.sector == s))}
    return {
        "businesses": len(businesses),
        "with_login": db.scalar(select(func.count()).select_from(User).where(User.role == "owner")),
        "business_months": len(records),
        "real_business_months": len(real),
        "synthetic_business_months": len(records) - len(real),
        "loss_months": sum(1 for r in records if _net(r) < 0),
        "target_business_months": 1500,  # proposal objective 2
        "by_sector": by_sector,
    }


@router.get("/businesses")
def businesses(db: Session = Depends(get_db)):
    rows = []
    for b in db.scalars(select(Business).order_by(Business.code)).all():
        recs = b.records
        owner = _owner(db, b.id)
        rows.append({
            "code": b.code,
            "sector": b.sector,
            "is_synthetic": b.is_synthetic,
            "months": len(recs),
            "first_month": f"{recs[0].month:%Y-%m}" if recs else None,
            "last_month": f"{recs[-1].month:%Y-%m}" if recs else None,
            "loss_months": sum(1 for r in recs if _net(r) < 0),
            "pro": pro.status(b),
            "contact": contact_summary(contact_of(db, owner)) if owner else None,
            "account": None if not owner else {
                "active": owner.is_active,
                "consent": owner.consent_at.isoformat(timespec="minutes") if owner.consent_at else None,
                "last_login": owner.last_login.isoformat(timespec="minutes") if owner.last_login else None,
            },
        })
    return rows


class AdminBusinessIn(BaseModel):
    code: str = Field(min_length=3, max_length=20, pattern=r"^[A-Za-z0-9-]+$")
    sector: Sector
    start_date: date | None = None
    is_synthetic: bool = False
    create_login: bool = True
    email: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=20)


@router.post("/businesses", status_code=201)
def create_business(payload: AdminBusinessIn, request: Request, db: Session = Depends(get_db),
                    admin: User = Depends(require_admin)):
    """Use this when you sign up a business in person after taking written consent."""
    code = payload.code.strip().upper()
    if db.scalar(select(Business).where(Business.code == code)):
        raise HTTPException(409, "That business code is taken.")
    b = Business(code=code, sector=payload.sector, start_date=payload.start_date, is_synthetic=payload.is_synthetic)
    db.add(b)
    db.flush()
    password = None
    email = clean_email(payload.email) if payload.email else None
    phone = clean_phone(payload.phone) if payload.phone else None
    if bool(email) != bool(phone):
        raise HTTPException(422, "Give both email and phone, or leave both empty for the owner to add later.")
    if payload.create_login and not payload.is_synthetic:
        password = temp_password()
        owner = User(username=code.lower(), password_hash=hash_password(password), role="owner",
                     business_id=b.id, must_change_password=True)
        db.add(owner)
        db.flush()
        if email:
            save_contact(db, owner, email, phone, consent=True)  # consent taken on the paper form
    audit(db, request, admin, "business.created", target=code, detail="synthetic" if payload.is_synthetic else "")
    db.commit()
    return {"code": code, "temporary_password": password}


@router.post("/businesses/{code}/password")
def reset_password(code: str, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Creates a login if the business has none, otherwise resets it. Logs the owner out everywhere."""
    b = db.scalar(select(Business).where(Business.code == code))
    if not b:
        raise HTTPException(404, "Business not found")
    if b.is_synthetic:
        raise HTTPException(400, "Synthetic businesses don't have logins.")
    password = temp_password()
    owner = _owner(db, b.id)
    if owner:
        owner.password_hash = hash_password(password)
        owner.is_active = True
        owner.must_change_password = True
        db.execute(delete(LoginSession).where(LoginSession.user_id == owner.id))
    else:
        db.add(User(username=code.lower(), password_hash=hash_password(password), role="owner",
                    business_id=b.id, must_change_password=True))
    audit(db, request, admin, "admin.password_reset", target=code)
    db.commit()
    return {"code": code, "temporary_password": password}


class ActiveIn(BaseModel):
    active: bool


@router.post("/businesses/{code}/active")
def set_active(code: str, payload: ActiveIn, request: Request, db: Session = Depends(get_db),
               admin: User = Depends(require_admin)):
    b = db.scalar(select(Business).where(Business.code == code))
    owner = _owner(db, b.id) if b else None
    if not owner:
        raise HTTPException(404, "This business has no login.")
    owner.is_active = payload.active
    if not payload.active:
        db.execute(delete(LoginSession).where(LoginSession.user_id == owner.id))
    audit(db, request, admin, "admin.login_switched_" + ("on" if payload.active else "off"), target=code)
    db.commit()
    return {"code": code, "active": owner.is_active}


@router.delete("/businesses/{code}")
def delete_business(code: str, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Removes the business, its records, predictions and login (Data Protection Act: right to erasure)."""
    b = db.scalar(select(Business).where(Business.code == code))
    if not b:
        raise HTTPException(404, "Business not found")
    erase_business(db, b)
    anonymise_activity(db, code)
    audit(db, request, admin, "business.deleted", target=code, detail="all records, login and contact details erased")
    db.commit()
    return {"deleted": code}


@router.get("/export.csv")
def export_csv(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Every business-month in one file, ready for the ML notebooks. No personal data included."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["business_code", "sector", "is_synthetic", "month", "revenue", "cogs", "operating_expenses",
                "cash_inflows", "cash_outflows", "mobile_money_receipts", "closing_stock",
                "outstanding_debt", "transaction_count", "net_operating_result"])
    for b in db.scalars(select(Business).order_by(Business.code)).all():
        for r in b.records:
            w.writerow([b.code, b.sector, int(b.is_synthetic), f"{r.month:%Y-%m}", r.revenue, r.cogs,
                        r.operating_expenses, r.cash_inflows, r.cash_outflows, r.mobile_money_receipts,
                        r.closing_stock, r.outstanding_debt, r.transaction_count, round(_net(r), 2)])
    audit(db, request, admin, "data.exported", detail="business-months CSV, no contact details")
    db.commit()
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="sme_business_months.csv"'})


# ---------- contact details & accountability ----------
def _owner_contact(db: Session, code: str) -> tuple[User, Contact]:
    b = db.scalar(select(Business).where(Business.code == code))
    owner = _owner(db, b.id) if b else None
    c = contact_of(db, owner) if owner else None
    if not c:
        raise HTTPException(404, "This business has no contact details yet.")
    return owner, c


@router.post("/businesses/{code}/contact/reveal")
def reveal_contact(code: str, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Shows the full email and phone. Every view is written to the activity log."""
    _, c = _owner_contact(db, code)
    audit(db, request, admin, "contact.viewed", target=code)
    db.commit()
    return contact_summary(c, full=True)


class PhoneVerifiedIn(BaseModel):
    verified: bool = True


@router.post("/businesses/{code}/contact/phone-verified")
def mark_phone(code: str, payload: PhoneVerifiedIn, request: Request, db: Session = Depends(get_db),
               admin: User = Depends(require_admin)):
    """After calling the owner on that number, an admin confirms it is theirs."""
    _, c = _owner_contact(db, code)
    c.phone_verified_at = utcnow() if payload.verified else None
    audit(db, request, admin, "phone." + ("verified" if payload.verified else "unverified"), target=code)
    db.commit()
    return contact_summary(c)


@router.get("/activity")
def activity(limit: int = 100, action: str = "", target: str = "", db: Session = Depends(get_db)):
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(max(1, min(limit, 500)))
    if action:
        q = q.where(AuditLog.action.like(action.strip() + "%"))
    if target:
        q = q.where(AuditLog.target.like("%" + target.strip().upper() + "%") | AuditLog.target.like("%" + target.strip().lower() + "%"))
    return [{"at": a.at.isoformat(timespec="seconds") + "Z", "actor": a.actor, "role": a.actor_role,
             "action": a.action, "target": a.target, "detail": a.detail, "ip": a.ip}
            for a in db.scalars(q).all()]


# ---------- messaging: is email/SMS live, and send a test ----------
import os  # noqa: E402

from .. import mailer, sms  # noqa: E402


@router.get("/messaging")
def messaging_status():
    return {
        "email": {"mode": mailer.mode(), "from": os.getenv("MAIL_FROM") or os.getenv("SMTP_USER") or "",
                  "host": os.getenv("SMTP_HOST", "")},
        "sms": {"mode": sms.mode(), "provider": sms.provider(), "username": os.getenv("AT_USERNAME", ""),
                "sender_id": os.getenv("AT_SENDER_ID", "")},
    }


class TestMessageIn(BaseModel):
    channel: Literal["email", "sms"]
    to: str = Field(min_length=3, max_length=120)


@router.post("/messaging/test")
def messaging_test(payload: TestMessageIn, request: Request, db: Session = Depends(get_db),
                   admin: User = Depends(require_admin)):
    """Sends one test message so you can see email or SMS really arrives."""
    if payload.channel == "email":
        to = clean_email(payload.to)
        try:
            mailer.send(to, "Biashara Check test email",
                        "This is a test from Biashara Check. If you can read this, email sending works.\n")
        except mailer.MailError as exc:
            raise HTTPException(502, str(exc)) from exc
        mode = mailer.mode()
    else:
        to = clean_phone(payload.to)
        try:
            sms.send(to, "Biashara Check test SMS. If you can read this, SMS sending works.")
        except sms.SmsError as exc:
            raise HTTPException(502, str(exc)) from exc
        mode = sms.mode()
    audit(db, request, admin, "messaging.test", target=payload.channel, detail=f"to {to[:4]}••• ({mode})")
    db.commit()
    where = {"live": "Sent for real.", "sandbox": "Sent to the Africa's Talking sandbox: open the simulator to see it.",
             "console": "Not sent: no settings yet, so it was printed in the server window."}[mode]
    return {"ok": True, "mode": mode, "message": where}


# ---------- admins, super admin and one-time admin codes ----------
from ..auth import verify_password  # noqa: E402
from ..invites import (INVITE_HOURS, active_invite, cancel_open, create_invite,  # noqa: E402
                       ensure_super_admin, require_super_admin)
from ..models import AdminInvite  # noqa: E402


def _iso(dt) -> str | None:
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


@router.get("/admins")
def admins(db: Session = Depends(get_db), me: User = Depends(require_admin)):
    rows = db.scalars(select(User).where(User.role == "admin").order_by(User.id)).all()
    return {
        "me": me.username,
        "i_am_super": bool(me.is_super_admin),
        "admins": [{"username": u.username, "is_super_admin": bool(u.is_super_admin), "active": u.is_active,
                    "last_login": _iso(u.last_login), "created_at": _iso(u.created_at),
                    "contact": contact_summary(contact_of(db, u))} for u in rows],
    }


def _invite_status(db: Session) -> dict:
    inv = active_invite(db)
    last_used = db.scalar(select(AdminInvite).where(AdminInvite.used_at.is_not(None)).order_by(AdminInvite.used_at.desc()))
    return {
        "hours": INVITE_HOURS,
        "active": None if not inv else {"created_at": _iso(inv.created_at), "expires_at": _iso(inv.expires_at),
                                        "created_by": inv.created_by},
        "last_used": None if not last_used else {"used_by": last_used.used_by, "used_at": _iso(last_used.used_at)},
    }


@router.get("/invite")
def invite_status(db: Session = Depends(get_db), _: User = Depends(require_super_admin)):
    """Is there an unused admin code? The code itself is never shown again after it's generated."""
    return _invite_status(db)


@router.post("/invite", status_code=201)
def new_invite(request: Request, db: Session = Depends(get_db), boss: User = Depends(require_super_admin)):
    """Generates a fresh random admin code. Any older unused code stops working."""
    code, inv = create_invite(db, boss)
    audit(db, request, boss, "admin.invite_created", detail=f"valid {INVITE_HOURS}h, older unused code cancelled")
    db.commit()
    return {"code": code, "expires_at": _iso(inv.expires_at), "hours": INVITE_HOURS}


@router.delete("/invite")
def cancel_invite(request: Request, db: Session = Depends(get_db), boss: User = Depends(require_super_admin)):
    n = cancel_open(db)
    if n:
        audit(db, request, boss, "admin.invite_cancelled")
    db.commit()
    return {"cancelled": n, **_invite_status(db)}


def _other_admin(db: Session, username: str, boss: User) -> User:
    u = db.scalar(select(User).where(User.role == "admin", func.lower(User.username) == username.strip().lower()))
    if not u:
        raise HTTPException(404, "No admin with that username.")
    if u.id == boss.id:
        raise HTTPException(400, "You can't do that to your own account.")
    return u


@router.post("/admins/{username}/active")
def set_admin_active(username: str, payload: ActiveIn, request: Request, db: Session = Depends(get_db),
                     boss: User = Depends(require_super_admin)):
    """The super admin switches another admin's login off (e.g. a team member who left) or back on."""
    u = _other_admin(db, username, boss)
    u.is_active = payload.active
    if not payload.active:
        db.execute(delete(LoginSession).where(LoginSession.user_id == u.id))
    audit(db, request, boss, "admin.admin_switched_" + ("on" if payload.active else "off"), target=u.username)
    db.commit()
    return {"username": u.username, "active": u.is_active}


class HandOverIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)


@router.post("/admins/{username}/make-super")
def hand_over(username: str, payload: HandOverIn, request: Request, db: Session = Depends(get_db),
              boss: User = Depends(require_super_admin)):
    """Hands the super admin role to another active admin. Needs your password."""
    boss = db.merge(boss)
    if not verify_password(payload.password, boss.password_hash):
        raise HTTPException(400, "Your password is wrong.")
    u = _other_admin(db, username, boss)
    if not u.is_active:
        raise HTTPException(400, "Switch that admin's login on first.")
    boss.is_super_admin = False
    u.is_super_admin = True
    cancel_open(db)  # codes you made shouldn't outlive your role
    db.flush()
    ensure_super_admin(db)
    audit(db, request, boss, "admin.super_handed_over", target=u.username)
    db.commit()
    return {"super_admin": u.username}


# ---------- Biashara Pro and M-Pesa payments ----------
from ..models import Payment  # noqa: E402


@router.get("/payments")
def payments(db: Session = Depends(get_db)):
    rows = db.scalars(select(Payment).order_by(Payment.id.desc()).limit(100)).all()
    paid = [p for p in rows if p.status == "paid"]
    return {
        "mode": mpesa.mode(),
        "shortcode": mpesa.shortcode(),
        "till": mpesa.till(),
        "callback": _callback_info(db),
        "plans": pro.plans(),
        "pro_businesses": sum(1 for b in db.scalars(select(Business)).all() if pro.is_pro(b)),
        "paid_total": sum(p.amount for p in paid if p.mode != "test"),
        "payments": [{"id": p.id, "business": p.business_code if p.business_id else p.business_code + " (deleted)",
                      "plan": p.plan, "amount": p.amount, "phone": p.phone_masked, "mode": p.mode,
                      "status": p.status, "message": p.result_desc, "receipt": p.receipt,
                      "at": p.created_at.isoformat(timespec="seconds") + "Z"} for p in rows],
    }


def _callback_info(db: Session) -> dict:
    base, source = mpesa.callback_base()
    last = db.scalar(select(AuditLog).where(AuditLog.action == "payment.callback").order_by(AuditLog.id.desc()))
    return {"url": base, "source": source,
            "last_received": last.at.isoformat(timespec="seconds") + "Z" if last else None}


@router.post("/mpesa/callback-test")
def callback_test(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Calls our own public callback address from outside-in (through ngrok), the way Safaricom will."""
    import httpx
    base, source = mpesa.callback_base()
    if not base:
        return {"ok": False, "message": "No public address yet. Start ngrok (ngrok http 127.0.0.1:8000) or set MPESA_CALLBACK_URL "
                                        "in .env. Payments still work: the app asks M-Pesa for the result instead."}
    if not base.startswith("https://"):
        return {"ok": False, "message": f"{base} isn't https. Safaricom only calls https addresses."}
    try:
        r = httpx.get(base + mpesa.CALLBACK_PATH + mpesa.callback_secret(), timeout=15,
                      headers={"ngrok-skip-browser-warning": "1", "User-Agent": "BiasharaCheck-callback-test"})
        ok = r.status_code == 200 and r.json().get("service") == "biashara-check-mpesa-callback"
    except Exception as exc:
        ok, r = False, None
        detail = exc.__class__.__name__
    else:
        detail = f"HTTP {r.status_code}"
    audit(db, request, admin, "mpesa.callback_tested", detail=("ok " if ok else "failed ") + f"({source})")
    db.commit()
    if ok:
        return {"ok": True, "message": f"Safaricom can reach this app at {base} ({'found automatically from ngrok' if source == 'ngrok' else 'from .env'}). "
                                       "Payment results and M-Pesa receipt numbers will now arrive by themselves."}
    hint = " Is ngrok still running, and pointing at port 8000?" if source == "ngrok" else \
           " Check MPESA_CALLBACK_URL in .env matches your ngrok address, and that ngrok is running."
    return {"ok": False, "message": f"Couldn't reach {base} ({detail}).{hint}"}


@router.post("/mpesa/check")
def mpesa_check(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Logs in to Daraja with the .env keys. Nothing is charged."""
    r = mpesa.check_connection()
    audit(db, request, admin, "mpesa.checked", detail=("ok" if r["ok"] else "failed") + f" ({r['mode']})")
    db.commit()
    return r


class ProIn(BaseModel):
    days: int = Field(ge=0, le=730)  # 0 switches Pro off


@router.post("/businesses/{code}/pro")
def give_pro(code: str, payload: ProIn, request: Request, db: Session = Depends(get_db),
             admin: User = Depends(require_admin)):
    """Study participants get Pro free: an admin adds days (or 0 to switch it off)."""
    b = db.scalar(select(Business).where(Business.code == code))
    if not b:
        raise HTTPException(404, "Business not found")
    if payload.days:
        pro.extend(b, payload.days, "admin")
        audit(db, request, admin, "pro.given", target=code, detail=f"{payload.days} days free")
    else:
        b.pro_until, b.pro_source = None, None
        audit(db, request, admin, "pro.removed", target=code)
    db.commit()
    return {"code": code, "pro": pro.status(b)}


# ---------- risk model: synthetic data, training, evaluation ----------
def _data_summary(db: Session) -> dict:
    rows = db.execute(select(Business.is_synthetic, func.count(MonthlyRecord.id))
                      .join(MonthlyRecord, MonthlyRecord.business_id == Business.id)
                      .group_by(Business.is_synthetic)).all()
    counts = {bool(k): int(v) for k, v in rows}
    return {"real_months": counts.get(False, 0), "synthetic_months": counts.get(True, 0),
            "synthetic_businesses": db.scalar(select(func.count()).select_from(Business).where(Business.is_synthetic.is_(True)))}


@router.get("/model")
def model_status(db: Session = Depends(get_db)):
    from .. import risk
    meta = None
    if risk.model_ready():
        from ml.train import load
        _, meta = load()
        meta = {k: v for k, v in (meta or {}).items() if k != "background"}
        from ml.predict import friendly
        for item in meta.get("importance", []):
            item["name"] = friendly(item["feature"])
    try:
        import ml.train  # noqa: F401  (are the ML libraries installed?)
        libs = True
    except Exception:
        libs = False
    return {"ready": meta is not None, "libraries": libs, "meta": meta, "data": _data_summary(db)}


class TrainIn(BaseModel):
    real_only: bool = False


@router.post("/model/train")
def model_train(payload: TrainIn, request: Request, background: BackgroundTasks, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    """Trains and compares the four models, keeps the best, then re-scores every business."""
    try:
        from ml.train import NotEnoughData, train
    except Exception as exc:
        raise HTTPException(503, "The machine-learning libraries aren't installed. Run: venv\\Scripts\\pip install -r requirements.txt") from exc
    try:
        meta = train(db, real_only=payload.real_only)
    except NotEnoughData as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(db, request, admin, "model.trained",
          detail=f"{meta['best_name']} {meta['version']}, PR-AUC {meta['models'][meta['best']]['pr_auc']}, "
                 f"{meta['rows']['labelled']} rows{' (real only)' if payload.real_only else ''}")
    db.commit()
    background.add_task(_rescore_all)
    return meta


def _rescore_all() -> None:
    """New model: save a fresh prediction for every real business (no alerts for a model change).
    Synthetic businesses are left out: there can be thousands, and their risk is worked out when opened."""
    from .. import risk
    from ..database import SessionLocal
    with SessionLocal() as db:
        for b in db.scalars(select(Business).where(Business.is_synthetic.is_(False))).all():
            r = risk.compute(db, b)
            if r:
                risk.save(db, b, r)
        db.commit()


class SyntheticIn(BaseModel):
    businesses: int = Field(ge=1, le=300)


@router.post("/synthetic")
def synthetic_add(payload: SyntheticIn, request: Request, db: Session = Depends(get_db),
                  admin: User = Depends(require_admin)):
    from ml.synthetic import generate
    out = generate(db, payload.businesses)
    audit(db, request, admin, "synthetic.generated",
          detail=f"{out['businesses']} businesses, {out['business_months']} months, loss rate {out['loss_rate']}")
    db.commit()
    return out


@router.post("/training-csv")
async def training_csv(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                       admin: User = Depends(require_admin)):
    """Adds synthetic businesses from a CSV (the layout of Download all records) for training."""
    from ml.import_csv import ImportError_, import_text
    raw = await file.read(30 * 1024 * 1024 + 1)
    if len(raw) > 30 * 1024 * 1024:
        raise HTTPException(413, "The file is larger than 30 MB. Split it into smaller files.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "Save the file as CSV UTF-8 and try again.")
    try:
        out = import_text(db, text)
    except ImportError_ as e:
        raise HTTPException(400, str(e))
    audit(db, request, admin, "synthetic.imported",
          detail=f"{out['businesses_added']} businesses, {out['business_months_added']} months from {file.filename}"[:250])
    db.commit()
    return out


@router.delete("/synthetic")
def synthetic_remove(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    from ml.synthetic import remove_all
    n = remove_all(db)
    audit(db, request, admin, "synthetic.removed", detail=f"{n} businesses")
    db.commit()
    return {"removed": n}


@router.get("/study-report.pdf")
def study_report_pdf(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Study progress, data quality, participants and model results, as one PDF."""
    from fastapi.responses import Response

    from ..reports import study_report
    data = study_report(db)
    audit(db, request, admin, "report.downloaded", detail="study report")
    db.commit()
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="Biashara-Check-study-report-{date.today():%Y-%m-%d}.pdf"'})


@router.post("/renewals/run")
def renewals_now(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Runs the Biashara Pro renewal check now (it also runs by itself every 30 minutes)."""
    from ..renewals import process
    out = process(db)
    audit(db, request, admin, "renewals.run", detail=f"{out['notices']} notices, {out['prompts']} prompts, {out['settled']} settled")
    db.commit()
    return out


@router.post("/reminders/send")
def reminders_now(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Reminds every owner who hasn't added last month yet (never twice in a month)."""
    from ..notify import send_reminders
    out = send_reminders(db)
    audit(db, request, admin, "reminders.run", detail=f"{out['month']}: {out['emails']} emails, {out['sms']} SMS")
    db.commit()
    return out
