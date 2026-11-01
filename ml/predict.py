"""Risk for one business: probability of a loss in the next 90 days, its band, and the
SHAP reasons turned into plain language with a suggested action."""
import numpy as np
import pandas as pd

from app.sectors import SECTORS

from . import features as F
from .train import band, calibrate, load, shap_values

NAMES = {
    "margin": "Profit margin this month", "margin_3m": "Profit margin, last 3 months",
    "margin_trend": "Change in profit margin", "losses_last3": "Recent loss months",
    "rev_growth_3m": "Sales trend", "cost_growth_3m": "Cost trend", "cost_vs_sales_growth": "Costs vs sales growth",
    "rev_mom": "Sales change from last month", "cogs_ratio": "Cost of goods share", "opex_ratio": "Running costs share",
    "net_cf_ratio": "Cash left over", "neg_cf_months_3": "Months with cash going out", "mpesa_share": "M-Pesa share",
    "tx_growth_3m": "Number of sales trend", "debt_to_rev": "Money owed", "debt_growth_3m": "Change in money owed",
    "stock_to_rev": "Stock on hand", "age_months": "Length of records", "month_sin": "Time of year",
    "month_cos": "Time of year", "time_of_year": "Time of year", "business_type": "Type of business",
}
for _k, _v in SECTORS.items():
    NAMES[f"sector_{_k}"] = f"Business type: {_v}"


def friendly(feature: str) -> str:
    return NAMES.get(feature, feature)


def _pct(x: float) -> str:
    return f"{abs(x) * 100:.0f}%"


def _per100(x: float) -> str:
    return f"{x * 100:.0f}"


def _sh(x: float) -> str:
    """'1 shilling' / '12 shillings' for a share of every 100 shillings."""
    n = round(x * 100)
    return f"{n} shilling" if abs(n) == 1 else f"{n} shillings"


# Figures whose sign tells good from bad: +1 = a positive value is the worse side, -1 = a negative value is.
SIGNED = {"margin": -1, "margin_3m": -1, "margin_trend": -1, "rev_growth_3m": -1, "rev_mom": -1, "net_cf_ratio": -1,
          "tx_growth_3m": -1, "cost_growth_3m": 1, "cost_vs_sales_growth": 1, "debt_growth_3m": 1}
SW_NAMES = {"margin": "Kiwango cha faida mwezi huu", "margin_3m": "Kiwango cha faida, miezi 3", "margin_trend": "Mabadiliko ya kiwango cha faida",
            "rev_growth_3m": "Mwelekeo wa mauzo", "rev_mom": "Mabadiliko ya mauzo tangu mwezi uliopita", "net_cf_ratio": "Pesa iliyobaki",
            "tx_growth_3m": "Mwelekeo wa idadi ya mauzo", "cost_growth_3m": "Mwelekeo wa gharama",
            "cost_vs_sales_growth": "Gharama dhidi ya ukuaji wa mauzo", "debt_growth_3m": "Mabadiliko ya madeni"}


def _against_intuition(feature: str, v: float, up: bool) -> bool:
    """True when the model's push goes the 'unexpected' way for this value (e.g. falling sales lowering the
    risk, often a recovery pattern in the data). The usual sentence would then say something untrue."""
    if feature not in SIGNED or v is None or (isinstance(v, float) and np.isnan(v)) or abs(v) < 1e-9:
        return False
    bad_side = np.sign(v) == SIGNED[feature]
    return up != bad_side


def _neutral(feature: str, v: float, up: bool, sw: bool = False) -> tuple[str, str]:
    shown = f"{v:+.2f} months of sales" if feature == "debt_growth_3m" else f"{v * 100:+.0f}%"
    if sw:
        return (f"{SW_NAMES.get(feature, feature)}: {shown}. Katika biashara kama yako, hii {'iliongeza' if up else 'ilipunguza'} uwezekano.", "")
    return (f"{friendly(feature)}: {shown}. In businesses like yours this {'raised' if up else 'lowered'} the chance.", "")


