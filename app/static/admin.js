const $ = (s, r = document) => r.querySelector(s);
const num = n => Number(n).toLocaleString("en-KE");
let SECTOR = { retail: "Retail shop / duka", wholesale: "Wholesale / distributor", service: "Other services" };

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let body = null;
  try { body = await res.json(); } catch { /* empty */ }
  if (res.status === 401) { location.href = "/login"; throw new Error("Please log in."); }
  if (res.status === 403 && body?.detail === "Admins only.") { location.href = "/"; throw new Error("Admins only."); }
  if (!res.ok) {
    const d = body && body.detail;
    throw new Error(typeof d === "string" ? d : "Something went wrong (error " + res.status + ").");
  }
  return body;
}
const postJSON = (path, payload, method = "POST") =>
  api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload ?? {}) });

function showMsg(el, kind, text) { el.className = "msg " + kind; el.textContent = text; }

/* A notice that shows a temporary password once, with a copy button */
function showPassword(code, password, action) {
  const n = $("#notice");
  n.hidden = false;
  n.innerHTML = "";
  const p = document.createElement("p");
  p.textContent = `${action} for ${code}. Give the owner this temporary password. It won't be shown again. They'll be asked to choose their own password when they log in.`;
  const row = document.createElement("div"); row.className = "pw-row";
  const code1 = document.createElement("code"); code1.textContent = password;
  const copy = document.createElement("button"); copy.className = "btn ghost small"; copy.type = "button"; copy.textContent = "Copy";
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(password); copy.textContent = "Copied"; } catch { copy.textContent = "Select and copy it"; }
  });
  const close = document.createElement("button"); close.className = "btn ghost small"; close.type = "button"; close.textContent = "Done";
  close.addEventListener("click", () => { n.hidden = true; n.innerHTML = ""; });
  row.append(code1, copy, close);
  n.append(p, row);
  n.scrollIntoView({ block: "nearest" });
}
function showNotice(text) {
  const n = $("#notice"); n.hidden = false; n.textContent = text;
  setTimeout(() => { if (n.textContent === text) n.hidden = true; }, 4000);
}

/* Overview */
async function loadOverview() {
  const o = await api("/admin/overview");
  const target = o.target_business_months;
  $("#p-total").textContent = num(o.business_months);
  $("#p-target").textContent = num(target);
  const realPct = Math.min(100, o.real_business_months / target * 100);
  const synPct = Math.min(100 - realPct, o.synthetic_business_months / target * 100);
  $("#m-real").style.width = realPct + "%";
  $("#m-syn").style.width = synPct + "%";
  $("#meter").setAttribute("aria-label", `${o.real_business_months} real and ${o.synthetic_business_months} synthetic business-months out of a target of ${target}`);
  $("#l-real").textContent = `${num(o.real_business_months)} real`;
  $("#l-syn").textContent = `${num(o.synthetic_business_months)} synthetic`;
  const lossShare = o.business_months ? Math.round(o.loss_months / o.business_months * 100) : 0;
  const stats = [
    ["Businesses", num(o.businesses)],
    ["With a login", num(o.with_login)],
    ["Loss months", `${num(o.loss_months)} (${lossShare}%)`],
  ];
  const dl = $("#a-stats"); dl.innerHTML = "";
  stats.forEach(([k, v]) => {
    const d = document.createElement("div");
    const dt = document.createElement("dt"); dt.textContent = k;
    const dd = document.createElement("dd"); dd.textContent = v;
    d.append(dt, dd); dl.append(d);
  });
}

/* Businesses table */
let allRows = [];
async function loadBusinesses() {
  allRows = await api("/admin/businesses");
  drawBusinesses();
}
function drawBusinesses() {
  const q = ($("#biz-search").value || "").trim().toUpperCase();
  const rows = q ? allRows.filter(b => b.code.includes(q)) : allRows;
  $("#biz-count").textContent = q ? `${rows.length} of ${allRows.length}` : `${allRows.length} total`;
  const tb = $("#biz tbody"); tb.innerHTML = "";
  if (!allRows.length) {
    tb.innerHTML = `<tr><td colspan="6" class="empty-row">No businesses yet. Add one with the form, or share the sign-up page with owners.</td></tr>`;
    return;
  }
  if (!rows.length) {
    tb.innerHTML = `<tr><td colspan="6" class="empty-row"></td></tr>`;
    tb.querySelector("td").textContent = `No business code contains "${q}".`;
    return;
  }
  rows.forEach(b => tb.append(row(b)));
}
document.addEventListener("input", e => { if (e.target.id === "biz-search") drawBusinesses(); });

function cell(tag, text, cls, label) {
  const c = document.createElement(tag);
  if (text != null) c.textContent = text;
  if (cls) c.className = cls;
  if (label) c.dataset.label = label;  // shown as the row label on phones
  return c;
}
const monthLabel = ym => ym ? new Date(ym + "-01T00:00:00").toLocaleDateString("en-GB", { month: "short", year: "numeric" }) : "";

