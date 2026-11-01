const $ = (s, r = document) => r.querySelector(s);
function showMsg(el, kind, text) { el.className = "msg " + kind; el.textContent = text; }

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let body = null;
  try { body = await res.json(); } catch { /* empty */ }
  if (res.status === 401) { location.href = "/login"; throw new Error("Please log in."); }
  if (!res.ok) {
    const d = body && body.detail;
    let msg = typeof d === "string" ? d : "Something went wrong (error " + res.status + ").";
    if (Array.isArray(d) && d[0]?.loc?.includes("new_password")) msg = "New password must be at least 8 characters.";
    else if (Array.isArray(d)) msg = "Check the form and try again.";
    throw new Error(msg);
  }
  return body;
}
const postJSON = (path, payload) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload ?? {}) });

/* Shared with the login page: shows a recovery code with copy + "written it down" */
function recoveryBox(code, { onDone, doneLabel = "Done" } = {}) {
  const wrap = document.createElement("div");
  wrap.className = "recovery";
  wrap.innerHTML = `<p><b>Write this down and keep it somewhere safe.</b> It's the only way to reset your password yourself. It won't be shown again.</p>
    <div class="pw-row"><code></code><button class="btn ghost small" type="button">Copy</button></div>
    <label class="consent"><input type="checkbox"><span>I have written down my recovery code</span></label>`;
  wrap.querySelector("code").textContent = code;
  const copy = wrap.querySelector("button");
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(code); copy.textContent = "Copied"; } catch { copy.textContent = "Select and copy it"; }
  });
  if (onDone) {
    const btn = document.createElement("button");
    btn.className = "btn primary"; btn.type = "button"; btn.textContent = doneLabel; btn.disabled = true;
    wrap.querySelector("input").addEventListener("change", e => { btn.disabled = !e.target.checked; });
    btn.addEventListener("click", onDone);
    wrap.append(btn);
  }
  return wrap;
}

document.querySelectorAll(".pw-toggle").forEach(btn => btn.addEventListener("click", () => {
  const input = document.getElementById(btn.getAttribute("aria-controls"));
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  btn.textContent = show ? "Hide" : "Show";
  btn.setAttribute("aria-pressed", show);
}));

let me = null;

/* ---------- Delete my account ---------- */
function setupDelete() {
  const name = me.business || me.username;
  $("#del-name").textContent = name;
  if (me.business) {
    $("#del-download").href = `/businesses/${encodeURIComponent(me.business)}/records.csv`;
  } else {
    $("#del-download-wrap").hidden = true;
    $("#del-what").textContent = "your admin account";
  }
  const check = () => { $("#del-btn").disabled = !($("#del-pass").value && $("#del-confirm").value.trim().toLowerCase() === name.toLowerCase()); };
  $("#del-pass").addEventListener("input", check);
  $("#del-confirm").addEventListener("input", check);
}
$("#del-form").addEventListener("submit", async e => {
  e.preventDefault();
  const msg = $("#del-form .msg"), btn = $("#del-btn");
  btn.disabled = true; btn.textContent = "Deleting…";
  try {
    await postJSON("/auth/delete-account", { password: $("#del-pass").value, confirm: $("#del-confirm").value.trim() });
    location.href = "/login?deleted=1";
  } catch (err) {
    showMsg(msg, "err", err.message);
    btn.disabled = false; btn.textContent = "Delete my account for good";
  }
});

