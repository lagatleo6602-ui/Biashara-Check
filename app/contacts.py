"""Email/phone checks, masking, one-time codes and the activity log."""
import re
import secrets
from datetime import timedelta

from fastapi import HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import mailer, sms
from .auth import hash_password, utcnow, verify_password
from .crypto import blind_index, decrypt, encrypt
from .models import AuditLog, Contact, OneTimeCode, User

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
CODE_MINUTES = 15
MAX_CODE_TRIES = 5
RESEND_SECONDS = 60


# ---------- validation ----------
def clean_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 120:
        raise HTTPException(422, "Enter a valid email address, like name@gmail.com.")
    return email


def clean_phone(raw: str) -> str:
    """Kenyan mobile numbers in any common form -> +2547XXXXXXXX / +2541XXXXXXXX."""
    digits = re.sub(r"[^\d+]", "", raw or "")
    if digits.startswith("+"):
        digits = digits[1:]
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "71":
        digits = "254" + digits
    if not re.fullmatch(r"254[71]\d{8}", digits):
        raise HTTPException(422, "Enter a Kenyan mobile number, like 0712 345 678.")
    return "+" + digits


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return (name[:2] + "•" * max(1, len(name) - 2)) + "@" + domain


def mask_phone(phone: str) -> str:
    return f"{phone[:5]}•••••{phone[-3:]}" if len(phone) > 8 else "•••"


# ---------- contacts ----------
def contact_of(db: Session, user: User) -> Contact | None:
    return db.scalar(select(Contact).where(Contact.user_id == user.id))


def find_by_email(db: Session, email: str) -> Contact | None:
    return db.scalar(select(Contact).where(Contact.email_hash == blind_index("email", email)))


def find_by_phone(db: Session, phone: str) -> list[Contact]:
    return list(db.scalars(select(Contact).where(Contact.phone_hash == blind_index("phone", phone))).all())


def save_contact(db: Session, user: User, email: str, phone: str, consent: bool = False) -> tuple[Contact, bool]:
    """Creates or updates. Returns (contact, email_changed). A changed email must be verified again."""
    taken = find_by_email(db, email)
    if taken and taken.user_id != user.id:
        raise HTTPException(409, "That email is already used by another account.")
    c = contact_of(db, user)
    email_changed = True
    if c is None:
        c = Contact(user_id=user.id)
        db.add(c)
    else:
        email_changed = c.email_hash != blind_index("email", email)
        phone_changed = c.phone_hash != blind_index("phone", phone)
        if phone_changed:
            c.phone_verified_at = None
    c.email_enc, c.email_hash = encrypt(email), blind_index("email", email)
    c.phone_enc, c.phone_hash = encrypt(phone), blind_index("phone", phone)
    if email_changed:
        c.email_verified_at = None
    if consent and not c.contact_consent_at:
        c.contact_consent_at = utcnow()
    c.updated_at = utcnow()
    db.flush()
    return c, email_changed


def contact_summary(c: Contact | None, full: bool = False) -> dict | None:
    if not c:
        return None
    email, phone = decrypt(c.email_enc), decrypt(c.phone_enc)
    return {
        "email": email if full else mask_email(email),
        "phone": phone if full else mask_phone(phone),
        "email_verified": bool(c.email_verified_at),
        "phone_verified": bool(c.phone_verified_at),
    }


# ---------- one-time codes ----------
def issue_code(db: Session, user: User, purpose: str) -> str:
    last = db.scalar(select(OneTimeCode).where(OneTimeCode.user_id == user.id, OneTimeCode.purpose == purpose)
                     .order_by(OneTimeCode.id.desc()))
    if last and last.created_at and (utcnow() - last.created_at).total_seconds() < RESEND_SECONDS:
        raise HTTPException(429, "A code was sent less than a minute ago. Check your email, or try again shortly.")
    db.execute(delete(OneTimeCode).where(OneTimeCode.user_id == user.id, OneTimeCode.purpose == purpose))
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(OneTimeCode(user_id=user.id, purpose=purpose, code_hash=hash_password(code),
                       expires_at=utcnow() + timedelta(minutes=CODE_MINUTES), created_at=utcnow()))
    db.flush()
    return code


def discard_codes(db: Session, user: User, purpose: str) -> None:
    """Used when sending failed, so the person can ask again straight away."""
    db.execute(delete(OneTimeCode).where(OneTimeCode.user_id == user.id, OneTimeCode.purpose == purpose))
    db.flush()


def check_code(db: Session, user: User, purpose: str, code: str) -> bool:
    row = db.scalar(select(OneTimeCode).where(OneTimeCode.user_id == user.id, OneTimeCode.purpose == purpose)
                    .order_by(OneTimeCode.id.desc()))
    if not row or row.expires_at < utcnow() or row.attempts >= MAX_CODE_TRIES:
        return False
    if verify_password(re.sub(r"\D", "", code or ""), row.code_hash):
        db.delete(row)
        return True
    row.attempts += 1
    db.flush()
    return False


def send_code_sms(phone: str, code: str, purpose: str) -> None:
    if purpose == "verify_phone":
        text = f"Biashara Check: your code to confirm this number is {code}. It expires in {CODE_MINUTES} minutes."
    else:
        text = f"Biashara Check: your password reset code is {code}. It expires in {CODE_MINUTES} minutes. Didn't ask? Ignore this."
    try:
        sms.send(phone, text)
    except sms.SmsError as exc:
        raise HTTPException(502, str(exc)) from exc


def send_code_email(email: str, code: str, purpose: str, who: str) -> None:
    if purpose == "verify_email":
        subject = f"Your Biashara Check code: {code}"
        body = (f"Hello,\n\nYour code to confirm this email for {who} is:\n\n    {code}\n\n"
                f"It expires in {CODE_MINUTES} minutes. If you didn't ask for it, you can ignore this email.\n")
    else:
        subject = f"Reset your Biashara Check password: {code}"
        body = (f"Hello,\n\nSomeone asked to reset the password for {who}. Your reset code is:\n\n    {code}\n\n"
                f"It expires in {CODE_MINUTES} minutes. If this wasn't you, ignore this email; your password stays the same.\n")
    try:
        mailer.send(email, subject, body)
    except mailer.MailError as exc:
        raise HTTPException(502, str(exc)) from exc


# ---------- activity log ----------
def audit(db: Session, request: Request | None, user: User | None, action: str,
          target: str = "", detail: str = "", actor: str | None = None) -> None:
    ip = ""
    if request is not None and request.client:
        ip = request.headers.get("x-forwarded-for", request.client.host).split(",")[0].strip()[:45]
    db.add(AuditLog(at=utcnow(), actor=(actor or (user.username if user else "anonymous"))[:60],
                    actor_role=(user.role if user else "-"), action=action, target=target[:60],
                    detail=detail[:255], ip=ip))
