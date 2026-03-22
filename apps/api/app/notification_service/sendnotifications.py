from __future__ import annotations

import base64
import hashlib
import hmac
import json
from threading import Lock
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlencode
from uuid import uuid4

from app.database import (
    claims_collection,
    device_commands_collection,
    get_network_payload,
    sold_devices_collection,
    upsert_network_component,
    users_collection,
    utc_now,
)
from app.schemas import DeviceCommandResponse

from .email_config import notification_config
from .service import EmailNotificationResult, NotificationEmailSettings, NotificationEvent, send_notifications


SensorSeverity = Literal["green", "yellow", "red"]
NotificationAction = Literal["keep", "off", "on"]
RelayTargetState = Literal["off", "on"]

NOTIFICATION_COOLDOWN_SECONDS: dict[SensorSeverity, int] = {
    "green": 0,
    "yellow": 180,
    "red": 300,
}
_notification_throttle_lock = Lock()
_notification_throttle_by_key: dict[tuple[str, str, str], datetime] = {}


@dataclass(frozen=True)
class SafetyTrigger:
    sensor_id: str
    severity: SensorSeverity
    title: str
    message: str
    hardware_id: str | None = None
    device_id: str | None = None
    relay_number: int = 1
    building_name: str | None = None
    sensor_name: str | None = None
    network_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SafetyTriggerResult:
    severity: SensorSeverity
    emails_sent: bool
    recipient_emails: tuple[str, ...]
    auto_shutdown_queued: bool
    command_id: str | None
    action_links: dict[str, str]
    notification_result: EmailNotificationResult | None
    detail: str


@dataclass(frozen=True)
class NotificationActionResult:
    action: NotificationAction
    command_id: str | None
    relay_number: int
    hardware_id: str | None
    detail: str
    load_id: str | None = None


def handle_sensor_status_event(
    trigger: SafetyTrigger,
    *,
    email_settings: NotificationEmailSettings | None = None,
    subject_prefix: str = "[INNOTHON]",
    action_base_url: str | None = None,
) -> SafetyTriggerResult:
    """
    Backend-only safety handler.

    - red: queue automatic relay OFF and email the claimed user(s)
    - yellow: email the claimed user(s) with turn-off / keep-on choices
    - green: no action
    """
    if trigger.severity == "green":
        return SafetyTriggerResult(
            severity=trigger.severity,
            emails_sent=False,
            recipient_emails=(),
            auto_shutdown_queued=False,
            command_id=None,
            action_links={},
            notification_result=None,
            detail="Green state received; no command or email was sent.",
        )

    device = _find_device(trigger)
    recipient_emails = _claimed_user_emails(str(device["_id"]))
    if not recipient_emails:
        return SafetyTriggerResult(
            severity=trigger.severity,
            emails_sent=False,
            recipient_emails=(),
            auto_shutdown_queued=False,
            command_id=None,
            action_links={},
            notification_result=None,
            detail="No claimed user email found for this device.",
        )

    command_id = None
    auto_shutdown_queued = False
    if trigger.severity == "red":
        command_id = _queue_shutdown_if_needed(str(device["_id"]), trigger.relay_number, trigger.sensor_id)
        auto_shutdown_queued = command_id is not None

    links = _build_action_links(trigger, action_base_url) if trigger.severity == "yellow" else {}
    notification_allowed, throttle_remaining_seconds = _reserve_notification_slot(device, trigger)
    notification_error: Exception | None = None
    notification_result: EmailNotificationResult | None = None
    if notification_allowed:
        try:
            notification_result = send_notifications(
                recipients=recipient_emails,
                notifications=[
                    NotificationEvent(
                        title=trigger.title,
                        message=_notification_message(trigger, auto_shutdown_queued),
                        severity="critical" if trigger.severity == "red" else "high",
                        building_name=trigger.building_name or device.get("display_name"),
                        sensor_name=trigger.sensor_name or trigger.sensor_id,
                        network_name=trigger.network_name or device.get("network_name"),
                        metadata={
                            **trigger.metadata,
                            **links,
                            "hardwareId": device.get("hardware_id"),
                            "relayNumber": trigger.relay_number,
                            "sensorId": trigger.sensor_id,
                            "autoShutdownQueued": auto_shutdown_queued,
                            "commandId": command_id,
                            "sensorState": "turned_off" if trigger.severity == "red" else "operator_decision_required",
                        },
                    )
                ],
                settings=email_settings,
                subject_prefix=subject_prefix,
            )
        except Exception as error:
            notification_error = error

    return SafetyTriggerResult(
        severity=trigger.severity,
        emails_sent=bool(notification_result and notification_result.sent),
        recipient_emails=tuple(recipient_emails),
        auto_shutdown_queued=auto_shutdown_queued,
        command_id=command_id,
        action_links=links,
        notification_result=notification_result,
        detail=(
            f"Suppressed duplicate {trigger.severity} notification for {trigger.sensor_id}; cooldown active for {throttle_remaining_seconds}s."
            if not notification_allowed and throttle_remaining_seconds > 0
            else
            f"Processed {'red safety event' if trigger.severity == 'red' else 'yellow operator-choice event'} without email delivery: {notification_error}"
            if notification_error
            else "Processed red safety event." if trigger.severity == "red"
            else "Processed yellow operator-choice event."
        ),
    )


