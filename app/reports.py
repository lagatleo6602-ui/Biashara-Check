"""PDF reports: monthly business report (owners), loan-readiness summary (Pro), study report (admins)."""
import io
import re
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AuditLog, Business, Contact, MonthlyRecord, Payment, User
from .sectors import SECTORS

FOREST, LEAF, MAIZE = "#0F3D2E", "#1C7350", "#F0B429"
INK, INK2, RULE, PAPER = "#13201A", "#55635B", "#DCE2DC", "#F2F4EF"
RED, AMBER = "#B3362C", "#96590A"
BAND_BG = {"Low": "#E3F0E8", "Moderate": "#FBEFDA", "High": "#F9E7E4"}
BAND_FG = {"Low": LEAF, "Moderate": AMBER, "High": RED}
VERDICT = {"Low": "Low risk of a loss in the next 3 months", "Moderate": "Moderate risk of a loss in the next 3 months",
           "High": "High risk of a loss in the next 3 months"}


def _rl():
    try:
        import reportlab  # noqa: F401
    except ImportError as exc:
        raise HTTPException(503, "PDF reports need reportlab. Stop the server, run "
                                 "venv\\Scripts\\pip install reportlab==4.2.5 and start it again.") from exc


def kes(x: float) -> str:
    return f"KES {x:,.0f}" if x >= 0 else f"-KES {abs(x):,.0f}"


def month_label(d) -> str:
    return f"{d:%b %Y}"


def net(r) -> float:
    return float(r.revenue) - float(r.cogs) - float(r.operating_expenses)


# ---------- building blocks ----------
def _styles():
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    base = getSampleStyleSheet()
    s = {
        "h1": ParagraphStyle("h1", parent=base["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24,
                             textColor="#FFFFFF", alignment=0, spaceAfter=2),
        "sub": ParagraphStyle("sub", parent=base["Normal"], fontSize=9.5, leading=13, textColor="#D7E6DD"),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16,
                             textColor=INK, spaceBefore=12, spaceAfter=6),
        "body": ParagraphStyle("body", parent=base["Normal"], fontSize=9.5, leading=13.5, textColor=INK),
        "small": ParagraphStyle("small", parent=base["Normal"], fontSize=8, leading=11, textColor=INK2),
        "verdict": ParagraphStyle("verdict", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=14, leading=18),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=8.5, leading=11, textColor=INK),
    }
    return s


def _header(title: str, lines: list[str], st) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, TableStyle
    inner = [Paragraph("Biashara Check", st["sub"]), Paragraph(title, st["h1"])] + \
            [Paragraph(x, st["sub"]) for x in lines]
    t = Table([[inner]], colWidths=[174 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), FOREST), ("LEFTPADDING", (0, 0), (-1, -1), 14),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 14), ("TOPPADDING", (0, 0), (-1, -1), 12),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 14)]))
    return [t]


def _table(rows: list[list], widths, st, header=True, align_right_from=1, zebra=True):
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, TableStyle
    data = [[c if not isinstance(c, str) else Paragraph(c, st["cell"]) for c in r] for r in rows]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1 if header else 0)
    style = [("FONTSIZE", (0, 0), (-1, -1), 8.5), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("LINEBELOW", (0, 0), (-1, -1), 0.25, RULE), ("TOPPADDING", (0, 0), (-1, -1), 4),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    if header:
        style += [("LINEBELOW", (0, 0), (-1, 0), 1, INK), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
    if zebra:
        for i in range(1 if header else 0, len(rows)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), "#F7F9F5"))
    t.setStyle(TableStyle(style))
    for row in t._cellvalues:
        for j, c in enumerate(row):
            if j >= align_right_from and hasattr(c, "style"):
                c.style = c.style.clone(c.style.name + "r", alignment=2)
    return t


