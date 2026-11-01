"""Messages to owners: monthly report email, risk-rise alerts and monthly reminders.

Every message respects the owner's choices on the Account page, goes only to a confirmed email
or phone number, and is logged. Each reminder and summary is sent at most once per month.
"""
import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import mailer, sms
from .contacts import audit, contact_of
from .crypto import decrypt
from .models import AuditLog, Business, MonthlyRecord, User

log = logging.getLogger("uvicorn.error")
EAT = timezone(timedelta(hours=3))
APP_URL = lambda: os.getenv("APP_URL", "").strip().rstrip("/")  # noqa: E731  e.g. your ngrok address


def _owner(db: Session, b: Business) -> User | None:
    return db.scalar(select(User).where(User.business_id == b.id, User.role == "owner", User.is_active.is_(True)))


def _sent(db: Session, action: str, code: str, detail: str) -> bool:
    return db.scalar(select(AuditLog.id).where(AuditLog.action == action, AuditLog.target == code,
                                               AuditLog.detail == detail).limit(1)) is not None


def _link(path: str = "/") -> str:
    base = APP_URL()
    return f"\n\nOpen Biashara Check: {base}{path}" if base else ""


def _ml(d: date) -> str:
    return f"{d:%B %Y}"


def outlook_line(db: Session, b: Business, o) -> str:
    """The owner's chosen outlook (when it isn't the standard 3 months), for messages."""
    h = (getattr(o, "outlook_months", 3) or 3) if o else 3
    if h == 3:
        return ""
    from . import risk
    if not (risk.model_ready() and risk.outlook_ready()):
        return ""
    ol = risk.compute_outlook(db, b, h)
    if not ol:
        return ""
    return (f"Your outlook for the next {h} months (to {date.fromisoformat(ol['until'] + '-01'):%B %Y}): "
            f"{round(ol['probability'] * 100)}% chance of at least one loss month ({ol['band']}).")


# ---------- monthly report email ----------
def monthly_summary(db: Session, b: Business, month: date) -> bool:
    """After the owner adds a month: email the monthly report as a PDF. Once per business and month."""
    o = _owner(db, b)
    c = contact_of(db, o) if o else None
    if not o or not o.notify_reports or not c or not c.email_verified_at or b.is_synthetic:
        return False
    tag = f"{month:%Y-%m}"
    if _sent(db, "report.emailed", b.code, tag):
        return False
    from .reports import _records, _risk_for, monthly_report, net
    recs = _records(db, b)
    r, _ = _risk_for(db, b, recs)
    last = recs[-1]
    lines = [f"Hello,\n\nHere is your Biashara Check report for {b.code}, with figures up to {_ml(last.month)}.\n",
             f"Sales: KES {float(last.revenue):,.0f}",
             f"Profit or loss: KES {net(last):,.0f}"]
    if r:
        lines.append(f"Risk of a loss in the next 3 months: {r['band']}"
                     + (f" ({round(r['probability'] * 100)}%)" if r.get("probability") is not None else ""))
        if r.get("reasons") and r["band"] != "Low":
            lines.append(f"Main reason: {r['reasons'][0]['text']}")
    ol = outlook_line(db, b, o)
    if ol:
        lines.append(ol)
    lines.append("\nThe full report with charts is attached as a PDF.")
    lines.append("You can switch these emails off on your Account page." + _link("/"))
    try:
        pdf = monthly_report(db, b)
        mailer.send(decrypt(c.email_enc), f"Your Biashara Check report for {_ml(last.month)}", "\n".join(lines),
                    attachments=[(f"Biashara-Check-{b.code}-{tag}.pdf", pdf, "application/pdf")])
    except Exception:
        log.exception("Monthly report email failed for %s", b.code)
        return False
    audit(db, None, None, "report.emailed", target=b.code, detail=tag, actor="Biashara Check")
    return True


