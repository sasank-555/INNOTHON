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
from app.database import sold_devices_collection
from app.schemas import DeviceCommandResponse, TelemetryPayload, TelemetryReading
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
        payload = self._parse_telemetry_payload(topic, payload_text)
        if payload is None:
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
        device = sold_devices_collection().find_one({"hardware_id": hardware_id}) or {}
        if str(device.get("mqtt_command_mode") or "").strip() == "plain-text-relay":
            payload = commands[-1].targetState.upper()
        else:
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

    def _parse_telemetry_payload(self, topic: str, payload_text: str) -> TelemetryPayload | None:
        try:
            return TelemetryPayload.model_validate_json(payload_text)
        except ValidationError:
            pass

        try:
            payload_data = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            self.status.last_error = f"Invalid MQTT payload on {topic}: {exc}"
            LOGGER.warning(self.status.last_error)
            return None

        hardware_id = self._hardware_id_from_topic(topic)
        if not hardware_id:
            self.status.last_error = f"Unable to infer hardware id from MQTT topic {topic}"
            LOGGER.warning(self.status.last_error)
            return None

        device = sold_devices_collection().find_one({"hardware_id": hardware_id})
        if device is None:
            self.status.last_error = f"Unknown MQTT hardware id {hardware_id} on {topic}"
            LOGGER.warning(self.status.last_error)
            return None

        manifest_item = next(iter(device.get("sensor_manifest") or []), None)
        if manifest_item is None:
            self.status.last_error = f"No sensor manifest configured for MQTT hardware id {hardware_id}"
            LOGGER.warning(self.status.last_error)
            return None

        power_value = self._number_or_none(payload_data.get("power"))
        voltage_value = self._number_or_none(payload_data.get("v_adc"))
        current_value = self._number_or_none(payload_data.get("current"))
        if power_value is None:
            self.status.last_error = f"MQTT payload for {hardware_id} is missing `power`."
            LOGGER.warning(self.status.last_error)
            return None

        relay_raw = payload_data.get("relay")
        relay_state = "on" if bool(relay_raw) else "off"
        try:
            return TelemetryPayload(
                hardwareId=hardware_id,
                deviceAuthToken=str(device.get("device_auth_token") or ""),
                espTimestamp=None,
                signalStrength=None,
                readings=[
                    TelemetryReading(
                        sensorId=str(manifest_item.get("sensorId") or ""),
                        sensorType=str(manifest_item.get("sensorType") or "p_mw"),
                        value=float(power_value),
                        unit=str(manifest_item.get("unit") or "MW"),
                        relayState=relay_state,
                        metadata={
                            "source": "mqtt-real-sensor",
                            "vAdc": voltage_value,
                            "currentA": current_value,
                            "powerRaw": power_value,
                            "hardwareId": hardware_id,
                        },
                    )
                ],
            )
        except ValidationError as exc:
            self.status.last_error = f"Invalid translated MQTT payload on {topic}: {exc.errors()}"
            LOGGER.warning(self.status.last_error)
            return None

    def _hardware_id_from_topic(self, topic: str) -> str | None:
        segments = [segment for segment in topic.split("/") if segment]
        if len(segments) >= 3 and segments[0] == "devices" and segments[2] == "telemetry":
            return segments[1]
        return None

    def _number_or_none(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


mqtt_bridge = MqttBridge()
