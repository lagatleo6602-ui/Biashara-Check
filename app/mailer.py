"""Sends email. With no SMTP settings in .env, messages are printed in the server window instead.

.env settings for Gmail (needs a Google "app password", not your normal password):
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=you@gmail.com
    SMTP_PASSWORD=your-16-character-app-password
    MAIL_FROM=Biashara Check <you@gmail.com>
"""
import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger("uvicorn.error")
OUTBOX: list[dict] = []  # last messages, for tests and console mode


class MailError(Exception):
    pass


def configured() -> bool:
    return bool(os.getenv("SMTP_HOST", "").strip())


def mode() -> str:
    return "live" if configured() else "console"


def send(to: str, subject: str, body: str, attachments: list[tuple[str, bytes, str]] | None = None) -> None:
    """attachments: (filename, data, mime type such as "application/pdf")."""
    OUTBOX.append({"to": to, "subject": subject, "body": body,
                   "attachments": [a[0] for a in attachments or []]})
    del OUTBOX[:-500]
    if not configured():
        log.warning("EMAIL (not sent, no SMTP settings) to %s | %s\n%s", to, subject, body)
        names = ", ".join(a[0] for a in attachments or [])
        print(f"\n===== EMAIL to {to} =====\n{subject}\n\n{body}\n" + (f"[attached: {names}]\n" if names else "")
              + "==========================\n", flush=True)
        return
    msg = EmailMessage()
    msg["From"] = os.getenv("MAIL_FROM") or os.getenv("SMTP_USER")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    for name, data, mime in attachments or []:
        main, _, sub = mime.partition("/")
        msg.add_attachment(data, maintype=main, subtype=sub, filename=name)
    port = int(os.getenv("SMTP_PORT", "587"))
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(os.environ["SMTP_HOST"].strip(), port, timeout=15)
        else:
            server = smtplib.SMTP(os.environ["SMTP_HOST"].strip(), port, timeout=15)
            server.starttls()
        with server as s:
            if os.getenv("SMTP_USER"):
                s.login(os.environ["SMTP_USER"].strip(), os.getenv("SMTP_PASSWORD", "").replace(" ", ""))
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError("The email account refused the login. For Gmail, use an app password, not your normal password.") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"Couldn't send the email ({exc.__class__.__name__}). Check SMTP_HOST, SMTP_PORT and the internet connection.") from exc
    log.info("Email sent to %s: %s", to, subject)
