from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from app.config import settings


mongo_client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=10000)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_database() -> Database:
    return mongo_client[settings.mongodb_database]


def users_collection() -> Collection:
    return get_database()["users"]


def sold_devices_collection() -> Collection:
    return get_database()["sold_devices"]


def sensor_readings_collection() -> Collection:
    return get_database()["sensor_readings"]


def device_commands_collection() -> Collection:
    return get_database()["device_commands"]


def parse_object_id(value: str) -> ObjectId:
    return ObjectId(value)


def initialize_database() -> None:
    db = get_database()
    db["users"].create_index([("email", ASCENDING)], unique=True)
    db["sold_devices"].create_index([("hardware_id", ASCENDING)], unique=True)
    db["device_commands"].create_index([("command_id", ASCENDING)], unique=True)
    db["sensor_readings"].create_index([("sold_device_id", ASCENDING), ("server_received_at", DESCENDING)])
    seed_demo_device()
    ensure_device_tokens()


def seed_demo_device() -> None:
    from app.security import hash_password, issue_device_token

    manifest = [
        {"sensorId": "voltage_a", "sensorType": "voltage", "unit": "V"},
        {"sensorId": "current_a", "sensorType": "current", "unit": "A"},
    ]
    devices = sold_devices_collection()
    existing = devices.find_one({"hardware_id": "ESP-000123"})
    if existing:
        return

    now = utc_now()
    devices.insert_one(
        {
            "hardware_id": "ESP-000123",
            "manufacturer_password_hash": hash_password("demo-password"),
            "device_model": "ESP32-POWER-BOARD",
            "sensor_manifest": manifest,
            "relay_count": 2,
            "firmware_version": "1.0.0",
            "claim_status": "unclaimed",
            "sold_to_user_id": None,
            "device_auth_token": issue_device_token(),
            "created_at": now,
            "updated_at": now,
        }
    )


def ensure_device_tokens() -> None:
    from app.security import issue_device_token

    devices = sold_devices_collection()
    for device in devices.find(
        {
            "$or": [
                {"device_auth_token": {"$exists": False}},
                {"device_auth_token": None},
                {"device_auth_token": ""},
            ]
        }
    ):
        devices.update_one(
            {"_id": device["_id"]},
            {"$set": {"device_auth_token": issue_device_token(), "updated_at": utc_now()}},
        )
