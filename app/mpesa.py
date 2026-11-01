"""M-Pesa Express (STK Push) through Safaricom Daraja.

Settings in .env:
    MPESA_ENV=sandbox                 # sandbox (free testing) or production
    MPESA_CONSUMER_KEY=...            # from your app on developer.safaricom.co.ke
    MPESA_CONSUMER_SECRET=...
    MPESA_SHORTCODE=                  # sandbox: leave empty to use Safaricom's test Paybill 174379
    MPESA_PASSKEY=                    # sandbox: leave empty to use Safaricom's public test passkey
    MPESA_TILL=                       # only for a Buy Goods till (then MPESA_SHORTCODE is the store number)
    MPESA_CALLBACK_URL=               # optional public https address of this app, e.g. an ngrok URL

Without a consumer key the app runs in TEST mode: no request goes to Safaricom and payments
succeed straight away, clearly marked "test", so the flow can be demonstrated offline.

The app doesn't need the callback to work: it asks Daraja for the result (STK Push Query)
while the owner waits. If MPESA_CALLBACK_URL is set, Safaricom also calls us back,
which adds the M-Pesa receipt number.
"""
import base64
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

log = logging.getLogger("uvicorn.error")
EAT = timezone(timedelta(hours=3))

# Safaricom's published sandbox test values (not secrets: they're in the Daraja docs for everyone)
SANDBOX_SHORTCODE = "174379"
SANDBOX_PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"

FRIENDLY = {
    "1032": "You cancelled the M-Pesa prompt. Nothing was paid.",
    "1037": "The phone didn't respond in time. Make sure it's on and unlocked, then try again.",
    "1": "Not enough money in M-Pesa to pay. Nothing was paid.",
    "2001": "Wrong M-Pesa PIN. Nothing was paid. Try again.",
    "1001": "Another M-Pesa payment is in progress on that phone. Wait a minute, then try again.",
    "1019": "The payment request expired. Try again.",
    "1025": "M-Pesa couldn't send the prompt. Try again.",
    "9999": "M-Pesa couldn't send the prompt. Try again.",
}


class MpesaError(Exception):
    pass


def mode() -> str:
    """test (no keys), sandbox, or live."""
    if not (os.getenv("MPESA_CONSUMER_KEY", "").strip() and os.getenv("MPESA_CONSUMER_SECRET", "").strip()):
        return "test"
    return "live" if os.getenv("MPESA_ENV", "sandbox").strip().lower() == "production" else "sandbox"


def _base() -> str:
    return "https://api.safaricom.co.ke" if mode() == "live" else "https://sandbox.safaricom.co.ke"


def shortcode() -> str:
    code = os.getenv("MPESA_SHORTCODE", "").strip()
    return code or (SANDBOX_SHORTCODE if mode() != "live" else "")


def _passkey() -> str:
    key = os.getenv("MPESA_PASSKEY", "").strip()
    return key or (SANDBOX_PASSKEY if mode() != "live" else "")


def till() -> str:
    return os.getenv("MPESA_TILL", "").strip()


def callback_secret() -> str:
    """Random path part so strangers can't post fake payment results to the callback."""
    env = os.getenv("MPESA_CALLBACK_SECRET", "").strip()
    if env:
        return env
    path = Path("instance") / "mpesa_callback.secret"
    if path.exists():
        return path.read_text().strip()
    path.parent.mkdir(exist_ok=True)
    value = secrets.token_urlsafe(24)
    path.write_text(value)
    return value


CALLBACK_PATH = "/payments/mpesa/callback/"
NGROK_API = "http://127.0.0.1:4040/api/tunnels"   # ngrok's local status page, only reachable on this computer
_ngrok_cache: dict = {"url": "", "at": 0.0}


