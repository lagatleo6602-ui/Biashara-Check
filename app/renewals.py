"""Automatic renewal of Biashara Pro.

M-Pesa can't take money without the owner's PIN, so "automatic" renewal means: a day before Pro ends, the
app sends the owner an M-Pesa prompt for the same plan. Nothing is paid unless they enter their PIN.
Three days before, they get an email or SMS saying when and how much, and how to cancel.
Cancelling (Account > Biashara Pro) stops all of this; Pro still runs to its end date.

process(db) runs every 30 minutes inside the app (renew_loop), and can be run by hand from the admin page.
Switch it off with RENEWALS=off in .env.
"""
import asyncio
import logging
import os
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import mailer, mpesa, pro, sms
from .auth import utcnow
from .contacts import audit, contact_of, mask_phone
from .crypto import decrypt
from .models import Business, Payment, User

log = logging.getLogger("uvicorn.error")
EAT = timedelta(hours=3)


def _when(dt) -> str:
    return (dt + EAT).strftime("%a %d %b %Y, %H:%M") + " (Nairobi time)"


def _owner(db: Session, b: Business) -> User | None:
    return db.scalar(select(User).where(User.business_id == b.id, User.role == "owner"))


def _tell(db: Session, b: Business, subject: str, text: str, sms_text: str) -> list[str]:
    o = _owner(db, b)
    c = contact_of(db, o) if o else None
    sent = []
    if c and c.email_verified_at:
        try:
            mailer.send(decrypt(c.email_enc), subject, text)
            sent.append("email")
        except Exception:
            log.exception("Renewal email failed for %s", b.code)
    if c and c.phone_verified_at:
        try:
            sms.send(decrypt(c.phone_enc), sms_text[:300])
            sent.append("SMS")
        except Exception:
            log.exception("Renewal SMS failed for %s", b.code)
    return sent


def process(db: Session) -> dict:
    """Sends due notices and renewal prompts, and settles renewal payments M-Pesa has answered."""
    from .routers.payments import GIVE_UP_AFTER, _settle
    now = utcnow()
    out = {"notices": 0, "prompts": 0, "settled": 0}

    # 1. renewal prompts already sent: ask M-Pesa how they went (nobody is on the page polling for them)
    for p in db.scalars(select(Payment).where(Payment.kind == "renewal", Payment.status == "pending")).all():
        try:
            res = mpesa.stk_query(p.checkout_id)
        except mpesa.MpesaError as exc:
            res = {"state": "pending", "desc": str(exc)}
        _settle(db, None, p, res["state"], res["desc"], actor="M-Pesa")
        if p.status == "pending" and now - p.created_at > GIVE_UP_AFTER:
            _settle(db, None, p, "failed", "No answer to the renewal prompt.", actor="M-Pesa")
        if p.status != "pending":
            out["settled"] += 1
            b = db.get(Business, p.business_id) if p.business_id else None
            if b and p.status != "paid":
                _tell(db, b, "Biashara Pro didn't renew",
                      f"Hello,\n\nThe M-Pesa prompt to renew Biashara Pro for {b.code} wasn't paid ({p.result_desc}). "
                      f"Pro ends {_when(b.pro_until)}. You can pay any time on the Account page, Biashara Pro tab.",
                      f"Biashara Check: Pro for {b.code} didn't renew. It ends {_when(b.pro_until)}. Pay on the Account page.")
    db.commit()

    due = db.scalars(select(Business).where(Business.auto_renew.is_(True), Business.pro_until.is_not(None),
                                            Business.pro_until > now)).all()
    for b in due:
        if not b.pro_plan or not b.renew_phone_enc:
            continue
        left = b.pro_until - now
        price = pro.charge_amount(b.pro_plan)
        name = pro.plans()[b.pro_plan]["name"]
        # 2. three days before: say when, how much, and how to cancel
        if left <= pro.RENEW_NOTICE_BEFORE and b.renew_notice_for != b.pro_until:
            b.renew_notice_for = b.pro_until
            sent = _tell(db, b, "Biashara Pro renews soon",
                         f"Hello,\n\nBiashara Pro for {b.code} ends {_when(b.pro_until)}. About a day before, we'll send an "
                         f"M-Pesa prompt for KES {price} ({name}) to {mask_phone(decrypt(b.renew_phone_enc))}. "
                         "Nothing is paid unless you enter your M-Pesa PIN.\n\nDon't want to renew? Cancel any time on the "
                         "Account page, Biashara Pro tab. Pro keeps working until its end date.",
                         f"Biashara Check: Pro for {b.code} renews around {(b.pro_until + EAT):%d %b}. You'll get an M-Pesa "
                         f"prompt for KES {price}. To cancel: Account > Biashara Pro.")
            audit(db, None, None, "pro.renewal_notice", target=b.code, actor="Biashara Check",
                  detail=", ".join(sent) or "no confirmed contact")
            out["notices"] += 1
        # 3. a day before: the M-Pesa prompt for the same plan
        if left <= pro.RENEW_PROMPT_BEFORE and b.renew_tried_for != b.pro_until:
            b.renew_tried_for = b.pro_until
            phone = decrypt(b.renew_phone_enc)
            try:
                r = mpesa.stk_push(phone, price, account_ref=b.code, description="Biashara Pro renewal")
            except mpesa.MpesaError as exc:
                audit(db, None, None, "payment.failed", target=b.code, actor="Biashara Check", detail=f"renewal: {exc}"[:200])
                continue
            o = _owner(db, b)
            db.add(Payment(business_id=b.id, business_code=b.code, username=o.username if o else "", plan=b.pro_plan,
                           amount=price, phone_masked=mask_phone(phone), mode=mpesa.mode(), checkout_id=r["checkout_id"],
                           merchant_request_id=r["merchant_request_id"], status="pending", kind="renewal",
                           auto_renew=True, created_at=now, updated_at=now))
            audit(db, None, None, "payment.started", target=b.code, actor="Biashara Check",
                  detail=f"renewal prompt, KES {price}, {b.pro_plan}, {mask_phone(phone)} ({mpesa.mode()})")
            out["prompts"] += 1
    db.commit()
    return out


async def renew_loop() -> None:
    from .database import SessionLocal
    await asyncio.sleep(90)
    while True:
        if os.getenv("RENEWALS", "on").lower() != "off":
            try:
                with SessionLocal() as db:
                    out = await asyncio.to_thread(process, db)
                    if any(out.values()):
                        log.info("Pro renewals: %s", out)
            except Exception:
                log.exception("Renewal run failed")
        await asyncio.sleep(30 * 60)