def _risk_box(r: dict, st, model_note: str) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    b = r["band"]
    vs = st["verdict"].clone("v2", textColor=BAND_FG[b])
    parts = [Paragraph(VERDICT[b], vs)]
    if r.get("probability") is not None:
        parts.append(Paragraph(f"Chance of at least one loss month in the next 3 months: <b>{round(r['probability'] * 100)}%</b> "
                               f"(figures up to {r['as_of']}).", st["body"]))
    else:
        parts.append(Paragraph(f"Simple rule-based check on your figures up to {r['as_of']}.", st["body"]))
    if r.get("reasons"):
        parts.append(Spacer(1, 4))
        parts.append(Paragraph("<b>Main reasons and what you can do</b>" if b != "Low" else "<b>Worth keeping an eye on</b>", st["body"]))
        for x in r["reasons"][:3]:
            tip = f" <font color='{INK2}'>What you can do: {x['tip']}</font>" if x.get("tip") else ""
            parts.append(Paragraph(f"• {x['text']}{tip}", st["body"]))
    if r.get("protective"):
        parts.append(Paragraph("<b>What's working for you</b>", st["body"]))
        for x in r["protective"][:2]:
            parts.append(Paragraph(f"• {x['text']}", st["body"]))
    parts.append(Spacer(1, 3))
    parts.append(Paragraph(model_note, st["small"]))
    t = Table([[parts]], colWidths=[174 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BAND_BG[b]), ("LINEBEFORE", (0, 0), (0, -1), 4, BAND_FG[b]),
                           ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                           ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
    return [t]


def _profit_chart(recs, width=480, height=150):
    """Bars of profit or loss per month: green above zero, red below."""
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors
    vals = [net(r) for r in recs]
    d = Drawing(width, height + 20)
    c = VerticalBarChart()
    c.x, c.y, c.width, c.height = 46, 22, width - 56, height - 10
    c.data = [vals]
    c.categoryAxis.categoryNames = [f"{r.month:%b}" for r in recs]
    c.categoryAxis.labels.fontSize = 7
    c.categoryAxis.labels.fontName = "Helvetica"
    c.categoryAxis.labels.fillColor = colors.HexColor(INK2)
    c.categoryAxis.labelAxisMode = "low"  # month names under the chart, not on the zero line
    c.categoryAxis.strokeColor = colors.HexColor("#8A948E")
    lo, hi = min(vals + [0]), max(vals + [0])
    pad = (hi - lo) * 0.1 or 1000
    c.valueAxis.valueMin, c.valueAxis.valueMax = lo - (pad if lo < 0 else 0), hi + pad
    c.valueAxis.labels.fontSize = 7
    c.valueAxis.labels.fontName = "Helvetica"
    c.valueAxis.labels.fillColor = colors.HexColor(INK2)
    c.valueAxis.labelTextFormat = lambda v: f"{v / 1000:,.0f}k"
    c.valueAxis.strokeColor = colors.HexColor("#FFFFFF")
    c.valueAxis.gridStrokeColor = colors.HexColor("#E7EBE6")
    c.valueAxis.visibleGrid = True
    c.barSpacing, c.groupSpacing = 0, 6
    c.bars[0].strokeColor = None
    for i, v in enumerate(vals):
        c.bars[(0, i)].fillColor = colors.HexColor(RED if v < 0 else LEAF)
    d.add(c)
    d.add(String(46, height + 10, "Profit or loss each month (KES)", fontSize=8.5, fontName="Helvetica-Bold", fillColor=colors.HexColor(INK)))
    return d


def _lines_chart(recs, width=480, height=150):
    """Sales and total costs per month."""
    from reportlab.graphics.charts.linecharts import HorizontalLineChart
    from reportlab.graphics.shapes import Drawing, Line, String
    from reportlab.lib import colors
    sales = [float(r.revenue) for r in recs]
    costs = [float(r.cogs) + float(r.operating_expenses) for r in recs]
    d = Drawing(width, height + 20)
    c = HorizontalLineChart()
    c.x, c.y, c.width, c.height = 46, 22, width - 56, height - 10
    c.data = [sales, costs]
    c.categoryAxis.categoryNames = [f"{r.month:%b}" for r in recs]
    c.categoryAxis.labels.fontSize = 7
    c.categoryAxis.labels.fontName = "Helvetica"
    c.categoryAxis.labels.fillColor = colors.HexColor(INK2)
    c.valueAxis.valueMin = 0
    c.valueAxis.valueMax = max(sales + costs) * 1.12 or 1
    c.valueAxis.labels.fontSize = 7
    c.valueAxis.labels.fontName = "Helvetica"
    c.valueAxis.labels.fillColor = colors.HexColor(INK2)
    c.valueAxis.labelTextFormat = lambda v: f"{v / 1000:,.0f}k"
    c.valueAxis.visibleGrid = True
    c.valueAxis.gridStrokeColor = colors.HexColor("#E7EBE6")
    c.valueAxis.strokeColor = colors.HexColor("#FFFFFF")
    c.lines[0].strokeColor, c.lines[1].strokeColor = colors.HexColor("#2a78d6"), colors.HexColor("#eb6834")
    c.lines[0].strokeWidth = c.lines[1].strokeWidth = 2
    d.add(c)
    d.add(String(46, height + 10, "Sales and costs each month (KES)", fontSize=8.5, fontName="Helvetica-Bold", fillColor=colors.HexColor(INK)))
    for i, (label, col) in enumerate((("Sales", "#2a78d6"), ("Costs", "#eb6834"))):
        x = width - 130 + i * 62
        d.add(Line(x, height + 13, x + 14, height + 13, strokeColor=colors.HexColor(col), strokeWidth=2))
        d.add(String(x + 18, height + 10, label, fontSize=8, fontName="Helvetica", fillColor=colors.HexColor(INK2)))
    return d


def _footer(note: str, fp: str = ""):
    def draw(canvas, doc):
        from reportlab.lib.units import mm
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(INK2)
        canvas.drawString(18 * mm, 10 * mm, note)
        if fp:  # SHA-256 of the records this report was made from (see app/finance.py)
            canvas.setFont("Courier", 6.5)
            canvas.drawString(18 * mm, 6.5 * mm, f"Records fingerprint (SHA-256): {fp}")
        canvas.drawRightString(192 * mm, 10 * mm, f"Page {doc.page}")
        canvas.setStrokeColor(MAIZE)
        canvas.setLineWidth(1.5)
        canvas.line(18 * mm, 14 * mm, 30 * mm, 14 * mm)
        canvas.restoreState()
    return draw


def _fp(b) -> str:
    from .finance import fingerprint
    return fingerprint(b.records) if b.records else ""


def _build(story, note: str, title: str, fp: str = "") -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=20 * mm, title=title, author="Biashara Check")
    doc.build(story, onFirstPage=_footer(note, fp), onLaterPages=_footer(note, fp))
    return buf.getvalue()


def _records(db: Session, b: Business) -> list:
    return db.scalars(select(MonthlyRecord).where(MonthlyRecord.business_id == b.id).order_by(MonthlyRecord.month)).all()


def _risk_for(db: Session, b: Business, recs) -> tuple[dict | None, str]:
    from . import risk
    from .rules import rule_risk
    r = risk.compute(db, b) if risk.model_ready() else None
    if r:
        return r, (f"Prediction by the {r['model_name']} model ({r['model_version']}); reasons from SHAP. "
                   "Decision support, not a guarantee.")
    return rule_risk(recs), "Early check using simple rules, until the AI model is trained. Decision support, not a guarantee."


