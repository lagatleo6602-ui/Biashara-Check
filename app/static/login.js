const $ = (s, r = document) => r.querySelector(s);

function showMsg(el, kind, text) { el.className = "msg " + kind; el.textContent = text; }
function clearMsg(el) { el.className = "msg"; el.textContent = ""; }

async function post(path, payload) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  let body = null;
  try { body = await res.json(); } catch { /* empty */ }
  if (!res.ok) {
    const d = body && body.detail;
    let msg = typeof d === "string" ? d : "Something went wrong. Try again.";
    if (Array.isArray(d)) {
      const f = d[0]?.loc?.[d[0].loc.length - 1];
      msg = { code: "Business code must be 3–20 letters, numbers or dashes.",
              password: "Password must be at least 8 characters.",
              username: "Admin username must be 3–40 letters, numbers, dots, dashes or underscores.",
              admin_code: "Enter the admin code.",
              new_password: "New password must be at least 8 characters.",
              email: "Enter a valid email address, like name@gmail.com.",
              phone: "Enter a Kenyan mobile number, like 0712 345 678.",
              code: "Enter the 6-digit code from the email." }[f] || "Check the form and try again.";
    }
    throw new Error(msg);
  }
  return body;
}

const goHome = async (me, carry = false) => {
  // a language picked on this page carries over to the account
  if (carry && window.I18N && I18N.lang !== (me.language || "en")) {
    await fetch("/auth/settings", { method: "PUT", headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({ language: I18N.lang }) }).catch(() => {});
  }
  location.href = me.must_change_password ? "/account" : (me.role === "admin" ? "/admin" : "/"); };

/* After sign-up or a reset: show the recovery code once before going in */
function showRecovery(me, heading) {
  ["#login-form", "#signup-form", "#recover", ".tabs"].forEach(sel => { $(sel).hidden = true; });
  const box = $("#rc-screen");
  box.hidden = false;
  box.innerHTML = `<h2></h2><div class="recovery">
      <p><b>Write down your recovery code and keep it somewhere safe.</b> If you forget your password, it's the only way to reset it yourself. It won't be shown again.</p>
      <div class="pw-row"><code></code><button class="btn ghost small" type="button" id="rc-copy">Copy</button></div>
      <label class="consent"><input type="checkbox" id="rc-ok"><span>I have written down my recovery code</span></label>
      <button class="btn primary" type="button" id="rc-go" disabled>Continue</button></div>`;
  $("h2", box).textContent = heading;
  $("code", box).textContent = me.recovery_code;
  if (me.notice) { const n = document.createElement("p"); n.className = "msg err"; n.textContent = me.notice; box.querySelector(".recovery").prepend(n); }
  $("#rc-copy").addEventListener("click", async e => {
    try { await navigator.clipboard.writeText(me.recovery_code); e.target.textContent = "Copied"; } catch { e.target.textContent = "Select and copy it"; }
  });
  $("#rc-ok").addEventListener("change", e => { $("#rc-go").disabled = !e.target.checked; });
  $("#rc-go").addEventListener("click", () => goHome(me, true));
  $("#rc-ok").focus();
}

// Already logged in? Skip this page.
fetch("/auth/me").then(r => r.ok ? r.json() : null).then(me => { if (me) goHome(me); }).catch(() => {});

/* Tabs */
function selectTab(which) {
  ["login", "signup"].forEach(t => {
    const on = t === which, tab = $("#tab-" + t);
    tab.setAttribute("aria-selected", on); tab.tabIndex = on ? 0 : -1;
    $(`#${t}-form`).hidden = !on;
  });
  $(`#${which}-form input:not([type=radio]):not([hidden] *)`)?.focus();
}
$("#tab-login").addEventListener("click", () => selectTab("login"));
$("#tab-signup").addEventListener("click", () => selectTab("signup"));
$(".tabs").addEventListener("keydown", e => {
  if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
  const next = $("#tab-login").getAttribute("aria-selected") === "true" ? "signup" : "login";
  selectTab(next); $("#tab-" + next).focus();
});
if (location.hash === "#signup") selectTab("signup");
if (new URLSearchParams(location.search).get("deleted")) $("#deleted-note").hidden = false;

/* Account type: owner or admin */
const isAdminSignup = () => $("input[name=account_type]:checked").value === "admin";
function syncAccountType() {
  const admin = isAdminSignup();
  $("#owner-fields").hidden = admin;
  $("#admin-fields").hidden = !admin;
  $("#consent-row").hidden = admin;
  $("#signup-form .msg").textContent = "";
}
document.querySelectorAll("input[name=account_type]").forEach(r => r.addEventListener("change", syncAccountType));
fetch("/auth/options").then(r => r.json()).then(o => {
  $("#account-type").hidden = !o.admin_signup;
  if (o.admin_signup_mode === "setup") {  // no admins yet: the first one uses ADMIN_SIGNUP_CODE and becomes super admin
    $("#admin-hint").textContent = "No admin exists yet. Enter the ADMIN_SIGNUP_CODE from the server's .env file. You'll become the super admin, the only one who can invite other admins.";
    $("#admincode-help").textContent = "After this, new admins need a one-time code from you.";
  }
}).catch(() => {});

