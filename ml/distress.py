"""Financial-distress model: a statistical logistic regression.

What it predicts
    The probability that, over the next 3 months, the business runs a cash shortfall (money paid out
    adds up to more than money received) or its debt rises by more than half a month's sales.
    See ml/features.py for the exact label.

Why logistic regression
    It is a classical statistical model, so every part of it can be written down and checked:

        log-odds = b0 + b1*z1 + b2*z2 + ... + b8*z8
        probability = 1 / (1 + e^(-log-odds))

    where each z is a figure from the business's records, standardised: z = (value - mean) / sd,
    with the mean and sd taken from the training data. Each coefficient b says how much one standard
    deviation of that figure moves the log-odds; e^b is the odds ratio. The model is fitted by
    maximum likelihood with no penalty and no class weights, so its probabilities are not pushed up
    or down, and standard errors, p-values and confidence intervals come from the usual
    Fisher-information formula.

It is trained alongside the main machine-learning model (python -m ml.train) on the same time-based
split, and its test results (ROC-AUC, PR-AUC, Brier score, calibration and the Hosmer-Lemeshow test)
are saved with it.
"""
import warnings

import joblib
import numpy as np
import pandas as pd

from . import features as F

# Eight figures an owner can recognise. "Costs vs sales growth" was left out on purpose: it overlaps so much
# with the margin figures that its coefficient came out with the counter-intuitive sign, which would make the
# explanation misleading (a known effect of multicollinearity in regression).
FEATURES = ["margin_3m", "losses_last3", "net_cf_ratio", "neg_cf_months_3", "rev_growth_3m",
            "debt_to_rev", "debt_growth_3m", "stock_to_rev"]
MIN_ROWS, MIN_EACH_CLASS = 150, 15


def _file():
    from .train import ARTIFACTS
    return ARTIFACTS / "distress.joblib"


def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))


class Model:
    """Median imputation + standardisation + unpenalised logistic regression, kept as plain numbers."""

    def __init__(self):
        self.median = self.mean = self.sd = self.coef = None
        self.intercept = 0.0

    def _z(self, X: pd.DataFrame) -> np.ndarray:
        A = X[FEATURES].astype(float).fillna(pd.Series(self.median)).values
        return (A - self.mean) / self.sd

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> "Model":
        from sklearn.linear_model import LogisticRegression
        A = X[FEATURES].astype(float)
        self.median = A.median().fillna(0).to_dict()
        A = A.fillna(pd.Series(self.median)).values
        self.mean, self.sd = A.mean(axis=0), A.std(axis=0)
        self.sd[self.sd < 1e-9] = 1.0
        Z = (A - self.mean) / self.sd
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lr = LogisticRegression(penalty=None, max_iter=5000, tol=1e-8).fit(Z, y)
        self.coef, self.intercept = lr.coef_[0].astype(float), float(lr.intercept_[0])
        self._Z, self._y = Z, y  # kept only until the statistics are worked out
        return self

    def log_odds(self, X: pd.DataFrame) -> np.ndarray:
        return self.intercept + self._z(X) @ self.coef

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return _sig(self.log_odds(X))

    def statistics(self) -> dict:
        """Coefficient table (standard errors from the inverse Fisher information), McFadden pseudo R-squared
        and a likelihood-ratio test against the intercept-only model."""
        from scipy import stats
        Z, y = self._Z, self._y
        D = np.column_stack([np.ones(len(Z)), Z])
        p = _sig(D @ np.r_[self.intercept, self.coef])
        W = p * (1 - p)
        cov = np.linalg.pinv(D.T @ (D * W[:, None]))
        se = np.sqrt(np.clip(np.diag(cov), 0, None))
        b = np.r_[self.intercept, self.coef]
        zval = np.divide(b, se, out=np.zeros_like(b), where=se > 0)
        pval = 2 * stats.norm.sf(np.abs(zval))
        eps = 1e-12
        ll = float(np.sum(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps)))
        p0 = y.mean()
        ll0 = float(len(y) * (p0 * np.log(p0 + eps) + (1 - p0) * np.log(1 - p0 + eps)))
        lr_stat = 2 * (ll - ll0)
        rows = []
        for i, name in enumerate(["(intercept)"] + FEATURES):
            rows.append({"feature": name, "coef": round(float(b[i]), 4), "se": round(float(se[i]), 4),
                         "z": round(float(zval[i]), 2), "p_value": float(f"{pval[i]:.3g}"),
                         "odds_ratio": round(float(np.exp(b[i])), 3),
                         "ci_low": round(float(np.exp(b[i] - 1.96 * se[i])), 3),
                         "ci_high": round(float(np.exp(b[i] + 1.96 * se[i])), 3)})
        for i, name in enumerate(FEATURES):
            rows[i + 1].update(mean=round(float(self.mean[i]), 4), sd=round(float(self.sd[i]), 4))
        del self._Z, self._y
        return {"coefficients": rows, "log_likelihood": round(ll, 2), "null_log_likelihood": round(ll0, 2),
                "mcfadden_r2": round(1 - ll / ll0, 4) if ll0 else None,
                "lr_test": {"statistic": round(lr_stat, 2), "df": len(FEATURES),
                            "p_value": float(f"{stats.chi2.sf(lr_stat, len(FEATURES)):.3g}")}}


