"""Database tables.

Data Protection Act 2019: no owner names, phone numbers or ID numbers are stored.
Each business is identified only by a pseudonymous code (e.g. SME-001).
"""
from datetime import date, datetime

from sqlalchemy import (BigInteger, Date, DateTime, Enum, ForeignKey, Integer,
                        Numeric, String, Text, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

Money = Numeric(14, 2)


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    sector: Mapped[str] = mapped_column(String(20))  # key from app/sectors.py
    start_date: Mapped[date | None] = mapped_column(Date)
    is_synthetic: Mapped[bool] = mapped_column(default=False)
    pro_until: Mapped[datetime | None] = mapped_column(DateTime)       # Biashara Pro active until (UTC)
    pro_source: Mapped[str | None] = mapped_column(String(10))         # "mpesa" or "admin"
    pro_plan: Mapped[str | None] = mapped_column(String(10))           # month / year: the plan last paid for
    auto_renew: Mapped[bool] = mapped_column(default=False)            # send an M-Pesa prompt before Pro ends
    renew_phone_enc: Mapped[str | None] = mapped_column(String(500))   # encrypted number for renewal prompts
    renew_notice_for: Mapped[datetime | None] = mapped_column(DateTime)  # pro_until the "renews soon" notice was sent for
    renew_tried_for: Mapped[datetime | None] = mapped_column(DateTime)   # pro_until the renewal prompt was sent for
    renew_cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    outlook_band: Mapped[str | None] = mapped_column(String(10))       # last band of the owner's chosen outlook
    outlook_for: Mapped[int | None] = mapped_column(Integer)           # ... and for how many months ahead
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    records: Mapped[list["MonthlyRecord"]] = relationship(
        back_populates="business", cascade="all, delete-orphan", order_by="MonthlyRecord.month"
    )


class MonthlyRecord(Base):
    """One business-month: the unit of analysis (proposal 1.10)."""

    __tablename__ = "monthly_records"
    __table_args__ = (UniqueConstraint("business_id", "month", name="uq_business_month"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    month: Mapped[date] = mapped_column(Date)  # first day of the month

    revenue: Mapped[float] = mapped_column(Money)
    cogs: Mapped[float] = mapped_column(Money)
    operating_expenses: Mapped[float] = mapped_column(Money)
    cash_inflows: Mapped[float] = mapped_column(Money)
    cash_outflows: Mapped[float] = mapped_column(Money)
    mobile_money_receipts: Mapped[float] = mapped_column(Money, default=0)
    closing_stock: Mapped[float] = mapped_column(Money, default=0)
    outstanding_debt: Mapped[float] = mapped_column(Money, default=0)
    transaction_count: Mapped[int] = mapped_column(BigInteger, default=0)

    business: Mapped[Business] = relationship(back_populates="records")

    @property
    def net_operating_result(self) -> float:
        return float(self.revenue) - float(self.cogs) - float(self.operating_expenses)


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    as_of_month: Mapped[date] = mapped_column(Date)
    probability: Mapped[float] = mapped_column(Numeric(5, 4))
    risk_band: Mapped[str] = mapped_column(Enum("Low", "Moderate", "High", name="risk_band"))
    model_version: Mapped[str] = mapped_column(String(50))
    explanation: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class User(Base):
    """A login. Owners are tied to one business; admins (the researcher) see everything.
    The username is the business code for owners, never a real name."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(Enum("owner", "admin", name="user_role"), default="owner")
    business_id: Mapped[int | None] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    is_active: Mapped[bool] = mapped_column(default=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime)
    must_change_password: Mapped[bool] = mapped_column(default=False)  # after an admin reset
    is_super_admin: Mapped[bool] = mapped_column(default=False)        # the one admin who can invite admins
    tour_done_at: Mapped[datetime | None] = mapped_column(DateTime)    # saw (or skipped) the welcome walkthrough
    notify_reports: Mapped[bool] = mapped_column(default=True)    # email the monthly report after adding a month
    notify_reminders: Mapped[bool] = mapped_column(default=True)  # remind me to add last month's figures
    notify_alerts: Mapped[bool] = mapped_column(default=True)     # tell me when my risk goes up
    language: Mapped[str] = mapped_column(String(5), default="en")  # en or sw
    outlook_months: Mapped[int] = mapped_column(Integer, default=3)  # how far ahead the owner wants to look (1-12)
    recovery_hash: Mapped[str | None] = mapped_column(String(200))     # hashed one-time recovery code
    last_login: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    business: Mapped[Business | None] = relationship()


class LoginSession(Base):
    """Server-side sessions, so logging out really ends the session."""

    __tablename__ = "login_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship()


class Contact(Base):
    """Email and phone, kept apart from the business figures and encrypted at rest.
    *_hash columns are keyed hashes, so we can look people up without decrypting everything."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    email_enc: Mapped[str] = mapped_column(String(500))
    email_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    phone_enc: Mapped[str] = mapped_column(String(500))
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    contact_consent_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship()


class OneTimeCode(Base):
    """6-digit codes for email verification and password reset. Only a hash is stored."""

    __tablename__ = "one_time_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(20))  # verify_email, verify_phone, reset_password, reset_sms
    code_hash: Mapped[str] = mapped_column(String(200))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    """Who did what, when: accountability for owners and admins alike."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    actor: Mapped[str] = mapped_column(String(60))          # username at the time, or "anonymous"
    actor_role: Mapped[str] = mapped_column(String(10))
    action: Mapped[str] = mapped_column(String(40), index=True)
    target: Mapped[str] = mapped_column(String(60), default="")
    detail: Mapped[str] = mapped_column(String(255), default="")
    ip: Mapped[str] = mapped_column(String(45), default="")


class AdminInvite(Base):
    """One-time code the super admin generates to let one new admin sign up.
    Only a hash is stored. Generating a new code cancels the previous unused one."""

    __tablename__ = "admin_invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    used_by: Mapped[str | None] = mapped_column(String(40))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)


class Payment(Base):
    """An M-Pesa STK Push payment for Biashara Pro.
    Kept after a business is deleted (receipts are financial records), but unlinked and with the phone blanked."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int | None] = mapped_column(ForeignKey("businesses.id", ondelete="SET NULL"), index=True)
    business_code: Mapped[str] = mapped_column(String(20))
    username: Mapped[str] = mapped_column(String(40))
    plan: Mapped[str] = mapped_column(String(10))                 # month / year
    amount: Mapped[int] = mapped_column(Integer)                  # KES
    phone_masked: Mapped[str] = mapped_column(String(20), default="")
    mode: Mapped[str] = mapped_column(String(10))                 # test / sandbox / live
    checkout_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    merchant_request_id: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending / paid / failed / cancelled
    kind: Mapped[str] = mapped_column(String(10), default="new")          # new (owner pressed Pay) / renewal (automatic prompt)
    auto_renew: Mapped[bool] = mapped_column(default=False)               # owner chose automatic renewal with this payment
    result_desc: Mapped[str] = mapped_column(String(255), default="")
    receipt: Mapped[str] = mapped_column(String(30), default="")
    applied: Mapped[bool] = mapped_column(default=False)          # Pro time added (only once)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class PendingSignup(Base):
    """A sign-up waiting for its email to be confirmed. Nothing is created until the code is entered.
    The details are encrypted; the password is already hashed. Rows expire after 15 minutes."""

    __tablename__ = "pending_signups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))                     # owner / admin
    email_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    data_enc: Mapped[str] = mapped_column(Text)
    code_hash: Mapped[str] = mapped_column(String(200))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    sent_at: Mapped[datetime] = mapped_column(DateTime)


class Feedback(Base):
    """The user evaluation questionnaire (proposal Appendix B), filled in inside the app."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_code: Mapped[str] = mapped_column(String(20), index=True)
    answers: Mapped[str] = mapped_column(String(200))       # JSON list of 1-5 ratings, one per statement
    liked: Mapped[str] = mapped_column(String(1000), default="")
    confusing: Mapped[str] = mapped_column(String(1000), default="")
    wish: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