/* Forgot password: by email code, or by recovery code */
function showRecover(on) {
  $("#login-form").hidden = on;
  $(".tabs").hidden = on;
  $("#recover").hidden = !on;
  if (on) {
    const typed = $("#l-user").value.trim();
    if (typed.includes("@")) $("#f-email").value = typed; else $("#r-user").value = typed;
    resetTarget = null;
    resetWay("email");
  } else $("#l-user").focus();
}
let resetTarget = null;  // {email} or {phone} once a code has been sent
function resetWay(way) {
  $(`input[name=reset_way][value=${way}]`).checked = true;
  const byCode = way === "email" || way === "sms";
  if (resetTarget && (("email" in resetTarget) !== (way === "email"))) resetTarget = null;  // switched channel
  $("#forgot-form").hidden = !byCode || !!resetTarget;
  $("#email-reset-form").hidden = !byCode || !resetTarget;
  $("#recover-form").hidden = byCode;
  $("#f-email-field").hidden = way !== "email";
  $("#f-phone-field").hidden = way !== "sms";
  $("#forgot-hint").textContent = way === "sms"
    ? "We'll text a 6-digit code to the mobile number on your account. It only works if you confirmed that number."
    : "We'll send a 6-digit code to the email on your account. It only works if you confirmed that email.";
  $("#e-code-label").textContent = way === "sms" ? "6-digit code from the SMS" : "6-digit code from the email";
  const focus = !byCode ? ($("#r-user").value ? $("#r-code") : $("#r-user"))
              : resetTarget ? $("#e-code") : (way === "sms" ? $("#f-phone") : $("#f-email"));
  focus.focus();
}
document.querySelectorAll("input[name=reset_way]").forEach(r => r.addEventListener("change", e => resetWay(e.target.value)));
$("#forgot-link").addEventListener("click", () => showRecover(true));
$("#back-to-login").addEventListener("click", () => showRecover(false));
fetch("/auth/options").then(r => r.json()).then(o => {
  // Offer SMS when it's set up, or on a test machine where messages print in the server window
  $("#way-sms").hidden = !(o.sms !== "console" || o.email === "console");
}).catch(() => {});

async function sendResetCode(target) {
  const r = await post("/auth/forgot", target);
  resetTarget = target;
  resetWay("phone" in target ? "sms" : "email");
  showMsg($("#email-reset-form .msg"), "", r.message);
}
$("#forgot-form").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target, msg = $(".msg", f), btn = $("button[type=submit]", f);
  const way = $("input[name=reset_way]:checked").value;
  let target;
  if (way === "sms") {
    const phone = f.phone.value.trim();
    if (phone.replace(/\D/g, "").length < 9) return showMsg(msg, "err", "Enter your mobile number, like 0712 345 678.");
    target = { phone };
  } else {
    const email = f.email.value.trim();
    if (!/^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(email)) return showMsg(msg, "err", "Enter a valid email address, like name@gmail.com.");
    target = { email };
  }
  btn.disabled = true; btn.textContent = "Sending…";
  try { await sendResetCode(target); clearMsg(msg); }
  catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.disabled = false; btn.textContent = "Send code"; }
});
$("#resend-reset").addEventListener("click", async () => {
  try { await sendResetCode(resetTarget); } catch (err) { showMsg($("#email-reset-form .msg"), "err", err.message); }
});
$("#email-reset-form").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target, msg = $(".msg", f), btn = $("button[type=submit]", f);
  if (!/^\d{6}$/.test(f.code.value.replace(/\s/g, ""))) return showMsg(msg, "err", "Enter the 6-digit code from the email.");
  if (f.password.value.length < 8) return showMsg(msg, "err", "New password must be at least 8 characters.");
  btn.disabled = true; btn.textContent = "Setting password…";
  try {
    const me = await post("/auth/reset-with-code", { ...resetTarget, code: f.code.value, new_password: f.password.value });
    showRecovery(me, "Password changed. Here is your new recovery code");
  } catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.disabled = false; btn.textContent = "Set new password"; }
});

$("#recover-form").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target, msg = $(".msg", f), btn = $("button[type=submit]", f);
  if (!f.username.value.trim() || !f.recovery_code.value.trim()) return showMsg(msg, "err", "Enter your business code and recovery code.");
  if (f.password.value.length < 8) return showMsg(msg, "err", "New password must be at least 8 characters.");
  btn.disabled = true; btn.textContent = "Setting password…";
  try {
    const me = await post("/auth/recover", { username: f.username.value.trim(), recovery_code: f.recovery_code.value, new_password: f.password.value });
    showRecovery(me, "Password changed. Here is your new recovery code");
  } catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.disabled = false; btn.textContent = "Set new password"; }
});

