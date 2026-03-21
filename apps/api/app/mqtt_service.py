from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt
from fastapi import HTTPException
from pydantic import ValidationError

from app.config import settings
from app.schemas import DeviceCommandResponse, TelemetryPayload
from app.services import ingest_telemetry


LOGGER = logging.getLogger(__name__)


@dataclass
class MqttStatus:
    enabled: bool
    connected: bool = False
    last_message_at: str | None = None
    last_error: str | None = None


class MqttBridge:
    def __init__(self) -> None:
        self.status = MqttStatus(enabled=settings.mqtt_enabled)
        self.client: mqtt.Client | None = None

    def start(self) -> None:
        if not settings.mqtt_enabled:
            LOGGER.info("MQTT bridge disabled by configuration.")
            return

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=settings.mqtt_client_id)
        if settings.mqtt_username:
            client.username_pw_set(settings.mqtt_username, settings.mqtt_password)

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message

        try:
            client.connect(settings.mqtt_host, settings.mqtt_port, settings.mqtt_keepalive)
        except Exception as exc:
            self.status.connected = False
            self.status.last_error = str(exc)
            LOGGER.warning("MQTT bridge could not connect: %s", exc)
            self.client = client
            return

        client.loop_start()
        self.client = client

    def stop(self) -> None:
        if self.client is None:
            return
        try:
            self.client.loop_stop()
            self.client.disconnect()
        finally:
            self.status.connected = False

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: Any,
        _flags: Any,
        reason_code: mqtt.ReasonCode,
        _properties: Any,
    ) -> None:
        if reason_code.is_failure:
            self.status.connected = False
            self.status.last_error = f"MQTT connection failed: {reason_code}"
            LOGGER.warning(self.status.last_error)
            return

        client.subscribe(settings.mqtt_telemetry_topic)
        self.status.connected = True
        self.status.last_error = None
        LOGGER.info("MQTT bridge subscribed to %s", settings.mqtt_telemetry_topic)

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: Any,
        reason_code: mqtt.ReasonCode,
        _properties: Any,
    ) -> None:
        self.status.connected = False
        if reason_code != 0:
            self.status.last_error = f"MQTT disconnected: {reason_code}"
            LOGGER.warning(self.status.last_error)

    def _on_message(self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        self.process_telemetry_message(msg.topic, msg.payload.decode("utf-8"))

    def process_telemetry_message(self, topic: str, payload_text: str) -> list[DeviceCommandResponse]:
        try:
            payload = TelemetryPayload.model_validate_json(payload_text)
        except ValidationError as exc:
            self.status.last_error = f"Invalid MQTT payload on {topic}: {exc.errors()}"
            LOGGER.warning(self.status.last_error)
            return []

        try:
            commands = ingest_telemetry(
                payload.hardwareId,
                payload.deviceAuthToken,
                payload.espTimestamp,
                payload.readings,
                payload.signalStrength,
            )
        except HTTPException as exc:
            self.status.last_error = f"Rejected MQTT telemetry on {topic}: {exc.detail}"
            LOGGER.warning(self.status.last_error)
            return []

        self.status.last_message_at = datetime.now(timezone.utc).isoformat()
        self.status.last_error = None
        self.publish_commands(payload.hardwareId, commands)
        return commands

    def publish_commands(self, hardware_id: str, commands: list[DeviceCommandResponse]) -> None:
        if self.client is None or not self.status.connected or not commands:
            return

        topic = settings.mqtt_command_topic_template.format(hardware_id=hardware_id)
        payload = json.dumps(
            {
                "status": "ok",
                "serverTimestamp": datetime.now(timezone.utc).isoformat(),
                "commands": [command.model_dump() for command in commands],
            }
        )
        result = self.client.publish(topic, payload)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            self.status.last_error = f"Failed to publish commands to {topic}: {result.rc}"
            LOGGER.warning(self.status.last_error)


mqtt_bridge = MqttBridge()