function row(b) {
  const tr = document.createElement("tr");
  const th = cell("th"); th.scope = "row";
  const link = document.createElement("a"); link.href = "/?business=" + encodeURIComponent(b.code); link.textContent = b.code;
  th.append(link);
  if (b.is_synthetic) th.append(cell("span", "synthetic", "tag"));
  if (b.pro?.active) { const t = cell("span", "Pro", "tag pro"); t.title = `Pro for ${b.pro.days_left} more days (${b.pro.source === "admin" ? "given free" : "paid by M-Pesa"})`; th.append(t); }
  tr.append(th);
  tr.append(cell("td", SECTOR[b.sector], "", "Type"));
  const months = cell("td", String(b.months), "", "Months");
  if (b.months) months.title = `${monthLabel(b.first_month)} to ${monthLabel(b.last_month)}`;
  tr.append(months);
  tr.append(cell("td", String(b.loss_months), b.loss_months ? "neg" : "", "Loss months"));

  tr.append(contactCell(b));

  let status = "None", cls = "muted";
  if (b.is_synthetic) status = "Not needed";
  else if (b.account) {
    status = b.account.active ? (b.account.last_login ? "Active" : "Never used") : "Switched off";
    cls = b.account.active ? "" : "neg";
  }
  const st = cell("td", status, cls, "Login");
  if (b.account?.last_login) st.title = "Last login " + b.account.last_login.replace("T", " ");
  tr.append(st);

  const td = cell("td", null, "actions");
  const actions = cell("div", null, "actions-inner");
  td.append(actions);
  if (!b.is_synthetic) {
    actions.append(actionBtn(b.account ? "Reset password" : "Create login", async () => {
      const r = await postJSON(`/admin/businesses/${encodeURIComponent(b.code)}/password`);
      showPassword(b.code, r.temporary_password, b.account ? "Password reset" : "Login created");
      await refresh();
    }));
    if (b.account) actions.append(actionBtn(b.account.active ? "Switch off" : "Switch on", async () => {
      await postJSON(`/admin/businesses/${encodeURIComponent(b.code)}/active`, { active: !b.account.active });
      showNotice(`${b.code} login ${b.account.active ? "switched off" : "switched on"}.`);
      await refresh();
    }));
  }
  if (!b.is_synthetic) actions.append(actionBtn(b.pro?.active ? "Remove Pro" : "Give Pro", async () => {
    const r = await postJSON(`/admin/businesses/${encodeURIComponent(b.code)}/pro`, { days: b.pro?.active ? 0 : 90 });
    showNotice(r.pro.active ? `${b.code} has Biashara Pro free for 90 days.` : `${b.code} is back on the free plan.`);
    await refresh();
  }));
  actions.append(deleteBtn(b));
  tr.append(td);
  return tr;
}

function contactCell(b) {
  const td = cell("td", null, "contact-cell", "Contact");
  if (b.is_synthetic) { td.textContent = "Not needed"; td.classList.add("muted"); return td; }
  if (!b.contact) { td.textContent = "Not added"; td.classList.add("muted"); return td; }
  const box = document.createElement("div");
  const em = document.createElement("span"); em.textContent = b.contact.email;
  em.append(badge(b.contact.email_verified ? "confirmed" : "unconfirmed", b.contact.email_verified));
  const ph = document.createElement("span"); ph.textContent = b.contact.phone;
  ph.append(badge(b.contact.phone_verified ? "confirmed" : "unconfirmed", b.contact.phone_verified));
  box.append(em, ph);
  const acts = document.createElement("div"); acts.className = "contact-acts";
  acts.append(actionBtn("Show", async btn => {
    const full = await postJSON(`/admin/businesses/${encodeURIComponent(b.code)}/contact/reveal`);
    em.firstChild.textContent = full.email; ph.firstChild.textContent = full.phone;
    btn.remove();
    await loadActivity();
  }));
  acts.append(actionBtn(b.contact.phone_verified ? "Unconfirm phone" : "Confirm phone", async () => {
    await postJSON(`/admin/businesses/${encodeURIComponent(b.code)}/contact/phone-verified`, { verified: !b.contact.phone_verified });
    showNotice(b.contact.phone_verified ? `${b.code} phone marked as unconfirmed.` : `${b.code} phone confirmed. Only do this after calling the owner on it.`);
    await refresh();
  }));
  td.append(box, acts);
  return td;
}
function badge(text, on) { const s = document.createElement("span"); s.className = "badge " + (on ? "on" : "off"); s.textContent = text; return s; }

function actionBtn(label, fn) {
  const btn = cell("button", label, "link-btn"); btn.type = "button";
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try { await fn(btn); } catch (err) { showNotice(err.message); } finally { btn.disabled = false; }
  });
  return btn;
}

/* Two-step delete: first click arms it for 5 seconds, second click deletes */
function deleteBtn(b) {
  const btn = cell("button", "Delete", "link-btn danger"); btn.type = "button";
  let armed = null;
  btn.addEventListener("click", async () => {
    if (!armed) {
      btn.textContent = `Delete ${b.code} and all its data?`;
      btn.classList.add("armed");
      armed = setTimeout(() => { armed = null; btn.textContent = "Delete"; btn.classList.remove("armed"); }, 5000);
      return;
    }
    clearTimeout(armed);
    btn.disabled = true;
    try {
      await api(`/admin/businesses/${encodeURIComponent(b.code)}`, { method: "DELETE" });
      showNotice(`Deleted ${b.code} and all its records.`);
      await refresh();
    } catch (err) { showNotice(err.message); btn.disabled = false; }
  });
  return btn;
}