# ---------- 1. monthly business report ----------
def monthly_report(db: Session, b: Business) -> bytes:
    _rl()
    from reportlab.platypus import Paragraph, Spacer
    recs = _records(db, b)
    if not recs:
        raise HTTPException(400, "Add at least one month of figures to get a report.")
    st = _styles()
    last = recs[-1]
    prev = recs[-2] if len(recs) > 1 else None
    sector = SECTORS.get(b.sector, b.sector)
    story = _header("Monthly business report",
                    [f"{b.code} · {sector}", f"Figures up to {month_label(last.month)} · "
                     f"{len(recs)} months recorded · Generated {date.today():%d %b %Y}"], st)
    story.append(Spacer(1, 10))
    r, note = _risk_for(db, b, recs)
    if r:
        story += _risk_box(r, st, note)
    else:
        story.append(Paragraph("Add at least 3 months to get your first risk check.", st["body"]))

    story.append(Paragraph(f"Key figures for {month_label(last.month)}", st["h2"]))
    rows = [["", month_label(last.month), month_label(prev.month) if prev else "Previous month", "Change"]]

    def line(label, now, before, good_up=True):
        if before is None:
            return [label, kes(now), "–", "–"]
        ch = now - before
        pct = f" ({ch / abs(before) * 100:+.0f}%)" if before else ""
        better = (ch >= 0) == good_up
        col = LEAF if better or ch == 0 else RED
        return [label, kes(now), kes(before), f"<font color='{col}'>{'+' if ch >= 0 else '-'}{abs(ch):,.0f}{pct}</font>"]

    P = (lambda f: float(getattr(prev, f) or 0)) if prev else (lambda f: None)
    rows += [
        line("Total sales", float(last.revenue), P("revenue")),
        line("Cost of goods sold", float(last.cogs), P("cogs"), good_up=False),
        line("Running expenses", float(last.operating_expenses), P("operating_expenses"), good_up=False),
        line("<b>Profit or loss</b>", net(last), net(prev) if prev else None),
        line("Money received", float(last.cash_inflows), P("cash_inflows")),
        line("Money paid out", float(last.cash_outflows), P("cash_outflows"), good_up=False),
        line("Received by M-Pesa", float(last.mobile_money_receipts or 0), P("mobile_money_receipts")),
        line("Money owed", float(last.outstanding_debt or 0), P("outstanding_debt"), good_up=False),
    ]
    story.append(_table(rows, [52, 40, 40, 42], st))
    margin = net(last) / float(last.revenue) * 100 if float(last.revenue) else 0
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"From every 100 shillings of sales in {month_label(last.month)} you kept "
                           f"<b>{margin:.0f}</b> as profit.", st["body"]))

    tail = recs[-12:]
    if len(tail) >= 2:
        story.append(Paragraph("The last 12 months", st["h2"]))
        story.append(_profit_chart(tail))
        story.append(Spacer(1, 6))
        story.append(_lines_chart(tail))
        rows = [["Month", "Sales", "Costs", "Profit or loss", "Cash in minus out"]]
        for x in reversed(tail):
            n = net(x)
            cf = float(x.cash_inflows) - float(x.cash_outflows)
            rows.append([month_label(x.month), kes(float(x.revenue)), kes(float(x.cogs) + float(x.operating_expenses)),
                         f"<font color='{RED if n < 0 else INK}'>{kes(n)}</font>",
                         f"<font color='{RED if cf < 0 else INK}'>{kes(cf)}</font>"])
        story.append(Spacer(1, 6))
        story.append(_table(rows, [30, 36, 36, 36, 36], st))
    return _build(story, "Biashara Check · decision support, not a guarantee · your figures are never shared with lenders",
                  f"Biashara Check report {b.code}", _fp(b))


# ---------- 2. loan-readiness summary (Pro) ----------
def _mpesa_imported_months(db: Session, b: Business) -> set[str]:
    out = set()
    for d in db.scalars(select(AuditLog.detail).where(AuditLog.action == "mpesa.statement_applied",
                                                      AuditLog.target == b.code)).all():
        out.update(re.findall(r"\d{4}-\d{2}", d or ""))
    return out


