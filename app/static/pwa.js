/* Install Biashara Check on a phone's home screen or a computer (an installable web app).
   Shows an "Install app" button in the top bar when the browser offers installing, and lets the
   /install page use the same prompt (window.BCInstall). */
(() => {
  if ("serviceWorker" in navigator && location.protocol !== "file:") {
    window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
  }
  let deferred = null;
  const announce = () => document.dispatchEvent(new CustomEvent("installchange"));
  const installed = () => window.matchMedia?.("(display-mode: standalone)").matches || navigator.standalone === true;

  async function prompt() {
    if (!deferred) return "unavailable";
    deferred.prompt();
    const choice = await deferred.userChoice.catch(() => ({ outcome: "dismissed" }));
    deferred = null;
    document.getElementById("install-btn")?.remove();
    announce();
    return choice.outcome;
  }
  window.BCInstall = { available: () => !!deferred, installed, prompt };

  window.addEventListener("beforeinstallprompt", e => {
    e.preventDefault();
    deferred = e;
    announce();
    const nav = document.querySelector(".nav");
    if (!nav || document.getElementById("install-btn")) return;
    const b = document.createElement("button");
    b.id = "install-btn"; b.type = "button"; b.className = "nav-link install-link"; b.textContent = "Install app";
    b.addEventListener("click", prompt);
    nav.prepend(b);
  });
  window.addEventListener("appinstalled", () => { deferred = null; document.getElementById("install-btn")?.remove(); announce(); });

  /* Any "Install" link or button marked data-install: install at once when the browser allows it,
     otherwise open the Get the app page with the guide showing where to tap */
  document.addEventListener("click", async e => {
    const t = e.target.closest?.("[data-install]");
    if (!t) return;
    e.preventDefault();
    if (deferred) { await prompt(); return; }
    location.href = "/install?guide=1";
  });

  /* The "Biashara Check on your phone" card: hidden inside the installed app, and for 30 days after "Not now" */
  const PROMO = "bc-promo-later";
  function promo() {
    const card = document.getElementById("app-promo");
    if (!card) return;
    let later = 0;
    try { later = Number(localStorage.getItem(PROMO) || 0); } catch { /* private mode */ }
    card.hidden = installed() || Date.now() - later < 30 * 864e5;
    card.querySelector(".ap-x")?.addEventListener("click", () => {
      card.hidden = true;
      try { localStorage.setItem(PROMO, String(Date.now())); } catch { /* private mode */ }
    }, { once: true });
  }
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", promo) : promo();
})();