/* Create business */
$("#create-form").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target, msg = $(".msg", f), btn = $("button[type=submit]", f);
  const code = f.code.value.trim().toUpperCase();
  if (!/^[A-Z0-9-]{3,20}$/.test(code)) return showMsg(msg, "err", "Business code must be 3–20 letters, numbers or dashes.");
  const payload = { code, sector: f.sector.value, is_synthetic: f.is_synthetic.checked, create_login: true };
  const email = f.email.value.trim(), phone = f.phone.value.trim();
  if (!!email !== !!phone) return showMsg(msg, "err", "Give both the owner's email and mobile, or leave both empty.");
  if (email) { payload.email = email; payload.phone = phone; }
  if (f.start_date.value) payload.start_date = f.start_date.value + "-01";
  btn.disabled = true;
  try {
    const r = await postJSON("/admin/businesses", payload);
    f.reset(); msg.textContent = "";
    window.AdminTabs?.show("businesses");
    if (r.temporary_password) showPassword(r.code, r.temporary_password, "Business added");
    else showNotice(`Added ${r.code}.`);
    await refresh();
  } catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.disabled = false; }
});

$("#logout").addEventListener("click", async () => {
  try { await fetch("/auth/logout", { method: "POST" }); } finally { location.href = "/login"; }
});

