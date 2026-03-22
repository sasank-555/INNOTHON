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
    "buildings",
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
    "buildings": "id",
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


def simulated_stream_templates_collection() -> Collection:
    return get_database()["simulated_stream_templates"]


def simulated_sensor_assignments_collection() -> Collection:
    return get_database()["simulated_sensor_assignments"]


def networks_collection() -> Collection:
    return get_database()["networks"]


def network_buses_collection() -> Collection:
    return get_database()["network_buses"]


def network_external_grids_collection() -> Collection:
    return get_database()["network_external_grids"]


def network_lines_collection() -> Collection:
    return get_database()["network_lines"]


def network_buildings_collection() -> Collection:
    return get_database()["network_buildings"]


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
        "buildings": network_buildings_collection(),
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
    db["sensor_readings"].create_index([("sensor_id", ASCENDING), ("server_received_at", DESCENDING)])
    db["claims"].create_index([("user_id", ASCENDING), ("device_id", ASCENDING)], unique=True)
    db["claims"].create_index([("device_id", ASCENDING)])
    db["simulated_stream_templates"].create_index([("stream_id", ASCENDING)], unique=True)
    db["simulated_sensor_assignments"].create_index([("sensor_id", ASCENDING)], unique=True)
    db["simulated_sensor_assignments"].create_index([("hardware_id", ASCENDING), ("sensor_id", ASCENDING)], unique=True)
    db["simulated_sensor_assignments"].create_index([("stream_id", ASCENDING)])
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

    payload = get_network_payload("NITW") or build_large_nitw_network_payload()
    network_name = payload.get("network", {}).get("name", "NITW")
    sensor_links_by_element: dict[str, list[dict[str, Any]]] = {}
    for link in payload.get("sensor_links", []):
        sensor_links_by_element.setdefault(str(link.get("element_id", "")), []).append(link)

    devices = sold_devices_collection()
    now = utc_now()
    building_hardware_ids = [
        graph_building_hardware_id(str(building["id"]))
        for building in payload.get("buildings", [])
        if building.get("id")
    ]
    devices.delete_many({"network_name": network_name, "node_kind": "load"})
    devices.delete_many(
        {
            "network_name": network_name,
            "node_kind": "building",
            "hardware_id": {"$nin": building_hardware_ids},
        }
    )
    for building in payload.get("buildings", []):
        building_id = str(building["id"])
        hardware_id = graph_building_hardware_id(building_id)
        sensor_manifest = [
            {
                "sensorId": link["sensor_id"],
                "sensorType": link.get("measurement", "p_mw"),
                "unit": "MW" if link.get("measurement") == "p_mw" else "unit",
                "measurement": link.get("measurement", "p_mw"),
                "loadId": load.get("id"),
                "loadName": load.get("name"),
                "buildingId": building_id,
                "busId": load.get("bus_id"),
            }
            for load in payload.get("loads", [])
            if load.get("building_id") == building_id
            for link in sensor_links_by_element.get(str(load.get("id", "")), [])
            if link.get("sensor_id")
        ]
        if not sensor_manifest:
            sensor_manifest = [
                {
                    "sensorId": f"sensor_{building_id}",
                    "sensorType": "p_mw",
                    "unit": "MW",
                    "measurement": "p_mw",
                    "buildingId": building_id,
                }
            ]

        devices.update_one(
            {"hardware_id": hardware_id},
            {
                "$set": {
                    "display_name": building.get("name", building_id),
                    "sensor_manifest": sensor_manifest,
                    "relay_count": max(1, len(sensor_manifest)),
                    "firmware_version": "building-gateway-1.0.0",
                    "network_name": network_name,
                    "node_id": building_id,
                    "node_kind": "building",
                    "bus_id": building.get("bus_id"),
                    "location": {
                        "latitude": building.get("lat"),
                        "longitude": building.get("long"),
                    },
                    "source_payload": building,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "hardware_id": hardware_id,
                    "manufacturer_password_hash": hash_password(graph_building_claim_password(building_id)),
                    "device_model": "BUILDING-ESP-GATEWAY",
                    "claim_status": "unclaimed",
                    "sold_to_user_id": None,
                    "device_auth_token": None,
                    "created_at": now,
                },
            },
            upsert=True,
        )

    ensure_network_demo_sensor_readings(payload)


def graph_hardware_id(node_id: str) -> str:
    return f"NODE-{node_id.replace('_', '-').upper()}"


def graph_claim_password(node_id: str) -> str:
    return f"claim-{node_id}"


def graph_building_hardware_id(building_id: str) -> str:
    return f"BLDG-{building_id.replace('_', '-').upper()}"


def graph_building_claim_password(building_id: str) -> str:
    return f"claim-{building_id}"


