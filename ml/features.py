"""Features and the 90-day loss label (proposal sections 3.4 and 3.5).

Unit of analysis: one business-month t. Every feature uses only months up to and including t.
Label: 1 if the business records a net operating loss in month t+1, t+2 or t+3, else 0.
Months without three following months get no label (used for prediction only).

Second label, for the financial-distress model (ml/distress.py): 1 if over months t+1..t+3
  (a) money paid out adds up to more than money received (a cash shortfall), or
  (b) money owed rises by more than half a month's sales (average of the last 3 months).
"""
import numpy as np
import pandas as pd

from app.sectors import SECTORS

MONEY = ["revenue", "cogs", "operating_expenses", "cash_inflows", "cash_outflows",
         "mobile_money_receipts", "closing_stock", "outstanding_debt", "transaction_count"]

NUMERIC_FEATURES = [
    "margin",               # net operating result / sales, this month
    "margin_3m",            # average margin over the last 3 months
    "margin_trend",         # margin now minus margin 3 months ago (points)
    "losses_last3",         # loss months among the last 3
    "rev_growth_3m",        # sales, last 3 months vs the 3 before
    "cost_growth_3m",       # costs (cogs + running), last 3 months vs the 3 before
    "cost_vs_sales_growth", # cost growth minus sales growth
    "rev_mom",              # sales change from last month
    "cogs_ratio",           # cost of goods / sales
    "opex_ratio",           # running expenses / sales
    "net_cf_ratio",         # (cash in - cash out) / sales, last 3 months
    "neg_cf_months_3",      # months with more cash out than in, last 3
    "mpesa_share",          # M-Pesa receipts / cash in
    "tx_growth_3m",         # number of sales, last 3 months vs the 3 before
    "debt_to_rev",          # money owed / monthly sales
    "debt_growth_3m",       # change in money owed over 3 months, relative to sales
    "stock_to_rev",         # closing stock / monthly sales
    "age_months",           # months since the first record (or start date)
    "month_sin", "month_cos",
]
SECTOR_FEATURES = [f"sector_{k}" for k in SECTORS]
DISTRESS_DEBT_RISE = 0.5  # debt growth over 3 months, in months of sales, that counts as distress
FEATURES = NUMERIC_FEATURES + SECTOR_FEATURES


