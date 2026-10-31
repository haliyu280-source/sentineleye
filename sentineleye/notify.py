"""Optional e-mail notifications for alerts.

Messages are queued while a request or job runs and only sent after the database commit,
so a rolled-back alert never sends mail. Delivery happens on a background thread; failures
are logged and never affect monitoring.
"""

import logging
import smtplib
import threading
from dataclasses import dataclass
from email.message import EmailMessage

from .config import Settings, get_settings

log = logging.getLogger("sentineleye.notify")

_pending = threading.local()


@dataclass(frozen=True)
class Notification:
    subject: str
    body: str


def queue_notification(alert, server, event: str) -> None:
    if not get_settings().email_enabled:
        return
    if event == "opened":
        subject = f"[SentinelEye] {alert.severity.upper()}: {server.name}: {alert.message}"
    else:
        subject = f"[SentinelEye] RECOVERED: {server.name}: {alert.kind.replace('_', ' ')}"
    body = (
        f"Server: {server.name} ({server.hostname or 'hostname not reported'})\n"
        f"Alert: {alert.kind}  status: {alert.status}\n"
        f"Message: {alert.message}\n"
        f"Opened: {alert.opened_at.isoformat()}\n"
    )
    if alert.resolved_at:
        body += f"Resolved: {alert.resolved_at.isoformat()}\n"
    if not hasattr(_pending, "items"):
        _pending.items = []
    _pending.items.append(Notification(subject, body))


def discard_pending() -> None:
    _pending.items = []


def flush_pending() -> None:
    """Send queued notifications. Call after a successful commit."""
    items = getattr(_pending, "items", [])
    _pending.items = []
    if items:
        threading.Thread(target=_send_all, args=(items, get_settings()), daemon=True).start()


def _send_all(items: list[Notification], settings: Settings) -> None:
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            for item in items:
                msg = EmailMessage()
                msg["From"] = settings.smtp_from
                msg["To"] = ", ".join(settings.smtp_recipients)
                msg["Subject"] = item.subject
                msg.set_content(item.body)
                smtp.send_message(msg)
        log.info("Sent %d alert e-mail(s)", len(items))
    except Exception as exc:  # delivery problems must never break monitoring
        log.error("Alert e-mail delivery failed: %s", exc.__class__.__name__)
