"""Biashara Check assistant: a built-in helper that answers owners' questions in English or Kiswahili.

Free and offline by design: no outside AI service is called and no figures leave the app. It works out
what the owner is asking (keyword and phrase matching that tolerates spelling mistakes), picks out a figure,
a month or a percentage, and answers from the owner's own records, their risk and distress checks, the
formulas in app/finance.py, and fixed help texts.

    answer(db, user, business, message, context) -> {"reply", "intent", "suggestions", "links", "lang", "context"}

Messages are not stored. Only the topic of each question (for example "risk" or "whatif") is written to
the activity log, so the study can see which help owners need.
"""
import difflib
import re
from datetime import date

from sqlalchemy.orm import Session

from . import finance, pro
from .models import Business, User

# ---------------------------------------------------------------- language
SW_MARKERS = {"nini", "gani", "yangu", "wangu", "zangu", "je", "ngapi", "nina", "hasara", "faida", "mauzo", "habari",
              "asante", "jinsi", "kwa", "mwezi", "biashara", "nifanye", "vipi", "naweza", "kiasi", "gharama", "pesa",
              "hatari", "deni", "madeni", "ni", "na", "ya", "mambo", "sasa", "niaje", "jambo", "shida", "lini", "kwanini",
              "kwa nini", "ushauri", "nisaidie", "nipe", "ilikuwa", "nilipata", "niliuza", "ongeza", "punguza",
              "katika", "miezi", "ijayo", "hadi", "mbele", "itakuwa", "nitapata"}


def detect_lang(text: str, default: str) -> str:
    words = set(re.findall(r"[a-z]+", text.lower()))
    hits = len(words & SW_MARKERS)
    if hits >= 2 or (hits == 1 and len(words) <= 2 and words & {"habari", "mambo", "asante", "niaje", "jambo", "sasa"}):
        return "sw"
    en = len(words & {"what", "how", "my", "is", "the", "why", "did", "much", "can", "i", "of", "in", "was"})
    return "en" if en >= 2 else default


# ---------------------------------------------------------------- helpers
def kes(x: float | None) -> str:
    return finance.kes(x)


def pct(x: float | None, dp: int = 0) -> str:
    return finance.pct(x, dp)


MONTHS_EN = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
             "november", "december"]
MONTHS_SW = ["januari", "februari", "machi", "aprili", "mei", "juni", "julai", "agosti", "septemba", "oktoba",
             "novemba", "desemba"]
SW_MON = ["Jan", "Feb", "Mac", "Apr", "Mei", "Jun", "Jul", "Ago", "Sep", "Okt", "Nov", "Des"]