def loan_report(db: Session, b: Business) -> bytes:
    _rl()
    from reportlab.platypus import Paragraph, Spacer
    recs = _records(db, b)[-12:]
    if len(recs) < 6:
        raise HTTPException(400, "The loan-readiness report needs at least 6 months of figures.")
    st = _styles()
    imported = _mpesa_imported_months(db, b)
    sales = [float(r.revenue) for r in recs]
    profits = [net(r) for r in recs]
    mpesa = sum(float(r.mobile_money_receipts or 0) for r in recs)
    inflows = sum(float(r.cash_inflows) for r in recs)
    g = (sum(sales[-3:]) - sum(sales[:3])) / sum(sales[:3]) * 100 if sum(sales[:3]) else 0
    ref = f"BC-{b.code}-{date.today():%Y%m%d}"
    story = _header("Business performance summary",
                    [f"{b.code} · {SECTORS.get(b.sector, b.sector)}",
                     f"{month_label(recs[0].month)} to {month_label(recs[-1].month)} ({len(recs)} months) · Reference {ref}"], st)
    story.append(Spacer(1, 10))
    story.append(Paragraph("Prepared from the business's monthly records in Biashara Check, for a lender, SACCO or "
                           "supplier assessing the business. Amounts in Kenya shillings.", st["body"]))
    story.append(Paragraph("Summary", st["h2"]))
    r, note = _risk_for(db, b, _records(db, b))
    rows = [["Measure", "Value"],
            ["Average monthly sales", kes(sum(sales) / len(sales))],
            ["Average monthly profit", kes(sum(profits) / len(profits))],
            ["Profitable months", f"{sum(p > 0 for p in profits)} of {len(profits)}"],
            ["Sales trend (first 3 vs last 3 months)", f"{g:+.0f}%"],
            ["Total received by M-Pesa", f"{kes(mpesa)} ({mpesa / inflows * 100:.0f}% of money received)" if inflows else kes(mpesa)],
            ["Months with M-Pesa figures from a statement", f"{len(imported & {f'{x.month:%Y-%m}' for x in recs})} of {len(recs)}"],
            ["Money owed (latest month)", kes(float(recs[-1].outstanding_debt or 0))],
            ["Current 90-day loss risk", r["band"] + (f" ({round(r['probability'] * 100)}%)" if r and r.get("probability") is not None else "") if r else "–"]]
    story.append(_table(rows, [90, 84], st))
    story.append(Spacer(1, 8))
    story.append(_profit_chart(recs))
    story.append(Paragraph("Monthly figures", st["h2"]))
    rows = [["Month", "Sales", "Costs", "Profit or loss", "Received by M-Pesa"]]
    for x in reversed(recs):
        tag = " *" if f"{x.month:%Y-%m}" in imported else ""
        rows.append([month_label(x.month), kes(float(x.revenue)), kes(float(x.cogs) + float(x.operating_expenses)),
                     kes(net(x)), kes(float(x.mobile_money_receipts or 0)) + tag])
    story.append(_table(rows, [30, 36, 36, 36, 36], st))
    story.append(Spacer(1, 4))
    story.append(Paragraph("* M-Pesa receipts for this month were read from the owner's M-Pesa statement. Other figures "
                           "were entered by the owner and have not been audited.", st["small"]))
    story.append(Spacer(1, 18))
    story.append(Paragraph("Owner's declaration: I confirm these figures are a true record of my business.", st["body"]))
    story.append(Spacer(1, 18))
    story.append(Paragraph("Signature: ______________________________ &nbsp;&nbsp;&nbsp; Date: ________________", st["body"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph(note, st["small"]))
    return _build(story, f"Biashara Check · {ref} · owner-reported figures, not audited", f"Business summary {b.code}", _fp(b))


# ---------- 2b. full business report (Pro) ----------
BLUE, ORANGE, GREY, PURPLE = "#2a78d6", "#eb6834", "#8A948E", "#6f4bb8"
PERIODS = {6: "Last 6 months", 12: "Last 12 months", 24: "Last 24 months", 0: "All months"}


def _labels(recs) -> list[str]:
    """Month names under a chart: with the year when the period spans years, thinned out when crowded."""
    multi_year = recs[0].month.year != recs[-1].month.year
    step = 1 if len(recs) <= 14 else 2 if len(recs) <= 28 else 3
    out = []
    for i, r in enumerate(recs):
        if i % step and i != len(recs) - 1:
            out.append("")
        else:
            out.append(f"{r.month:%b %y}" if multi_year else f"{r.month:%b}")
    return out


def _axis(ax, fmt=None):
    from reportlab.lib import colors
    ax.labels.fontSize = 7
    ax.labels.fontName = "Helvetica"
    ax.labels.fillColor = colors.HexColor(INK2)
    if fmt:
        ax.labelTextFormat = fmt


def _k(v):
    return f"{v / 1000:,.0f}k" if abs(v) >= 1000 else f"{v:,.0f}"


def _title(d, title, width, height, legend=()):
    from reportlab.graphics.shapes import Line, Rect, String
    from reportlab.lib import colors
    d.add(String(46, height + 10, title, fontSize=8.5, fontName="Helvetica-Bold", fillColor=colors.HexColor(INK)))
    x = width - 8
    for label, col, kind in reversed(legend):
        w = 18 + len(label) * 4.4
        x -= w
        if kind == "line":
            d.add(Line(x, height + 13, x + 12, height + 13, strokeColor=colors.HexColor(col), strokeWidth=2))
        else:
            d.add(Rect(x, height + 9, 9, 8, fillColor=colors.HexColor(col), strokeColor=None))
        d.add(String(x + 15, height + 10, label, fontSize=7.5, fontName="Helvetica", fillColor=colors.HexColor(INK2)))
        x -= 6


def bar_chart(recs, values, title, *, color_fn=None, fmt=_k, width=480, height=135, legend=()):
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors
    d = Drawing(width, height + 20)
    c = VerticalBarChart()
    c.x, c.y, c.width, c.height = 46, 22, width - 56, height - 10
    c.data = [values]
    c.categoryAxis.categoryNames = _labels(recs)
    _axis(c.categoryAxis)
    c.categoryAxis.labelAxisMode = "low"
    c.categoryAxis.strokeColor = colors.HexColor(GREY)
    lo, hi = min(values + [0]), max(values + [0])
    pad = (hi - lo) * 0.1 or 1000
    c.valueAxis.valueMin, c.valueAxis.valueMax = lo - (pad if lo < 0 else 0), hi + pad
    _axis(c.valueAxis, fmt)
    c.valueAxis.strokeColor = colors.HexColor("#FFFFFF")
    c.valueAxis.gridStrokeColor = colors.HexColor("#E7EBE6")
    c.valueAxis.visibleGrid = True
    c.barSpacing, c.groupSpacing = 0, 4 if len(values) > 14 else 6
    c.bars[0].strokeColor = None
    for i, v in enumerate(values):
        c.bars[(0, i)].fillColor = colors.HexColor(color_fn(v) if color_fn else LEAF)
    d.add(c)
    _title(d, title, width, height, legend)
    return d


def stacked_chart(recs, series, title, *, fmt=_k, width=480, height=135):
    """series: [(name, values, colour)], stacked bottom to top."""
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors
    d = Drawing(width, height + 20)
    c = VerticalBarChart()
    c.x, c.y, c.width, c.height = 46, 22, width - 56, height - 10
    c.data = [v for _, v, _ in series]
    c.categoryAxis.style = "stacked"
    c.categoryAxis.categoryNames = _labels(recs)
    _axis(c.categoryAxis)
    c.categoryAxis.strokeColor = colors.HexColor(GREY)
    c.valueAxis.valueMin = 0
    c.valueAxis.valueMax = max(sum(col) for col in zip(*c.data)) * 1.1 or 1
    _axis(c.valueAxis, fmt)
    c.valueAxis.strokeColor = colors.HexColor("#FFFFFF")
    c.valueAxis.gridStrokeColor = colors.HexColor("#E7EBE6")
    c.valueAxis.visibleGrid = True
    c.barSpacing, c.groupSpacing = 0, 4 if len(recs) > 14 else 6
    for i, (_, _, col) in enumerate(series):
        c.bars[i].fillColor = colors.HexColor(col)
        c.bars[i].strokeColor = colors.white
        c.bars[i].strokeWidth = 0.5
    d.add(c)
    _title(d, title, width, height, [(n, col, "box") for n, _, col in series])
    return d


def line_chart(recs, series, title, *, fmt=_k, width=480, height=135, zero=True, ref=None):
    """series: [(name, values, colour)]. ref: (value, label) drawn as a dashed line."""
    from reportlab.graphics.charts.linecharts import HorizontalLineChart
    from reportlab.graphics.shapes import Drawing, Line, String
    from reportlab.lib import colors
    d = Drawing(width, height + 20)
    c = HorizontalLineChart()
    c.x, c.y, c.width, c.height = 46, 22, width - 56, height - 10
    c.data = [v for _, v, _ in series]
    c.categoryAxis.categoryNames = _labels(recs)
    _axis(c.categoryAxis)
    c.categoryAxis.labelAxisMode = "low"  # month names under the chart even when values go below zero
    c.categoryAxis.strokeColor = colors.HexColor(GREY)
    allv = [x for v in c.data for x in v] + ([ref[0]] if ref else [])
    lo, hi = min(allv), max(allv)
    pad = (hi - lo) * 0.12 or 1
    c.valueAxis.valueMin = 0 if zero and lo >= 0 else lo - pad
    c.valueAxis.valueMax = hi + pad
    _axis(c.valueAxis, fmt)
    c.valueAxis.visibleGrid = True
    c.valueAxis.gridStrokeColor = colors.HexColor("#E7EBE6")
    c.valueAxis.strokeColor = colors.HexColor("#FFFFFF")
    for i, (_, _, col) in enumerate(series):
        c.lines[i].strokeColor = colors.HexColor(col)
        c.lines[i].strokeWidth = 2
    d.add(c)
    if ref:
        v0, v1 = c.valueAxis.valueMin, c.valueAxis.valueMax
        y = c.y + (ref[0] - v0) / (v1 - v0) * c.height
        d.add(Line(c.x, y, c.x + c.width, y, strokeColor=colors.HexColor(GREY), strokeWidth=0.8, strokeDashArray=[3, 2]))
        d.add(String(c.x + c.width - 2, y + 3, ref[1], fontSize=6.5, fontName="Helvetica", textAnchor="end",
                     fillColor=colors.HexColor(INK2)))
    _title(d, title, width, height, [(n, col, "line") for n, _, col in series] if len(series) > 1 else ())
    return d


def _tiles(items, st):
    """A row of 4 boxed figures: [(label, value, note, colour)]."""
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, TableStyle
    cells = []
    for label, value, note, col in items:
        cells.append([Paragraph(label, st["small"]),
                      Paragraph(f"<font color='{col}'><b>{value}</b></font>", st["body"].clone("tv", fontSize=13, leading=17)),
                      Paragraph(note or "&nbsp;", st["small"])])
    t = Table([cells], colWidths=[43.5 * mm] * len(cells))
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), "#F4F7F2"), ("BOX", (0, 0), (-1, -1), 0, "#FFFFFF"),
                           ("LINEAFTER", (0, 0), (-2, -1), 3, "#FFFFFF"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 7),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return t


