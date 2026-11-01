/* Welcome walkthrough: shown once to new owners, and again from "How it works". */
(() => {
  const STEPS = [
    {
      title: "Welcome to Biashara Check",
      text: "Each month you add your sales and costs. Biashara Check looks at the last few months and tells you if the next three are heading toward a loss, early enough to do something about it.",
      art: `<div class="ta-band"><span>Your risk check</span><b>Low risk of a loss in the next 3 months</b>
              <div class="ta-gauge"><i class="on"></i><i></i><i></i></div></div>`,
    },
    {
      title: "Add your months",
      text: "Add a month after it ends. Type the figures from your sales book, upload many months at once from Excel, or, with Biashara Pro, read them from your M-Pesa statement.",
      art: `<div class="ta-ways">
              <div><svg viewBox="0 0 24 24"><path d="M5 4h11l3 3v13H5z"/><path d="M8 10h8M8 14h8M8 18h5"/></svg><b>Type in</b></div>
              <div><svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 10h16M10 4v16"/></svg><b>Excel / CSV</b></div>
              <div><svg viewBox="0 0 24 24"><rect x="7" y="3" width="10" height="18" rx="2"/><path d="M10 17h4"/></svg><b>M-Pesa <em>Pro</em></b></div>
            </div>`,
    },
    {
      title: "Read your risk check",
      text: "After 3 months you get your first check: low, moderate or high risk of a loss. When there are warning signs, each one comes with something practical you can do.",
      art: `<div class="ta-band ta-mid"><span>Your risk check</span><b>Moderate risk: watch your costs</b>
              <div class="ta-gauge"><i></i><i class="on"></i><i></i></div>
              <p>What you can do: check whether supplier prices went up.</p></div>`,
    },
    {
      title: "Watch the trend",
      text: "Charts show profit, sales and costs, cash and money owed month by month. Spotted a mistake? Choose Edit on that month in Your records.",
      art: `<svg class="ta-bars" viewBox="0 0 240 90" aria-hidden="true"><line x1="0" y1="70" x2="240" y2="70"/>
              <rect x="10" y="30" width="26" height="40" rx="3"/><rect x="50" y="20" width="26" height="50" rx="3"/>
              <rect x="90" y="26" width="26" height="44" rx="3"/><rect x="130" y="14" width="26" height="56" rx="3"/>
              <rect x="170" y="24" width="26" height="46" rx="3"/><rect x="210" y="10" width="26" height="60" rx="3"/></svg>`,
    },
    {
      title: "Your figures stay yours",
      text: "Only you and the study team can see your figures. They're never shared with lenders. The more months you add, the more reliable your check: 12 months is best.",
      art: `<div class="ta-lock"><svg viewBox="0 0 24 24"><rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg></div>`,
    },
  ];

  let dlg, i = 0, onDone = null;

  function build() {
    dlg = document.createElement("dialog");
    dlg.className = "tour";
    dlg.setAttribute("aria-labelledby", "tour-title");
    dlg.innerHTML = `
      <div class="tour-art" aria-hidden="true"></div>
      <div class="tour-body">
        <p class="tour-count" aria-live="polite"></p>
        <h2 id="tour-title"></h2>
        <p class="tour-text"></p>
        <div class="tour-dots" aria-hidden="true">${STEPS.map(() => "<span></span>").join("")}</div>
        <div class="tour-actions">
          <button type="button" class="link-btn tour-skip">Skip</button>
          <span class="tour-nav">
            <button type="button" class="btn ghost tour-back">Back</button>
            <button type="button" class="btn primary tour-next">Next</button>
          </span>
        </div>
      </div>`;
    document.body.append(dlg);
    dlg.querySelector(".tour-next").addEventListener("click", () => (i < STEPS.length - 1 ? show(i + 1) : close(true)));
    dlg.querySelector(".tour-back").addEventListener("click", () => show(i - 1));
    dlg.querySelector(".tour-skip").addEventListener("click", () => close(false));
    dlg.addEventListener("cancel", e => { e.preventDefault(); close(false); });
    dlg.addEventListener("keydown", e => {
      if (e.target.closest("button")) return;
      if (e.key === "ArrowRight" && i < STEPS.length - 1) show(i + 1);
      if (e.key === "ArrowLeft" && i > 0) show(i - 1);
    });
  }

  function show(n) {
    i = n;
    const s = STEPS[i], last = i === STEPS.length - 1;
    dlg.querySelector(".tour-art").innerHTML = s.art;
    dlg.querySelector(".tour-count").textContent = `Step ${i + 1} of ${STEPS.length}`;
    dlg.querySelector("#tour-title").textContent = s.title;
    dlg.querySelector(".tour-text").textContent = s.text;
    dlg.querySelectorAll(".tour-dots span").forEach((d, k) => d.classList.toggle("on", k === i));
    dlg.querySelector(".tour-back").hidden = i === 0;
    dlg.querySelector(".tour-skip").hidden = last;
    const next = dlg.querySelector(".tour-next");
    next.textContent = last ? (Tour.hasRecords ? "Go to my dashboard" : "Add my first month") : "Next";
    next.focus();
  }

  function close(finished) {
    dlg.close();
    fetch("/auth/tour-done", { method: "POST" }).catch(() => {});
    if (onDone) onDone(finished);
  }

  window.Tour = {
    hasRecords: false,
    open(done) {
      if (!dlg) build();
      onDone = done || null;
      dlg.showModal();
      show(0);
    },
  };
})();