/* Activity log */
const ACTIONS = {
  "login": "Logged in", "login.failed": "Failed login", "account.created": "Signed up", "signup.code_sent": "Sign-up code emailed", "admin.created": "Admin account created",
  "admin_signup.failed": "Wrong admin code", "record.added": "Added a month", "record.edited": "Edited a month",
  "record.deleted": "Deleted a month", "records.uploaded": "Uploaded CSV", "contact.changed": "Changed contact details",
  "contact.viewed": "Viewed contact details", "email.verified": "Confirmed email", "phone.verified": "Confirmed phone",
  "phone.unverified": "Unconfirmed phone", "password.changed": "Changed password", "password.reset": "Reset password",
  "password.reset_requested": "Asked for reset email", "recovery_code.renewed": "New recovery code",
  "admin.password_reset": "Gave temporary password", "admin.login_switched_off": "Switched login off",
  "admin.login_switched_on": "Switched login on", "business.created": "Added business", "business.deleted": "Deleted business",
  "data.exported": "Downloaded all records", "messaging.test": "Sent a test message",
  "account.deleted": "Deleted own account", "records.downloaded": "Downloaded own figures",
  "admin.invite_created": "Generated admin code", "admin.invite_cancelled": "Cancelled admin code",
  "admin.admin_switched_off": "Switched admin off", "admin.admin_switched_on": "Switched admin on",
  "admin.super_handed_over": "Handed over super admin",
  "payment.started": "Started M-Pesa payment", "payment.paid": "Paid for Pro", "payment.failed": "M-Pesa payment failed",
  "report.downloaded": "Downloaded a report", "report.emailed": "Emailed monthly report", "alert.risk": "Sent a risk alert",
  "reminder.sent": "Sent a reminder", "reminders.run": "Ran reminders", "feedback.given": "Gave feedback", "settings.changed": "Changed settings",
  "model.trained": "Trained the risk model", "synthetic.generated": "Added synthetic data", "synthetic.removed": "Removed synthetic data", "synthetic.imported": "Imported training data", "report.emailed_by_owner": "Emailed a report to themselves",
  "mpesa.checked": "Checked M-Pesa connection", "mpesa.callback_tested": "Tested callback address",
  "payment.callback": "M-Pesa sent a result", "payment.checked": "Checked payment with M-Pesa", "pro.given": "Gave Pro free", "pro.removed": "Removed Pro",
  "mpesa.statement_read": "Read M-Pesa statement", "mpesa.statement_applied": "Used M-Pesa statement figures",
};
const when = iso => new Date(iso).toLocaleString("en-GB", { timeZone: "Africa/Nairobi", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
async function loadActivity() {
  const params = new URLSearchParams({ limit: "150" });
  const target = $("#act-target").value.trim(), kind = $("#act-kind").value;
  if (target) params.set("target", target);
  if (kind) params.set("action", kind);
  const rows = await api("/admin/activity?" + params);
  const tb = $("#act tbody"); tb.innerHTML = "";
  if (!rows.length) { tb.innerHTML = `<tr><td colspan="5" class="empty-row">Nothing recorded yet for this filter.</td></tr>`; return; }
  rows.forEach(a => {
    const tr = document.createElement("tr");
    if (a.action.endsWith("failed") || a.action === "contact.viewed" || a.action.startsWith("business.deleted")) tr.className = "flag";
    tr.append(cell("td", when(a.at), "", "When"));
    tr.append(cell("td", a.actor + (a.role === "admin" ? " (admin)" : ""), "", "Who"));
    tr.append(cell("td", ACTIONS[a.action] || a.action, "", "What"));
    tr.append(cell("td", a.target.toUpperCase().startsWith("SME") || a.target.includes("-") ? a.target.toUpperCase() : a.target, "", "Business"));
    const d = cell("td", a.detail, "act-detail", "Details"); if (a.ip) d.title = "From " + a.ip;
    tr.append(d);
    tb.append(tr);
  });
}
let actTimer;
$("#act-target").addEventListener("input", () => { clearTimeout(actTimer); actTimer = setTimeout(loadActivity, 250); });
$("#act-kind").addEventListener("change", loadActivity);

/* Email and SMS status */
const CH = {
  email: {
    live: ["Live", "on", m => `Sending from ${m.from || m.host}.`],
    console: ["Not set up", "off", () => "Emails are printed in the server window instead of sent. Add SMTP_HOST, SMTP_USER and SMTP_PASSWORD to .env, then restart the server."],
  },
  sms: {
    live: ["Live", "on", m => m.provider === "textbee"
      ? "Sending from your Android phone through TextBee. Free plan: 50 a day, 300 a month. Keep that phone on and online."
      : `Africa's Talking app "${m.username}"${m.sender_id ? `, sender ${m.sender_id}` : ", shared short code"}. Each SMS costs credit.`],
    sandbox: ["Sandbox", "mid", () => "Free testing: messages appear in the Africa's Talking simulator, not on real phones. Use your live username and API key to go live."],
    console: ["Not set up", "off", () => "SMS are printed in the server window. Add TEXTBEE_API_KEY (free, sends from your phone) or Africa's Talking keys to .env, then restart the server."],
  },
};
async function loadMessaging() {
  const m = await api("/admin/messaging");
  [["email", "Email"], ["sms", "SMS"]].forEach(([k, name]) => {
    const [label, cls, text] = CH[k][m[k].mode];
    const box = $("#ch-" + k); box.innerHTML = "";
    const h = document.createElement("p"); h.className = "ch-head";
    h.append(name + " ", badge(label, cls === "on"));
    if (cls === "mid") h.lastChild.className = "badge mid";
    const p = document.createElement("p"); p.className = "hint"; p.textContent = text(m[k]);
    box.append(h, p);
  });
}
$("#t-channel").addEventListener("change", e => { $("#t-to").placeholder = e.target.value === "sms" ? "your mobile, e.g. 0712 345 678" : "your email"; });
$("#test-form").addEventListener("submit", async e => {
  e.preventDefault();
  const msg = $("#test-form .msg"), btn = $("#test-form button");
  const to = $("#t-to").value.trim();
  if (!to) return showMsg(msg, "err", "Enter where to send the test.");
  btn.disabled = true; btn.textContent = "Sending…";
  try {
    const r = await postJSON("/admin/messaging/test", { channel: $("#t-channel").value, to });
    showMsg(msg, r.mode === "console" ? "" : "ok", r.message);
    loadActivity();
  } catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.disabled = false; btn.textContent = "Send test"; }
});

/* Admins, super admin and one-time admin codes */
const ago = iso => iso ? new Date(iso).toLocaleString("en-GB", { timeZone: "Africa/Nairobi", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "Never";
let iAmSuper = false;
async function loadAdmins() {
  const d = await api("/admin/admins");
  iAmSuper = d.i_am_super;
  const tb = $("#adm tbody"); tb.innerHTML = "";
  d.admins.forEach(a => {
    const tr = document.createElement("tr");
    const th = cell("th", a.username); th.scope = "row";
    if (a.username === d.me) th.append(cell("span", "you", "tag"));
    tr.append(th);
    const role = cell("td", null, "", "Role");
    role.append(a.is_super_admin ? (() => { const b = badge("Super admin", true); b.className = "badge super"; return b; })() : document.createTextNode("Admin"));
    if (!a.active) role.append(" ", badge("switched off", false));
    tr.append(role);
    const ct = cell("td", a.contact ? a.contact.email : "Not added", a.contact ? "" : "muted", "Contact");
    if (a.contact) ct.append(badge(a.contact.email_verified ? "confirmed" : "unconfirmed", a.contact.email_verified));
    tr.append(ct);
    tr.append(cell("td", ago(a.last_login), a.last_login ? "" : "muted", "Last login"));
    const td = cell("td", null, "actions");
    if (iAmSuper && a.username !== d.me) {
      const inner = cell("div", null, "actions-inner");
      inner.append(actionBtn(a.active ? "Switch off" : "Switch on", async () => {
        await postJSON(`/admin/admins/${encodeURIComponent(a.username)}/active`, { active: !a.active });
        showNotice(`${a.username} ${a.active ? "switched off and logged out" : "switched back on"}.`);
        await Promise.all([loadAdmins(), loadActivity()]);
      }));
      td.append(inner);
    }
    tr.append(td);
    tb.append(tr);
  });
  $("#adm-count").textContent = d.admins.length === 1 ? "1 admin" : `${d.admins.length} admins`;
  const boss = d.admins.find(a => a.is_super_admin);
  const note = $("#adm-note");
  note.hidden = iAmSuper;
  note.textContent = `Only the super admin${boss ? ` (${boss.username})` : ""} can add admins. Ask them for a one-time admin code.`;
  $("#super-tools").hidden = !iAmSuper;
  if (iAmSuper) {
    const sel = $("#ho-user"); sel.innerHTML = "";
    const others = d.admins.filter(a => a.username !== d.me && a.active);
    others.forEach(a => sel.append(new Option(a.username, a.username)));
    if (!others.length) sel.append(new Option("No other active admin yet", ""));
    sel.disabled = !others.length;
    $("#handover button").disabled = !others.length;
    await loadInvite();
  }
}

function drawInviteStatus(st) {
  $("#inv-hours").textContent = st.hours;
  const s = $("#inv-status"); s.innerHTML = "";
  if (st.active) {
    const b = badge("Waiting", true); s.append(b, `A code is waiting to be used. It expires ${ago(st.active.expires_at)}.`);
  } else {
    s.append(badge("None", false), "No code is open, so nobody can sign up as admin.");
  }
  if (st.last_used) s.append(cell("span", ` Last used by ${st.last_used.used_by}, ${ago(st.last_used.used_at)}.`, "hint"));
  $("#inv-cancel").hidden = !st.active;
  $("#inv-new").textContent = st.active ? "Generate a new code" : "Generate code";
}
async function loadInvite() { drawInviteStatus(await api("/admin/invite")); }

function showInviteCode(code, expires) {
  const box = $("#inv-code"); box.innerHTML = ""; box.hidden = false;
  const c = document.createElement("code"); c.textContent = code;
  const copy = cell("button", "Copy", "btn ghost small"); copy.type = "button";
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(code); copy.textContent = "Copied"; } catch { copy.textContent = "Select and copy it"; }
  });
  const hide = cell("button", "Hide", "btn ghost small"); hide.type = "button";
  hide.addEventListener("click", () => { box.hidden = true; box.innerHTML = ""; });
  box.append(c, copy, hide, cell("p", `Shown once only. Works for one sign-up until ${ago(expires)}.`));
}

