"""Biashara Pro payments with M-Pesa Express (STK Push)."""
import hmac
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import mpesa, pro
from ..auth import current_user, utcnow
from ..contacts import audit, clean_phone, contact_of, mask_phone
from ..crypto import decrypt, encrypt
from ..database import get_db
from ..models import Business, Payment, User

router = APIRouter(prefix="/payments", tags=["payments"])

GIVE_UP_AFTER = timedelta(hours=24)     # after this, an unconfirmed payment is marked failed
RECHECK_WINDOW = timedelta(days=3)      # how long a payment can be checked again with M-Pesa
CHECK_EVERY = timedelta(seconds=4)


def _own_business(user: User, db: Session) -> Business:
    if user.role != "owner" or not user.business_id:
        raise HTTPException(400, "Only business owners pay for Biashara Pro. Admins already have every feature.")
    return db.get(Business, user.business_id)


def _payment_out(p: Payment) -> dict:
    return {"id": p.id, "plan": p.plan, "amount": p.amount, "phone": p.phone_masked, "mode": p.mode, "kind": p.kind or "new",
            "status": p.status, "message": p.result_desc, "receipt": p.receipt,
            "at": p.created_at.isoformat(timespec="seconds") + "Z"}


def _local(phone: str) -> str:
    return "0" + phone[4:] if phone.startswith("+254") else phone


