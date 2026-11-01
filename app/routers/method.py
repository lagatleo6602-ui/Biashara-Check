"""Evidence for the "How it's calculated" page: how the models were tested and how well they did.
Only summary numbers from the training run: no business's figures are in here."""
from fastapi import APIRouter, Depends

from ..auth import current_user
from ..models import User

router = APIRouter(prefix="/method", tags=["method"])


@router.get("/evidence")
def evidence(_: User = Depends(current_user)):
    from .. import risk
    if not risk.model_ready():
        return {"ready": False}
    from ml.predict import friendly
    from ml.train import load
    _, meta = load()
    meta = {k: v for k, v in (meta or {}).items() if k != "background"}
    for item in meta.get("importance", []):
        item["name"] = friendly(item["feature"])
    d = meta.get("distress") or {}
    if d.get("coefficients"):
        from ml.distress import NAMES
        for c in d["coefficients"]:
            c["name"] = NAMES.get(c["feature"], "Starting point (intercept)")
    return {"ready": True, **meta}
