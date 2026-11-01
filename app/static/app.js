/* Biashara Check: owner dashboard. Plain JS, no libraries, for slow connections. */
const $ = (sel, root = document) => root.querySelector(sel);
const fmt = n => "KES " + Math.round(n).toLocaleString("en-KE");
const short = n => {
  const a = Math.abs(n), s = n < 0 ? "−" : "";
  if (a >= 1e6) return s + (a / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (a >= 1e3) return s + Math.round(a / 1e3) + "k";
  return s + Math.round(a);
};
const asDate = iso => new Date(iso.slice(0, 7) + "-01T00:00:00");
const monthName = iso => asDate(iso).toLocaleDateString("en-GB", { month: "short", year: "numeric" });
const monthOnly = iso => asDate(iso).toLocaleDateString("en-GB", { month: "long" });
const ym = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
const thisMonth = () => ym(new Date());
const addMonths = (iso, n) => { const d = asDate(iso); d.setMonth(d.getMonth() + n); return ym(d); };
const lastFullMonth = () => addMonths(thisMonth(), -1);  // the current month isn't finished yet
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

const state = { me: null, businesses: [], current: null, records: [], showAll: false, editing: null };

/* ---------- API ---------- */
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let body = null;
  try { body = await res.json(); } catch { /* empty body */ }
  if (res.status === 401) { location.href = "/login"; throw new Error("Please log in."); }
  if (!res.ok) throw apiError(res.status, body);
  return body;
}
const sendJSON = (path, method, payload) =>
  api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });

function apiError(status, body) {
  const d = body && body.detail;
  let message = "Something went wrong (error " + status + "). Try again in a moment.";
  let list = [];
  if (typeof d === "string") message = d;
  else if (Array.isArray(d)) {
    message = "Some values need fixing:";
    list = d.map(e => `${labelFor(e.loc?.[e.loc.length - 1])}: ${plain(e.msg)}`);
  } else if (d && d.message) { message = d.message; list = d.errors || []; }
  const err = new Error(message); err.list = list; err.fields = Array.isArray(d) ? d.map(e => e.loc?.[e.loc.length - 1]) : [];
  return err;
}
const LABELS = { month: "Month", revenue: "Total sales", cogs: "Cost of goods sold", operating_expenses: "Running expenses",
  cash_inflows: "Money received", cash_outflows: "Money paid out", mobile_money_receipts: "Received by M-Pesa",
  closing_stock: "Stock value", outstanding_debt: "Money you owe", transaction_count: "Number of sales" };
const labelFor = k => LABELS[k] || k;
const plain = m => m.replace("Input should be greater than or equal to 0", "can't be negative")
                    .replace(/Input should be a valid (number|integer).*/, "must be a number")
                    .replace(/^Value error, /, "");

function showMsg(el, kind, text, list = []) {
  el.className = "msg " + kind;
  el.textContent = text;
  if (list.length) {
    const ul = document.createElement("ul");
    list.slice(0, 12).forEach(t => { const li = document.createElement("li"); li.textContent = t; ul.append(li); });
    el.append(ul);
  }
}
function clearMsg(el) { el.className = "msg"; el.textContent = ""; }

let toastTimer;
function toast(text) {
  const t = $("#toast");
  t.textContent = text; t.hidden = false;
  requestAnimationFrame(() => t.classList.add("show"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.classList.remove("show"); setTimeout(() => { t.hidden = true; }, 250); }, 3500);
}

/* ---------- Businesses ---------- */
async function loadBusinesses(selectCode) {
  state.businesses = await api("/businesses");
  const sel = $("#business-select");
  sel.innerHTML = "";
  state.businesses.forEach(b => sel.add(new Option(b.code, b.code)));
  sel.parentElement.hidden = state.me.role !== "admin" || state.businesses.length < 2;
  if (!state.businesses.length) { $("#onboard").hidden = false; return; }
  const remembered = selectCode || store.get("business");
  const pick = state.businesses.find(b => b.code === remembered) || state.businesses[0];
  sel.value = pick.code;
  await openBusiness(pick.code);
}

async function openBusiness(code) {
  state.current = state.businesses.find(b => b.code === code);
  store.set("business", code);
  $("#onboard").hidden = true;
  $("#dash").hidden = false;
  $("#dash-title").textContent = code;
  exitEdit({ silent: true });
  await loadRecords();
}

async function loadRecords() {
  state.records = await api(`/businesses/${encodeURIComponent(state.current.code)}/records`);
  render();
  if (!state.editing) setMonth(nextMonthToAdd());
  loadModelRisk();
  loadFigures();
}

/* The trained model's risk, when there is one; the rule-based check stays otherwise */
// risk reasons come from the server in the chosen language, so fetch them again after a switch
document.addEventListener("languagechange", () => { if (state.current && state.records?.length >= 3) loadModelRisk(); });

async function loadModelRisk() {
  if (state.records.length < 3) return;
  const code = state.current.code;
  try {
    const r = await api(`/businesses/${encodeURIComponent(code)}/risk`);
    if (state.current.code !== code) return;
    state.risk = r;
    if (r.source === "model" && outlookMonths() === 3) renderModelRisk(r);
    renderDistress(r.distress);
    applyHorizon();
  } catch (err) { console.warn("Model risk unavailable", err); }
}

/* One layout for both checks: the score on the left (percentage, band meter, month-by-month dots),
   the verdict and the reasons on the right. Keeps the card short enough to see the figures below it. */
function riskCard({ band, pct, label, verdict, why, reasonsTitle, reasons, goodTitle, good, history, basis, caption }) {
  const el = $("#risk");
  el.className = "risk is-" + band;
  el.innerHTML = "";
  const top = document.createElement("div"); top.className = "risk-top";

  const score = document.createElement("div"); score.className = "risk-score";
  const h = document.createElement("h2"); h.textContent = label;
  const big = document.createElement("p"); big.className = "risk-pct";
  const num = document.createElement("b"); num.textContent = pct != null ? `${pct}%` : { low: "Low", mid: "Moderate", high: "High" }[band];
  const cap = document.createElement("span");
  cap.textContent = caption || (pct != null ? "chance of a loss month in the next 3 months" : "risk of a loss in the next 3 months");
  big.append(num, cap);
  const g = document.createElement("div"); g.className = "gauge"; g.setAttribute("aria-hidden", "true");
  [["low", "Low"], ["mid", "Moderate"], ["high", "High"]].forEach(([k, name]) => {
    const seg = document.createElement("span"); seg.className = "seg seg-" + k + (k === band ? " on" : "");
    const bar = document.createElement("i"); const t = document.createElement("span"); t.textContent = name;
    seg.append(bar, t); g.append(seg);
  });
  score.append(h, big, g);
  if (history && history.length > 1) score.append(riskTrend(history));

  const main = document.createElement("div"); main.className = "risk-main";
  const v = document.createElement("p"); v.className = "verdict"; v.textContent = verdict;
  const w = document.createElement("p"); w.className = "why"; w.textContent = why;
  main.append(v, w);
  if (reasons && reasons.length) {
    const sub = document.createElement("h3"); sub.className = "signs-h"; sub.textContent = reasonsTitle;
    const ol = document.createElement("ol"); ol.className = "signs";
    reasons.forEach(s => {
      const li = document.createElement("li");
      const t = document.createElement("p"); t.textContent = s.text; li.append(t);
      if (s.tip) { const tip = document.createElement("p"); tip.className = "tip-text"; tip.textContent = "What you can do: " + s.tip; li.append(tip); }
      ol.append(li);
    });
    main.append(sub, ol);
  }
  if (good && good.length) {
    const box = document.createElement("div"); box.className = "working";
    const gh = document.createElement("h3"); gh.className = "signs-h"; gh.textContent = goodTitle;
    const ul = document.createElement("ul");
    good.forEach(s => { const li = document.createElement("li"); li.textContent = s.text; ul.append(li); });
    box.append(gh, ul); main.append(box);
  }
  top.append(score, main);
  const b = document.createElement("p"); b.className = "basis"; b.textContent = basis;
  el.append(top, b);
}

function renderModelRisk(r) {
  const band = { Low: "low", Moderate: "mid", High: "high" }[r.band];
  const low = r.band === "Low";
  riskCard({
    band, pct: Math.round(r.probability * 100), label: "Your risk check",
    verdict: { High: "High risk of a loss in the next 3 months", Moderate: "Moderate risk of a loss in the next 3 months",
               Low: "Low risk of a loss in the next 3 months" }[r.band],
    why: `Based on your figures up to ${monthName(r.as_of)}.`,
    reasonsTitle: low ? "Worth keeping an eye on" : "The main reasons",
    reasons: low ? r.reasons.slice(0, 2) : r.reasons,
    goodTitle: low ? "What's keeping your risk low" : "What's working for you",
    good: low ? r.protective : r.protective.slice(0, 2),
    history: r.history,
    basis: `Machine-learning prediction by the ${r.model_name} model (${r.model_version}). Reasons come from SHAP: they show what moved your risk up or down. Decision support, not a guarantee.`,
  });
  const how = document.createElement("a"); how.href = "/how#risk"; how.className = "basis-link";
  how.textContent = "How the % is worked out, and how accurate it is";
  $("#risk .basis").append(" ", how);
}

