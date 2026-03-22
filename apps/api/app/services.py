from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException, status

from app.database import (
    claims_collection,
    device_commands_collection,
    parse_object_id,
    sensor_readings_collection,
    sold_devices_collection,
    users_collection,
    utc_now,
)
from app.live_feed import live_feed_broker
from app.schemas import (
    DeviceCommandCreateRequest,
    DeviceCommandResponse,
    DeviceSummary,
    ReadingResponse,
    UserResponse,
)
from app.security import create_access_token, hash_password, issue_device_token, verify_password


def register_user(email: str, password: str) -> tuple[str, UserResponse]:
    users = users_collection()
    existing = users.find_one({"email": email})
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")

    result = users.insert_one(
        {
            "email": email,
            "password_hash": hash_password(password),
            "created_at": utc_now(),
        }
    )
    user_id = str(result.inserted_id)
    token = create_access_token(user_id, email)
    return token, UserResponse(id=user_id, email=email)


def login_user(email: str, password: str) -> tuple[str, UserResponse]:
    user = users_collection().find_one({"email": email})
    if user is None or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")
    token = create_access_token(str(user["_id"]), user["email"])
    return token, UserResponse(id=str(user["_id"]), email=user["email"])


def claim_device(user_id: str, hardware_id: str, manufacturer_password: str) -> DeviceSummary:
    devices = sold_devices_collection()
    device = devices.find_one({"hardware_id": hardware_id})
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found.")
    if not verify_password(manufacturer_password, device["manufacturer_password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Manufacturer password is incorrect.",
        )

    device_token = device.get("device_auth_token") or issue_device_token()
    claims_collection().update_one(
        {"user_id": user_id, "device_id": str(device["_id"])},
        {
            "$setOnInsert": {
                "user_id": user_id,
                "device_id": str(device["_id"]),
                "claimed_at": utc_now(),
            }
        },
        upsert=True,
    )
    devices.update_one(
        {"_id": device["_id"]},
        {
            "$set": {
                "claim_status": "claimed",
                "device_auth_token": device_token,
                "updated_at": utc_now(),
            }
        },
    )
    return get_device_summary(str(device["_id"]), user_id, include_token=True)


def create_device_command(user_id: str, device_id: str, payload: DeviceCommandCreateRequest) -> DeviceCommandResponse:
    ensure_device_access(device_id, user_id)
    command_id = f"cmd_{uuid4().hex[:12]}"
    device_commands_collection().insert_one(
        {
            "sold_device_id": device_id,
            "command_id": command_id,
            "command_type": "relay.set",
            "relay_number": payload.relayNumber,
            "target_state": payload.targetState,
            "reason": payload.reason,
            "status": "pending",
            "created_at": utc_now(),
            "sent_at": None,
        }
    )
    return DeviceCommandResponse(
        commandId=command_id,
        type="relay.set",
        relayNumber=payload.relayNumber,
        targetState=payload.targetState,
        reason=payload.reason,
        status="pending",
    )


def ingest_telemetry(
    hardware_id: str,
    device_auth_token: str,
    esp_timestamp: datetime | None,
    readings: list,
    signal_strength: int | None,
) -> list[DeviceCommandResponse]:
    received_at = datetime.now(timezone.utc).isoformat()
    device = sold_devices_collection().find_one({"hardware_id": hardware_id})
    if device is None or device.get("device_auth_token") != device_auth_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device credentials.")

    manifest_index = _sensor_manifest_index(device)
    unknown_sensor_ids = sorted(
        {
            reading.sensorId
            for reading in readings
            if reading.sensorId not in manifest_index
        }
    )
    if unknown_sensor_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown sensor ids for {hardware_id}: {', '.join(unknown_sensor_ids)}",
        )

    telemetry_docs = []
    live_updates = []
    for reading in readings:
        manifest_item = manifest_index.get(reading.sensorId, {})
        metadata = {
            "buildingHardwareId": hardware_id,
            "nodeKind": device.get("node_kind"),
        }
        if signal_strength is not None:
            metadata["signalStrength"] = signal_strength
        if manifest_item.get("loadId"):
            metadata["loadId"] = manifest_item["loadId"]
        if manifest_item.get("buildingId"):
            metadata["buildingId"] = manifest_item["buildingId"]
        if manifest_item.get("measurement"):
            metadata["measurement"] = manifest_item["measurement"]
        if manifest_item.get("busId"):
            metadata["busId"] = manifest_item["busId"]
        if reading.metadata:
            metadata.update(reading.metadata)
        telemetry_docs.append(
            {
                "sold_device_id": str(device["_id"]),
                "sensor_id": reading.sensorId,
                "sensor_type": reading.sensorType,
                "reading_value": reading.value,
                "unit": reading.unit,
                "relay_state": reading.relayState,
                "esp_timestamp": esp_timestamp.isoformat() if esp_timestamp else None,
                "server_received_at": received_at,
                "metadata_json": metadata,
            }
        )
        live_updates.append(
            {
                "sensorId": reading.sensorId,
                "sensorType": reading.sensorType,
                "value": reading.value,
                "unit": reading.unit,
                "relayState": reading.relayState,
                "metadata": metadata,
            }
        )
    if telemetry_docs:
        sensor_readings_collection().insert_many(telemetry_docs)

    pending_rows = list(
        device_commands_collection()
        .find({"sold_device_id": str(device["_id"]), "status": "pending"})
        .sort("created_at", 1)
    )
    if pending_rows:
        device_commands_collection().update_many(
            {"_id": {"$in": [row["_id"] for row in pending_rows]}},
            {"$set": {"status": "sent", "sent_at": received_at}},
        )

    if live_updates:
        live_feed_broker.publish(
            {
                "type": "telemetry_packet",
                "hardwareId": hardware_id,
                "deviceId": str(device["_id"]),
                "displayName": device.get("display_name"),
                "networkName": device.get("network_name"),
                "nodeKind": device.get("node_kind"),
                "serverTimestamp": received_at,
                "espTimestamp": esp_timestamp.isoformat() if esp_timestamp else None,
                "signalStrength": signal_strength,
                "updates": live_updates,
            }
        )

    return [
        DeviceCommandResponse(
            commandId=row["command_id"],
            type="relay.set",
            relayNumber=row["relay_number"],
            targetState=row["target_state"],
            reason=row["reason"],
            status="sent",
        )
        for row in pending_rows
    ]