def hosmer_lemeshow(y: np.ndarray, p: np.ndarray, groups: int = 10) -> dict:
    """Groups the test months into tenths by predicted probability and compares predicted with actual
    distress counts. A large p-value (above 0.05) means no evidence that the probabilities are off."""
    from scipy import stats
    order = np.argsort(p)
    chi = 0.0
    used = 0
    for part in np.array_split(order, groups):
        if not len(part):
            continue
        n, obs, exp = len(part), y[part].sum(), p[part].sum()
        if 0 < exp < n:
            chi += (obs - exp) ** 2 / (exp * (1 - exp / n))
            used += 1
    df = max(1, used - 2)
    return {"statistic": round(float(chi), 2), "df": df, "p_value": float(f"{stats.chi2.sf(chi, df):.3g}")}


def train(X: pd.DataFrame) -> dict:
    """X: the feature table from features.build (all businesses). Saves the model; returns its summary.
    Raises train.NotEnoughData if there aren't enough labelled months."""
    from .train import ARTIFACTS, NotEnoughData, _metrics, calibration, split

    lab = X[X["distress"].notna()].copy()
    n_pos = int(lab["distress"].sum()) if len(lab) else 0
    if len(lab) < MIN_ROWS or n_pos < MIN_EACH_CLASS or len(lab) - n_pos < MIN_EACH_CLASS:
        raise NotEnoughData(f"Not enough data for the distress model: {len(lab)} months with a known outcome, {n_pos} in distress.")
    tr, te, cut = split(lab)
    if tr["distress"].nunique() < 2 or te["distress"].nunique() < 2:
        raise NotEnoughData("The distress model's test period has only one kind of outcome.")
    m = Model().fit(tr, tr["distress"].astype(int).values)
    m.statistics()  # frees the training copy
    yt = te["distress"].astype(int).values
    p = m.predict_proba(te)
    test = {**_metrics(yt, p), "hosmer_lemeshow": hosmer_lemeshow(yt, p), "calibration": calibration(yt, p),
            "positive_rate": round(float(yt.mean()), 4), "train_positive_rate": round(float(tr["distress"].mean()), 4)}

    final = Model().fit(lab, lab["distress"].astype(int).values)
    stats_ = final.statistics()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, _file())
    _cache.clear()
    return {"name": "Logistic regression (statistical)", "target": "Cash shortfall or fast-rising debt in the next 3 months",
            "rows": {"labelled": int(len(lab)), "train": int(len(tr)), "test": int(len(te)), "positives": n_pos,
                     "positive_rate": round(n_pos / len(lab), 4)},
            "test_from": cut.strftime("%Y-%m"), "test": test, **stats_}


_cache: dict = {}


def load() -> Model | None:
    f = _file()
    if not f.exists():
        return None
    mtime = f.stat().st_mtime
    if _cache.get("mtime") != mtime:
        _cache.update(mtime=mtime, model=joblib.load(f))
    return _cache["model"]


NAMES = {"margin_3m": "Profit margin, last 3 months", "losses_last3": "Loss months in the last 3",
         "net_cf_ratio": "Cash left over per 100 of sales, last 3 months", "neg_cf_months_3": "Months with more cash out than in",
         "rev_growth_3m": "Sales trend", "cost_vs_sales_growth": "Costs growing faster than sales",
         "debt_to_rev": "Money owed, in months of sales", "debt_growth_3m": "Change in money owed",
         "stock_to_rev": "Stock on hand, in months of sales"}