def apply_notification_action(action: NotificationAction, token: str) -> NotificationActionResult:
    payload = _decode_action_token(token)
    token_action = _normalize_notification_action(str(payload.get("action") or "").strip().lower())
    requested_action = _normalize_notification_action(action)
    if token_action != requested_action:
        raise ValueError("Action does not match the signed notification token.")

    relay_number = int(payload.get("relayNumber") or 1)
    sensor_id = str(payload.get("sensorId") or "sensor")
    hardware_id = str(payload.get("hardwareId") or "").strip() or None
    if requested_action == "keep":
        return NotificationActionResult(
            action="keep",
            command_id=None,
            relay_number=relay_number,
            hardware_id=hardware_id,
            load_id=None,
            detail=f"No shutdown command sent. Sensor {sensor_id} will stay in its current state.",
        )

    return apply_sensor_control_action(
        sensor_id=sensor_id,
        hardware_id=hardware_id,
        device_id=payload.get("deviceId"),
        relay_number=relay_number,
        target_state="off",
        reason=f"email_{requested_action}_action:{sensor_id}"[:120],
    )


def apply_sensor_control_action(
    *,
    sensor_id: str,
    hardware_id: str | None,
    device_id: str | None,
    relay_number: int,
    target_state: RelayTargetState,
    reason: str,
) -> NotificationActionResult:
    device = _find_device(
        SafetyTrigger(
            sensor_id=sensor_id,
            severity="yellow",
            title="Sensor control",
            message="Sensor control requested.",
            hardware_id=hardware_id,
            device_id=device_id,
            relay_number=relay_number,
        )
    )
    load_id = _set_sensor_active_state(device, sensor_id, next_is_active=target_state == "on")
    command_id = _queue_command_if_needed(
        str(device["_id"]),
        relay_number,
        target_state,
        reason=reason,
    )
    _publish_command_immediately(
        hardware_id=str(device.get("hardware_id") or ""),
        command=DeviceCommandResponse(
            commandId=command_id,
            type="relay.set",
            relayNumber=relay_number,
            targetState=target_state,
            reason=reason,
            status="pending",
        ),
    )
    return NotificationActionResult(
        action="on" if target_state == "on" else "off",
        command_id=command_id,
        relay_number=relay_number,
        hardware_id=device.get("hardware_id"),
        detail=(
            f"Turned on sensor {sensor_id} and queued relay {relay_number} ON command."
            if target_state == "on"
            else f"Turned off sensor {sensor_id} and queued relay {relay_number} OFF command."
        ),
        load_id=load_id,
    )


def _find_device(trigger: SafetyTrigger) -> dict[str, Any]:
    if trigger.device_id:
        from bson import ObjectId

        try:
            device = sold_devices_collection().find_one({"_id": ObjectId(trigger.device_id)})
        except Exception:
            device = None
        if device is not None:
            return device
    if trigger.hardware_id:
        device = sold_devices_collection().find_one({"hardware_id": trigger.hardware_id})
        if device is not None:
            return device
    raise ValueError("Unable to locate device for safety trigger.")


def _claimed_user_emails(device_id: str) -> list[str]:
    user_ids = [claim["user_id"] for claim in claims_collection().find({"device_id": device_id}) if claim.get("user_id")]
    if not user_ids:
        return []
    object_ids = []
    for user_id in user_ids:
        try:
            object_ids.append(_to_object_id(user_id))
        except Exception:
            continue
    if not object_ids:
        return []
    users = users_collection().find({"_id": {"$in": object_ids}})
    emails = []
    seen = set()
    for user in users:
        email = str(user.get("email") or "").strip()
        if not email:
            continue
        lowered = email.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        emails.append(email)
    return emails


def _queue_shutdown_if_needed(device_id: str, relay_number: int, sensor_id: str) -> str | None:
    return _queue_command_if_needed(
        device_id,
        relay_number,
        "off",
        reason=f"auto_red_shutdown:{sensor_id}"[:120],
    )


def _reserve_notification_slot(device: dict[str, Any], trigger: SafetyTrigger) -> tuple[bool, int]:
    cooldown_seconds = NOTIFICATION_COOLDOWN_SECONDS.get(trigger.severity, 0)
    if cooldown_seconds <= 0:
        return True, 0

    hardware_id = str(device.get("hardware_id") or "").strip() or str(device.get("_id") or "").strip()
    key = (hardware_id, trigger.sensor_id, trigger.severity)
    now = datetime.now(timezone.utc)
    with _notification_throttle_lock:
        last_sent_at = _notification_throttle_by_key.get(key)
        if last_sent_at is not None:
            elapsed_seconds = int((now - last_sent_at).total_seconds())
            if elapsed_seconds < cooldown_seconds:
                return False, cooldown_seconds - elapsed_seconds
        _notification_throttle_by_key[key] = now
    return True, 0


