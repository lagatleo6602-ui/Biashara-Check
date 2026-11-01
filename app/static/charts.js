/* Dashboard charts: plain SVG, no library.
   A view (what to show: profit, sales and costs, cash, margin, money owed) can be drawn as
   bars, lines, area, a pie (a breakdown of the whole period), a histogram (how many months fell
   in each range) or a table. Hover, touch and arrow keys show each month's figures. */
(() => {
  const kes = n => "KES " + Math.round(n).toLocaleString("en-KE");
  const short = n => {
    const a = Math.abs(n), s = n < 0 ? "-" : "";
    if (a >= 1e6) return s + (a / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
    if (a >= 1e3) return s + Math.round(a / 1e3) + "k";
    return s + Math.round(a);
  };
  const pctFmt = n => (n < 0 ? "-" : "") + Math.abs(n).toFixed(0) + "%";
  const monthLong = iso => new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { month: "long", year: "numeric" });
  const monthShort = iso => new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { month: "short" });
  const net = r => r.revenue - r.cogs - r.operating_expenses;
  const sum = (rs, f) => rs.reduce((t, r) => t + f(r), 0);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  /* What each view shows, its default way of drawing, and its pie breakdown */
  const VIEWS = {
    profit: {
      label: "Profit", title: "Profit or loss each month",
      hint: "Sales minus cost of goods and running expenses. Red bars are loss months.",
      kind: "bar", fmt: short, tip: kes, signed: true,
      series: [{ name: "Profit or loss", value: net }],
      pie: salesSplit,
    },
    sales: {
      label: "Sales and costs", title: "Sales and costs each month",
      hint: "When the costs line climbs to meet the sales line, profit is shrinking.",
      kind: "line", fmt: short, tip: kes,
      series: [
        { name: "Sales", value: r => r.revenue, cls: "s1" },
        { name: "Costs", value: r => r.cogs + r.operating_expenses, cls: "s2" },
      ],
      pie: salesSplit,
    },
    cash: {
      label: "Cash", title: "Cash left over each month",
      hint: "Money received minus money paid out. Red bars are months where more cash went out than came in.",
      kind: "bar", fmt: short, tip: kes, signed: true,
      series: [{ name: "Cash left over", value: r => r.cash_inflows - r.cash_outflows }],
      pie: recs => {
        const inflow = sum(recs, r => r.cash_inflows), mp = sum(recs, r => r.mobile_money_receipts || 0);
        if (mp > 0) return { title: "How money came in", total: inflow, totalLabel: "received", fmt: kes,
          slices: [{ name: "By M-Pesa", value: mp, cls: "p-blue" }, { name: "Cash and other", value: Math.max(0, inflow - mp), cls: "p-grey" }] };
        const out = sum(recs, r => r.cash_outflows);
        return { title: "Money in and money out", total: inflow + out, totalLabel: "moved", fmt: kes,
          slices: [{ name: "Money received", value: inflow, cls: "p-green" }, { name: "Money paid out", value: out, cls: "p-orange" }] };
      },
    },
    margin: {
      label: "Margin", title: "Profit per 100 shillings sold",
      hint: "How many shillings you keep from every 100 you sell. A falling line means costs are eating your sales.",
      kind: "line", fmt: pctFmt, tip: n => n.toFixed(1) + " KES per 100", zero: true, signed: true,
      series: [{ name: "Profit per 100 KES", value: r => r.revenue ? net(r) / r.revenue * 100 : 0, cls: "s1" }],
      pie: recs => {
        const good = recs.filter(r => net(r) > 0).length, bad = recs.filter(r => net(r) < 0).length, even = recs.length - good - bad;
        return { title: "Months with a profit or a loss", total: recs.length, totalLabel: recs.length === 1 ? "month" : "months",
          fmt: n => `${n} month${n === 1 ? "" : "s"}`, count: true,
          slices: [{ name: "Profit", value: good, cls: "p-green" }, { name: "Loss", value: bad, cls: "p-red" },
                   { name: "Break-even", value: even, cls: "p-grey" }] };
      },
    },
    debt: {
      label: "Money owed", title: "Money you owe at month end",
      hint: "Loans, supplier credit and other debts. A steady rise is an early warning sign.",
      kind: "line", fmt: short, tip: kes, zero: true,
      series: [{ name: "Money owed", value: r => r.outstanding_debt || 0, cls: "s1" }],
      pie: recs => {
        let up = 0, down = 0, same = 0;
        for (let i = 1; i < recs.length; i++) {
          const d = (recs[i].outstanding_debt || 0) - (recs[i - 1].outstanding_debt || 0);
          d > 0 ? up++ : d < 0 ? down++ : same++;
        }
        return { title: "Months when money owed went up or down", total: up + down + same,
          totalLabel: "changes", fmt: n => `${n} month${n === 1 ? "" : "s"}`, count: true,
          slices: [{ name: "Went up", value: up, cls: "p-red" }, { name: "Went down", value: down, cls: "p-green" },
                   { name: "No change", value: same, cls: "p-grey" }] };
      },
    },
  };

  /* Where each shilling of sales went */
  function salesSplit(recs) {
    const sales = sum(recs, r => r.revenue), cogs = sum(recs, r => r.cogs), opex = sum(recs, r => r.operating_expenses);
    const profit = sales - cogs - opex;
    if (profit >= 0) return { title: "Where your sales went", total: sales, totalLabel: "sales", fmt: kes,
      slices: [{ name: "Cost of goods", value: cogs, cls: "p-orange" }, { name: "Running expenses", value: opex, cls: "p-maize" },
               { name: "Profit", value: profit, cls: "p-green" }] };
    return { title: "Your costs: more than your sales", total: cogs + opex, totalLabel: "costs", fmt: kes,
      note: `Costs were ${kes(-profit)} more than sales in this period: a loss.`,
      slices: [{ name: "Cost of goods", value: cogs, cls: "p-orange" }, { name: "Running expenses", value: opex, cls: "p-maize" }] };
  }

  /* Ways to draw; "default" uses the view's own kind */
  const MODES = {
    bar: { label: "Bar" }, line: { label: "Line" }, area: { label: "Area" },
    pie: { label: "Pie" }, hist: { label: "Histogram" }, table: { label: "Table" },
  };
  const MODE_HINTS = {
    pie: "The whole period at once. Hover or tap a slice to see its amount.",
    hist: "How many months fell into each range. Tall bars show what a typical month looks like.",
    table: "Every month's figures, newest first.",
  };

  /* 3–5 round tick values covering [min, max] */
  function ticks(min, max) {
    const span = max - min || Math.abs(max) || 1;
    const raw = span / 4, mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => span / s <= 5);
    const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
    const out = [];
    for (let v = lo; v <= hi + step / 2; v += step) out.push(Math.round(v * 1e6) / 1e6);
    return out;
  }

  function render(box, recs, viewKey, mode) {
    const view = VIEWS[viewKey] || VIEWS.profit;
    mode = MODES[mode] ? mode : view.kind;
    box.innerHTML = "";
    if (!recs.length) {
      box.innerHTML = `<p class="empty">No months yet. Add your first month or upload a CSV to see your charts.</p>`;
      return;
    }
    if (mode === "pie") return renderPie(box, recs, view);
    if (mode === "hist") return renderHist(box, recs, view, viewKey);
    if (mode === "table") return renderTable(box, recs, view);
    return renderSeries(box, recs, view, viewKey, mode);
  }

  /* ---------- bars, lines, area over time ---------- */
  function renderSeries(box, recs, view, viewKey, mode) {
    const W = Math.max(300, Math.round(box.clientWidth || 640)), narrow = W < 520;
    const multi = view.series.length > 1;
    const H = narrow ? 200 : 240, padL = 46, padR = mode !== "bar" && multi && !narrow ? 56 : 10, padT = 12, padB = 26;
    const n = recs.length, slot = (W - padL - padR) / n;
    const data = view.series.map(s => recs.map(s.value));
    const all = data.flat();
    let min = Math.min(...all), max = Math.max(...all);
    if (mode !== "line" || view.zero || min >= 0) { min = Math.min(0, min); max = Math.max(0, max); }
    const tk = ticks(min, max);
    min = tk[0]; max = tk[tk.length - 1];
    const y = v => padT + (max - v) / ((max - min) || 1) * (H - padT - padB);
    const cx = i => padL + i * slot + slot / 2;

    let s = `<svg viewBox="0 0 ${W} ${H}" role="img" tabindex="0" aria-label="${esc(view.title)}, ${n} months. Use left and right arrow keys to read each month.">`;
    tk.forEach(v => {
      s += `<line class="${v === 0 ? "zero" : "grid-line"}" x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}"/>`;
      s += `<text x="${padL - 6}" y="${y(v) + 4}" text-anchor="end">${esc(view.fmt(v))}</text>`;
    });
    const step = Math.ceil(n / (narrow ? 4 : 8));
    recs.forEach((r, i) => {
      const last = i === n - 1;
      if ((i % step === 0 && n - 1 - i >= step / 2) || last) {
        const yr = i === 0 || r.month.endsWith("-01-01") ? " " + r.month.slice(2, 4) : "";
        s += `<text x="${last ? Math.min(cx(i) + 8, W - padR) : cx(i)}" y="${H - 6}" text-anchor="${last ? "end" : "middle"}">${monthShort(r.month)}${yr}</text>`;
      }
    });

    if (mode === "bar") {
      const k = data.length, group = Math.max(2, Math.min(26 * k, slot - 3)), bw = Math.max(2, (group - (k - 1) * 2) / k);
      data.forEach((vals, j) => vals.forEach((v, i) => {
        const x = cx(i) - group / 2 + j * (bw + 2), top = Math.min(y(v), y(0)), h = Math.max(1, Math.abs(y(v) - y(0)));
        const cls = multi ? "bar-" + view.series[j].cls : v < 0 && view.signed ? "bar-neg" : "bar-pos";
        s += barPath(x, top, bw, h, v >= 0, cls);
      }));
    } else {
      data.forEach((vals, k) => {
        const cls = view.series[k].cls || "s1";
        const pts = vals.map((v, i) => `${cx(i).toFixed(1)},${y(v).toFixed(1)}`);
        if (mode === "area") {
          s += `<path class="area ${cls}" d="M${cx(0).toFixed(1)},${y(Math.max(min, Math.min(0, max)))}L${pts.join("L")}L${cx(n - 1).toFixed(1)},${y(Math.max(min, Math.min(0, max)))}Z"/>`;
        }
        s += `<path class="line ${cls}" d="M${pts.join("L")}"/>`;
        if (n <= 14) vals.forEach((v, i) => { s += `<circle class="dot ${cls}" cx="${cx(i)}" cy="${y(v)}" r="3.5"/>`; });
      });
      if (multi && !narrow) {
        const labels = data.map((vals, k) => ({ name: view.series[k].name, y: y(vals[n - 1]) + 4 })).sort((a, b) => a.y - b.y);
        for (let i = 1; i < labels.length; i++) labels[i].y = Math.max(labels[i].y, labels[i - 1].y + 14);
        labels.forEach(l => { s += `<text class="end-label" x="${cx(n - 1) + 8}" y="${l.y}">${esc(l.name)}</text>`; });
      }
    }
    s += `<line class="cross" x1="0" x2="0" y1="${padT}" y2="${H - padB}" visibility="hidden"/>`;
    s += `<rect class="hit" x="${padL}" y="0" width="${W - padL - padR}" height="${H}" fill="transparent"/>`;
    s += `</svg>`;

    const legend = multi ? `<ul class="chart-legend">` + view.series.map(se => `<li><span class="key ${se.cls}"></span>${esc(se.name)}</li>`).join("") + `</ul>` : "";
    box.innerHTML = legend + `<div class="chart-plot">${s}<div class="tip" role="status" hidden></div></div>`;

    const svg = box.querySelector("svg"), tip = box.querySelector(".tip"), cross = box.querySelector(".cross");
    let current = -1;
    function show(i) {
      current = Math.max(0, Math.min(n - 1, i));
      const r = recs[current];
      cross.setAttribute("x1", cx(current)); cross.setAttribute("x2", cx(current)); cross.setAttribute("visibility", "visible");
      tip.innerHTML = `<strong>${esc(monthLong(r.month))}</strong>` + view.series.map((se, k) => {
        const v = data[k][current];
        return `<div>${multi ? `<span class="key ${se.cls}"></span>` : ""}${esc(se.name)}: <b class="${v < 0 && view.signed ? "neg" : ""}">${esc(view.tip(v))}</b></div>`;
      }).join("");
      tip.hidden = false;
      const scale = svg.getBoundingClientRect().width / W;
      const px = cx(current) * scale, tw = tip.offsetWidth, plotW = svg.getBoundingClientRect().width;
      tip.style.left = Math.max(0, Math.min(plotW - tw, px - tw / 2)) + "px";
    }
    hoverable(svg, tip, cross, e => {
      const rect = svg.getBoundingClientRect();
      return Math.floor(((e.clientX - rect.left) * (W / rect.width) - padL) / slot);
    }, show, () => current, n);
  }

  /* Shared hover / touch / keyboard behaviour */
  function hoverable(svg, tip, cross, indexFromEvent, show, current, n) {
    const hide = () => { tip.hidden = true; if (cross) cross.setAttribute("visibility", "hidden"); };
    svg.addEventListener("pointermove", e => show(indexFromEvent(e)));
    svg.addEventListener("pointerdown", e => show(indexFromEvent(e)));
    svg.addEventListener("pointerleave", e => { if (e.pointerType === "mouse") hide(); });
    svg.addEventListener("focus", () => show(current() < 0 ? n - 1 : current()));
    svg.addEventListener("blur", hide);
    svg.addEventListener("keydown", e => {
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") { show(current() - 1); e.preventDefault(); }
      if (e.key === "ArrowRight" || e.key === "ArrowDown") { show(current() + 1); e.preventDefault(); }
      if (e.key === "Escape") hide();
    });
  }

  /* ---------- pie (donut) of the whole period ---------- */
  function renderPie(box, recs, view) {
    const p = view.pie(recs);
    const slices = p.slices.filter(sl => sl.value > 0);
    const total = slices.reduce((t, sl) => t + sl.value, 0);
    if (!total) { box.innerHTML = `<p class="empty">Nothing to show for this period yet.</p>`; return; }
    const W = Math.max(300, Math.round(box.clientWidth || 640)), narrow = W < 560;
    const size = narrow ? 210 : 230, R = size / 2 - 4, r0 = R * 0.6, c = size / 2;
    let a = -Math.PI / 2, svg = `<svg viewBox="0 0 ${size} ${size}" role="img" tabindex="0" aria-label="${esc(p.title)}: ${slices.map(sl => `${sl.name} ${Math.round(sl.value / total * 100)}%`).join(", ")}">`;
    const arcs = [];
    slices.forEach((sl, i) => {
      const frac = sl.value / total, a2 = a + frac * Math.PI * 2;
      const gap = slices.length > 1 ? 0.012 : 0, s1 = a + gap, s2 = a2 - gap;
      const big = s2 - s1 > Math.PI ? 1 : 0, pt = (rr, t) => `${(c + rr * Math.cos(t)).toFixed(2)},${(c + rr * Math.sin(t)).toFixed(2)}`;
      const d = frac >= 0.9999
        ? `M${c - R},${c}A${R},${R} 0 1 1 ${c + R},${c}A${R},${R} 0 1 1 ${c - R},${c}M${c - r0},${c}A${r0},${r0} 0 1 0 ${c + r0},${c}A${r0},${r0} 0 1 0 ${c - r0},${c}Z`
        : `M${pt(R, s1)}A${R},${R} 0 ${big} 1 ${pt(R, s2)}L${pt(r0, s2)}A${r0},${r0} 0 ${big} 0 ${pt(r0, s1)}Z`;
      svg += `<path class="slice ${sl.cls}" data-i="${i}" d="${d}" fill-rule="evenodd"/>`;
      arcs.push([a, a2]);
      a = a2;
    });
    const totalText = p.count ? String(p.total) : short(p.total);
    svg += `<text class="pie-total" x="${c}" y="${c - 2}" text-anchor="middle">${esc(totalText)}</text>`;
    svg += `<text class="pie-sub" x="${c}" y="${c + 16}" text-anchor="middle">${esc(p.totalLabel)}</text></svg>`;
    const legend = `<ul class="pie-legend">` + slices.map((sl, i) => `<li data-i="${i}"><span class="swatch ${sl.cls}"></span>
        <span class="pl-name">${esc(sl.name)}</span><b>${Math.round(sl.value / total * 100)}%</b><span class="pl-val">${esc(p.fmt(sl.value))}</span></li>`).join("") + `</ul>`;
    box.innerHTML = `<p class="pie-title">${esc(p.title)}</p><div class="pie-wrap"><div class="chart-plot pie-plot">${svg}<div class="tip" role="status" hidden></div></div>${legend}</div>`
      + (p.note ? `<p class="pie-note">${esc(p.note)}</p>` : "");
    const el = box.querySelector("svg"), tip = box.querySelector(".tip");
    let current = -1;
    function show(i) {
      if (i < 0 || i >= slices.length) return;
      current = i;
      const sl = slices[i];
      box.querySelectorAll(".slice, .pie-legend li").forEach(x => x.classList.toggle("dim", Number(x.dataset.i) !== i));
      tip.innerHTML = `<strong>${esc(sl.name)}</strong><div>${esc(p.fmt(sl.value))} (${Math.round(sl.value / total * 100)}%)</div>`;
      tip.hidden = false;
      const mid = (arcs[i][0] + arcs[i][1]) / 2, scale = el.getBoundingClientRect().width / size;
      tip.style.left = Math.max(0, (c + R * 0.8 * Math.cos(mid)) * scale - tip.offsetWidth / 2) + "px";
      tip.style.top = Math.max(0, (c + R * 0.8 * Math.sin(mid)) * scale - 44) + "px";
    }
    const clear = () => { tip.hidden = true; box.querySelectorAll(".dim").forEach(x => x.classList.remove("dim")); };
    el.querySelectorAll(".slice").forEach(sl => sl.addEventListener("pointerenter", () => show(Number(sl.dataset.i))));
    box.querySelectorAll(".pie-legend li").forEach(li => li.addEventListener("pointerenter", () => show(Number(li.dataset.i))));
    box.querySelector(".pie-wrap").addEventListener("pointerleave", e => { if (e.pointerType === "mouse") clear(); });
    el.addEventListener("focus", () => show(current < 0 ? 0 : current));
    el.addEventListener("blur", clear);
    el.addEventListener("keydown", e => {
      if (["ArrowRight", "ArrowDown"].includes(e.key)) { show((current + 1) % slices.length); e.preventDefault(); }
      if (["ArrowLeft", "ArrowUp"].includes(e.key)) { show((current - 1 + slices.length) % slices.length); e.preventDefault(); }
      if (e.key === "Escape") clear();
    });
  }

  /* ---------- histogram: how many months fell in each range ---------- */
  function renderHist(box, recs, view, viewKey) {
    const se = view.series[0], vals = recs.map(se.value);
    if (recs.length < 3) { box.innerHTML = `<p class="empty">A histogram needs at least 3 months. Choose a longer period or another view.</p>`; return; }
    const lo0 = Math.min(...vals), hi0 = Math.max(...vals);
    const k = Math.max(3, Math.min(10, Math.ceil(Math.log2(vals.length) + 1)));
    // round bin width so the edges read cleanly
    const rawW = (hi0 - lo0 || Math.abs(hi0) || 1) / k, mag = 10 ** Math.floor(Math.log10(rawW));
    const bw = [1, 2, 2.5, 5, 10].map(m => m * mag).find(w => w >= rawW);
    let lo = Math.floor(lo0 / bw) * bw;
    if (view.signed && lo < 0 && hi0 > 0) lo = Math.floor(lo0 / bw) * bw; // keep 0 on an edge
    const bins = [];
    for (let x = lo; x <= hi0 || !bins.length; x += bw) bins.push({ from: x, to: x + bw, n: 0, months: [] });
    vals.forEach((v, i) => {
      const b = bins[Math.min(bins.length - 1, Math.floor((v - lo) / bw))];
      b.n++; b.months.push(recs[i].month);
    });
    const W = Math.max(300, Math.round(box.clientWidth || 640)), narrow = W < 520;
    const H = narrow ? 200 : 240, padL = 34, padR = 10, padT = 12, padB = 40;
    const m = bins.length, slot = (W - padL - padR) / m, maxN = Math.max(...bins.map(b => b.n));
    const tk = ticks(0, maxN).filter(t => Number.isInteger(t));
    const top = tk[tk.length - 1] || 1;
    const y = v => padT + (top - v) / top * (H - padT - padB);
    const fmt = viewKey === "margin" ? (v => v.toFixed(0)) : short;
    let s = `<svg viewBox="0 0 ${W} ${H}" role="img" tabindex="0" aria-label="How many months fell in each range of ${esc(se.name.toLowerCase())}">`;
    tk.forEach(v => {
      s += `<line class="${v === 0 ? "zero" : "grid-line"}" x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}"/>`;
      s += `<text x="${padL - 6}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
    });
    const every = Math.ceil(m / (narrow ? 4 : 8));
    bins.forEach((b, i) => {
      const x = padL + i * slot + 1, w = Math.max(2, slot - 2), h = Math.max(b.n ? 1 : 0, y(0) - y(b.n));
      const cls = view.signed && b.to <= 0 ? "bar-neg" : "bar-pos";
      if (b.n) s += barPath(x, y(b.n), w, h, true, cls);
      if (i % every === 0) s += `<text x="${padL + i * slot}" y="${H - padB + 16}" text-anchor="middle">${esc(fmt(b.from))}</text>`;
    });
    s += `<text x="${W - padR}" y="${H - padB + 16}" text-anchor="end">${esc(fmt(bins[m - 1].to))}</text>`;
    s += `<text x="${padL + (W - padL - padR) / 2}" y="${H - 4}" text-anchor="middle" class="axis-title">${esc(se.name)}${viewKey === "margin" ? " (KES per 100)" : " (KES)"} → number of months</text>`;
    s += `<rect class="hit" x="${padL}" y="0" width="${W - padL - padR}" height="${H}" fill="transparent"/></svg>`;
    box.innerHTML = `<div class="chart-plot">${s}<div class="tip" role="status" hidden></div></div>`;
    const svg = box.querySelector("svg"), tip = box.querySelector(".tip");
    let current = -1;
    function show(i) {
      current = Math.max(0, Math.min(m - 1, i));
      const b = bins[current];
      const range = viewKey === "margin" ? `${b.from.toFixed(0)} to ${b.to.toFixed(0)} per 100` : `${kes(b.from)} to ${kes(b.to)}`;
      tip.innerHTML = `<strong>${esc(range)}</strong><div>${b.n} month${b.n === 1 ? "" : "s"}${b.n ? ": " + esc(b.months.map(monthShort).join(", ")) : ""}</div>`;
      tip.hidden = false;
      const scale = svg.getBoundingClientRect().width / W, tw = tip.offsetWidth;
      tip.style.left = Math.max(0, Math.min(svg.getBoundingClientRect().width - tw, (padL + (current + 0.5) * slot) * scale - tw / 2)) + "px";
    }
    hoverable(svg, tip, null, e => {
      const rect = svg.getBoundingClientRect();
      return Math.floor(((e.clientX - rect.left) * (W / rect.width) - padL) / slot);
    }, show, () => current, m);
  }

  /* ---------- table ---------- */
  function renderTable(box, recs, view) {
    const rows = [...recs].reverse().map(r => `<tr><th scope="row">${esc(monthLong(r.month))}</th>` + view.series.map(se => {
      const v = se.value(r);
      return `<td class="num ${v < 0 && view.signed ? "neg" : ""}">${esc(view.tip(v))}</td>`;
    }).join("") + `</tr>`).join("");
    box.innerHTML = `<div class="table-wrap chart-table"><table><thead><tr><th scope="col">Month</th>`
      + view.series.map(se => `<th scope="col" class="num">${esc(se.name)}</th>`).join("") + `</tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  /* Bar with 4px rounded end on the data side, square on the baseline */
  function barPath(x, top, w, h, up, cls) {
    const r = Math.min(4, w / 2, h);
    if (up) return `<path class="${cls}" d="M${x},${top + h}V${top + r}Q${x},${top} ${x + r},${top}H${x + w - r}Q${x + w},${top} ${x + w},${top + r}V${top + h}Z"/>`;
    const b = top + h;
    return `<path class="${cls}" d="M${x},${top}V${b - r}Q${x},${b} ${x + r},${b}H${x + w - r}Q${x + w},${b} ${x + w},${b - r}V${top}Z"/>`;
  }

  window.Charts = { VIEWS, MODES, MODE_HINTS, render };
})();
