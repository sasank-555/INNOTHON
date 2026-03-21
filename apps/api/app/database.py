from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from app.config import settings


mongo_client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=10000)
ROOT = Path(__file__).resolve().parents[3]
NITW_GRAPH_PATH = ROOT / "ml" / "sample_data" / "nitw.json"


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


def claims_collection() -> Collection:
    return get_database()["claims"]


def parse_object_id(value: str) -> ObjectId:
    return ObjectId(value)


def initialize_database() -> None:
    db = get_database()
    db["users"].create_index([("email", ASCENDING)], unique=True)
    db["sold_devices"].create_index([("hardware_id", ASCENDING)], unique=True)
    db["device_commands"].create_index([("command_id", ASCENDING)], unique=True)
    db["sensor_readings"].create_index([("sold_device_id", ASCENDING), ("server_received_at", DESCENDING)])
    db["claims"].create_index([("user_id", ASCENDING), ("device_id", ASCENDING)], unique=True)
    db["claims"].create_index([("device_id", ASCENDING)])
    seed_demo_device()
    seed_nitw_graph_devices()
    ensure_device_tokens()
    migrate_single_owner_claims()


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


def seed_nitw_graph_devices() -> None:
    from app.security import hash_password

    if not NITW_GRAPH_PATH.exists():
        return

    payload = json.loads(NITW_GRAPH_PATH.read_text(encoding="utf-8"))
    network_name = payload.get("network", {}).get("name", "NITW")
    sensor_links = payload.get("sensor_links", [])
    sensor_links_by_element = {}
    for link in sensor_links:
        sensor_links_by_element.setdefault(link.get("element_id"), []).append(link)

    devices = sold_devices_collection()
    for load in payload.get("loads", []):
        node_id = load["id"]
        hardware_id = graph_hardware_id(node_id)
        existing = devices.find_one({"hardware_id": hardware_id})
        if existing:
            continue

        sensor_manifest = []
        for link in sensor_links_by_element.get(node_id, []):
            sensor_manifest.append(
                {
                    "sensorId": link["sensor_id"],
                    "sensorType": link.get("measurement", "power"),
                    "unit": "MW" if link.get("measurement") == "p_mw" else "unit",
                }
            )
        if not sensor_manifest:
            sensor_manifest.append(
                {
                    "sensorId": f"sensor_{node_id}",
                    "sensorType": "p_mw",
                    "unit": "MW",
                }
            )

        now = utc_now()
        devices.insert_one(
            {
                "hardware_id": hardware_id,
                "manufacturer_password_hash": hash_password(graph_claim_password(node_id)),
                "device_model": "GRAPH-NODE-ESP",
                "display_name": load["name"],
                "sensor_manifest": sensor_manifest,
                "relay_count": 1,
                "firmware_version": "graph-seeded-1.0.0",
                "claim_status": "unclaimed",
                "sold_to_user_id": None,
                "device_auth_token": None,
                "created_at": now,
                "updated_at": now,
                "network_name": network_name,
                "node_id": node_id,
                "node_kind": "load",
                "bus_id": load.get("bus_id"),
                "location": {
                    "latitude": load.get("lat"),
                    "longitude": load.get("long"),
                },
                "source_payload": load,
            }
        )


def graph_hardware_id(node_id: str) -> str:
    return f"NODE-{node_id.replace('_', '-').upper()}"


def graph_claim_password(node_id: str) -> str:
    return f"claim-{node_id}"


def migrate_single_owner_claims() -> None:
    claims = claims_collection()
    devices = sold_devices_collection()
    for device in devices.find({"sold_to_user_id": {"$nin": [None, ""]}}):
        claims.update_one(
            {"user_id": device["sold_to_user_id"], "device_id": str(device["_id"])},
            {
                "$setOnInsert": {
                    "user_id": device["sold_to_user_id"],
                    "device_id": str(device["_id"]),
                    "claimed_at": device.get("updated_at") or device.get("created_at") or utc_now(),
                }
            },
            upsert=True,
        )