def _set_sensor_active_state(device: dict[str, Any], sensor_id: str, *, next_is_active: bool) -> str | None:
    network_name = str(device.get("network_name") or "").strip()
    if not network_name:
        return None

    manifest_item = next(
        (
            item
            for item in device.get("sensor_manifest", [])
            if str(item.get("sensorId") or "").strip() == sensor_id
        ),
        None,
    )
    if manifest_item is None:
        return None

    load_id = str(manifest_item.get("loadId") or "").strip()
    if not load_id:
        return None

    payload = get_network_payload(network_name)
    if payload is None:
        raise ValueError(f"Unable to locate network payload for {network_name}.")

    load_row = next(
        (
            dict(load)
            for load in payload.get("loads", [])
            if str(load.get("id") or "").strip() == load_id
        ),
        None,
    )
    if load_row is None:
        raise ValueError(f"Unable to locate load {load_id} for sensor {sensor_id}.")

    load_row["is_active"] = next_is_active
    upsert_network_component(network_name, "loads", load_row)
    return load_id


def _publish_command_immediately(*, hardware_id: str, command: DeviceCommandResponse) -> None:
    if not hardware_id:
        return
    try:
        from app.mqtt_service import mqtt_bridge

        mqtt_bridge.publish_commands(hardware_id, [command])
    except Exception:
        return


def _queue_command_if_needed(
    device_id: str,
    relay_number: int,
    target_state: Literal["on", "off"],
    *,
    reason: str,
) -> str:
    existing = device_commands_collection().find_one(
        {
            "sold_device_id": device_id,
            "relay_number": relay_number,
            "target_state": target_state,
            "status": "pending",
        },
        sort=[("created_at", -1)],
    )
    if existing is not None:
        return str(existing.get("command_id") or "")

    command_id = f"cmd_{uuid4().hex[:12]}"
    device_commands_collection().insert_one(
        {
            "sold_device_id": device_id,
            "command_id": command_id,
            "command_type": "relay.set",
            "relay_number": relay_number,
            "target_state": target_state,
            "reason": reason,
            "status": "pending",
            "created_at": utc_now(),
            "sent_at": None,
        }
    )
    return command_id


def _build_action_links(trigger: SafetyTrigger, action_base_url: str | None) -> dict[str, str]:
    base_url = (action_base_url or notification_config.action_base_url).strip().rstrip("/")
    if not base_url:
        return {}

    turn_off_token = _build_action_token(trigger, "off")
    keep_on_token = _build_action_token(trigger, "keep")
    return {
        "turnOffUrl": f"{base_url}?{urlencode({'action': 'off', 'token': turn_off_token})}",
        "keepOnUrl": f"{base_url}?{urlencode({'action': 'keep', 'token': keep_on_token})}",
    }


def _build_action_token(trigger: SafetyTrigger, action: NotificationAction) -> str:
    secret = notification_config.action_secret
    payload = {
        "action": action,
        "deviceId": trigger.device_id,
        "hardwareId": trigger.hardware_id,
        "sensorId": trigger.sensor_id,
        "severity": trigger.severity,
        "relayNumber": trigger.relay_number,
        "issuedAt": datetime.now(timezone.utc).isoformat(),
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    signature = hmac.new(secret.encode("utf-8"), payload_json.encode("utf-8"), hashlib.sha256).hexdigest()
    token = json.dumps({"payload": payload, "signature": signature}, separators=(",", ":"))
    return base64.urlsafe_b64encode(token.encode("utf-8")).decode("utf-8")


def _decode_action_token(token: str) -> dict[str, Any]:
    secret = notification_config.action_secret
    try:
        decoded = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        wrapper = json.loads(decoded)
        payload = dict(wrapper["payload"])
        signature = str(wrapper["signature"])
    except Exception as error:
        raise ValueError("Invalid notification action token.") from error

    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    expected_signature = hmac.new(secret.encode("utf-8"), payload_json.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("Notification action token signature is invalid.")
    return payload


def _normalize_notification_action(action: str) -> NotificationAction:
    normalized = action.strip().lower()
    if normalized == "on":
        return "keep"
    if normalized not in {"keep", "off"}:
        raise ValueError("Invalid notification action requested.")
    return normalized  # type: ignore[return-value]


def _notification_message(trigger: SafetyTrigger, auto_shutdown_queued: bool) -> str:
    if trigger.severity == "red":
        action_text = "Automatic relay shutdown has been queued." if auto_shutdown_queued else "Automatic shutdown was already pending."
        return f"{trigger.message} {action_text}"
    return f"{trigger.message} Operator decision required: keep it as is or turn it OFF."


def _to_object_id(value: str):
    from bson import ObjectId

    return ObjectId(value)
