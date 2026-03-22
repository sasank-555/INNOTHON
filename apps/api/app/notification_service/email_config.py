from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationConfig:
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = "sarangkulkarni1104@gmail.com"
    smtp_password: str = "xwxx nluz cdwg ochq"
    from_email: str = "sarangkulkarni1104@gmail.com"
    from_name: str = "INNOTHON Alerts"
    reply_to: str | None = None
    use_tls: bool = True
    use_ssl: bool = False
    dry_run: bool = False
    timeout_seconds: float = 20.0
    action_base_url: str = "http://127.0.0.1:8000/notifications/action"
    action_secret: str = "replace-with-a-long-random-secret"


notification_config = NotificationConfig()