def slugify_identifier(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "_" for character in value).strip("_")


def build_large_nitw_network_payload() -> dict[str, Any]:
    payload = empty_network_payload("NITW")
    payload["buses"] = [
        {
            "id": "bus_slack",
            "name": "Main Grid Bus",
            "vn_kv": 20.0,
            "type": "b",
        }
    ]
    payload["external_grids"] = [
        {
            "id": "grid_main",
            "bus_id": "bus_slack",
            "vm_pu": 1.0,
            "name": "Main Grid",
        }
    ]
    payload["sensor_links"] = [
        {
            "sensor_id": "sensor_bus_slack_voltage",
            "element_type": "bus",
            "element_id": "bus_slack",
            "measurement": "vm_pu",
        }
    ]

    load_weights = [0.05, 0.06, 0.07, 0.08, 0.09, 0.1, 0.1, 0.12, 0.15, 0.18]
    for building_index, base_load in enumerate(_building_demo_base_loads(), start=1):
        building_name = str(base_load.get("name") or f"Building {building_index}")
        slug = slugify_identifier(building_name) or f"building_{building_index}"
        building_id = f"building_{slug}"
        bus_id = f"bus_{slug}"
        lat = float(base_load.get("lat", 17.98369646253154))
        lng = float(base_load.get("long", 79.53082786635768))
        base_p = float(base_load.get("p_mw", 0.4))
        base_q = float(base_load.get("q_mvar", base_p * 0.4))

        payload["buildings"].append(
            {
                "id": building_id,
                "name": building_name,
                "bus_id": bus_id,
                "lat": lat,
                "long": lng,
                "gateway_hardware_id": graph_building_hardware_id(building_id),
                "sensor_count": len(load_weights),
                "p_mw": round(base_p, 4),
                "q_mvar": round(base_q, 4),
            }
        )
        payload["buses"].append(
            {
                "id": bus_id,
                "name": f"Bus {building_name}",
                "vn_kv": 20.0,
                "type": "b",
            }
        )
        payload["lines"].append(
            {
                "id": f"line_bus_slack_to_{bus_id}",
                "name": f"Slack to {building_name}",
                "from_bus_id": "bus_slack",
                "to_bus_id": bus_id,
                "length_km": round(0.15 + building_index * 0.03, 3),
                "std_type": "NA2XS2Y 1x95 RM/25 12/20 kV",
            }
        )

        for sensor_index, weight in enumerate(load_weights, start=1):
            load_id = f"load_{slug}_{sensor_index:02d}"
            sensor_id = f"sensor_{slug}_{sensor_index:02d}"
            p_mw = round(base_p * weight, 4)
            q_mvar = round(base_q * weight, 4)
            payload["loads"].append(
                {
                    "id": load_id,
                    "name": f"{building_name} Sensor {sensor_index:02d}",
                    "bus_id": bus_id,
                    "building_id": building_id,
                    "sensor_index": sensor_index,
                    "is_active": True,
                    "p_mw": p_mw,
                    "q_mvar": q_mvar,
                    "lat": lat,
                    "long": lng,
                }
            )
            payload["sensor_links"].append(
                {
                    "sensor_id": sensor_id,
                    "element_type": "load",
                    "element_id": load_id,
                    "measurement": "p_mw",
                }
            )

    return payload


def _building_demo_base_loads() -> list[dict[str, Any]]:
    if NITW_GRAPH_PATH.exists():
        source = json.loads(NITW_GRAPH_PATH.read_text(encoding="utf-8"))
        source_loads = [dict(item) for item in source.get("loads", [])][:10]
        if source_loads:
            return source_loads

    return [
        {"name": "CHEM DEPT", "bus_id": "bus_chem_dept", "p_mw": 0.5, "q_mvar": 0.2, "lat": 17.985566361807546, "long": 79.53388386718099},
        {"name": "LH", "bus_id": "bus_lh", "p_mw": 0.4, "q_mvar": 0.15, "lat": 17.985765350695704, "long": 79.53161471839925},
        {"name": "Siemens Centre of Excellence", "bus_id": "bus_siemens", "p_mw": 0.6, "q_mvar": 0.25, "lat": 17.982723791958378, "long": 79.53290875258377},
        {"name": "PED", "bus_id": "bus_ped", "p_mw": 0.45, "q_mvar": 0.18, "lat": 17.9817090323481, "long": 79.53247172855703},
        {"name": "DISPENSARY", "bus_id": "bus_dispensary", "p_mw": 0.3, "q_mvar": 0.1, "lat": 17.981158442071962, "long": 79.52957737723754},
        {"name": "IFC A", "bus_id": "bus_ifc_a", "p_mw": 0.5, "q_mvar": 0.2, "lat": 17.983706566261628, "long": 79.53435269736654},
        {"name": "MME", "bus_id": "bus_mme", "p_mw": 0.55, "q_mvar": 0.22, "lat": 17.984682554681754, "long": 79.53394928246638},
        {"name": "mFC", "bus_id": "bus_mfc", "p_mw": 0.35, "q_mvar": 0.12, "lat": 17.984252512451206, "long": 79.53265697091757},
        {"name": "CCPD", "bus_id": "bus_ccpd", "p_mw": 0.4, "q_mvar": 0.15, "lat": 17.984021500243745, "long": 79.53334288220447},
        {"name": "LIB", "bus_id": "bus_lib", "p_mw": 0.6, "q_mvar": 0.25, "lat": 17.98445825915247, "long": 79.53009085887841},
    ]