def _ngrok_url() -> str:
    """If ngrok is running on this computer, the public https address it gives the app (checked every 30 s)."""
    if time.time() - _ngrok_cache["at"] < 30:
        return _ngrok_cache["url"]
    url = ""
    try:
        r = httpx.get(NGROK_API, timeout=1.5)
        tunnels = r.json().get("tunnels", []) if r.status_code == 200 else []
        port = os.getenv("APP_PORT", "8000")
        https = [t for t in tunnels if str(t.get("public_url", "")).startswith("https://")]
        mine = [t for t in https if str((t.get("config") or {}).get("addr", "")).rstrip("/").endswith(":" + port)]
        if mine or https:
            url = (mine or https)[0]["public_url"].rstrip("/")
    except Exception:  # ngrok not running, or not reachable
        url = ""
    _ngrok_cache.update(url=url, at=time.time())
    return url


def callback_base() -> tuple[str, str]:
    """(public base address, where it came from: "env", "ngrok" or "")."""
    env = os.getenv("MPESA_CALLBACK_URL", "").strip().rstrip("/")
    if env:
        return env, "env"
    found = _ngrok_url()
    return (found, "ngrok") if found else ("", "")


def callback_url() -> str:
    base, _ = callback_base()
    if base:
        return f"{base}{CALLBACK_PATH}{callback_secret()}"
    # Daraja insists on an https URL even when we only use STK Push Query, so give a harmless one.
    return "https://example.com/mpesa-callback-not-set"


_token: dict = {"value": "", "until": 0.0}


def _access_token() -> str:
    if _token["value"] and time.time() < _token["until"]:
        return _token["value"]
    try:
        r = httpx.get(f"{_base()}/oauth/v1/generate", params={"grant_type": "client_credentials"}, timeout=20,
                      auth=(os.environ["MPESA_CONSUMER_KEY"].strip(), os.environ["MPESA_CONSUMER_SECRET"].strip()))
    except httpx.HTTPError as exc:
        raise MpesaError(f"Couldn't reach Safaricom ({exc.__class__.__name__}). Check the internet connection.") from exc
    if r.status_code in (400, 401):
        raise MpesaError("Safaricom rejected the consumer key or secret. Check MPESA_CONSUMER_KEY and "
                         "MPESA_CONSUMER_SECRET in .env (and that MPESA_ENV matches the app: sandbox or production).")
    if r.status_code != 200:
        raise MpesaError(f"Safaricom login failed (error {r.status_code}). Try again in a minute.")
    data = r.json()
    _token["value"] = data["access_token"]
    _token["until"] = time.time() + int(data.get("expires_in", 3599)) - 60
    return _token["value"]


def _password(ts: str) -> str:
    return base64.b64encode(f"{shortcode()}{_passkey()}{ts}".encode()).decode()


def _post(path: str, body: dict) -> httpx.Response:
    try:
        return httpx.post(f"{_base()}{path}", json=body, timeout=30,
                          headers={"Authorization": f"Bearer {_access_token()}"})
    except httpx.HTTPError as exc:
        raise MpesaError(f"Couldn't reach Safaricom ({exc.__class__.__name__}). Check the internet connection.") from exc


