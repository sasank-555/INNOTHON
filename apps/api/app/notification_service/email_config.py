from __future__ import annotations

from dataclasses import dataclass

from app.config import settings


@dataclass(frozen=True)
class NotificationConfig:
    smtp_host: str = settings.notification_smtp_host
    smtp_port: int = settings.notification_smtp_port
    smtp_username: str = settings.notification_smtp_username
    smtp_password: str = settings.notification_smtp_password
    from_email: str = settings.notification_from_email
    from_name: str = settings.notification_from_name
    reply_to: str | None = settings.notification_reply_to
    use_tls: bool = settings.notification_use_tls
    use_ssl: bool = settings.notification_use_ssl
    dry_run: bool = settings.notification_dry_run
    timeout_seconds: float = settings.notification_timeout_seconds
    action_base_url: str = settings.notification_action_base_url
    action_secret: str = settings.notification_action_secret


notification_config = NotificationConfig()
