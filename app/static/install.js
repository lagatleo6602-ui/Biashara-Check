/* "Get the app": one-tap install when the browser allows it, otherwise a guide that points at the
   browser's own menu; the right steps for this device; a QR code for computers; and a check that the
   address isn't blocking installation (ngrok's free warning page does this). */
(() => {
  const $ = s => document.querySelector(s);
  const ua = navigator.userAgent;
  const device = /iPhone|iPad|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1) ? "iphone"
    : /Android/.test(ua) ? "android" : "computer";
  const local = ["127.0.0.1", "localhost", "::1"].includes(location.hostname);
  const secure = location.protocol === "https:" || local;
  const ngrok = /ngrok/.test(location.hostname);

  function showDevice(dev) {
    document.querySelectorAll(".ga-tabs [role=tab]").forEach(t => {
      const on = t.dataset.dev === dev; t.setAttribute("aria-selected", on); t.tabIndex = on ? 0 : -1;
    });
    document.querySelectorAll(".ga-steps").forEach(p => { p.hidden = p.dataset.dev !== dev; });
  }
  document.querySelectorAll(".ga-tabs [role=tab]").forEach(t => {
    t.addEventListener("click", () => showDevice(t.dataset.dev));
    t.addEventListener("keydown", e => {
      const tabs = [...document.querySelectorAll(".ga-tabs [role=tab]")], i = tabs.indexOf(t);
      const d = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (d) { const n = tabs[(i + d + tabs.length) % tabs.length]; showDevice(n.dataset.dev); n.focus(); }
    });
  });
  showDevice(device);

  /* The guide: a big arrow at the browser's menu (Android, computer) or Share button (iPhone) */
  const GUIDE = {
    android: { arrow: "top-right", steps: ["Tap the <b>⋮</b> menu at the top right of Chrome.", "Tap <b>Install app</b> (or <b>Add to Home screen</b>), then <b>Install</b>."] },
    iphone: { arrow: "bottom", steps: ["Tap the <b>Share</b> button (square with an arrow) at the bottom of Safari.", "Scroll down, tap <b>Add to Home Screen</b>, then <b>Add</b>."] },
    computer: { arrow: "top-right", steps: ["Click the <b>install icon</b> at the right end of the address bar (a screen with a down arrow), or the <b>⋮</b> menu.", "Click <b>Install</b>. Biashara Check opens in its own window."] },
  };
  function guide() {
    const g = GUIDE[device], box = $("#ga-guide");
    $("#gg-arrow").className = "gg-arrow " + g.arrow;
    const ol = $("#gg-steps"); ol.innerHTML = "";
    g.steps.forEach(html => { const li = document.createElement("li"); li.innerHTML = html; ol.append(li); });
    box.hidden = false; $("#gg-done").focus();
  }
  const closeGuide = () => { $("#ga-guide").hidden = true; $("#ga-install").focus(); };
  $("#gg-done").addEventListener("click", closeGuide);
  $("#ga-guide").addEventListener("click", e => { if (e.target.id === "ga-guide") closeGuide(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("#ga-guide").hidden) closeGuide(); });

  function state() {
    const st = $("#ga-state"), I = window.BCInstall, label = $("#ga-install-label");
    if (I?.installed()) { label.textContent = "Already installed"; $("#ga-install").disabled = true;
      st.textContent = "You're using the installed app. Nothing more to do."; return; }
    $("#ga-install").disabled = false;
    if (I?.available()) { label.textContent = "Install the app"; st.textContent = "One tap: your phone will ask you to confirm."; return; }
    label.textContent = device === "iphone" ? "Add to Home Screen" : "Install the app";
    st.textContent = !secure ? "Installing needs a secure (https://) address: open the app's https address first."
      : device === "iphone" ? "On iPhone and iPad it's installed from Safari's Share menu: tap the button to see where."
      : "Tap the button and we'll show you exactly where to tap.";
  }
  $("#ga-install").addEventListener("click", async () => {
    const I = window.BCInstall;
    if (I?.available()) {
      const out = await I.prompt();
      $("#ga-state").textContent = out === "accepted" ? "Installing… the Biashara Check icon will appear on your home screen." : "No problem: you can install it any time.";
      return;
    }
    guide();
  });
  document.addEventListener("installchange", state);
  window.addEventListener("load", state);
  state();
  if (new URLSearchParams(location.search).get("guide") === "1") setTimeout(() => { if (!window.BCInstall?.available()) guide(); }, 900);

  /* Is this address stopping the browser from reading the app's details? (ngrok's free warning page does,
     when the browser fetches them) */
  if (!local) {
    fetch("/manifest.webmanifest", { credentials: "include", headers: { Accept: "application/manifest+json" } })
      .then(r => r.text()).then(t => { JSON.parse(t); })
      .catch(() => {
        const w = $("#ga-blocked"); w.hidden = false;
        w.textContent = (ngrok ? "This ngrok address shows its warning page to the browser, so the one-tap install can't start. " : "This address isn't serving the app's install details correctly. ")
          + "You can still add it: use the browser menu (⋮ → Add to Home screen). For the full install, use a hosted address or a paid ngrok plan.";
      });
  }

  // QR code of this address, for opening the app on a phone
  if (device === "computer" && window.qrcode) {
    const url = location.origin + "/install";
    const q = window.qrcode(0, "M"); q.addData(url); q.make();
    const n = q.getModuleCount(), m = 2, size = n + m * 2, ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${size} ${size}`); svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "QR code for " + url); svg.setAttribute("shape-rendering", "crispEdges");
    const bg = document.createElementNS(ns, "rect"); bg.setAttribute("width", size); bg.setAttribute("height", size); bg.setAttribute("fill", "#fff");
    let d = "";
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (q.isDark(r, c)) d += `M${c + m},${r + m}h1v1h-1z`;
    const path = document.createElementNS(ns, "path"); path.setAttribute("d", d); path.setAttribute("fill", "#13201A");
    svg.append(bg, path);
    $("#qr-box").append(svg);
    $("#ga-url").textContent = url;
    $("#ga-qr").hidden = false;
    if (local) {
      const w = $("#ga-local"); w.hidden = false;
      w.textContent = `You're on ${location.host}, which only works on this computer: a phone can't open it. `
        + "To install on a phone, open the public address instead (the ngrok https address from start-with-ngrok.bat, or the hosted site) and scan the code there.";
      $("#ga-qr").classList.add("dim");
    }
  }

  // logged-out visitors: the top bar links go to the login page
  fetch("/auth/me").then(r => { if (!r.ok) { $("#home-link").href = "/login"; $("#home-link").textContent = "Log in"; $("#acct-link").hidden = true; } })
    .catch(() => {});
})();