/* ---------- Financial distress: the statistical (logistic regression) check ---------- */
const BAND_KEY = { Low: "low", Moderate: "mid", High: "high" };
function renderDistress(d) {
  const el = $("#distress");
  el.hidden = !d || state.records.length < 3;
  if (el.hidden) return;
  const band = BAND_KEY[d.band], p = Math.round(d.probability * 100);
  el.className = "card distress is-" + band;
  el.innerHTML = `
    <div class="ds-top">
      <div>
        <h2 id="ds-h">Financial distress check</h2>
        <p class="hint">Statistical model (logistic regression): the chance that over the next 3 months more money goes out than comes in, or your debt rises by more than half a month's sales.</p>
      </div>
      <p class="ds-score"><b></b><span></span></p>
    </div>
    <div class="ds-drivers"></div>
    <details class="ds-calc"><summary>See the full calculation</summary><div class="ds-calc-body"></div></details>
    <p class="basis">Figures up to <span class="ds-asof"></span>. <a href="/how#distress">How this model works and how well it tested</a></p>`;
  $(".ds-score b", el).textContent = p + "%";
  $(".ds-score span", el).textContent = { Low: "Low", Moderate: "Moderate", High: "High" }[d.band];
  $(".ds-asof", el).textContent = monthName(d.as_of);
  const drivers = $(".ds-drivers", el);
  [["Pushing the chance up", d.drivers_up], ["Keeping it down", d.drivers_down]].forEach(([title, list]) => {
    if (!list.length) return;
    const box = document.createElement("div");
    const h = document.createElement("h3"); h.className = "signs-h"; h.textContent = title;
    const ul = document.createElement("ul");
    list.forEach(t => {
      const li = document.createElement("li"); li.textContent = t.text;
      if (t.tip) { const tip = document.createElement("small"); tip.textContent = "What you can do: " + t.tip; li.append(tip); }
      ul.append(li);
    });
    box.append(h, ul); drivers.append(box);
  });
  // the whole sum, term by term, so the owner (or an examiner) can check it with a calculator
  const body = $(".ds-calc-body", el);
  const intro = document.createElement("p"); intro.className = "hint";
  intro.textContent = "Each figure is compared with the average business (z = (your value - average) / spread), multiplied by its weight from the model, and the results are added up. The total (the log-odds) is turned into a chance with 1 / (1 + e^(-total)).";
  const wrap = document.createElement("div"); wrap.className = "table-wrap";
  const t = document.createElement("table"); t.className = "ds-table";
  t.innerHTML = `<thead><tr><th scope="col">Figure</th><th scope="col">Yours</th><th scope="col">Average</th><th scope="col">z</th><th scope="col">Weight</th><th scope="col">Effect</th></tr></thead><tbody></tbody><tfoot></tfoot>`;
  const num = (x, dp = 2) => (x >= 0 ? "+" : "") + x.toFixed(dp);
  d.terms.forEach(x => {
    const tr = document.createElement("tr");
    [x.name, x.imputed ? "not recorded" : x.shown, x.average, num(x.z), num(x.coef, 3), num(x.contribution, 3)].forEach((v, i) => {
      const c = document.createElement(i ? "td" : "th"); if (!i) c.scope = "row"; c.textContent = v;
      if (i === 5) c.className = x.contribution > 0 ? "up" : x.contribution < 0 ? "down" : ""; tr.append(c);
    });
    $("tbody", t).append(tr);
  });
  const foot = [["Starting point (intercept)", num(d.intercept, 3)], ["Total (log-odds)", num(d.log_odds, 3)],
                ["Chance = 1 / (1 + e^(" + (-d.log_odds).toFixed(3) + "))", (d.probability * 100).toFixed(1) + "%"]];
  foot.forEach(([k, v]) => {
    const tr = document.createElement("tr"); const th = document.createElement("th"); th.scope = "row"; th.colSpan = 5; th.textContent = k;
    const td = document.createElement("td"); td.textContent = v; tr.append(th, td); $("tfoot", t).append(tr);
  });
  wrap.append(t); body.append(intro, wrap);
}

/* ---------- Look ahead 1 to 12 months: one choice drives the risk card and the month-by-month bars ---------- */
const BAND_WORD = { Low: "Low", Moderate: "Moderate", High: "High" };
const QUICK = [1, 3, 6, 9, 12];
function outlookMonths() { return Math.min(12, Math.max(1, Number(state.outlookMonths || state.me?.outlook_months || 3))); }
const plural = h => `${h} month${h === 1 ? "" : "s"}`;

function buildHorizonBar() {
  const chips = $("#hb-chips"), sel = $("#hb-select");
  chips.innerHTML = ""; sel.innerHTML = "";
  QUICK.forEach(h => {
    const b = document.createElement("button"); b.type = "button"; b.setAttribute("role", "radio"); b.dataset.h = h;
    b.textContent = plural(h);
    b.addEventListener("click", () => chooseOutlook(h));
    chips.append(b);
  });
  const last = state.records.length ? state.records[state.records.length - 1].month.slice(0, 7) : null;
  for (let h = 1; h <= 12; h++) {
    const o = document.createElement("option"); o.value = h;
    o.textContent = plural(h) + (last ? ` (to ${monthName(addMonths(last, h))})` : "");
    sel.append(o);
  }
}
function markHorizon(h) {
  $("#hb-chips").querySelectorAll("button").forEach(b => {
    const on = Number(b.dataset.h) === h; b.setAttribute("aria-checked", on); b.tabIndex = on || (!QUICK.includes(h) && b.dataset.h === "3") ? 0 : -1;
  });
  $("#hb-select").value = String(h);
}
function hbNote(text) { const n = $("#hb-note"); n.hidden = !text; n.textContent = text || ""; }

/* Called after the 3-month check has loaded, and whenever the owner picks a horizon */
async function applyHorizon(months) {
  const bar = $("#horizon-bar"), card = $("#outlook");
  const modelOn = state.risk && state.risk.source === "model";
  bar.hidden = state.records.length < 3;
  if (state.records.length < 3) { card.hidden = true; return; }
  const h = months || outlookMonths();
  state.outlookMonths = h;
  buildHorizonBar(); markHorizon(h);
  if (!modelOn) {
    card.hidden = true;
    hbNote(state.records.length < 3 ? "" : "Looking further than 3 months needs the trained risk model. Until then the check below covers the next 3 months.");
    return;
  }
  const code = state.current.code;
  let r;
  try { r = await api(`/businesses/${encodeURIComponent(code)}/outlook?months=${h}`); }
  catch (err) { console.warn("Outlook unavailable", err); r = { ready: false, reason: "error" }; }
  if (state.current.code !== code || state.outlookMonths !== h) return;
  if (!r.ready) {
    renderModelRisk(state.risk);                 // fall back to the 3-month check, and say why
    card.hidden = true;
    hbNote(h === 3 ? "" : r.reason === "no_model"
      ? (state.me.role === "admin"
          ? "Only 3 months is available: retrain the risk model (Admin → Risk model → Train the model) to switch on 1-12 months."
          : "Only 3 months is available until the study team updates the risk model. The check below covers the next 3 months.")
      : "The longer outlook isn't available right now. The check below covers the next 3 months.");
    return;
  }
  hbNote("");
  if (h === 3) renderModelRisk(state.risk); else renderHorizonRisk(r);
  renderOutlook(r);
}

/* The big risk card for a horizon other than 3 months */
function renderHorizonRisk(r) {
  const band = BAND_KEY[r.band], low = r.band === "Low", h = r.months;
  const from = monthName(addMonths(r.as_of, 1)), to = monthName(r.until);
  riskCard({
    band, pct: Math.round(r.probability * 100), label: `Your risk check: next ${plural(h)}`,
    caption: h === 1 ? `chance that ${to} is a loss month` : `chance of a loss month in the next ${plural(h)}`,
    verdict: `${BAND_WORD[r.band]} risk of a loss in the next ${plural(h)}`,
    why: h === 1 ? `Looking at ${to}, based on your figures up to ${monthName(r.as_of)}.`
                 : `Looking from ${from} to ${to}, based on your figures up to ${monthName(r.as_of)}.`,
    reasonsTitle: low ? "Worth keeping an eye on" : "The main reasons",
    reasons: low ? r.reasons.slice(0, 2) : r.reasons,
    goodTitle: low ? "What's keeping your risk low" : "What's working for you",
    good: low ? r.protective : r.protective.slice(0, 2),
    history: null,
    basis: `Machine-learning outlook for ${plural(h)} ahead (${r.model_version}), agreeing with the 3-month check. The further ahead, the less certain. Decision support, not a guarantee.`,
  });
  const how = document.createElement("a"); how.href = "/how#outlook"; how.className = "basis-link";
  how.textContent = "How the outlook works";
  $("#risk .basis").append(" ", how);
}

/* The month-by-month bars under the risk card */
function renderOutlook(r) {
  const card = $("#outlook");
  card.hidden = false;
  card.className = "card outlook is-" + BAND_KEY[r.band];
  const strip = $("#ol-strip"); strip.innerHTML = "";
  r.curve.forEach(c => {
    const li = document.createElement("li");
    const b = document.createElement("button"); b.type = "button";
    b.className = "ol-bar b-" + BAND_KEY[c.band] + (c.months === r.months ? " on" : "");
    b.setAttribute("aria-label", `By ${monthName(c.month)}: ${Math.round(c.probability * 100)}% (${c.band})`);
    b.setAttribute("aria-pressed", c.months === r.months);
    const fill = document.createElement("i"); fill.style.height = Math.max(3, Math.round(c.probability * 78)) + "%";
    const val = document.createElement("span"); val.className = "ol-val"; val.textContent = Math.round(c.probability * 100);
    const lab = document.createElement("span"); lab.className = "ol-mon"; lab.textContent = monthName(c.month).split(" ")[0];
    b.append(val, fill); li.append(b, lab);
    b.addEventListener("click", () => chooseOutlook(c.months));
    strip.append(li);
  });
  const ev = r.evidence, basis = $("#ol-basis");
  basis.textContent = "";
  if (ev && ev.enough) {
    const b = Object.fromEntries(ev.bands.map(x => [x.band, x]));
    const pctOf = x => x && x.actual != null ? Math.round(x.actual * 100) + "%" : "-";
    basis.append(`Predictions ${plural(r.months)} ahead were tested on ${ev.n.toLocaleString("en-KE")} later business-months: `
      + `${pctOf(b.High)} of those rated High had a loss, against ${pctOf(b.Low)} of those rated Low. `);
  } else if (ev) {
    basis.append(`Few test months reach ${plural(r.months)} ahead yet, so this horizon is less tested. `);
  }
  const a = document.createElement("a"); a.href = "/how#outlook"; a.textContent = "How the outlook works";
  basis.append(a);
}
function chooseOutlook(h) {
  h = Number(h);
  if (state.me) state.me.outlook_months = h;
  sendJSON("/auth/settings", "PUT", { outlook_months: h }).catch(() => {});   // remembered on the account
  applyHorizon(h);
}
$("#hb-select").addEventListener("change", e => chooseOutlook(e.target.value));
$("#hb-chips").addEventListener("keydown", e => {
  const d = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
  if (!d) return;
  e.preventDefault();
  const i = QUICK.indexOf(outlookMonths()), next = QUICK[(Math.max(0, i) + d + QUICK.length) % QUICK.length];
  chooseOutlook(next);
  setTimeout(() => $(`#hb-chips [data-h="${next}"]`)?.focus(), 0);
});