/* ---------- Contact details ---------- */
function renderContact() {
  const c = me.contact, dl = $("#ct-list");
  dl.innerHTML = "";
  if (!c) {
    dl.innerHTML = `<div><dt>Email and mobile</dt><dd class="status-off">Not added yet</dd></div>`;
    $("#ct-edit-label").textContent = "Add email and mobile number";
    $("#ct-edit-wrap").open = true;
    $("#ct-verify").hidden = true;
    return;
  }
  $("#ct-edit-label").textContent = "Change email or mobile number";
  [["Email", c.email, c.email_verified ? "Confirmed" : "Not confirmed"],
   ["Mobile", c.phone, c.phone_verified ? "Confirmed" : "Not confirmed"]].forEach(([k, v, st]) => {
    const d = document.createElement("div");
    const dt = document.createElement("dt"); dt.textContent = k;
    const dd = document.createElement("dd"); dd.textContent = v;
    const badge = document.createElement("span");
    badge.className = "badge " + (st.startsWith("Confirmed") ? "on" : "off"); badge.textContent = st;
    dd.append(" ", badge); d.append(dt, dd); dl.append(d);
  });
  $("#ct-verify").hidden = c.email_verified;
  $("#ct-phone-verify").hidden = c.phone_verified;
}
$("#ct-phone-send").addEventListener("click", async e => {
  const msg = $("#ct-phone-verify .msg"), btn = e.currentTarget;
  btn.disabled = true;
  try {
    const r = await postJSON("/auth/phone/send-code");
    $("#ct-phone-code-wrap").hidden = false; btn.textContent = "Send again";
    showMsg(msg, "ok", r.mode === "sandbox" ? "Sent to the Africa's Talking sandbox. Open the simulator to see it."
                       : r.mode === "console" ? "Test mode: the code is printed in the server window."
                       : "Code sent. It can take a minute to arrive.");
    $("#ct-phone-code").focus();
  } catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.disabled = false; }
});
$("#ct-phone-verify").addEventListener("submit", async e => {
  e.preventDefault();
  const msg = $(".msg", e.target), code = $("#ct-phone-code").value.replace(/\s/g, "");
  if (!/^\d{6}$/.test(code)) return showMsg(msg, "err", "Enter the 6-digit code from the SMS.");
  try { me = await postJSON("/auth/phone/verify", { code }); renderContact(); }
  catch (err) { showMsg(msg, "err", err.message); }
});
$("#ct-form").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target, msg = $(".msg", f), btn = $("button[type=submit]", f);
  const email = f.email.value.trim(), phone = f.phone.value.trim();
  if (!/^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(email)) return showMsg(msg, "err", "Enter a valid email address, like name@gmail.com.");
  if (phone.replace(/\D/g, "").length < 9) return showMsg(msg, "err", "Enter your mobile number, like 0712 345 678.");
  if (!f.password.value) return showMsg(msg, "err", "Enter your password to save these.");
  btn.disabled = true;
  try {
    me = await api("/auth/contact", { method: "PUT", headers: { "Content-Type": "application/json" },
                                      body: JSON.stringify({ email, phone, current_password: f.password.value }) });
    f.reset();
    $("#ct-edit-wrap").open = false;
    renderContact();
    showMsg($("#ct-verify .msg"), me.notice ? "err" : (me.contact.email_verified ? "ok" : ""),
            me.notice || (me.contact.email_verified ? "Saved." : "Saved. We sent a code to your email: enter it above to confirm."));
    if (!me.contact.email_verified) $("#ct-code").focus();
  } catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.disabled = false; }
});
$("#ct-verify").addEventListener("submit", async e => {
  e.preventDefault();
  const msg = $(".msg", e.target), code = $("#ct-code").value.replace(/\s/g, "");
  if (!/^\d{6}$/.test(code)) return showMsg(msg, "err", "Enter the 6-digit code from the email.");
  try { me = await postJSON("/auth/email/verify", { code }); renderContact(); }
  catch (err) { showMsg(msg, "err", err.message); }
});
$("#ct-resend").addEventListener("click", async () => {
  const msg = $("#ct-verify .msg");
  try { await postJSON("/auth/email/send-code"); showMsg(msg, "ok", "New code sent. It expires in 15 minutes."); }
  catch (err) { showMsg(msg, "err", err.message); }
});

