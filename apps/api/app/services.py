from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException, status

from app.database import get_connection, serialize_manifest, utc_now
from app.schemas import (
    DeviceCommandCreateRequest,
    DeviceCommandResponse,
    DeviceSummary,
    ReadingResponse,
    UserResponse,
)
from app.security import create_access_token, hash_password, issue_device_token, verify_password


def register_user(email: str, password: str) -> tuple[str, UserResponse]:
    with get_connection() as connection:
        existing = connection.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")
        cursor = connection.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, hash_password(password), utc_now()),
        )
        user_id = cursor.lastrowid

    token = create_access_token(user_id, email)
    return token, UserResponse(id=user_id, email=email)


def login_user(email: str, password: str) -> tuple[str, UserResponse]:
    with get_connection() as connection:
        user = connection.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    if user is None or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")
    token = create_access_token(user["id"], user["email"])
    return token, UserResponse(id=user["id"], email=user["email"])


def claim_device(user_id: int, hardware_id: str, manufacturer_password: str) -> DeviceSummary:
    now = utc_now()
    with get_connection() as connection:
        device = connection.execute(
            """
            SELECT id, hardware_id, manufacturer_password_hash, device_model, sensor_manifest,
                   relay_count, firmware_version, claim_status, sold_to_user_id, device_auth_token
            FROM sold_devices
            WHERE hardware_id = ?
            """,
            (hardware_id,),
        ).fetchone()
        if device is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found.")
        if device["claim_status"] == "claimed" and device["sold_to_user_id"] != user_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device already claimed.")
        if not verify_password(manufacturer_password, device["manufacturer_password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Manufacturer password is incorrect.",
            )
        device_token = device["device_auth_token"] or issue_device_token()
        connection.execute(
            """
            UPDATE sold_devices
            SET claim_status = 'claimed',
                sold_to_user_id = ?,
                device_auth_token = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (user_id, device_token, now, device["id"]),
        )

    return get_device_summary(device["id"], user_id, include_token=True)


def create_device_command(user_id: int, device_id: int, payload: DeviceCommandCreateRequest) -> DeviceCommandResponse:
    ensure_device_access(device_id, user_id)
    command_id = f"cmd_{uuid4().hex[:12]}"
    created_at = utc_now()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO device_commands (
                sold_device_id,
                command_id,
                command_type,
                relay_number,
                target_state,
                reason,
                status,
                created_at
            ) VALUES (?, ?, 'relay.set', ?, ?, ?, 'pending', ?)
            """,
            (device_id, command_id, payload.relayNumber, payload.targetState, payload.reason, created_at),
        )
    return DeviceCommandResponse(
        commandId=command_id,
        type="relay.set",
        relayNumber=payload.relayNumber,
        targetState=payload.targetState,
        reason=payload.reason,
        status="pending",
    )


def ingest_telemetry(hardware_id: str, device_auth_token: str, esp_timestamp: datetime | None, readings: list, signal_strength: int | None) -> list[DeviceCommandResponse]:
    received_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        device = connection.execute(
            "SELECT id, device_auth_token FROM sold_devices WHERE hardware_id = ? AND claim_status = 'claimed'",
            (hardware_id,),
        ).fetchone()
        if device is None or device["device_auth_token"] != device_auth_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device credentials.")

        for reading in readings:
            metadata = {}
            if signal_strength is not None:
                metadata["signalStrength"] = signal_strength
            connection.execute(
                """
                INSERT INTO sensor_readings (
                    sold_device_id,
                    sensor_id,
                    sensor_type,
                    reading_value,
                    unit,
                    relay_state,
                    esp_timestamp,
                    server_received_at,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device["id"],
                    reading.sensorId,
                    reading.sensorType,
                    reading.value,
                    reading.unit,
                    reading.relayState,
                    esp_timestamp.isoformat() if esp_timestamp else None,
                    received_at,
                    json.dumps(metadata),
                ),
            )

        pending_rows = connection.execute(
            """
            SELECT id, command_id, relay_number, target_state, reason, status
            FROM device_commands
            WHERE sold_device_id = ? AND status = 'pending'
            ORDER BY created_at ASC
            """,
            (device["id"],),
        ).fetchall()
        if pending_rows:
            connection.executemany(
                "UPDATE device_commands SET status = 'sent', sent_at = ? WHERE id = ?",
                [(received_at, row["id"]) for row in pending_rows],
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


def list_user_devices(user_id: int) -> list[DeviceSummary]:
    with get_connection() as connection:
        device_rows = connection.execute(
            """
            SELECT id
            FROM sold_devices
            WHERE sold_to_user_id = ?
            ORDER BY hardware_id
            """,
            (user_id,),
        ).fetchall()
    return [get_device_summary(row["id"], user_id, include_token=True) for row in device_rows]


def get_device_summary(device_id: int, user_id: int, include_token: bool = False) -> DeviceSummary:
    ensure_device_access(device_id, user_id)
    with get_connection() as connection:
        device = connection.execute(
            """
            SELECT id, hardware_id, device_model, relay_count, firmware_version, claim_status,
                   sensor_manifest, device_auth_token
            FROM sold_devices
            WHERE id = ?
            """,
            (device_id,),
        ).fetchone()
        reading_rows = connection.execute(
            """
            SELECT sensor_id, sensor_type, reading_value, unit, relay_state, esp_timestamp,
                   server_received_at, metadata_json
            FROM sensor_readings
            WHERE sold_device_id = ?
            ORDER BY server_received_at DESC, id DESC
            LIMIT 10
            """,
            (device_id,),
        ).fetchall()

    latest_readings = [
        ReadingResponse(
            sensorId=row["sensor_id"],
            sensorType=row["sensor_type"],
            value=row["reading_value"],
            unit=row["unit"],
            relayState=row["relay_state"],
            espTimestamp=row["esp_timestamp"],
            serverReceivedAt=row["server_received_at"],
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
        )
        for row in reading_rows
    ]
    return DeviceSummary(
        id=device["id"],
        hardwareId=device["hardware_id"],
        deviceModel=device["device_model"],
        relayCount=device["relay_count"],
        firmwareVersion=device["firmware_version"],
        claimStatus=device["claim_status"],
        sensorManifest=serialize_manifest(device["sensor_manifest"]),
        deviceAuthToken=device["device_auth_token"] if include_token else None,
        latestReadings=latest_readings,
    )


def ensure_device_access(device_id: int, user_id: int) -> None:
    with get_connection() as connection:
        device = connection.execute(
            "SELECT id FROM sold_devices WHERE id = ? AND sold_to_user_id = ?",
            (device_id, user_id),
        ).fetchone()
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found for this user.")
