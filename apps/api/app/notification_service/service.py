from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from html import escape
from typing import Any, Sequence

from .email_config import notification_config


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
    smtp_host: str = notification_config.smtp_host
    smtp_port: int = notification_config.smtp_port
    smtp_username: str | None = notification_config.smtp_username
    smtp_password: str | None = notification_config.smtp_password
    from_email: str = notification_config.from_email
    from_name: str = notification_config.from_name
    reply_to: str | None = notification_config.reply_to
    use_tls: bool = notification_config.use_tls
    use_ssl: bool = notification_config.use_ssl
    dry_run: bool = notification_config.dry_run
    timeout_seconds: float = notification_config.timeout_seconds


@dataclass(frozen=True)
class EmailNotificationResult:
    sent: bool
    recipients: tuple[str, ...]
    subject: str
    notification_count: int
    highest_severity: str
    transport: str
    delivered_at: datetime | None = None


def render_notifications_text(notifications: Sequence[NotificationEvent]) -> str:
    normalized_notifications = tuple(_normalize_notifications(notifications))
    if not normalized_notifications:
        raise ValueError("At least one notification event is required.")
    return _build_text_body(normalized_notifications)


def render_notifications_html(notifications: Sequence[NotificationEvent]) -> str:
    normalized_notifications = tuple(_normalize_notifications(notifications))
    if not normalized_notifications:
        raise ValueError("At least one notification event is required.")
    return _build_html_body(normalized_notifications)


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
    text_body = render_notifications_text(normalized_notifications)
    html_body = render_notifications_html(normalized_notifications)
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
        raise ValueError("SMTP host is required. Update notification_service/email_config.py or pass NotificationEmailSettings.")

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
  <body style="margin:0;padding:0;background:#f5f7f6;font-family:Segoe UI,Arial,sans-serif;color:#163041;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f7f6;">
      <tr>
        <td align="center" style="padding:24px 16px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:720px;">
            <tr>
              <td style="padding:0 0 16px 0;">
                <h1 style="margin:0;font-size:28px;line-height:1.2;">INNOTHON Notifications</h1>
              </td>
            </tr>
            {cards}
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def _render_html_card(notification: NotificationEvent) -> str:
    accent = _severity_color(notification.severity)
    turn_off_url = str(notification.metadata.get("turnOffUrl") or "").strip()
    keep_on_url = str(notification.metadata.get("keepOnUrl") or "").strip()
    sensor_state = str(notification.metadata.get("sensorState") or "").strip().lower()
    details = []
    if notification.building_name:
        details.append(f"<div><strong>Building:</strong> {escape(notification.building_name)}</div>")
    if notification.sensor_name:
        details.append(f"<div><strong>Sensor:</strong> {escape(notification.sensor_name)}</div>")
    metadata_items = {
        key: value
        for key, value in notification.metadata.items()
        if key not in {"turnOffUrl", "keepOnUrl", "sensorState"}
    }
    if metadata_items:
        metadata_rows = "".join(
            f"<li><strong>{escape(str(key))}:</strong> {escape(str(value))}</li>"
            for key, value in metadata_items.items()
        )
        details.append(f"<ul style='margin:8px 0 0 18px;padding:0;'>{metadata_rows}</ul>")

    status_html = ""
    if sensor_state == "turned_off":
        status_html = (
            "<tr>"
            "<td style=\"padding:14px 18px 0 18px;\">"
            "<div style=\"border-radius:14px;background:#fdecec;border:1px solid #e5b7b7;padding:12px 14px;"
            "font-size:13px;line-height:1.5;color:#7e2d2d;font-weight:700;\">"
            "Sensor has been turned off automatically for safety."
            "</div>"
            "</td>"
            "</tr>"
        )

    actions_html = ""
    if turn_off_url or keep_on_url:
        button_rows = []
        if turn_off_url:
            button_rows.append(
                f"<tr><td style=\"padding:0 18px 12px 18px;\"><a href=\"{escape(turn_off_url)}\" "
                "style=\"display:block;padding:12px 18px;border-radius:999px;background:#b43d3d;color:#ffffff;"
                "text-decoration:none;font-weight:700;text-align:center;\">Turn Off Sensor</a></td></tr>"
            )
        if keep_on_url:
            button_rows.append(
                f"<tr><td style=\"padding:0 18px 0 18px;\"><a href=\"{escape(keep_on_url)}\" "
                "style=\"display:block;padding:12px 18px;border-radius:999px;background:#1d6d52;color:#ffffff;"
                "text-decoration:none;font-weight:700;text-align:center;\">Keep As Is</a></td></tr>"
            )
        actions_html = (
            "<tr>"
            "<td style=\"padding:14px 18px 0 18px;\">"
            "<div style=\"border-radius:14px;background:#f7efe5;border:1px solid #ead3af;padding:12px 14px;"
            "font-size:13px;line-height:1.5;color:#6b4b12;font-weight:700;\">"
            "Choose what should happen to this sensor directly from the email."
            "</div>"
            "</td>"
            "</tr>"
            f"{''.join(button_rows)}"
        )

    details_html = "".join(details)
    return f"""\
<tr>
  <td style="padding:0 0 12px 0;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff;border:1px solid {accent};border-radius:16px;">
      <tr>
        <td style="padding:16px 18px 8px 18px;">
          <div style="font-size:12px;font-weight:700;letter-spacing:0.08em;color:{accent};text-transform:uppercase;">{escape(notification.severity)}</div>
          <h2 style="margin:6px 0 8px 0;font-size:18px;line-height:1.3;">{escape(notification.title)}</h2>
          <div style="font-size:12px;line-height:1.5;color:#5f7282;">{escape(notification.occurred_at.astimezone(timezone.utc).isoformat())}</div>
        </td>
      </tr>
      <tr>
        <td style="padding:0 18px 0 18px;">
          <p style="margin:0;color:#2a4152;line-height:1.6;">{escape(notification.message)}</p>
        </td>
      </tr>
      {status_html}
      {actions_html}
      <tr>
        <td style="padding:10px 18px 18px 18px;font-size:13px;line-height:1.6;color:#4b6475;">
          {details_html}
        </td>
      </tr>
    </table>
  </td>
</tr>
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
        client.ehlo()
        if not settings.use_ssl and settings.use_tls:
            client.starttls()
            client.ehlo()

        username = _resolved_smtp_username(settings)
        password = _resolved_smtp_password(settings)
        if username and password:
            try:
                client.login(username, password)
            except smtplib.SMTPAuthenticationError as error:
                raise ValueError("SMTP authentication failed. Check the configured email address and app password.") from error
        elif settings.smtp_username or settings.smtp_password:
            raise ValueError("Both SMTP username and SMTP password are required for authenticated email sending.")

        try:
            client.send_message(message)
        except smtplib.SMTPResponseException as error:
            raise ValueError(_smtp_response_error_message(error)) from error
        except smtplib.SMTPException as error:
            raise ValueError(f"SMTP send failed: {error}") from error


def _resolved_smtp_username(settings: NotificationEmailSettings) -> str:
    username = (settings.smtp_username or "").strip()
    from_email = (settings.from_email or "").strip()
    if username and "@" in username:
        return username
    if from_email and "@" in from_email:
        return from_email
    return username


def _resolved_smtp_password(settings: NotificationEmailSettings) -> str:
    return (settings.smtp_password or "").replace(" ", "").strip()


def _smtp_response_error_message(error: smtplib.SMTPResponseException) -> str:
    code = int(getattr(error, "smtp_code", 0) or 0)
    raw_error = getattr(error, "smtp_error", b"")
    decoded = raw_error.decode("utf-8", errors="replace") if isinstance(raw_error, (bytes, bytearray)) else str(raw_error)
    compact = " ".join(decoded.split())
    lowered = compact.lower()

    if "daily user sending limit exceeded" in lowered:
        return (
            "SMTP send failed: the configured Gmail account has exceeded its daily sending limit. "
            "Wait for the quota reset or switch INNOTHON_SMTP_USERNAME/INNOTHON_SMTP_PASSWORD to another SMTP account."
        )
    if code == 535 or "authentication failed" in lowered:
        return (
            "SMTP authentication failed. Verify INNOTHON_SMTP_USERNAME, INNOTHON_SMTP_PASSWORD, and that the mailbox allows app-password SMTP access."
        )
    if code == 530 or "starttls" in lowered:
        return "SMTP server requires TLS. Enable INNOTHON_SMTP_USE_TLS=true or verify the SMTP port/settings."
    if code == 550 and "sender" in lowered:
        return "SMTP sender rejected. Ensure INNOTHON_FROM_EMAIL matches the authenticated SMTP account."

    return f"SMTP send failed ({code}): {compact}" if compact else f"SMTP send failed with SMTP code {code}."
