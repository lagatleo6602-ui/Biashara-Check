"""Business figures worked out from the monthly records, each with its formula and a worked example
using the owner's own numbers, so nothing on the dashboard is a black box.

Everything here is plain arithmetic and fixed business rules: no model is involved.

    Gross profit        = sales - cost of goods sold
    Operating profit    = gross profit - running expenses        (the "profit or loss" used everywhere)
    Net cash flow       = money received - money paid out        ("cash left over")
    Break-even sales    = running expenses / gross margin
"""
import hashlib
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AuditLog, Business, MonthlyRecord

MONEY = ["revenue", "cogs", "operating_expenses", "cash_inflows", "cash_outflows",
         "mobile_money_receipts", "closing_stock", "outstanding_debt", "transaction_count"]

# Thresholds for the warning checks. Fixed rules, shown to the owner with each warning.
RULES = {
    "gross_margin_low": 0.15,     # keep less than 15 of every 100 shillings after paying for stock
    "cash_conversion_low": 0.80,  # less than 80% of sales came in as money
    "stock_cover_high": 3.0,      # more than 3 months of stock
    "debt_months_high": 2.0,      # owe more than 2 months of sales
}


def _f(x) -> float:
    return float(x or 0)


def _div(a: float, b: float) -> float | None:
    return a / b if abs(b) > 1e-9 else None


def kes(x: float | None) -> str:
    if x is None:
        return "-"
    return ("-KES " if x < 0 else "KES ") + f"{abs(round(x)):,.0f}"


def pct(x: float | None, digits: int = 0) -> str:
    return "-" if x is None else f"{x * 100:.{digits}f}%"


def month_figures(r) -> dict:
    """All derived figures for one month (r: a MonthlyRecord or a dict with the MONEY fields)."""
    g = (lambda k: _f(r[k])) if isinstance(r, dict) else (lambda k: _f(getattr(r, k)))
    sales, cogs, opex = g("revenue"), g("cogs"), g("operating_expenses")
    cin, cout = g("cash_inflows"), g("cash_outflows")
    gross = sales - cogs
    op = gross - opex
    gm = _div(gross, sales)
    be = opex / gm if gm and gm > 0 else None
    m = r["month"] if isinstance(r, dict) else r.month
    return {
        "month": f"{m:%Y-%m}" if hasattr(m, "strftime") else str(m)[:7],
        "sales": sales, "cogs": cogs, "opex": opex,
        "gross_profit": gross, "gross_margin": gm,
        "operating_profit": op, "net_margin": _div(op, sales),
        "cost_ratio": _div(cogs + opex, sales),
        "cash_in": cin, "cash_out": cout, "net_cash_flow": cin - cout,
        "cash_conversion": _div(cin, sales),
        "profit_cash_gap": op - (cin - cout),
        "break_even_sales": be,
        "margin_of_safety": _div(sales - be, sales) if be is not None else None,
        "mpesa_share": _div(g("mobile_money_receipts"), cin) if g("mobile_money_receipts") else None,
        "avg_sale": _div(sales, g("transaction_count")) if g("transaction_count") else None,
        "transactions": int(g("transaction_count")),
        "stock": g("closing_stock"), "stock_cover": _div(g("closing_stock"), cogs) if g("closing_stock") else None,
        "debt": g("outstanding_debt"), "debt_months": _div(g("outstanding_debt"), sales) if g("outstanding_debt") else None,
    }


def _status(good: bool | None, bad: bool | None) -> str:
    return "bad" if bad else "good" if good else "watch" if good is not None else "none"