/* ---------- Business figures with formulas ---------- */
async function loadFigures() {
  const code = state.current.code;
  if (!state.records.length) { $("#figures-card").hidden = true; return; }
  try {
    const f = await api(`/businesses/${encodeURIComponent(code)}/figures`);
    if (state.current.code !== code) return;
    state.figures = f;
    renderFigures(f);
  } catch (err) { console.warn("Figures unavailable", err); }
}
function fmtValue(it) {
  if (it.value === null || it.value === undefined) return "-";
  if (it.unit === "kes") return fmt(it.value);
  if (it.unit === "pct") return (it.value * 100).toFixed(it.value !== 0 && Math.abs(it.value) < 0.1 ? 1 : 0) + "%";
  if (it.unit === "months") return it.value.toFixed(1) + " months";
  return String(it.value);
}
function renderFigures(f) {
  const card = $("#figures-card");
  card.hidden = !f.latest;
  if (!f.latest) return;
  const t = f.totals;
  $("#fg-sub").textContent = `${monthName(f.latest.month)}. Loss months so far: ${t.loss_months} of ${t.months}.`;
  // profit and cash, laid out like a simple statement
  const st = $("#fg-statements"); st.innerHTML = "";
  [["Profit and loss", f.statement.profit], ["Cash flow", f.statement.cash]].forEach(([title, rows]) => {
    const box = document.createElement("div"); box.className = "fg-stmt";
    const h = document.createElement("h3"); h.textContent = title;
    const dl = document.createElement("dl");
    rows.forEach(([label, v]) => {
      const row = document.createElement("div"); if (label.startsWith("=")) row.className = "total";
      const dt = document.createElement("dt"); dt.textContent = label.replace(/^[-=] /, "");
      if (label.startsWith("-")) dt.prepend(Object.assign(document.createElement("span"), { className: "op", textContent: "minus " }));
      const dd = document.createElement("dd"); dd.textContent = fmt(Math.abs(v) * (label.startsWith("-") ? 1 : Math.sign(v) || 1));
      if (label.startsWith("=") && v < 0) dd.className = "neg";
      row.append(dt, dd); dl.append(row);
    });
    box.append(h, dl); st.append(box);
  });
  // warnings from fixed business rules
  const ck = $("#fg-checks"); ck.innerHTML = "";
  if (f.checks.length) {
    const h = document.createElement("h3"); h.className = "fg-h3"; h.textContent = "Warnings from business rules";
    const ul = document.createElement("ul");
    f.checks.forEach(c => {
      const li = document.createElement("li"); li.className = "chk chk-" + c.level;
      const b = document.createElement("b"); b.textContent = c.title;
      const p = document.createElement("p"); p.textContent = c.text;
      const r = document.createElement("small"); r.textContent = "Rule: " + c.rule;
      li.append(b, p, r); ul.append(li);
    });
    ck.append(h, ul);
  }
  // every figure, each opening to its formula
  const ul = $("#fg-items"); ul.innerHTML = "";
  const SHOW = 6;
  f.items.forEach((it, i) => {
    const li = document.createElement("li"); li.className = "fg-item s-" + it.status;
    if (i >= SHOW && !state.allFigures) li.hidden = true;
    const d = document.createElement("details");
    const sm = document.createElement("summary");
    const name = document.createElement("span"); name.className = "fg-name"; name.textContent = it.name;
    const val = document.createElement("b"); val.textContent = fmtValue(it);
    if (typeof it.value === "number" && it.value < 0) val.className = "neg";
    const st = document.createElement("span"); st.className = "fg-dot";
    st.textContent = { good: "OK", watch: "Watch", bad: "Problem", none: "" }[it.status] || "";
    sm.append(name, st, val);
    const body = document.createElement("div"); body.className = "fg-how";
    [["Formula", it.formula], ["With your numbers", it.worked], ["What it means", it.meaning]].forEach(([k, v]) => {
      if (!v) return;
      const p = document.createElement("p"); const kk = document.createElement("span"); kk.textContent = k;
      p.append(kk, document.createTextNode(v)); if (k === "With your numbers") p.className = "worked"; body.append(p);
    });
    d.append(sm, body); li.append(d); ul.append(li);
  });
  const more = $("#fg-all");
  more.hidden = f.items.length <= SHOW;
  more.textContent = state.allFigures ? "Show fewer figures" : `Show all ${f.items.length} figures`;
  more.setAttribute("aria-expanded", !!state.allFigures);
}
$("#fg-all").addEventListener("click", () => { state.allFigures = !state.allFigures; renderFigures(state.figures); });

/* A small strip of past checks: one dot per month, coloured by band, with its month underneath */
function riskTrend(hist) {
  const box = document.createElement("div"); box.className = "risk-trend";
  const t = document.createElement("p"); t.className = "trend-h"; t.textContent = "Your risk check, month by month";
  const row = document.createElement("ol"); row.className = "trend-row";
  hist.slice(-12).forEach(h => {
    const li = document.createElement("li"); li.className = "t-" + h.band.toLowerCase();
    li.title = `${monthName(h.month)}: ${h.band} (${Math.round(h.probability * 100)}%)`;
    const dot = document.createElement("i"); dot.setAttribute("aria-hidden", "true");
    const m = document.createElement("span"); m.textContent = monthName(h.month).split(" ")[0];
    const sr = document.createElement("span"); sr.className = "sr"; sr.textContent = `${monthName(h.month)}: ${h.band}`;
    li.append(dot, m, sr); row.append(li);
  });
  box.append(t, row);
  return box;
}

/* ---------- Derived numbers ---------- */
const net = r => r.revenue - r.cogs - r.operating_expenses;
const sum = (arr, f) => arr.reduce((t, r) => t + f(r), 0);
const pct = (now, before) => before > 0 ? (now - before) / before * 100 : null;
const recordFor = month => state.records.find(r => r.month.slice(0, 7) === month);

/* Months missing between the first and last saved month, as [from, to] ranges */
function gaps(recs) {
  const out = [];
  for (let i = 1; i < recs.length; i++) {
    const expected = addMonths(recs[i - 1].month, 1), got = recs[i].month.slice(0, 7);
    if (got !== expected) out.push([expected, addMonths(got, -1)]);
  }
  return out;
}
const adjacent = (a, b) => addMonths(a.month, 1) === b.month.slice(0, 7);
const prevLabel = (prev, last) => adjacent(prev, last) ? monthOnly(prev.month) : monthName(prev.month);

function nextMonthToAdd() {
  const last = state.records[state.records.length - 1];
  if (!last) return lastFullMonth();
  const next = addMonths(last.month, 1);
  return next <= lastFullMonth() ? next : null;
}

/* Proposal 3.6 baseline: "next quarter repeats last quarter's sign".
   Warning signs come from the proposal 3.5 feature groups. Stand-in until the ML model is trained. */
function baselineRisk(recs) {
  if (recs.length < 3) return null;
  const last3 = recs.slice(-3), prev3 = recs.slice(-6, -3);
  const lastNet = sum(last3, net);
  const signs = [];
  if (prev3.length === 3) {
    const rg = pct(sum(last3, r => r.revenue), sum(prev3, r => r.revenue));
    const eg = pct(sum(last3, r => r.cogs + r.operating_expenses), sum(prev3, r => r.cogs + r.operating_expenses));
    if (rg !== null && eg !== null && eg - rg > 3)
      signs.push({ text: eg >= 0
                     ? `Costs grew ${eg.toFixed(0)}% while sales ${rg >= 0 ? "grew only" : "fell"} ${Math.abs(rg).toFixed(0)}% over the last 3 months.`
                     : `Sales fell ${Math.abs(rg).toFixed(0)}% but costs only fell ${Math.abs(eg).toFixed(0)}% over the last 3 months.`,
                   tip: "List your three biggest costs. Ask suppliers for a better price, or drop items that sell slowly." });
    const m1 = sum(last3, net) / Math.max(1, sum(last3, r => r.revenue)) * 100;
    const m0 = sum(prev3, net) / Math.max(1, sum(prev3, r => r.revenue)) * 100;
    if (m0 - m1 > 3)
      signs.push({ text: m1 < 0
                     ? `You now lose ${Math.abs(m1).toFixed(0)} shillings on every 100 of sales. Three months before, you ${m0 >= 0 ? `kept ${m0.toFixed(0)}` : `lost ${Math.abs(m0).toFixed(0)}`}.`
                     : `From every 100 shillings of sales you now keep ${m1.toFixed(0)}, down from ${m0.toFixed(0)}.`,
                   tip: "Check whether supplier prices went up while your selling prices stayed the same." });
    const d1 = last3[2].outstanding_debt, d0 = prev3[2].outstanding_debt;
    if (d1 > d0 * 1.2 && d1 - d0 > 5000)
      signs.push({ text: `Money you owe rose from ${fmt(d0)} to ${fmt(d1)}.`,
                   tip: "Plan repayments before taking more credit, and avoid buying slow stock on credit." });
  }
  const cash = sum(last3, r => r.cash_inflows - r.cash_outflows);
  if (cash < 0)
    signs.push({ text: `More cash went out than came in over the last 3 months (${fmt(cash)}).`,
                 tip: "Follow up money customers owe you, and hold off purchases that can wait." });

  let band = "low";
  if (lastNet < 0) band = "high";
  else if (signs.length >= 2) band = "mid";
  return { band, lastNet, signs };
}

