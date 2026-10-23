"""Outgoing e-mail over SMTP, configured from the environment (backend/.env).

    SMTP_HOST                  mail server, e.g. smtp.gmail.com / smtp.office365.com (unset = e-mail switched off)
    SMTP_PORT                  587 for STARTTLS (default), 465 for SSL, 25 for plain
    SMTP_SECURITY              starttls (default) | ssl | none
    SMTP_USERNAME              login, if the server needs one
    SMTP_PASSWORD              password / app password for that login
    SMTP_FROM                  sender address (defaults to SMTP_USERNAME)
    SMTP_TIMEOUT_S             connect / send timeout, seconds (default 15)
    ACCESS_REQUEST_NOTIFY_TO   who is told about new sign-up requests - comma-separated addresses
    APP_BASE_URL               frontend URL used in links (default http://localhost:4300)

Sending never raises: failures are logged (without credentials or message bodies) and reported as False, so a mail
problem can't break the request that triggered it.
"""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

log = logging.getLogger(__name__)


def recipients(value: str | None) -> list[str]:
    return [a.strip() for a in (value or "").replace(";", ",").split(",") if a.strip()]


def mail_configured() -> bool:
    return bool(os.getenv("SMTP_HOST"))


def send_mail(to: list[str], subject: str, text: str, html: str | None = None) -> bool:
    host = os.getenv("SMTP_HOST")
    if not host:
        log.warning("e-mail not sent: SMTP_HOST is not set", extra={"event": "mail.skipped", "subject": subject})
        return False
    if not to:
        log.warning("e-mail not sent: no recipients", extra={"event": "mail.skipped", "subject": subject})
        return False
    security = os.getenv("SMTP_SECURITY", "starttls").lower()
    port = int(os.getenv("SMTP_PORT", "465" if security == "ssl" else "587"))
    user, password = os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM") or user
    timeout = float(os.getenv("SMTP_TIMEOUT_S", "15"))
    if not sender:
        log.warning("e-mail not sent: set SMTP_FROM (or SMTP_USERNAME)", extra={"event": "mail.skipped"})
        return False

    msg = EmailMessage()  # refuses CR/LF in headers, so user-supplied text can't inject headers
    msg["Subject"] = subject.replace("\r", " ").replace("\n", " ")
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        context = ssl.create_default_context()
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
        with server:
            if security == "starttls":
                server.starttls(context=context)
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        log.info("e-mail sent", extra={"event": "mail.sent", "subject": msg["Subject"], "recipients": len(to)})
        return True
    except (OSError, smtplib.SMTPException) as exc:
        log.error("e-mail failed", extra={"event": "mail.failed", "subject": msg["Subject"], "smtp_host": host,
                                          "error": type(exc).__name__, "message": str(exc)[:200]})
        return False
