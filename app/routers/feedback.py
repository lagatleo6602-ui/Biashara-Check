"""In-app user evaluation questionnaire (proposal Appendix B and section 3.11)."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user, require_admin
from ..contacts import audit
from ..database import get_db
from ..models import Feedback, User

router = APIRouter(tags=["feedback"])

QUESTIONS = [
    "Signing up and confirming my email was easy",
    "Adding a month of figures was easy",
    "Importing my M-Pesa statement saved me time",
    "I understood the risk check (low, moderate or high)",
    "The reasons given for my risk made sense for my business",
    "The suggested actions were practical",
    "The charts helped me see how my business is doing",
    "The app worked well on my phone",
    "I trust the app to keep my figures private",
    "I would keep using Biashara Check every month",
    "I would pay for Biashara Pro with M-Pesa",
]
GROUPS = {"Ease of use (TAM)": [0, 1, 2, 7], "Usefulness (TAM)": [3, 4, 5, 6], "Trust and intention": [8, 9, 10]}


class FeedbackIn(BaseModel):
    answers: list[int | None] = Field(min_length=len(QUESTIONS), max_length=len(QUESTIONS))
    liked: str = Field(default="", max_length=1000)
    confusing: str = Field(default="", max_length=1000)
    wish: str = Field(default="", max_length=1000)


@router.get("/feedback/questions")
def questions(db: Session = Depends(get_db), user: User = Depends(current_user)):
    code = user.business.code if user.business else user.username
    given = db.scalar(select(Feedback.id).where(Feedback.business_code == code).limit(1)) is not None
    return {"questions": QUESTIONS, "given": given}


@router.post("/feedback", status_code=201)
def give_feedback(payload: FeedbackIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if any(a is not None and not 1 <= a <= 5 for a in payload.answers):
        raise HTTPException(422, "Each answer must be from 1 to 5.")
    if all(a is None for a in payload.answers):
        raise HTTPException(422, "Answer at least one statement.")
    code = user.business.code if user.business else user.username
    db.add(Feedback(business_code=code, answers=json.dumps(payload.answers), liked=payload.liked.strip(),
                    confusing=payload.confusing.strip(), wish=payload.wish.strip()))
    audit(db, request, user, "feedback.given", target=code)
    db.commit()
    return {"ok": True}


def summary(db: Session) -> dict:
    rows = db.scalars(select(Feedback).order_by(Feedback.id.desc())).all()
    per_q = []
    for i, q in enumerate(QUESTIONS):
        vals = [a[i] for a in (json.loads(r.answers) for r in rows) if i < len(a) and a[i]]
        per_q.append({"question": q, "n": len(vals), "mean": round(sum(vals) / len(vals), 2) if vals else None})
    groups = []
    for name, idx in GROUPS.items():
        means = [per_q[i]["mean"] for i in idx if per_q[i]["mean"] is not None]
        groups.append({"group": name, "mean": round(sum(means) / len(means), 2) if means else None})
    comments = [{"business": r.business_code, "at": r.created_at.isoformat(timespec="minutes") if r.created_at else "",
                 "liked": r.liked, "confusing": r.confusing, "wish": r.wish}
                for r in rows if r.liked or r.confusing or r.wish][:50]
    return {"responses": len(rows), "questions": per_q, "groups": groups, "comments": comments}


@router.get("/admin/feedback")
def feedback_summary(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return summary(db)
