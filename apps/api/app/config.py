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
        for origin in os.getenv("INNOTHON_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
        if origin.strip()
    )
    mongodb_uri: str = os.getenv("INNOTHON_MONGODB_URI", "mongodb+srv://sarangkulkarni:untu2005@cluster0.ukspo.mongodb.net/")
    mongodb_database: str = os.getenv("INNOTHON_MONGODB_DATABASE", "innothon")
    mqtt_enabled: bool = os.getenv("INNOTHON_MQTT_ENABLED", "true").lower() == "true"
    mqtt_host: str = os.getenv("INNOTHON_MQTT_HOST", "127.0.0.1")
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


settings = Settings()