/* ---------- Rendering ---------- */
function render() {
  const recs = state.records, has = recs.length > 0;
  $("#start").hidden = has;
  $("#risk").hidden = !has;
  $("#chart-card").hidden = !has;
  $("#records-card").hidden = !has;
  $("#stats").hidden = !has;
  renderHead(recs);
  if (!has) { $("#figures-card").hidden = true; $("#distress").hidden = true; $("#outlook").hidden = true; $("#horizon-bar").hidden = true; return; }
  renderRisk(recs);
  renderChart(recs);
  renderStats(recs);
  renderTable(recs);
}

function renderHead(recs) {
  const pr = state.me?.pro, pill = $("#pro-pill");
  pill.hidden = !(pr && pr.active);
  if (pr && pr.active) {
    const end = new Date(pr.until).toLocaleDateString("en-GB", { timeZone: "Africa/Nairobi", day: "numeric", month: "short", year: "numeric" });
    pill.textContent = `Biashara Pro until ${end} · ${pr.days_left} day${pr.days_left === 1 ? "" : "s"} left${pr.auto_renew ? " · renews automatically" : ""}`;
  }
  const sector = (state.sectors || {})[state.current.sector] || "Business";
  const last = recs[recs.length - 1];
  $("#dash-sub").textContent = last
    ? `${sector}. ${recs.length} month${recs.length === 1 ? "" : "s"} saved, latest ${monthName(last.month)}.`
    : `${sector}. No figures saved yet.`;
  const g = gaps(recs), note = $("#gap-note");
  note.hidden = !g.length;
  if (g.length) {
    const missing = g.reduce((t, [a, b]) => t + (asDate(b).getFullYear() - asDate(a).getFullYear()) * 12 + asDate(b).getMonth() - asDate(a).getMonth() + 1, 0);
    const [a, b] = g[0];
    const where = g.length === 1
      ? (a === b ? `${monthName(a)} is missing.` : `${monthName(a)} to ${monthName(b)} are missing.`)
      : `${missing} months are missing, the earliest ${a === b ? `is ${monthName(a)}` : `run from ${monthName(a)} to ${monthName(b)}`}.`;
    $("#gap-text").textContent = `${where} Your risk check and charts are more accurate with no gaps.`;
    $("#gap-btn").textContent = `Add ${monthName(a)}`;
    $("#gap-btn").dataset.month = a;
  }
  $("#report-btn").hidden = !last;
  const next = nextMonthToAdd(), btn = $("#next-month-btn");
  btn.hidden = !last || !next;
  if (next) { btn.textContent = `Add ${monthName(next)}`; btn.dataset.month = next; }
}

function renderRisk(recs) {
  const el = $("#risk");
  const r = baselineRisk(recs);
  if (!r) {
    el.className = "risk"; el.innerHTML = "";
    const need = 3 - recs.length;
    const h = document.createElement("h2"); h.textContent = "Your risk check";
    el.append(h);
    el.insertAdjacentHTML("beforeend", `<p class="verdict"></p><p class="why"></p>`);
    $(".verdict", el).textContent = `Add ${need} more month${need === 1 ? "" : "s"} to get your first check`;
    $(".why", el).textContent = "We compare your last 3 months with the 3 before them. 12 months or more gives the most reliable result.";
    return;
  }
  const text = {
    high: ["High risk of a loss in the next 3 months", "Your last 3 months added up to a loss. Unless something changes, the next 3 are likely to as well."],
    mid: ["Moderate risk: watch your costs", "You are still making a profit, but warning signs are building up."],
    low: ["Low risk of a loss in the next 3 months", "Your recent months are profitable and we see no strong warning signs."],
  }[r.band];
  riskCard({
    band: r.band, pct: null, label: "Your risk check",
    verdict: text[0], why: `${text[1]} Last 3 months combined: ${fmt(r.lastNet)}.`,
    reasonsTitle: "Warning signs", reasons: r.signs.slice(0, 3),
    basis: "Early check using a simple rule. The full AI prediction with its top 3 reasons will appear here once the model is trained.",
  });
}

/* Chart picker: the owner's choice is remembered on this device */
function chartView() {
  const v = store.get("chartView");
  return Charts.VIEWS[v] ? v : "profit";
}
function buildChartSwitch() {
  const box = $("#chart-switch");
  box.innerHTML = "";
  Object.entries(Charts.VIEWS).forEach(([key, v]) => {
    const b = document.createElement("button");
    b.type = "button"; b.setAttribute("role", "radio"); b.dataset.view = key; b.textContent = v.label;
    b.addEventListener("click", () => { store.set("chartView", key); renderChart(state.records); });
    box.append(b);
  });
  box.addEventListener("keydown", e => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const keys = Object.keys(Charts.VIEWS), i = keys.indexOf(chartView());
    const next = keys[(i + (e.key === "ArrowRight" ? 1 : keys.length - 1)) % keys.length];
    store.set("chartView", next); renderChart(state.records);
    box.querySelector(`[data-view="${next}"]`).focus();
  });
}
/* How to draw it (bar, line, area, pie, histogram, table), remembered per view, and for which months */
const MODE_ICONS = {
  bar: '<path d="M3 13h2V7H3zM7 13h2V3H7zM11 13h2V9h-2z"/>',
  line: '<path d="M2 12l4-5 3 3 5-7" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>',
  area: '<path d="M2 13V10l4-4 3 2 5-5v10z" opacity=".55"/><path d="M2 10l4-4 3 2 5-5" fill="none" stroke="currentColor" stroke-width="1.4"/>',
  pie: '<path d="M8 2a6 6 0 1 0 6 6H8z"/><path d="M9.5 0.8v5.7h5.7A5.7 5.7 0 0 0 9.5.8z" opacity=".55"/>',
  hist: '<path d="M2 13h3V9H2zM5.5 13h3V4h-3zM9 13h3V7H9zM12.5 13H15v-2h-2.5z"/>',
  table: '<path d="M2 3h12v10H2zM2 6.3h12M2 9.6h12M6 3v10" fill="none" stroke="currentColor" stroke-width="1.3"/>',
};
function chartMode(view) {
  const m = store.get("chartMode:" + view);
  return Charts.MODES[m] ? m : Charts.VIEWS[view].kind;
}
function chartPeriod() {
  const p = Number(store.get("chartPeriod"));
  return [6, 12, 0].includes(p) && store.get("chartPeriod") !== null ? p : 12;
}
function buildModeSwitch() {
  const box = $("#mode-switch");
  box.innerHTML = "";
  Object.entries(Charts.MODES).forEach(([key, m]) => {
    const b = document.createElement("button");
    b.type = "button"; b.setAttribute("role", "radio"); b.dataset.mode = key;
    b.innerHTML = `<svg viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">${MODE_ICONS[key]}</svg><span></span>`;
    b.querySelector("span").textContent = m.label;
    b.addEventListener("click", () => { store.set("chartMode:" + chartView(), key); renderChart(state.records); });
    box.append(b);
  });
  box.addEventListener("keydown", e => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const keys = Object.keys(Charts.MODES), i = keys.indexOf(chartMode(chartView()));
    const next = keys[(i + (e.key === "ArrowRight" ? 1 : keys.length - 1)) % keys.length];
    store.set("chartMode:" + chartView(), next); renderChart(state.records);
    box.querySelector(`[data-mode="${next}"]`).focus();
  });
  $("#chart-period").value = String(chartPeriod());
  $("#chart-period").addEventListener("change", e => { store.set("chartPeriod", e.target.value); renderChart(state.records); });
}
function renderChart(recs) {
  if (!recs.length) return;
  const key = chartView(), view = Charts.VIEWS[key], mode = chartMode(key), period = chartPeriod();
  $("#chart-switch").querySelectorAll("button").forEach(b => {
    const on = b.dataset.view === key;
    b.setAttribute("aria-checked", on); b.tabIndex = on ? 0 : -1;
  });
  $("#mode-switch").querySelectorAll("button").forEach(b => {
    const on = b.dataset.mode === mode;
    b.setAttribute("aria-checked", on); b.tabIndex = on ? 0 : -1;
  });
  const shown = period ? recs.slice(-period) : recs;
  $("#chart-period").value = String(period);
  // over-time charts say "each month"; a pie, histogram or table looks at the whole period
  $("#chart-title").textContent = ["pie", "hist", "table"].includes(mode) ? view.title.replace(/ each month$/, "") : view.title;
  $("#chart-hint").textContent = Charts.MODE_HINTS[mode] || view.hint;
  Charts.render($("#chart"), shown, key, mode);
}

/* Four tiles at the top of the dashboard, each compared with the month before */
function renderStats(recs) {
  const dl = $("#stats");
  dl.innerHTML = "";
  const last = recs[recs.length - 1], prev = recs[recs.length - 2];
  const tiles = [];
  const diffNote = (now, before) => {
    if (!prev) return "";
    const d = now - before;
    return d === 0 ? `Same as ${prevLabel(prev, last)}` : `${fmt(Math.abs(d))} ${d > 0 ? "more" : "less"} than ${prevLabel(prev, last)}`;
  };

  let salesNote = "";
  if (prev && prev.revenue) {
    const g = pct(last.revenue, prev.revenue);
    salesNote = Math.abs(g) < 0.5 ? `Same as ${prevLabel(prev, last)}` : `${g > 0 ? "Up" : "Down"} ${Math.abs(g).toFixed(0)}% on ${prevLabel(prev, last)}`;
  }
  tiles.push({ label: `Sales in ${monthOnly(last.month)}`, value: fmt(last.revenue), note: salesNote, noteBad: prev && last.revenue < prev.revenue });

  const gross = r => r.revenue - r.cogs;
  const gm = last.revenue > 0 ? ` (${Math.round(gross(last) / last.revenue * 100)}% of sales)` : "";
  tiles.push({ label: "Gross profit", value: fmt(gross(last)), bad: gross(last) < 0,
               note: `Sales minus cost of goods${gm}`, noteBad: false, plain: true });

  tiles.push({ label: `Profit in ${monthOnly(last.month)}`, value: fmt(net(last)), bad: net(last) < 0,
               note: diffNote(net(last), prev ? net(prev) : 0), noteBad: prev && net(last) < net(prev) });

  const cash = r => r.cash_inflows - r.cash_outflows;
  tiles.push({ label: "Cash left over", value: fmt(cash(last)), bad: cash(last) < 0,
               note: diffNote(cash(last), prev ? cash(prev) : 0), noteBad: prev && cash(last) < cash(prev) });

  tiles.forEach(t => {
    const d = document.createElement("div");
    const dt = document.createElement("dt"); dt.textContent = t.label;
    const dd = document.createElement("dd"); dd.textContent = t.value; if (t.bad) dd.className = "neg";
    d.append(dt, dd);
    if (t.note) { const n = document.createElement("p"); n.className = "delta" + (t.noteBad ? " down" : "") + (t.plain ? " plain" : ""); n.textContent = t.note; d.append(n); }
    dl.append(d);
  });
}

