/* "How it's calculated": fills the method page with the latest test results and, for owners,
   their own numbers, track record and data-integrity checks. */
const $ = (s, r = document) => r.querySelector(s);
const pc = (x, dp = 0) => x == null ? "-" : (x * 100).toFixed(dp) + "%";
const n3 = x => x == null ? "-" : Number(x).toFixed(3);
const monthName = iso => new Date(iso.slice(0, 7) + "-01T00:00:00").toLocaleDateString("en-GB", { month: "short", year: "numeric" });
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

async function api(path) {
  const res = await fetch(path);
  if (res.status === 401) { location.href = "/login"; throw new Error("Please log in."); }
  if (!res.ok) throw new Error("Error " + res.status);
  return res.json();
}
function setEv(key, value) { document.querySelectorAll(`[data-ev="${key}"]`).forEach(e => { e.textContent = value; }); }
function row(tbody, cells, cls) {
  const tr = el("tr", cls);
  cells.forEach((c, i) => { const td = el(i ? "td" : "th", "", c); if (!i) td.scope = "row"; tr.append(td); });
  tbody.append(tr); return tr;
}

/* Grouped bars: for each prediction range, what we predicted vs what happened. Values are labelled, and the
   same numbers are in the table underneath, so colour is never the only cue. */
function calChart(box, cal) {
  const W = 640, H = 240, L = 40, B = 34, T = 14, R = 8;
  const pw = W - L - R, ph = H - T - B, g = pw / cal.length, bw = Math.min(26, g * 0.32);
  const y = v => T + ph * (1 - v);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Predicted against actual share of months followed by a loss");
  const add = (tag, attrs, text) => { const e = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v)); if (text != null) e.textContent = text; svg.append(e); return e; };
  [0, .25, .5, .75, 1].forEach(v => {
    add("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "cal-grid" });
    add("text", { x: L - 6, y: y(v) + 4, class: "cal-axis", "text-anchor": "end" }, (v * 100) + "%");
  });
  cal.forEach((c, i) => {
    const cx = L + g * i + g / 2;
    [["predicted", -1, "cal-pred"], ["actual", 1, "cal-act"]].forEach(([k, side, cls]) => {
      const x = cx + side * (bw / 2 + 1) - bw / 2, top = y(c[k]), h = Math.max(1, y(0) - top);
      const r = add("path", { d: `M${x},${y(0)} V${top + 4} q0,-4 4,-4 h${bw - 8} q4,0 4,4 V${y(0)} Z`, class: cls });
      const t = document.createElementNS(ns, "title"); t.textContent = `${pc(c.from)}–${pc(c.to)}: ${k} ${pc(c[k])} (${c.n} months)`; r.append(t);
      if (g > 60) add("text", { x: x + bw / 2, y: top - 4, class: "cal-val", "text-anchor": "middle" }, Math.round(c[k] * 100));
    });
    add("text", { x: cx, y: H - B + 16, class: "cal-axis", "text-anchor": "middle" }, `${Math.round(c.from * 100)}–${Math.round(c.to * 100)}%`);
  });
  add("text", { x: L + pw / 2, y: H - 4, class: "cal-axis", "text-anchor": "middle" }, "Range of predicted chance");
  box.innerHTML = ""; box.append(svg);
}

