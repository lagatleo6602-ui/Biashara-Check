"""The outlook: the risk of a loss over 1 to 12 months ahead, chosen by the owner.

What it predicts
    For a chosen horizon h (1..12 months), the chance that at least one of the next h months is a loss
    month (net operating result below zero). h = 3 is the original 90-day question.

How
    One model covers every horizon. Each past business-month t is used once per horizon h whose months
    t+1..t+h are all recorded, with h as an extra input and the label "any loss in t+1..t+h". This uses
    the data far better than twelve separate models, and LightGBM is told that the chance can only rise
    with h (a monotone constraint), because a loss within 3 months is also a loss within 6.

    Anchoring: the 3-month risk check shown everywhere else in the app comes from the main model
    (best of four, calibrated). So the outlook agrees with it, the whole 1..12 curve is shifted on the
    log-odds scale so its 3-month point equals the main model's %:
        logit(p_h) = logit(q_h) + (logit(p_main_3) - logit(q_3))
    A constant shift keeps the order of the horizons. Finally a running maximum guarantees the curve
    never goes down.

Testing
    Time-based and leak-free: the test period is the latest 25% of months; a training example (t, h) is
    only used if its whole label window t+1..t+h ends before the test period starts. The anchoring in the
    test uses a copy of the main model trained the same way. Results are saved per horizon (rows tested,
    share followed by a loss, ROC-AUC, PR-AUC, recall, precision, Brier score and what happened after each
    band), so the app can say how well predictions that far ahead have done.
"""
import warnings

import joblib
import numpy as np
import pandas as pd

from . import features as F

HORIZONS = list(range(1, 13))
FEATURES = F.FEATURES + ["horizon"]
MIN_ROWS = 300


def _file():
    from .train import ARTIFACTS
    return ARTIFACTS / "horizon.joblib"


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _sig(x):
    return 1 / (1 + np.exp(-x))


def future_losses(X: pd.DataFrame) -> pd.DataFrame:
    """For every row of the feature table: y1..y12 = 1 if any of the next h calendar months was a loss,
    0 if none was, NaN if any of those months isn't recorded (too recent, or a gap)."""
    out = pd.DataFrame(np.nan, index=X.index, columns=[f"y{h}" for h in HORIZONS])
    for _, g in X.groupby("business_id", sort=False):
        g = g.sort_values("month")
        full = pd.date_range(g["month"].min(), g["month"].max(), freq="MS")
        loss = pd.Series((g["net"].values < 0).astype(float), index=pd.DatetimeIndex(g["month"].values)).reindex(full)
        cur, allp = None, None
        for h in HORIZONS:
            s = loss.shift(-h)
            cur = s if cur is None else pd.Series(np.fmax(cur.values, s.values), index=full)
            allp = s.notna() if allp is None else (allp & s.notna())
            out.loc[g.index, f"y{h}"] = cur.where(allp).reindex(pd.DatetimeIndex(g["month"].values)).values
    return out


def stack(X: pd.DataFrame, Y: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for h in HORIZONS:
        m = Y[f"y{h}"].notna()
        if not m.any():
            continue
        part = X.loc[m, ["month", "business_id", "is_synthetic", *F.FEATURES]].copy()
        part["horizon"] = float(h)
        part["y"] = Y.loc[m, f"y{h}"].astype(int).values
        parts.append(part)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["month", *FEATURES, "y"])


def _end_month(df: pd.DataFrame) -> pd.Series:
    """Last month of each example's label window: month + horizon."""
    per = df["month"].dt.to_period("M")
    return (per + df["horizon"].astype(int)).dt.to_timestamp()


def make_model():
    from lightgbm import LGBMClassifier
    from sklearn.pipeline import Pipeline
    # no class weights, so the % stays honest; the chance may only rise with the horizon
    return Pipeline([("prep", "passthrough"),
                     ("clf", LGBMClassifier(n_estimators=350, learning_rate=0.05, num_leaves=31, min_child_samples=40,
                                            subsample=0.9, subsample_freq=1, colsample_bytree=0.9, random_state=42,
                                            monotone_constraints=[0] * len(F.FEATURES) + [1], verbose=-1))])


def _curve(model, rows: pd.DataFrame) -> np.ndarray:
    """(n rows) x 12 horizons of raw chances."""
    reps = rows.loc[rows.index.repeat(len(HORIZONS)), F.FEATURES].copy()
    reps["horizon"] = np.tile(np.array(HORIZONS, dtype=float), len(rows))
    return model.predict_proba(reps[FEATURES])[:, 1].reshape(len(rows), len(HORIZONS))


def anchor(q: np.ndarray, p3: np.ndarray | None) -> np.ndarray:
    """Shift each curve so its 3-month point equals the main model's %, then make it non-decreasing."""
    q = np.atleast_2d(q)
    if p3 is not None:
        shift = _logit(np.asarray(p3).reshape(-1, 1)) - _logit(q[:, [2]])
        q = _sig(_logit(q) + shift)
    return np.maximum.accumulate(q, axis=1)