# +1: a higher value is the worse direction for a business; -1: a lower value is worse
WORSE = {"margin_3m": -1, "losses_last3": 1, "net_cf_ratio": -1, "neg_cf_months_3": 1, "rev_growth_3m": -1,
         "cost_vs_sales_growth": 1, "debt_to_rev": 1, "debt_growth_3m": 1, "stock_to_rev": 1}
NAMES_SW = {"margin_3m": "Kiwango cha faida, miezi 3 iliyopita", "losses_last3": "Miezi ya hasara kati ya 3 iliyopita",
            "net_cf_ratio": "Pesa iliyobaki kwa kila 100 za mauzo, miezi 3", "neg_cf_months_3": "Miezi ambayo pesa zilizotoka zilizidi",
            "rev_growth_3m": "Mwelekeo wa mauzo", "cost_vs_sales_growth": "Gharama kukua kuliko mauzo",
            "debt_to_rev": "Madeni, kwa miezi ya mauzo", "debt_growth_3m": "Mabadiliko ya madeni",
            "stock_to_rev": "Bidhaa zilizopo, kwa miezi ya mauzo"}


def _neutral(feature: str, shown: str, avg: str, up: bool, lang: str) -> str:
    if lang == "sw":
        return f"{NAMES_SW[feature]}: {shown} (wastani wa biashara: {avg}). Hii {'inaongeza' if up else 'inapunguza'} uwezekano."
    return f"{NAMES[feature]}: {shown} (average business: {avg}). This {'raises' if up else 'lowers'} the chance."


def _show(feature: str, v: float) -> str:
    if v is None or np.isnan(v):
        return "not recorded"
    if feature in ("losses_last3", "neg_cf_months_3"):
        return f"{int(round(v))} of 3"
    if feature in ("debt_to_rev", "stock_to_rev"):
        return f"{v:.1f} months"
    if feature == "debt_growth_3m":
        return f"{(round(v, 2) or 0):+.2f} months of sales"
    x = round(v * 100) or 0  # no "-0%"
    return f"{x:+d}%" if feature in ("rev_growth_3m", "cost_vs_sales_growth") else f"{x:d}%"


def predict_rows(rows: list[dict], lang: str = "en") -> dict | None:
    """Distress probability for the business's latest month, with the full calculation."""
    from .predict import explain, explain_sw
    from .train import band

    m = load()
    if m is None or len(rows) < 3:
        return None
    X = F.build(F.records_frame(rows))
    last = X.iloc[[-1]]
    z = m._z(last)[0]
    contrib = z * m.coef
    lo = float(m.intercept + contrib.sum())
    p = float(_sig(lo))
    raw = last[FEATURES].iloc[0]
    terms = []
    for i, f in enumerate(FEATURES):
        v = float(raw[f]) if pd.notna(raw[f]) else np.nan
        up = contrib[i] > 0
        # the plain-language sentence only when it matches the direction the model actually used
        # (a coefficient can go against intuition when figures overlap); otherwise a neutral, factual line
        shown, avg = _show(f, v), _show(f, float(m.mean[i]))
        bad_side = not np.isnan(v) and np.sign(z[i]) == WORSE[f]
        if up == bad_side and not np.isnan(v):
            text, tip = (explain_sw if lang == "sw" else explain)(f, v, up)
        else:
            text, tip = "", ""
        text = text or _neutral(f, shown, avg, up, lang)
        terms.append({"feature": f, "name": (NAMES_SW if lang == "sw" else NAMES)[f], "value": None if np.isnan(v) else round(v, 4),
                      "shown": shown, "average": avg,
                      "imputed": bool(np.isnan(v)), "mean": round(float(m.mean[i]), 4), "sd": round(float(m.sd[i]), 4),
                      "z": round(float(z[i]), 3), "coef": round(float(m.coef[i]), 4), "contribution": round(float(contrib[i]), 4),
                      "text": text, "tip": tip if up else ""})
    order = sorted(terms, key=lambda t: -abs(t["contribution"]))
    return {"source": "logistic_regression", "probability": round(p, 4), "band": band(p),
            "as_of": last["month"].iloc[0].strftime("%Y-%m"), "intercept": round(m.intercept, 4),
            "log_odds": round(lo, 4), "terms": terms,
            "drivers_up": [t for t in order if t["contribution"] > 0.05][:3],
            "drivers_down": [t for t in order if t["contribution"] < -0.05][:3]}
