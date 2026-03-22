from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from html import escape
from typing import Any, Sequence


SEVERITY_RANK = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


@dataclass(frozen=True)
class NotificationEvent:
    title: str
    message: str
    severity: str = "info"
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    building_name: str | None = None
    sensor_name: str | None = None
    network_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NotificationEmailSettings:
    smtp_host: str = os.getenv("INNOTHON_SMTP_HOST", "")
    smtp_port: int = int(os.getenv("INNOTHON_SMTP_PORT", "587"))
    smtp_username: str | None = os.getenv("INNOTHON_SMTP_USERNAME")
    smtp_password: str | None = os.getenv("INNOTHON_SMTP_PASSWORD")
    from_email: str = os.getenv("INNOTHON_NOTIFICATION_FROM_EMAIL", "alerts@innothon.local")
    from_name: str = os.getenv("INNOTHON_NOTIFICATION_FROM_NAME", "INNOTHON Alerts")
    reply_to: str | None = os.getenv("INNOTHON_NOTIFICATION_REPLY_TO")
    use_tls: bool = os.getenv("INNOTHON_SMTP_USE_TLS", "true").lower() == "true"
    use_ssl: bool = os.getenv("INNOTHON_SMTP_USE_SSL", "false").lower() == "true"
    dry_run: bool = os.getenv("INNOTHON_NOTIFICATION_DRY_RUN", "false").lower() == "true"
    timeout_seconds: float = float(os.getenv("INNOTHON_SMTP_TIMEOUT_SECONDS", "20"))


@dataclass(frozen=True)
class EmailNotificationResult:
    sent: bool
    recipients: tuple[str, ...]
    subject: str
    notification_count: int
    highest_severity: str
    transport: str
    delivered_at: datetime | None = None


def send_notifications(
    recipients: Sequence[str],
    notifications: Sequence[NotificationEvent],
    *,
    settings: NotificationEmailSettings | None = None,
    subject_prefix: str = "[INNOTHON]",
) -> EmailNotificationResult:
    """
    Send one email containing a batch of notifications.

    This function is intentionally backend-only and standalone:
    it does not register endpoints or mutate existing app services.
    """
    normalized_recipients = tuple(_normalize_recipients(recipients))
    normalized_notifications = tuple(_normalize_notifications(notifications))
    if not normalized_recipients:
        raise ValueError("At least one recipient email is required.")
    if not normalized_notifications:
        raise ValueError("At least one notification event is required.")

    mail_settings = settings or NotificationEmailSettings()
    highest_severity = _highest_severity(normalized_notifications)
    subject = _build_subject(subject_prefix, highest_severity, normalized_notifications)
    text_body = _build_text_body(normalized_notifications)
    html_body = _build_html_body(normalized_notifications)
    message = _build_message(
        recipients=normalized_recipients,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        settings=mail_settings,
    )

    if mail_settings.dry_run:
        return EmailNotificationResult(
            sent=False,
            recipients=normalized_recipients,
            subject=subject,
            notification_count=len(normalized_notifications),
            highest_severity=highest_severity,
            transport="dry-run",
        )

    if not mail_settings.smtp_host:
        raise ValueError("SMTP host is required. Set INNOTHON_SMTP_HOST or pass NotificationEmailSettings.")

    _send_message(message, mail_settings)
    return EmailNotificationResult(
        sent=True,
        recipients=normalized_recipients,
        subject=subject,
        notification_count=len(normalized_notifications),
        highest_severity=highest_severity,
        transport="smtp-ssl" if mail_settings.use_ssl else "smtp-starttls" if mail_settings.use_tls else "smtp",
        delivered_at=datetime.now(timezone.utc),
    )


def _normalize_recipients(recipients: Sequence[str]) -> list[str]:
    unique_recipients: list[str] = []
    seen: set[str] = set()
    for recipient in recipients:
        email = recipient.strip()
        if not email:
            continue
        lowered = email.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique_recipients.append(email)
    return unique_recipients


def _normalize_notifications(notifications: Sequence[NotificationEvent]) -> list[NotificationEvent]:
    normalized: list[NotificationEvent] = []
    for notification in notifications:
        severity = notification.severity.lower().strip() or "info"
        if severity not in SEVERITY_RANK:
            severity = "info"
        normalized.append(
            NotificationEvent(
                title=notification.title.strip(),
                message=notification.message.strip(),
                severity=severity,
                occurred_at=notification.occurred_at,
                building_name=notification.building_name,
                sensor_name=notification.sensor_name,
                network_name=notification.network_name,
                metadata=dict(notification.metadata),
            )
        )
    return normalized


