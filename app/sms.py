"""Sends SMS. Two providers; with no settings in .env, messages are printed in the server window.

1) TextBee (https://textbee.dev): sends from YOUR Android phone's SIM. Free plan: 50 SMS/day, 300/month.
   Each SMS uses that phone's own SMS bundle/airtime.
    TEXTBEE_API_KEY=your-key          # textbee dashboard > API keys
    TEXTBEE_DEVICE_ID=                 # optional; the default phone is used if empty

2) Africa's Talking (https://africastalking.com):
    AT_USERNAME=sandbox            # "sandbox" for free testing, or your live app username
    AT_API_KEY=your-api-key        # from the Africa's Talking dashboard: Settings > API Key
    AT_SENDER_ID=                  # optional registered sender name; leave empty to use the shared short code

Sandbox messages don't reach real phones: they show in the simulator at
https://simulator.africastalking.com (log in with the same phone number).
"""
import logging
import os

import httpx

log = logging.getLogger("uvicorn.error")
OUTBOX: list[dict] = []
OK_CODES = {100, 101, 102}  # Processed, Sent, Queued


class SmsError(Exception):
    pass


def provider() -> str:
    if os.getenv("TEXTBEE_API_KEY", "").strip():
        return "textbee"
    if os.getenv("AT_USERNAME", "").strip() and os.getenv("AT_API_KEY", "").strip():
        return "africastalking"
    return "none"


def mode() -> str:
    p = provider()
    if p == "none":
        return "console"
    if p == "africastalking" and os.getenv("AT_USERNAME", "").strip() == "sandbox":
        return "sandbox"
    return "live"


def _send_textbee(to: str, message: str) -> None:
    body = {"recipients": [to], "message": message}
    device = os.getenv("TEXTBEE_DEVICE_ID", "").strip()
    if device:
        body["deviceId"] = device
    try:
        r = httpx.post("https://api.textbee.dev/api/v1/gateway/send-sms", json=body, timeout=20,
                       headers={"x-api-key": os.environ["TEXTBEE_API_KEY"].strip()})
    except httpx.HTTPError as exc:
        raise SmsError(f"Couldn't reach TextBee ({exc.__class__.__name__}). Check the internet connection.") from exc
    if r.status_code == 401:
        raise SmsError("TextBee rejected the API key. Check TEXTBEE_API_KEY in .env.")
    if r.status_code == 429:
        raise SmsError("TextBee's free limit is used up (50 a day, 300 a month). Try tomorrow, or upgrade the plan.")
    if r.status_code == 400:
        raise SmsError("TextBee couldn't use your phone. Open the TextBee app, make sure the phone is online, "
                       "enabled and has SMS permission, then try again.")
    if r.status_code >= 300:
        raise SmsError(f"TextBee refused the SMS (HTTP {r.status_code}): {r.text[:150]}")
    data = (r.json() or {}).get("data", {}) if r.headers.get("content-type", "").startswith("application/json") else {}
    if data.get("success") is False or data.get("failureCount"):
        raise SmsError(f"TextBee couldn't send the SMS: {data.get('message', 'no reason given')}")
    log.info("SMS handed to TextBee for %s", to)


def _endpoint() -> str:
    host = "api.sandbox.africastalking.com" if mode() == "sandbox" else "api.africastalking.com"
    return f"https://{host}/version1/messaging"


def send(to: str, message: str) -> None:
    """to: +2547XXXXXXXX. Raises SmsError with a readable reason if the gateway refuses."""
    OUTBOX.append({"to": to, "message": message})
    del OUTBOX[:-500]
    if mode() == "console":
        log.warning("SMS (not sent, no SMS settings) to %s: %s", to, message)
        print(f"\n===== SMS to {to} =====\n{message}\n========================\n", flush=True)
        return
    if provider() == "textbee":
        return _send_textbee(to, message)
    data = {"username": os.environ["AT_USERNAME"].strip(), "to": to, "message": message}
    sender = os.getenv("AT_SENDER_ID", "").strip()
    if sender:
        data["from"] = sender
    try:
        r = httpx.post(_endpoint(), data=data, timeout=15,
                       headers={"apiKey": os.environ["AT_API_KEY"].strip(), "Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise SmsError(f"Couldn't reach Africa's Talking ({exc.__class__.__name__}). Check the internet connection.") from exc
    if r.status_code == 401:
        raise SmsError("Africa's Talking rejected the API key or username. Check AT_USERNAME and AT_API_KEY in .env.")
    try:
        recipients = r.json()["SMSMessageData"]["Recipients"]
    except Exception as exc:
        raise SmsError(f"Unexpected reply from Africa's Talking (HTTP {r.status_code}): {r.text[:150]}") from exc
    if not recipients:
        raise SmsError(f"Africa's Talking didn't accept the message: {r.json()['SMSMessageData'].get('Message', 'no reason given')}")
    rec = recipients[0]
    if rec.get("statusCode") not in OK_CODES and rec.get("status") != "Success":
        hints = {"InsufficientBalance": " Top up your Africa's Talking account.",
                 "InvalidSenderId": " Remove AT_SENDER_ID or use one approved on your account.",
                 "InvalidPhoneNumber": " Check the number."}
        raise SmsError(f"SMS not sent: {rec.get('status')}." + hints.get(rec.get("status", ""), ""))
    log.info("SMS sent to %s (%s, cost %s)", to, rec.get("status"), rec.get("cost"))
