"""The simple rule-based risk check (same rules as the dashboard), used when no model is trained."""


def _pct(now: float, before: float) -> float | None:
    return (now - before) / before * 100 if before > 0 else None


def rule_risk(recs: list) -> dict | None:
    """recs: MonthlyRecord rows, oldest first. Returns a result shaped like the model's, or None."""
    if len(recs) < 3:
        return None
    net = lambda r: float(r.revenue) - float(r.cogs) - float(r.operating_expenses)  # noqa: E731
    last3, prev3 = recs[-3:], recs[-6:-3]
    last_net = sum(net(r) for r in last3)
    signs = []
    if len(prev3) == 3:
        rg = _pct(sum(float(r.revenue) for r in last3), sum(float(r.revenue) for r in prev3))
        eg = _pct(sum(float(r.cogs) + float(r.operating_expenses) for r in last3),
                  sum(float(r.cogs) + float(r.operating_expenses) for r in prev3))
        if rg is not None and eg is not None and eg - rg > 3:
            signs.append({"text": f"Costs grew {eg:.0f}% while sales changed {rg:.0f}% over the last 3 months.",
                          "tip": "List your three biggest costs. Ask suppliers for a better price, or drop items that sell slowly."})
        m1 = last_net / max(1.0, sum(float(r.revenue) for r in last3)) * 100
        m0 = sum(net(r) for r in prev3) / max(1.0, sum(float(r.revenue) for r in prev3)) * 100
        if m0 - m1 > 3:
            signs.append({"text": f"From every 100 shillings of sales you now keep {m1:.0f}, down from {m0:.0f}.",
                          "tip": "Check whether supplier prices went up while your selling prices stayed the same."})
        d1, d0 = float(last3[-1].outstanding_debt or 0), float(prev3[-1].outstanding_debt or 0)
        if d1 > d0 * 1.2 and d1 - d0 > 5000:
            signs.append({"text": f"Money you owe rose from KES {d0:,.0f} to KES {d1:,.0f}.",
                          "tip": "Plan repayments before taking more credit, and avoid buying slow stock on credit."})
    cash = sum(float(r.cash_inflows) - float(r.cash_outflows) for r in last3)
    if cash < 0:
        signs.append({"text": f"More cash went out than came in over the last 3 months (KES {cash:,.0f}).",
                      "tip": "Follow up money customers owe you, and hold off purchases that can wait."})
    band = "High" if last_net < 0 else "Moderate" if len(signs) >= 2 else "Low"
    return {"source": "rules", "band": band, "probability": None, "as_of": f"{recs[-1].month:%Y-%m}",
            "reasons": signs[:3], "protective": [], "last3_net": last_net}