def stk_push(phone: str, amount: int, account_ref: str, description: str) -> dict:
    """Sends the PIN prompt to the phone. Returns {checkout_id, merchant_request_id, message}.
    phone is +2547XXXXXXXX."""
    msisdn = phone.lstrip("+")
    if mode() == "test":
        log.info("[M-Pesa TEST] STK Push of KES %s to %s for %s (not sent: no Daraja keys in .env)",
                 amount, msisdn[:6] + "•••", account_ref)
        return {"checkout_id": "ws_TEST_" + secrets.token_hex(8), "merchant_request_id": "TEST",
                "message": "Test mode: no prompt is sent and no money moves."}
    if mode() == "live" and not (shortcode() and _passkey()):
        raise MpesaError("Set MPESA_SHORTCODE and MPESA_PASSKEY in .env for production.")
    ts = datetime.now(EAT).strftime("%Y%m%d%H%M%S")
    body = {
        "BusinessShortCode": shortcode(),
        "Password": _password(ts),
        "Timestamp": ts,
        "TransactionType": "CustomerBuyGoodsOnline" if till() else "CustomerPayBillOnline",
        "Amount": int(amount),
        "PartyA": msisdn,
        "PartyB": till() or shortcode(),
        "PhoneNumber": msisdn,
        "CallBackURL": callback_url(),
        "AccountReference": account_ref[:12],
        "TransactionDesc": description[:13],
    }
    r = _post("/mpesa/stkpush/v1/processrequest", body)
    data = _json(r)
    if r.status_code != 200 or str(data.get("ResponseCode")) != "0":
        msg = data.get("errorMessage") or data.get("ResponseDescription") or f"error {r.status_code}"
        if "Invalid Access Token" in msg:
            _token["value"] = ""
        raise MpesaError(f"M-Pesa didn't accept the request: {msg}")
    return {"checkout_id": data["CheckoutRequestID"], "merchant_request_id": data.get("MerchantRequestID", ""),
            "message": data.get("CustomerMessage", "")}


def stk_query(checkout_id: str) -> dict:
    """Asks Daraja how the payment went. Returns {state: pending|paid|failed|cancelled, desc}."""
    if checkout_id.startswith("ws_TEST_"):
        return {"state": "paid", "desc": "Test payment (no money moved)."}
    if mode() == "test":  # a real M-Pesa payment, but the keys are gone: never guess
        raise MpesaError("M-Pesa keys aren't set in .env, so this payment can't be checked. Add them and restart the server.")
    ts = datetime.now(EAT).strftime("%Y%m%d%H%M%S")
    r = _post("/mpesa/stkpushquery/v1/query",
              {"BusinessShortCode": shortcode(), "Password": _password(ts), "Timestamp": ts,
               "CheckoutRequestID": checkout_id})
    data = _json(r)
    if "ResultCode" in data:
        return result(str(data["ResultCode"]), data.get("ResultDesc", ""))
    msg = str(data.get("errorMessage", ""))
    if "being processed" in msg.lower() or r.status_code in (500, 503):
        return {"state": "pending", "desc": "Waiting for the PIN."}
    if r.status_code == 429:
        return {"state": "pending", "desc": "Waiting for M-Pesa."}
    return {"state": "pending", "desc": msg or f"M-Pesa error {r.status_code}"}


STILL_PROCESSING = {"4999", "500.001.1001"}


def result(code: str, desc: str) -> dict:
    if code == "0":
        return {"state": "paid", "desc": "Paid."}
    # "The transaction is still under processing": not an answer yet, keep waiting
    if code in STILL_PROCESSING or any(w in (desc or "").lower() for w in ("under processing", "being processed")):
        return {"state": "pending", "desc": "M-Pesa is still processing the payment."}
    state = "cancelled" if code == "1032" else "failed"
    return {"state": state, "desc": FRIENDLY.get(code, desc or "The payment didn't go through.")}


def _json(r: httpx.Response) -> dict:
    try:
        data = r.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def check_connection() -> dict:
    """Logs in to Daraja with the keys in .env, without charging anything."""
    if mode() == "test":
        return {"ok": False, "mode": "test", "message": "No Daraja keys in .env, so M-Pesa runs in test mode. "
                "Add MPESA_CONSUMER_KEY and MPESA_CONSUMER_SECRET to .env (not .env.example), then restart the server."}
    _token.update(value="", until=0)
    try:
        _access_token()
    except MpesaError as exc:
        return {"ok": False, "mode": mode(), "message": str(exc)}
    where = "Safaricom sandbox" if mode() == "sandbox" else "Safaricom (live)"
    return {"ok": True, "mode": mode(), "message": f"Connected to {where}. Shortcode {shortcode()}"
            + (f", till {till()}" if till() else "") + ". Payments will send real PIN prompts."}