function renderTable(recs) {
  const tb = $("#records tbody");
  tb.innerHTML = "";
  $("#record-count").textContent = `${recs.length} month${recs.length === 1 ? "" : "s"}`;
  const rows = [...recs].reverse();
  const shown = state.showAll ? rows : rows.slice(0, 6);
  const more = $("#show-all");
  more.hidden = recs.length <= 6;
  more.textContent = state.showAll ? "Show latest 6 months" : `Show all ${recs.length} months`;
  more.setAttribute("aria-expanded", !!state.showAll);
  shown.forEach(r => {
    const tr = document.createElement("tr");
    if (state.editing === r.month.slice(0, 7)) tr.className = "editing";
    const th = document.createElement("th"); th.scope = "row"; th.textContent = monthName(r.month);
    const cells = [short(r.revenue), short(r.cogs + r.operating_expenses), fmt(net(r))];
    tr.append(th);
    cells.forEach((c, i) => { const td = document.createElement("td"); td.textContent = c; if (i === 2 && net(r) < 0) td.className = "neg"; tr.append(td); });
    const td = document.createElement("td"); td.className = "row-action";
    const b = document.createElement("button"); b.type = "button"; b.className = "link-btn"; b.textContent = "Edit";
    b.setAttribute("aria-label", `Edit ${monthName(r.month)}`);
    b.addEventListener("click", () => { enterEdit(r); $("#entry > .card").scrollIntoView({ behavior: "smooth", block: "start" }); });
    td.append(b); tr.append(td);
    tb.append(tr);
  });
}

/* ---------- Add / edit a month ---------- */
const form = $("#panel-month");
const moneyFields = ["revenue", "cogs", "operating_expenses", "cash_inflows", "cash_outflows",
                     "mobile_money_receipts", "closing_stock", "outstanding_debt", "transaction_count"];
const toNumber = v => v.replace(/[,\s]|KES|Ksh/gi, "");
const readNum = name => { const v = toNumber(form.elements[name].value.trim()); return v === "" ? null : Number(v); };
const pretty = n => Number(n).toLocaleString("en-KE", { maximumFractionDigits: 2 });

function setMonth(value) {
  const input = $("#r-month");
  input.max = lastFullMonth();
  if (value) input.value = value;
  checkMonth();
}

function checkMonth() {
  const note = $("#month-note"), v = $("#r-month").value;
  note.hidden = true; note.className = "month-note";
  if (!v || state.editing) return;
  if (v > lastFullMonth()) { note.hidden = false; note.classList.add("bad"); note.textContent = `That month hasn't finished yet. Add it once it's over. The latest you can add is ${monthName(lastFullMonth())}.`; return; }
  const rec = recordFor(v);
  if (rec) enterEdit(rec, { fromPicker: true });
}

function enterEdit(rec, { fromPicker = false } = {}) {
  state.editing = rec.month.slice(0, 7);
  selectTab("month");
  $("#entry-tabs").hidden = true;
  $("#edit-banner").hidden = false;
  $("#edit-title").textContent = `Editing ${monthName(rec.month)}`;
  $("#r-month").value = state.editing;
  $("#r-month").disabled = true;
  moneyFields.forEach(f => {
    const el = form.elements[f];
    el.value = el.required ? pretty(rec[f] ?? 0) : (rec[f] ? pretty(rec[f]) : "");  // blank optional zeros
  });
  $("#more-fields").open = !!(rec.closing_stock || rec.outstanding_debt || rec.transaction_count);
  $("#save-btn").textContent = "Save changes";
  $("#cancel-edit").hidden = false;
  $("#delete-month").hidden = false;
  disarmDelete();
  clearMsg($(".msg", form));
  if (fromPicker) showMsg($(".msg", form), "", `You already saved ${monthName(rec.month)}. Change the figures to update it, or choose Cancel.`);
  updateLive();
  renderTable(state.records);
  form.elements.revenue.focus({ preventScroll: true });
}

function exitEdit({ silent = false } = {}) {
  const wasEditing = !!state.editing;
  state.editing = null;
  form.reset();
  $("#entry-tabs").hidden = false;
  $("#edit-banner").hidden = true;
  $("#r-month").disabled = false;
  $("#save-btn").textContent = "Save month";
  $("#cancel-edit").hidden = true;
  $("#delete-month").hidden = true;
  $("#more-fields").open = false;
  disarmDelete();
  clearMsg($(".msg", form));
  updateLive();
  if (!silent) { setMonth(nextMonthToAdd()); if (wasEditing) renderTable(state.records); }
}

/* Live preview of this month's profit and cash, so mistakes show before saving */
function updateLive() {
  const rev = readNum("revenue"), cogs = readNum("cogs"), opex = readNum("operating_expenses");
  const cin = readNum("cash_inflows"), cout = readNum("cash_outflows");
  const showP = [rev, cogs, opex].every(v => v !== null && !isNaN(v));
  const showC = [cin, cout].every(v => v !== null && !isNaN(v));
  $("#live").hidden = !showP && !showC;
  const p = $("#live-profit"), c = $("#live-cash");
  p.parentElement.hidden = !showP; c.parentElement.hidden = !showC;
  if (showP) { const v = rev - cogs - opex; p.textContent = fmt(v); p.className = v < 0 ? "neg" : ""; }
  if (showC) { const v = cin - cout; c.textContent = fmt(v); c.className = v < 0 ? "neg" : ""; }
}

/* Figures that are possible but often typing mistakes */
function qualityFlags(p, month) {
  const n = k => Number(p[k] || 0), out = [];
  const rev = n("revenue"), cogs = n("cogs"), opex = n("operating_expenses"), cin = n("cash_inflows"), cout = n("cash_outflows");
  if (rev === 0) out.push("Total sales is 0. Was the business closed this month?");
  if (rev > 0 && cogs > rev * 1.5) out.push("Cost of goods sold is much higher than total sales. Check you didn't type stock bought instead.");
  if (rev > 0 && opex > rev * 1.5) out.push("Running expenses are much higher than total sales.");
  if (rev > 0 && cin > rev * 3) out.push("Money received is more than 3 times your sales. Did a loan or personal money come in?");
  if (n("mobile_money_receipts") > cin * 1.05 && cin > 0) out.push("Received by M-Pesa is more than all money received.");
  if (rev > 0 && cout > (cogs + opex) * 3 && cout > 0) out.push("Money paid out is more than 3 times your costs. Did you repay a loan or buy a lot of stock?");
  const prevMonth = (() => { const [y, m] = month.split("-").map(Number); return m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, "0")}`; })();
  const prev = recordFor(prevMonth);
  if (prev && prev.revenue > 0 && rev > 0) {
    const ratio = rev / prev.revenue;
    if (ratio > 3) out.push(`Sales are ${ratio.toFixed(1)} times last month's. Check for an extra zero.`);
    if (ratio < 0.3) out.push(`Sales are less than a third of last month's. Check for a missing zero.`);
  }
  return out;
}

form.addEventListener("input", e => {
  if (state.qualityOk) { state.qualityOk = null; $("#save-btn").textContent = state.editing ? "Save changes" : "Save month"; }
  if (e.target.name && moneyFields.includes(e.target.name)) { e.target.removeAttribute("aria-invalid"); updateLive(); }
});
form.addEventListener("focusout", e => {  // tidy numbers: 120000 -> 120,000
  const el = e.target;
  if (!moneyFields.includes(el.name) || !el.value.trim()) return;
  const n = Number(toNumber(el.value));
  if (isNaN(n)) { el.setAttribute("aria-invalid", "true"); return; }
  el.value = pretty(n);
});
$("#r-month").addEventListener("change", checkMonth);
$("#cancel-edit").addEventListener("click", () => exitEdit());

let deleteArmed = null;
function disarmDelete() { clearTimeout(deleteArmed); deleteArmed = null; const b = $("#delete-month"); b.textContent = "Delete this month"; b.classList.remove("armed"); }
$("#delete-month").addEventListener("click", async () => {
  const b = $("#delete-month"), month = state.editing;
  if (!deleteArmed) {
    b.textContent = `Yes, delete ${monthName(month)} for good`;
    b.classList.add("armed");
    deleteArmed = setTimeout(disarmDelete, 5000);
    return;
  }
  disarmDelete(); b.disabled = true;
  try {
    await api(`/businesses/${encodeURIComponent(state.current.code)}/records/${month}`, { method: "DELETE" });
    exitEdit({ silent: true });
    await loadRecords();
    toast(`Deleted ${monthName(month)}.`);
  } catch (err) { showMsg($(".msg", form), "err", err.message); }
  finally { b.disabled = false; }
});

