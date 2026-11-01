"""Train and compare models for 90-day operating-loss risk (proposal section 3.6).

    python -m ml.train                 # train on everything in the database
    python -m ml.train --real-only     # leave synthetic businesses out

Steps
1. Build features and labels from every business-month (ml/features.py).
2. Time-based split: the latest 20% of months are the test set. Training rows stop three
   months before the test period starts, because their labels look three months ahead
   (otherwise the test period would leak into training).
3. Train logistic regression (baseline), random forest, XGBoost and LightGBM, all weighted
   for the rarer loss class.
4. Compare on the test set: PR-AUC (main), ROC-AUC, recall, precision, F1, Brier score.
5. The best model by PR-AUC is refitted on all labelled rows and saved to ml/artifacts/,
   with SHAP feature importance from the test set.
"""
import argparse
import json
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from . import features as F

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
MODEL_FILE = ARTIFACTS / "model.joblib"
META_FILE = ARTIFACTS / "model_meta.json"
BANDS = {"moderate": 0.35, "high": 0.60}  # probability thresholds for the risk bands
MIN_ROWS, MIN_EACH_CLASS = 150, 15
MODEL_NAMES = {"logreg": "Logistic regression (baseline)", "rf": "Random forest",
               "xgb": "XGBoost", "lgbm": "LightGBM"}


class NotEnoughData(Exception):
    pass


def make_model(kind: str, pos_weight: float):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    if kind == "logreg":
        return Pipeline([("prep", Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())])),
                         ("clf", LogisticRegression(max_iter=2000, class_weight="balanced", C=0.5))])
    if kind == "rf":
        return Pipeline([("prep", SimpleImputer(strategy="median")),
                         ("clf", RandomForestClassifier(n_estimators=300, min_samples_leaf=5, class_weight="balanced",
                                                        n_jobs=-1, random_state=42))])
    if kind == "xgb":
        from xgboost import XGBClassifier
        return Pipeline([("prep", "passthrough"),
                         ("clf", XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.9,
                                               colsample_bytree=0.9, scale_pos_weight=pos_weight,
                                               eval_metric="logloss", random_state=42, n_jobs=2))])
    if kind == "lgbm":
        from lightgbm import LGBMClassifier
        return Pipeline([("prep", "passthrough"),
                         ("clf", LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15,
                                                min_child_samples=20, subsample=0.9, subsample_freq=1,
                                                colsample_bytree=0.9, class_weight="balanced",
                                                random_state=42, verbose=-1))])
    raise ValueError(kind)


def transform(model, X: pd.DataFrame) -> np.ndarray:
    prep = model.named_steps["prep"]
    return X.values if prep == "passthrough" else prep.transform(X)


def shap_values(model, X: pd.DataFrame, background: pd.DataFrame | None = None) -> np.ndarray:
    """SHAP values (log-odds of a loss) for each row and feature."""
    import shap

    clf = model.named_steps["clf"]
    Xt = transform(model, X)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if model.steps[-1][1].__class__.__name__ == "LogisticRegression":
            bg = transform(model, background if background is not None else X)
            ex = shap.LinearExplainer(clf, shap.maskers.Independent(bg, max_samples=200))
        else:
            ex = shap.TreeExplainer(clf)
        sv = ex.shap_values(Xt)
    if isinstance(sv, list):
        sv = sv[1]
    sv = np.asarray(sv)
    if sv.ndim == 3:
        sv = sv[:, :, 1]
    return sv


def band(p: float) -> str:
    return "High" if p >= BANDS["high"] else "Moderate" if p >= BANDS["moderate"] else "Low"


def _metrics(y, p) -> dict:
    from sklearn.metrics import (average_precision_score, brier_score_loss, confusion_matrix, f1_score,
                                 precision_score, recall_score, roc_auc_score)
    pred = (p >= 0.5).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {"pr_auc": round(float(average_precision_score(y, p)), 4),
            "roc_auc": round(float(roc_auc_score(y, p)), 4),
            "recall": round(float(recall_score(y, pred, zero_division=0)), 4),
            "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
            "f1": round(float(f1_score(y, pred, zero_division=0)), 4),
            "brier": round(float(brier_score_loss(y, p)), 4),
            "confusion": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}}