@router.get("/pro")
def pro_page(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Plan status, prices and recent payments for the owner's business."""
    b = _own_business(user, db)
    c = contact_of(db, user)
    pays = db.scalars(select(Payment).where(Payment.business_id == b.id).order_by(Payment.id.desc()).limit(10)).all()
    return {
        "business": b.code,
        "mode": mpesa.mode(),
        "plans": [{"id": k, **v, "charge": pro.charge_amount(k)} for k, v in pro.plans().items()],
        "features": pro.FEATURES,
        "status": pro.status(b),
        "phone": _local(decrypt(c.phone_enc)) if c else "",
        "payments": [_payment_out(p) for p in pays],
    }


class StkIn(BaseModel):
    plan: Literal["month", "year"]
    phone: str = Field(min_length=9, max_length=20)
    auto_renew: bool = False  # send an M-Pesa prompt for the same plan before Pro ends (approved with the PIN each time)


@router.post("/stk", status_code=201)
def start_payment(payload: StkIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Sends the M-Pesa PIN prompt to the phone."""
    b = _own_business(user, db)
    phone = clean_phone(payload.phone)
    recent = db.scalar(select(Payment).where(Payment.business_id == b.id, Payment.status == "pending",
                                             Payment.created_at > utcnow() - timedelta(seconds=60)))
    if recent:
        raise HTTPException(429, "A payment prompt was sent less than a minute ago. Finish or cancel it on the phone first.")
    amount = pro.charge_amount(payload.plan)
    try:
        r = mpesa.stk_push(phone, amount, account_ref=b.code, description="Biashara Pro")
    except mpesa.MpesaError as exc:
        audit(db, request, user, "payment.failed", target=b.code, detail=str(exc)[:200]); db.commit()
        raise HTTPException(502, str(exc)) from exc
    now = utcnow()
    if payload.auto_renew:
        b.renew_phone_enc = encrypt(phone)
    p = Payment(business_id=b.id, business_code=b.code, username=user.username, plan=payload.plan, amount=amount,
                kind="new", auto_renew=payload.auto_renew,
                phone_masked=mask_phone(phone), mode=mpesa.mode(), checkout_id=r["checkout_id"],
                merchant_request_id=r["merchant_request_id"], status="pending", created_at=now, updated_at=now)
    db.add(p)
    audit(db, request, user, "payment.started", target=b.code,
          detail=f"KES {amount}, {payload.plan}, {mask_phone(phone)} ({p.mode})" + (", renews automatically" if payload.auto_renew else ""))
    db.commit()
    return {**_payment_out(p), "prompt": r["message"]}


def _settle(db: Session, request: Request | None, p: Payment, state: str, desc: str, receipt: str = "",
            actor: str | None = None) -> None:
    if p.status == "paid":
        return
    if state == "pending":
        return
    p.status, p.result_desc, p.updated_at = state, desc[:255], utcnow()
    if receipt:
        p.receipt = receipt[:30]
    b = db.get(Business, p.business_id) if p.business_id else None
    if state == "paid" and pro.apply_payment(b, p):
        audit(db, request, None, "payment.paid", target=p.business_code, actor=actor or p.username,
              detail=f"KES {p.amount}, {p.plan}{', ' + p.receipt if p.receipt else ''} ({p.mode})")
    elif state != "paid":
        audit(db, request, None, "payment.failed", target=p.business_code, actor=actor or p.username, detail=desc[:200])


class RenewIn(BaseModel):
    on: bool
    phone: str | None = Field(default=None, max_length=20)


@router.post("/auto-renew")
def set_auto_renew(payload: RenewIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Cancel (or turn back on) automatic renewal. Cancelling keeps Pro until its end date and stops every
    future M-Pesa prompt; the saved renewal number is deleted."""
    b = _own_business(user, db)
    if not payload.on:
        was = b.auto_renew
        b.auto_renew, b.renew_phone_enc, b.renew_cancelled_at = False, None, utcnow()
        audit(db, request, user, "pro.renewal_cancelled", target=b.code,
              detail=f"Pro stays until {b.pro_until:%Y-%m-%d %H:%M} UTC" if b.pro_until else "no active Pro")
        db.commit()
        return {"status": pro.status(b), "was_on": was}
    if not pro.is_pro(b):
        raise HTTPException(400, "Biashara Pro isn't active. Pay for a plan first, and tick \"Renew automatically\".")
    if not b.pro_plan:
        raise HTTPException(400, "Your Pro was given by the study team, so there is nothing to renew. Pay for a plan when it ends.")
    if payload.phone:
        phone = clean_phone(payload.phone)
    elif b.renew_phone_enc:
        phone = decrypt(b.renew_phone_enc)
    else:
        c = contact_of(db, user)
        if not c:
            raise HTTPException(400, "Enter the M-Pesa number to send renewal prompts to.")
        phone = decrypt(c.phone_enc)
    b.auto_renew, b.renew_phone_enc, b.renew_cancelled_at = True, encrypt(phone), None
    audit(db, request, user, "pro.renewal_on", target=b.code, detail=f"{b.pro_plan}, {mask_phone(phone)}")
    db.commit()
    return {"status": pro.status(b)}


@router.get("/{payment_id}")
def payment_status(payment_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The page polls this while the owner enters their PIN. We ask Daraja for the result."""
    p = db.get(Payment, payment_id)
    if not p or (user.role != "admin" and p.business_id != user.business_id):
        raise HTTPException(404, "Payment not found")
    now = utcnow()
    if p.status == "pending" and (not p.last_checked or now - p.last_checked >= CHECK_EVERY):
        p.last_checked = now
        try:
            res = mpesa.stk_query(p.checkout_id)
        except mpesa.MpesaError as exc:
            res = {"state": "pending", "desc": str(exc)}
        _settle(db, request, p, res["state"], res["desc"])
        if p.status == "pending" and now - p.created_at > GIVE_UP_AFTER:
            _settle(db, request, p, "failed", "M-Pesa never confirmed this payment. If money left your M-Pesa, "
                                              "keep the M-Pesa message and contact the study team.")
        db.commit()
    b = db.get(Business, p.business_id) if p.business_id else None
    return {**_payment_out(p), "pro": pro.status(b) if b else None}


@router.post("/{payment_id}/check")
def check_again(payment_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Asks M-Pesa again about a payment that is waiting or was marked as not gone through.
    If M-Pesa now says it was paid, Pro is switched on."""
    p = db.get(Payment, payment_id)
    if not p or (user.role != "admin" and p.business_id != user.business_id):
        raise HTTPException(404, "Payment not found")
    if p.status != "paid":
        if utcnow() - p.created_at > RECHECK_WINDOW:
            raise HTTPException(400, "This payment is too old to check with M-Pesa. Contact the study team with your M-Pesa message.")
        try:
            res = mpesa.stk_query(p.checkout_id)
        except mpesa.MpesaError as exc:
            raise HTTPException(502, str(exc)) from exc
        p.last_checked = utcnow()
        if res["state"] == "paid":
            p.status = "pending"  # allow _settle to overrule an earlier failure
            _settle(db, request, p, "paid", res["desc"], actor=user.username)
        elif res["state"] == "pending":
            p.status, p.result_desc, p.updated_at = "pending", res["desc"], utcnow()
        elif p.status == "pending":
            _settle(db, request, p, res["state"], res["desc"], actor=user.username)
        audit(db, request, user, "payment.checked", target=p.business_code, detail=f"#{p.id}: {p.status}")
        db.commit()
    b = db.get(Business, p.business_id) if p.business_id else None
    return {**_payment_out(p), "pro": pro.status(b) if b else None}


@router.get("/mpesa/callback/{secret}", include_in_schema=False)
def mpesa_callback_ping(secret: str):
    """Lets the admin page check that Safaricom can reach this address (e.g. through ngrok)."""
    if not hmac.compare_digest(secret, mpesa.callback_secret()):
        raise HTTPException(404)
    return {"ok": True, "service": "biashara-check-mpesa-callback"}


@router.post("/mpesa/callback/{secret}", include_in_schema=False)
async def mpesa_callback(secret: str, request: Request, db: Session = Depends(get_db)):
    """Safaricom posts the final result here (only if MPESA_CALLBACK_URL is set)."""
    if not hmac.compare_digest(secret, mpesa.callback_secret()):
        raise HTTPException(404)
    try:
        cb = (await request.json())["Body"]["stkCallback"]
    except Exception:
        return {"ResultCode": 1, "ResultDesc": "Bad payload"}
    p = db.scalar(select(Payment).where(Payment.checkout_id == str(cb.get("CheckoutRequestID", ""))))
    if not p:
        return {"ResultCode": 0, "ResultDesc": "Accepted"}  # not ours; acknowledge so Safaricom stops retrying
    res = mpesa.result(str(cb.get("ResultCode")), cb.get("ResultDesc", ""))
    audit(db, request, None, "payment.callback", target=p.business_code, actor="M-Pesa",
          detail=f"#{p.id}: result {cb.get('ResultCode')} ({res['state']})")
    items = {i.get("Name"): i.get("Value") for i in (cb.get("CallbackMetadata") or {}).get("Item", [])}
    if res["state"] == "paid" and int(float(items.get("Amount", 0) or 0)) != p.amount:
        res = {"state": "failed", "desc": f"Amount paid ({items.get('Amount')}) doesn't match KES {p.amount}. Contact the study team."}
    if p.status == "paid" and items.get("MpesaReceiptNumber") and not p.receipt:
        p.receipt = str(items["MpesaReceiptNumber"])[:30]
    if p.status != "paid":
        p.status = "pending"  # a late success can still overrule an earlier "no answer"
        _settle(db, request, p, res["state"], res["desc"], str(items.get("MpesaReceiptNumber", "")), actor="M-Pesa")
    db.commit()
    return {"ResultCode": 0, "ResultDesc": "Accepted"}