def summary(records: list) -> dict | None:
    """Latest month in full, with formulas, plus totals, trends and rule-based warning checks."""
    if not records:
        return None
    months = [month_figures(r) for r in records]
    L = months[-1]
    P = months[-2] if len(months) > 1 else None
    last3, prev3 = months[-3:], months[-6:-3]
    s3 = lambda k, rows: sum(x[k] for x in rows)  # noqa: E731

    items = [
        {"key": "gross_profit", "name": "Gross profit", "value": L["gross_profit"], "unit": "kes",
         "formula": "Total sales - cost of goods sold",
         "worked": f"{kes(L['sales'])} - {kes(L['cogs'])} = {kes(L['gross_profit'])}",
         "meaning": "What is left from sales after paying for the stock you sold, before rent, wages and other running costs.",
         "status": _status(L["gross_profit"] > 0, L["gross_profit"] < 0)},
        {"key": "gross_margin", "name": "Gross margin", "value": L["gross_margin"], "unit": "pct",
         "formula": "Gross profit / total sales x 100",
         "worked": f"{kes(L['gross_profit'])} / {kes(L['sales'])} x 100 = {pct(L['gross_margin'], 1)}",
         "meaning": f"Of every 100 shillings of sales, {L['gross_margin'] * 100:.0f} are left after paying for the stock." if L["gross_margin"] is not None else "Needs sales above zero.",
         "status": _status(L["gross_margin"] is not None and L["gross_margin"] >= RULES["gross_margin_low"],
                           L["gross_margin"] is not None and L["gross_margin"] < RULES["gross_margin_low"])},
        {"key": "operating_profit", "name": "Operating profit (profit or loss)", "value": L["operating_profit"], "unit": "kes",
         "formula": "Gross profit - running expenses  (= sales - cost of goods - running expenses)",
         "worked": f"{kes(L['gross_profit'])} - {kes(L['opex'])} = {kes(L['operating_profit'])}",
         "meaning": "The month's profit or loss from running the business. Below zero is a loss month: the event the risk check looks for.",
         "status": _status(L["operating_profit"] >= 0, L["operating_profit"] < 0)},
        {"key": "net_margin", "name": "Net margin", "value": L["net_margin"], "unit": "pct",
         "formula": "Operating profit / total sales x 100",
         "worked": f"{kes(L['operating_profit'])} / {kes(L['sales'])} x 100 = {pct(L['net_margin'], 1)}",
         "meaning": "How many shillings of every 100 of sales you keep as profit.",
         "status": _status(L["net_margin"] is not None and L["net_margin"] >= 0, L["net_margin"] is not None and L["net_margin"] < 0)},
        {"key": "net_cash_flow", "name": "Net cash flow (cash left over)", "value": L["net_cash_flow"], "unit": "kes",
         "formula": "Money received - money paid out",
         "worked": f"{kes(L['cash_in'])} - {kes(L['cash_out'])} = {kes(L['net_cash_flow'])}",
         "meaning": "Whether more money came in than went out this month, whatever it was for (sales, stock, loans, repayments).",
         "status": _status(L["net_cash_flow"] >= 0, L["net_cash_flow"] < 0)},
        {"key": "profit_cash_gap", "name": "Profit vs cash difference", "value": L["profit_cash_gap"], "unit": "kes",
         "formula": "Operating profit - net cash flow",
         "worked": f"{kes(L['operating_profit'])} - {kes(L['net_cash_flow'])} = {kes(L['profit_cash_gap'])}",
         "meaning": ("Profit is higher than the cash you kept: money is tied up in stock, sales on credit or loan repayments."
                     if L["profit_cash_gap"] > 0 else
                     "You kept more cash than the profit you made: from a loan, money customers paid back, or stock you didn't replace."
                     if L["profit_cash_gap"] < 0 else "Profit and cash match this month."),
         "status": "none"},
        {"key": "break_even_sales", "name": "Break-even sales", "value": L["break_even_sales"], "unit": "kes",
         "formula": "Running expenses / gross margin",
         "worked": (f"{kes(L['opex'])} / {pct(L['gross_margin'], 1)} = {kes(L['break_even_sales'])}"
                    if L["break_even_sales"] is not None else "Can't be worked out: gross margin is zero or below, so no level of sales covers the costs."),
         "meaning": "The sales you need each month to cover running costs at today's margin. Sell less than this and the month is a loss.",
         "status": _status(L["break_even_sales"] is not None and L["sales"] >= L["break_even_sales"],
                           L["break_even_sales"] is None or L["sales"] < L["break_even_sales"])},
        {"key": "margin_of_safety", "name": "Margin of safety", "value": L["margin_of_safety"], "unit": "pct",
         "formula": "(Total sales - break-even sales) / total sales x 100",
         "worked": (f"({kes(L['sales'])} - {kes(L['break_even_sales'])}) / {kes(L['sales'])} x 100 = {pct(L['margin_of_safety'], 1)}"
                    if L["margin_of_safety"] is not None else "Needs a break-even figure."),
         "meaning": (f"Sales could fall by {L['margin_of_safety'] * 100:.0f}% before the month turns into a loss."
                     if L["margin_of_safety"] is not None and L["margin_of_safety"] > 0 else
                     "Sales are already below break-even." if L["margin_of_safety"] is not None else ""),
         "status": _status(L["margin_of_safety"] is not None and L["margin_of_safety"] >= 0.10,
                           L["margin_of_safety"] is None or L["margin_of_safety"] < 0)},
        {"key": "cash_conversion", "name": "Sales received as money", "value": L["cash_conversion"], "unit": "pct",
         "formula": "Money received / total sales x 100",
         "worked": f"{kes(L['cash_in'])} / {kes(L['sales'])} x 100 = {pct(L['cash_conversion'])}",
         "meaning": "Below 100% can mean customers owe you; far above 100% usually means a loan or personal money came in.",
         "status": _status(L["cash_conversion"] is not None and L["cash_conversion"] >= RULES["cash_conversion_low"],
                           L["cash_conversion"] is not None and L["cash_conversion"] < RULES["cash_conversion_low"])},
        {"key": "cost_ratio", "name": "Costs per 100 shillings of sales", "value": L["cost_ratio"], "unit": "pct",
         "formula": "(Cost of goods + running expenses) / total sales x 100",
         "worked": f"({kes(L['cogs'])} + {kes(L['opex'])}) / {kes(L['sales'])} x 100 = {pct(L['cost_ratio'])}",
         "meaning": "Above 100% means costs were bigger than sales: a loss.",
         "status": _status(L["cost_ratio"] is not None and L["cost_ratio"] <= 1, L["cost_ratio"] is not None and L["cost_ratio"] > 1)},
    ]
    if L["stock_cover"] is not None:
        items.append({"key": "stock_cover", "name": "Months of stock", "value": L["stock_cover"], "unit": "months",
                      "formula": "Stock value at month end / cost of goods sold this month",
                      "worked": f"{kes(L['stock'])} / {kes(L['cogs'])} = {L['stock_cover']:.1f} months",
                      "meaning": "How long your stock would last at this month's pace. A lot of stock ties up cash.",
                      "status": _status(L["stock_cover"] <= RULES["stock_cover_high"], L["stock_cover"] > RULES["stock_cover_high"])})
    if L["debt_months"] is not None:
        items.append({"key": "debt_months", "name": "Money owed, in months of sales", "value": L["debt_months"], "unit": "months",
                      "formula": "Money you owe / total sales this month",
                      "worked": f"{kes(L['debt'])} / {kes(L['sales'])} = {L['debt_months']:.1f} months",
                      "meaning": "How many months of sales it would take to pay off everything you owe.",
                      "status": _status(L["debt_months"] <= RULES["debt_months_high"], L["debt_months"] > RULES["debt_months_high"])})
    if L["avg_sale"] is not None:
        items.append({"key": "avg_sale", "name": "Average sale", "value": L["avg_sale"], "unit": "kes",
                      "formula": "Total sales / number of sales",
                      "worked": f"{kes(L['sales'])} / {L['transactions']:,} = {kes(L['avg_sale'])}",
                      "meaning": "How much a customer spends each time, on average.", "status": "none"})
    if L["mpesa_share"] is not None:
        items.append({"key": "mpesa_share", "name": "M-Pesa share", "value": L["mpesa_share"], "unit": "pct",
                      "formula": "Received by M-Pesa / money received x 100",
                      "worked": f"{kes(_f(L['mpesa_share'] * L['cash_in']))} / {kes(L['cash_in'])} x 100 = {pct(L['mpesa_share'])}",
                      "meaning": "The part of your money that came in by M-Pesa, which leaves a record you can show a lender.",
                      "status": "none"})

    # trends: last 3 months against the 3 before
    trends = None
    if len(prev3) == 3:
        def g3(k):
            a, b = s3(k, last3), s3(k, prev3)
            return {"now": a, "before": b, "change": _div(a - b, abs(b))}
        trends = {"sales": g3("sales"), "gross_profit": g3("gross_profit"), "opex": g3("opex"),
                  "operating_profit": g3("operating_profit"), "net_cash_flow": g3("net_cash_flow")}

    checks = _checks(L, P, last3, prev3, months)
    totals = {
        "months": len(months),
        "loss_months": sum(1 for x in months if x["operating_profit"] < 0),
        "last3": {k: s3(k, last3) for k in ("sales", "gross_profit", "opex", "operating_profit", "net_cash_flow")},
        "all": {k: s3(k, months) for k in ("sales", "gross_profit", "operating_profit", "net_cash_flow")},
    }
    statement = {
        "month": L["month"],
        "profit": [("Total sales", L["sales"]), ("- Cost of goods sold", -L["cogs"]), ("= Gross profit", L["gross_profit"]),
                   ("- Running expenses", -L["opex"]), ("= Operating profit", L["operating_profit"])],
        "cash": [("Money received", L["cash_in"]), ("- Money paid out", -L["cash_out"]), ("= Net cash flow", L["net_cash_flow"])],
    }
    return {"latest": L, "previous": P, "items": items, "trends": trends, "checks": checks, "totals": totals,
            "statement": statement, "months": months, "rules": RULES}