$("#inv-new").addEventListener("click", async e => {
  const btn = e.currentTarget, msg = $("#invite-box .msg");
  btn.disabled = true; showMsg(msg, "", "");
  try {
    const r = await postJSON("/admin/invite");
    showInviteCode(r.code, r.expires_at);
    await Promise.all([loadInvite(), loadActivity()]);
  } catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.disabled = false; }
});
$("#inv-cancel").addEventListener("click", async e => {
  const btn = e.currentTarget, msg = $("#invite-box .msg");
  btn.disabled = true;
  try {
    drawInviteStatus(await api("/admin/invite", { method: "DELETE" }));
    $("#inv-code").hidden = true; $("#inv-code").innerHTML = "";
    showMsg(msg, "ok", "Code cancelled. It no longer works.");
    loadActivity();
  } catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.disabled = false; }
});
$("#handover").addEventListener("submit", async e => {
  e.preventDefault();
  const msg = $("#handover .msg"), who = $("#ho-user").value, pass = $("#ho-pass").value;
  if (!who) return showMsg(msg, "err", "There's no other active admin to hand over to.");
  if (!pass) return showMsg(msg, "err", "Enter your password to confirm.");
  try {
    await postJSON(`/admin/admins/${encodeURIComponent(who)}/make-super`, { password: pass });
    $("#ho-pass").value = "";
    $("#inv-code").hidden = true; $("#inv-code").innerHTML = "";
    showNotice(`${who} is now the super admin. Any open admin code was cancelled.`);
    await Promise.all([loadAdmins(), loadActivity()]);
  } catch (err) { showMsg(msg, "err", err.message); }
});