def explain(feature: str, v: float, up: bool) -> tuple[str, str]:
    """(what we see, what you can do) for a feature that pushes risk up (up=True) or down."""
    if _against_intuition(feature, v, up):
        return _neutral(feature, v, up)
    nan = v is None or (isinstance(v, float) and np.isnan(v))
    tip_cost = "List your three biggest costs. Ask suppliers for a better price, or drop items that sell slowly."
    if feature in ("month_sin", "month_cos"):
        return (("The coming months are usually slower for businesses like yours.",
                 "Plan for the slow season: keep cash aside and buy less stock ahead of it.") if up else
                ("The coming months are usually good for businesses like yours.", ""))
    if feature.startswith("sector_"):
        return ((f"{SECTORS.get(feature[7:], 'This type of business').split(' /')[0]} businesses make losses more often in our data.",
                 "Watch your margin closely each month.") if up else ("Your type of business is usually steady.", ""))
    if nan:
        return (f"{friendly(feature)} is not recorded.", "Add the optional figures for a more reliable check.") if up else ("", "")
    texts = {
        "margin": (f"This month was a loss: costs were higher than sales." if v < 0 else
                   f"This month you kept only {_sh(v)} of every 100 of sales as profit.",
                   "Check which costs grew and which items sell at a thin margin.",
                   f"You kept {_sh(v)} of every 100 of sales as profit this month."),
        "margin_3m": (f"Over the last 3 months you lost on average {_sh(-v)} on every 100 of sales." if v < 0 else
                      f"Over the last 3 months you kept on average only {_sh(v)} of every 100 of sales.",
                      "Raise prices on items where costs went up, or cut costs that don't bring in sales.",
                      f"Over the last 3 months you kept {_sh(v)} of every 100 of sales as profit."),
        "margin_trend": (f"Your profit margin fell by {abs(v) * 100:.0f} points compared with 3 months ago." if v < 0 else
                         "Your profit margin has not improved over the last 3 months.",
                         "Compare this month's costs line by line with 3 months ago to find what changed.",
                         f"Your profit margin improved by {abs(v) * 100:.0f} points over 3 months."),
        "losses_last3": (f"{int(v)} of your last 3 months {'was a loss' if int(v) == 1 else 'were losses'}." if v >= 1 else
                         "Your recent months were close to breaking even.",
                         "Cut spending that can wait until sales recover.",
                         "None of your last 3 months were losses."),
        "rev_growth_3m": (f"Sales over the last 3 months were {_pct(v)} lower than the 3 months before." if v < 0 else
                          f"Sales grew only {_pct(v)} over the last 3 months.",
                          "Follow up regular customers you haven't seen, and check if a competitor opened nearby.",
                          f"Sales over the last 3 months grew {_pct(v)}."),
        "cost_growth_3m": (f"Your costs over the last 3 months rose {_pct(v)} compared with the 3 before." if v > 0 else
                           "Your costs stayed high while sales changed.", tip_cost,
                           "Your costs are under control."),
        "cost_vs_sales_growth": (f"Costs grew {abs(v) * 100:.0f} points faster than sales over the last 3 months.",
                                 tip_cost, "Your sales are growing faster than your costs."),
        "rev_mom": (f"Sales fell {_pct(v)} from last month." if v < 0 else
                    f"Sales jumped {_pct(v)} from last month; a sudden jump often falls back.",
                    "Check whether this month was unusual or the start of a trend.",
                    f"Sales went up {_pct(v)} from last month."),
        "cogs_ratio": (f"Stock you sold cost you {_sh(v)} of every 100 of sales.",
                       "Compare supplier prices, buy in bulk with other traders, or adjust your selling prices.",
                       "Your cost of goods is in a normal range for your business."),
        "opex_ratio": (f"Running costs (rent, wages, power) take {_sh(v)} of every 100 of sales.",
                       "Review rent, wages and power: which can be reduced without hurting sales?",
                       "Your running costs are low compared with your sales."),
        "net_cf_ratio": ("Over the last 3 months more cash went out than came in." if v < 0 else
                         f"Cash left over is only {_sh(v)} of every 100 of sales.",
                         "Follow up money customers owe you, and hold off purchases that can wait.",
                         "You have been keeping cash left over each month."),
        "neg_cf_months_3": (f"{int(v)} of the last 3 months had more cash going out than coming in.",
                            "Keep a weekly cash book so you see shortfalls early.",
                            "More cash came in than went out in recent months."),
        "mpesa_share": (f"M-Pesa brings in {_pct(v)} of the money you receive.",
                        "Keep business and personal M-Pesa separate so you see the true picture.",
                        f"M-Pesa brings in {_pct(v)} of your money, which keeps records clear."),
        "tx_growth_3m": (f"Your number of sales fell {_pct(v)} over the last 3 months." if v < 0 else
                         "Your number of sales is not growing.",
                         "Find out why customers come less often: prices, stock gaps or competition.",
                         f"Your number of sales grew {_pct(v)} over the last 3 months."),
        "debt_to_rev": (f"Money you owe equals {v:.1f} months of sales.",
                        "Plan repayments before taking more credit, and avoid buying slow stock on credit.",
                        "Money you owe is low compared with your sales."),
        "debt_growth_3m": ("Money you owe has grown over the last 3 months." if v > 0 else "Your debt is not going down.",
                           "Talk to your lender or supplier early about a repayment plan you can manage.",
                           "You have been paying down money you owe."),
        "stock_to_rev": (f"Stock on hand equals {v:.1f} months of sales." if v >= 1 else
                         f"Stock on hand is {_pct(v)} of a month's sales.",
                         "Sell slow-moving stock with a discount and buy smaller amounts more often.",
                         "Your stock level matches your sales."),
        "age_months": ("Your records cover only a short time, so the check is less certain.",
                       "Add more past months: 12 or more gives the most reliable check.",
                       "You have a long record, which makes the check more reliable."),
    }
    if feature not in texts:
        return (friendly(feature), "") if up else (friendly(feature), "")
    bad, tip, good = texts[feature]
    return (bad, tip) if up else (good, "")