def _safe_div(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(np.abs(b) > 1e-9, a / b, np.nan)
    return out


def _growth(now, before):
    return _safe_div(now - before, np.abs(before))


def records_frame(rows: list[dict]) -> pd.DataFrame:
    """rows: dicts with business_id, sector, is_synthetic, start_date, month + money fields."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["month"] = pd.to_datetime(df["month"])
    for c in MONEY:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)
    return df.sort_values(["business_id", "month"]).reset_index(drop=True)


def _one_business(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("month").copy()
    # put the months on a full monthly calendar so "3 months ago" means 3 calendar months
    full = pd.date_range(g["month"].min(), g["month"].max(), freq="MS")
    g = g.set_index("month").reindex(full)
    g.index.name = "month"
    present = g["revenue"].notna()
    for c in ["business_id", "sector", "is_synthetic", "start_date"]:
        g[c] = g[c].ffill().bfill()

    rev, cogs, opex = g["revenue"], g["cogs"], g["operating_expenses"]
    cost = cogs + opex
    net = rev - cost
    g["net"] = net
    f = pd.DataFrame(index=g.index)
    f["margin"] = _safe_div(net, rev)
    f["margin_3m"] = pd.Series(f["margin"], index=g.index).rolling(3, min_periods=2).mean()
    f["margin_trend"] = f["margin"] - pd.Series(f["margin"], index=g.index).shift(3)
    f["losses_last3"] = (net < 0).astype(float).where(present).rolling(3, min_periods=1).sum()
    r3, c3 = rev.rolling(3, min_periods=3).sum(), cost.rolling(3, min_periods=3).sum()
    f["rev_growth_3m"] = _growth(r3, r3.shift(3))
    f["cost_growth_3m"] = _growth(c3, c3.shift(3))
    f["cost_vs_sales_growth"] = f["cost_growth_3m"] - f["rev_growth_3m"]
    f["rev_mom"] = _growth(rev, rev.shift(1))
    f["cogs_ratio"] = _safe_div(cogs, rev)
    f["opex_ratio"] = _safe_div(opex, rev)
    cf = g["cash_inflows"] - g["cash_outflows"]
    f["net_cf_ratio"] = _safe_div(cf.rolling(3, min_periods=1).sum(), rev.rolling(3, min_periods=1).sum())
    f["neg_cf_months_3"] = (cf < 0).astype(float).where(present).rolling(3, min_periods=1).sum()
    f["mpesa_share"] = _safe_div(g["mobile_money_receipts"], g["cash_inflows"])
    f.loc[g["mobile_money_receipts"].fillna(0) == 0, "mpesa_share"] = np.nan  # not recorded
    t3 = g["transaction_count"].rolling(3, min_periods=3).sum()
    f["tx_growth_3m"] = _growth(t3, t3.shift(3))
    f.loc[g["transaction_count"].fillna(0) == 0, "tx_growth_3m"] = np.nan
    f["debt_to_rev"] = _safe_div(g["outstanding_debt"], rev)
    f["debt_growth_3m"] = _safe_div(g["outstanding_debt"] - g["outstanding_debt"].shift(3), rev)
    f["stock_to_rev"] = _safe_div(g["closing_stock"], rev)
    first = pd.to_datetime(g["start_date"].iloc[0]) if pd.notna(g["start_date"].iloc[0]) else g.index.min()
    first = min(first, g.index.min())
    f["age_months"] = [(m.year - first.year) * 12 + m.month - first.month for m in g.index]
    f["month_sin"] = np.sin(2 * np.pi * g.index.month / 12)
    f["month_cos"] = np.cos(2 * np.pi * g.index.month / 12)
    for k in SECTORS:
        f[f"sector_{k}"] = float(g["sector"].iloc[0] == k)

    # label: a loss in any of the next three months, only when all three are recorded
    loss = (net < 0).astype(float).where(present)
    nxt = pd.concat([loss.shift(-1), loss.shift(-2), loss.shift(-3)], axis=1)
    f["label"] = np.where(nxt.notna().all(axis=1), nxt.max(axis=1), np.nan)

    # financial distress: a cash shortfall over the next three months, or fast-growing debt
    f3 = cf.shift(-1) + cf.shift(-2) + cf.shift(-3)  # NaN unless all three months are recorded
    debt = g["outstanding_debt"]
    dgrow = pd.Series(_safe_div(debt.shift(-3) - debt, rev.rolling(3, min_periods=1).mean()), index=g.index)
    distress = (f3 < 0) | (dgrow.fillna(0) > DISTRESS_DEBT_RISE)
    f["distress"] = np.where(f3.notna(), distress.astype(float), np.nan)

    f["business_id"] = g["business_id"].astype(int)
    f["is_synthetic"] = g["is_synthetic"].astype(bool)
    f["sector"] = g["sector"]
    f["net"] = net
    f["revenue"] = rev
    f = f[present.values].reset_index()
    # clip extreme ratios (tiny sales months) so one odd month can't dominate
    for c in NUMERIC_FEATURES:
        if c not in ("age_months", "month_sin", "month_cos", "losses_last3", "neg_cf_months_3"):
            f[c] = f[c].clip(-5, 5)
    return f


def build(df: pd.DataFrame) -> pd.DataFrame:
    """Feature table: one row per recorded business-month, with FEATURES, label and ids."""
    if df.empty:
        return pd.DataFrame(columns=["month", *FEATURES, "label", "distress", "business_id", "is_synthetic", "sector"])
    parts = [_one_business(g) for _, g in df.groupby("business_id", sort=False)]
    out = pd.concat(parts, ignore_index=True)
    out[FEATURES] = out[FEATURES].astype(float)
    return out


def load_rows(db) -> list[dict]:
    """All business-months from the database, as plain dicts."""
    from sqlalchemy import select

    from app.models import Business, MonthlyRecord

    q = select(MonthlyRecord, Business).join(Business, MonthlyRecord.business_id == Business.id)
    rows = []
    for r, b in db.execute(q).all():
        rows.append({"business_id": b.id, "sector": b.sector, "is_synthetic": b.is_synthetic,
                     "start_date": b.start_date, "month": r.month,
                     **{c: float(getattr(r, c) or 0) for c in MONEY}})
    return rows


def load_rows_for(db, business_id: int) -> list[dict]:
    """One business's months, oldest first."""
    from sqlalchemy import select

    from app.models import Business, MonthlyRecord

    b = db.get(Business, business_id)
    recs = db.scalars(select(MonthlyRecord).where(MonthlyRecord.business_id == business_id)
                      .order_by(MonthlyRecord.month)).all()
    return [{"business_id": b.id, "sector": b.sector, "is_synthetic": b.is_synthetic, "start_date": b.start_date,
             "month": r.month, **{c: float(getattr(r, c) or 0) for c in MONEY}} for r in recs]
