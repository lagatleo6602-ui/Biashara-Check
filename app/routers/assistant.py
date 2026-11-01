"""The built-in assistant (app/assistant.py). Free: no outside AI service, nothing leaves the app.
Messages are answered and forgotten; only the topic is logged."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import current_user, utcnow
from ..contacts import audit
from ..database import get_db
from ..models import AuditLog, User

router = APIRouter(prefix="/assistant", tags=["assistant"])
PER_DAY = 300  # plenty for a person; stops a script from hammering the server


class AskIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    context: dict = Field(default_factory=dict)


@router.post("/ask")
def ask(payload: AskIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from .. import assistant
    n = db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.action == "assistant.asked", AuditLog.actor == user.username[:60], AuditLog.at >= utcnow() - timedelta(days=1)))
    if n >= PER_DAY:
        raise HTTPException(429, "You've asked a lot of questions today. Please try again tomorrow.")
    ctx = {k: v for k, v in payload.context.items() if k in ("figure", "month") and isinstance(v, str) and len(v) < 40}
    out = assistant.answer(db, user, user.business, payload.message, ctx)
    audit(db, request, user, "assistant.asked", target=user.business.code if user.business else "", detail=out["intent"])
    db.commit()
    return out
