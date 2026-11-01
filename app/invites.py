"""Super admin and one-time admin invite codes.

There is always exactly one super admin while any admin exists. Only they can generate
an admin code. Each code works once, expires after INVITE_HOURS, and generating a new
one cancels the old one. Only a hash of the code is stored."""
import hashlib
import secrets
from datetime import timedelta

from fastapi import Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .auth import normalise_code, require_admin, utcnow
from .models import AdminInvite, User

INVITE_HOURS = 24
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/O or 1/l


def _hash(code: str) -> str:
    return hashlib.sha256(("admin-invite:" + normalise_code(code)).encode()).hexdigest()


def new_code() -> str:
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(4))


def active_invite(db: Session) -> AdminInvite | None:
    return db.scalar(select(AdminInvite)
                     .where(AdminInvite.used_at.is_(None), AdminInvite.cancelled_at.is_(None),
                            AdminInvite.expires_at > utcnow())
                     .order_by(AdminInvite.id.desc()))


def cancel_open(db: Session) -> int:
    """Cancels every unused code. Returns how many were still open."""
    return db.execute(update(AdminInvite)
                      .where(AdminInvite.used_at.is_(None), AdminInvite.cancelled_at.is_(None))
                      .values(cancelled_at=utcnow())).rowcount or 0


def create_invite(db: Session, by: User) -> tuple[str, AdminInvite]:
    cancel_open(db)
    code = new_code()
    now = utcnow()
    inv = AdminInvite(code_hash=_hash(code), created_by=by.username, created_at=now,
                      expires_at=now + timedelta(hours=INVITE_HOURS))
    db.add(inv)
    db.flush()
    return code, inv


def match_invite(db: Session, code: str) -> AdminInvite | None:
    inv = active_invite(db)
    if inv and secrets.compare_digest(inv.code_hash, _hash(code)):
        return inv
    return None


def any_admin(db: Session) -> bool:
    return db.scalar(select(User.id).where(User.role == "admin").limit(1)) is not None


def super_admin(db: Session) -> User | None:
    return db.scalar(select(User).where(User.role == "admin", User.is_super_admin.is_(True),
                                        User.is_active.is_(True)).order_by(User.id))


def ensure_super_admin(db: Session) -> User | None:
    """Makes sure exactly one active admin is the super admin: keeps the current one,
    otherwise promotes the oldest active admin (e.g. after an upgrade)."""
    current = super_admin(db)
    if current is None:
        current = db.scalar(select(User).where(User.role == "admin", User.is_active.is_(True)).order_by(User.id))
        if current is None:
            return None
        current.is_super_admin = True
    db.execute(update(User).where(User.is_super_admin.is_(True), User.id != current.id).values(is_super_admin=False))
    return current


def require_super_admin(user: User = Depends(require_admin)) -> User:
    if not user.is_super_admin:
        raise HTTPException(403, "Only the super admin can do this.")
    return user