def train(X: pd.DataFrame, main_kind: str, main_scaler: dict | None) -> dict:
    """X: the feature table from features.build. Saves the outlook model and returns its test evidence."""
    from .train import BANDS, NotEnoughData, _metrics, by_band, calibrate, make_model as make_main

    Y = future_losses(X)
    S = stack(X, Y)
    if len(S) < MIN_ROWS or S["y"].nunique() < 2:
        raise NotEnoughData("Not enough recorded months yet for the 1-12 month outlook.")
    months = np.sort(X["month"].unique())
    cut = pd.Timestamp(months[int(len(months) * 0.75)])
    tr = S[_end_month(S) < cut]
    if len(tr) < MIN_ROWS or tr["y"].nunique() < 2:
        raise NotEnoughData("Not enough months before the test period for the 1-12 month outlook.")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = make_model().fit(tr[FEATURES], tr["y"])

        # the main 3-month model, trained only on months whose label ends before the test period
        lab3 = X[X["label"].notna()]
        lab3 = lab3[(lab3["month"].dt.to_period("M") + 3).dt.to_timestamp() < cut]
        p3 = None
        if lab3["label"].nunique() == 2:
            pw = float((lab3["label"] == 0).sum() / max(1, (lab3["label"] == 1).sum()))
            main = make_main(main_kind, pw).fit(lab3[F.FEATURES], lab3["label"].astype(int))

    te_rows = X[X["month"] >= cut]
    Yte = Y.loc[te_rows.index]
    q = _curve(model, te_rows)
    if lab3["label"].nunique() == 2:
        p3 = calibrate(main.predict_proba(te_rows[F.FEATURES])[:, 1], main_scaler)
    P = anchor(q, p3)

    per_h = {}
    for i, h in enumerate(HORIZONS):
        m = Yte[f"y{h}"].notna().values
        if m.sum() < 30 or len(np.unique(Yte[f"y{h}"].values[m])) < 2:
            per_h[str(h)] = {"n": int(m.sum()), "enough": False}
            continue
        y = Yte[f"y{h}"].values[m].astype(int)
        mt = _metrics(y, P[m, i])
        per_h[str(h)] = {"enough": True, "n": int(m.sum()), "positive_rate": round(float(y.mean()), 4),
                         "businesses": int(te_rows.loc[m, "business_id"].nunique()),
                         **{k: mt[k] for k in ("pr_auc", "roc_auc", "recall", "precision", "f1", "brier")},
                         "brier_unanchored": round(float(np.mean((q[m, i] - y) ** 2)), 4),
                         "bands": by_band(y, P[m, i])}

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        final = make_model().fit(S[FEATURES], S["y"])
    from datetime import datetime, timezone
    version = "outlook-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    joblib.dump({"model": final, "version": version, "features": FEATURES}, _file())
    _cache.clear()
    return {"name": "LightGBM, one model for 1-12 months (monotone in the horizon)", "version": version,
            "anchored": p3 is not None, "test_from": cut.strftime("%Y-%m"),
            "rows": {"examples": int(len(S)), "train": int(len(tr)), "business_months": int(len(X))},
            "bands": BANDS, "horizons": per_h}


_cache: dict = {}


def load():
    f = _file()
    if not f.exists():
        return None
    mtime = f.stat().st_mtime
    if _cache.get("mtime") != mtime:
        _cache.update(mtime=mtime, bundle=joblib.load(f))
    return _cache["bundle"]


def predict_rows(rows: list[dict], months: int, p3: float | None) -> dict | None:
    """The outlook for one business: the 1..12 month curve (anchored to the 3-month check p3) and the
    reasons for the chosen horizon."""
    from .predict import reasons_from
    from .train import band, shap_values

    bundle = load()
    if bundle is None or len(rows) < 3:
        return None
    X = F.build(F.records_frame(rows))
    last = X.iloc[[-1]]
    model = bundle["model"]
    curve = anchor(_curve(model, last), None if p3 is None else np.array([p3]))[0]
    as_of = last["month"].iloc[0]
    row = last[F.FEATURES].copy()
    row["horizon"] = float(months)
    sv = shap_values(model, row[FEATURES])[0]
    reasons, protective = reasons_from(sv, row[FEATURES].iloc[0], FEATURES)
    p = float(curve[months - 1])
    return {"months": months, "as_of": as_of.strftime("%Y-%m"),
            "until": (as_of.to_period("M") + months).strftime("%Y-%m"),
            "probability": round(p, 4), "band": band(p), "model_version": bundle["version"],
            "anchored": p3 is not None,
            "curve": [{"months": h, "month": (as_of.to_period("M") + h).strftime("%Y-%m"),
                       "probability": round(float(curve[h - 1]), 4), "band": band(float(curve[h - 1]))} for h in HORIZONS],
            "reasons": reasons, "protective": protective}