form.addEventListener("submit", async e => {
  e.preventDefault();
  const msg = $(".msg", form), btn = $("#save-btn");
  form.querySelectorAll("[aria-invalid]").forEach(i => i.removeAttribute("aria-invalid"));
  const month = state.editing || $("#r-month").value;
  const payload = { month: month + "-01" }, missing = [], bad = [];
  if (!month) missing.push("Month");
  if (!state.editing && month > lastFullMonth()) { $("#r-month").setAttribute("aria-invalid", "true"); return showMsg(msg, "err", `That month hasn't finished yet. The latest you can add is ${monthName(lastFullMonth())}.`); }
  for (const name of moneyFields) {
    const input = form.elements[name], v = toNumber(input.value.trim());
    if (!v) { if (input.required) { missing.push(labelFor(name)); input.setAttribute("aria-invalid", "true"); } continue; }
    if (isNaN(Number(v))) { bad.push(labelFor(name)); input.setAttribute("aria-invalid", "true"); continue; }
    payload[name] = v;
  }
  if (missing.length) return showMsg(msg, "err", "Fill in: " + missing.join(", ") + ".");
  if (bad.length) return showMsg(msg, "err", "Use numbers only in: " + bad.join(", ") + ".");
  // Data-quality check: unusual figures are allowed, but the owner confirms them once
  const flags = qualityFlags(payload, month);
  const sig = JSON.stringify(payload);
  if (flags.length && state.qualityOk !== sig) {
    state.qualityOk = sig;
    showMsg(msg, "warn", "Please double-check these figures. If they're right, press Save anyway.", flags);
    btn.textContent = "Save anyway";
    return;
  }
  state.qualityOk = null;
  btn.textContent = state.editing ? "Save changes" : "Save month";
  btn.disabled = true;
  const base = `/businesses/${encodeURIComponent(state.current.code)}/records`;
  try {
    if (state.editing) {
      await sendJSON(`${base}/${state.editing}`, "PUT", payload);
      exitEdit({ silent: true });
      await loadRecords();
      toast(`Updated ${monthName(month)}.`);
    } else {
      await sendJSON(base, "POST", payload);
      form.reset(); clearMsg(msg); updateLive();
      await loadRecords();
      const next = nextMonthToAdd();
      toast(next ? `Saved ${monthName(month)}. Next: ${monthName(next)}.` : `Saved ${monthName(month)}. You're up to date.`);
      form.elements.revenue.focus({ preventScroll: true });
    }
  } catch (err) {
    err.fields.forEach(name => form.elements[name]?.setAttribute("aria-invalid", "true"));
    showMsg(msg, "err", err.message, err.list);
  } finally { btn.disabled = false; }
});

/* ---------- Reports dialog ---------- */
const REPORTS = {
  monthly: { path: "report.pdf", name: "Monthly-report", pro: false },
  business: { path: "business-report.pdf", name: "Business-report", pro: true },
  loan: { path: "loan-report.pdf", name: "Summary-for-lenders", pro: true },
};
function openReports() {
  const dlg = $("#report-dlg");
  const pro = state.me.role === "admin" || !!state.me.pro?.active;
  const n = state.records.length;
  $("#rd-lock").hidden = pro;
  dlg.querySelectorAll(".rd-pro").forEach(sec => sec.classList.toggle("locked", !pro));
  dlg.querySelector('[data-report="business"]').disabled = !pro || n < 2;
  dlg.querySelector('[data-report="loan"]').disabled = !pro || n < 6;
  dlg.querySelectorAll(".rd-period input").forEach(i => { i.disabled = !pro; });
  const c = state.me.contact, mailOk = !!(c && c.email_verified);
  $("#rd-email").textContent = mailOk ? c.email : "your email once you confirm it";
  dlg.querySelectorAll("[data-email]").forEach(b => {
    const k = b.dataset.email;
    b.disabled = !mailOk || (k !== "monthly" && !pro) || (k === "business" && n < 2) || (k === "loan" && n < 6);
    b.title = mailOk ? "" : "Confirm your email on the Account page first";
  });
  clearMsg($("#rd-msg"));
  dlg.showModal();
}
async function downloadReport(kind, btn) {
  const r = REPORTS[kind], msg = $("#rd-msg");
  let url = `/businesses/${encodeURIComponent(state.current.code)}/${r.path}`;
  if (kind === "business") url += `?months=${document.querySelector("input[name=rd-months]:checked").value}`;
  const old = btn.textContent; btn.disabled = true; btn.textContent = "Preparing…"; clearMsg(msg);
  try {
    const res = await fetch(url, { credentials: "same-origin" });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      throw new Error(typeof j.detail === "string" ? j.detail : `Couldn't make the report (error ${res.status}).`);
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${r.name}-${state.current.code}-${new Date().toISOString().slice(0, 10)}.pdf`;
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    showMsg(msg, "ok", "Your report is downloading.");
  } catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.textContent = old; btn.disabled = false; }
}
$("#report-btn").addEventListener("click", openReports);
$("#rd-close").addEventListener("click", () => $("#report-dlg").close());
$("#report-dlg").addEventListener("click", e => { if (e.target === e.currentTarget) e.currentTarget.close(); });
$("#report-dlg").querySelectorAll("[data-report]").forEach(b => b.addEventListener("click", () => downloadReport(b.dataset.report, b)));
async function emailReport(kind, btn) {
  const msg = $("#rd-msg"), old = btn.textContent;
  const months = Number(document.querySelector("input[name=rd-months]:checked").value);
  btn.disabled = true; btn.textContent = "Sending…"; clearMsg(msg);
  try {
    const r = await sendJSON(`/businesses/${encodeURIComponent(state.current.code)}/reports/email`, "POST", { kind, months });
    showMsg(msg, "ok", r.mode === "live" ? `Sent to ${r.sent_to}. It can take a minute to arrive; check spam if you can't see it.`
                                         : `Email isn't set up on this server yet, so the email was printed in the server window instead of sent.`);
  } catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.textContent = old; btn.disabled = false; }
}
$("#report-dlg").querySelectorAll("[data-email]").forEach(b => b.addEventListener("click", () => emailReport(b.dataset.email, b)));

/* ---------- Wrong tab? A records file in the M-Pesa tab, or a statement in the CSV tab ---------- */
async function fileKind(file) {
  if (/\.pdf$/i.test(file.name)) return "statement";
  const head = (await file.slice(0, 4000).text()).toLowerCase();
  if (/paid\s*in/.test(head) && /receipt|completion/.test(head)) return "statement";
  if (/\brevenue\b/.test(head) && /\bcogs\b/.test(head)) return "records";
  return "unknown";
}
/* Offers to move the file to the right tab, with one button */
function wrongTab(msg, text, label, target, file) {
  showMsg(msg, "err", text);
  const b = document.createElement("button");
  b.type = "button"; b.className = "btn ghost small wrong-tab-btn"; b.textContent = label;
  b.addEventListener("click", () => {
    const input = target === "csv" ? $("#csv-file") : $("#mp-file");
    try { const dt = new DataTransfer(); dt.items.add(file); input.files = dt.files; } catch { /* old browser: choose again */ }
    input.dispatchEvent(new Event("change"));
    clearMsg(msg);
    selectTab(target);
    if (target === "mpesa" && !$("#mpesa-form").hidden && input.files.length && !/\.pdf$/i.test(file.name)) $("#mpesa-form").requestSubmit();
    else if (target === "csv" && input.files.length) { /* the file's change event reads it */ }
    else input.focus();
  });
  msg.append(document.createElement("br"), b);
}

/* ---------- Any spreadsheet: read it, show how it was understood, then import ---------- */
const IMPORT_FIELDS = [
  ["month", "Month"], ["revenue", "Total sales"], ["cogs", "Cost of goods sold"], ["operating_expenses", "Running expenses"],
  ["cash_inflows", "Money received"], ["cash_outflows", "Money paid out"], ["mobile_money_receipts", "Received by M-Pesa"],
  ["closing_stock", "Stock value"], ["outstanding_debt", "Money owed"], ["transaction_count", "Number of sales"],
  ["total_costs", "Total costs (if not split)"], ["profit", "Profit (if no costs)"],
];
const imp = { file: null, mapping: {}, last: null };
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

async function importPreview() {
  const f = $("#panel-csv"), msg = $(".msg", f), box = $("#import-review"), btn = $("#imp-read");
  if (!imp.file) return showMsg(msg, "err", "Choose your file first.");
  if (await fileKind(imp.file) === "statement")
    return wrongTab(msg, "This looks like an M-Pesa statement, not your monthly records. Statements go in the M-Pesa tab.",
                    "Open it in the M-Pesa tab", "mpesa", imp.file);
  const data = new FormData(); data.append("file", imp.file); data.append("mapping", JSON.stringify(imp.mapping));
  btn.disabled = true; btn.textContent = "Reading…"; clearMsg(msg);
  try {
    const r = await api(`/businesses/${encodeURIComponent(state.current.code)}/import/preview`, { method: "POST", body: data });
    imp.last = r;
    renderReview(r);
  } catch (err) { box.hidden = true; showMsg(msg, "err", err.message); }
  finally { btn.disabled = false; btn.textContent = "Read my file"; }
}