def _checks(L: dict, P: dict | None, last3: list, prev3: list, months: list) -> list[dict]:
    """Business-logic warnings. Each one says the rule that triggered it."""
    out = []

    def add(level, title, text, rule):
        out.append({"level": level, "title": title, "text": text, "rule": rule})

    if L["gross_profit"] < 0:
        add("bad", "Selling below cost", f"You paid {kes(L['cogs'])} for stock that sold for {kes(L['sales'])}.",
            "Shown when cost of goods sold is more than total sales.")
    elif L["gross_profit"] < L["opex"]:
        add("bad", "Gross profit doesn't cover running costs",
            f"Gross profit was {kes(L['gross_profit'])} but running expenses were {kes(L['opex'])}, so the month was a loss of {kes(-L['operating_profit'])}.",
            "Shown when gross profit is less than running expenses.")
    if L["operating_profit"] >= 0 and L["net_cash_flow"] < 0:
        add("watch", "Profit, but cash went down",
            f"You made {kes(L['operating_profit'])} profit but paid out {kes(-L['net_cash_flow'])} more than you received. "
            "Check stock bought, sales on credit and loan repayments.",
            "Shown when the month is profitable but money paid out is more than money received.")
    if len(last3) == 3 and sum(1 for x in last3 if x["net_cash_flow"] < 0) >= 2:
        add("bad", "Cash shortfall in 2 or more of the last 3 months",
            f"Over the last 3 months, cash left over adds up to {kes(sum(x['net_cash_flow'] for x in last3))}.",
            "Shown when money paid out is more than money received in at least 2 of the last 3 months.")
    if L["break_even_sales"] is not None and L["sales"] < L["break_even_sales"]:
        add("bad", "Sales below break-even",
            f"You needed {kes(L['break_even_sales'])} of sales to cover running costs, and sold {kes(L['sales'])}.",
            "Shown when total sales are below running expenses / gross margin.")
    elif L["margin_of_safety"] is not None and 0 <= L["margin_of_safety"] < 0.10:
        add("watch", "Close to break-even",
            f"Sales {L['margin_of_safety'] * 100:.0f}% lower would have made this month a loss.",
            "Shown when the margin of safety is under 10%.")
    if P and L["gross_margin"] is not None and P["gross_margin"] is not None and P["gross_margin"] - L["gross_margin"] > 0.05:
        add("watch", "Gross margin fell",
            f"From {pct(P['gross_margin'])} to {pct(L['gross_margin'])} of sales. Supplier prices may have risen while your prices stayed the same.",
            "Shown when gross margin drops by more than 5 points from the month before.")
    if len(prev3) == 3:
        sg = _div(sum(x["sales"] for x in last3) - sum(x["sales"] for x in prev3), sum(x["sales"] for x in prev3))
        cg = _div(sum(x["cogs"] + x["opex"] for x in last3) - sum(x["cogs"] + x["opex"] for x in prev3),
                  sum(x["cogs"] + x["opex"] for x in prev3))
        if sg is not None and cg is not None and cg - sg > 0.05:
            add("watch", "Costs growing faster than sales",
                f"Over the last 3 months costs changed {cg * 100:+.0f}% and sales {sg * 100:+.0f}%.",
                "Shown when cost growth is more than 5 points above sales growth (last 3 months vs the 3 before).")
    if L["cash_conversion"] is not None and L["cash_conversion"] < RULES["cash_conversion_low"]:
        add("watch", "Much of your sales didn't come in as money",
            f"Only {pct(L['cash_conversion'])} of sales was received. Follow up customers who owe you.",
            "Shown when money received is under 80% of sales.")
    if L["stock_cover"] is not None and L["stock_cover"] > RULES["stock_cover_high"]:
        add("watch", "A lot of stock on hand",
            f"Your stock would last {L['stock_cover']:.1f} months at this pace. Cash is tied up in it.",
            "Shown when stock at month end is more than 3 months of cost of goods sold.")
    if L["debt_months"] is not None and L["debt_months"] > RULES["debt_months_high"]:
        add("watch", "Money owed is high",
            f"You owe {L['debt_months']:.1f} months of sales.", "Shown when money owed is more than 2 months of sales.")
    if len(months) >= 4 and months[-4]["debt"] and L["debt"] > months[-4]["debt"] * 1.2 and L["debt"] - months[-4]["debt"] > 5000:
        add("watch", "Money owed is rising",
            f"From {kes(months[-4]['debt'])} three months ago to {kes(L['debt'])}.",
            "Shown when money owed grew by more than 20% (and KES 5,000) in 3 months.")
    return out


