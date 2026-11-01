"""Synthetic SME business-months, to extend the real sample (proposal objective 2).

Every synthetic business is flagged is_synthetic=True, gets a SYN-### code, has no login,
and is reported separately everywhere. The simulation is deliberately simple and documented,
so the thesis can describe exactly how the extension was made:

- each business type has a typical monthly sales level, cost-of-goods ratio, M-Pesa share
  and sale size (SECTOR_PARAMS);
- a business follows one trajectory: healthy, declining sales, creeping costs, a temporary
  shock, or volatile;
- seasonality (December peak, January dip, school-fee months for schools), random noise,
  fixed running costs that rise with inflation, borrowing in bad months, and stock.

Losses are not drawn at random: they emerge from falling sales or rising costs, so the
warning signs come before the loss, as in real businesses.

    python -m ml.synthetic --businesses 60          # add 60 synthetic businesses
    python -m ml.synthetic --remove                 # delete all synthetic businesses
    python -m ml.synthetic --csv data/training/biashara_training_data.csv --businesses 500 --seed 2026
                                                    # write a training CSV instead (no database)
"""
import argparse
import math
import random
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

# type: (median monthly sales KES, cogs ratio low, high, M-Pesa share low, high, average sale KES)
SECTOR_PARAMS = {
    "retail": (150_000, .70, .80, .50, .80, 250),
    "wholesale": (600_000, .82, .90, .40, .70, 3_000),
    "service": (80_000, .10, .30, .60, .90, 800),
    "food": (120_000, .40, .55, .50, .80, 300),
    "agri": (100_000, .45, .65, .40, .70, 1_500),
    "manufacturing": (300_000, .50, .65, .30, .60, 5_000),
    "beauty": (70_000, .15, .30, .60, .90, 600),
    "fashion": (90_000, .50, .65, .50, .80, 1_200),
    "hardware": (250_000, .70, .82, .40, .70, 2_000),
    "electronics": (150_000, .65, .78, .50, .80, 1_500),
    "agent": (60_000, .00, .05, .90, .99, 50),
    "transport": (90_000, .30, .45, .70, .95, 200),
    "health": (160_000, .55, .70, .50, .80, 700),
    "education": (200_000, .05, .15, .60, .90, 5_000),
    "ict": (50_000, .20, .35, .60, .90, 150),
    "other": (100_000, .40, .60, .50, .80, 600),
}
SECTOR_WEIGHTS = {"retail": 18, "wholesale": 6, "service": 6, "food": 10, "agri": 6, "manufacturing": 3,
                  "beauty": 8, "fashion": 6, "hardware": 5, "electronics": 5, "agent": 5, "transport": 6,
                  "health": 4, "education": 3, "ict": 4, "other": 5}
TRAJECTORIES = [("healthy", 45), ("declining", 15), ("cost_creep", 15), ("shock", 15), ("volatile", 10)]