def after_month_added(business_id: int, month: date) -> None:
    """Background task: risk refresh first (it may alert), then the monthly report email."""
    from . import risk
    from .database import SessionLocal
    risk.refresh(business_id)
    try:
        with SessionLocal() as db:
            b = db.get(Business, business_id)
            latest = db.scalar(select(MonthlyRecord.month).where(MonthlyRecord.business_id == business_id)
                               .order_by(MonthlyRecord.month.desc()).limit(1))
            if b and latest == month:  # only for the newest month, not when filling in old months
                if monthly_summary(db, b, month):
                    db.commit()
    except Exception:
        log.exception("After-month tasks failed")


# ---------- outlook alert: the owner's chosen 1-12 month outlook went up a band ----------
def outlook_alert(db: Session, b: Business, prev_band: str, ol: dict) -> bool:
    o = _owner(db, b)
    c = contact_of(db, o) if o else None
    if not o or not o.notify_alerts or not c:
        return False
    h, pc = ol["months"], round(ol["probability"] * 100)
    until = f"{date.fromisoformat(ol['until'] + '-01'):%B %Y}"
    reason = ol["reasons"][0]["text"] if ol.get("reasons") else ""
    sent = []
    if c.phone_verified_at:
        try:
            sms.send(decrypt(c.phone_enc), (f"Biashara Check: {b.code} outlook for the next {h} months rose from {prev_band} to "
                                            f"{ol['band']} ({pc}% chance of a loss month by {until}). {reason[:80]}")[:300])
            sent.append("SMS")
        except Exception:
            log.exception("Outlook SMS failed for %s", b.code)
    if c.email_verified_at:
        tips = "\n".join(f"- {x['text']}" + (f"\n  What you can do: {x['tip']}" if x.get("tip") else "") for x in ol.get("reasons", [])[:3])
        try:
            mailer.send(decrypt(c.email_enc), f"Biashara Check: your {h}-month outlook went up to {ol['band']}",
                        f"Hello,\n\nLooking {h} months ahead (to {until}), the chance of at least one loss month for {b.code} is now "
                        f"{pc}% ({ol['band']}, up from {prev_band}).\n\nThe main reasons:\n{tips}\n\n"
                        "You chose how far ahead to look on your dashboard. You can switch alerts off on your Account page." + _link("/"))
            sent.append("email")
        except Exception:
            log.exception("Outlook email failed for %s", b.code)
    if sent:
        audit(db, None, None, "alert.outlook", target=b.code, actor="Biashara Check",
              detail=f"{h} months: {prev_band} to {ol['band']} by {' and '.join(sent)}")
    return bool(sent)


# ---------- risk-rise alert ----------
def risk_alert(db: Session, b: Business, prev_band: str, r: dict) -> bool:
    """The risk went up a band: tell the owner by SMS (confirmed phone) and email (confirmed email)."""
    o = _owner(db, b)
    c = contact_of(db, o) if o else None
    if not o or not o.notify_alerts or not c:
        return False
    reason = r["reasons"][0]["text"] if r.get("reasons") else ""
    sent = []
    if c.phone_verified_at:
        text = (f"Biashara Check: {b.code} risk of a loss in the next 3 months rose from {prev_band} to {r['band']}. "
                f"{reason[:90]} Log in to see what you can do.")
        try:
            sms.send(decrypt(c.phone_enc), text[:300])
            sent.append("SMS")
        except Exception:
            log.exception("Risk SMS failed for %s", b.code)
    if c.email_verified_at:
        ol_text = outlook_line(db, b, o)
        tips = "\n".join(f"- {x['text']}\n  What you can do: {x['tip']}" for x in r.get("reasons", [])[:3] if x.get("tip"))
        body = (f"Hello,\n\nYour Biashara Check risk for {b.code} rose from {prev_band} to {r['band']}"
                + (f" ({round(r['probability'] * 100)}% chance of a loss month in the next 3 months)" if r.get("probability") is not None else "")
                + f", based on your figures up to {r['as_of']}.\n\nThe main reasons:\n{tips}\n\n"
                + (ol_text + "\n\n" if ol_text else "")
                + "Acting now, before the loss happens, is what the early warning is for."
                "\n\nYou can switch these alerts off on your Account page." + _link("/"))
        try:
            mailer.send(decrypt(c.email_enc), f"Biashara Check: your risk went up to {r['band']}", body)
            sent.append("email")
        except Exception:
            log.exception("Risk email failed for %s", b.code)
    if sent:
        audit(db, None, None, "alert.risk", target=b.code, actor="Biashara Check",
              detail=f"{prev_band} to {r['band']} by {' and '.join(sent)}")
    return bool(sent)


