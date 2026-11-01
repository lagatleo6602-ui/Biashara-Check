import hmac
import json
import os
import re
import secrets
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..auth import (MIN_PASSWORD, check_locked, clear_fails, current_user, end_other_sessions,
                    end_session, hash_password, normalise_code, record_fail, recovery_code,
                    start_session, utcnow, verify_password)
from .. import mailer, sms
from ..contacts import (MAX_CODE_TRIES, RESEND_SECONDS, audit, check_code, clean_email, clean_phone, contact_of,
                        contact_summary, discard_codes, mask_email,
                        find_by_email, find_by_phone, issue_code, save_contact, send_code_email, send_code_sms)
from ..crypto import blind_index, decrypt, encrypt
from ..database import get_db
from ..sectors import SECTORS, Sector
from ..pro import status as pro_status
from ..invites import any_admin, active_invite, match_invite, super_admin, INVITE_HOURS
from ..models import AdminInvite, Business, LoginSession, PendingSignup, User

router = APIRouter(prefix="/auth", tags=["login"])


def me_payload(db: Session, user: User) -> dict:
    return {"username": user.username, "role": user.role,
            "is_super_admin": bool(user.role == "admin" and user.is_super_admin),
            "show_tour": user.role == "owner" and user.tour_done_at is None,
            "business": user.business.code if user.business else None,
            "must_change_password": bool(user.must_change_password),
            "contact": contact_summary(contact_of(db, user)),
            "pro": pro_status(user.business) if user.business else None,
            "language": user.language or "en",
            "outlook_months": user.outlook_months or 3,
            "notify": {"reports": bool(user.notify_reports), "reminders": bool(user.notify_reminders),
                       "alerts": bool(user.notify_alerts)}}


def new_recovery_code(user: User) -> str:
    code = recovery_code()
    user.recovery_hash = hash_password(normalise_code(code))
    return code


def who(user: User) -> str:
    return user.business.code if user.business else user.username


def send_verify_email(db: Session, user: User) -> None:
    c = contact_of(db, user)
    if c and not c.email_verified_at:
        code = issue_code(db, user, "verify_email")
        try:
            send_code_email(decrypt(c.email_enc), code, "verify_email", who(user))
        except HTTPException:
            discard_codes(db, user, "verify_email")
            raise


def try_send_verify_email(db: Session, user: User) -> str | None:
    """At sign-up a failed email mustn't lose the new account: report it and let the owner resend later."""
    try:
        send_verify_email(db, user)
        return None
    except HTTPException as exc:
        return f"Your account is ready, but the confirmation email didn't send: {exc.detail} You can send it again from the dashboard."


# ---------- log in / out ----------
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=200)


def find_login(db: Session, name: str) -> User | None:
    """Username, business code or email address. The business code keeps working after an owner
    picks a new username."""
    name = name.strip().lower()
    if "@" in name:
        c = find_by_email(db, name)
        return c.user if c else None
    user = db.scalar(select(User).where(func.lower(User.username) == name))
    if user is None:
        b = db.scalar(select(Business).where(func.lower(Business.code) == name))
        if b is not None:
            user = db.scalar(select(User).where(User.business_id == b.id, User.role == "owner"))
    return user