$("#pw-form").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target, msg = $(".msg", f), btn = $("button[type=submit]", f);
  if (!f.current.value) return showMsg(msg, "err", "Enter your current password.");
  if (f.new1.value.length < 8) return showMsg(msg, "err", "New password must be at least 8 characters.");
  if (f.new1.value !== f.new2.value) return showMsg(msg, "err", "The two new passwords don't match.");
  btn.disabled = true;
  try {
    await postJSON("/auth/change-password", { current_password: f.current.value, new_password: f.new1.value });
    f.reset();
    showMsg(msg, "ok", "Password changed. Any other phone or computer logged in to this account has been logged out.");
    if (me.must_change_password) {
      me.must_change_password = false;
      $("#must-change").hidden = true;
      // People given a temporary password have no recovery code yet: offer one straight away
      const r = await postJSON("/auth/recovery-code");
      const out = $("#rc-out"); out.hidden = false; out.innerHTML = "";
      out.append(recoveryBox(r.recovery_code, { onDone: () => { location.href = me.role === "admin" ? "/admin" : "/"; }, doneLabel: "Go to my dashboard" }));
      out.scrollIntoView({ block: "nearest" });
    }
  } catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.disabled = false; }
});

/* ---------- Username ---------- */
function renderUsername() {
  $("#un-now").textContent = me.username;
  $("#un-also").textContent = me.business
    ? `You can also log in with your business code ${me.business} or your email.`
    : "You can also log in with your email.";
}
$("#un-form").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target, msg = $(".msg", f), btn = $("button[type=submit]", f);
  const name = f.username.value.trim().toLowerCase();
  if (!/^[a-z0-9][a-z0-9._-]{2,29}$/.test(name))
    return showMsg(msg, "err", "Use 3 to 30 letters, numbers, dots, dashes or underscores, starting with a letter or number.");
  if (!f.password.value) return showMsg(msg, "err", "Enter your current password.");
  btn.disabled = true;
  try {
    me = await api("/auth/username", { method: "PUT", headers: { "Content-Type": "application/json" },
                                       body: JSON.stringify({ username: name, current_password: f.password.value }) });
    f.reset(); renderUsername(); renderWho();
    showMsg(msg, "ok", `Done. Log in with ${me.username} from now on.`);
  } catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.disabled = false; }
});

$("#rc-btn").addEventListener("click", async e => {
  const btn = e.target;
  btn.disabled = true;
  try {
    const r = await postJSON("/auth/recovery-code");
    const out = $("#rc-out"); out.hidden = false; out.innerHTML = "";
    out.append(recoveryBox(r.recovery_code));
    btn.textContent = "Make another new code";
  } catch (err) { alertInline(err.message); }
  finally { btn.disabled = false; }
});
function alertInline(text) { const out = $("#rc-out"); out.hidden = false; out.innerHTML = ""; const p = document.createElement("p"); p.className = "msg err"; p.textContent = text; out.append(p); }