def _highest_severity(notifications: Sequence[NotificationEvent]) -> str:
    return max(notifications, key=lambda item: SEVERITY_RANK.get(item.severity, 0)).severity


def _build_subject(
    subject_prefix: str,
    highest_severity: str,
    notifications: Sequence[NotificationEvent],
) -> str:
    network_name = next((item.network_name for item in notifications if item.network_name), "Network")
    if len(notifications) == 1:
        return f"{subject_prefix} {highest_severity.upper()} {network_name}: {notifications[0].title}"
    return f"{subject_prefix} {highest_severity.upper()} {network_name}: {len(notifications)} notifications"


def _build_message(
    *,
    recipients: Sequence[str],
    subject: str,
    text_body: str,
    html_body: str,
    settings: NotificationEmailSettings,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{settings.from_name} <{settings.from_email}>"
    message["To"] = ", ".join(recipients)
    if settings.reply_to:
        message["Reply-To"] = settings.reply_to
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    return message


def _build_text_body(notifications: Sequence[NotificationEvent]) -> str:
    lines = [
        "INNOTHON notification batch",
        "",
    ]
    for index, notification in enumerate(notifications, start=1):
        lines.extend(
            [
                f"{index}. [{notification.severity.upper()}] {notification.title}",
                f"   Time: {notification.occurred_at.astimezone(timezone.utc).isoformat()}",
                f"   Message: {notification.message}",
            ]
        )
        if notification.building_name:
            lines.append(f"   Building: {notification.building_name}")
        if notification.sensor_name:
            lines.append(f"   Sensor: {notification.sensor_name}")
        if notification.metadata:
            lines.append(f"   Metadata: {notification.metadata}")
        lines.append("")
    return "\n".join(lines).strip()


def _build_html_body(notifications: Sequence[NotificationEvent]) -> str:
    cards = "\n".join(_render_html_card(notification) for notification in notifications)
    return f"""\
<html>
  <body style="margin:0;padding:24px;background:#f5f7f6;font-family:Segoe UI,Arial,sans-serif;color:#163041;">
    <div style="max-width:720px;margin:0 auto;">
      <h1 style="margin:0 0 16px;">INNOTHON Notifications</h1>
      <div style="display:grid;gap:12px;">
        {cards}
      </div>
    </div>
  </body>
</html>
"""


def _render_html_card(notification: NotificationEvent) -> str:
    accent = _severity_color(notification.severity)
    details = []
    if notification.building_name:
        details.append(f"<div><strong>Building:</strong> {escape(notification.building_name)}</div>")
    if notification.sensor_name:
        details.append(f"<div><strong>Sensor:</strong> {escape(notification.sensor_name)}</div>")
    if notification.metadata:
        metadata_rows = "".join(
            f"<li><strong>{escape(str(key))}:</strong> {escape(str(value))}</li>"
            for key, value in notification.metadata.items()
        )
        details.append(f"<ul style='margin:8px 0 0 18px;padding:0;'>{metadata_rows}</ul>")

    details_html = "".join(details)
    return f"""\
<section style="background:#ffffff;border:1px solid {accent};border-radius:16px;padding:16px 18px;">
  <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">
    <div>
      <div style="font-size:12px;font-weight:700;letter-spacing:0.08em;color:{accent};text-transform:uppercase;">{escape(notification.severity)}</div>
      <h2 style="margin:6px 0 8px;font-size:18px;">{escape(notification.title)}</h2>
    </div>
    <div style="font-size:12px;color:#5f7282;">{escape(notification.occurred_at.astimezone(timezone.utc).isoformat())}</div>
  </div>
  <p style="margin:0;color:#2a4152;line-height:1.5;">{escape(notification.message)}</p>
  <div style="margin-top:10px;font-size:13px;color:#4b6475;">{details_html}</div>
</section>
"""


def _severity_color(severity: str) -> str:
    return {
        "info": "#2f61bd",
        "low": "#2f61bd",
        "medium": "#a86f10",
        "high": "#c45832",
        "critical": "#b43d3d",
    }.get(severity, "#2f61bd")


def _send_message(message: EmailMessage, settings: NotificationEmailSettings) -> None:
    smtp_class = smtplib.SMTP_SSL if settings.use_ssl else smtplib.SMTP
    with smtp_class(settings.smtp_host, settings.smtp_port, timeout=settings.timeout_seconds) as client:
        if not settings.use_ssl and settings.use_tls:
            client.starttls()
        if settings.smtp_username and settings.smtp_password:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)