# ---------- monthly reminders ----------
def last_full_month(today: date | None = None) -> date:
    t = today or datetime.now(EAT).date()
    return date(t.year - 1, 12, 1) if t.month == 1 else date(t.year, t.month - 1, 1)


def send_reminders(db: Session, today: date | None = None) -> dict:
    """Reminds owners who haven't added last month yet. At most once per owner per month."""
    month = last_full_month(today)
    tag = f"{month:%Y-%m}"
    counts = {"emails": 0, "sms": 0, "skipped": 0}
    owners = db.scalars(select(User).where(User.role == "owner", User.is_active.is_(True))).all()
    for o in owners:
        b = o.business
        if not b or b.is_synthetic or not o.notify_reminders:
            counts["skipped"] += 1
            continue
        has = db.scalar(select(MonthlyRecord.id).where(MonthlyRecord.business_id == b.id, MonthlyRecord.month == month))
        if has or _sent(db, "reminder.sent", b.code, tag):
            counts["skipped"] += 1
            continue
        c = contact_of(db, o)
        if not c:
            counts["skipped"] += 1
            continue
        how = []
        if c.email_verified_at:
            try:
                mailer.send(decrypt(c.email_enc), f"Add your {_ml(month)} figures to Biashara Check",
                            f"Hello,\n\n{_ml(month)} is over. Add its sales, costs and cash for {b.code} so your risk "
                            f"check stays up to date. It takes about 5 minutes.\n\nTip: with Biashara Pro you can fill in "
                            "M-Pesa figures from your M-Pesa statement.\n\nYou can switch reminders off on your Account page."
                            + _link("/"))
                counts["emails"] += 1
                how.append("email")
            except Exception:
                log.exception("Reminder email failed for %s", b.code)
        if c.phone_verified_at and sms.mode() != "console":
            try:
                sms.send(decrypt(c.phone_enc), f"Biashara Check: {_ml(month)} is over. Add your figures for {b.code} "
                                               "to keep your risk check up to date.")
                counts["sms"] += 1
                how.append("SMS")
            except Exception:
                log.exception("Reminder SMS failed for %s", b.code)
        if how:
            audit(db, None, None, "reminder.sent", target=b.code, detail=tag, actor="Biashara Check")
    db.commit()
    return {"month": tag, **counts}


async def reminder_loop() -> None:
    """Runs inside the app: from the 2nd to the 10th of each month, after 9 am Nairobi time,
    sends reminders once (send_reminders skips anyone already reminded). Checks every 3 hours.
    Switch off with REMINDERS=off in .env."""
    from .database import SessionLocal
    await asyncio.sleep(60)
    while True:
        now = datetime.now(EAT)
        if os.getenv("REMINDERS", "on").lower() != "off" and 2 <= now.day <= 10 and now.hour >= 9:
            try:
                with SessionLocal() as db:
                    out = await asyncio.to_thread(send_reminders, db)
                    if out["emails"] or out["sms"]:
                        log.info("Monthly reminders sent: %s", out)
            except Exception:
                log.exception("Reminder run failed")
        await asyncio.sleep(3 * 3600)