/* Biashara Pro and M-Pesa payments */
const PAY_MODE = {
  test: ["Test mode", "off", "M-Pesa isn't connected: payments succeed straight away and no money moves. Add MPESA_CONSUMER_KEY and MPESA_CONSUMER_SECRET (from developer.safaricom.co.ke) to .env, then restart."],
  sandbox: ["Sandbox", "mid", "Daraja sandbox: real PIN prompts from Safaricom's test system, KES 1 per payment. Set MPESA_ENV=production with your own shortcode and passkey to go live."],
  live: ["Live", "on", "Real M-Pesa payments."],
};
const PAY_STATUS = { paid: "Paid", pending: "Waiting for M-Pesa", failed: "Failed", cancelled: "Cancelled" };
async function loadPayments() {
  const d = await api("/admin/payments");
  const [label, cls, text] = PAY_MODE[d.mode];
  const b = badge(label, cls === "on"); if (cls === "mid") b.className = "badge mid";
  $("#pay-mode").replaceChildren(b);
  $("#pay-mode-text").textContent = text + (d.mode !== "test" ? ` Paybill/shortcode ${d.shortcode}${d.till ? ", till " + d.till : ""}.` : "");
  const cb = d.callback, line = $("#callback-line"); line.innerHTML = "";
  if (cb.url) {
    line.append(badge(cb.source === "ngrok" ? "ngrok" : "Callback set", true), " Safaricom sends results to ");
    const code = document.createElement("code"); code.textContent = cb.url; line.append(code, ".");
    line.append(cell("span", cb.last_received ? ` Last result received ${when(cb.last_received)}.` : " No result received yet.", "hint"));
  } else {
    line.append(badge("No callback", false), " Results are checked by asking M-Pesa while the owner waits. Start ngrok to get them sent here directly.");
  }
  const sum = $("#pay-sum"); sum.innerHTML = "";
  [["Businesses with Pro", d.pro_businesses], ["Received (not test)", "KES " + num(d.paid_total)],
   ["Price", `KES ${num(d.plans.month.price)} a month, KES ${num(d.plans.year.price)} a year`]].forEach(([k, v]) => {
    const div = document.createElement("div"); div.append(cell("dt", k), cell("dd", String(v))); sum.append(div);
  });
  const tb = $("#pays tbody"); tb.innerHTML = "";
  if (!d.payments.length) { tb.innerHTML = `<tr><td colspan="6" class="empty-row">No payments yet.</td></tr>`; return; }
  d.payments.forEach(p => {
    const tr = document.createElement("tr");
    tr.append(cell("td", when(p.at), "", "When"), cell("td", p.business, "", "Business"),
      cell("td", `KES ${num(p.amount)}${p.mode !== "live" ? " (" + p.mode + ")" : ""}`, "", "Amount"),
      cell("td", p.phone || "–", "", "Phone"));
    const st = cell("td", PAY_STATUS[p.status] || p.status, p.status === "paid" ? "" : (p.status === "pending" ? "" : "neg"), "Status");
    if (p.message && p.status !== "paid") st.title = p.message;
    const rc = cell("td", p.receipt || "–", "", "M-Pesa receipt");
    if (p.status !== "paid" && p.mode !== "test" && p.business && !p.business.endsWith("(deleted)")) {
      rc.append(" ", actionBtn("Check again", async () => {
        const r = await postJSON(`/payments/${p.id}/check`);
        showNotice(r.status === "paid" ? `M-Pesa confirmed payment ${p.id}. Pro is on for ${p.business}.` :
          r.status === "pending" ? "M-Pesa is still processing it. Try again in a minute." : `M-Pesa says: ${r.message}`);
        await refresh();
      }));
    }
    tr.append(st, rc);
    tb.append(tr);
  });
}

$("#mpesa-check").addEventListener("click", async e => {
  const btn = e.currentTarget, msg = $("#mpesa-check-msg");
  btn.disabled = true; btn.textContent = "Checking…"; showMsg(msg, "", "");
  try { const r = await postJSON("/admin/mpesa/check"); showMsg(msg, r.ok ? "ok" : "err", r.message); loadActivity(); }
  catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.disabled = false; btn.textContent = "Check M-Pesa connection"; }
});

$("#callback-test").addEventListener("click", async e => {
  const btn = e.currentTarget, msg = $("#mpesa-check-msg");
  btn.disabled = true; btn.textContent = "Testing…"; showMsg(msg, "", "");
  try { const r = await postJSON("/admin/mpesa/callback-test"); showMsg(msg, r.ok ? "ok" : "err", r.message); loadPayments(); loadActivity(); }
  catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.disabled = false; btn.textContent = "Test callback address"; }
});