def _change(now: float, before: float | None, good_up=True) -> tuple[str, str]:
    if before is None or before == 0:
        return "", INK2
    ch = (now - before) / abs(before) * 100
    better = (ch >= 0) == good_up
    return f"{ch:+.0f}% on the {{n}} months before", LEAF if better else RED


def business_report(db: Session, b: Business, months: int = 12) -> bytes:
    _rl()
    from reportlab.platypus import CondPageBreak, Paragraph, Spacer
    from . import risk as risk_mod
    allrecs = _records(db, b)
    if len(allrecs) < 2:
        raise HTTPException(400, "The business report needs at least 2 months of figures.")
    recs = allrecs[-months:] if months else allrecs
    before = allrecs[-2 * len(recs):-len(recs)] if months and len(allrecs) >= 2 * len(recs) else None
    st = _styles()
    n = len(recs)
    f = lambda rs, a: sum(float(getattr(r, a) or 0) for r in rs)  # noqa: E731
    sales, cogs, opex = f(recs, "revenue"), f(recs, "cogs"), f(recs, "operating_expenses")
    profit = sales - cogs - opex
    cash = f(recs, "cash_inflows") - f(recs, "cash_outflows")
    inflow, mpesa = f(recs, "cash_inflows"), f(recs, "mobile_money_receipts")
    profitable = sum(net(r) > 0 for r in recs)
    period = f"{month_label(recs[0].month)} to {month_label(recs[-1].month)}"
    story = _header("Business report", [
        f"{b.code} · {SECTORS.get(b.sector, b.sector)} · Biashara Pro",
        f"{period} ({n} month{'s' if n != 1 else ''}) · Generated {date.today():%d %b %Y}"], st)
    story.append(Spacer(1, 10))

    # --- at a glance
    story.append(Paragraph("At a glance", st["h2"]))
    def ch(now, attr_fn, good_up=True):
        if not before:
            return "", INK2
        txt, col = _change(now, attr_fn(before), good_up)
        return txt.format(n=len(before)), col
    s_note, _ = ch(sales, lambda rs: f(rs, "revenue"))
    p_note, _ = ch(profit, lambda rs: f(rs, "revenue") - f(rs, "cogs") - f(rs, "operating_expenses"))
    story.append(_tiles([
        ("Total sales", kes(sales), s_note, INK),
        ("Gross profit", kes(sales - cogs), f"Sales minus cost of goods ({(sales - cogs) / sales * 100:.0f}% of sales)" if sales else "Sales minus cost of goods", RED if sales < cogs else INK),
        ("Profit or loss", kes(profit), p_note, RED if profit < 0 else LEAF),
        ("Kept from every 100 sold", f"{profit / sales * 100:.0f} shillings" if sales else "-", "Profit per 100 KES of sales", RED if profit < 0 else INK),
    ], st))
    story.append(Spacer(1, 6))
    debt_now = float(recs[-1].outstanding_debt or 0)
    debt_then = float(recs[0].outstanding_debt or 0)
    story.append(_tiles([
        ("Profitable months", f"{profitable} of {n}", f"{n - profitable} loss month{'s' if n - profitable != 1 else ''}" if n - profitable else "No loss months", RED if profitable < n / 2 else INK),
        ("Cash left over", kes(cash), "Money received minus paid out", RED if cash < 0 else INK),
        ("Received by M-Pesa", f"{mpesa / inflow * 100:.0f}%" if inflow else "-", kes(mpesa), INK),
        ("Money owed now", kes(debt_now), (f"{'Up' if debt_now > debt_then else 'Down'} from {kes(debt_then)}" if debt_now != debt_then else "Unchanged"),
         RED if debt_now > debt_then * 1.2 and debt_now - debt_then > 5000 else INK),
    ], st))

    # --- risk
    r, note = _risk_for(db, b, allrecs)
    if r:
        story.append(Paragraph("Risk of a loss in the next 3 months", st["h2"]))
        story += _risk_box(r, st, note)
        hist = risk_mod.history(db, b, limit=36)
        hist = [h for h in hist if h["month"] >= f"{recs[0].month:%Y-%m}"]
        if len(hist) >= 3:
            class _M:  # chart helper needs .month
                def __init__(s, m): s.month = date.fromisoformat(m + "-01")
            story.append(Spacer(1, 6))
            story.append(line_chart([_M(h["month"]) for h in hist], [("Risk", [h["probability"] * 100 for h in hist], PURPLE)],
                                    "Chance of a loss month in the next 3 months, as checked each month (%)",
                                    fmt=lambda v: f"{v:.0f}%", height=110, ref=(60, "High from 60%")))

    # --- charts (each section starts on a new page only when it wouldn't fit)
    story.append(CondPageBreak(200))
    story.append(Paragraph("Profit, sales and costs", st["h2"]))
    nets = [net(r) for r in recs]
    story.append(bar_chart(recs, nets, "Profit or loss each month (KES)", color_fn=lambda v: RED if v < 0 else LEAF))
    story.append(Spacer(1, 8))
    story.append(line_chart(recs, [("Sales", [float(r.revenue) for r in recs], BLUE),
                                   ("Total costs", [float(r.cogs) + float(r.operating_expenses) for r in recs], ORANGE)],
                            "Sales and costs each month (KES)"))
    story.append(Spacer(1, 8))
    story.append(stacked_chart(recs, [("Cost of goods", [float(r.cogs) for r in recs], "#9FB8AA"),
                                      ("Running expenses", [float(r.operating_expenses) for r in recs], ORANGE)],
                               "Where the money went: costs each month (KES)"))
    story.append(Spacer(1, 8))
    margins = [net(r) / float(r.revenue) * 100 if float(r.revenue) else 0 for r in recs]
    story.append(line_chart(recs, [("Kept per 100", margins, LEAF)],
                            "Profit kept from every 100 shillings of sales", fmt=lambda v: f"{v:.0f}", zero=False,
                            ref=(0, "Break-even")))

    story.append(CondPageBreak(200))
    story.append(Paragraph("Cash, money owed and customers", st["h2"]))
    flows = [float(r.cash_inflows) - float(r.cash_outflows) for r in recs]
    story.append(bar_chart(recs, flows, "Cash left over each month: money received minus paid out (KES)",
                           color_fn=lambda v: RED if v < 0 else BLUE))
    story.append(Spacer(1, 8))
    debt = [float(r.outstanding_debt or 0) for r in recs]
    stock = [float(r.closing_stock or 0) for r in recs]
    if any(debt) or any(stock):
        story.append(line_chart(recs, [("Money owed", debt, RED), ("Stock value", stock, GREY)],
                                "Money owed and stock at the end of each month (KES)"))
        story.append(Spacer(1, 8))
    mp = [float(r.mobile_money_receipts or 0) / float(r.cash_inflows) * 100 if float(r.cash_inflows) else 0 for r in recs]
    if any(mp):
        story.append(line_chart(recs, [("M-Pesa share", mp, LEAF)], "Share of money received that came by M-Pesa (%)",
                                fmt=lambda v: f"{v:.0f}%"))
        story.append(Spacer(1, 8))
    tx = [int(r.transaction_count or 0) for r in recs]
    if any(tx):
        avg = [float(r.revenue) / t if t else 0 for r, t in zip(recs, tx)]
        story.append(bar_chart(recs, [float(t) for t in tx], "Number of sales each month", color_fn=lambda v: BLUE,
                               fmt=lambda v: f"{v:,.0f}"))
        story.append(Spacer(1, 8))
        story.append(line_chart(recs, [("Average sale", avg, ORANGE)], "Average sale value (KES)", fmt=lambda v: f"{v:,.0f}"))

    # --- highlights
    story.append(CondPageBreak(90))
    story.append(Paragraph("Highlights", st["h2"]))
    best = max(recs, key=net)
    worst = min(recs, key=net)
    streak = cur = 0
    for r in recs:
        cur = cur + 1 if net(r) > 0 else 0
        streak = max(streak, cur)
    half = n // 2
    pts = [f"Best month: <b>{month_label(best.month)}</b>, with a profit of {kes(net(best))} on sales of {kes(float(best.revenue))}.",
           f"Weakest month: <b>{month_label(worst.month)}</b>, {'a loss' if net(worst) < 0 else 'a profit'} of {kes(abs(net(worst)))}.",
           f"Longest run of profitable months: <b>{streak}</b>."]
    if half >= 2:
        s1, s2 = f(recs[:half], "revenue"), f(recs[-half:], "revenue")
        c1 = f(recs[:half], "cogs") + f(recs[:half], "operating_expenses")
        c2 = f(recs[-half:], "cogs") + f(recs[-half:], "operating_expenses")
        if s1 and c1:
            gs, gc = (s2 - s1) / s1 * 100, (c2 - c1) / c1 * 100
            pts.append(f"Comparing the last {half} months with the first {half}: sales {'grew' if gs >= 0 else 'fell'} "
                       f"<b>{abs(gs):.0f}%</b> and costs {'grew' if gc >= 0 else 'fell'} <b>{abs(gc):.0f}%</b>."
                       + (" Costs are growing faster than sales: check supplier prices and running costs." if gc - gs > 3 else ""))
    if before:
        pb = f(before, "revenue") - f(before, "cogs") - f(before, "operating_expenses")
        pts.append(f"Profit in this period: {kes(profit)}, against {kes(pb)} in the {len(before)} months before.")
    for p in pts:
        story.append(Paragraph("• " + p, st["body"]))

    # --- table
    story.append(Paragraph("Month by month", st["h2"]))
    rows = [["Month", "Sales", "Goods", "Running", "Profit or loss", "Per 100", "Cash left", "M-Pesa", "Owed"]]
    for x in reversed(recs):
        nn = net(x)
        cf = float(x.cash_inflows) - float(x.cash_outflows)
        rows.append([month_label(x.month), _k(float(x.revenue)), _k(float(x.cogs)), _k(float(x.operating_expenses)),
                     f"<font color='{RED if nn < 0 else INK}'>{_k(nn)}</font>",
                     f"{nn / float(x.revenue) * 100:.0f}" if float(x.revenue) else "-",
                     f"<font color='{RED if cf < 0 else INK}'>{_k(cf)}</font>",
                     _k(float(x.mobile_money_receipts or 0)), _k(float(x.outstanding_debt or 0))])
    rows.append(["<b>Total</b>", f"<b>{_k(sales)}</b>", f"<b>{_k(cogs)}</b>", f"<b>{_k(opex)}</b>",
                 f"<b><font color='{RED if profit < 0 else INK}'>{_k(profit)}</font></b>",
                 f"<b>{profit / sales * 100:.0f}</b>" if sales else "-", f"<b>{_k(cash)}</b>", f"<b>{_k(mpesa)}</b>", ""])
    story.append(_table(rows, [20, 20, 19, 19, 24, 15, 20, 19, 18], st))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Amounts in Kenya shillings; k = thousands. Per 100 = profit kept from every 100 shillings of sales. "
                           "Figures as entered by the owner.", st["small"]))
    return _build(story, "Biashara Check Pro · decision support, not a guarantee · your figures are never shared with lenders",
                  f"Business report {b.code}", _fp(b))


