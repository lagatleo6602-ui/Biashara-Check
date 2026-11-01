"""Right to erasure (Data Protection Act 2019): one place that removes a person's data,
used both when an owner deletes their own account and when an admin deletes a business."""
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from .models import AuditLog, Business, Contact, LoginSession, OneTimeCode, Payment, Prediction, User


def erase_user(db: Session, user: User) -> None:
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    db.execute(delete(Contact).where(Contact.user_id == user.id))
    db.execute(delete(OneTimeCode).where(OneTimeCode.user_id == user.id))
    db.delete(user)


def erase_business(db: Session, business: Business) -> None:
    """Business, every monthly record, predictions, logins and contact details."""
    for u in db.scalars(select(User).where(User.business_id == business.id)).all():
        erase_user(db, u)
    db.execute(delete(Prediction).where(Prediction.business_id == business.id))
    # payment receipts are financial records: keep them, but unlink and blank the phone
    db.execute(update(Payment).where(Payment.business_id == business.id).values(business_id=None, phone_masked=""))
    db.delete(business)  # monthly records go with it (cascade)


def anonymise_activity(db: Session, *names: str) -> None:
    """Keep the activity log for accountability, but blank IP addresses tied to this person."""
    names = [n for n in names if n]
    if not names:
        return
    lowered = [n.lower() for n in names] + [n.upper() for n in names] + list(names)
    db.execute(update(AuditLog)
               .where(or_(AuditLog.actor.in_(lowered), AuditLog.target.in_(lowered)))
               .values(ip=""))