def reasons_from(sv: np.ndarray, vals: pd.Series, features: list[str] | None = None) -> tuple[list, list]:
    """SHAP values for one business-month -> (top 3 reasons pushing the risk up, up to 3 things keeping it down),
    each as plain sentences with a tip. Shared by the 3-month check and the 1-12 month outlook."""
    features = features or F.FEATURES
    order = np.argsort(-sv)
    reasons, protective, seen = [], [], set()
    for i in order:
        f, s, v = features[i], float(sv[i]), float(vals.iloc[i]) if pd.notna(vals.iloc[i]) else np.nan
        if s <= 0 or len(reasons) == 3:
            break
        if f == "horizon" or (f.startswith("sector_") and v == 0):
            continue
        key = "month" if f.startswith("month_") else f
        if key in seen:
            continue
        seen.add(key)
        text, tip = explain(f, v, True)
        reasons.append({"feature": f, "name": friendly(f), "text": text, "tip": tip, "impact": round(s, 4)})
    for i in order[::-1]:
        f, s, v = features[i], float(sv[i]), float(vals.iloc[i]) if pd.notna(vals.iloc[i]) else np.nan
        if s >= 0 or len(protective) == 3:
            break
        if f == "horizon" or (f.startswith("sector_") and v == 0):
            continue
        key = "month" if f.startswith("month_") else f
        if key in seen:
            continue
        seen.add(key)
        text, _ = explain(f, v, False)
        if text:
            protective.append({"feature": f, "name": friendly(f), "text": text, "impact": round(s, 4)})
    return reasons, protective


def main_probability(rows: list[dict]) -> float | None:
    """Just the main model's calibrated 3-month % for the latest month (no explanation)."""
    bundle, _ = load()
    if bundle is None or len(rows) < 3:
        return None
    X = F.build(F.records_frame(rows))
    return float(calibrate(bundle["model"].predict_proba(X.iloc[[-1]][F.FEATURES])[:, 1], bundle.get("scaler"))[0])


def predict_rows(rows: list[dict]) -> dict | None:
    """rows = one business's months (as from features.load_rows). None if no model or too few months."""
    bundle, meta = load()
    if bundle is None or len(rows) < 3:
        return None
    X = F.build(F.records_frame(rows))
    last = X.iloc[[-1]]
    model = bundle["model"]
    p = float(calibrate(model.predict_proba(last[F.FEATURES])[:, 1], bundle.get("scaler"))[0])
    bg = pd.DataFrame(meta.get("background") or {}) if meta else pd.DataFrame()
    sv = shap_values(model, last[F.FEATURES], background=bg if len(bg) else None)[0]
    reasons, protective = reasons_from(sv, last[F.FEATURES].iloc[0])
    return {"source": "model", "probability": round(p, 4), "band": band(p),
            "as_of": last["month"].iloc[0].strftime("%Y-%m"), "model_version": bundle["version"],
            "model_name": (meta or {}).get("best_name", bundle.get("kind", "")),
            "reasons": reasons, "protective": protective}


# ---------- Kiswahili ----------
def _shs(x: float) -> str:
    return f"shilingi {round(x * 100)}"