def seed_nitw_network() -> None:
    existing = networks_collection().find_one({"network.name": "NITW"})
    if existing and existing.get("payload"):
        existing_payload = normalize_network_payload(existing["payload"])
        if len(existing_payload.get("buildings", [])) >= 10 and len(existing_payload.get("loads", [])) >= 100:
            return

    sync_network_payload(build_large_nitw_network_payload(), kind="reference-network")


def ensure_network_demo_sensor_readings(payload: dict[str, Any]) -> None:
    devices = sold_devices_collection()
    readings_collection = sensor_readings_collection()
    timestamp = utc_now()
    load_by_id = {str(load["id"]): load for load in payload.get("loads", []) if load.get("id")}

    for building in payload.get("buildings", []):
        building_id = str(building.get("id", ""))
        if not building_id:
            continue
        device = devices.find_one({"hardware_id": graph_building_hardware_id(building_id)})
        if device is None:
            continue

        sensor_ids = [item.get("sensorId") for item in device.get("sensor_manifest", []) if item.get("sensorId")]
        if not sensor_ids:
            continue
        existing_sensor_ids = set(
            readings_collection.distinct(
                "sensor_id",
                {"sensor_id": {"$in": sensor_ids}},
            )
        )
        docs = []
        for manifest_item in device.get("sensor_manifest", []):
            sensor_id = manifest_item.get("sensorId")
            if not sensor_id or sensor_id in existing_sensor_ids:
                continue
            load = next(
                (
                    load_row
                    for load_row in payload.get("loads", [])
                    if load_row.get("building_id") == building_id
                    and any(
                        link.get("sensor_id") == sensor_id and link.get("element_id") == load_row.get("id")
                        for link in payload.get("sensor_links", [])
                    )
                ),
                None,
            )
            if load is None:
                continue
            docs.append(
                {
                    "sold_device_id": str(device["_id"]),
                    "sensor_id": sensor_id,
                    "sensor_type": manifest_item.get("sensorType", "p_mw"),
                    "reading_value": _synthetic_actual_reading(load),
                    "unit": manifest_item.get("unit", "MW"),
                    "relay_state": None,
                    "esp_timestamp": timestamp,
                    "server_received_at": timestamp,
                    "metadata_json": {
                        "seeded": True,
                        "building_id": building_id,
                        "load_id": load.get("id"),
                    },
                }
            )
        if docs:
            readings_collection.insert_many(docs)


def _synthetic_actual_reading(load: dict[str, Any]) -> float:
    load_id = str(load.get("id", ""))
    baseline = float(load.get("p_mw", 0.0))
    checksum = sum(ord(character) for character in load_id)
    multiplier = 1 + (((checksum % 9) - 4) * 0.0125)
    return round(max(0.0, baseline * multiplier), 4)


def _sensor_id_for_load(payload: dict[str, Any], load_id: str) -> str | None:
    for link in payload.get("sensor_links", []):
        if link.get("element_type") == "load" and link.get("element_id") == load_id:
            return str(link.get("sensor_id"))
    return None


