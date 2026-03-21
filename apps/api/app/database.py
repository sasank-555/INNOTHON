from __future__ import annotations

import json
import sys
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
ML_SRC = ROOT / "ml" / "src"

for candidate in (ROOT, ML_SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from innothon_sim.io import network_definition_from_payload


NETWORK_COMPONENT_SECTIONS = (
    "buses",
    "external_grids",
    "lines",
    "transformers",
    "loads",
    "static_generators",
    "storage",
    "switches",
    "sensor_links",
)

SECTION_ID_FIELDS = {
    "buses": "id",
    "external_grids": "id",
    "lines": "id",
    "transformers": "id",
    "loads": "id",
    "static_generators": "id",
    "storage": "id",
    "switches": "id",
    "sensor_links": "sensor_id",
}


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


def networks_collection() -> Collection:
    return get_database()["networks"]


def network_buses_collection() -> Collection:
    return get_database()["network_buses"]


def network_external_grids_collection() -> Collection:
    return get_database()["network_external_grids"]


def network_lines_collection() -> Collection:
    return get_database()["network_lines"]


def network_transformers_collection() -> Collection:
    return get_database()["network_transformers"]


def network_loads_collection() -> Collection:
    return get_database()["network_loads"]


def network_static_generators_collection() -> Collection:
    return get_database()["network_static_generators"]


def network_storage_collection() -> Collection:
    return get_database()["network_storage"]


def network_switches_collection() -> Collection:
    return get_database()["network_switches"]


def network_sensor_links_collection() -> Collection:
    return get_database()["network_sensor_links"]


def network_component_collection(section_name: str) -> Collection:
    mapping = {
        "buses": network_buses_collection(),
        "external_grids": network_external_grids_collection(),
        "lines": network_lines_collection(),
        "transformers": network_transformers_collection(),
        "loads": network_loads_collection(),
        "static_generators": network_static_generators_collection(),
        "storage": network_storage_collection(),
        "switches": network_switches_collection(),
        "sensor_links": network_sensor_links_collection(),
    }
    if section_name not in mapping:
        raise ValueError(f"Unsupported network section: {section_name}")
    return mapping[section_name]


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
    db["networks"].create_index([("network.name", ASCENDING)], unique=True)
    for section_name in NETWORK_COMPONENT_SECTIONS:
        id_field = SECTION_ID_FIELDS[section_name]
        collection = network_component_collection(section_name)
        collection.create_index([("network_name", ASCENDING), (id_field, ASCENDING)], unique=True)
        collection.create_index([("network_name", ASCENDING), ("order", ASCENDING)])
    seed_demo_device()
    seed_nitw_network()
    seed_nitw_graph_devices()
    repair_network_topology()
    repair_networks_from_load_devices()
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


def seed_nitw_network() -> None:
    if not NITW_GRAPH_PATH.exists():
        return

    existing = networks_collection().find_one({"network.name": "NITW"})
    if existing and existing.get("payload"):
        return

    payload = json.loads(NITW_GRAPH_PATH.read_text(encoding="utf-8"))
    sync_network_payload(payload, kind="reference-network")


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


def empty_network_payload(network_name: str) -> dict[str, Any]:
    return {
        "network": {
            "name": network_name,
            "f_hz": 50.0,
            "sn_mva": 1.0,
        },
        **{section_name: [] for section_name in NETWORK_COMPONENT_SECTIONS},
    }


def normalize_network_payload(payload: dict[str, Any]) -> dict[str, Any]:
    network = dict(payload.get("network") or {})
    if not network.get("name"):
        raise ValueError("network.name is required")

    normalized: dict[str, Any] = {
        "network": {
            "name": network["name"],
            "f_hz": float(network.get("f_hz", 50.0)),
            "sn_mva": float(network.get("sn_mva", 1.0)),
        }
    }
    for section_name in NETWORK_COMPONENT_SECTIONS:
        normalized[section_name] = [dict(item) for item in payload.get(section_name, [])]

    _autofill_missing_buses(normalized)
    _autoconnect_orphan_buses(normalized)
    _ensure_unique_component_ids(normalized)
    network_definition_from_payload(normalized)
    return normalized


def sync_network_payload(payload: dict[str, Any], *, kind: str = "managed-network") -> dict[str, Any]:
    normalized = normalize_network_payload(payload)
    network_name = normalized["network"]["name"]
    timestamp = utc_now()

    for section_name in NETWORK_COMPONENT_SECTIONS:
        collection = network_component_collection(section_name)
        collection.delete_many({"network_name": network_name})
        items = normalized.get(section_name, [])
        if items:
            collection.insert_many(
                [
                    {
                        **item,
                        "network_name": network_name,
                        "order": index,
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    }
                    for index, item in enumerate(items)
                ]
            )

    sync_network_load_devices(normalized, timestamp)

    networks_collection().update_one(
        {"network.name": network_name},
        {
            "$set": {
                "kind": kind,
                "network": normalized["network"],
                "payload": normalized,
                "component_counts": {
                    section_name: len(normalized.get(section_name, []))
                    for section_name in NETWORK_COMPONENT_SECTIONS
                },
                "updated_at": timestamp,
            },
            "$setOnInsert": {
                "created_at": timestamp,
            },
        },
        upsert=True,
    )
    return get_network_bundle(network_name) or {"network_name": network_name, "payload": normalized}


def get_network_payload(network_name: str) -> dict[str, Any] | None:
    network = networks_collection().find_one({"network.name": network_name})
    if network and network.get("payload"):
        return normalize_network_payload(network["payload"])

    return build_network_payload_from_collections(network_name)


def get_network_bundle(network_name: str) -> dict[str, Any] | None:
    payload = get_network_payload(network_name)
    if payload is None:
        return None

    network = networks_collection().find_one({"network.name": network_name}) or {}
    return {
        "status": "ok",
        "network_name": network_name,
        "kind": network.get("kind", "managed-network"),
        "payload": payload,
        "collections": get_network_collections_snapshot(network_name),
        "component_counts": {
            section_name: len(payload.get(section_name, []))
            for section_name in NETWORK_COMPONENT_SECTIONS
        },
        "updated_at": network.get("updated_at"),
    }


def build_network_payload_from_collections(network_name: str) -> dict[str, Any] | None:
    network = networks_collection().find_one({"network.name": network_name})
    has_components = any(
        network_component_collection(section_name).count_documents({"network_name": network_name}, limit=1) > 0
        for section_name in NETWORK_COMPONENT_SECTIONS
    )
    if network is None and not has_components:
        return None

    payload = empty_network_payload(network_name)
    if network and network.get("network"):
        payload["network"].update(dict(network["network"]))

    for section_name in NETWORK_COMPONENT_SECTIONS:
        payload[section_name] = _collection_items_as_payload(
            network_component_collection(section_name),
            network_name,
        )

    return normalize_network_payload(payload)


def get_network_collections_snapshot(network_name: str) -> dict[str, list[dict[str, Any]]]:
    return {
        section_name: _collection_items_as_payload(network_component_collection(section_name), network_name)
        for section_name in NETWORK_COMPONENT_SECTIONS
    }


def upsert_network_component(
    network_name: str,
    section_name: str,
    component_payload: dict[str, Any],
) -> dict[str, Any]:
    if section_name not in NETWORK_COMPONENT_SECTIONS:
        raise ValueError(f"Unsupported network section: {section_name}")

    id_field = SECTION_ID_FIELDS[section_name]
    if not component_payload.get(id_field):
        raise ValueError(f"{section_name} requires `{id_field}`")

    payload = get_network_payload(network_name) or empty_network_payload(network_name)
    payload["network"]["name"] = network_name

    updated_items = []
    replaced = False
    for item in payload[section_name]:
        if item.get(id_field) == component_payload[id_field]:
            updated_items.append(dict(component_payload))
            replaced = True
        else:
            updated_items.append(item)
    if not replaced:
        updated_items.append(dict(component_payload))

    payload[section_name] = updated_items
    network = networks_collection().find_one({"network.name": network_name}) or {}
    return sync_network_payload(payload, kind=network.get("kind", "managed-network"))


def latest_network_sensor_readings(network_name: str) -> dict[str, float]:
    payload = get_network_payload(network_name)
    if payload is None:
        return {}

    sensor_ids = [item["sensor_id"] for item in payload.get("sensor_links", []) if item.get("sensor_id")]
    if not sensor_ids:
        return {}

    pipeline = [
        {"$match": {"sensor_id": {"$in": sensor_ids}}},
        {"$sort": {"server_received_at": -1, "_id": -1}},
        {
            "$group": {
                "_id": "$sensor_id",
                "reading_value": {"$first": "$reading_value"},
            }
        },
    ]
    return {
        row["_id"]: float(row["reading_value"])
        for row in sensor_readings_collection().aggregate(pipeline)
        if row.get("reading_value") is not None
    }


def generate_alerts_from_comparisons(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    alerts: list[dict[str, Any]] = []
    for item in comparisons:
        status = item.get("status")
        sensor_id = item.get("sensor_id")
        element_id = item.get("element_id")
        expected = item.get("expected")
        actual = item.get("actual")
        absolute_delta = item.get("absolute_delta")

        if status == "match":
            continue
        if status == "missing_actual":
            alerts.append(
                {
                    "sensor_id": sensor_id,
                    "element_id": element_id,
                    "severity": "medium",
                    "message": "Sensor value missing for comparison",
                }
            )
            continue
        if status == "missing_expected":
            alerts.append(
                {
                    "sensor_id": sensor_id,
                    "element_id": element_id,
                    "severity": "low",
                    "message": "Simulation value missing for linked element",
                }
            )
            continue
        if status != "deviation" or absolute_delta is None:
            continue

        baseline = max(abs(float(expected or 0.0)), 0.001)
        ratio = float(absolute_delta) / baseline
        severity = "high" if ratio >= 0.25 else "medium" if ratio >= 0.1 else "low"
        alerts.append(
            {
                "sensor_id": sensor_id,
                "element_id": element_id,
                "severity": severity,
                "message": (
                    f"Actual {round(float(actual or 0.0), 4)} differs from simulated "
                    f"{round(float(expected or 0.0), 4)}"
                ),
                "delta": item.get("delta"),
                "absolute_delta": absolute_delta,
                "measurement": item.get("measurement"),
            }
        )

    return {
        "alerts": alerts,
        "summary": {
            "total": len(alerts),
            "high": sum(1 for item in alerts if item["severity"] == "high"),
            "medium": sum(1 for item in alerts if item["severity"] == "medium"),
            "low": sum(1 for item in alerts if item["severity"] == "low"),
        },
    }


def sync_network_load_devices(payload: dict[str, Any], timestamp: str) -> None:
    from app.security import hash_password

    devices = sold_devices_collection()
    network_name = payload["network"]["name"]
    sensor_links_by_element: dict[str, list[dict[str, Any]]] = {}
    for link in payload.get("sensor_links", []):
        sensor_links_by_element.setdefault(link.get("element_id", ""), []).append(link)

    for load in payload.get("loads", []):
        node_id = str(load["id"])
        hardware_id = graph_hardware_id(node_id)
        sensor_manifest = [
            {
                "sensorId": link["sensor_id"],
                "sensorType": link.get("measurement", "p_mw"),
                "unit": "MW" if link.get("measurement") == "p_mw" else "unit",
            }
            for link in sensor_links_by_element.get(node_id, [])
            if link.get("sensor_id")
        ]
        if not sensor_manifest:
            sensor_manifest = [
                {
                    "sensorId": f"sensor_{node_id}",
                    "sensorType": "p_mw",
                    "unit": "MW",
                }
            ]

        devices.update_one(
            {"hardware_id": hardware_id},
            {
                "$set": {
                    "display_name": load.get("name", node_id),
                    "sensor_manifest": sensor_manifest,
                    "relay_count": 1,
                    "firmware_version": "network-sync-1.0.0",
                    "network_name": network_name,
                    "node_id": node_id,
                    "node_kind": "load",
                    "bus_id": load.get("bus_id"),
                    "location": {
                        "latitude": load.get("lat"),
                        "longitude": load.get("long"),
                    },
                    "source_payload": load,
                    "updated_at": timestamp,
                },
                "$setOnInsert": {
                    "hardware_id": hardware_id,
                    "manufacturer_password_hash": hash_password(graph_claim_password(node_id)),
                    "device_model": "GRAPH-NODE-ESP",
                    "claim_status": "unclaimed",
                    "sold_to_user_id": None,
                    "device_auth_token": None,
                    "created_at": timestamp,
                },
            },
            upsert=True,
        )


def repair_networks_from_load_devices() -> None:
    for network_name in sold_devices_collection().distinct("network_name", {"node_kind": "load"}):
        if not network_name:
            continue

        payload = get_network_payload(network_name)
        if payload is None:
            continue

        known_load_ids = {item["id"] for item in payload.get("loads", []) if item.get("id")}
        known_bus_ids = {item["id"] for item in payload.get("buses", []) if item.get("id")}
        known_sensor_ids = {
            item["sensor_id"]
            for item in payload.get("sensor_links", [])
            if item.get("sensor_id")
        }
        changed = False

        for device in sold_devices_collection().find({"network_name": network_name, "node_kind": "load"}):
            node_id = device.get("node_id")
            source_payload = dict(device.get("source_payload") or {})
            if not node_id or node_id in known_load_ids or not source_payload:
                continue

            load_id = str(source_payload.get("id") or node_id)
            bus_id = str(source_payload.get("bus_id") or device.get("bus_id") or f"bus_{load_id}")
            payload["loads"].append(
                {
                    "id": load_id,
                    "name": source_payload.get("name") or device.get("display_name") or load_id,
                    "bus_id": bus_id,
                    "p_mw": float(source_payload.get("p_mw", 0.0)),
                    "q_mvar": float(source_payload.get("q_mvar", 0.0)),
                    "lat": source_payload.get("lat", (device.get("location") or {}).get("latitude")),
                    "long": source_payload.get("long", (device.get("location") or {}).get("longitude")),
                }
            )
            known_load_ids.add(load_id)
            changed = True

            if bus_id not in known_bus_ids:
                payload["buses"].append(
                    {
                        "id": bus_id,
                        "name": f"Bus {(source_payload.get('name') or load_id)}",
                        "vn_kv": 20.0,
                        "type": "b",
                        "auto_created": True,
                    }
                )
                known_bus_ids.add(bus_id)

            for manifest_item in device.get("sensor_manifest", []):
                sensor_id = manifest_item.get("sensorId")
                if not sensor_id or sensor_id in known_sensor_ids:
                    continue
                payload["sensor_links"].append(
                    {
                        "sensor_id": sensor_id,
                        "element_type": "load",
                        "element_id": load_id,
                        "measurement": manifest_item.get("sensorType", "p_mw"),
                    }
                )
                known_sensor_ids.add(sensor_id)

        if changed:
            network = networks_collection().find_one({"network.name": network_name}) or {}
            sync_network_payload(payload, kind=network.get("kind", "managed-network"))


def repair_network_topology() -> None:
    for network in networks_collection().find({"payload": {"$exists": True}}):
        payload = network.get("payload")
        if not payload:
            continue

        normalized = normalize_network_payload(payload)
        existing_lines = payload.get("lines", [])
        normalized_lines = normalized.get("lines", [])
        if len(normalized_lines) == len(existing_lines):
            continue

        sync_network_payload(normalized, kind=network.get("kind", "managed-network"))


def _collection_items_as_payload(collection: Collection, network_name: str) -> list[dict[str, Any]]:
    rows = collection.find({"network_name": network_name}).sort("order", ASCENDING)
    return [_strip_network_collection_metadata(row) for row in rows]


def _strip_network_collection_metadata(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in {"_id", "network_name", "order", "created_at", "updated_at"}
    }


def _ensure_unique_component_ids(payload: dict[str, Any]) -> None:
    for section_name in NETWORK_COMPONENT_SECTIONS:
        id_field = SECTION_ID_FIELDS[section_name]
        ids = [item.get(id_field) for item in payload.get(section_name, [])]
        if any(item is None for item in ids):
            raise ValueError(f"{section_name} contains an item without `{id_field}`")
        if len(set(ids)) != len(ids):
            raise ValueError(f"{section_name} contains duplicate `{id_field}` values")


def _autofill_missing_buses(payload: dict[str, Any]) -> None:
    existing_bus_ids = {item.get("id") for item in payload.get("buses", []) if item.get("id")}
    default_voltage = next(
        (
            float(item.get("vn_kv"))
            for item in payload.get("buses", [])
            if item.get("vn_kv") is not None
        ),
        11.0,
    )
    missing_bus_ids: set[str] = set()

    for item in payload.get("external_grids", []):
        _collect_bus_reference(missing_bus_ids, existing_bus_ids, item.get("bus_id"))
    for item in payload.get("loads", []):
        _collect_bus_reference(missing_bus_ids, existing_bus_ids, item.get("bus_id"))
    for item in payload.get("static_generators", []):
        _collect_bus_reference(missing_bus_ids, existing_bus_ids, item.get("bus_id"))
    for item in payload.get("storage", []):
        _collect_bus_reference(missing_bus_ids, existing_bus_ids, item.get("bus_id"))
    for item in payload.get("switches", []):
        _collect_bus_reference(missing_bus_ids, existing_bus_ids, item.get("bus_id"))
    for item in payload.get("lines", []):
        _collect_bus_reference(missing_bus_ids, existing_bus_ids, item.get("from_bus_id"))
        _collect_bus_reference(missing_bus_ids, existing_bus_ids, item.get("to_bus_id"))
    for item in payload.get("transformers", []):
        _collect_bus_reference(missing_bus_ids, existing_bus_ids, item.get("hv_bus_id"))
        _collect_bus_reference(missing_bus_ids, existing_bus_ids, item.get("lv_bus_id"))

    if not missing_bus_ids:
        return

    for bus_id in sorted(missing_bus_ids):
        payload["buses"].append(
            {
                "id": bus_id,
                "name": bus_id.replace("_", " ").title(),
                "vn_kv": default_voltage,
                "type": "b",
                "auto_created": True,
            }
        )


def _autoconnect_orphan_buses(payload: dict[str, Any]) -> None:
    external_grids = payload.get("external_grids", [])
    buses = payload.get("buses", [])
    if not external_grids or not buses:
        return

    root_bus_id = external_grids[0].get("bus_id")
    if not root_bus_id:
        return

    referenced_bus_ids = {
        item.get("bus_id")
        for section_name in ("loads", "static_generators", "storage", "switches")
        for item in payload.get(section_name, [])
        if item.get("bus_id")
    }
    referenced_bus_ids.update(
        item.get("from_bus_id")
        for item in payload.get("lines", [])
        if item.get("from_bus_id")
    )
    referenced_bus_ids.update(
        item.get("to_bus_id")
        for item in payload.get("lines", [])
        if item.get("to_bus_id")
    )
    referenced_bus_ids.update(
        item.get("hv_bus_id")
        for item in payload.get("transformers", [])
        if item.get("hv_bus_id")
    )
    referenced_bus_ids.update(
        item.get("lv_bus_id")
        for item in payload.get("transformers", [])
        if item.get("lv_bus_id")
    )

    energized_bus_ids = _energized_bus_ids_from_payload(payload)
    existing_line_ids = {item.get("id") for item in payload.get("lines", []) if item.get("id")}

    for bus in buses:
        bus_id = bus.get("id")
        if not bus_id or bus_id == root_bus_id or bus_id in energized_bus_ids:
            continue
        if bus_id not in referenced_bus_ids:
            continue

        line_id = _build_unique_component_id(f"line_{root_bus_id}_to_{bus_id}", existing_line_ids)
        existing_line_ids.add(line_id)
        payload.setdefault("lines", []).append(
            {
                "id": line_id,
                "name": f"{root_bus_id} to {bus_id}",
                "from_bus_id": root_bus_id,
                "to_bus_id": bus_id,
                "length_km": 1.0,
                "std_type": "NA2XS2Y 1x95 RM/25 12/20 kV",
                "auto_created": True,
            }
        )
        energized_bus_ids.add(bus_id)


def _energized_bus_ids_from_payload(payload: dict[str, Any]) -> set[str]:
    adjacency: dict[str, set[str]] = {}

    def connect(left: str, right: str) -> None:
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)

    for line in payload.get("lines", []):
        from_bus_id = line.get("from_bus_id")
        to_bus_id = line.get("to_bus_id")
        if from_bus_id and to_bus_id:
            connect(from_bus_id, to_bus_id)

    for transformer in payload.get("transformers", []):
        hv_bus_id = transformer.get("hv_bus_id")
        lv_bus_id = transformer.get("lv_bus_id")
        if hv_bus_id and lv_bus_id:
            connect(hv_bus_id, lv_bus_id)

    visited = {item.get("bus_id") for item in payload.get("external_grids", []) if item.get("bus_id")}
    stack = list(visited)

    while stack:
        bus_id = stack.pop()
        for neighbor in adjacency.get(bus_id, set()):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            stack.append(neighbor)

    return visited


def _build_unique_component_id(base_id: str, existing_ids: set[str]) -> str:
    if base_id not in existing_ids:
        return base_id

    counter = 2
    while f"{base_id}_{counter}" in existing_ids:
        counter += 1
    return f"{base_id}_{counter}"


def _collect_bus_reference(
    missing_bus_ids: set[str],
    existing_bus_ids: set[str],
    bus_id: str | None,
) -> None:
    if bus_id and bus_id not in existing_bus_ids:
        missing_bus_ids.add(bus_id)