/* Risk model */
const pctx = v => (v * 100).toFixed(1) + "%";
async function loadModel() {
  const d = await api("/admin/model");
  const st = $("#model-state"), b = $("#model-badge");
  const data = d.data;
  $("#syn-state").textContent = data.synthetic_businesses
    ? `${num(data.synthetic_businesses)} synthetic businesses, ${num(data.synthetic_months)} months. Real data: ${num(data.real_months)} months.`
    : `No synthetic data. Real data: ${num(data.real_months)} months.`;
  if (!d.libraries) {
    b.replaceChildren(badge("Not installed", false));
    st.textContent = "The machine-learning libraries aren't installed. Run venv\\Scripts\\pip install -r requirements.txt, then restart.";
    $("#model-results").hidden = true; return;
  }
  if (!d.ready) {
    b.replaceChildren(badge("Not trained", false));
    st.textContent = "No model yet: the dashboard uses the simple rule-based check. Add data (or synthetic businesses), then train.";
    $("#model-results").hidden = true; return;
  }
  const m = d.meta, best = m.models[m.best];
  b.replaceChildren(badge("In use", true));
  st.textContent = `${m.best_name} is in use (version ${m.version}), trained ${when(m.trained_at)} on ${num(m.rows.labelled)} business-months from ${num(m.rows.businesses)} businesses (${num(m.rows.real)} real, ${num(m.rows.synthetic)} synthetic). It caught ${pctx(best.recall)} of coming losses in the test months.`;
  $("#model-split").textContent = `Trained on months before the test period, tested on ${num(m.rows.test)} business-months from ${m.test_from} on. ${pctx(m.rows.positive_rate)} of business-months were followed by a loss within 90 days.`;
  const tb = $("#model-table tbody"); tb.innerHTML = "";
  Object.entries(m.models).sort((a, b) => b[1].pr_auc - a[1].pr_auc).forEach(([k, r]) => {
    const tr = document.createElement("tr"); if (k === m.best) tr.className = "best";
    const th = cell("th", r.name); th.scope = "row"; if (k === m.best) th.append(cell("span", "best", "tag pro"));
    tr.append(th);
    ["pr_auc", "roc_auc", "recall", "precision", "f1", "brier"].forEach(f => tr.append(cell("td", r[f].toFixed(3))));
    tb.append(tr);
  });
  const c = best.confusion, cm = $("#cm"); cm.innerHTML = "";
  $("#cm-name").textContent = `(${m.best_name}, threshold 0.5)`;
  const cellCm = (label, n, kind) => { const d = document.createElement("div"); d.className = "cm-cell " + kind; d.setAttribute("role", "cell");
    d.append(cell("b", num(n)), cell("span", label)); return d; };
  cm.append(cell("span", "", "cm-corner"), cell("span", "Predicted: no loss", "cm-head"), cell("span", "Predicted: loss", "cm-head"),
    cell("span", "Actual: no loss", "cm-side"), cellCm("correctly calm", c.tn, "ok"), cellCm("false alarms", c.fp, "warn"),
    cell("span", "Actual: loss", "cm-side"), cellCm("missed losses", c.fn, "bad"), cellCm("losses caught", c.tp, "ok"));
  const imp = $("#imp"); imp.innerHTML = "";
  const max = Math.max(...m.importance.map(x => x.value), 1e-9);
  m.importance.slice(0, 10).forEach(x => {
    const row = document.createElement("div"); row.className = "imp-row";
    row.title = `${x.name}: mean |SHAP| ${x.value.toFixed(4)}`;
    const bar = document.createElement("span"); bar.className = "imp-bar"; bar.style.width = (x.value / max * 100).toFixed(1) + "%";
    const track = document.createElement("span"); track.className = "imp-track"; track.append(bar);
    row.append(cell("span", x.name, "imp-name"), track);
    imp.append(row);
  });
  $("#model-results").hidden = false;
}
async function modelAction(btn, label, fn) {
  const msg = $("#model-msg"); btn.disabled = true; const old = btn.textContent; btn.textContent = label; showMsg(msg, "", "");
  try { await fn(msg); } catch (err) { showMsg(msg, "err", err.message); } finally { btn.disabled = false; btn.textContent = old; }
}
$("#train-btn").addEventListener("click", e => modelAction(e.currentTarget, "Training… (1–2 minutes with a lot of data)", async msg => {
  const m = await postJSON("/admin/model/train", { real_only: $("#real-only").checked });
  showMsg(msg, "ok", `Trained. ${m.best_name} did best (PR-AUC ${m.models[m.best].pr_auc.toFixed(3)}). Every business is being re-scored.`);
  await Promise.all([loadModel(), loadActivity()]);
}));
$("#syn-add").addEventListener("click", e => modelAction(e.currentTarget, "Adding…", async msg => {
  const n = Math.max(1, Math.min(300, Number($("#syn-n").value) || 60));
  const r = await postJSON("/admin/synthetic", { businesses: n });
  showMsg(msg, "ok", `Added ${r.businesses} synthetic businesses with ${num(r.business_months)} months (${pctx(r.loss_rate)} loss months). Train the model to use them.`);
  await refresh();
}));
$("#trn-file").addEventListener("change", e => {
  const file = e.target.files[0]; if (!file) return;
  const label = document.querySelector("label[for=trn-file]");
  modelAction(label, `Importing ${file.name}…`, async msg => {
    const fd = new FormData(); fd.append("file", file);
    const res = await fetch("/admin/training-csv", { method: "POST", body: fd, credentials: "same-origin" });
    const r = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(r.detail || `Import failed (error ${res.status}).`);
    const skipped = r.skipped_existing.length ? ` Skipped ${r.skipped_existing.length} business code${r.skipped_existing.length === 1 ? "" : "s"} already in the database.` : "";
    showMsg(msg, "ok", `Imported ${num(r.businesses_added)} businesses with ${num(r.business_months_added)} business-months, marked synthetic.${skipped} Now press Train the model.`);
    await refresh();
  }).finally(() => { e.target.value = ""; });
});
let synArmed = null;
$("#syn-remove").addEventListener("click", e => {
  const btn = e.currentTarget;
  if (!synArmed) { btn.textContent = "Remove every synthetic business and its months?"; btn.classList.add("armed");
    synArmed = setTimeout(() => { synArmed = null; btn.textContent = "Remove all synthetic businesses"; btn.classList.remove("armed"); }, 5000); return; }
  clearTimeout(synArmed); synArmed = null; btn.classList.remove("armed"); btn.textContent = "Remove all synthetic businesses";
  modelAction(btn, "Removing…", async msg => {
    const r = await api("/admin/synthetic", { method: "DELETE" });
    showMsg(msg, "ok", `Removed ${r.removed} synthetic businesses.`); await refresh();
  });
});

