"""The risk check: the trained model when there is one, otherwise the simple rules in the dashboard.

Predictions are saved in the predictions table (one per business, month and model version), so the
history of each business's risk is kept, and a jump to a higher band can trigger an alert.
"""
import json
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Business, Prediction

log = logging.getLogger("uvicorn.error")
ORDER = {"Low": 0, "Moderate": 1, "High": 2}


def model_ready() -> bool:
    try:
        from ml.train import MODEL_FILE
        return MODEL_FILE.exists()
    except Exception:  # ML libraries not installed
        return False


def compute(db: Session, business: Business, lang: str = "en") -> dict | None:
    """Model prediction for the business's latest month, or None (no model, too few months, or an error).
    lang="sw" gives the reasons and tips in Kiswahili."""
    try:
        from ml.features import load_rows_for
        from ml.predict import predict_rows, translate
        rows = load_rows_for(db, business.id)
        r = predict_rows(rows)
        return translate(r, rows) if r and lang == "sw" else r
    except Exception:
        log.exception("Risk model failed for %s", business.code)
        return None


def compute_distress(db: Session, business: Business, lang: str = "en") -> dict | None:
    """The logistic-regression financial-distress check, or None."""
    try:
        from ml.distress import predict_rows
        from ml.features import load_rows_for
        return predict_rows(load_rows_for(db, business.id), lang=lang)
    except Exception:
        log.exception("Distress model failed for %s", business.code)
        return None


def compute_outlook(db: Session, business: Business, months: int, lang: str = "en") -> dict | None:
    """The 1-12 month outlook (ml/horizon.py), anchored to the 3-month check, with the test evidence for
    that horizon. None if there's no outlook model or too few months."""
    try:
        from ml.features import load_rows_for
        from ml.horizon import predict_rows
        from ml.predict import main_probability, translate
        from ml.train import load
        rows = load_rows_for(db, business.id)
        r = predict_rows(rows, months, main_probability(rows))
        if r is None:
            return None
        if lang == "sw":
            r = translate(r, rows)
        _, meta = load()
        r["evidence"] = ((meta or {}).get("horizon") or {}).get("horizons", {}).get(str(months))
        r["test_from"] = ((meta or {}).get("horizon") or {}).get("test_from")
        return r
    except Exception:
        log.exception("Outlook failed for %s", business.code)
        return None


def outlook_ready() -> bool:
    try:
        from ml.horizon import _file
        return _file().exists()
    except Exception:
        return False


def track_record(db: Session, business: Business) -> dict:
    """Checks this business was given in the past, set against what actually happened in the three
    months after each one. Only checks whose three following months are now recorded count."""
    from .models import MonthlyRecord
    recs = {r.month: float(r.revenue) - float(r.cogs) - float(r.operating_expenses)
            for r in db.scalars(select(MonthlyRecord).where(MonthlyRecord.business_id == business.id)).all()}

    def plus(m: date, n: int) -> date:
        y, mo = divmod(m.month - 1 + n, 12)
        return date(m.year + y, mo + 1, 1)

    out = []
    for h in history(db, business, limit=60):
        m = date.fromisoformat(h["month"] + "-01")
        nxt = [plus(m, i) for i in (1, 2, 3)]
        if not all(x in recs for x in nxt):
            continue
        losses = [f"{x:%Y-%m}" for x in nxt if recs[x] < 0]
        out.append({**h, "loss_followed": bool(losses), "loss_months": losses,
                    "right": (h["band"] == "High" and bool(losses)) or (h["band"] == "Low" and not losses)
                             if h["band"] != "Moderate" else None})
    judged = [x for x in out if x["right"] is not None]
    return {"checks": out, "judged": len(judged), "right": sum(1 for x in judged if x["right"])}


def save(db: Session, business: Business, r: dict) -> tuple[Prediction, str | None]:
    """Stores the prediction. Returns (row, band of the previous prediction for an earlier month or model)."""
    month = date.fromisoformat(r["as_of"] + "-01")
    prev = db.scalar(select(Prediction).where(Prediction.business_id == business.id)
                     .order_by(Prediction.as_of_month.desc(), Prediction.id.desc()))
    row = db.scalar(select(Prediction).where(Prediction.business_id == business.id, Prediction.as_of_month == month,
                                             Prediction.model_version == r["model_version"]))
    expl = json.dumps([{"f": x["feature"], "i": x["impact"]} for x in r["reasons"]])[:1000]
    prev_band = prev.risk_band if prev and prev is not row else None
    if row is None:
        row = Prediction(business_id=business.id, as_of_month=month, model_version=r["model_version"],
                         probability=r["probability"], risk_band=r["band"], explanation=expl)
        db.add(row)
    else:
        prev_band = prev_band if prev is not row else None
        row.probability, row.risk_band, row.explanation = r["probability"], r["band"], expl
    return row, prev_band


def history(db: Session, business: Business, limit: int = 24) -> list[dict]:
    """Latest prediction per month, oldest first."""
    rows = db.scalars(select(Prediction).where(Prediction.business_id == business.id)
                      .order_by(Prediction.as_of_month.desc(), Prediction.id.desc())).all()
    seen, out = set(), []
    for p in rows:
        if p.as_of_month in seen:
            continue
        seen.add(p.as_of_month)
        out.append({"month": f"{p.as_of_month:%Y-%m}", "probability": float(p.probability), "band": p.risk_band})
        if len(out) == limit:
            break
    return out[::-1]


def _check_outlook(db: Session, b: Business) -> None:
    """The owner's chosen outlook (1-12 months): remember its band, and alert when it goes up a band."""
    try:
        from .notify import _owner, outlook_alert
        own = _owner(db, b)
        h = (own.outlook_months if own else 3) or 3
        if h == 3 or not outlook_ready():   # 3 months is the main risk check, which has its own alert
            return
        ol = compute_outlook(db, b, h)
        if not ol:
            return
        prev = b.outlook_band if b.outlook_for == h else None
        b.outlook_band, b.outlook_for = ol["band"], h
        db.commit()
        if prev and ORDER[ol["band"]] > ORDER[prev] and not b.is_synthetic:
            outlook_alert(db, b, prev, ol)
            db.commit()
    except Exception:
        log.exception("Outlook check failed for %s", b.code)


def refresh(business_id: int) -> None:
    """After figures change: predict again, save it, and alert the owner if the risk went up a band.
    Runs after the response is sent, in its own database session, and never raises."""
    from .database import SessionLocal

    try:
        with SessionLocal() as db:
            b = db.get(Business, business_id)
            if b is None or not model_ready():
                return
            r = compute(db, b)
            if r is None:
                return
            _, prev_band = save(db, b, r)
            db.commit()
            if prev_band and ORDER[r["band"]] > ORDER[prev_band] and not b.is_synthetic:
                try:
                    from .notify import risk_alert
                    risk_alert(db, b, prev_band, r)
                    db.commit()
                except Exception:
                    log.exception("Risk alert failed for %s", b.code)
            _check_outlook(db, b)
    except Exception:
        log.exception("Risk refresh failed")
