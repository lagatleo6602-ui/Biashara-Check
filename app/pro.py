"""Biashara Pro: what it costs and who has it."""
import os
from datetime import timedelta

from fastapi import HTTPException

from . import mpesa
from .auth import utcnow
from .models import Business, Payment, User

FEATURES = [
    "Import your M-Pesa statement: received payments and number of sales filled in for you",
    "Business summary for lenders: a PDF of 6 to 12 months to take to a SACCO, bank or supplier",
]


def plans() -> dict:
    month = int(os.getenv("PRO_PRICE_MONTH", "300") or 300)
    year = int(os.getenv("PRO_PRICE_YEAR", "3000") or 3000)
    return {"month": {"name": "1 month", "price": month, "days": 30},
            "year": {"name": "12 months", "price": year, "days": 365}}


def charge_amount(plan: str) -> int:
    """In the Daraja sandbox we always ask for KES 1, so testing never risks real money."""
    return 1 if mpesa.mode() == "sandbox" else plans()[plan]["price"]


def is_pro(b: Business | None) -> bool:
    return bool(b and b.pro_until and b.pro_until > utcnow())


RENEW_PROMPT_BEFORE = timedelta(hours=24)   # the renewal M-Pesa prompt goes out a day before Pro ends
RENEW_NOTICE_BEFORE = timedelta(days=3)     # and a "renews soon" message three days before


def status(b: Business) -> dict:
    """Everything the Account page shows: exact end time (UTC, shown in the owner's time with a live countdown),
    the plan, and whether, when and for how much it renews."""
    from .contacts import mask_phone
    from .crypto import decrypt
    active = is_pro(b)
    days_left = max(0, (b.pro_until - utcnow()).days) if active else 0
    renews = bool(active and b.auto_renew and b.pro_plan and b.renew_phone_enc)
    plan = plans().get(b.pro_plan or "", None)
    phone = ""
    if b.renew_phone_enc:
        try:
            phone = mask_phone(decrypt(b.renew_phone_enc))
        except Exception:
            phone = ""
    return {"active": active, "until": b.pro_until.isoformat(timespec="seconds") + "Z" if b.pro_until else None,
            "source": b.pro_source, "days_left": days_left,
            "plan": b.pro_plan, "plan_name": plan["name"] if plan else None,
            "auto_renew": renews,
            "renewal": {"prompt_at": (b.pro_until - RENEW_PROMPT_BEFORE).isoformat(timespec="seconds") + "Z",
                        "amount": charge_amount(b.pro_plan), "phone": phone} if renews else None,
            "cancelled_at": b.renew_cancelled_at.isoformat(timespec="seconds") + "Z" if b.renew_cancelled_at else None}


def extend(b: Business, days: int, source: str) -> None:
    start = b.pro_until if is_pro(b) else utcnow()
    b.pro_until = start + timedelta(days=days)
    b.pro_source = source


def apply_payment(b: Business | None, p: Payment) -> bool:
    """Adds the plan's days once, when a payment is confirmed. Returns True if it did."""
    if p.status != "paid" or p.applied or b is None:
        return False
    extend(b, plans().get(p.plan, {"days": 30})["days"], "mpesa")
    b.pro_plan = p.plan
    if p.auto_renew and (p.kind or "new") == "new":  # a renewal never switches renewal back on after a cancel
        b.auto_renew, b.renew_cancelled_at = True, None
    p.applied = True
    return True


def require_pro(b: Business, user: User) -> None:
    if user.role == "admin":
        return  # the study team can use every feature
    if not is_pro(b):
        raise HTTPException(402, "This is a Biashara Pro feature. Upgrade on the Account page (paid with M-Pesa).")