/* ---------- Biashara Pro (M-Pesa) ---------- */
const kes = n => "KES " + Number(n).toLocaleString("en-KE");
const dayTime = iso => new Date(iso).toLocaleString("en-GB", { timeZone: "Africa/Nairobi", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const dayOnly = iso => new Date(iso).toLocaleDateString("en-GB", { timeZone: "Africa/Nairobi", day: "numeric", month: "long", year: "numeric" });
const STATUS = { paid: "Paid", pending: "Waiting for M-Pesa", failed: "Didn't go through", cancelled: "Cancelled" };

async function checkAgain(id, btn) {
  btn.disabled = true; btn.textContent = "Checking…";
  const msg = $("#pay-msg");
  try {
    const p = await postJSON(`/payments/${id}/check`);
    if (p.status === "paid") showMsg(msg, "ok", `M-Pesa confirmed the payment${p.receipt ? " (" + p.receipt + ")" : ""}. Biashara Pro is on until ${dayOnly(p.pro.until)}.`);
    else if (p.status === "pending") showMsg(msg, "", "M-Pesa is still processing this payment. Check again in a minute.");
    else showMsg(msg, "err", p.message || "M-Pesa says this payment didn't go through.");
    await loadPro();
  } catch (err) { showMsg(msg, "err", err.message); btn.disabled = false; btn.textContent = "Check again with M-Pesa"; }
}
let proData = null, polling = null;

function renderPro(d) {
  proData = d;
  const st = d.status;
  const badge = $("#pro-badge"); badge.className = "badge " + (st.active ? "super" : "off");
  badge.textContent = st.active ? "Active" : "Free plan";
  $("#pro-state").textContent = st.active ? "Your plan includes:" : st.until ? `Biashara Pro ended on ${dayTime(st.until)}. You're on the free plan. Pro adds:` : "You're on the free plan. Pro adds:";
  renderTerm(st);
  const ul = $("#pro-features"); ul.innerHTML = "";
  d.features.forEach(f => { const li = document.createElement("li"); li.textContent = f; ul.append(li); });
  const mode = $("#pro-mode");
  mode.hidden = d.mode === "live";
  mode.textContent = d.mode === "test"
    ? "Test mode: M-Pesa isn't connected yet, so no prompt is sent and no money moves. Payments go through straight away."
    : "M-Pesa sandbox: Safaricom's test system. You'll only be asked for KES 1.";
  const box = $("#plans"); box.querySelectorAll("label").forEach(l => l.remove());
  d.plans.forEach((p, i) => {
    const l = document.createElement("label");
    const r = document.createElement("input"); r.type = "radio"; r.name = "plan"; r.value = p.id; r.checked = i === 0;
    const span = document.createElement("span");
    span.innerHTML = `<b></b><small></small>`;
    span.firstChild.textContent = p.name;
    const saving = p.id === "year" ? Math.round((1 - p.price / (d.plans[0].price * 12)) * 100) : 0;
    span.lastChild.textContent = kes(p.price) + (saving > 0 ? `, save ${saving}%` : "");
    l.append(r, span); box.append(l);
  });
  if (!$("#pay-phone").value) $("#pay-phone").value = d.phone || "";
  $("#pay-btn").textContent = st.active ? "Add more time with M-Pesa" : "Pay with M-Pesa";
  const list = $("#pay-list"); list.innerHTML = "";
  d.payments.forEach(p => {
    const li = document.createElement("li");
    const left = document.createElement("span"); left.textContent = `${dayTime(p.at)}, ${kes(p.amount)}${p.kind === "renewal" ? ", automatic renewal" : ""}${p.mode !== "live" ? " (" + p.mode + ")" : ""}`;
    const right = document.createElement("span"); right.className = "pay-status " + p.status;
    right.textContent = STATUS[p.status] + (p.receipt ? ", " + p.receipt : "");
    if (p.message && p.status !== "paid") right.title = p.message;
    li.append(left, right);
    const recent = Date.now() - new Date(p.at).getTime() < 3 * 864e5;
    if (p.status !== "paid" && p.mode !== "test" && recent) {
      const again = document.createElement("button"); again.type = "button"; again.className = "link-btn inline";
      again.textContent = "Check again with M-Pesa";
      again.addEventListener("click", () => checkAgain(p.id, again));
      li.append(again);
    }
    list.append(li);
  });
  $("#pay-history").hidden = !d.payments.length;
}

async function loadPro() { renderPro(await api("/payments/pro")); }

/* ---------- When Pro ends, a live countdown, and automatic renewal (cancel / turn back on) ---------- */
let countTimer = null;
function countdown(untilIso) {
  const end = new Date(untilIso).getTime();
  const tick = () => {
    let s = Math.max(0, Math.floor((end - Date.now()) / 1000));
    if (s === 0) { clearInterval(countTimer); $("#pro-count").textContent = "Ended"; loadPro().catch(() => {}); return; }
    const d = Math.floor(s / 86400); s -= d * 86400;
    const h = Math.floor(s / 3600); s -= h * 3600;
    const m = Math.floor(s / 60); s -= m * 60;
    $("#pro-count").textContent = `${d} day${d === 1 ? "" : "s"}, ${h} h ${String(m).padStart(2, "0")} min ${String(s).padStart(2, "0")} s left`;
  };
  clearInterval(countTimer); tick(); countTimer = setInterval(tick, 1000);
}
function renderTerm(st) {
  const box = $("#pro-term");
  box.hidden = !st.active;
  if (!st.active) { clearInterval(countTimer); return; }
  $("#pro-until").textContent = new Date(st.until).toLocaleString("en-GB", { timeZone: "Africa/Nairobi", weekday: "short", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit" });
  $("#pro-until").setAttribute("datetime", st.until);
  countdown(st.until);
  $("#pt-plan").textContent = st.source === "admin" && !st.plan ? "Given free by the study team."
    : `Plan: ${st.plan_name || "Biashara Pro"}, paid with M-Pesa. Paying again adds time on top of this date.`;
  const r = $("#renew-box"); r.innerHTML = "";
  r.className = "renew-box " + (st.auto_renew ? "on" : "off");
  const p = document.createElement("p"), actions = document.createElement("div"); actions.className = "renew-actions";
  const msg = document.createElement("p"); msg.className = "msg"; msg.setAttribute("role", "status");
  if (st.auto_renew) {
    p.innerHTML = "<b>Automatic renewal is on.</b> ";
    p.append(`Around ${dayTime(st.renewal.prompt_at)} we'll send an M-Pesa prompt for ${kes(st.renewal.amount)} to ${st.renewal.phone}. Nothing is paid unless you enter your PIN.`);
    const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "btn ghost small danger-ghost"; cancel.textContent = "Cancel automatic renewal";
    cancel.addEventListener("click", () => {
      actions.innerHTML = "";
      const q = document.createElement("p"); q.className = "renew-q";
      q.textContent = `Stop renewing? Pro keeps working until ${dayTime(st.until)}, then you go back to the free plan. No more M-Pesa prompts will be sent.`;
      const yes = document.createElement("button"); yes.type = "button"; yes.className = "btn danger small"; yes.textContent = "Yes, cancel renewal";
      const no = document.createElement("button"); no.type = "button"; no.className = "btn ghost small"; no.textContent = "Keep renewing";
      yes.addEventListener("click", async () => {
        yes.disabled = true;
        try { const out = await postJSON("/payments/auto-renew", { on: false }); proData.status = out.status; renderPro(proData);
              showMsg($("#renew-box .msg"), "ok", `Automatic renewal cancelled. Pro still ends on ${dayTime(out.status.until)}.`); }
        catch (err) { showMsg(msg, "err", err.message); yes.disabled = false; }
      });
      no.addEventListener("click", () => renderTerm(st));
      actions.append(q, yes, no);
    });
    actions.append(cancel);
  } else if (st.plan) {
    p.innerHTML = "<b>Automatic renewal is off.</b> ";
    p.append(`Pro ends on ${dayTime(st.until)} and won't renew${st.cancelled_at ? ` (cancelled ${dayTime(st.cancelled_at)})` : ""}. You won't get any M-Pesa prompts.`);
    const on = document.createElement("button"); on.type = "button"; on.className = "btn ghost small"; on.textContent = "Turn renewal back on";
    on.addEventListener("click", async () => {
      on.disabled = true;
      try { const out = await postJSON("/payments/auto-renew", { on: true, phone: $("#pay-phone").value.trim() || null });
            proData.status = out.status; renderPro(proData); showMsg($("#renew-box .msg"), "ok", "Automatic renewal is back on."); }
      catch (err) { showMsg(msg, "err", err.message); on.disabled = false; }
    });
    actions.append(on);
  } else {
    p.textContent = "This Pro time was given by the study team, so it doesn't renew. You can pay for a plan any time.";
  }
  r.append(p, actions, msg);
}

function waiting(on, title = "", text = "") {
  $("#pay-wait").hidden = !on;
  $("#pay-btn").disabled = on;
  $("#wait-title").textContent = title; $("#wait-text").textContent = text;
}

$("#pay-form").addEventListener("submit", async e => {
  e.preventDefault();
  const msg = $("#pay-msg"), plan = $("input[name=plan]:checked")?.value, phone = $("#pay-phone").value.trim();
  if (!phone) return showMsg(msg, "err", "Enter the M-Pesa number to pay from.");
  showMsg(msg, "", "");
  const p = proData.plans.find(x => x.id === plan);
  waiting(true, "Sending the M-Pesa prompt…", "");
  try {
    const pay = await postJSON("/payments/stk", { plan, phone, auto_renew: $("#pay-renew").checked });
    waiting(true, "Check your phone", `Enter your M-Pesa PIN to pay ${kes(pay.amount)} for ${p.name} of Biashara Pro. The prompt goes to ${pay.phone}.`);
    pollPayment(pay.id, Date.now());
  } catch (err) { waiting(false); showMsg(msg, "err", err.message); }
});

function pollPayment(id, started) {
  clearTimeout(polling);
  polling = setTimeout(async () => {
    try {
      const p = await api(`/payments/${id}`);
      if (p.status === "pending") {
        const secs = Math.round((Date.now() - started) / 1000);
        if (secs > 150) {
          waiting(false);
          showMsg($("#pay-msg"), "", "M-Pesa hasn't confirmed the payment yet. If you entered your PIN and got the M-Pesa message, use Check again with M-Pesa under Your payments in a minute or two. You won't be charged twice.");
          $("#pay-history").open = true;
          return loadPro();
        }
        if (secs > 40) $("#wait-text").textContent = "Still waiting for M-Pesa to confirm. This can take a minute, especially in the sandbox.";
        return pollPayment(id, started);
      }
      waiting(false);
      if (p.status === "paid") {
        showMsg($("#pay-msg"), "ok", `Paid${p.receipt ? " (M-Pesa " + p.receipt + ")" : ""}. Biashara Pro is on until ${dayOnly(p.pro.until)}.`);
      } else {
        showMsg($("#pay-msg"), "err", p.message || "The payment didn't go through.");
      }
      await loadPro();
    } catch (err) { waiting(false); showMsg($("#pay-msg"), "err", err.message); }
  }, 3000);
}

/* ---------- Messages (notification choices) ---------- */
function renderNotify() {
  $("#notify").hidden = me.role !== "owner";
  $("#nt-lang").value = window.I18N ? I18N.lang : (me.language || "en");
  $("#nt-reports").checked = me.notify.reports;
  $("#nt-reminders").checked = me.notify.reminders;
  $("#nt-alerts").checked = me.notify.alerts;
}
$("#nt-lang").addEventListener("change", async e => {
  if (window.I18N) await I18N.set(e.target.value);
  showMsg($("#nt-msg"), "ok", e.target.value === "sw" ? "Imehifadhiwa." : "Saved.");
  setTimeout(() => showMsg($("#nt-msg"), "", ""), 2000);
});
document.addEventListener("languagechange", e => { $("#nt-lang").value = e.detail; });

/* Sections as tabs: one panel at a time, so the page stays short */
const TAB_OF = { contact: "profile", notify: "profile", profile: "profile", pro: "pro", security: "security",
                 "pw-form": "security", password: "security", username: "security", feedback: "feedback", delete: "delete" };
function panelVisible(p) { return [...p.children].some(c => !c.hidden); }
function showTab(name, focus = false) {
  const tabs = [...document.querySelectorAll(".acct-nav [role=tab]")];
  let tab = tabs.find(t => t.dataset.tab === name && !t.hidden) || tabs.find(t => !t.hidden);
  tabs.forEach(t => {
    const on = t === tab;
    t.setAttribute("aria-selected", on); t.tabIndex = on ? 0 : -1;
    document.querySelector(`[data-panel="${t.dataset.tab}"]`).hidden = !on;
  });
  if (focus) tab.focus();
  return tab;
}
let wantedTab = TAB_OF[location.hash.slice(1)] || null;   // from a link such as /account#feedback
function pickTab(name) {
  wantedTab = null;
  const tab = showTab(name);
  history.replaceState(null, "", "#" + tab.dataset.tab);
}
function refreshTabs() {
  document.querySelectorAll(".acct-nav [role=tab]").forEach(t => {
    t.hidden = !panelVisible(document.querySelector(`[data-panel="${t.dataset.tab}"]`));
  });
  const cur = document.querySelector(".acct-nav [aria-selected=true]");
  showTab(wantedTab || (cur && !cur.hidden ? cur.dataset.tab : "profile"));
}
document.querySelectorAll(".acct-nav [role=tab]").forEach(t => {
  t.addEventListener("click", () => pickTab(t.dataset.tab));
  t.addEventListener("keydown", e => {
    const tabs = [...document.querySelectorAll(".acct-nav [role=tab]")].filter(x => !x.hidden);
    const i = tabs.indexOf(t);
    const next = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (next) { e.preventDefault(); pickTab(tabs[(i + next + tabs.length) % tabs.length].dataset.tab); document.querySelector(".acct-nav [aria-selected=true]").focus(); }
  });
});
window.addEventListener("hashchange", () => { wantedTab = TAB_OF[location.hash.slice(1)] || "profile"; refreshTabs(); });

[["nt-reports", "reports"], ["nt-reminders", "reminders"], ["nt-alerts", "alerts"]].forEach(([id, key]) => {
  $("#" + id).addEventListener("change", async e => {
    const msg = $("#nt-msg");
    try { me = await api("/auth/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ [key]: e.target.checked }) });
          showMsg(msg, "ok", "Saved."); setTimeout(() => showMsg(msg, "", ""), 2000); }
    catch (err) { e.target.checked = !e.target.checked; showMsg(msg, "err", err.message); }
  });
});

/* ---------- Feedback questionnaire ---------- */
async function loadFeedback() {
  if (me.role !== "owner") return;
  const q = await api("/feedback/questions");
  const box = $("#fb-questions"); box.innerHTML = "";
  q.questions.forEach((text, i) => {
    const fs = document.createElement("fieldset"); fs.className = "fb-q";
    const lg = document.createElement("legend"); lg.textContent = `${i + 1}. ${text}`; fs.append(lg);
    const row = document.createElement("div"); row.className = "fb-scale";
    [1, 2, 3, 4, 5].forEach(n => {
      const l = document.createElement("label");
      const r = document.createElement("input"); r.type = "radio"; r.name = "q" + i; r.value = n;
      const sp = document.createElement("span"); sp.textContent = n;
      l.append(r, sp); row.append(l);
    });
    fs.append(row); box.append(fs);
  });
  $("#feedback").hidden = false;
  if (q.given) showMsg($("#feedback .msg"), "ok", "Thank you: you've already sent feedback. You can send it again if your view changed.");
  refreshTabs();
}
$("#feedback").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target, msg = $(".msg", f), n = $("#fb-questions").children.length;
  const answers = Array.from({ length: n }, (_, i) => { const c = f.querySelector(`input[name=q${i}]:checked`); return c ? Number(c.value) : null; });
  if (answers.every(a => a === null)) return showMsg(msg, "err", "Choose a number for at least one statement.");
  try {
    await postJSON("/feedback", { answers, liked: $("#fb-liked").value, confusing: $("#fb-confusing").value, wish: $("#fb-wish").value });
    f.reset(); showMsg(msg, "ok", "Thank you! Your feedback was sent.");
  } catch (err) { showMsg(msg, "err", err.message); }
});

$("#logout").addEventListener("click", async () => {
  try { await fetch("/auth/logout", { method: "POST" }); } finally { location.href = "/login"; }
});

function renderWho() {
  $("#who").textContent = me.role === "admin"
    ? `Logged in as ${me.username} (study admin).`
    : me.username === (me.business || "").toLowerCase() ? `Logged in as ${me.business}.` : `Logged in as ${me.username} (business ${me.business}).`;
}

(async () => {
  me = await api("/auth/me");
  window.I18N?.sync(me.language);
  $("#account").hidden = false;
  renderWho();
  renderUsername();
  if (me.role === "admin") { $("#home-link").href = "/admin"; $("#home-link").textContent = "Admin"; }
  setupDelete();
  $("#must-change").hidden = !me.must_change_password;
  renderContact();
  if (me.role === "owner" && !me.must_change_password) {
    $("#pro").hidden = false;
    await loadPro().catch(err => { $("#pro-state").textContent = err.message; });
  }
  renderNotify();
  if (me.must_change_password) wantedTab = "security";
  refreshTabs();
  loadFeedback().catch(() => {});
  if (me.must_change_password) $("#cur").focus();
})().catch(err => console.error(err));