CAL_EDGES = [0.0, 0.10, 0.20, 0.35, 0.50, 0.60, 0.80, 1.0001]


def calibration(y, p) -> list[dict]:
    """Predicted chance against what actually happened, in bins of predicted probability.
    If the model is honest, about 30 in 100 of the months it gave 30% should be followed by the event."""
    y, p = np.asarray(y), np.asarray(p)
    out = []
    for a, b in zip(CAL_EDGES, CAL_EDGES[1:]):
        m = (p >= a) & (p < b)
        if m.sum():
            out.append({"from": round(a, 2), "to": round(min(b, 1.0), 2), "n": int(m.sum()),
                        "predicted": round(float(p[m].mean()), 4), "actual": round(float(y[m].mean()), 4),
                        "events": int(y[m].sum())})
    return out


def by_band(y, p) -> list[dict]:
    """For each risk band: how many test months landed there and how many were followed by a loss."""
    y, p = np.asarray(y), np.asarray(p)
    out = []
    for name, a, b in (("Low", 0.0, BANDS["moderate"]), ("Moderate", BANDS["moderate"], BANDS["high"]), ("High", BANDS["high"], 1.0001)):
        m = (p >= a) & (p < b)
        out.append({"band": name, "n": int(m.sum()), "losses": int(y[m].sum()),
                    "actual": round(float(y[m].mean()), 4) if m.sum() else None,
                    "predicted": round(float(p[m].mean()), 4) if m.sum() else None})
    return out


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def calibrate(p, scaler: dict | None):
    """Platt scaling: chance = 1 / (1 + e^-(a * logit(p) + b)). Keeps the order of predictions (so PR-AUC,
    ROC-AUC and SHAP reasons are unchanged) but makes the % match how often losses really follow."""
    if not scaler:
        return np.asarray(p, dtype=float)
    return 1 / (1 + np.exp(-(scaler["a"] * _logit(p) + scaler["b"])))


def fit_scaler(kind: str, tr: pd.DataFrame) -> dict | None:
    """Fits the Platt scaler on a calibration window: the last 20% of the training months, which a copy of
    the model (trained on the months before them, with the same 3-month gap) has not seen."""
    from sklearn.linear_model import LogisticRegression
    fit, cal, _ = split(tr)
    if len(fit) < MIN_ROWS or cal["label"].nunique() < 2 or fit["label"].nunique() < 2:
        return None
    m = make_model(kind, float((fit["label"] == 0).sum() / max(1, (fit["label"] == 1).sum())))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m.fit(fit[F.FEATURES], fit["label"].astype(int))
        x = _logit(m.predict_proba(cal[F.FEATURES])[:, 1]).reshape(-1, 1)
        lr = LogisticRegression(C=1e6, max_iter=1000).fit(x, cal["label"].astype(int))
    return {"a": round(float(lr.coef_[0][0]), 5), "b": round(float(lr.intercept_[0]), 5), "rows": int(len(cal))}


def rule_baseline(te: pd.DataFrame) -> dict:
    """The simple rule with no machine learning, for comparison: predict a loss when the
    last 3 months' average profit margin was below zero."""
    y = te["label"].astype(int).values
    pred = (te["margin_3m"].fillna(0).values < 0).astype(float)
    out = _metrics(y, pred)
    out["name"] = "Simple rule (no ML): last 3 months' average margin below zero"
    return out


def split(X: pd.DataFrame, test_share: float = 0.2):
    months = np.sort(X["month"].unique())
    cut = months[int(len(months) * (1 - test_share))]
    gap = pd.Timestamp(cut) - pd.DateOffset(months=3)
    return X[X["month"] < gap], X[X["month"] >= cut], pd.Timestamp(cut)