# ---------- 3. study report (admins) ----------
def study_report(db: Session) -> bytes:
    _rl()
    from reportlab.platypus import PageBreak, Paragraph, Spacer
    st = _styles()
    bs = db.scalars(select(Business)).all()
    recs = db.scalars(select(MonthlyRecord)).all()
    by_b: dict[int, list] = {}
    for r in recs:
        by_b.setdefault(r.business_id, []).append(r)
    real_b = [b for b in bs if not b.is_synthetic]
    real_r = [r for b in real_b for r in by_b.get(b.id, [])]
    syn_r = [r for b in bs if b.is_synthetic for r in by_b.get(b.id, [])]
    loss = lambda rs: sum(net(r) < 0 for r in rs)  # noqa: E731
    story = _header("Study data report", [f"Explainable ML early-warning system for SME operating-loss risk · "
                                          f"Generated {datetime.now():%d %b %Y, %H:%M}"], st)
    story.append(Paragraph("Data collected", st["h2"]))
    target = 1500
    rows = [["", "Real", "Synthetic", "Total"],
            ["Businesses", f"{len(real_b)}", f"{len(bs) - len(real_b)}", f"{len(bs)}"],
            ["Business-months", f"{len(real_r):,}", f"{len(syn_r):,}", f"{len(recs):,}"],
            ["Loss months", f"{loss(real_r):,}", f"{loss(syn_r):,}", f"{loss(recs):,}"],
            ["Loss months, share", f"{loss(real_r) / len(real_r) * 100:.1f}%" if real_r else "–",
             f"{loss(syn_r) / len(syn_r) * 100:.1f}%" if syn_r else "–",
             f"{loss(recs) / len(recs) * 100:.1f}%" if recs else "–"]]
    story.append(_table(rows, [64, 36, 36, 38], st))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"Progress to the target of {target:,} business-months: <b>{len(recs) / target * 100:.0f}%</b> "
                           f"overall, {len(real_r) / target * 100:.0f}% from real businesses.", st["body"]))

    story.append(Paragraph("By type of business (real businesses)", st["h2"]))
    rows = [["Type of business", "Businesses", "Months", "Loss months"]]
    for k, label in SECTORS.items():
        bk = [b for b in real_b if b.sector == k]
        if not bk:
            continue
        rk = [r for b in bk for r in by_b.get(b.id, [])]
        rows.append([label, str(len(bk)), str(len(rk)), f"{loss(rk)} ({loss(rk) / len(rk) * 100:.0f}%)" if rk else "0"])
    if len(rows) == 1:
        rows.append(["No real businesses yet", "", "", ""])
    story.append(_table(rows, [80, 30, 30, 34], st))

    story.append(Paragraph("Data completeness (real business-months)", st["h2"]))
    rows = [["Optional field", "Months filled in"]]
    for f, label in (("mobile_money_receipts", "Received by M-Pesa"), ("closing_stock", "Stock value"),
                     ("outstanding_debt", "Money owed"), ("transaction_count", "Number of sales")):
        n = sum(float(getattr(r, f) or 0) > 0 for r in real_r)
        rows.append([label, f"{n} of {len(real_r)} ({n / len(real_r) * 100:.0f}%)" if real_r else "–"])
    story.append(_table(rows, [80, 94], st))

    owners = db.scalars(select(User).where(User.role == "owner")).all()
    conts = {c.user_id: c for c in db.scalars(select(Contact)).all()}
    ver = sum(1 for o in owners if conts.get(o.id) and conts[o.id].email_verified_at)
    phone = sum(1 for o in owners if conts.get(o.id) and conts[o.id].phone_verified_at)
    paid = db.scalars(select(Payment).where(Payment.status == "paid")).all()
    story.append(Paragraph("Participants", st["h2"]))
    rows = [["", "Count"], ["Owner accounts", str(len(owners))],
            ["Email confirmed", f"{ver} of {len(owners)}"], ["Phone confirmed", f"{phone} of {len(owners)}"],
            ["Businesses with Biashara Pro now", str(sum(1 for b in bs if b.pro_until and b.pro_until > datetime.utcnow()))],
            ["Paid Pro payments (not test mode)", str(sum(1 for p in paid if p.mode != "test"))]]
    story.append(_table(rows, [80, 94], st))

    from .routers.feedback import summary as fb_summary
    fb = fb_summary(db)
    story.append(Paragraph("User evaluation (questionnaire)", st["h2"]))
    if fb["responses"]:
        story.append(Paragraph(f"{fb['responses']} response{'s' if fb['responses'] != 1 else ''}; ratings from 1 "
                               "(strongly disagree) to 5 (strongly agree).", st["body"]))
        rows = [["Group", "Average"]] + [[g["group"], f"{g['mean']:.2f}" if g["mean"] is not None else "-"] for g in fb["groups"]]
        story.append(_table(rows, [120, 54], st))
        story.append(Spacer(1, 6))
        rows = [["Statement", "Average", "Answers"]] + [[q["question"], f"{q['mean']:.2f}" if q["mean"] is not None else "-", str(q["n"])]
                                                        for q in fb["questions"]]
        story.append(_table(rows, [118, 28, 28], st))
    else:
        story.append(Paragraph("No questionnaire responses yet.", st["body"]))

    from . import risk
    if risk.model_ready():
        from ml.predict import friendly
        from ml.train import load
        _, m = load()
        if m:
            story.append(PageBreak())
            story.append(Paragraph("Risk model", st["h2"]))
            story.append(Paragraph(
                f"Best model: <b>{m['best_name']}</b> (version {m['version']}), trained {m['trained_at'][:16].replace('T', ' ')} UTC "
                f"on {m['rows']['labelled']:,} business-months from {m['rows']['businesses']} businesses "
                f"({m['rows']['real']:,} real, {m['rows']['synthetic']:,} synthetic). Time-based split: tested on "
                f"{m['rows']['test']:,} business-months from {m['test_from']}; {m['rows']['positive_rate'] * 100:.1f}% of "
                "business-months were followed by a loss within 90 days.", st["body"]))
            rows = [["Model", "PR-AUC", "ROC-AUC", "Recall", "Precision", "F1", "Brier"]]
            for k, x in sorted(m["models"].items(), key=lambda kv: -kv[1]["pr_auc"]):
                rows.append([x["name"] + (" (best)" if k == m["best"] else ""), f"{x['pr_auc']:.3f}", f"{x['roc_auc']:.3f}",
                             f"{x['recall']:.3f}", f"{x['precision']:.3f}", f"{x['f1']:.3f}", f"{x['brier']:.3f}"])
            story.append(Spacer(1, 4))
            story.append(_table(rows, [54, 20, 20, 20, 20, 20, 20], st))
            c = m["models"][m["best"]]["confusion"]
            story.append(Paragraph("Confusion matrix, best model, threshold 0.5", st["h2"]))
            story.append(_table([["", "Predicted: no loss", "Predicted: loss"],
                                 ["Actual: no loss", f"{c['tn']:,} correctly calm", f"{c['fp']:,} false alarms"],
                                 ["Actual: loss", f"{c['fn']:,} missed losses", f"{c['tp']:,} losses caught"]],
                                [50, 62, 62], st, zebra=False))
            story.append(Paragraph("What drives the predictions (mean |SHAP|, test months)", st["h2"]))
            rows = [["Feature", "Mean |SHAP|"]] + [[friendly(x["feature"]), f"{x['value']:.4f}"] for x in m["importance"][:10]]
            story.append(_table(rows, [120, 54], st))
    return _build(story, "Biashara Check · study report · no personal data", "Biashara Check study report")