function renderReview(r) {
  const box = $("#import-review"), msg = $("#panel-csv .msg");
  box.innerHTML = ""; box.hidden = false;
  if (r.status === "mpesa") { box.hidden = true; return wrongTab(msg, r.message, "Open it in the M-Pesa tab", "mpesa", imp.file); }
  if (r.status === "error") { box.hidden = true; return showMsg(msg, "err", r.message); }

  // several businesses in one file: which one is yours?
  if (r.status === "choose_business") {
    box.append(el("p", "imp-q", "This file has figures for several businesses. Which one is yours?"));
    const sel = el("select"); sel.append(new Option("Choose…", ""));
    r.businesses.forEach(b => sel.append(new Option(b, b)));
    sel.addEventListener("change", () => { if (sel.value) { imp.mapping.business_column = r.business_column; imp.mapping.business_value = sel.value; importPreview(); } });
    box.append(sel);
    return;
  }

  const recs = r.records || [], fresh = recs.filter(x => !x.saved);
  // summary
  const sum = el("div", "imp-summary " + (recs.length ? "good" : "need"));
  if (recs.length) {
    sum.append(el("b", "", `We found ${recs.length} month${recs.length === 1 ? "" : "s"}, ${monthName(recs[0].month)} to ${monthName(recs[recs.length - 1].month)}.`));
    sum.append(el("span", "", fresh.length === recs.length ? " All of them are new."
      : fresh.length ? ` ${fresh.length} are new; ${recs.length - fresh.length} you already saved will stay as they are.`
      : " You've already saved all of them, so nothing would change."));
  } else if (r.status === "need_start") {
    sum.append(el("b", "", "Your file has figures but no dates."));
    sum.append(el("span", "", " Tell us which month the first row is, or choose the column that holds the dates."));
  } else {
    sum.append(el("b", "", "Almost there."));
    sum.append(el("span", "", " " + (r.message || "Choose which column has your sales.")));
  }
  box.append(sum);

  if (r.status === "need_start" || imp.mapping.start_month) {
    const row = el("label", "imp-start");
    row.append(el("span", "", "First row is the month of"));
    const inp = el("input"); inp.type = "month"; inp.max = lastFullMonth().slice(0, 7); inp.value = imp.mapping.start_month || "";
    inp.addEventListener("change", () => { if (inp.value) { imp.mapping.start_month = inp.value; importPreview(); } });
    row.append(inp); box.append(row);
  }

  // how we read the file
  if (r.notes && r.notes.length) {
    const d = el("details", "imp-notes"); d.open = recs.length > 0 && recs.length <= 60;
    d.append(el("summary", "", `How we read your file (${r.notes.length})`));
    const ul = el("ul"); r.notes.forEach(n => ul.append(el("li", "", n))); d.append(ul); box.append(d);
  }

  // which column is which: change any of them
  const map = el("details", "imp-map");
  map.open = r.status !== "ok" || IMPORT_FIELDS.some(([k]) => k in imp.mapping);  // stay open while the owner is adjusting
  map.append(el("summary", "", r.status === "ok" ? "Check which column is which" : "Which column is which?"));
  const grid = el("div", "imp-grid");
  const cols = r.columns || [];
  IMPORT_FIELDS.forEach(([key, label]) => {
    const cur = r.mapping[key];
    const lab = el("label", "imp-field" + (["revenue"].includes(key) && !cur ? " missing" : ""));
    lab.append(el("span", "", label + (key === "revenue" ? " *" : "")));
    const sel = el("select"); sel.dataset.key = key;
    sel.append(new Option(key === "month" ? "No dates in my file" : "Not in my file", ""));
    if (Array.isArray(cur)) sel.append(new Option(`${cur.length} columns added up`, "__multi__"));
    cols.forEach(c => sel.append(new Option(c.sample.length ? `${c.name}  (e.g. ${c.sample[0]})` : c.name, c.name)));
    sel.value = Array.isArray(cur) ? "__multi__" : (cur || "");
    sel.addEventListener("change", () => {
      if (sel.value === "__multi__") return;
      imp.mapping[key] = sel.value;
      if (key === "month" && sel.value) delete imp.mapping.start_month;
      importPreview();
    });
    lab.append(sel); grid.append(lab);
  });
  map.append(grid);
  map.append(el("p", "hint", "Change a box and we read the file again straight away. Nothing is saved until you press Import."));
  box.append(map);

  // what will be saved
  if (recs.length) {
    const wrap = el("div", "table-wrap imp-table");
    const t = el("table"); const head = el("tr");
    ["Month", "Sales", "Costs", "Profit", ""].forEach((h, k) => head.append(el("th", k && k < 4 ? "num" : "", h)));
    const thead = el("thead"); thead.append(head); t.append(thead);
    const tb = el("tbody");
    recs.slice().reverse().slice(0, 12).forEach(x => {
      const tr = el("tr"); const costs = (x.cogs || 0) + (x.operating_expenses || 0), p = x.revenue - costs;
      const n = v => Math.round(v).toLocaleString("en-KE");
      tr.append(el("td", "", monthName(x.month)), el("td", "num", n(x.revenue)), el("td", "num", n(costs)));
      tr.append(el("td", "num" + (p < 0 ? " neg" : ""), n(p)));
      tr.append(el("td", "imp-tag " + (x.saved ? "old" : "new"), x.saved ? "Already saved" : "New"));
      tb.append(tr);
    });
    t.append(tb); wrap.append(t); box.append(wrap);
    if (recs.length > 12) box.append(el("p", "hint", `…and ${recs.length - 12} earlier month${recs.length - 12 === 1 ? "" : "s"}.`));
  }
  if (r.skipped_count) {
    const d = el("details", "imp-skipped");
    d.append(el("summary", "", `${r.skipped_count} row${r.skipped_count === 1 ? "" : "s"} left out`));
    const ul = el("ul"); r.skipped.slice(0, 30).forEach(sk => ul.append(el("li", "", `Row ${sk.row}: ${sk.reason}`)));
    d.append(ul); box.append(d);
  }

  if (recs.length) box.append(el("p", "hint", "Amounts in KES."));
  const saved = recs.length - fresh.length;
  let replace = null;
  if (saved) {
    const lab = el("label", "consent imp-replace");
    replace = el("input"); replace.type = "checkbox"; replace.checked = !!imp.replace;
    lab.append(replace, el("span", "", `Also update the ${saved} month${saved === 1 ? "" : "s"} I already saved with the figures in this file`));
    box.append(lab);
  }
  const actions = el("div", "imp-actions");
  const go = el("button", "btn primary", "");
  const label = () => {
    const n = fresh.length + (replace && replace.checked ? saved : 0);
    go.textContent = n ? `Import ${n} month${n === 1 ? "" : "s"}` : "Nothing new to import";
    go.disabled = !n;
  };
  if (replace) replace.addEventListener("change", () => { imp.replace = replace.checked; label(); });
  label();
  go.type = "button";
  go.addEventListener("click", () => importNow(go));
  const again = el("button", "btn ghost", "Choose another file"); again.type = "button";
  again.addEventListener("click", resetImport);
  actions.append(go, again); box.append(actions);
}

async function importNow(btn) {
  const msg = $("#panel-csv .msg");
  const data = new FormData(); data.append("file", imp.file); data.append("mapping", JSON.stringify(imp.mapping));
  if (imp.replace) data.append("replace", "1");
  btn.disabled = true; btn.textContent = "Importing…";
  try {
    const r = await api(`/businesses/${encodeURIComponent(state.current.code)}/import`, { method: "POST", body: data });
    resetImport();
    const parts = [];
    if (r.inserted) parts.push(`Added ${r.inserted} month${r.inserted === 1 ? "" : "s"}, ${monthName(r.first_month)} to ${monthName(r.last_month)}.`);
    if (r.updated) parts.push(`Updated ${r.updated} month${r.updated === 1 ? "" : "s"} you had already saved.`);
    else if (r.skipped_existing) parts.push(`${r.skipped_existing} month${r.skipped_existing === 1 ? "" : "s"} you had already saved stayed as they were.`);
    if (r.problems.length) parts.push(`Left out: ${r.problems.join("; ")}.`);
    showMsg(msg, r.inserted || r.updated ? "ok" : "", parts.join(" ") || "Nothing new was added.");
    await loadRecords();
    if (r.inserted || r.updated) toast(`Saved ${r.inserted + r.updated} month${r.inserted + r.updated === 1 ? "" : "s"}.`);
  } catch (err) { btn.disabled = false; btn.textContent = "Try again"; showMsg(msg, "err", err.message); }
}
function resetImport() {
  imp.file = null; imp.mapping = {}; imp.last = null; imp.replace = false;
  $("#csv-file").value = ""; $("#import-review").hidden = true; $("#import-review").innerHTML = "";
}
$("#csv-file").addEventListener("change", e => {
  imp.file = e.target.files[0] || null; imp.mapping = {};
  if (imp.file) importPreview(); else resetImport();
});
$("#panel-csv").addEventListener("submit", e => {
  e.preventDefault();
  if (!imp.file) imp.file = $("#csv-file").files[0] || null;
  importPreview();
});

/* ---------- M-Pesa statement (Biashara Pro) ---------- */
const kes = n => "KES " + Number(n).toLocaleString("en-KE", { maximumFractionDigits: 0 });
let mpMonths = [];
function renderMpesaAccess() {
  const open = state.me.role === "admin" || !!state.me.pro?.active;
  $("#mpesa-locked").hidden = open;
  $("#mpesa-form").hidden = !open;
  $("#mpesa-result").hidden = true;
}
$("#mp-file").addEventListener("change", e => {
  const f = e.target.files[0];
  $("#mp-pass-field").hidden = !(f && /\.pdf$/i.test(f.name));
});
$("#mpesa-form").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target, msg = $(".msg", f), btn = $("button[type=submit]", f), file = $("#mp-file").files[0];
  if (!file) return showMsg(msg, "err", "Choose your statement first.");
  if (await fileKind(file) === "records")
    return wrongTab(msg, "This is a monthly records file (sales and costs per month), not an M-Pesa statement.",
                    "Upload it as monthly records", "csv", file);
  const data = new FormData(); data.append("file", file); data.append("password", $("#mp-pass").value);
  btn.disabled = true; btn.textContent = "Reading…"; clearMsg(msg);
  try {
    const r = await api(`/businesses/${encodeURIComponent(state.current.code)}/mpesa-statement`, { method: "POST", body: data });
    $("#mp-pass").value = "";
    showMpesa(r);
  } catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.disabled = false; btn.textContent = "Read statement"; }
});
function showMpesa(r) {
  mpMonths = r.months;
  $("#mpesa-form").hidden = true;
  $("#mpesa-result").hidden = false;
  clearMsg($("#mp-msg"));
  const day = iso => new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  $("#mp-summary").textContent = `${r.transactions} completed transactions, ${day(r.from)} to ${day(r.to)}.`
    + (r.skipped ? ` ${r.skipped} line${r.skipped === 1 ? "" : "s"} couldn't be read and were left out.` : "");
  const tb = $("#mp-table tbody"); tb.innerHTML = "";
  r.months.forEach((m, i) => {
    const tr = document.createElement("tr");
    const tdc = document.createElement("td");
    const cb = document.createElement("input"); cb.type = "checkbox"; cb.dataset.i = i; cb.id = "mp-" + i;
    cb.checked = m.usable && m.saved && !m.note; cb.disabled = !m.usable || !m.saved;
    cb.setAttribute("aria-label", "Update " + monthName(m.month));
    tdc.append(cb); tr.append(tdc);
    const tdm = document.createElement("td");
    const lab = document.createElement("label"); lab.htmlFor = cb.id; lab.textContent = monthName(m.month); tdm.append(lab);
    const sub = document.createElement("small"); sub.className = "mp-note";
    if (!m.usable) sub.textContent = m.note;
    else if (!m.saved) {
      sub.textContent = "Not saved yet. ";
      const add = document.createElement("button"); add.type = "button"; add.className = "link-btn inline"; add.textContent = "Add this month";
      add.addEventListener("click", () => prefillFromMpesa(m)); sub.append(add);
    } else if (m.note) sub.textContent = m.note + ". Tick it only if that's right.";
    else sub.textContent = "Saved: will update";
    tdm.append(sub); tr.append(tdm);
    const rec = document.createElement("td"); rec.className = "num"; rec.textContent = kes(m.received); tr.append(rec);
    const cnt = document.createElement("td"); cnt.className = "num"; cnt.textContent = m.count_in.toLocaleString("en-KE"); tr.append(cnt);
    tb.append(tr);
  });
  updateApplyBtn();
}
function updateApplyBtn() {
  const n = $("#mp-table").querySelectorAll("input:checked").length;
  $("#mp-apply").disabled = !n;
  $("#mp-apply").textContent = n ? `Update ${n} month${n === 1 ? "" : "s"}` : "Tick the months to update";
}
$("#mp-table").addEventListener("change", updateApplyBtn);
function prefillFromMpesa(m) {
  goToEntry("month");
  setMonth(m.month);
  form.elements.mobile_money_receipts.value = pretty(m.received);
  form.elements.transaction_count.value = m.count_in;
  $("#more-fields").open = true;
  updateLive();
  showMsg($(".msg", form), "", `M-Pesa figures for ${monthName(m.month)} filled in from your statement. Add the rest, then save.`);
}
$("#mp-apply").addEventListener("click", async () => {
  const picked = [...$("#mp-table").querySelectorAll("input:checked")].map(cb => mpMonths[+cb.dataset.i])
    .map(m => ({ month: m.month, received: m.received, count: m.count_in }));
  const btn = $("#mp-apply"); btn.disabled = true;
  try {
    const r = await sendJSON(`/businesses/${encodeURIComponent(state.current.code)}/mpesa-statement/apply`, "POST", { months: picked });
    showMsg($("#mp-msg"), "ok", `Updated ${r.updated.length} month${r.updated.length === 1 ? "" : "s"}: ${r.updated.map(monthName).join(", ")}.`);
    await loadRecords();
    toast("M-Pesa figures updated.");
    $("#mp-table").querySelectorAll("input:checked").forEach(cb => { cb.checked = false; });
    updateApplyBtn();
  } catch (err) { showMsg($("#mp-msg"), "err", err.message); btn.disabled = false; }
});
$("#mp-again").addEventListener("click", () => { $("#mpesa-form").reset(); $("#mp-pass-field").hidden = true; renderMpesaAccess(); });