def _season(sector: str, month: int) -> float:
    if sector == "education":  # fees paid at the start of each term
        return {1: 1.7, 5: 1.6, 9: 1.6, 4: 0.5, 8: 0.5, 11: 0.6, 12: 0.4}.get(month, 0.9)
    if sector == "agri":
        return {3: 0.8, 4: 0.8, 7: 1.2, 8: 1.3, 11: 1.1, 12: 1.2}.get(month, 1.0)
    base = {12: 1.18, 1: 0.84, 2: 0.92, 4: 0.97, 11: 1.05}.get(month, 1.0)
    if sector in ("retail", "fashion", "food", "electronics"):
        base = 1 + (base - 1) * 1.4  # stronger festive season
    return base


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def simulate_business(rnd: random.Random, sector: str, n_months: int, last_month: date) -> tuple[list[dict], str]:
    """Returns (monthly rows, trajectory name)."""
    med, c_lo, c_hi, m_lo, m_hi, ticket = SECTOR_PARAMS[sector]
    base_rev = med * math.exp(rnd.gauss(0, 0.45))
    cogs_ratio = rnd.uniform(c_lo, c_hi)
    margin = rnd.uniform(0.05, 0.22)
    fixed_cost = base_rev * max(0.03, 1 - cogs_ratio - margin)
    mpesa_share = rnd.uniform(m_lo, m_hi)
    debt = base_rev * rnd.uniform(0, 0.5)
    stock = base_rev * cogs_ratio * rnd.uniform(0.6, 1.2)
    traj = rnd.choices([t for t, _ in TRAJECTORIES], weights=[w for _, w in TRAJECTORIES])[0]
    turn = rnd.randint(max(4, n_months // 3), max(5, n_months - 4))  # when trouble starts
    trend = rnd.uniform(0.003, 0.018) if traj == "healthy" else rnd.uniform(-0.004, 0.012)
    noise_sd = 0.20 if traj == "volatile" else 0.07
    drop, shock_len = rnd.uniform(0.25, 0.5), rnd.randint(2, 4)
    decline, creep = rnd.uniform(0.03, 0.07), rnd.uniform(0.005, 0.015)

    first = _add_months(last_month, -(n_months - 1))
    level, rows = 1.0, []
    for i in range(n_months):
        month = _add_months(first, i)
        level *= 1 + trend
        if traj == "declining" and i >= turn:
            level *= 1 - decline
        shock = 1 - drop if traj == "shock" and turn <= i < turn + shock_len else 1.0
        rev = base_rev * level * shock * _season(sector, month.month) * math.exp(rnd.gauss(0, noise_sd))
        ratio = cogs_ratio + (creep * (i - turn) if traj == "cost_creep" and i >= turn else 0)
        ratio = min(ratio, 0.97) * math.exp(rnd.gauss(0, 0.03))
        cogs = rev * ratio
        opex = fixed_cost * (1.004 ** i) * math.exp(rnd.gauss(0, 0.05))
        net = rev - cogs - opex
        borrow = 0.0
        if net < 0 and rnd.random() < 0.35:
            borrow = base_rev * rnd.uniform(0.2, 0.6)
        repay = min(debt, debt * 0.06 + (base_rev * 0.01 if debt > 0 else 0))
        debt = max(0.0, debt + borrow - repay)
        new_stock = max(0.0, stock + rnd.gauss(0, 0.05) * cogs)
        inflows = rev * rnd.uniform(0.92, 1.02) + borrow
        outflows = cogs + opex + repay + (new_stock - stock)
        stock = new_stock
        mpesa = min(inflows, inflows * min(0.99, mpesa_share + 0.004 * i))
        rows.append({
            "month": month, "revenue": round(rev), "cogs": round(cogs), "operating_expenses": round(opex),
            "cash_inflows": round(inflows), "cash_outflows": round(max(0.0, outflows)),
            "mobile_money_receipts": round(mpesa), "closing_stock": round(stock),
            "outstanding_debt": round(debt), "transaction_count": max(1, round(rev / ticket * math.exp(rnd.gauss(0, 0.1)))),
        })
    return rows, traj


def last_full_month(today: date | None = None) -> date:
    today = today or date.today()
    return _add_months(today.replace(day=1), -1)


def generate(db: Session, businesses: int = 60, seed: int | None = None, min_months: int = 18,
             max_months: int = 36, today: date | None = None) -> dict:
    """Adds synthetic businesses with their months. Returns a summary."""
    from app.models import Business, MonthlyRecord

    rnd = random.Random(seed)
    codes = db.scalars(select(Business.code).where(Business.code.like("SYN-%"))).all()
    nums = [int(c[4:]) for c in codes if c[4:].isdigit()]
    nxt = max(nums, default=0) + 1
    last = last_full_month(today)
    sectors, weights = list(SECTOR_WEIGHTS), list(SECTOR_WEIGHTS.values())
    months = losses = 0
    trajectories: dict[str, int] = {}
    for k in range(businesses):
        sector = rnd.choices(sectors, weights=weights)[0]
        n = rnd.randint(min_months, max_months)
        rows, traj = simulate_business(rnd, sector, n, last)
        trajectories[traj] = trajectories.get(traj, 0) + 1
        b = Business(code=f"SYN-{nxt + k:03d}", sector=sector, start_date=rows[0]["month"], is_synthetic=True)
        db.add(b)
        db.flush()
        for r in rows:
            db.add(MonthlyRecord(business_id=b.id, **r))
            months += 1
            losses += r["revenue"] - r["cogs"] - r["operating_expenses"] < 0
    db.commit()
    return {"businesses": businesses, "business_months": months, "loss_months": losses,
            "loss_rate": round(losses / months, 3) if months else 0, "trajectories": trajectories}


CSV_COLUMNS = ["business_code", "sector", "is_synthetic", "month", "revenue", "cogs", "operating_expenses",
               "cash_inflows", "cash_outflows", "mobile_money_receipts", "closing_stock", "outstanding_debt",
               "transaction_count", "net_operating_result", "loss_next_3m", "trajectory"]


def write_csv(path: str, businesses: int = 500, seed: int | None = 2026, min_months: int = 24,
              max_months: int = 48, today: date | None = None, prefix: str = "TRN") -> dict:
    """Writes synthetic businesses to a CSV in the same layout as Admin > Download all records,
    plus two columns for analysis: loss_next_3m (the model's label: 1 if any of the next 3 months is a
    loss, blank when those months aren't all in the file) and trajectory (the pattern simulated).
    The admin page can import it (Risk model > Import training data)."""
    import csv
    from pathlib import Path

    rnd = random.Random(seed)
    last = last_full_month(today)
    sectors, weights = list(SECTOR_WEIGHTS), list(SECTOR_WEIGHTS.values())
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    rows_out = losses = labelled = positives = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        for k in range(businesses):
            sector = rnd.choices(sectors, weights=weights)[0]
            # businesses end in different months, as real records do
            end = _add_months(last, -rnd.choice([0, 0, 0, 1, 2, 3]))
            rows, traj = simulate_business(rnd, sector, rnd.randint(min_months, max_months), end)
            nets = [r["revenue"] - r["cogs"] - r["operating_expenses"] for r in rows]
            for i, r in enumerate(rows):
                ahead = nets[i + 1:i + 4]
                label = "" if len(ahead) < 3 else int(any(n < 0 for n in ahead))
                w.writerow([f"{prefix}-{k + 1:04d}", sector, 1, f"{r['month']:%Y-%m}", r["revenue"], r["cogs"],
                            r["operating_expenses"], r["cash_inflows"], r["cash_outflows"], r["mobile_money_receipts"],
                            r["closing_stock"], r["outstanding_debt"], r["transaction_count"], nets[i], label, traj])
                rows_out += 1
                losses += nets[i] < 0
                if label != "":
                    labelled += 1
                    positives += label
    return {"businesses": businesses, "business_months": rows_out, "loss_months": losses,
            "loss_rate": round(losses / rows_out, 3), "labelled": labelled,
            "positive_rate": round(positives / labelled, 3) if labelled else 0}


def remove_all(db: Session) -> int:
    from app.erase import erase_business
    from app.models import Business

    synth = db.scalars(select(Business).where(Business.is_synthetic.is_(True))).all()
    for b in synth:
        erase_business(db, b)
    db.commit()
    return len(synth)


if __name__ == "__main__":
    from app.database import Base, SessionLocal, engine

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--businesses", type=int, default=60)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--remove", action="store_true", help="delete all synthetic businesses")
    ap.add_argument("--csv", help="write the businesses to this CSV file instead of the database")
    a = ap.parse_args()
    if a.csv:
        print(write_csv(a.csv, a.businesses, 2026 if a.seed is None else a.seed))
        raise SystemExit
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as s:
        if a.remove:
            print(f"Removed {remove_all(s)} synthetic businesses.")
        else:
            print(generate(s, a.businesses, a.seed))
