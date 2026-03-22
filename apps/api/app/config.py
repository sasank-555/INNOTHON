from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = "INNOTHON API"
    jwt_secret: str = os.getenv("INNOTHON_JWT_SECRET", "change-me-in-production")
    jwt_algorithm: str = "HS256"
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv(
            "INNOTHON_CORS_ORIGINS",
            "*",
        ).split(",")
        if origin.strip()
    )
    mongodb_uri: str = os.getenv("INNOTHON_MONGODB_URI", "mongodb+srv://sarangkulkarni:untu2005@cluster0.ukspo.mongodb.net/")
    mongodb_database: str = os.getenv("INNOTHON_MONGODB_DATABASE", "innothon")
    mqtt_enabled: bool = os.getenv("INNOTHON_MQTT_ENABLED", "true").lower() == "true"
    mqtt_host: str = os.getenv("INNOTHON_MQTT_HOST", "172.20.249.119")
    mqtt_port: int = int(os.getenv("INNOTHON_MQTT_PORT", "1883"))
    mqtt_username: str | None = os.getenv("INNOTHON_MQTT_USERNAME")
    mqtt_password: str | None = os.getenv("INNOTHON_MQTT_PASSWORD")
    mqtt_keepalive: int = int(os.getenv("INNOTHON_MQTT_KEEPALIVE", "60"))
    mqtt_client_id: str = os.getenv("INNOTHON_MQTT_CLIENT_ID", "innothon-backend")
    mqtt_telemetry_topic: str = os.getenv("INNOTHON_MQTT_TELEMETRY_TOPIC", "devices/+/telemetry")
    mqtt_command_topic_template: str = os.getenv(
        "INNOTHON_MQTT_COMMAND_TOPIC_TEMPLATE",
        "devices/{hardware_id}/commands",
    )
    simulator_enabled: bool = os.getenv("INNOTHON_SIMULATOR_ENABLED", "false").lower() == "true"
    simulator_interval_seconds: float = float(os.getenv("INNOTHON_SIMULATOR_INTERVAL_SECONDS", "0.75"))
    simulator_stream_count: int = int(os.getenv("INNOTHON_SIMULATOR_STREAM_COUNT", "100"))
    notification_smtp_host: str = "smtp.gmail.com"
    notification_smtp_port: int = 587
    notification_smtp_username: str = "thunderking2288@gmail.com"
    notification_smtp_password: str = "jmty msrh rjep yjed"
    notification_from_email: str = "thunderking2288@gmail.com"
    notification_from_name: str = "INNOTHON Alerts"
    notification_reply_to: str | None = None
    notification_use_tls: bool = True
    notification_use_ssl: bool = False
    notification_dry_run: bool = False
    notification_timeout_seconds: float = 20.0
    notification_action_base_url: str = "http://127.0.0.1:8000/notifications/action"
    notification_action_secret: str = "replace-with-a-long-random-secret"


settings = Settings()