/* ---------- Tabs, buttons ---------- */
function selectTab(which) {
  ["month", "csv", "mpesa"].forEach(t => {
    const on = t === which;
    $("#tab-" + t).setAttribute("aria-selected", on);
    $("#tab-" + t).tabIndex = on ? 0 : -1;
    $("#panel-" + t).hidden = !on;
  });
}
$("#tab-month").addEventListener("click", () => selectTab("month"));
$("#tab-csv").addEventListener("click", () => selectTab("csv"));
$("#tab-mpesa").addEventListener("click", () => selectTab("mpesa"));
$("#entry-tabs").addEventListener("keydown", e => {
  if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
    const tabs = ["month", "csv", "mpesa"];
    const i = tabs.findIndex(t => $("#tab-" + t).getAttribute("aria-selected") === "true");
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    selectTab(next); $("#tab-" + next).focus();
  }
});
function goToEntry(tab) {
  if (state.editing) exitEdit();
  selectTab(tab);
  $("#entry > .card").scrollIntoView({ behavior: "smooth", block: "start" });
  (tab === "month" ? form.elements.revenue : $("#csv-file")).focus({ preventScroll: true });
}
$("#start-type").addEventListener("click", () => goToEntry("month"));
$("#start-upload").addEventListener("click", () => goToEntry("csv"));
$("#gap-btn").addEventListener("click", e => { goToEntry("month"); setMonth(e.currentTarget.dataset.month); });
$("#next-month-btn").addEventListener("click", e => { goToEntry("month"); setMonth(e.currentTarget.dataset.month); });
$("#business-select").addEventListener("change", e => openBusiness(e.target.value));
$("#logout").addEventListener("click", async () => {
  try { await fetch("/auth/logout", { method: "POST" }); } finally { location.href = "/login"; }
});
$("#show-all").addEventListener("click", () => { state.showAll = !state.showAll; renderTable(state.records); });
let resizeTimer;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => renderChart(state.records), 150); });

/* Email confirmation and missing-contact banners */
function renderContactNotes() {
  const c = state.me.contact, o = state.options || {};
  const smsOffered = o.sms && (o.sms !== "console" || o.email === "console");
  $("#contact-note").hidden = !!c;
  $("#verify-note").hidden = !c || c.email_verified;
  if (c && !c.email_verified) $("#verify-email").textContent = c.email;
  const later = store.get("phoneLater") === state.me.username;
  $("#phone-note").hidden = !c || !c.email_verified || c.phone_verified || !smsOffered || later;
  if (c) $("#phone-to").textContent = c.phone;
}
$("#phone-send").addEventListener("click", async e => {
  const msg = $("#phone-note .msg"), btn = e.currentTarget;
  btn.disabled = true;
  try {
    const r = await sendJSON("/auth/phone/send-code", "POST", {});
    $("#phone-code-wrap").hidden = false;
    btn.textContent = "Send again";
    showMsg(msg, "ok", r.mode === "sandbox" ? "Sent to the Africa's Talking sandbox. Open the simulator to see it."
                       : r.mode === "console" ? "Test mode: the code is printed in the server window."
                       : "Code sent. It can take a minute to arrive.");
    $("#phone-code").focus();
  } catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.disabled = false; }
});
$("#phone-note").addEventListener("submit", async e => {
  e.preventDefault();
  const msg = $("#phone-note .msg"), code = $("#phone-code").value.replace(/\s/g, "");
  if (!/^\d{6}$/.test(code)) return showMsg(msg, "err", "Enter the 6-digit code from the SMS.");
  try {
    state.me = await sendJSON("/auth/phone/verify", "POST", { code });
    renderContactNotes();
    toast("Mobile number confirmed.");
  } catch (err) { showMsg(msg, "err", err.message); }
});
$("#phone-later").addEventListener("click", () => { store.set("phoneLater", state.me.username); renderContactNotes(); });
$("#verify-note").addEventListener("submit", async e => {
  e.preventDefault();
  const msg = $("#verify-note .msg"), code = $("#verify-code").value.replace(/\s/g, "");
  if (!/^\d{6}$/.test(code)) return showMsg(msg, "err", "Enter the 6-digit code from the email.");
  try {
    state.me = await sendJSON("/auth/email/verify", "POST", { code });
    renderContactNotes();
    toast("Email confirmed. Thank you.");
  } catch (err) { showMsg(msg, "err", err.message); }
});
$("#verify-resend").addEventListener("click", async () => {
  const msg = $("#verify-note .msg");
  try { await sendJSON("/auth/email/send-code", "POST", {}); showMsg(msg, "ok", "New code sent. It expires in 15 minutes."); }
  catch (err) { showMsg(msg, "err", err.message); }
});

async function start() {
  buildChartSwitch();
  buildModeSwitch();
  let sectorList;
  [state.me, state.options, sectorList] = await Promise.all([api("/auth/me"), fetch("/auth/options").then(r => r.json()).catch(() => ({})),
    fetch("/sectors").then(r => r.json()).catch(() => [])]);
  state.sectors = Object.fromEntries(sectorList.map(s => [s.id, s.label]));
  window.I18N?.sync(state.me.language);
  if (state.me.must_change_password) { location.href = "/account"; return; }
  const isAdmin = state.me.role === "admin";
  $("#admin-link").hidden = !isAdmin;
  renderContactNotes();
  renderMpesaAccess();
  const wanted = new URLSearchParams(location.search).get("business");
  await loadBusinesses(isAdmin ? wanted : null);
  $("#loading").hidden = true;
  if (state.me.show_tour) openTour();
  feedbackNudge();
  if (location.hash) dashHash(location.hash);
}

/* Links such as /#entry, /#upload, /#mpesa, /#reports, /#figures-card (from the assistant or another page)
   open the right part of the dashboard */
function dashHash(hash) {
  const go = { "#entry": () => goToEntry("month"), "#add": () => goToEntry("month"), "#upload": () => goToEntry("csv"),
               "#mpesa": () => goToEntry("mpesa"), "#reports": () => { if (state.records.length) openReports(); } }[hash];
  if (go) { go(); return true; }
  const target = document.querySelector(hash.replace(/[^#\w-]/g, ""));
  if (target && !target.hidden) { target.scrollIntoView({ behavior: "smooth", block: "start" }); return true; }
  return false;
}
window.BCNav = { hash: dashHash };
window.addEventListener("hashchange", () => dashHash(location.hash));

async function feedbackNudge() {
  if (state.me.role !== "owner" || state.records.length < 3 || store.get("nudgeLater") === state.me.username) return;
  try {
    const q = await api("/feedback/questions");
    $("#feedback-nudge").hidden = q.given;
  } catch { /* not important */ }
}
$("#nudge-later").addEventListener("click", () => { store.set("nudgeLater", state.me.username); $("#feedback-nudge").hidden = true; });

function openTour() {
  Tour.hasRecords = state.records.length > 0;
  Tour.open(finished => {
    state.me.show_tour = false;
    if (finished && !state.records.length) goToEntry("month");
  });
}
$("#tour-link").addEventListener("click", openTour);

start().catch(err => {
  if (err.message === "Please log in.") return;
  $("#loading").hidden = true;
  $("#main").innerHTML = `<div class="card" style="margin-top:24px"><h2>Can't load your figures</h2>
    <p class="hint" style="margin-top:8px">Check that MySQL is running in the XAMPP Control Panel, then refresh this page.</p></div>`;
  console.error(err);
});