def _autofill_missing_buildings(payload: dict[str, Any]) -> None:
    existing_building_ids = {
        str(item.get("id"))
        for item in payload.get("buildings", [])
        if item.get("id")
    }
    if "buildings" not in payload:
        payload["buildings"] = []

    bus_ids_with_buildings = {
        str(item.get("bus_id"))
        for item in payload.get("buildings", [])
        if item.get("bus_id")
    }
    for load in payload.get("loads", []):
        building_id = str(load.get("building_id") or "")
        if not building_id:
            building_id = f"building_{slugify_identifier(str(load.get('name') or load.get('id') or load.get('bus_id') or 'unknown'))}"
            load["building_id"] = building_id
        if building_id in existing_building_ids:
            continue

        bus_id = str(load.get("bus_id") or f"bus_{building_id}")
        if bus_id in bus_ids_with_buildings:
            matching = next(
                (
                    item
                    for item in payload.get("buildings", [])
                    if str(item.get("bus_id")) == bus_id
                ),
                None,
            )
            if matching is not None:
                load["building_id"] = str(matching["id"])
                continue

        payload["buildings"].append(
            {
                "id": building_id,
                "name": str(load.get("name") or building_id).split(" Sensor ")[0],
                "bus_id": bus_id,
                "lat": load.get("lat"),
                "long": load.get("long"),
                "gateway_hardware_id": graph_building_hardware_id(building_id),
                "sensor_count": 0,
            }
        )
        existing_building_ids.add(building_id)
        bus_ids_with_buildings.add(bus_id)

    load_counts: dict[str, int] = {}
    load_totals: dict[str, dict[str, float]] = {}
    for load in payload.get("loads", []):
        building_id = str(load.get("building_id") or "")
        if not building_id:
            continue
        load_counts[building_id] = load_counts.get(building_id, 0) + 1
        totals = load_totals.setdefault(building_id, {"p_mw": 0.0, "q_mvar": 0.0})
        totals["p_mw"] += float(load.get("p_mw", 0.0))
        totals["q_mvar"] += float(load.get("q_mvar", 0.0))

    for building in payload.get("buildings", []):
        building_id = str(building.get("id", ""))
        totals = load_totals.get(building_id, {"p_mw": 0.0, "q_mvar": 0.0})
        building["sensor_count"] = load_counts.get(building_id, 0)
        if building.get("gateway_hardware_id") is None:
            building["gateway_hardware_id"] = graph_building_hardware_id(building_id)
        building["p_mw"] = round(totals["p_mw"], 4)
        building["q_mvar"] = round(totals["q_mvar"], 4)


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
    for load in normalized["loads"]:
        load["is_active"] = bool(load.get("is_active", True))

    _autofill_missing_buildings(normalized)
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

    sync_network_building_devices(normalized, timestamp)

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


def sync_network_building_devices(payload: dict[str, Any], timestamp: str) -> None:
    from app.security import hash_password

    devices = sold_devices_collection()
    network_name = payload["network"]["name"]
    building_hardware_ids = [
        graph_building_hardware_id(str(building["id"]))
        for building in payload.get("buildings", [])
        if building.get("id")
    ]
    devices.delete_many({"network_name": network_name, "node_kind": "load"})
    devices.delete_many(
        {
            "network_name": network_name,
            "node_kind": "building",
            "hardware_id": {"$nin": building_hardware_ids},
        }
    )
    sensor_links_by_element: dict[str, list[dict[str, Any]]] = {}
    for link in payload.get("sensor_links", []):
        sensor_links_by_element.setdefault(str(link.get("element_id", "")), []).append(link)

    for building in payload.get("buildings", []):
        building_id = str(building["id"])
        hardware_id = graph_building_hardware_id(building_id)
        sensor_manifest = [
            {
                "sensorId": link["sensor_id"],
                "sensorType": link.get("measurement", "p_mw"),
                "unit": "MW" if link.get("measurement") == "p_mw" else "unit",
                "measurement": link.get("measurement", "p_mw"),
                "loadId": load.get("id"),
                "loadName": load.get("name"),
                "buildingId": building_id,
                "busId": load.get("bus_id"),
            }
            for load in payload.get("loads", [])
            if load.get("building_id") == building_id
            for link in sensor_links_by_element.get(str(load.get("id", "")), [])
            if link.get("sensor_id")
        ]
        if not sensor_manifest:
            sensor_manifest = [
                {
                    "sensorId": f"sensor_{building_id}",
                    "sensorType": "p_mw",
                    "unit": "MW",
                    "measurement": "p_mw",
                    "buildingId": building_id,
                }
            ]

        devices.update_one(
            {"hardware_id": hardware_id},
            {
                "$set": {
                    "display_name": building.get("name", building_id),
                    "sensor_manifest": sensor_manifest,
                    "relay_count": max(1, len(sensor_manifest)),
                    "firmware_version": "building-network-sync-1.0.0",
                    "network_name": network_name,
                    "node_id": building_id,
                    "node_kind": "building",
                    "bus_id": building.get("bus_id"),
                    "location": {
                        "latitude": building.get("lat"),
                        "longitude": building.get("long"),
                    },
                    "source_payload": building,
                    "updated_at": timestamp,
                },
                "$setOnInsert": {
                    "hardware_id": hardware_id,
                    "manufacturer_password_hash": hash_password(graph_building_claim_password(building_id)),
                    "device_model": "BUILDING-ESP-GATEWAY",
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
                    "is_active": True,
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