# ---------- data integrity ----------
def fingerprint(records: list) -> str:
    """SHA-256 of the figures in a fixed order. Any change to any figure changes it, so a printed
    report can be matched against the records it came from."""
    h = hashlib.sha256()
    for r in sorted(records, key=lambda r: r.month):
        h.update((f"{r.month:%Y-%m}|" + "|".join(f"{_f(getattr(r, k)):.2f}" for k in MONEY) + "\n").encode())
    return h.hexdigest()


def _gaps(months: list[date]) -> list[str]:
    out = []
    for a, b in zip(months, months[1:]):
        y, m = a.year, a.month
        while True:
            m += 1
            if m == 13:
                y, m = y + 1, 1
            if (y, m) >= (b.year, b.month):
                break
            out.append(f"{y}-{m:02d}")
    return out


def quality_flags(r, prev=None) -> list[str]:
    """The same 'possible typing mistake' checks the entry form makes, run again on saved months."""
    f = lambda k: _f(getattr(r, k))  # noqa: E731
    rev, cogs, opex, cin, cout = f("revenue"), f("cogs"), f("operating_expenses"), f("cash_inflows"), f("cash_outflows")
    out = []
    if rev == 0:
        out.append("Total sales is 0")
    if rev > 0 and cogs > rev * 1.5:
        out.append("Cost of goods sold is much higher than sales")
    if rev > 0 and opex > rev * 1.5:
        out.append("Running expenses are much higher than sales")
    if rev > 0 and cin > rev * 3:
        out.append("Money received is more than 3 times sales")
    if cin > 0 and f("mobile_money_receipts") > cin * 1.05:
        out.append("M-Pesa receipts are more than all money received")
    if prev is not None and _f(prev.revenue) > 0 and rev > 0:
        ratio = rev / _f(prev.revenue)
        if ratio > 3:
            out.append(f"Sales are {ratio:.1f} times the month before")
        if ratio < 0.3:
            out.append("Sales are less than a third of the month before")
    return out