/* Show / hide password */
document.querySelectorAll(".pw-toggle").forEach(btn => btn.addEventListener("click", () => {
  const input = document.getElementById(btn.getAttribute("aria-controls"));
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  btn.textContent = show ? "Hide" : "Show";
  btn.setAttribute("aria-pressed", show);
}));

/* Log in */
$("#login-form").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target, msg = $(".msg", f), btn = $("button[type=submit]", f);
  if (!f.username.value.trim() || !f.password.value) return showMsg(msg, "err", "Enter your business code and password.");
  btn.disabled = true; btn.textContent = "Logging in…";
  try {
    goHome(await post("/auth/login", { username: f.username.value.trim(), password: f.password.value }), true);
  } catch (err) {
    showMsg(msg, "err", err.message);
    f.password.value = ""; f.password.focus();
  } finally { btn.disabled = false; btn.textContent = "Log in"; }
});

/* Sign up */
$("#signup-form").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target, msg = $(".msg", f), btn = $("button[type=submit]", f);
  const email = f.email.value.trim(), phone = f.phone.value.trim();
  if (!/^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(email)) return showMsg(msg, "err", "Enter a valid email address, like name@gmail.com.");
  if (phone.replace(/\D/g, "").length < 9) return showMsg(msg, "err", "Enter your mobile number, like 0712 345 678.");
  if (f.password.value.length < 8) return showMsg(msg, "err", "Password must be at least 8 characters.");
  if (!f.contact_consent.checked) return showMsg(msg, "err", "Tick the box about how we use your email and phone.");
  const contact = { email, phone, contact_consent: true };
  let path, payload;
  if (isAdminSignup()) {
    const username = f.username.value.trim().toLowerCase();
    if (!/^[a-z0-9._-]{3,40}$/.test(username)) return showMsg(msg, "err", "Admin username must be 3–40 letters, numbers, dots, dashes or underscores.");
    if (!f.admin_code.value.trim()) return showMsg(msg, "err", "Enter the admin code.");
    path = "/auth/register-admin";
    payload = { username, password: f.password.value, admin_code: f.admin_code.value, ...contact };
  } else {
    const code = f.code.value.trim().toUpperCase();
    if (!/^[A-Z0-9-]{3,20}$/.test(code)) return showMsg(msg, "err", "Business code must be 3–20 letters, numbers or dashes.");
    if (!f.consent.checked) return showMsg(msg, "err", "Tick the consent box to take part.");
    path = "/auth/register";
    payload = { code, sector: f.sector.value, password: f.password.value, consent: true, ...contact };
    if (f.start_date.value) payload.start_date = f.start_date.value + "-01";
  }
  btn.disabled = true; btn.textContent = "Sending code…"; clearMsg(msg);
  try { showConfirm(email, await post(path, payload)); }
  catch (err) { showMsg(msg, "err", err.message); }
  finally { btn.disabled = false; btn.textContent = "Continue"; }
});

/* Step 2 of sign-up: the code from the email creates the account */
let pendingEmail = "";
function showConfirm(email, r) {
  pendingEmail = email;
  $("#signup-form").hidden = true; $(".tabs").hidden = true;
  const box = $("#confirm-screen"); box.hidden = false;
  $("#cf-email").textContent = email;
  $("#cf-console").hidden = r.email_mode !== "console";
  clearMsg($(".msg", box));
  $("#cf-code").value = ""; $("#cf-code").focus();
}
$("#confirm-screen").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target, msg = $(".msg", f), btn = $("button[type=submit]", f), code = $("#cf-code").value.replace(/\D/g, "");
  if (code.length !== 6) return showMsg(msg, "err", "Enter the 6-digit code from the email.");
  btn.disabled = true; btn.textContent = "Checking…";
  try {
    const me = await post("/auth/register/confirm", { email: pendingEmail, code });
    f.hidden = true;
    showRecovery(me, "Email confirmed. Your account is ready");
  } catch (err) { showMsg(msg, "err", err.message); $("#cf-code").select(); }
  finally { btn.disabled = false; btn.textContent = "Confirm and create account"; }
});
$("#cf-code").addEventListener("input", e => {
  if (e.target.value.replace(/\D/g, "").length === 6) $("#confirm-screen").requestSubmit();
});
$("#cf-resend").addEventListener("click", async () => {
  const msg = $("#confirm-screen .msg");
  try { await post("/auth/register/resend", { email: pendingEmail }); showMsg(msg, "ok", "New code sent. The old one no longer works."); }
  catch (err) { showMsg(msg, "err", err.message); }
});
$("#cf-back").addEventListener("click", () => {
  $("#confirm-screen").hidden = true; $(".tabs").hidden = false; $("#signup-form").hidden = false;
  $("#signup-form input[name=email]").focus();
});

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
fillSectors(document.getElementById("s-sector"));
