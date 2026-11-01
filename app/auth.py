"""Password hashing, sessions and access rules (proposal 3.12: role-based access)."""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Business, LoginSession, User

COOKIE = "sid"
SESSION_HOURS = 12
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"  # set true when hosted on https
MIN_PASSWORD = 8


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------- passwords (scrypt, from the standard library) ----------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    return hmac.compare_digest(digest.hex(), digest_hex)


def temp_password() -> str:
    """Easy to read out over the phone: no 0/O or 1/l."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


def recovery_code() -> str:
    """16 characters in 4 groups, written down once by the owner at sign-up."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4))


def normalise_code(code: str) -> str:
    return "".join(ch for ch in code.lower() if ch.isalnum())


# ---------- sessions ----------
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(db: Session, user: User, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    db.execute(delete(LoginSession).where(LoginSession.expires_at < utcnow()))  # tidy old ones
    db.add(LoginSession(token_hash=_token_hash(token), user_id=user.id,
                        expires_at=utcnow() + timedelta(hours=SESSION_HOURS)))
    user.last_login = utcnow()
    db.commit()
    response.set_cookie(COOKIE, token, max_age=SESSION_HOURS * 3600, httponly=True,
                        samesite="lax", secure=COOKIE_SECURE, path="/")


def end_other_sessions(db: Session, user: User, request: Request) -> None:
    """After a password change, log out every other device."""
    keep = request.cookies.get(COOKIE)
    q = delete(LoginSession).where(LoginSession.user_id == user.id)
    if keep:
        q = q.where(LoginSession.token_hash != _token_hash(keep))
    db.execute(q)


def end_session(db: Session, request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == _token_hash(token)))
        db.commit()
    response.delete_cookie(COOKIE, path="/")


# ---------- failed-login lockout (in memory; resets when the server restarts) ----------
_fails: dict[str, tuple[int, datetime]] = {}
MAX_FAILS, LOCK_MINUTES = 5, 10


def check_locked(username: str) -> None:
    count, until = _fails.get(username, (0, utcnow()))
    if count >= MAX_FAILS and until > utcnow():
        mins = int((until - utcnow()).total_seconds() // 60) + 1
        raise HTTPException(429, f"Too many wrong passwords. Try again in {mins} minute{'s' if mins > 1 else ''}.")


def record_fail(username: str) -> None:
    count, _ = _fails.get(username, (0, utcnow()))
    _fails[username] = (count + 1, utcnow() + timedelta(minutes=LOCK_MINUTES))


def clear_fails(username: str) -> None:
    _fails.pop(username, None)


# ---------- dependencies used by the routes ----------
def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Please log in.")
    sess = db.scalar(select(LoginSession).where(LoginSession.token_hash == _token_hash(token)))
    if not sess or sess.expires_at < utcnow() or not sess.user.is_active:
        raise HTTPException(401, "Your session has ended. Please log in again.")
    return sess.user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Admins only.")
    return user


def business_for(code: str, user: User, db: Session) -> Business:
    """Owners can only reach their own business. Others get 404 so codes aren't revealed."""
    business = db.scalar(select(Business).where(Business.code == code))
    if not business or (user.role != "admin" and user.business_id != business.id):
        raise HTTPException(404, f"Business {code} not found")
    return business