def integrity(db: Session, business: Business) -> dict:
    recs = db.scalars(select(MonthlyRecord).where(MonthlyRecord.business_id == business.id)
                      .order_by(MonthlyRecord.month)).all()
    flagged = []
    for i, r in enumerate(recs):
        prev = recs[i - 1] if i and _gaps([recs[i - 1].month, r.month]) == [] else None
        fl = quality_flags(r, prev)
        if fl:
            flagged.append({"month": f"{r.month:%Y-%m}", "flags": fl})
    acts = dict(db.execute(select(AuditLog.action, func.count()).where(
        AuditLog.target == business.code, AuditLog.action.in_(["record.added", "record.edited", "record.deleted",
                                                               "records.uploaded", "mpesa.statement_applied"]))
        .group_by(AuditLog.action)).all())
    last = db.scalar(select(func.max(AuditLog.at)).where(
        AuditLog.target == business.code,
        AuditLog.action.in_(["record.added", "record.edited", "record.deleted", "records.uploaded", "mpesa.statement_applied"])))
    return {
        "months": len(recs),
        "first": f"{recs[0].month:%Y-%m}" if recs else None,
        "last": f"{recs[-1].month:%Y-%m}" if recs else None,
        "gaps": _gaps([r.month for r in recs]),
        "flagged": flagged,
        "changes": {"added": acts.get("record.added", 0), "edited": acts.get("record.edited", 0),
                    "deleted": acts.get("record.deleted", 0),
                    "uploads": acts.get("records.uploaded", 0), "mpesa": acts.get("mpesa.statement_applied", 0)},
        "last_change": last.isoformat(timespec="minutes") if last else None,
        "fingerprint": fingerprint(recs) if recs else None,
    }