def month_label(ym: str, lang: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{SW_MON[m - 1]} {y}" if lang == "sw" else date(y, m, 1).strftime("%b %Y")


def norm(text: str) -> str:
    t = text.lower().replace("m-pesa", "mpesa").replace("m pesa", "mpesa").replace("break-even", "break even")
    t = t.replace("’", "'")
    return re.sub(r"[^a-z0-9%.' -]+", " ", t)


def _tokens(t: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", t)


def has(t: str, toks: list[str], phrase: str) -> bool:
    """Phrase in the message; single words also match with a small spelling mistake."""
    if " " in phrase or len(phrase) < 5 or not phrase.isalpha():
        return re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", t) is not None
    if phrase in toks:
        return True
    return any(len(w) >= 5 and abs(len(w) - len(phrase)) <= 2 and difflib.SequenceMatcher(None, w, phrase).ratio() >= 0.8
               for w in toks if w not in STOP)


STOP = {"change", "changed", "chance", "charge", "where", "there", "these", "those", "which", "about", "would", "could",
        "should", "their", "after", "before", "month", "months"}


# ---------------------------------------------------------------- figures the owner can ask about
# key: (English label, Kiswahili label, words, unit). Longer, more specific phrases are listed first.
FIGURES = {
    "gross_margin": ("gross margin", "kiwango cha faida ghafi", ["gross margin"], "pct"),
    "gross_profit": ("gross profit", "faida ghafi", ["gross profit", "faida ghafi", "gross"], "kes"),
    "margin_of_safety": ("margin of safety", "kiwango cha usalama", ["margin of safety", "safety margin"], "pct"),
    "break_even_sales": ("break-even sales", "mauzo ya kurudisha gharama", ["break even", "breakeven", "kurudisha gharama"], "kes"),
    "net_margin": ("net margin", "kiwango cha faida", ["net margin", "profit margin", "kiwango cha faida", "margin"], "pct"),
    "cash_in": ("money received", "pesa zilizoingia", ["money received", "cash in", "cash received", "pesa zilizoingia", "nilipokea"], "kes"),
    "cash_out": ("money paid out", "pesa zilizotoka", ["paid out", "cash out", "money out", "pesa zilizotoka", "nililipa"], "kes"),
    "net_cash_flow": ("cash left over", "pesa iliyobaki", ["cash flow", "cash left", "net cash", "pesa iliyobaki", "mtiririko", "cash"], "kes"),
    "avg_sale": ("average sale", "wastani wa mauzo", ["average sale", "per customer", "basket"], "kes"),
    "transactions": ("number of sales", "idadi ya mauzo", ["number of sales", "how many sales", "transactions", "customers", "wateja", "idadi ya mauzo"], "count"),
    "cogs": ("cost of goods sold", "gharama ya bidhaa", ["cost of goods", "cogs", "stock bought", "purchases", "buying", "gharama ya bidhaa"], "kes"),
    "opex": ("running expenses", "gharama za uendeshaji", ["running costs", "running expenses", "expenses", "overheads", "rent", "wages", "salaries", "uendeshaji", "matumizi", "kodi", "mishahara"], "kes"),
    "total_costs": ("total costs", "gharama zote", ["total costs", "costs", "cost", "spend", "spent", "gharama"], "kes"),
    "mpesa": ("money received by M-Pesa", "pesa za M-Pesa", ["mpesa"], "kes"),
    "debt": ("money owed", "madeni", ["debt", "debts", "owe", "loan", "loans", "credit", "deni", "madeni", "mkopo"], "kes"),
    "stock": ("stock at month end", "bidhaa mwisho wa mwezi", ["stock", "inventory", "bidhaa zilizopo"], "kes"),
    "operating_profit": ("profit", "faida", ["operating profit", "net profit", "profit", "profits", "loss", "faida", "hasara", "earn", "earned", "make", "made"], "kes"),
    "sales": ("sales", "mauzo", ["sales", "revenue", "sold", "sell", "turnover", "income", "takings", "mauzo", "niliuza", "mapato"], "kes"),
}
SUMMABLE = {"sales", "cogs", "opex", "total_costs", "gross_profit", "operating_profit", "net_cash_flow", "cash_in",
            "cash_out", "mpesa", "transactions"}


def find_figure(t: str, toks: list[str]) -> str | None:
    for key, (_, _, words, _) in FIGURES.items():
        if any(has(t, toks, w) for w in words):
            return key
    return None


def value_of(key: str, m: dict) -> float | None:
    if key == "total_costs":
        return m["cogs"] + m["opex"]
    if key == "mpesa":
        return (m["mpesa_share"] or 0) * m["cash_in"]
    return m.get(key)


def show(key: str, v: float | None) -> str:
    unit = FIGURES[key][3]
    if v is None:
        return "-"
    return kes(v) if unit == "kes" else pct(v, 1) if unit == "pct" else f"{int(round(v)):,}"


# ---------------------------------------------------------------- months and periods
def find_month(t: str, toks: list[str], months: list[dict]) -> str | None:
    """'March', 'mar 2026', 'machi', '2026-03', '03/2026', 'last month', 'previous month'."""
    have = [m["month"] for m in months]
    if not have:
        return None
    m = re.search(r"\b(20\d\d)[-/](\d{1,2})\b", t) or re.search(r"\b(\d{1,2})[-/](20\d\d)\b", t)
    if m:
        a, b = m.groups()
        y, mo = (int(a), int(b)) if len(a) == 4 else (int(b), int(a))
        return f"{y}-{mo:02d}"
    if re.search(r"\b(previous|month before|before last|uliotangulia)\b", t):
        return have[-2] if len(have) > 1 else have[-1]
    if re.search(r"\b(last|this|latest|recent|current) month\b|\bmwezi (uliopita|huu|wa mwisho)\b", t):
        return have[-1]
    year = re.search(r"\b(20\d\d)\b", t)
    for i, (en, sw) in enumerate(zip(MONTHS_EN, MONTHS_SW)):
        names = {en, sw, en[:3]} | ({"sept"} if en == "september" else set())
        if names & set(toks):
            cands = [h for h in have if int(h[5:7]) == i + 1 and (not year or h[:4] == year.group(1))]
            return cands[-1] if cands else f"{year.group(1) if year else have[-1][:4]}-{i + 1:02d}"
    return None


def find_period(t: str) -> int | None:
    """Number of recent months for totals: 'last 3 months', 'quarter', 'this year', 'all months', 'so far'."""
    m = re.search(r"\b(last|past|previous|miezi)\s+(\d{1,2})\s*(months|mwezi|miezi)?\b", t) or re.search(r"\bmiezi\s+(\d{1,2})\b", t)
    if m:
        n = int(m.groups()[-2] if len(m.groups()) == 3 else m.group(1))
        return max(1, min(n, 120))
    if re.search(r"\b(quarter|robo)\b", t):
        return 3
    if re.search(r"\b(half year|six months)\b", t):
        return 6
    if re.search(r"\b(this year|past year|last year|12 months|year|mwaka)\b", t):
        return 12
    if re.search(r"\b(total|all|so far|altogether|ever|jumla|zote|tangu)\b", t):
        return 0
    return None


# ---------------------------------------------------------------- intents
INTENTS = {
    "whatif": ["what if", "if i", "suppose", "kama nikipunguza", "kama nikiongeza", "ikiwa", "nikipunguza", "nikiongeza"],
    "risk": ["risk", "hatari", "chance of a loss", "will i make a loss", "make a loss", "loss next", "risky", "danger",
             "reasons", "sababu", "band", "next 3 months", "next three months", "miezi 3 ijayo", "prediction"],
    "distress": ["distress", "dhiki", "shortfall", "run out of cash", "run out of money", "cash crunch", "financial trouble",
                 "upungufu wa pesa", "kuishiwa"],
    "warnings": ["warning", "warnings", "worry", "worried", "problem", "problems", "wrong", "issues", "tahadhari", "shida",
                 "matatizo", "watch out", "concern"],
    "advice": ["improve", "advice", "tips", "tip", "what should i do", "how can i", "how do i increase", "how do i reduce",
               "increase my", "reduce my", "cut my", "boost", "grow my", "ushauri", "nifanye nini", "kuongeza", "kupunguza",
               "better", "nisaidie", "help me", "save money", "lower my", "raise my"],
    "trend": ["trend", "growing", "compare", "comparison", "better than", "worse than", "going up", "going down",
              "improving", "getting worse", "change", "changed", "linganisha", "inakua", "mwelekeo", "progress"],
    "best_worst": ["best month", "worst month", "highest", "lowest", "biggest", "smallest", "best", "worst", "bora",
                   "mbaya zaidi", "top month"],
    "losses": ["loss months", "how many losses", "how many loss", "months of loss", "hasara ngapi", "miezi ya hasara"],
    "explain": ["what is", "what's", "what does", "meaning", "mean", "define", "definition", "explain", "maana", "ni nini",
                "nieleze"],
    "calc": ["how is", "how are", "calculated", "calculate", "formula", "worked out", "work out", "kokotoa",
             "inakokotolewa", "kanuni", "computed"],
    "accuracy": ["accurate", "accuracy", "trust", "reliable", "correct", "sahihi", "kuamini", "proof", "prove",
                 "how good", "how well", "evidence", "tested"],
    "model_kind": ["artificial intelligence", "machine learning", "ml", "ai", "model", "algorithm", "statistical",
                   "statistics", "rule based", "rules", "akili bandia"],
    "privacy": ["privacy", "private", "who can see", "who sees", "shared", "share my", "safe", "secure", "security",
                "my data", "lender", "lenders", "faragha", "usalama", "siri", "data protection"],
    "integrity": ["missing", "gap", "gaps", "mistake", "mistakes", "typo", "fingerprint", "integrity", "check my data",
                  "check my figures", "kukosa", "makosa"],
    "track": ["track record", "past checks", "were you right", "was it right", "history", "rekodi"],
    "howto": ["how do i", "how to", "where do i", "where can i", "can i", "jinsi ya", "nawezaje", "naweza"],
    "help": ["help", "what can you do", "who are you", "msaada", "unaweza", "what do you do", "menu"],
    "greeting": ["hi", "hello", "hey", "habari", "mambo", "jambo", "niaje", "sasa", "good morning", "good afternoon",
                 "good evening", "hujambo", "salama"],
    "thanks": ["thanks", "thank you", "thank", "asante", "shukran", "great", "ok thanks", "sawa"],
}

HOWTO = {
    "add_month": ["add a month", "add month", "enter", "new month", "record my", "type in", "ongeza mwezi", "add my figures", "input"],
    "edit": ["edit", "fix", "correct a month", "change a month", "wrong figure", "delete a month", "remove a month", "hariri", "rekebisha"],
    "upload": ["upload", "excel", "csv", "spreadsheet", "file", "import", "pakia"],
    "mpesa": ["statement", "mpesa"],
    "reports": ["report", "reports", "pdf", "print", "email me", "ripoti"],
    "pro": ["pro", "premium", "subscribe", "subscription", "pay", "price", "cost of pro", "upgrade", "lipa", "bei"],
    "username": ["username", "user name", "jina la mtumiaji", "login name"],
    "password": ["password", "forgot", "reset", "recovery", "nenosiri", "locked"],
    "download": ["download my data", "download my figures", "download my records", "export", "copy of my data", "copy of my figures", "pakua"],
    "delete": ["delete my account", "delete account", "close my account", "close account", "futa akaunti", "remove my account"],
    "language": ["kiswahili", "swahili", "english", "language", "lugha"],
    "install": ["install", "home screen", "app on my phone", "download the app", "download the application", "download app",
                "get the app", "phone app", "mobile app", "play store", "app store", "apk", "on my phone", "on my device", "sakinisha", "pakua programu"],
    "reminders": ["reminder", "reminders", "notification", "notifications", "alert", "alerts", "sms", "emails", "ukumbusho"],
    "contact": ["change my email", "change email", "phone number", "change phone", "contact details", "barua pepe"],
}

GLOSSARY = {
    "gross profit": ("Gross profit is sales minus the cost of the goods you sold. It's what is left to pay rent, wages and other running costs.",
                     "Faida ghafi ni mauzo toa gharama ya bidhaa ulizouza. Ndiyo inayobaki kulipa kodi, mishahara na gharama nyingine."),
    "gross margin": ("Gross margin is gross profit divided by sales. 30% means you keep 30 shillings of every 100 after paying for the stock.",
                     "Kiwango cha faida ghafi ni faida ghafi gawanya kwa mauzo. 30% ina maana unabaki na shilingi 30 kwa kila 100 baada ya kulipia bidhaa."),
    "operating profit": ("Operating profit (your profit or loss) is gross profit minus running expenses: sales − cost of goods − running expenses. Below zero is a loss month.",
                         "Faida ya uendeshaji ni faida ghafi toa gharama za uendeshaji. Ikiwa chini ya sifuri, ni mwezi wa hasara."),
    "net margin": ("Net margin is profit divided by sales: how many shillings of every 100 of sales you keep as profit.",
                   "Kiwango cha faida ni faida gawanya kwa mauzo: shilingi ngapi za kila 100 unazobaki nazo kama faida."),
    "cash flow": ("Net cash flow (cash left over) is money received minus money paid out in the month, whatever it was for. You can make a profit and still run short of cash if money is tied up in stock or credit.",
                  "Mtiririko wa pesa ni pesa zilizoingia toa pesa zilizotoka. Unaweza kupata faida lakini ukakosa pesa ikiwa pesa imekwama kwenye bidhaa au mikopo."),
    "break even": ("Break-even sales are the sales you need to cover your running costs: running expenses ÷ gross margin. Sell less and the month is a loss.",
                   "Mauzo ya kurudisha gharama ni mauzo unayohitaji kulipia gharama za uendeshaji: gharama za uendeshaji ÷ kiwango cha faida ghafi."),
    "margin of safety": ("Margin of safety is how far sales could fall before the month becomes a loss: (sales − break-even sales) ÷ sales.",
                         "Kiwango cha usalama ni kiasi mauzo yanavyoweza kushuka kabla mwezi haujawa wa hasara."),
    "cost of goods": ("Cost of goods sold is what you paid for the stock you actually sold this month, not all the stock you bought.",
                      "Gharama ya bidhaa zilizouzwa ni bei uliyolipa kwa bidhaa ulizouza mwezi huu, si bidhaa zote ulizonunua."),
    "running expenses": ("Running expenses are the costs of keeping the business open: rent, wages, power, water, transport, airtime and similar.",
                         "Gharama za uendeshaji ni kodi, mishahara, umeme, maji, usafiri na kadhalika."),
    "risk": ("The risk % is the chance that at least one of your next 3 months is a loss month, worked out by a machine-learning model from your figures. Low is below 35%, Moderate from 35%, High from 60%.",
             "Asilimia ya hatari ni uwezekano kwamba angalau mwezi mmoja kati ya 3 ijayo utakuwa wa hasara. Chini ni chini ya 35%, Wastani kuanzia 35%, Juu kuanzia 60%."),
    "distress": ("Financial distress here means that over the next 3 months more money goes out than comes in, or your debt rises by more than half a month's sales. A logistic regression works out the chance.",
                 "Dhiki ya kifedha hapa ni kwamba katika miezi 3 ijayo pesa zinazotoka zinazidi zinazoingia, au madeni yanaongezeka zaidi ya nusu ya mauzo ya mwezi."),
    "shap": ("SHAP is a method that splits a prediction into how much each of your figures pushed the risk up or down. The biggest pushes become your 'main reasons'.",
             "SHAP ni mbinu inayogawa utabiri kuonyesha kila takwimu ilivyoongeza au kupunguza hatari."),
    "logistic regression": ("Logistic regression is a statistical model: it adds up your figures, each multiplied by a weight, and turns the total into a chance with 1 / (1 + e^-total). It powers the financial distress check, and you can see the whole sum on the dashboard.",
                            "Logistic regression ni modeli ya kitakwimu: inajumlisha takwimu zako, kila moja ikizidishwa kwa uzito, na kugeuza jumla kuwa uwezekano."),
    "machine learning": ("Machine learning means the model learned patterns from thousands of past business-months whose outcome is known, instead of following rules someone wrote.",
                         "Machine learning ina maana modeli imejifunza mifumo kutoka maelfu ya miezi ya biashara iliyopita."),
    "calibration": ("Calibration means the % comes true about as often as it says: of all months given about 30%, about 30 in 100 were followed by a loss.",
                    "Calibration ina maana asilimia inatimia mara nyingi kama inavyosema."),
    "recall": ("Recall is the share of real loss periods the model warned about.", "Recall ni sehemu ya vipindi vya hasara ambavyo modeli ilitahadharisha."),
    "precision": ("Precision is the share of the model's warnings that turned out right.", "Precision ni sehemu ya tahadhari za modeli zilizotimia."),
    "pr-auc": ("PR-AUC measures how well the model ranks risky months above safe ones, focusing on the rarer loss months. 1 is perfect.",
               "PR-AUC hupima jinsi modeli inavyopanga miezi ya hatari juu ya ile salama. 1 ni bora kabisa."),
    "roc-auc": ("ROC-AUC measures how well the model separates months followed by a loss from the rest. 0.5 is guessing, 1 is perfect.",
                "ROC-AUC hupima jinsi modeli inavyotenganisha miezi ya hasara na mingine. 0.5 ni kubahatisha, 1 ni bora kabisa."),
    "brier": ("The Brier score is the average squared gap between the predicted chance and what happened (0 or 1). Lower is better; 0 is perfect.",
              "Brier ni wastani wa tofauti kati ya uwezekano uliotabiriwa na kilichotokea. Chini ni bora."),
    "fingerprint": ("The fingerprint is a SHA-256 code made from all your figures. Change any figure by even one shilling and it changes completely, so a printed report can be matched to your records.",
                    "Alama ya kidijitali ni msimbo wa SHA-256 unaotokana na takwimu zako zote. Ukibadilisha takwimu yoyote, inabadilika kabisa."),
    "odds ratio": ("An odds ratio above 1 means that figure raises the chance; below 1 lowers it. It's e to the power of the weight.",
                   "Odds ratio juu ya 1 ina maana takwimu hiyo inaongeza uwezekano; chini ya 1 inapunguza."),
    "p-value": ("A p-value under 0.05 means an effect is very unlikely to be just chance.", "p-value chini ya 0.05 ina maana athari hiyo haiwezekani kuwa bahati tu."),
    "synthetic": ("Synthetic data are simulated businesses made to follow realistic Kenyan SME patterns. They let the model be built and tested before enough real months are collected.",
                  "Data bandia ni biashara zilizoigwa kufuata mifumo halisi ya biashara ndogo za Kenya."),
    "overtrading": ("Overtrading is growing faster than your cash allows: you pay for more stock before the money from the extra sales comes in, so cash runs short even while sales grow.",
                    "Overtrading ni kukua haraka kuliko pesa zinavyoruhusu: unanunua bidhaa zaidi kabla pesa za mauzo hazijaingia."),
    "stock": ("Stock (inventory) is the goods you have on hand at month end, valued at what you paid. Months of stock = stock ÷ cost of goods sold.",
              "Bidhaa zilizopo ni bidhaa ulizonazo mwisho wa mwezi, kwa bei uliyonunua."),
    "money owed": ("Money owed is everything you still have to pay back: bank or SACCO loans, supplier credit, chama loans, mobile loans.",
                   "Madeni ni kila unachodaiwa: mikopo ya benki au SACCO, mikopo ya wasambazaji, chama, mikopo ya simu."),
}
GLOSS_ALIASES = {"gross margin": ["gross margin"], "gross profit": ["gross profit", "faida ghafi"],
                 "operating profit": ["operating profit", "net profit", "profit or loss"], "net margin": ["net margin", "profit margin", "margin"],
                 "cash flow": ["cash flow", "cash left", "mtiririko"], "break even": ["break even", "breakeven"],
                 "margin of safety": ["margin of safety"], "cost of goods": ["cost of goods", "cogs"],
                 "running expenses": ["running expenses", "running costs", "overheads", "opex"], "risk": ["risk %", "risk percentage", "risk band", "risk", "hatari"],
                 "distress": ["distress", "dhiki"], "shap": ["shap"], "logistic regression": ["logistic regression", "logistic"],
                 "machine learning": ["machine learning"], "calibration": ["calibration", "calibrated"], "recall": ["recall"],
                 "precision": ["precision"], "pr-auc": ["pr auc", "pr-auc"], "roc-auc": ["roc auc", "roc-auc", "auc"], "brier": ["brier"],
                 "fingerprint": ["fingerprint", "sha"], "odds ratio": ["odds ratio", "odds"], "p-value": ["p value", "p-value"],
                 "synthetic": ["synthetic", "simulated"], "overtrading": ["overtrading"], "stock": ["stock", "inventory"],
                 "money owed": ["money owed", "debt"]}


def find_term(t: str, toks: list[str]) -> str | None:
    for term, words in GLOSS_ALIASES.items():
        if any(has(t, toks, w) for w in words):
            return term
    return None


def detect(t: str, toks: list[str]) -> tuple[str, dict]:
    scores = {}
    for name, words in INTENTS.items():
        s = 0
        for w in words:
            if has(t, toks, w):
                s += 2 if " " in w else 1
        if s:
            scores[name] = s
    return max(scores, key=lambda k: scores[k]) if scores else "", scores


# ---------------------------------------------------------------- the answer
class Ctx:
    def __init__(self, db: Session, user: User, business: Business | None, lang: str):
        self.db, self.user, self.b, self.lang = db, user, business, lang
        self.records = list(business.records) if business else []
        self._summary = None

    @property
    def summary(self) -> dict | None:
        if self._summary is None and self.records:
            self._summary = finance.summary(self.records)
        return self._summary

    def T(self, en: str, sw: str) -> str:
        return sw if self.lang == "sw" else en


def _out(ctx: Ctx, intent: str, reply: str, suggestions=None, links=None, context=None) -> dict:
    return {"reply": reply.strip(), "intent": intent, "lang": ctx.lang,
            "suggestions": suggestions if suggestions is not None else default_suggestions(ctx),
            "links": links or [], "context": context or {}}


def default_suggestions(ctx: Ctx) -> list[str]:
    if not ctx.records:
        return [ctx.T("How do I add a month?", "Naongezaje mwezi?"), ctx.T("Can I upload Excel?", "Naweza kupakia Excel?"),
                ctx.T("Who can see my data?", "Nani anaona data yangu?")]
    return [ctx.T("Why is my risk at this level?", "Kwa nini hatari yangu iko hivi?"),
            ctx.T("What was my gross profit last month?", "Faida ghafi yangu mwezi uliopita?"),
            ctx.T("What if I cut running costs by 10%?", "Kama nikipunguza gharama za uendeshaji kwa 10%?"),
            ctx.T("How can I improve my profit?", "Nifanye nini kuongeza faida?")]


def no_records(ctx: Ctx, intent: str) -> dict:
    return _out(ctx, intent, ctx.T(
        "You haven't saved any months yet, so I have no figures to look at. Add at least 3 months (Add a month, or Upload CSV on the dashboard) and ask me again.",
        "Bado hujahifadhi mwezi wowote, kwa hivyo sina takwimu za kuangalia. Ongeza angalau miezi 3 kisha uniulize tena."))


def answer(db: Session, user: User, business: Business | None, message: str, context: dict | None = None) -> dict:
    context = context or {}
    lang = detect_lang(message, user.language or "en")
    ctx = Ctx(db, user, business, lang)
    t = norm(message)
    toks = _tokens(t)
    if not toks:
        return help_answer(ctx)

    intent, scores = detect(t, toks)
    months = ctx.summary["months"] if ctx.summary else []
    fig = find_figure(t, toks)
    month = find_month(t, toks, months)
    period = find_period(t.replace("total costs", "costs").replace("total sales", "sales"))
    pcts = re.findall(r"(\d+(?:\.\d+)?)\s*(?:%|percent|per cent|asilimia)", t) or \
        (re.findall(r"\bby\s+(\d+(?:\.\d+)?)\b", t) if re.search(r"\b(cut|reduce|raise|increase|lower|punguza|ongeza)\b", t) else [])

    # a short follow-up such as "and in May?" or "what about sales?" carries on from the last answer
    if not intent and (month or period is not None) and not fig and context.get("figure"):
        fig = context["figure"]
    followup = bool(re.match(r"\s*(and|what about|how about|na|je|then)\b", t))
    if not intent and fig and not month and period is None and context.get("month") and followup:
        month = context["month"]

    # Biashara Pro: when it ends, cancelling or turning on automatic renewal
    if any(has(t, toks, w) for w in SUB_WORDS) and ctx.b:
        return subscription(ctx)
    # "how do I upload...", "how do I change my username": app questions go straight to the help texts
    if "howto" in scores and not pcts:
        for topic, words in HOWTO.items():
            if any(has(t, toks, w) for w in words):
                return howto(ctx, topic)
    if intent == "howto":  # "can I ..." with no app topic: use the next best reading
        rest = {k: v for k, v in scores.items() if k != "howto"}
        intent = max(rest, key=lambda k: rest[k]) if rest else ""
    # looking further ahead: "risk in the next 6 months", "outlook for 9 months", "miezi 6 ijayo"
    ahead = (re.search(r"\b(?:next|coming|ahead|within|over)\s+(\d{1,2})\s*months?\b", t)
             or re.search(r"\b(\d{1,2})\s*months?\s+(?:ahead|from now|time)\b", t)
             or re.search(r"\bin\s+(\d{1,2})\s*months?\b", t)
             or re.search(r"\bmiezi\s+(\d{1,2})\s+ijayo\b", t))
    if ahead and not pcts and ctx.b:
        return outlook_answer(ctx, int(ahead.group(1)))
    if any(has(t, toks, w) for w in ("outlook", "future", "coming months", "months ahead", "siku zijazo", "miezi ijayo")) and ctx.b and not pcts:
        return outlook_answer(ctx, ctx.user.outlook_months or 3)
    if intent == "risk" and scores.get("accuracy"):
        intent = "accuracy"
    if pcts and (intent in ("whatif", "advice", "") or re.search(r"\b(cut|reduce|raise|increase|lower|punguza|ongeza|if)\b", t)):
        return whatif(ctx, t, toks, float(pcts[0]) / 100)
    if intent in ("greeting",) and len(toks) <= 4 and not fig:
        return greeting(ctx)
    if intent == "thanks" and len(toks) <= 5 and not fig:
        return _out(ctx, "thanks", ctx.T("You're welcome. Ask me anything else about your business.",
                                         "Karibu. Niulize chochote kingine kuhusu biashara yako."))
    if intent in ("explain",) or (intent == "calc" and not fig):
        term = find_term(t, toks)
        if intent == "calc" and fig and ctx.records:
            return formula(ctx, fig)
        if term:
            return explain(ctx, term)
        if intent == "calc":
            return method(ctx)
    if intent == "calc" and fig:
        return formula(ctx, fig) if ctx.records else explain(ctx, find_term(t, toks) or "operating profit")
    if intent == "howto" or (intent in ("help", "") and any(has(t, toks, w) for ws in HOWTO.values() for w in ws if " " in w)):
        for topic, words in HOWTO.items():
            if any(has(t, toks, w) for w in words):
                return howto(ctx, topic)
    if intent == "risk" and not (scores.get("accuracy") and scores["accuracy"] >= scores["risk"]):
        return risk_answer(ctx)
    if intent == "distress":
        return distress_answer(ctx)
    if intent == "accuracy":
        return accuracy(ctx)
    if intent == "model_kind":
        return model_kind(ctx)
    if intent == "privacy":
        return privacy(ctx)
    if intent == "integrity":
        return integrity(ctx)
    if intent == "track":
        return track(ctx)
    if intent == "warnings":
        return warnings_answer(ctx)
    if intent == "advice":
        return advice(ctx, fig)
    if intent == "losses":
        return losses(ctx)
    if intent == "best_worst":
        return best_worst(ctx, t, fig or "operating_profit")
    if intent == "trend":
        return trend(ctx, fig)
    if fig:
        return lookup(ctx, fig, month, period)
    if month:
        return month_overview(ctx, month)
    for topic, words in HOWTO.items():
        if any(has(t, toks, w) for w in words):
            return howto(ctx, topic)
    term = find_term(t, toks)
    if term:
        return explain(ctx, term)
    if intent == "help":
        return help_answer(ctx)
    return fallback(ctx)


# ---------------------------------------------------------------- answers
def greeting(ctx: Ctx) -> dict:
    who = ctx.b.code if ctx.b else ctx.user.username
    return _out(ctx, "greeting", ctx.T(
        f"Hello {who}! I'm the Biashara Check assistant. Ask me about your sales, profit, cash or risk, what a word means, "
        "or how to do something in the app. I work inside the app: your figures never leave it.",
        f"Habari {who}! Mimi ni msaidizi wa Biashara Check. Niulize kuhusu mauzo, faida, pesa au hatari yako, maana ya neno, "
        "au jinsi ya kufanya kitu kwenye programu. Takwimu zako hazitoki nje ya programu."))


def help_answer(ctx: Ctx) -> dict:
    return _out(ctx, "help", ctx.T(
        "I can help with:\n"
        "• Your figures: \"What were my sales in March?\", \"Gross profit last 3 months\", \"Best month\"\n"
        "• Your risk: \"Why is my risk high?\", \"Chance of a cash shortfall\"\n"
        "• What-ifs: \"What if I raise prices by 5%?\", \"If I cut rent by 10%\"\n"
        "• Advice: \"How can I improve my cash flow?\"\n"
        "• Meanings and formulas: \"What is break-even?\", \"How is gross margin calculated?\"\n"
        "• The app: adding months, uploading Excel, reports, Biashara Pro, passwords, privacy.\n"
        "I'm a built-in assistant, not an outside AI, so I'm free and your figures never leave the app.",
        "Ninaweza kusaidia na:\n"
        "• Takwimu zako: \"Mauzo yangu ya Machi?\", \"Faida ghafi miezi 3\", \"Mwezi bora\"\n"
        "• Hatari yako: \"Kwa nini hatari yangu iko juu?\"\n"
        "• Kama nikifanya: \"Kama nikipandisha bei kwa 5%?\"\n"
        "• Ushauri: \"Nifanye nini kuongeza faida?\"\n"
        "• Maana na kanuni: \"Faida ghafi ni nini?\"\n"
        "• Programu: kuongeza miezi, kupakia Excel, ripoti, Biashara Pro, nenosiri, faragha.\n"
        "Mimi ni msaidizi wa ndani, si AI ya nje: ni bure na takwimu zako hazitoki nje."))


def fallback(ctx: Ctx) -> dict:
    return _out(ctx, "unknown", ctx.T(
        "Sorry, I didn't understand that. I'm a simple built-in assistant, so short questions work best, such as "
        "\"What was my profit in May?\", \"Why is my risk high?\" or \"What is gross margin?\".",
        "Samahani, sijaelewa. Mimi ni msaidizi rahisi, kwa hivyo maswali mafupi ni bora, kama "
        "\"Faida yangu ya Mei?\", \"Kwa nini hatari yangu iko juu?\" au \"Faida ghafi ni nini?\"."))


def _month_row(ctx: Ctx, ym: str) -> dict | None:
    return next((m for m in ctx.summary["months"] if m["month"] == ym), None) if ctx.summary else None


def lookup(ctx: Ctx, key: str, month: str | None, period: int | None) -> dict:
    if not ctx.records:
        return no_records(ctx, "figure")
    en, sw, _, unit = FIGURES[key]
    label = ctx.T(en, sw)
    months = ctx.summary["months"]
    sugg = [ctx.T(f"How is {en} calculated?", f"{sw.capitalize()} inakokotolewaje?"),
            ctx.T(f"Best month for {en}", f"Mwezi bora wa {sw}"), ctx.T(f"{en.capitalize()} trend", f"Mwelekeo wa {sw}")]
    if period is not None and not month:
        rows = months if period == 0 else months[-period:]
        span = ctx.T(f"{len(rows)} months ({month_label(rows[0]['month'], 'en')} to {month_label(rows[-1]['month'], 'en')})",
                     f"miezi {len(rows)} ({month_label(rows[0]['month'], 'sw')} hadi {month_label(rows[-1]['month'], 'sw')})")
        if key in SUMMABLE:
            tot = sum(value_of(key, m) or 0 for m in rows)
            avg = tot / len(rows)
            reply = ctx.T(f"Your {label} over the last {span} add up to {show(key, tot)}, an average of {show(key, avg)} a month.",
                          f"{label.capitalize()} zako kwa {span} ni jumla ya {show(key, tot)}, wastani wa {show(key, avg)} kwa mwezi.")
        else:
            S = {k: sum(m[k] for m in rows) for k in ("sales", "cogs", "opex")}
            agg = finance.month_figures({"month": rows[-1]["month"] + "-01", "revenue": S["sales"], "cogs": S["cogs"],
                                         "operating_expenses": S["opex"], **{k: 0 for k in ("cash_inflows", "cash_outflows",
                                         "mobile_money_receipts", "closing_stock", "outstanding_debt", "transaction_count")}})
            v = agg.get(key) if key in agg else None
            if v is None and key in ("debt", "stock"):
                v = rows[-1][key]
            reply = ctx.T(f"Your {label} over the last {span}: {show(key, v)}.", f"{label.capitalize()} kwa {span}: {show(key, v)}.")
        return _out(ctx, "figure", reply, sugg, context={"figure": key})
    ym = month or months[-1]["month"]
    row = _month_row(ctx, ym)
    if row is None:
        first, last = months[0]["month"], months[-1]["month"]
        return _out(ctx, "figure", ctx.T(
            f"I don't have {month_label(ym, 'en')} in your records. You have months from {month_label(first, 'en')} to {month_label(last, 'en')}.",
            f"Sina {month_label(ym, 'sw')} kwenye kumbukumbu zako. Una miezi kuanzia {month_label(first, 'sw')} hadi {month_label(last, 'sw')}."),
            context={"figure": key})
    v = value_of(key, row)
    ml = month_label(ym, ctx.lang)
    if key == "operating_profit":
        reply = ctx.T(f"In {ml} you made a profit of {kes(v)}." if v >= 0 else f"In {ml} you made a loss of {kes(-v)}.",
                      f"{ml}: ulipata faida ya {kes(v)}." if v >= 0 else f"{ml}: ulipata hasara ya {kes(-v)}.")
        reply += ctx.T(f"\nThat's sales {kes(row['sales'])} − cost of goods {kes(row['cogs'])} − running expenses {kes(row['opex'])}.",
                       f"\nYaani mauzo {kes(row['sales'])} − gharama ya bidhaa {kes(row['cogs'])} − gharama za uendeshaji {kes(row['opex'])}.")
    elif v is None:
        reply = ctx.T(f"{label.capitalize()} isn't recorded for {ml}.", f"{label.capitalize()} haijarekodiwa kwa {ml}.")
    else:
        verb = "were" if en in ("sales", "total costs", "running expenses") else "was"
        reply = ctx.T(f"Your {label} in {ml} {verb} {show(key, v)}.", f"{label.capitalize()} {ml}: {show(key, v)}.")
        item = next((i for i in ctx.summary["items"] if i["key"] == key), None) if ym == months[-1]["month"] else None
        if key == "gross_profit":
            reply += ctx.T(f"\nThat's sales {kes(row['sales'])} − cost of goods {kes(row['cogs'])}" + (f", {pct(row['gross_margin'])} of sales." if row["gross_margin"] is not None else "."),
                           f"\nYaani mauzo {kes(row['sales'])} − gharama ya bidhaa {kes(row['cogs'])}.")
        elif item and item.get("worked"):
            reply += ctx.T(f"\nWorked out: {item['worked']}", f"\nHesabu: {item['worked']}")
    i = [m["month"] for m in months].index(ym)
    if i > 0 and v is not None and key in SUMMABLE | {"net_margin", "gross_margin", "debt", "stock"}:
        pv = value_of(key, months[i - 1])
        if pv is not None and pv != v:
            up = v > pv
            diff = show(key, abs(v - pv)) if unit != "pct" else f"{abs(v - pv) * 100:.1f} points"
            pl = month_label(months[i - 1]["month"], ctx.lang)
            reply += ctx.T(f"\n{diff} {'more' if up else 'less'} than {pl}.", f"\n{diff} {'zaidi' if up else 'chini'} ya {pl}.")
    return _out(ctx, "figure", reply, sugg, context={"figure": key, "month": ym})


def month_overview(ctx: Ctx, ym: str) -> dict:
    if not ctx.records:
        return no_records(ctx, "month")
    row = _month_row(ctx, ym)
    if row is None:
        return lookup(ctx, "operating_profit", ym, None)
    ml = month_label(ym, ctx.lang)
    p = row["operating_profit"]
    reply = ctx.T(
        f"{ml} at a glance:\n• Sales {kes(row['sales'])}\n• Gross profit {kes(row['gross_profit'])}\n"
        f"• {'Profit' if p >= 0 else 'Loss'} {kes(abs(p))}\n• Cash left over {kes(row['net_cash_flow'])}",
        f"{ml} kwa ufupi:\n• Mauzo {kes(row['sales'])}\n• Faida ghafi {kes(row['gross_profit'])}\n"
        f"• {'Faida' if p >= 0 else 'Hasara'} {kes(abs(p))}\n• Pesa iliyobaki {kes(row['net_cash_flow'])}")
    return _out(ctx, "month", reply, context={"month": ym})


def formula(ctx: Ctx, key: str) -> dict:
    items = {i["key"]: i for i in (ctx.summary or {}).get("items", [])}
    k = {"total_costs": "cost_ratio", "sales": None, "cash_in": None, "cash_out": None}.get(key, key)
    if k in items:
        it = items[k]
        reply = ctx.T(f"{it['name']} = {it['formula']}.\nWith your latest month ({month_label(ctx.summary['latest']['month'], 'en')}): {it['worked']}\n{it['meaning']}",
                      f"{it['name']} = {it['formula']}.\nKwa mwezi wako wa mwisho: {it['worked']}\n{it['meaning']}")
        return _out(ctx, "calc", reply, links=[{"label": ctx.T("All formulas", "Kanuni zote"), "href": "/how#figures"}], context={"figure": key})
    term = {"sales": None, "operating_profit": "operating profit"}.get(key)
    if term:
        return explain(ctx, term)
    return _out(ctx, "calc", ctx.T(f"{FIGURES[key][0].capitalize()} is a figure you enter yourself each month, so there's no formula behind it.",
                                   f"{FIGURES[key][1].capitalize()} ni takwimu unayoingiza mwenyewe kila mwezi."),
                links=[{"label": ctx.T("All formulas", "Kanuni zote"), "href": "/how#figures"}])


def explain(ctx: Ctx, term: str) -> dict:
    en, sw = GLOSSARY[term]
    reply = ctx.T(en, sw)
    s = ctx.summary
    if s and term in ("gross profit", "gross margin", "break even", "margin of safety", "operating profit", "net margin", "cash flow"):
        key = {"break even": "break_even_sales", "cash flow": "net_cash_flow"}.get(term, term.replace(" ", "_"))
        it = next((i for i in s["items"] if i["key"] == key), None)
        if it:
            reply += ctx.T(f"\nYours for {month_label(s['latest']['month'], 'en')}: {it['worked']}", f"\nYako: {it['worked']}")
    link = {"risk": "/how#risk", "shap": "/how#risk", "distress": "/how#distress", "logistic regression": "/how#distress",
            "calibration": "/how#accuracy", "recall": "/how#accuracy", "precision": "/how#accuracy", "pr-auc": "/how#accuracy",
            "roc-auc": "/how#accuracy", "brier": "/how#accuracy", "fingerprint": "/how#integrity", "odds ratio": "/how#distress",
            "p-value": "/how#distress"}.get(term, "/how#figures")
    return _out(ctx, "explain", reply, links=[{"label": ctx.T("Read more", "Soma zaidi"), "href": link}])


def method(ctx: Ctx) -> dict:
    return _out(ctx, "calc", ctx.T(
        "Every figure has a fixed formula (gross profit = sales − cost of goods, profit = gross profit − running expenses, cash left over = money received − money paid out). "
        "The risk % comes from a machine-learning model and the distress % from a logistic regression. Ask about any one, e.g. \"How is break-even calculated?\"",
        "Kila takwimu ina kanuni (faida ghafi = mauzo − gharama ya bidhaa, faida = faida ghafi − gharama za uendeshaji). "
        "Asilimia ya hatari inatoka kwa modeli ya machine learning, na ya dhiki kwa logistic regression."),
        links=[{"label": ctx.T("How it's calculated", "Jinsi inavyokokotolewa"), "href": "/how"}])


def _risk_link(ctx):
    return [{"label": ctx.T("How the % is worked out", "Jinsi asilimia inavyokokotolewa"), "href": "/how#risk"}]


def risk_answer(ctx: Ctx) -> dict:
    from . import risk
    if len(ctx.records) < 3:
        return _out(ctx, "risk", ctx.T(f"Your risk check needs at least 3 months; you have {len(ctx.records)}. Add {3 - len(ctx.records)} more.",
                                       f"Ukaguzi wa hatari unahitaji angalau miezi 3; una {len(ctx.records)}."))
    r = risk.compute(ctx.db, ctx.b, lang=ctx.lang) if risk.model_ready() else None
    if r is None:
        s = ctx.summary
        n3 = s["totals"]["last3"]["operating_profit"]
        band = "High" if n3 < 0 else "Moderate" if len([c for c in s["checks"] if c["level"] == "bad"]) >= 2 else "Low"
        reply = ctx.T(f"The model isn't trained yet, so this is the simple early check: {band} risk. Your last 3 months added up to {kes(n3)}.",
                      f"Modeli bado haijafunzwa, kwa hivyo huu ni ukaguzi rahisi: hatari {band}. Miezi 3 iliyopita jumla ni {kes(n3)}.")
        return _out(ctx, "risk", reply, links=_risk_link(ctx))
    bands = {"Low": ("Low", "Chini"), "Moderate": ("Moderate", "Wastani"), "High": ("High", "Juu")}[r["band"]]
    pc_ = round(r["probability"] * 100)
    reply = ctx.T(f"Your risk check: {pc_}% ({bands[0]}). That's the chance that at least one of your next 3 months is a loss month, based on your figures up to {month_label(r['as_of'], 'en')}.",
                  f"Ukaguzi wako wa hatari: {pc_}% ({bands[1]}). Huu ni uwezekano kwamba angalau mwezi mmoja kati ya 3 ijayo utakuwa wa hasara, kwa takwimu hadi {month_label(r['as_of'], 'sw')}.")
    if r["reasons"]:
        reply += ctx.T("\nWhat pushes it up:", "\nKinachoiongeza:")
        for x in r["reasons"]:
            reply += f"\n• {x['text']}" + (ctx.T(f" Try: {x['tip']}", f" Jaribu: {x['tip']}") if x.get("tip") else "")
    if r["protective"]:
        reply += ctx.T("\nWhat keeps it down:", "\nKinachoipunguza:")
        for x in r["protective"][:2]:
            reply += f"\n• {x['text']}"
    return _out(ctx, "risk", reply, [ctx.T("Is the risk % accurate?", "Je, asilimia ni sahihi?"),
                                     ctx.T("Chance of a cash shortfall?", "Uwezekano wa upungufu wa pesa?"),
                                     ctx.T("How can I lower my risk?", "Nifanye nini kupunguza hatari?")], _risk_link(ctx))


def outlook_answer(ctx: Ctx, months: int) -> dict:
    from . import risk
    link = [{"label": ctx.T("See your outlook", "Ona mwelekeo wako"), "href": "/#outlook"}]
    if not 1 <= months <= 12:
        return _out(ctx, "outlook", ctx.T("I can look 1 to 12 months ahead. Try, for example, \"risk in the next 6 months\".",
                                          "Ninaweza kuangalia miezi 1 hadi 12 mbele."), links=link)
    if len(ctx.records) < 3:
        return _out(ctx, "outlook", ctx.T("The outlook needs at least 3 months of figures.", "Mwelekeo unahitaji angalau miezi 3 ya takwimu."))
    ol = risk.compute_outlook(ctx.db, ctx.b, months, lang=ctx.lang) if risk.model_ready() and risk.outlook_ready() else None
    if ol is None:
        return _out(ctx, "outlook", ctx.T("The outlook isn't available yet: the risk model needs to be trained first.",
                                          "Mwelekeo bado haupatikani."), links=link)
    pc = round(ol["probability"] * 100)
    until = month_label(ol["until"], ctx.lang)
    bsw = {"Low": "Chini", "Moderate": "Wastani", "High": "Juu"}[ol["band"]]
    reply = ctx.T(f"Looking {months} month{'s' if months != 1 else ''} ahead (to {until}): {pc}% chance of at least one loss month ({ol['band']}).",
                  f"Ukiangalia miezi {months} mbele (hadi {until}): uwezekano wa {pc}% wa angalau mwezi mmoja wa hasara ({bsw}).")
    if ol["reasons"]:
        reply += ctx.T("\nWhat pushes it up:", "\nKinachoiongeza:") + "".join(f"\n• {x['text']}" for x in ol["reasons"][:3])
    ev = ol.get("evidence")
    if ev and ev.get("enough"):
        hi = next((b for b in ev["bands"] if b["band"] == "High"), None)
        if hi and hi["actual"] is not None:
            reply += ctx.T(f"\nIn testing, {round(hi['actual'] * 100)}% of businesses rated High this far ahead did have a loss.",
                           f"\nKatika majaribio, {round(hi['actual'] * 100)}% ya biashara zilizowekwa Juu zilipata hasara.")
    others = [h for h in (1, 3, 6, 12) if h != months][:3]
    return _out(ctx, "outlook", reply,
                [ctx.T(f"Risk in the next {h} months", f"Hatari katika miezi {h} ijayo") for h in others], links=link)


def distress_answer(ctx: Ctx) -> dict:
    from . import risk
    d = risk.compute_distress(ctx.db, ctx.b, lang=ctx.lang) if ctx.b and risk.model_ready() else None
    if d is None:
        return _out(ctx, "distress", ctx.T("The financial distress check needs at least 3 months and a trained model. It isn't available yet.",
                                           "Ukaguzi wa dhiki ya kifedha unahitaji miezi 3 na modeli iliyofunzwa. Bado haupatikani."))
    pc_ = round(d["probability"] * 100)
    bsw = {"Low": "Chini", "Moderate": "Wastani", "High": "Juu"}[d["band"]]
    reply = ctx.T(f"Chance of financial distress in the next 3 months: {pc_}% ({d['band']}). Distress here means more money going out than coming in, or debt rising by more than half a month's sales.",
                  f"Uwezekano wa dhiki ya kifedha katika miezi 3 ijayo: {pc_}% ({bsw}). Dhiki hapa ni pesa zinazotoka kuzidi zinazoingia, au madeni kuongezeka zaidi ya nusu ya mauzo ya mwezi.")
    if d["drivers_up"]:
        reply += ctx.T("\nPushing it up:", "\nKinachoiongeza:") + "".join(f"\n• {x['text']}" for x in d["drivers_up"])
    if d["drivers_down"]:
        reply += ctx.T("\nKeeping it down:", "\nKinachoipunguza:") + "".join(f"\n• {x['text']}" for x in d["drivers_down"][:2])
    reply += ctx.T(f"\nIt's a logistic regression: log-odds {d['log_odds']:+.2f} → 1 / (1 + e^{-d['log_odds']:+.2f}) = {d['probability'] * 100:.1f}%. The full sum is under \"See the full calculation\" on the dashboard.",
                   f"\nNi logistic regression: log-odds {d['log_odds']:+.2f} → {d['probability'] * 100:.1f}%. Hesabu kamili iko kwenye dashibodi.")
    return _out(ctx, "distress", reply, links=[{"label": ctx.T("About this model", "Kuhusu modeli hii"), "href": "/how#distress"}])


def _evidence():
    from . import risk
    if not risk.model_ready():
        return None
    from ml.train import load
    _, meta = load()
    return meta


def accuracy(ctx: Ctx) -> dict:
    meta = _evidence()
    if not meta or not meta.get("evidence"):
        return _out(ctx, "accuracy", ctx.T("The model's test results aren't available yet: it needs to be trained (or retrained) first.",
                                           "Matokeo ya majaribio ya modeli bado hayapatikani."), links=[{"label": "How it's calculated", "href": "/how#accuracy"}])
    e, best = meta["evidence"], meta["models"][meta["best"]]
    b = {x["band"]: x for x in e["bands"]}
    lo, mo, hi = (pct(b[k]["actual"]) if b[k]["actual"] is not None else "-" for k in ("Low", "Moderate", "High"))
    reply = ctx.T(
        f"It was tested on {meta['rows']['test']:,} business-months it had never seen ({month_label(e['test_months'][0], 'en')} to {month_label(e['test_months'][1], 'en')}). "
        f"Of months it put in Low risk, {lo} were followed by a loss; Moderate {mo}; High {hi}. "
        f"It caught {pct(best['recall'])} of coming losses, and when it warned it was right {pct(best['precision'])} of the time "
        f"(a simple rule caught {pct(e['rule']['recall'])}).",
        f"Ilijaribiwa kwa miezi {meta['rows']['test']:,} ambayo haikuwahi kuona. Miezi iliyowekwa Chini: {lo} ilifuatwa na hasara; Wastani {mo}; Juu {hi}. "
        f"Ilinasa {pct(best['recall'])} ya hasara zilizokuja.")
    if meta["rows"].get("synthetic"):
        reply += ctx.T("\nHonest note: most training months are simulated businesses; accuracy on real businesses is being measured in this study.",
                       "\nKwa uwazi: miezi mingi ya mafunzo ni ya biashara zilizoigwa; usahihi kwa biashara halisi unapimwa katika utafiti huu.")
    from . import risk
    tr = risk.track_record(ctx.db, ctx.b) if ctx.b else None
    if tr and tr["judged"]:
        reply += ctx.T(f"\nFor your own business: {tr['right']} of {tr['judged']} past checks that can be judged turned out right.",
                       f"\nKwa biashara yako: {tr['right']} kati ya {tr['judged']} ya ukaguzi uliopita yalitimia.")
    return _out(ctx, "accuracy", reply, links=[{"label": ctx.T("See the evidence", "Ona ushahidi"), "href": "/how#accuracy"}])


def model_kind(ctx: Ctx) -> dict:
    meta = _evidence()
    name = meta.get("best_name") if meta else None
    return _out(ctx, "model_kind", ctx.T(
        "All three kinds, each for a different job:\n"
        f"• Risk of a loss: machine learning ({name or 'the best of four models, once trained'}), explained with SHAP.\n"
        "• Financial distress: a statistical model (logistic regression).\n"
        "• Warnings: fixed business rules.\n• Gross profit, margins, cash flow: plain formulas.\n"
        "And me? I'm a built-in assistant that matches your question to answers from your figures. I'm not an outside AI, so nothing you type leaves the app.",
        "Aina zote tatu:\n• Hatari ya hasara: machine learning.\n• Dhiki ya kifedha: modeli ya kitakwimu (logistic regression).\n"
        "• Tahadhari: kanuni za biashara.\n• Faida ghafi, viwango, mtiririko wa pesa: kanuni za hesabu.\n"
        "Mimi ni msaidizi wa ndani, si AI ya nje, kwa hivyo unachoandika hakitoki nje."),
        links=[{"label": ctx.T("ML, statistics or rules?", "ML, takwimu au kanuni?"), "href": "/how#kinds"}])


def privacy(ctx: Ctx) -> dict:
    return _out(ctx, "privacy", ctx.T(
        "Your figures are kept under a business code, not your name. Your email and phone are encrypted and hidden from the study team. "
        "Nothing is shared with lenders or anyone else: reports leave only when you download them or email them to yourself. "
        "You can download, correct or delete everything. This chat doesn't use any outside service and your messages aren't saved.",
        "Takwimu zako zinahifadhiwa kwa msimbo wa biashara, si jina lako. Barua pepe na simu zimesimbwa. "
        "Hakuna kinachoshirikiwa na wakopeshaji au mtu mwingine. Unaweza kupakua, kurekebisha au kufuta kila kitu. Mazungumzo haya hayahifadhiwi."),
        links=[{"label": ctx.T("Your data and privacy", "Data yako na faragha"), "href": "/how#privacy"}])


def integrity(ctx: Ctx) -> dict:
    if not ctx.b or not ctx.records:
        return no_records(ctx, "integrity")
    i = finance.integrity(ctx.db, ctx.b)
    reply = ctx.T(f"You have {i['months']} months saved, {month_label(i['first'], 'en')} to {month_label(i['last'], 'en')}. ",
                  f"Una miezi {i['months']} imehifadhiwa. ")
    reply += ctx.T(("Missing: " + ", ".join(month_label(g, "en") for g in i["gaps"][:6]) + ". Gaps make the check less reliable.") if i["gaps"] else "No months are missing.",
                   ("Inakosekana: " + ", ".join(month_label(g, "sw") for g in i["gaps"][:6]) + ".") if i["gaps"] else "Hakuna mwezi unaokosekana.")
    if i["flagged"]:
        reply += ctx.T("\nWorth double-checking:", "\nAngalia tena:") + "".join(f"\n• {month_label(f['month'], ctx.lang)}: {'; '.join(f['flags'])}" for f in i["flagged"][:4])
    else:
        reply += ctx.T("\nNo month looks like a typing mistake.", "\nHakuna mwezi unaoonekana kuwa na kosa la kuandika.")
    return _out(ctx, "integrity", reply, links=[{"label": ctx.T("Your records now", "Kumbukumbu zako"), "href": "/how#integrity"}])


def track(ctx: Ctx) -> dict:
    from . import risk
    tr = risk.track_record(ctx.db, ctx.b) if ctx.b else {"checks": [], "judged": 0, "right": 0}
    if not tr["checks"]:
        return _out(ctx, "track", ctx.T("Not enough time has passed: a check is judged once the 3 months after it are recorded.",
                                        "Bado muda haujatosha: ukaguzi hupimwa baada ya miezi 3 inayofuata kurekodiwa."))
    return _out(ctx, "track", ctx.T(f"Of {tr['judged']} past Low or High checks that can be judged, {tr['right']} turned out right.",
                                    f"Kati ya ukaguzi {tr['judged']} wa Chini au Juu unaoweza kupimwa, {tr['right']} ulitimia."),
                links=[{"label": ctx.T("See each check", "Ona kila ukaguzi"), "href": "/how#yours"}])


def warnings_answer(ctx: Ctx) -> dict:
    if not ctx.records:
        return no_records(ctx, "warnings")
    ch = ctx.summary["checks"]
    if not ch:
        return _out(ctx, "warnings", ctx.T(f"No warnings for {month_label(ctx.summary['latest']['month'], 'en')}: none of the business rules was triggered.",
                                           "Hakuna tahadhari kwa mwezi wako wa mwisho."))
    reply = ctx.T(f"{len(ch)} thing{'s' if len(ch) != 1 else ''} to look at:", f"Mambo {len(ch)} ya kuangalia:")
    for c in ch[:5]:
        reply += f"\n• {c['title']}: {c['text']}"
    return _out(ctx, "warnings", reply, [ctx.T("How can I improve my profit?", "Nifanye nini kuongeza faida?"),
                                         ctx.T("Why is my risk at this level?", "Kwa nini hatari yangu iko hivi?")])


def _avg3(ctx: Ctx) -> dict:
    rows = ctx.summary["months"][-3:]
    return {k: sum(r[k] for r in rows) / len(rows) for k in ("sales", "cogs", "opex", "operating_profit", "net_cash_flow", "cash_in", "cash_out")}


def advice(ctx: Ctx, fig: str | None) -> dict:
    if not ctx.records:
        return no_records(ctx, "advice")
    a, L = _avg3(ctx), ctx.summary["latest"]
    n = len(ctx.summary["months"][-3:])
    base = ctx.T(f"(averages of your last {n} months)", f"(wastani wa miezi {n} iliyopita)")
    topic = {"opex": "costs", "cogs": "cogs", "total_costs": "costs", "sales": "sales", "transactions": "sales", "avg_sale": "sales",
             "net_cash_flow": "cash", "cash_in": "cash", "cash_out": "cash", "debt": "debt", "stock": "stock",
             "gross_margin": "cogs", "gross_profit": "cogs"}.get(fig or "", "profit")
    lines = []
    if topic in ("costs", "profit"):
        save = a["opex"] * 0.10
        lines.append(ctx.T(f"Running costs average {kes(a['opex'])} a month {base}. Cutting them by 10% adds about {kes(save)} a month to profit. List them and start with the biggest: rent, wages, power, transport.",
                           f"Gharama za uendeshaji ni wastani wa {kes(a['opex'])} kwa mwezi. Kuzipunguza kwa 10% kunaongeza takriban {kes(save)} kwa mwezi."))
    if topic in ("cogs", "profit"):
        gm = (a["sales"] - a["cogs"]) / a["sales"] if a["sales"] else None
        lines.append(ctx.T(f"You keep {pct(gm)} of sales after paying for stock. Raising prices 5% on your best sellers, or buying 5% cheaper (bulk buying, other suppliers), adds about {kes(a['sales'] * 0.05)} a month.",
                           f"Unabaki na {pct(gm)} ya mauzo baada ya kulipia bidhaa. Kupandisha bei kwa 5% au kununua kwa bei nafuu kwa 5% kunaongeza takriban {kes(a['sales'] * 0.05)} kwa mwezi."))
    if topic in ("sales", "profit"):
        be = L["break_even_sales"]
        if be is not None:
            gap = L["sales"] - be
            lines.append(ctx.T(f"Your break-even is {kes(be)} of sales a month; last month you were {kes(abs(gap))} {'above' if gap >= 0 else 'below'} it. "
                               "Bring back regular customers, keep popular items in stock, and tell customers you take M-Pesa.",
                               f"Mauzo ya kurudisha gharama ni {kes(be)} kwa mwezi; mwezi uliopita ulikuwa {kes(abs(gap))} {'juu' if gap >= 0 else 'chini'}."))
    if topic in ("cash", "profit"):
        lines.append(ctx.T(f"Cash left over averages {kes(a['net_cash_flow'])} a month. Follow up customers who owe you, buy stock in smaller amounts more often, and keep a weekly cash book.",
                           f"Pesa iliyobaki ni wastani wa {kes(a['net_cash_flow'])} kwa mwezi. Fuatilia wanaokudai, nunua bidhaa kidogo mara nyingi zaidi, na weka daftari la pesa la kila wiki."))
    if topic == "debt":
        lines.append(ctx.T(f"You owe {kes(L['debt'])}" + (f", about {L['debt_months']:.1f} months of sales." if L["debt_months"] else ".") +
                           " Pay the most expensive loans first (mobile loans are often the dearest), avoid buying slow stock on credit, and agree a plan with lenders early.",
                           f"Unadaiwa {kes(L['debt'])}. Lipa kwanza mikopo yenye riba kubwa, epuka kununua bidhaa zinazouzwa polepole kwa mkopo."))
    if topic == "stock":
        lines.append(ctx.T(f"Stock at month end was {kes(L['stock'])}" + (f", {L['stock_cover']:.1f} months' worth." if L["stock_cover"] else ".") +
                           " Sell slow movers with a small discount and reorder little and often, so less cash sits on the shelves.",
                           f"Bidhaa mwisho wa mwezi zilikuwa {kes(L['stock'])}. Uza zinazouzwa polepole kwa punguzo kidogo na nunua kidogo mara nyingi."))
    from . import risk
    r = risk.compute(ctx.db, ctx.b, lang=ctx.lang) if topic == "profit" and risk.model_ready() and len(ctx.records) >= 3 else None
    if r and r["reasons"]:
        lines.append(ctx.T("From your risk check: ", "Kutoka ukaguzi wa hatari: ") + " ".join(x["tip"] for x in r["reasons"][:2] if x.get("tip")))
    reply = "\n".join(f"• {x}" for x in lines)
    return _out(ctx, "advice", reply, [ctx.T("What if I cut running costs by 10%?", "Kama nikipunguza gharama za uendeshaji kwa 10%?"),
                                       ctx.T("What if I raise prices by 5%?", "Kama nikipandisha bei kwa 5%?"),
                                       ctx.T("What should I worry about?", "Nini kinapaswa kunitia wasiwasi?")])


def whatif(ctx: Ctx, t: str, toks: list[str], p: float) -> dict:
    if not ctx.records:
        return no_records(ctx, "whatif")
    a = _avg3(ctx)
    S, C, O = a["sales"], a["cogs"], a["opex"]
    down = bool(re.search(r"\b(cut|reduce|lower|drop|fall|falls|decrease|less|save|punguza|nikipunguza|shuka)\b", t))
    up = bool(re.search(r"\b(raise|increase|more|grow|rise|rises|up|add|ongeza|nikiongeza|pandisha|nikipandisha)\b", t))
    sign = -1 if down and not up else 1
    if has(t, toks, "price") or has(t, toks, "prices") or "bei" in toks:
        what, S2, C2, O2 = ("prices", "bei"), S * (1 + sign * p), C, O
        note = ctx.T("assuming you sell the same amount", "ikiwa unauza kiasi kilekile")
    elif any(has(t, toks, w) for w in ("cost of goods", "cogs", "stock", "supplier", "suppliers", "buying", "purchases", "bidhaa")):
        what, S2, C2, O2 = ("cost of goods", "gharama ya bidhaa"), S, C * (1 + sign * p), O
        note = ctx.T("with the same sales", "kwa mauzo yaleyale")
    elif any(has(t, toks, w) for w in ("running", "rent", "wages", "salaries", "expenses", "overheads", "power", "transport", "uendeshaji", "kodi", "mishahara")):
        what, S2, C2, O2 = ("running costs", "gharama za uendeshaji"), S, C, O * (1 + sign * p)
        note = ctx.T("with the same sales", "kwa mauzo yaleyale")
    elif any(has(t, toks, w) for w in ("sales", "sell", "customers", "revenue", "mauzo", "wateja")):
        what, S2, C2, O2 = ("sales", "mauzo"), S * (1 + sign * p), C * (1 + sign * p), O
        note = ctx.T("at today's prices: cost of goods moves with sales, running costs stay the same",
                     "kwa bei za sasa, gharama ya bidhaa ikienda pamoja na mauzo")
    else:
        what, S2, C2, O2 = ("all costs", "gharama zote"), S, C * (1 + sign * p), O * (1 + sign * p)
        note = ctx.T("with the same sales", "kwa mauzo yaleyale")
    before, after = S - C - O, S2 - C2 - O2
    verb = ctx.T(("rose" if sign > 0 else "fell") if what[0] == "sales" else ("were raised" if sign > 0 else "were cut"),
                 "zikiongezwa" if sign > 0 else "zikipunguzwa")
    reply = ctx.T(
        f"If {what[0]} {verb} by {p * 100:g}% ({note}), based on your last 3 months' average:\n"
        f"• Profit now: {kes(before)} a month\n• Profit then: {kes(after)} a month\n• Change: {'+' if after >= before else '-'}{kes(abs(after - before))} a month, about {kes(abs(after - before) * 12)} a year",
        f"Kama {what[1]} {verb} kwa {p * 100:g}% ({note}), kwa wastani wa miezi 3 iliyopita:\n"
        f"• Faida sasa: {kes(before)} kwa mwezi\n• Faida baadaye: {kes(after)} kwa mwezi\n• Tofauti: {kes(after - before)} kwa mwezi")
    if before < 0 <= after:
        reply += ctx.T("\nThat would turn your average month from a loss into a profit.", "\nHilo lingegeuza mwezi wako wa wastani kutoka hasara hadi faida.")
    elif before >= 0 > after:
        reply += ctx.T("\nCareful: that would turn your average month into a loss.", "\nTahadhari: hilo lingegeuza mwezi wako wa wastani kuwa hasara.")
    if what[0] == "prices" and sign > 0:
        reply += ctx.T("\nCustomers may buy a little less after a price rise, so try it on a few items first.",
                       "\nWateja wanaweza kununua kidogo baada ya kupandisha bei, kwa hivyo jaribu kwa bidhaa chache kwanza.")
    return _out(ctx, "whatif", reply, [ctx.T("What if sales fall by 10%?", "Kama mauzo yakishuka kwa 10%?"),
                                       ctx.T("What if I cut cost of goods by 5%?", "Kama nikipunguza gharama ya bidhaa kwa 5%?"),
                                       ctx.T("What is break-even?", "Mauzo ya kurudisha gharama ni nini?")])


def losses(ctx: Ctx) -> dict:
    if not ctx.records:
        return no_records(ctx, "losses")
    lm = [m for m in ctx.summary["months"] if m["operating_profit"] < 0]
    n = len(ctx.summary["months"])
    if not lm:
        return _out(ctx, "losses", ctx.T(f"None: all {n} of your months were profitable.", f"Hakuna: miezi yako yote {n} ilikuwa na faida."))
    worst = min(lm, key=lambda m: m["operating_profit"])
    return _out(ctx, "losses", ctx.T(
        f"{len(lm)} of your {n} months were losses: " + ", ".join(month_label(m["month"], "en") for m in lm[-6:]) + ("…" if len(lm) > 6 else "") +
        f". The biggest was {month_label(worst['month'], 'en')} ({kes(-worst['operating_profit'])}).",
        f"Miezi {len(lm)} kati ya {n} ilikuwa ya hasara: " + ", ".join(month_label(m["month"], "sw") for m in lm[-6:]) +
        f". Kubwa zaidi ilikuwa {month_label(worst['month'], 'sw')} ({kes(-worst['operating_profit'])})."), context={"figure": "operating_profit"})


def best_worst(ctx: Ctx, t: str, key: str) -> dict:
    if not ctx.records:
        return no_records(ctx, "best_worst")
    rows = [m for m in ctx.summary["months"] if value_of(key, m) is not None]
    if not rows:
        return lookup(ctx, key, None, None)
    worst_q = bool(re.search(r"\b(worst|lowest|smallest|least|mbaya|chini zaidi)\b", t))
    pick = (min if worst_q ^ (key in ("total_costs", "opex", "cogs", "debt")) else max)(rows, key=lambda m: value_of(key, m))
    en, sw = FIGURES[key][0], FIGURES[key][1]
    return _out(ctx, "best_worst", ctx.T(
        f"Your {'lowest' if worst_q else 'highest'} {en}: {month_label(pick['month'], 'en')}, {show(key, value_of(key, pick))}." if key not in ("operating_profit",) else
        f"Your {'worst' if worst_q else 'best'} month for profit: {month_label(pick['month'], 'en')}, {kes(pick['operating_profit'])}.",
        f"{'Chini zaidi' if worst_q else 'Juu zaidi'} ({sw}): {month_label(pick['month'], 'sw')}, {show(key, value_of(key, pick))}."),
        context={"figure": key, "month": pick["month"]})


def trend(ctx: Ctx, fig: str | None) -> dict:
    if not ctx.records:
        return no_records(ctx, "trend")
    tr = ctx.summary["trends"]
    if not tr:
        return _out(ctx, "trend", ctx.T("I need at least 6 months to compare your last 3 months with the 3 before.",
                                        "Nahitaji angalau miezi 6 kulinganisha miezi 3 iliyopita na 3 kabla yake."))
    keys = [fig] if fig in tr else ["sales", "gross_profit", "opex", "operating_profit", "net_cash_flow"]
    lab = {"sales": ("Sales", "Mauzo"), "gross_profit": ("Gross profit", "Faida ghafi"), "opex": ("Running costs", "Gharama za uendeshaji"),
           "operating_profit": ("Profit", "Faida"), "net_cash_flow": ("Cash left over", "Pesa iliyobaki")}
    reply = ctx.T("Last 3 months compared with the 3 before:", "Miezi 3 iliyopita ukilinganisha na 3 kabla yake:")
    for k in keys:
        x = tr[k]
        ch = f"{x['change'] * 100:+.0f}%" if x["change"] is not None else "-"
        reply += f"\n• {ctx.T(*lab[k])}: {kes(x['before'])} → {kes(x['now'])} ({ch})"
    s, p = tr["sales"]["change"], tr["operating_profit"]["now"] - tr["operating_profit"]["before"]
    if s is not None:
        reply += ctx.T(f"\nIn short: sales are {'growing' if s > 0.02 else 'falling' if s < -0.02 else 'flat'} and profit is {'up' if p > 0 else 'down'}.",
                       f"\nKwa ufupi: mauzo {'yanakua' if s > 0.02 else 'yanashuka' if s < -0.02 else 'hayabadiliki'} na faida {'imepanda' if p > 0 else 'imeshuka'}.")
    return _out(ctx, "trend", reply)


SUB_WORDS = ["subscription", "subscribe", "unsubscribe", "cancel my", "cancel pro", "cancel the", "renew", "renewal", "renews",
             "expire", "expires", "expiry", "pro end", "pro ends", "when does my pro", "billing", "auto renew", "sitisha", "usajili"]


def subscription(ctx: Ctx) -> dict:
    st = pro.status(ctx.b)
    link = [{"label": ctx.T("Manage Biashara Pro", "Simamia Biashara Pro"), "href": "/account#pro"}]
    if not st["active"]:
        return _out(ctx, "subscription", ctx.T(
            "You're on the free plan, so there's nothing to cancel and nothing will be charged. You can get Biashara Pro on the Account page, Biashara Pro tab.",
            "Uko kwenye mpango wa bure, kwa hivyo hakuna cha kusitisha wala kulipishwa."), links=link)
    from datetime import datetime, timedelta
    end = (datetime.fromisoformat(st["until"].rstrip("Z")) + timedelta(hours=3)).strftime("%a %d %b %Y, %H:%M")
    reply = ctx.T(f"Your Biashara Pro is active until {end} (Nairobi time), {st['days_left']} days from now.",
                  f"Biashara Pro yako inafanya kazi hadi {end}, siku {st['days_left']} kuanzia sasa.")
    if st["auto_renew"]:
        r = st["renewal"]
        reply += ctx.T(f"\nAutomatic renewal is on: about a day before it ends we'll send an M-Pesa prompt for {kes(r['amount'])} to {r['phone']}. Nothing is paid unless you enter your PIN."
                       "\nTo stop future payments: Account → Biashara Pro → **Cancel automatic renewal**. Pro keeps working until the end date.",
                       f"\nKulipia upya kiotomatiki kumewashwa: siku moja kabla ya mwisho tutatuma ombi la M-Pesa la {kes(r['amount'])}. "
                       "\nKusitisha: Akaunti → Biashara Pro → **Sitisha kulipia upya kiotomatiki**.")
    else:
        reply += ctx.T("\nAutomatic renewal is off, so nothing more will be charged. Pro simply ends on that date.",
                       "\nKulipia upya kiotomatiki kumezimwa, kwa hivyo hakuna malipo zaidi.")
    return _out(ctx, "subscription", reply, links=link)


HOWTO_TEXT = {
    "add_month": ("On the dashboard choose **Add a month** (or the green \"Add <month>\" button). Type sales, cost of goods sold, running expenses, money received and money paid out, then Save. Profit and cash show as you type.",
                  "Kwenye dashibodi chagua **Ongeza mwezi**. Andika mauzo, gharama ya bidhaa, gharama za uendeshaji, pesa zilizoingia na zilizotoka, kisha Hifadhi.", "/#add"),
    "edit": ("In **Your records** on the dashboard, choose Edit on that month, change the figure and save. To remove it, choose Edit then **Delete this month**.",
             "Kwenye **Kumbukumbu zako**, chagua Hariri kwenye mwezi huo, badilisha na uhifadhi.", "/#records-card"),
    "upload": ("Use the **Upload CSV** tab on the dashboard. Any layout works: CSV or Excel, months down or across, English or Kiswahili headings. You'll see how the file was read before anything is saved.",
               "Tumia kichupo cha **Pakia CSV**. Mpangilio wowote unafanya kazi, na utaona jinsi faili lilivyosomwa kabla ya kuhifadhi.", "/#upload"),
    "mpesa": ("With Biashara Pro, the **M-Pesa** tab reads your M-Pesa statement (PDF with its password, or CSV) and fills in M-Pesa receipts and number of sales for each month. The statement is thrown away after reading.",
              "Kwa Biashara Pro, kichupo cha **M-Pesa** husoma taarifa yako ya M-Pesa na kujaza pesa za M-Pesa kwa kila mwezi.", "/#mpesa"),
    "reports": ("Choose **Reports (PDF)** on the dashboard. The monthly summary is free; the business report and the summary for lenders come with Biashara Pro. Each can be downloaded or emailed to your own confirmed email.",
                "Chagua **Ripoti (PDF)** kwenye dashibodi. Muhtasari wa mwezi ni bure; ripoti nyingine ni za Biashara Pro.", "/#reports"),
    "pro": ("Biashara Pro adds the M-Pesa statement import, the full business report and the summary for lenders. Pay with M-Pesa on the Account page, Biashara Pro tab.",
            "Biashara Pro inaongeza usomaji wa taarifa ya M-Pesa na ripoti kamili. Lipa kwa M-Pesa kwenye ukurasa wa Akaunti.", "/account#pro"),
    "username": ("Account → **Username and password** → Change username. You need your current password. You can still log in with your business code or email.",
                 "Akaunti → **Jina la mtumiaji na nenosiri** → Badilisha jina la mtumiaji.", "/account#security"),
    "password": ("To change it: Account → Username and password. Forgot it? On the login page choose \"Forgot password\" and use your email, SMS or recovery code.",
                 "Kubadilisha: Akaunti → Jina la mtumiaji na nenosiri. Umesahau? Kwenye ukurasa wa kuingia chagua \"Umesahau nenosiri\".", "/account#security"),
    "download": ("Account → **Delete account** tab → \"Download my figures (CSV)\". It downloads every month as a CSV you can open in Excel, without deleting anything.",
                 "Akaunti → kichupo cha **Futa akaunti** → \"Pakua takwimu zangu (CSV)\". Haifuti chochote.", "/account#delete"),
    "delete": ("Account → **Delete account**. Download your figures first if you want a copy. It erases your business, every month, your login and your contact details for good.",
               "Akaunti → **Futa akaunti**. Pakua takwimu zako kwanza ukitaka nakala.", "/account#delete"),
    "language": ("Press **Kiswahili** (or English) at the top of any page. I answer in the language you write in.",
                 "Bonyeza **Kiswahili** (au English) juu ya ukurasa. Ninajibu kwa lugha unayoandika.", None),
    "install": ("Yes, you can put Biashara Check on your phone or computer for free, straight from the browser (no Play Store needed). On Android in Chrome: menu (⋮) → **Install app**. On iPhone in Safari: Share → **Add to Home Screen**. On a computer: the install icon in Chrome or Edge's address bar. The **Get the app** page has an install button, the steps for each device and a QR code to open it on your phone.",
                "Ndiyo, unaweza kuweka Biashara Check kwenye simu au kompyuta bure, moja kwa moja kutoka kwa kivinjari. Android (Chrome): menyu (⋮) → **Install app**. iPhone (Safari): Share → **Add to Home Screen**. Ukurasa wa **Pata programu** una kitufe cha kusakinisha na hatua kwa kila kifaa.", "/install"),
    "reminders": ("Account → **Contact and messages**: switch the monthly report email, the reminder to add last month's figures, and risk alerts on or off.",
                  "Akaunti → **Mawasiliano na ujumbe**: washa au zima ripoti ya mwezi, ukumbusho na tahadhari za hatari.", "/account#notify"),
    "contact": ("Account → **Contact and messages** → Change email or mobile number (needs your password). You'll be asked to confirm the new one with a code.",
                "Akaunti → **Mawasiliano na ujumbe** → Badilisha barua pepe au simu.", "/account#contact"),
}


def howto(ctx: Ctx, topic: str) -> dict:
    en, sw, href = HOWTO_TEXT[topic]
    return _out(ctx, "howto:" + topic, ctx.T(en, sw), links=[{"label": ctx.T("Take me there", "Nipeleke huko"), "href": href}] if href else [])