@router.post("/login")
def login(payload: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    key = payload.username.strip().lower()
    check_locked(key)
    user = find_login(db, key)
    if not user or not verify_password(payload.password, user.password_hash):
        record_fail(key)
        audit(db, request, None, "login.failed", target=key[:60], actor="anonymous")
        db.commit()
        raise HTTPException(401, "Wrong username, business code, email or password.")
    if not user.is_active:
        raise HTTPException(403, "This account has been switched off. Contact the study team.")
    clear_fails(key)
    audit(db, request, user, "login", target=who(user))
    start_session(db, user, response)
    return me_payload(db, user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    end_session(db, request, response)
    return {"ok": True}


@router.get("/me")
def me(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return me_payload(db, user)


class SettingsIn(BaseModel):
    reports: bool | None = None
    reminders: bool | None = None
    alerts: bool | None = None
    language: Literal["en", "sw"] | None = None
    outlook_months: int | None = Field(default=None, ge=1, le=12)


@router.put("/settings")
def update_settings(payload: SettingsIn, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    """Notification choices and language."""
    if payload.reports is not None:
        user.notify_reports = payload.reports
    if payload.reminders is not None:
        user.notify_reminders = payload.reminders
    if payload.alerts is not None:
        user.notify_alerts = payload.alerts
    if payload.language is not None:
        user.language = payload.language
    if payload.outlook_months is not None:
        user.outlook_months = payload.outlook_months
    audit(db, request, user, "settings.changed", target=who(user),
          detail=", ".join(f"{k}={v}" for k, v in payload.model_dump(exclude_none=True).items()))
    db.commit()
    return me_payload(db, user)


class UsernameIn(BaseModel):
    username: str = Field(min_length=3, max_length=30)
    current_password: str = Field(min_length=1, max_length=200)


USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,29}$")
RESERVED = {"admin", "administrator", "root", "support", "system", "anonymous", "biashara", "biashara-check"}


@router.put("/username")
def change_username(payload: UsernameIn, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    """Pick a new username. Owners can still log in with their business code and email too.
    Needs the current password, and the change is written to the activity log."""
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "Your current password is wrong.")
    new = payload.username.strip().lower()
    if not USERNAME_RE.match(new):
        raise HTTPException(422, "Use 3 to 30 letters, numbers, dots, dashes or underscores, starting with a letter or number.")
    if re.search(r"\d{8,}", re.sub(r"[._-]", "", new)):
        raise HTTPException(422, "Don't use a phone or ID number as your username: other people may see it.")
    if new == user.username.lower():
        raise HTTPException(400, "That is already your username.")
    if new in RESERVED and user.role != "admin":
        raise HTTPException(409, "That username is reserved. Pick another.")
    taken = db.scalar(select(User).where(func.lower(User.username) == new, User.id != user.id))
    other_code = db.scalar(select(Business).where(func.lower(Business.code) == new))
    if taken or (other_code is not None and other_code.id != user.business_id):
        raise HTTPException(409, "That username is taken. Pick another.")
    user = db.merge(user)
    old = user.username
    user.username = new
    audit(db, request, user, "username.changed", target=who(user), detail=f"{old} -> {new}")
    db.commit()
    return me_payload(db, user)


@router.post("/tour-done")
def tour_done(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The welcome walkthrough was finished or skipped: don't show it again automatically."""
    if user.tour_done_at is None:
        user.tour_done_at = utcnow()
        db.commit()
    return {"ok": True}


# ---------- sign up ----------
class ContactIn(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    phone: str = Field(min_length=9, max_length=20)


class RegisterIn(ContactIn):
    code: str = Field(min_length=3, max_length=20, pattern=r"^[A-Za-z0-9-]+$")
    sector: Sector
    start_date: date | None = None
    password: str = Field(min_length=MIN_PASSWORD, max_length=200)
    consent: bool
    contact_consent: bool


# Sign-up happens in two steps, so nobody gets an account with an email they don't own:
#   1. POST /auth/register (or /auth/register-admin) checks the details and emails a 6-digit code.
#   2. POST /auth/register/confirm with that code creates the account and logs in.
SIGNUP_MINUTES = 15


def _signup_email(email: str, code: str, name: str) -> None:
    subject = f"Confirm your email for Biashara Check: {code}"
    body = (f"Hello,\n\nYou're creating a Biashara Check account for {name}. Enter this code to confirm "
            f"your email and finish:\n\n    {code}\n\nIt expires in {SIGNUP_MINUTES} minutes. "
            f"If you didn't start this, ignore this email: no account is created without the code.\n")
    try:
        mailer.send(email, subject, body)
    except mailer.MailError as exc:
        raise HTTPException(502, f"We couldn't send the confirmation email: {exc}") from exc


def _start_signup(db: Session, request: Request, kind: str, email: str, data: dict, name: str) -> dict:
    now = utcnow()
    db.execute(delete(PendingSignup).where(PendingSignup.expires_at < now))
    key = blind_index("email", email)
    db.execute(delete(PendingSignup).where(PendingSignup.email_hash == key))  # starting again replaces the old one
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(PendingSignup(kind=kind, email_hash=key, data_enc=encrypt(json.dumps({**data, "email": email})),
                         code_hash=hash_password(code), expires_at=now + timedelta(minutes=SIGNUP_MINUTES), sent_at=now))
    db.flush()
    _signup_email(email, code, name)  # on failure nothing is kept (the request rolls back)
    audit(db, request, None, "signup.code_sent", target=name, detail=f"{kind}, {mask_email(email)}")
    db.commit()
    return {"pending": True, "email": mask_email(email), "minutes": SIGNUP_MINUTES, "email_mode": mailer.mode()}


def _check_owner_free(db: Session, code: str, email: str) -> None:
    if db.scalar(select(Business).where(Business.code == code)) or \
       db.scalar(select(User).where(func.lower(User.username) == code.lower())):
        raise HTTPException(409, "That business code is taken. Try another, for example SME-002.")
    if find_by_email(db, email):
        raise HTTPException(409, "That email is already used by another account. Log in instead, or use another email.")


@router.post("/register", status_code=202)
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    """Step 1 for owners: check the details and email a code. No account exists yet."""
    if not payload.consent:
        raise HTTPException(400, "You need to agree to the research consent statement to take part.")
    if not payload.contact_consent:
        raise HTTPException(400, "You need to agree to how we use your email and phone number.")
    email, phone = clean_email(payload.email), clean_phone(payload.phone)
    code = payload.code.strip().upper()
    _check_owner_free(db, code, email)
    data = {"code": code, "sector": payload.sector,
            "start_date": payload.start_date.isoformat() if payload.start_date else None,
            "password_hash": hash_password(payload.password), "phone": phone}
    return _start_signup(db, request, "owner", email, data, code)


class AdminRegisterIn(ContactIn):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=MIN_PASSWORD, max_length=200)
    admin_code: str = Field(min_length=1, max_length=200)


def admin_signup_code() -> str:
    """ADMIN_SIGNUP_CODE in .env is only for creating the very FIRST admin (who becomes super admin).
    After that, every new admin needs a one-time code from the super admin."""
    code = os.getenv("ADMIN_SIGNUP_CODE", "").strip()
    if len(code) < 8 or code == "change-me-to-a-secret":  # the example value never works
        return ""
    return code


def admin_signup_mode(db: Session) -> str:
    """'invite' = a super admin code is waiting to be used, 'setup' = no admins yet, '' = off."""
    if not any_admin(db):
        return "setup" if admin_signup_code() else ""
    return "invite" if active_invite(db) else ""


@router.get("/options")
def options(db: Session = Depends(get_db)):
    """Tells the login page whether to offer admin sign-up."""
    mode = admin_signup_mode(db)
    return {"admin_signup": bool(mode), "admin_signup_mode": mode, "email": mailer.mode(), "sms": sms.mode()}


def _admin_code_ok(db: Session, request: Request, username: str, admin_code: str):
    """Returns (ok, invite or None, first_admin)."""
    first = not any_admin(db)
    if first:
        expected = admin_signup_code()
        if not expected:
            raise HTTPException(403, "No admin exists yet. Set ADMIN_SIGNUP_CODE (8+ characters) in .env and restart the server, or run: python -m app.create_admin")
        return hmac.compare_digest(admin_code.strip(), expected), None, True
    invite = match_invite(db, admin_code)
    return invite is not None, invite, False


@router.post("/register-admin", status_code=202)
def register_admin(payload: AdminRegisterIn, request: Request, db: Session = Depends(get_db)):
    """Step 1 for admins: check the one-time admin code (or, for the very first admin only,
    ADMIN_SIGNUP_CODE from .env) and the details, then email a code."""
    check_locked("admin-signup")
    ok, invite, first = _admin_code_ok(db, request, payload.username, payload.admin_code)
    if not ok:
        record_fail("admin-signup")
        audit(db, request, None, "admin_signup.failed", target=payload.username[:60]); db.commit()
        if first:
            raise HTTPException(403, "That admin code is wrong.")
        raise HTTPException(403, f"That admin code is wrong, already used, or expired. Ask the super admin for a new one (codes work once and last {INVITE_HOURS} hours).")
    clear_fails("admin-signup")
    email, phone = clean_email(payload.email), clean_phone(payload.phone)
    username = payload.username.strip().lower()
    _check_admin_free(db, username, email)
    data = {"username": username, "password_hash": hash_password(payload.password), "phone": phone,
            "invite_id": invite.id if invite else None, "first": first}
    return _start_signup(db, request, "admin", email, data, username)


def _check_admin_free(db: Session, username: str, email: str) -> None:
    if db.scalar(select(User).where(func.lower(User.username) == username)) or \
       db.scalar(select(Business).where(func.lower(Business.code) == username)):
        raise HTTPException(409, "That username is taken. Pick another.")
    if find_by_email(db, email):
        raise HTTPException(409, "That email is already used by another account.")


class SignupEmailIn(BaseModel):
    email: str = Field(min_length=3, max_length=120)


class SignupConfirmIn(SignupEmailIn):
    code: str = Field(min_length=4, max_length=12)


def _pending(db: Session, email: str) -> PendingSignup | None:
    return db.scalar(select(PendingSignup).where(PendingSignup.email_hash == blind_index("email", clean_email(email))))


@router.post("/register/resend")
def register_resend(payload: SignupEmailIn, request: Request, db: Session = Depends(get_db)):
    p = _pending(db, payload.email)
    if not p or p.expires_at < utcnow():
        raise HTTPException(404, "That sign-up has expired. Fill in the form again.")
    if (utcnow() - p.sent_at).total_seconds() < RESEND_SECONDS:
        raise HTTPException(429, "A code was sent less than a minute ago. Check your inbox and spam folder, or try again shortly.")
    data = json.loads(decrypt(p.data_enc))
    code = f"{secrets.randbelow(1_000_000):06d}"
    p.code_hash, p.attempts, p.sent_at = hash_password(code), 0, utcnow()
    p.expires_at = utcnow() + timedelta(minutes=SIGNUP_MINUTES)
    db.flush()
    _signup_email(data["email"], code, data.get("code") or data.get("username"))
    db.commit()
    return {"pending": True, "email": mask_email(data["email"]), "minutes": SIGNUP_MINUTES}


@router.post("/register/confirm", status_code=201)
def register_confirm(payload: SignupConfirmIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Step 2: the code from the email creates the account, with the email already confirmed."""
    email = clean_email(payload.email)
    key = "signup:" + blind_index("email", email)
    check_locked(key)
    p = _pending(db, email)
    if not p or p.expires_at < utcnow():
        raise HTTPException(404, "That code has expired. Fill in the form again to get a new one.")
    if p.attempts >= MAX_CODE_TRIES:
        db.delete(p); db.commit()
        raise HTTPException(400, "Too many wrong codes. Fill in the form again to get a new one.")
    if not verify_password(re.sub(r"\D", "", payload.code), p.code_hash):
        p.attempts += 1; record_fail(key); db.commit()
        left = MAX_CODE_TRIES - p.attempts
        raise HTTPException(400, f"That code is wrong. {left} tr{'y' if left == 1 else 'ies'} left." if left else
                            "That code is wrong. Fill in the form again to get a new one.")
    clear_fails(key)
    data, kind = json.loads(decrypt(p.data_enc)), p.kind
    db.delete(p)
    db.flush()
    if kind == "owner":
        user, name = _create_owner(db, data)
        audit(db, request, user, "account.created", target=name, detail="email confirmed at sign-up")
    else:
        user, name, detail = _create_admin(db, data)
        audit(db, request, user, "admin.created", target=name, detail=detail)
    rc = new_recovery_code(user)
    c = contact_of(db, user)
    c.email_verified_at = utcnow()
    audit(db, request, user, "email.verified", target=name)
    db.commit()
    start_session(db, user, response)
    return {**me_payload(db, user), "recovery_code": rc, "notice": None}


def _create_owner(db: Session, d: dict) -> tuple[User, str]:
    _check_owner_free(db, d["code"], d["email"])  # someone may have taken it meanwhile
    b = Business(code=d["code"], sector=d["sector"],
                 start_date=date.fromisoformat(d["start_date"]) if d.get("start_date") else None)
    db.add(b)
    db.flush()
    user = User(username=d["code"].lower(), password_hash=d["password_hash"], role="owner",
                business_id=b.id, consent_at=utcnow())
    db.add(user)
    db.flush()
    save_contact(db, user, d["email"], d["phone"], consent=True)
    return user, d["code"]


def _create_admin(db: Session, d: dict) -> tuple[User, str, str]:
    _check_admin_free(db, d["username"], d["email"])
    invite = db.get(AdminInvite, d["invite_id"]) if d.get("invite_id") else None
    if d.get("first"):
        if any_admin(db):
            raise HTTPException(403, "Another admin was created first. Ask them for a one-time admin code.")
    elif not invite or invite.used_at or invite.cancelled_at or invite.expires_at < utcnow():
        raise HTTPException(403, "Your admin code was used, cancelled or expired while you were confirming. Ask the super admin for a new one.")
    user = User(username=d["username"], password_hash=d["password_hash"], role="admin",
                is_super_admin=super_admin(db) is None)
    db.add(user)
    db.flush()
    save_contact(db, user, d["email"], d["phone"], consent=True)
    if invite:
        invite.used_at, invite.used_by = utcnow(), d["username"]
    return user, d["username"], (f"invite code from {invite.created_by}" if invite else "first admin, super admin")


# ---------- contact details & email verification ----------
class UpdateContactIn(ContactIn):
    current_password: str = Field(min_length=1, max_length=200)


@router.put("/contact")
def update_contact(payload: UpdateContactIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    """Add or change email and phone. Needs the current password, so a borrowed phone can't hijack the account."""
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "Your current password is wrong.")
    user = db.merge(user)
    _, email_changed = save_contact(db, user, clean_email(payload.email), clean_phone(payload.phone), consent=True)
    audit(db, request, user, "contact.changed", target=who(user), detail="email changed" if email_changed else "phone changed")
    problem = try_send_verify_email(db, user) if email_changed else None
    db.commit()
    return {**me_payload(db, user), "notice": problem}


@router.post("/email/send-code")
def resend_verify(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    user = db.merge(user)
    c = contact_of(db, user)
    if not c:
        raise HTTPException(400, "Add your email first.")
    if c.email_verified_at:
        return {"ok": True, "already_verified": True}
    try:
        send_verify_email(db, user)
    except HTTPException:
        db.commit()
        raise
    db.commit()
    return {"ok": True, "mode": mailer.mode()}


class CodeIn(BaseModel):
    code: str = Field(min_length=4, max_length=12)


@router.post("/email/verify")
def verify_email(payload: CodeIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    user = db.merge(user)
    c = contact_of(db, user)
    if not c:
        raise HTTPException(400, "Add your email first.")
    if not check_code(db, user, "verify_email", payload.code):
        db.commit()
        raise HTTPException(400, "That code is wrong or has expired. Ask for a new one.")
    c.email_verified_at = utcnow()
    audit(db, request, user, "email.verified", target=who(user))
    db.commit()
    return me_payload(db, user)


@router.post("/phone/send-code")
def phone_send_code(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    user = db.merge(user)
    c = contact_of(db, user)
    if not c:
        raise HTTPException(400, "Add your mobile number first.")
    if c.phone_verified_at:
        return {"ok": True, "already_verified": True}
    code = issue_code(db, user, "verify_phone")
    try:
        send_code_sms(decrypt(c.phone_enc), code, "verify_phone")
    except HTTPException:
        discard_codes(db, user, "verify_phone"); db.commit()
        raise
    db.commit()
    return {"ok": True, "mode": sms.mode()}


@router.post("/phone/verify")
def phone_verify(payload: CodeIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    user = db.merge(user)
    c = contact_of(db, user)
    if not c:
        raise HTTPException(400, "Add your mobile number first.")
    if not check_code(db, user, "verify_phone", payload.code):
        db.commit()
        raise HTTPException(400, "That code is wrong or has expired. Ask for a new one.")
    c.phone_verified_at = utcnow()
    audit(db, request, user, "phone.verified", target=who(user), detail="by SMS code")
    db.commit()
    return me_payload(db, user)


# ---------- passwords ----------
class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=MIN_PASSWORD, max_length=200)


@router.post("/change-password")
def change_password(payload: ChangePasswordIn, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    """Logged-in user changes their own password. Other devices are logged out."""
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "Your current password is wrong.")
    if payload.new_password == payload.current_password:
        raise HTTPException(400, "Choose a password that is different from the current one.")
    user = db.merge(user)
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    end_other_sessions(db, user, request)
    audit(db, request, user, "password.changed", target=who(user))
    db.commit()
    return {"ok": True}


@router.post("/recovery-code")
def make_recovery_code(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Makes a new recovery code. The old one stops working."""
    user = db.merge(user)
    code = new_recovery_code(user)
    audit(db, request, user, "recovery_code.renewed", target=who(user))
    db.commit()
    return {"recovery_code": code}


def _finish_reset(db: Session, request: Request, response: Response, user: User, new_password: str, how: str) -> dict:
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))  # log out everywhere
    rc = new_recovery_code(user)
    audit(db, request, user, "password.reset", target=who(user), detail=how)
    db.commit()
    start_session(db, user, response)
    return {**me_payload(db, user), "recovery_code": rc}


class RecoverIn(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    recovery_code: str = Field(min_length=1, max_length=60)
    new_password: str = Field(min_length=MIN_PASSWORD, max_length=200)


@router.post("/recover")
def recover(payload: RecoverIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Forgot password: business code (or email) + recovery code -> new password."""
    name = payload.username.strip().lower()
    key = "recover:" + name
    check_locked(key)
    user = find_login(db, name)
    if not user or not user.recovery_hash or not verify_password(normalise_code(payload.recovery_code), user.recovery_hash):
        record_fail(key)
        raise HTTPException(400, "That business code and recovery code don't match.")
    if not user.is_active:
        raise HTTPException(403, "This account has been switched off. Contact the study team.")
    clear_fails(key); clear_fails(name)
    return _finish_reset(db, request, response, user, payload.new_password, "recovery code")


class ForgotIn(BaseModel):
    email: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=20)


SAME_ANSWER = {"ok": True, "message": "If that belongs to an account where it was confirmed, a reset code is on its way. It expires in 15 minutes."}


@router.post("/forgot")
def forgot(payload: ForgotIn, request: Request, db: Session = Depends(get_db)):
    """Sends a reset code by email or SMS. Always gives the same answer, so nobody can test which
    emails or numbers are registered."""
    try:
        if payload.phone:
            value, channel = clean_phone(payload.phone), "sms"
        else:
            value, channel = clean_email(payload.email or ""), "email"
    except HTTPException:
        return SAME_ANSWER
    key = f"forgot:{value}"
    check_locked(key)
    record_fail(key)  # counts requests; more than 5 in 10 minutes is blocked
    if channel == "email":
        c = find_by_email(db, value)
        targets = [c] if c and c.email_verified_at and c.user.is_active else []
    else:  # a number shared by several accounts can't be used to pick one
        matches = [c for c in find_by_phone(db, value) if c.phone_verified_at and c.user.is_active]
        targets = matches if len(matches) == 1 else []
    for c in targets:
        try:
            code = issue_code(db, c.user, "reset_password" if channel == "email" else "reset_sms")
        except HTTPException:
            continue  # a code went out less than a minute ago: same answer
        try:
            if channel == "email":
                send_code_email(value, code, "reset_password", who(c.user))
            else:
                send_code_sms(value, code, "reset_sms")
        except HTTPException:  # sending failed: say so (it's not a secret) and allow a retry
            discard_codes(db, c.user, "reset_password" if channel == "email" else "reset_sms"); db.commit()
            raise
        audit(db, request, c.user, "password.reset_requested", target=who(c.user), actor="anonymous", detail=f"by {channel}")
        db.commit()
    return SAME_ANSWER


class ResetCodeIn(BaseModel):
    email: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=20)
    code: str = Field(min_length=4, max_length=12)
    new_password: str = Field(min_length=MIN_PASSWORD, max_length=200)


@router.post("/reset-with-code")
def reset_with_code(payload: ResetCodeIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if payload.phone:
        matches = [c for c in find_by_phone(db, clean_phone(payload.phone)) if c.phone_verified_at]
        c, purpose, how = (matches[0] if len(matches) == 1 else None), "reset_sms", "SMS code"
    else:
        c, purpose, how = find_by_email(db, clean_email(payload.email or "")), "reset_password", "email code"
    if not c or not check_code(db, c.user, purpose, payload.code):
        db.commit()
        raise HTTPException(400, "That code is wrong or has expired. Ask for a new one.")
    if not c.user.is_active:
        raise HTTPException(403, "This account has been switched off. Contact the study team.")
    clear_fails(c.user.username)
    return _finish_reset(db, request, response, c.user, payload.new_password, how)


class ResetEmailIn(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    code: str = Field(min_length=4, max_length=12)
    new_password: str = Field(min_length=MIN_PASSWORD, max_length=200)


@router.post("/reset-with-email")
def reset_with_email(payload: ResetEmailIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Kept for older pages; same as /reset-with-code with an email."""
    return reset_with_code(ResetCodeIn(email=payload.email, code=payload.code, new_password=payload.new_password),
                           request, response, db)


# ---------- delete my account ----------
class DeleteAccountIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    confirm: str = Field(min_length=1, max_length=40)  # must be the business code (owners) or username (admins)


@router.post("/delete-account")
def delete_account(payload: DeleteAccountIn, request: Request, response: Response, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    """The owner erases their own account and every figure in it. Can't be undone."""
    from ..erase import anonymise_activity, erase_business, erase_user

    user = db.merge(user)
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(400, "Your password is wrong.")
    name = who(user)
    if payload.confirm.strip().lower() != name.lower():
        raise HTTPException(400, f"Type {name} exactly to confirm.")
    if user.role == "admin":
        admins = db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True)))
        if admins <= 1:
            raise HTTPException(400, "You're the only admin. Create another admin account first, so the study data isn't left without one.")
        if user.is_super_admin:
            raise HTTPException(400, "You're the super admin. Hand that role to another admin first (Admin page, Admins card), then delete your account.")

    # Tell them it's done, while we still have their email (sending must not block erasure)
    c = contact_of(db, user)
    if c:
        try:
            mailer.send(decrypt(c.email_enc), "Your Biashara Check account has been deleted",
                        f"Hello,\n\nThe account {name} and all its business figures and contact details have been "
                        "deleted from Biashara Check, as you asked. Nothing more will be sent to this address.\n\n"
                        "If you didn't do this, reply to this email straight away.\n")
        except Exception:  # noqa: BLE001
            pass

    audit(db, request, user, "account.deleted", target=name, detail="by the owner: figures, login and contact details erased")
    if user.business:
        erase_business(db, user.business)
    else:
        erase_user(db, user)
    db.flush()  # so the "account deleted" entry above is blanked too
    anonymise_activity(db, name, user.username)
    db.commit()
    response.delete_cookie("sid", path="/")
    return {"deleted": name}
