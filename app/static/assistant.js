/* The Biashara Check assistant: a chat panel for business owners.
   Answers come from /assistant/ask, which runs inside the app (no outside AI, nothing leaves the app).
   The conversation is kept only in this browser tab (sessionStorage) and forgotten when the tab closes. */
(() => {
  const KEY = "bc-chat";
  const T = s => (window.I18N ? window.I18N.t(s) : s);
  let ctx = {}, busy = false, panel, log, input, chips, fab;

  const load = () => { try { return JSON.parse(sessionStorage.getItem(KEY) || "[]"); } catch { return []; } };
  const save = list => { try { sessionStorage.setItem(KEY, JSON.stringify(list.slice(-40))); } catch { /* private mode */ } };
  let chatLog = load();

  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

  /* Bot text: lines starting with "• " become a list, **words** become bold. Built with DOM nodes, never innerHTML. */
  function rich(text) {
    const box = el("div", "bot-text");
    let ul = null;
    text.split("\n").forEach(line => {
      const bullet = line.startsWith("• ");
      const target = bullet ? (ul ||= box.appendChild(el("ul"))) : box.appendChild(el("p"));
      if (!bullet) ul = null;
      const host = bullet ? target.appendChild(el("li")) : target;
      line.replace(/^• /, "").split(/(\*\*[^*]+\*\*)/).forEach(part => {
        if (/^\*\*.+\*\*$/.test(part)) host.append(el("b", "", part.slice(2, -2)));
        else if (part) host.append(document.createTextNode(part));
      });
    });
    return box;
  }

  function addMsg(m, scroll = true) {
    const row = el("div", "bot-msg " + (m.who === "me" ? "me" : "bot"));
    if (m.who === "me") row.append(el("p", "", m.text));
    else {
      row.append(rich(m.text));
      if (m.links?.length) {
        const ls = el("p", "bot-links");
        m.links.forEach(l => {
          const a = el("a", "", l.label + " →"); a.href = l.href;
          a.addEventListener("click", e => { e.preventDefault(); go(l.href); });
          ls.append(a);
        });
        row.append(ls);
      }
    }
    log.append(row);
    if (scroll) log.scrollTop = log.scrollHeight;
  }

  function setChips(list) {
    chips.innerHTML = "";
    const asked = new Set(chatLog.filter(m => m.who === "me").map(m => m.text.toLowerCase()));
    (list || []).filter(s => !asked.has(s.toLowerCase())).slice(0, 4).forEach(s => {
      const b = el("button", "bot-chip", s); b.type = "button";
      b.addEventListener("click", () => ask(s));
      chips.append(b);
    });
  }

  async function ask(text) {
    text = text.trim();
    if (!text || busy) return;
    busy = true; input.value = "";
    const mine = { who: "me", text }; chatLog.push(mine); addMsg(mine); setChips([]);
    const typing = el("div", "bot-msg bot typing"); typing.append(el("span"), el("span"), el("span"));
    typing.setAttribute("aria-label", T("Typing")); log.append(typing); log.scrollTop = log.scrollHeight;
    try {
      const res = await fetch("/assistant/ask", { method: "POST", headers: { "Content-Type": "application/json" },
                                                  body: JSON.stringify({ message: text, context: ctx }) });
      if (res.status === 401) { location.href = "/login"; return; }
      const body = await res.json().catch(() => ({}));
      const m = res.ok ? { who: "bot", text: body.reply, links: body.links }
                       : { who: "bot", text: typeof body.detail === "string" ? body.detail : T("Sorry, something went wrong. Please try again.") };
      if (res.ok && body.context && Object.keys(body.context).length) ctx = body.context;
      typing.remove(); chatLog.push(m); addMsg(m); setChips(body.suggestions);
      save(chatLog);
    } catch {
      typing.remove(); addMsg({ who: "bot", text: T("You seem to be offline. Try again when you're connected.") });
    } finally { busy = false; input.focus(); }
  }

  /* "Take me there": close the chat first (on a phone it covers the whole screen), then open the page,
     or, when it's on this page, the right tab, dialog or section */
  function go(href) {
    const u = new URL(href, location.href);
    open(false, false);
    if (u.pathname !== location.pathname) { location.href = u.pathname + u.search + u.hash; return; }
    if (!u.hash) { window.scrollTo({ top: 0, behavior: "smooth" }); return; }
    window.history.replaceState(null, "", u.hash);
    if (window.BCNav?.hash(u.hash)) return;
    const t = document.querySelector(u.hash);
    if (t) t.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function open(show, refocus = true) {
    panel.hidden = !show;
    fab.setAttribute("aria-expanded", show);
    document.body.classList.toggle("bot-open", show);
    if (show) {
      if (!log.children.length) start();
      setTimeout(() => input.focus(), 30);
    } else if (refocus) fab.focus();
  }

  function start() {
    if (chatLog.length) { chatLog.forEach(m => addMsg(m, false)); log.scrollTop = log.scrollHeight; setChips(DEFAULT()); return; }
    addMsg({ who: "bot", text: T("Hello! I can answer questions about your sales, profit, cash and risk, explain any figure, try a what-if, or show you how to do something in the app.") });
    setChips(DEFAULT());
  }
  const DEFAULT = () => [T("Why is my risk at this level?"), T("What was my gross profit last month?"),
                         T("What if I cut running costs by 10%?"), T("How can I improve my profit?")];

  /* ---------- A movable Ask button ----------
     Drag it anywhere; on release it sticks to the nearer side. Drop it at the very edge of the screen
     (or choose "tuck it away") and it hides, leaving a small tab; tap the tab to bring it back.
     The place is remembered on this device. While scrolling down on a phone it shrinks to just the icon. */
  const POS_KEY = "bc-fab";
  let pos = (() => { try { return { side: "right", y: 0.86, tucked: false, ...JSON.parse(localStorage.getItem(POS_KEY) || "{}") }; } catch { return { side: "right", y: 0.86, tucked: false }; } })();
  let dragMoved = false;
  const savePos = () => { try { localStorage.setItem(POS_KEY, JSON.stringify(pos)); } catch { /* private mode */ } };
  function place() {
    if (!fab) return;
    const h = fab.offsetHeight || 48, w = fab.offsetWidth || 96, gap = innerWidth < 560 ? 12 : 20;
    const top = Math.min(Math.max(pos.y * innerHeight - h / 2, 64), innerHeight - h - gap);
    fab.classList.add("placed");
    fab.classList.toggle("tucked", !!pos.tucked);
    fab.classList.toggle("on-left", pos.side === "left");
    fab.style.top = top + "px";
    fab.style.left = pos.side === "left" ? (pos.tucked ? 0 : gap) + "px" : "auto";
    fab.style.right = pos.side === "right" ? (pos.tucked ? 0 : gap) + "px" : "auto";
    fab.setAttribute("aria-label", pos.tucked ? T("Show the Ask button") : T("Ask Biashara Check"));
    if (panel) panel.classList.toggle("on-left", pos.side === "left");
  }
  function makeMovable() {
    let start = null;
    fab.addEventListener("pointerdown", e => {
      if (e.button !== 0) return;
      const r = fab.getBoundingClientRect();
      start = { x: e.clientX, y: e.clientY, dx: e.clientX - r.left, dy: e.clientY - r.top, moving: false };
      try { fab.setPointerCapture(e.pointerId); } catch { /* not supported */ }  // keep getting moves when the finger outruns the button
    });
    fab.addEventListener("pointermove", e => {
      if (!start) return;
      if (!start.moving && Math.hypot(e.clientX - start.x, e.clientY - start.y) < 8) return;
      if (!start.moving) { start.moving = true; fab.classList.add("dragging"); fab.classList.remove("tucked"); }
      fab.style.left = Math.min(Math.max(e.clientX - start.dx, -20), innerWidth - fab.offsetWidth + 20) + "px";
      fab.style.right = "auto";
      fab.style.top = Math.min(Math.max(e.clientY - start.dy, 56), innerHeight - fab.offsetHeight) + "px";
      e.preventDefault();
    });
    const end = e => {
      if (!start) return;
      if (start.moving) {
        dragMoved = true;
        fab.classList.remove("dragging");
        pos.side = e.clientX < innerWidth / 2 ? "left" : "right";
        pos.y = Math.min(Math.max(e.clientY / innerHeight, 0.1), 0.95);
        pos.tucked = e.clientX < 18 || e.clientX > innerWidth - 18;   // dropped at the very edge: tuck it away
        place(); savePos();
        setTimeout(() => { dragMoved = false; }, 400);
      }
      start = null;
    };
    fab.addEventListener("pointerup", end);
    fab.addEventListener("pointercancel", end);
    addEventListener("resize", place);
    // shrink to just the icon while scrolling down on a phone; full size again when scrolling up
    let lastY = scrollY;
    addEventListener("scroll", () => {
      const down = scrollY > lastY + 4, up = scrollY < lastY - 4;
      if (down && scrollY > 150) fab.classList.add("mini");
      else if (up) fab.classList.remove("mini");
      lastY = scrollY;
    }, { passive: true });
    requestAnimationFrame(place);
  }

  function build() {
    fab = el("button", "bot-fab"); fab.type = "button";
    fab.setAttribute("aria-haspopup", "dialog"); fab.setAttribute("aria-expanded", "false"); fab.setAttribute("aria-controls", "bot-panel");
    fab.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.2 3.6c-.5.4-1.3.1-1.3-.6V16A2.5 2.5 0 0 1 4 13.5z" fill="currentColor"/><circle cx="9" cy="9.5" r="1.2" fill="#0F3D2E"/><circle cx="12" cy="9.5" r="1.2" fill="#0F3D2E"/><circle cx="15" cy="9.5" r="1.2" fill="#0F3D2E"/></svg><span></span>`;
    fab.querySelector("span").textContent = "Ask";
    panel = el("section", "bot-panel"); panel.id = "bot-panel"; panel.hidden = true;
    panel.setAttribute("role", "dialog"); panel.setAttribute("aria-labelledby", "bot-h");
    panel.innerHTML = `
      <header class="bot-head">
        <div><h2 id="bot-h">Ask Biashara Check</h2><p>Built-in helper: free, and your figures stay in the app</p></div>
        <button class="bot-x" type="button" aria-label="Close">&times;</button>
      </header>
      <p class="bot-move-tip">Tip: drag the Ask button anywhere, or <button type="button" class="link-btn bot-tuck">tuck it away</button> to the side of the screen.</p>
      <div class="bot-log" role="log" aria-live="polite" data-no-i18n></div>
      <div class="bot-chips" data-no-i18n></div>
      <form class="bot-form" novalidate>
        <label class="sr" for="bot-in">Your question</label>
        <input id="bot-in" autocomplete="off" maxlength="500" placeholder="Ask about your business…">
        <button class="btn primary small" type="submit">Send</button>
      </form>`;
    log = panel.querySelector(".bot-log"); chips = panel.querySelector(".bot-chips"); input = panel.querySelector("input");
    fab.addEventListener("click", e => {
      if (dragMoved) { dragMoved = false; e.preventDefault(); return; }  // the end of a drag isn't a tap
      if (pos.tucked) { pos.tucked = false; place(); savePos(); return; } // a tucked-away button comes back first
      open(panel.hidden);
    });
    makeMovable();
    panel.querySelector(".bot-x").addEventListener("click", () => open(false));
    panel.querySelector(".bot-tuck").addEventListener("click", () => { open(false, false); pos.tucked = true; place(); savePos(); });
    panel.querySelector("form").addEventListener("submit", e => { e.preventDefault(); ask(input.value); });
    panel.addEventListener("keydown", e => { if (e.key === "Escape") open(false); });
    document.body.append(fab, panel);
    document.body.classList.add("has-bot");
    window.BCAssistant = { open: () => open(true), ask: q => { open(true); ask(q); } };
  }

  (async () => {
    try {
      const r = await fetch("/auth/me");
      if (!r.ok) return;
      const me = await r.json();
      if (me.role !== "owner") return;   // the assistant answers from the owner's own business
      build();
    } catch { /* offline: no assistant */ }
  })();
})();