/* Reminders and feedback */
$("#remind-btn").addEventListener("click", async e => {
  const btn = e.currentTarget, msg = $("#remind-msg"); btn.disabled = true;
  try { const r = await postJSON("/admin/reminders/send");
        showMsg(msg, "ok", `Reminders for ${monthLabel(r.month)}: ${r.emails} email${r.emails === 1 ? "" : "s"} and ${r.sms} SMS sent; ${r.skipped} owners skipped (already added it, already reminded, switched off or no confirmed contact).`);
        loadActivity(); }
  catch (err) { showMsg(msg, "err", err.message); } finally { btn.disabled = false; }
});
$("#renew-btn").addEventListener("click", async e => {
  const btn = e.currentTarget, msg = $("#renew-msg"); btn.disabled = true;
  try { const r = await postJSON("/admin/renewals/run");
        showMsg(msg, "ok", `${r.notices} "renews soon" notice${r.notices === 1 ? "" : "s"}, ${r.prompts} M-Pesa renewal prompt${r.prompts === 1 ? "" : "s"} sent, ${r.settled} renewal payment${r.settled === 1 ? "" : "s"} settled.`);
        loadActivity(); }
  catch (err) { showMsg(msg, "err", err.message); } finally { btn.disabled = false; }
});
async function loadFeedback() {
  const d = await api("/admin/feedback");
  $("#fbk-count").textContent = d.responses === 1 ? "1 response" : `${d.responses} responses`;
  const g = $("#fbk-groups"); g.innerHTML = "";
  d.groups.forEach(x => { const div = document.createElement("div"); div.append(cell("dt", x.group), cell("dd", x.mean == null ? "–" : `${x.mean.toFixed(1)} / 5`)); g.append(div); });
  const tb = $("#fbk-table tbody"); tb.innerHTML = "";
  d.questions.forEach(q => {
    const tr = document.createElement("tr");
    const th = cell("th", q.question); th.scope = "row"; tr.append(th);
    tr.append(cell("td", q.mean == null ? "–" : q.mean.toFixed(2), q.mean != null && q.mean < 4 ? "neg" : "", "Average"), cell("td", String(q.n), "", "Answers"));
    tb.append(tr);
  });
  const ul = $("#fbk-comments"); ul.innerHTML = "";
  if (!d.comments.length) ul.append(cell("li", "No comments yet.", "hint"));
  d.comments.forEach(c => {
    const li = document.createElement("li");
    li.append(cell("b", `${c.business}, ${c.at.replace("T", " ")}`));
    [["Liked", c.liked], ["Confusing", c.confusing], ["Would add", c.wish]].forEach(([k, v]) => { if (v) li.append(cell("p", `${k}: ${v}`)); });
    ul.append(li);
  });
}

async function refresh() { await Promise.all([loadModel(), loadFeedback(), loadOverview(), loadBusinesses(), loadAdmins(), loadPayments(), loadActivity(), loadMessaging()]); }

(async () => {
  const me = await api("/auth/me");
  if (me.must_change_password) { location.href = "/account"; return; }
  if (me.role !== "admin") { location.href = "/"; return; }
  $("#admin").hidden = false;
  SECTOR = (await fillSectors($("#c-sector"))) || SECTOR;
  await refresh();
})().catch(err => console.error(err));

/* Types of business come from the server, so the list lives in one place (app/sectors.py) */
async function fillSectors(select) {
  try {
    const list = await (await fetch("/sectors")).json();
    const keep = select.value;
    select.innerHTML = "";
    list.forEach(s => select.add(new Option(s.label, s.id)));
    select.value = list.some(s => s.id === keep) ? keep : list[0].id;
    return Object.fromEntries(list.map(s => [s.id, s.label]));
  } catch { return null; }
}

/* ---------- Sections as tabs: one at a time, remembered in the address (#model, #activity …) ---------- */
(() => {
  const tabs = [...document.querySelectorAll(".admin-tabs [role=tab]")];
  const names = tabs.map(t => t.dataset.tab);
  function show(name, { focus = false, remember = true } = {}) {
    if (!names.includes(name)) name = names[0];
    tabs.forEach(t => {
      const on = t.dataset.tab === name;
      t.setAttribute("aria-selected", on); t.tabIndex = on ? 0 : -1;
      document.querySelector(`.admin-tabs [data-panel="${t.dataset.tab}"]`).hidden = !on;
      if (on && focus) t.focus();
    });
    if (remember) history.replaceState(null, "", "#" + name);
  }
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => show(t.dataset.tab));
    t.addEventListener("keydown", e => {
      const step = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e.key];
      if (!step) return;
      e.preventDefault();
      show(names[(i + step + names.length) % names.length], { focus: true });
    });
  });
  document.querySelectorAll("[data-goto]").forEach(b => b.addEventListener("click", () => {
    show(b.dataset.goto);
    document.querySelector(`[data-panel="${b.dataset.goto}"] input, [data-panel="${b.dataset.goto}"] select`)?.focus();
  }));
  window.addEventListener("hashchange", () => show(location.hash.slice(1), { remember: false }));
  show(location.hash.slice(1), { remember: false });
  window.AdminTabs = { show };
})();