function renderEvidence(ev) {
  if (!ev.ready) { $("#no-model").hidden = false; $("#ds-none").hidden = false; setEv("best_name", "not trained yet"); return; }
  const e = ev.evidence || {};
  setEv("best_name", ev.best_name);
  setEv("band_mod", Math.round(ev.bands.moderate * 100)); setEv("band_high", Math.round(ev.bands.high * 100));
  // importance
  if (ev.importance?.length) {
    const ul = $("#imp-bars"), max = ev.importance[0].value;
    ev.importance.slice(0, 8).forEach(it => {
      const li = el("li"); li.append(el("span", "", it.name));
      const bar = el("i"); bar.style.setProperty("--w", (it.value / max * 100).toFixed(1) + "%"); li.append(bar);
      ul.append(li);
    });
    $("#imp-wrap").hidden = false;
  }
  if (!e.calibration) { $("#no-model").hidden = false; $("#no-model").textContent = "Retrain the model (Admin, Risk model) to see the full test results here."; }
  else {
    $("#acc").hidden = false;
    setEv("train_from", monthName(e.train_months[0])); setEv("train_to", monthName(e.train_months[1]));
    setEv("test_from", monthName(e.test_months[0])); setEv("test_to", monthName(e.test_months[1]));
    setEv("test_n", ev.rows.test.toLocaleString("en-KE")); setEv("test_biz", e.test_businesses.toLocaleString("en-KE"));
    // the headline proof: what happened after each band
    const proof = $("#band-proof"); proof.innerHTML = "";
    e.bands.forEach(b => {
      const d = el("div", "proof-band pb-" + b.band.toLowerCase());
      d.append(el("p", "pb-name", `${b.band} risk`));
      d.append(el("p", "pb-big", b.actual == null ? "-" : pc(b.actual)));
      d.append(el("p", "pb-text", b.n ? `of ${b.n.toLocaleString("en-KE")} test months we put here were followed by a loss. We predicted ${pc(b.predicted)} on average.` : "No test months landed here."));
      proof.append(d);
    });
    calChart($("#cal-chart"), e.calibration);
    const tb = $("#cal-table tbody"); tb.innerHTML = "";
    e.calibration.forEach(c => row(tb, [`${pc(c.from)} to ${pc(c.to)}`, c.n.toLocaleString("en-KE"), pc(c.predicted), `${pc(c.actual)} (${c.events})`]));
    const mt = $("#model-table tbody"); mt.innerHTML = "";
    Object.entries(ev.models).forEach(([k, m]) => {
      const tr = row(mt, [m.name + (k === ev.best ? " (used)" : ""), pc(m.recall), pc(m.precision), n3(m.pr_auc), n3(m.roc_auc), n3(m.brier)], k === ev.best ? "best" : "");
    });
    if (e.rule) row(mt, [e.rule.name, pc(e.rule.recall), pc(e.rule.precision), n3(e.rule.pr_auc), n3(e.rule.roc_auc), n3(e.rule.brier)], "rule");
    const best = ev.models[ev.best], cm = best.confusion, lossN = cm.tp + cm.fn, warnN = cm.tp + cm.fp;
    $("#confusion-text").textContent = `In the test, ${lossN.toLocaleString("en-KE")} months were followed by a loss. The ${ev.best_name} model warned (50% or more) about ${cm.tp.toLocaleString("en-KE")} of them, `
      + `${Math.round(cm.tp / lossN * 100)} in every 100. Of the ${warnN.toLocaleString("en-KE")} months it warned about, ${cm.tp.toLocaleString("en-KE")} were right: ${Math.round(cm.tp / warnN * 100)} in every 100.`
      + (e.rule ? ` The simple rule caught ${pc(e.rule.recall)} of them.` : "");
    const syn = ev.rows.synthetic, real = ev.rows.real;
    $("#synthetic-note").textContent = syn
      ? `${real ? `${real.toLocaleString("en-KE")} of the ${ev.rows.labelled.toLocaleString("en-KE")}` : `All ${ev.rows.labelled.toLocaleString("en-KE")}`} business-months the model learned from ${real ? "come from real businesses; the rest are" : "are"} simulated (synthetic) Kenyan SMEs, made to follow realistic patterns. The results above show the method works; how well it does on real businesses is being measured in this study, and the model will be retrained as real months come in.`
      : `All ${ev.rows.labelled.toLocaleString("en-KE")} business-months the model learned from come from real businesses in the study.`;
    $("#trained-at").textContent = `Model ${ev.version}, trained ${new Date(ev.trained_at).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })} on ${ev.rows.labelled.toLocaleString("en-KE")} business-months from ${ev.rows.businesses.toLocaleString("en-KE")} businesses.`;
  }
  // the 1-12 month outlook
  const hz = ev.horizon;
  if (!hz || hz.error) { $("#ol-none").hidden = false; if (hz?.error) $("#ol-none").textContent = hz.error; }
  else {
    $("#ol-ev").hidden = false;
    $("#ol-ev-intro").textContent = `Tested on business-months from ${monthName(hz.test_from)} onwards, after learning only from label windows that ended before then.`
      + (hz.anchored ? " Figures are for the anchored outlook, exactly as shown on the dashboard." : "");
    const tb = $("#ol-table tbody"); tb.innerHTML = "";
    Object.entries(hz.horizons).forEach(([h, m]) => {
      if (!m.enough) { row(tb, [`${h}`, m.n.toLocaleString("en-KE"), "-", "-", "-", "too few test months", "-"]); return; }
      const b = Object.fromEntries(m.bands.map(x => [x.band, x]));
      row(tb, [`${h}`, m.n.toLocaleString("en-KE"), pc(m.positive_rate), n3(m.roc_auc), n3(m.brier),
               b.High?.actual != null ? `${pc(b.High.actual)} of ${b.High.n.toLocaleString("en-KE")}` : "-",
               b.Low?.actual != null ? `${pc(b.Low.actual)} of ${b.Low.n.toLocaleString("en-KE")}` : "-"], h === "3" ? "best" : "");
    });
  }
  // distress model
  const d = ev.distress;
  if (!d || d.error) { $("#ds-none").hidden = false; if (d?.error) $("#ds-none").textContent = d.error; return; }
  $("#ds-ev").hidden = false;
  const ct = $("#coef-table tbody"); ct.innerHTML = "";
  const pv = p => p < 0.001 ? "< 0.001" : p.toFixed(3);
  d.coefficients.forEach(c => {
    const tr = row(ct, [c.name, (c.coef >= 0 ? "+" : "") + c.coef.toFixed(3), c.se.toFixed(3),
                        c.feature === "(intercept)" ? "-" : c.odds_ratio.toFixed(2),
                        c.feature === "(intercept)" ? "-" : `${c.ci_low.toFixed(2)} to ${c.ci_high.toFixed(2)}`, pv(c.p_value)]);
    if (c.feature !== "(intercept)" && c.p_value >= 0.05) tr.className = "weak";
  });
  const sales = d.coefficients.find(c => c.feature === "rev_growth_3m");
  if (sales && sales.coef > 0 && sales.p_value < 0.05)
    $("#ds-notes").textContent = "Why does a rising sales trend raise the chance a little? Growing businesses often pay for more stock before the money from the extra sales comes in, so cash can run short even while sales grow (overtrading).";
  const t = d.test, ds = $("#ds-stats"); ds.innerHTML = "";
  [["ROC-AUC (test)", n3(t.roc_auc)], ["PR-AUC (test)", n3(t.pr_auc)], ["Brier score (test)", n3(t.brier)],
   ["Catches distress (recall)", pc(t.recall)], ["Right when it warns", pc(t.precision)],
   ["McFadden pseudo R²", n3(d.mcfadden_r2)], ["Likelihood-ratio test", `χ² ${d.lr_test.statistic.toLocaleString("en-KE")}, p ${pv(d.lr_test.p_value)}`],
   ["Distress rate (test months)", pc(t.positive_rate, 1)]].forEach(([k, v]) => {
    const div = el("div"); div.append(el("dt", "", k), el("dd", "", v)); ds.append(div);
  });
  const hl = t.hosmer_lemeshow;
  $("#ds-hl").textContent = `Tested on ${d.rows.test.toLocaleString("en-KE")} later months (from ${monthName(d.test_from)}). `
    + `Hosmer-Lemeshow calibration test: χ² ${hl.statistic} on ${hl.df} df, p ${pv(hl.p_value)}. `
    + (hl.p_value >= 0.05 ? "No evidence that the chances are off." :
       `With thousands of test months this test flags even small gaps. Distress was more common in the test months (${pc(t.positive_rate)}) than in training (${pc(t.train_positive_rate)}), so the model tends to under-state the chance a little; the ranking (ROC-AUC) is what it does best.`);
}

