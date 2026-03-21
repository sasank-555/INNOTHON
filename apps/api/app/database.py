from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import settings


DB_PATH = Path(settings.database_path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sold_devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hardware_id TEXT NOT NULL UNIQUE,
        manufacturer_password_hash TEXT NOT NULL,
        device_model TEXT NOT NULL,
        sensor_manifest TEXT NOT NULL,
        relay_count INTEGER NOT NULL DEFAULT 0,
        firmware_version TEXT,
        claim_status TEXT NOT NULL DEFAULT 'unclaimed',
        sold_to_user_id INTEGER,
        device_auth_token TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (sold_to_user_id) REFERENCES users (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sensor_readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sold_device_id INTEGER NOT NULL,
        sensor_id TEXT NOT NULL,
        sensor_type TEXT NOT NULL,
        reading_value REAL NOT NULL,
        unit TEXT NOT NULL,
        relay_state TEXT,
        esp_timestamp TEXT,
        server_received_at TEXT NOT NULL,
        metadata_json TEXT,
        FOREIGN KEY (sold_device_id) REFERENCES sold_devices (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS device_commands (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sold_device_id INTEGER NOT NULL,
        command_id TEXT NOT NULL UNIQUE,
        command_type TEXT NOT NULL,
        relay_number INTEGER,
        target_state TEXT,
        reason TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        sent_at TEXT,
        FOREIGN KEY (sold_device_id) REFERENCES sold_devices (id)
    )
    """,
)


def initialize_database() -> None:
    with get_connection() as connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
    seed_demo_device()


def seed_demo_device() -> None:
    from app.security import hash_password

    manifest = [
        {"sensorId": "voltage_a", "sensorType": "voltage", "unit": "V"},
        {"sensorId": "current_a", "sensorType": "current", "unit": "A"},
    ]
    now = utc_now()
    with get_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM sold_devices WHERE hardware_id = ?",
            ("ESP-000123",),
        ).fetchone()
        if existing:
            return
        connection.execute(
            """
            INSERT INTO sold_devices (
                hardware_id,
                manufacturer_password_hash,
                device_model,
                sensor_manifest,
                relay_count,
                firmware_version,
                claim_status,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ESP-000123",
                hash_password("demo-password"),
                "ESP32-POWER-BOARD",
                json.dumps(manifest),
                2,
                "1.0.0",
                "unclaimed",
                now,
                now,
            ),
        )


def serialize_manifest(raw_manifest: str) -> list[dict[str, Any]]:
    return json.loads(raw_manifest)