def train(db=None, real_only: bool = False, frame: pd.DataFrame | None = None) -> dict:
    t0 = time.time()
    if frame is None:
        from app.database import SessionLocal
        own = db is None
        db = db or SessionLocal()
        try:
            frame = F.records_frame(F.load_rows(db))
        finally:
            if own:
                db.close()
    X = F.build(frame)
    if real_only and len(X):
        X = X[~X["is_synthetic"]]
    lab = X[X["label"].notna()].copy()
    n_pos = int(lab["label"].sum()) if len(lab) else 0
    if len(lab) < MIN_ROWS or n_pos < MIN_EACH_CLASS or len(lab) - n_pos < MIN_EACH_CLASS:
        raise NotEnoughData(f"Not enough data to train yet: {len(lab)} business-months with a known 90-day outcome "
                            f"({n_pos} followed by a loss). Need at least {MIN_ROWS}, with {MIN_EACH_CLASS} of each kind. "
                            "Add more months, or generate synthetic businesses on the admin page.")
    tr, te, cut = split(lab)
    if te["label"].nunique() < 2 or tr["label"].nunique() < 2:
        raise NotEnoughData("The test period has only one kind of outcome. Add more months of data and try again.")
    pos_weight = float((tr["label"] == 0).sum() / max(1, (tr["label"] == 1).sum()))

    results, fitted, probs = {}, {}, {}
    yt = te["label"].astype(int).values
    for kind in MODEL_NAMES:
        m = make_model(kind, pos_weight)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m.fit(tr[F.FEATURES], tr["label"].astype(int))
        p = m.predict_proba(te[F.FEATURES])[:, 1]
        results[kind] = _metrics(yt, p)
        fitted[kind], probs[kind] = m, p
    best = max(results, key=lambda k: (results[k]["pr_auc"], results[k]["roc_auc"]))
    # the models are trained with extra weight on the rarer loss months, which pushes their % up; Platt scaling,
    # fitted on training months only, brings the % back in line with how often losses really happen
    scaler = fit_scaler(best, tr)
    raw = {"brier": results[best]["brier"], "calibration": calibration(yt, probs[best])}
    pb = calibrate(probs[best], scaler)
    results[best] = {**_metrics(yt, pb), "uncalibrated_brier": raw["brier"]}
    evidence = {"calibration": calibration(yt, pb), "bands": by_band(yt, pb), "scaler": scaler,
                "uncalibrated": raw,
                "rule": rule_baseline(te), "test_positive_rate": round(float(yt.mean()), 4),
                "test_businesses": int(te["business_id"].nunique()),
                "test_months": [te["month"].min().strftime("%Y-%m"), te["month"].max().strftime("%Y-%m")],
                "train_months": [tr["month"].min().strftime("%Y-%m"), tr["month"].max().strftime("%Y-%m")]}

    # global explanation: mean |SHAP| on the test set, from the model as evaluated
    # (on up to 400 test months: SHAP on thousands of rows of a 300-tree forest takes minutes, and a sample
    # gives the same ranking)
    te_shap = te[F.FEATURES].sample(min(400, len(te)), random_state=3)
    sv = shap_values(fitted[best], te_shap, background=tr[F.FEATURES].sample(min(200, len(tr)), random_state=1))
    imp = pd.Series(np.abs(sv).mean(axis=0), index=F.FEATURES)
    # report the two time-of-year columns and the business-type columns as one each
    imp["month_sin"] = imp["month_sin"] + imp["month_cos"]
    imp["sector_retail"] = imp[F.SECTOR_FEATURES].sum()
    imp = imp.drop(["month_cos"] + [f for f in F.SECTOR_FEATURES if f != "sector_retail"])
    imp = imp.rename({"month_sin": "time_of_year", "sector_retail": "business_type"}).sort_values(ascending=False)
    importance = [{"feature": f, "value": round(float(v), 4)} for f, v in imp.head(12).items() if v > 0]

    final = make_model(best, float((lab["label"] == 0).sum() / max(1, n_pos)))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        final.fit(lab[F.FEATURES], lab["label"].astype(int))
    # the statistical financial-distress model (logistic regression), trained on the same split
    from . import distress
    try:
        distress_meta = distress.train(X[~X["is_synthetic"]] if real_only else X)
    except NotEnoughData as exc:
        distress_meta = {"error": str(exc)}

    # the 1-12 month outlook, anchored to this model's 3-month %
    from . import horizon
    try:
        horizon_meta = horizon.train(X[~X["is_synthetic"]] if real_only else X, best, scaler)
    except NotEnoughData as exc:
        horizon_meta = {"error": str(exc)}

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    version = f"{best}-{stamp}"
    meta = {
        "version": version, "best": best, "best_name": MODEL_NAMES[best],
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(time.time() - t0, 1), "real_only": real_only,
        "rows": {"labelled": int(len(lab)), "train": int(len(tr)), "test": int(len(te)),
                 "positives": n_pos, "positive_rate": round(n_pos / len(lab), 4),
                 "real": int((~lab["is_synthetic"]).sum()), "synthetic": int(lab["is_synthetic"].sum()),
                 "businesses": int(lab["business_id"].nunique())},
        "test_from": cut.strftime("%Y-%m"),
        "models": {k: {"name": MODEL_NAMES[k], **v} for k, v in results.items()},
        "importance": importance, "bands": BANDS, "features": F.FEATURES,
        "evidence": evidence, "distress": distress_meta, "horizon": horizon_meta,
        "background": tr[F.FEATURES].sample(min(100, len(tr)), random_state=2).to_dict("list"),
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": final, "version": version, "features": F.FEATURES, "kind": best, "scaler": scaler}, MODEL_FILE)
    META_FILE.write_text(json.dumps(meta, indent=2))
    _cache.clear()
    return {k: v for k, v in meta.items() if k != "background"}


# ---------- loading the saved model ----------
_cache: dict = {}


def load():
    """(bundle, meta) of the saved model, or (None, None). Reloaded when the file changes."""
    if not MODEL_FILE.exists():
        return None, None
    mtime = MODEL_FILE.stat().st_mtime
    if _cache.get("mtime") != mtime:
        bundle = joblib.load(MODEL_FILE)
        meta = json.loads(META_FILE.read_text()) if META_FILE.exists() else {}
        _cache.update(mtime=mtime, bundle=bundle, meta=meta)
    return _cache["bundle"], _cache["meta"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Train the 90-day loss-risk model.")
    ap.add_argument("--real-only", action="store_true")
    a = ap.parse_args()
    out = train(real_only=a.real_only)
    print(f"Best: {out['best_name']} ({out['version']}), trained in {out['seconds']} s on {out['rows']['labelled']} rows")
    for k, m in [*out["models"].items(), ("rule", out["evidence"]["rule"])]:
        print(f"  {m['name'][:32]:32s} PR-AUC {m['pr_auc']:.3f}  ROC-AUC {m['roc_auc']:.3f}  recall {m['recall']:.3f}  "
              f"precision {m['precision']:.3f}  Brier {m['brier']:.3f}")
    print("Calibration of the best model on the test months (predicted -> actual):")
    for c in out["evidence"]["calibration"]:
        print(f"  {c['from']:.0%}-{c['to']:.0%}: {c['n']:5d} months, predicted {c['predicted']:.0%}, actual {c['actual']:.0%}")
    hz = out["horizon"]
    if "error" in hz:
        print("Outlook (1-12 months):", hz["error"])
    else:
        print("Outlook (1-12 months), test from", hz["test_from"], "- per horizon: tested months, loss share, ROC-AUC, Brier")
        for h, m in hz["horizons"].items():
            print(f"  {int(h):2d} months: " + (f"{m['n']:6d}  {m['positive_rate']:.0%}  {m['roc_auc']:.3f}  {m['brier']:.3f}"
                                                if m.get("enough") else f"{m['n']:6d}  (too few test months)"))
    d = out["distress"]
    if "error" in d:
        print("Distress model:", d["error"])
    else:
        t = d["test"]
        print(f"Distress model (logistic regression): ROC-AUC {t['roc_auc']:.3f}  PR-AUC {t['pr_auc']:.3f}  Brier {t['brier']:.3f}  "
              f"Hosmer-Lemeshow p = {t['hosmer_lemeshow']['p_value']}  McFadden R2 {d['mcfadden_r2']}")
        for c in d["coefficients"]:
            print(f"  {c['feature']:22s} b = {c['coef']:+.3f}  OR = {c['odds_ratio']:.2f}  p = {c['p_value']}")