function renderMine(f) {
  document.querySelectorAll("[data-owner]").forEach(e => { e.hidden = false; });
  if (f.latest) {
    $("#my-month").textContent = monthName(f.latest.month);
    const ul = $("#my-worked"); ul.innerHTML = "";
    f.items.forEach(it => {
      const li = el("li"); li.append(el("b", "", it.name), el("code", "", it.worked)); ul.append(li);
    });
  } else $("#my-figures").hidden = true;
  // track record
  const tr = f.track_record, sum = $("#tr-sum");
  if (!tr.checks.length) sum.textContent = "Not enough time has passed yet: a check is judged once the 3 months after it are recorded.";
  else {
    sum.textContent = tr.judged
      ? `Of ${tr.judged} Low or High checks that can now be judged, ${tr.right} turned out right (High followed by a loss, or Low with no loss). Moderate checks are a warning to watch, so they aren't scored.`
      : "Your checks so far were all Moderate, which are warnings to watch rather than yes-or-no calls.";
    const tb = $("#tr-table tbody"); tb.innerHTML = "";
    tr.checks.slice().reverse().forEach(c => {
      row(tb, [monthName(c.month), `${Math.round(c.probability * 100)}% (${c.band})`,
               c.loss_followed ? `Loss in ${c.loss_months.map(monthName).join(", ")}` : "No loss",
               c.right == null ? "Watch" : c.right ? "Right" : "Wrong"], c.right == null ? "" : c.right ? "ok" : "miss");
    });
    $("#tr-wrap").hidden = false;
  }
  // integrity
  const i = f.integrity, st = $("#int-stats"); st.innerHTML = "";
  if (!i.months) { $("#my-integrity").hidden = true; return; }
  [["Months saved", `${i.months} (${monthName(i.first)} to ${monthName(i.last)})`],
   ["Missing months", i.gaps.length ? i.gaps.map(monthName).join(", ") : "None"],
   ["Changes logged", `${i.changes.added} added, ${i.changes.edited} edited, ${i.changes.deleted} deleted, ${i.changes.uploads} uploads`],
   ["Last change", i.last_change ? new Date(i.last_change + "Z").toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "-"]]
    .forEach(([k, v]) => { const d = el("div"); d.append(el("dt", "", k), el("dd", "", v)); st.append(d); });
  const fl = $("#int-flags"); fl.innerHTML = "";
  if (i.flagged.length) {
    fl.append(el("p", "", "Months worth double-checking (possible typing mistakes):"));
    const ul = el("ul", "flag-list");
    i.flagged.forEach(x => ul.append(el("li", "", `${monthName(x.month)}: ${x.flags.join("; ")}.`)));
    fl.append(ul);
  } else fl.append(el("p", "ok-line", "No month looks like a typing mistake."));
  $("#int-fp").textContent = i.fingerprint;
}

$("#logout").addEventListener("click", async () => {
  try { await fetch("/auth/logout", { method: "POST" }); } finally { location.href = "/login"; }
});

(async () => {
  const me = await api("/auth/me");
  window.I18N?.sync(me.language);
  if (me.role === "admin") { $("#home-link").href = "/admin"; $("#home-link").textContent = "Admin"; }
  const [ev, fig] = await Promise.all([
    api("/method/evidence").catch(() => ({ ready: false })),
    me.business ? api(`/businesses/${encodeURIComponent(me.business)}/figures`).catch(() => null) : null,
  ]);
  renderEvidence(ev);
  if (fig) renderMine(fig);
  if (location.hash) document.querySelector(location.hash)?.scrollIntoView();
})().catch(err => console.error(err));