def list_user_devices(user_id: str) -> list[DeviceSummary]:
    claims = list(claims_collection().find({"user_id": user_id}))
    device_ids = [parse_object_id(claim["device_id"]) for claim in claims]
    if not device_ids:
        return []
    device_rows = sold_devices_collection().find({"_id": {"$in": device_ids}}).sort("hardware_id", 1)
    return [get_device_summary(str(row["_id"]), user_id, include_token=True) for row in device_rows]


def list_device_inventory() -> list[DeviceSummary]:
    device_rows = sold_devices_collection().find().sort("hardware_id", 1)
    return [build_device_summary(row, include_token=False) for row in device_rows]


def get_device_summary(device_id: str, user_id: str, include_token: bool = False) -> DeviceSummary:
    ensure_device_access(device_id, user_id)
    device = sold_devices_collection().find_one({"_id": parse_object_id(device_id)})
    latest_readings = _latest_readings_for_device(device)
    return build_device_summary(device, include_token=include_token, latest_readings=latest_readings)


def build_device_summary(
    device: dict,
    *,
    include_token: bool,
    latest_readings: list[ReadingResponse] | None = None,
) -> DeviceSummary:
    location = device.get("location") or {}
    claim_count = claims_collection().count_documents({"device_id": str(device["_id"])})
    return DeviceSummary(
        id=str(device["_id"]),
        hardwareId=device["hardware_id"],
        deviceModel=device["device_model"],
        displayName=device.get("display_name"),
        networkName=device.get("network_name"),
        nodeId=device.get("node_id"),
        nodeKind=device.get("node_kind"),
        latitude=location.get("latitude"),
        longitude=location.get("longitude"),
        relayCount=device["relay_count"],
        firmwareVersion=device.get("firmware_version"),
        claimStatus="claimed" if claim_count > 0 else "unclaimed",
        claimCount=claim_count,
        sensorManifest=device["sensor_manifest"],
        deviceAuthToken=device.get("device_auth_token") if include_token else None,
        latestReadings=latest_readings or [],
    )


def ensure_device_access(device_id: str, user_id: str) -> None:
    try:
        device = claims_collection().find_one({"device_id": device_id, "user_id": user_id})
    except Exception:
        device = None
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found for this user.")


def _sensor_manifest_index(device: dict) -> dict[str, dict]:
    manifest_index: dict[str, dict] = {}
    for item in device.get("sensor_manifest", []):
        sensor_id = item.get("sensorId")
        if sensor_id:
            manifest_index[str(sensor_id)] = dict(item)
    return manifest_index


def _latest_readings_for_device(device: dict) -> list[ReadingResponse]:
    device_id = str(device["_id"])
    manifest_index = _sensor_manifest_index(device)
    sensor_ids = list(manifest_index)
    if not sensor_ids:
        return []

    pipeline = [
        {
            "$match": {
                "sold_device_id": device_id,
                "sensor_id": {"$in": sensor_ids},
            }
        },
        {"$sort": {"server_received_at": -1, "_id": -1}},
        {
            "$group": {
                "_id": "$sensor_id",
                "sensor_type": {"$first": "$sensor_type"},
                "reading_value": {"$first": "$reading_value"},
                "unit": {"$first": "$unit"},
                "relay_state": {"$first": "$relay_state"},
                "esp_timestamp": {"$first": "$esp_timestamp"},
                "server_received_at": {"$first": "$server_received_at"},
                "metadata_json": {"$first": "$metadata_json"},
            }
        },
    ]
    rows = list(sensor_readings_collection().aggregate(pipeline))
    rows_by_sensor_id = {str(row["_id"]): row for row in rows}

    responses: list[ReadingResponse] = []
    for sensor_id in sensor_ids:
        row = rows_by_sensor_id.get(sensor_id)
        if row is None:
            continue
        responses.append(
            ReadingResponse(
                sensorId=sensor_id,
                sensorType=row.get("sensor_type") or manifest_index[sensor_id].get("sensorType", "unknown"),
                value=row["reading_value"],
                unit=row.get("unit") or manifest_index[sensor_id].get("unit", "unit"),
                relayState=row.get("relay_state"),
                espTimestamp=row.get("esp_timestamp"),
                serverReceivedAt=row["server_received_at"],
                metadata=row.get("metadata_json") or {},
            )
        )
    return responses