def explain_sw(feature: str, v: float, up: bool) -> tuple[str, str]:
    """Kiswahili version of explain(): (tunachoona, unachoweza kufanya)."""
    if _against_intuition(feature, v, up):
        return _neutral(feature, v, up, sw=True)
    nan = v is None or (isinstance(v, float) and np.isnan(v))
    tip_cost = "Orodhesha gharama zako tatu kubwa zaidi. Omba bei nafuu kwa wasambazaji, au acha bidhaa zinazouzwa polepole."
    if feature in ("month_sin", "month_cos"):
        return (("Miezi ijayo kwa kawaida huwa ya mauzo machache kwa biashara kama yako.",
                 "Jiandae kwa msimu wa mauzo machache: weka akiba na nunua bidhaa kidogo kabla yake.") if up else
                ("Miezi ijayo kwa kawaida huwa mizuri kwa biashara kama yako.", ""))
    if feature.startswith("sector_"):
        return (("Biashara za aina yako hupata hasara mara nyingi zaidi katika data yetu.",
                 "Fuatilia faida yako kwa karibu kila mwezi.") if up else ("Aina yako ya biashara kwa kawaida ni thabiti.", ""))
    if nan:
        return ("Takwimu hii haijarekodiwa.", "Ongeza takwimu za hiari ili ukaguzi uwe wa kuaminika zaidi.") if up else ("", "")
    t = {
        "margin": ("Mwezi huu ulikuwa wa hasara: gharama zilizidi mauzo." if v < 0 else
                   f"Mwezi huu ulibaki na faida ya {_shs(v)} tu kwa kila 100 za mauzo.",
                   "Angalia gharama zipi zimepanda na bidhaa zipi zinauzwa kwa faida ndogo.",
                   f"Ulibaki na faida ya {_shs(v)} kwa kila 100 za mauzo mwezi huu."),
        "margin_3m": (f"Katika miezi 3 iliyopita ulipata hasara ya wastani ya {_shs(-v)} kwa kila 100 za mauzo." if v < 0 else
                      f"Katika miezi 3 iliyopita ulibaki na wastani wa {_shs(v)} tu kwa kila 100 za mauzo.",
                      "Pandisha bei za bidhaa ambazo gharama zake zimepanda, au punguza gharama zisizoleta mauzo.",
                      f"Katika miezi 3 iliyopita ulibaki na faida ya {_shs(v)} kwa kila 100 za mauzo."),
        "margin_trend": (f"Kiwango chako cha faida kimeshuka kwa pointi {abs(v) * 100:.0f} ukilinganisha na miezi 3 iliyopita." if v < 0 else
                         "Kiwango chako cha faida hakijaimarika katika miezi 3 iliyopita.",
                         "Linganisha gharama za mwezi huu, moja moja, na za miezi 3 iliyopita ili uone kilichobadilika.",
                         f"Kiwango chako cha faida kimeongezeka kwa pointi {abs(v) * 100:.0f} katika miezi 3."),
        "losses_last3": (f"Miezi {int(v)} kati ya 3 iliyopita ilikuwa ya hasara." if v >= 1 else
                         "Miezi yako ya karibuni ilikaribia kukosa faida.",
                         "Punguza matumizi yanayoweza kusubiri hadi mauzo yarudi.",
                         "Hakuna mwezi wa hasara katika miezi 3 iliyopita."),
        "rev_growth_3m": (f"Mauzo ya miezi 3 iliyopita yalikuwa chini kwa {_pct(v)} kuliko miezi 3 kabla yake." if v < 0 else
                          f"Mauzo yameongezeka kwa {_pct(v)} tu katika miezi 3 iliyopita.",
                          "Wafuatilie wateja wa kawaida usiowaona siku hizi, na uangalie kama kuna mshindani mpya karibu.",
                          f"Mauzo ya miezi 3 iliyopita yameongezeka kwa {_pct(v)}."),
        "cost_growth_3m": (f"Gharama zako za miezi 3 iliyopita zimepanda kwa {_pct(v)} ukilinganisha na miezi 3 kabla yake." if v > 0 else
                           "Gharama zako zimebaki juu wakati mauzo yamebadilika.", tip_cost, "Gharama zako ziko chini ya udhibiti."),
        "cost_vs_sales_growth": (f"Gharama zimekua kwa pointi {abs(v) * 100:.0f} zaidi ya mauzo katika miezi 3 iliyopita.",
                                 tip_cost, "Mauzo yako yanakua haraka kuliko gharama."),
        "rev_mom": (f"Mauzo yameshuka kwa {_pct(v)} kutoka mwezi uliopita." if v < 0 else
                    f"Mauzo yameruka kwa {_pct(v)} kutoka mwezi uliopita; ongezeko la ghafla mara nyingi hurudi chini.",
                    "Angalia kama mwezi huu ulikuwa wa kipekee au ni mwanzo wa mwelekeo mpya.",
                    f"Mauzo yameongezeka kwa {_pct(v)} kutoka mwezi uliopita."),
        "cogs_ratio": (f"Bidhaa ulizouza zilikugharimu {_shs(v)} kwa kila 100 za mauzo.",
                       "Linganisha bei za wasambazaji, nunua kwa jumla pamoja na wafanyabiashara wengine, au rekebisha bei zako.",
                       "Gharama ya bidhaa zako iko katika kiwango cha kawaida kwa biashara yako."),
        "opex_ratio": (f"Gharama za uendeshaji (kodi, mishahara, umeme) zinachukua {_shs(v)} kwa kila 100 za mauzo.",
                       "Kagua kodi, mishahara na umeme: kipi kinaweza kupunguzwa bila kuathiri mauzo?",
                       "Gharama zako za uendeshaji ziko chini ukilinganisha na mauzo."),
        "net_cf_ratio": ("Katika miezi 3 iliyopita pesa zilizotoka zilizidi zilizoingia." if v < 0 else
                         f"Pesa inayobaki ni {_shs(v)} tu kwa kila 100 za mauzo.",
                         "Fuatilia pesa unazodai wateja, na usitishe manunuzi yanayoweza kusubiri.",
                         "Umekuwa ukibaki na pesa kila mwezi."),
        "neg_cf_months_3": (f"Miezi {int(v)} kati ya 3 iliyopita pesa zilizotoka zilizidi zilizoingia.",
                            "Weka daftari la pesa la kila wiki ili uone upungufu mapema.",
                            "Katika miezi ya karibuni pesa zilizoingia zilizidi zilizotoka."),
        "mpesa_share": (f"M-Pesa inaleta {_pct(v)} ya pesa unazopokea.",
                        "Tenganisha M-Pesa ya biashara na ya binafsi ili uone hali halisi.",
                        f"M-Pesa inaleta {_pct(v)} ya pesa zako, na hivyo kumbukumbu ziko wazi."),
        "tx_growth_3m": (f"Idadi ya mauzo yako imeshuka kwa {_pct(v)} katika miezi 3 iliyopita." if v < 0 else
                         "Idadi ya mauzo yako haiongezeki.",
                         "Tafuta kwa nini wateja wanakuja mara chache: bei, bidhaa kukosekana au ushindani.",
                         f"Idadi ya mauzo yako imeongezeka kwa {_pct(v)} katika miezi 3 iliyopita."),
        "debt_to_rev": (f"Madeni yako ni sawa na mauzo ya miezi {v:.1f}.",
                        "Panga marejesho kabla ya kuchukua mkopo zaidi, na usinunue bidhaa zinazouzwa polepole kwa mkopo.",
                        "Madeni yako ni madogo ukilinganisha na mauzo."),
        "debt_growth_3m": ("Madeni yako yameongezeka katika miezi 3 iliyopita." if v > 0 else "Madeni yako hayapungui.",
                           "Ongea mapema na mkopeshaji au msambazaji wako kuhusu mpango wa marejesho unaoweza kumudu.",
                           "Umekuwa ukipunguza madeni yako."),
        "stock_to_rev": (f"Bidhaa ulizonazo ni sawa na mauzo ya miezi {v:.1f}." if v >= 1 else
                         f"Bidhaa ulizonazo ni {_pct(v)} ya mauzo ya mwezi mmoja.",
                         "Uza bidhaa zinazouzwa polepole kwa punguzo, na nunua kiasi kidogo mara nyingi zaidi.",
                         "Kiwango cha bidhaa zako kinalingana na mauzo."),
        "age_months": ("Kumbukumbu zako ni za muda mfupi, kwa hivyo ukaguzi hauna uhakika sana.",
                       "Ongeza miezi iliyopita zaidi: miezi 12 au zaidi hutoa ukaguzi wa kuaminika zaidi.",
                       "Una kumbukumbu za muda mrefu, jambo linalofanya ukaguzi uaminike zaidi."),
    }
    if feature not in t:
        return ("", "")
    bad, tip, good = t[feature]
    return (bad, tip) if up else (good, "")


def translate(result: dict, rows: list[dict]) -> dict:
    """Same prediction with the reasons in Kiswahili (values recomputed from the same features)."""
    if not result:
        return result
    X = F.build(F.records_frame(rows))
    vals = X[F.FEATURES].iloc[-1]
    out = dict(result)
    for key, up in (("reasons", True), ("protective", False)):
        items = []
        for x in result.get(key, []):
            v = float(vals[x["feature"]]) if pd.notna(vals[x["feature"]]) else np.nan
            text, tip = explain_sw(x["feature"], v, up)
            items.append({**x, "text": text or x["text"], "tip": tip if up else x.get("tip", "")})
        out[key] = items
    return out
