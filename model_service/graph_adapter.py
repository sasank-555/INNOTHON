from __future__ import annotations

from copy import deepcopy
from typing import Any


def graph_to_ml_payload(
    snapshot: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, float], dict[str, str]]:
    nodes = [normalize_graph_node(node) for node in deepcopy(snapshot["graph"]["nodes"])]
    edges: list[dict[str, Any]] = snapshot["graph"]["edges"]
    sensor_readings: list[dict[str, Any]] = snapshot["sensorReadings"]
    node_ids = {node["id"] for node in nodes}

    if not any(node["type"] == "source" for node in nodes) and nodes:
        nodes[0]["type"] = "source"

    buses = []
    external_grids = []
    lines = []
    loads = []
    storage = []
    sensor_links = []
    readings_payload: dict[str, float] = {}
    sensor_to_node: dict[str, str] = {}
    reading_by_node = {reading["nodeId"]: reading for reading in sensor_readings}

    for node in nodes:
        bus_id = bus_id_for(node["id"])
        buses.append(
            {
                "id": bus_id,
                "name": node["label"],
                "vn_kv": nominal_voltage_kv(node["type"]),
                "type": "b",
            }
        )

        sensor_id = sensor_id_for(node["id"])
        sensor_to_node[sensor_id] = node["id"]
        reading = reading_by_node.get(node["id"])
        actual_power_mw = ((reading or {}).get("powerKw", node["nominalPowerKw"])) / 1000.0
        readings_payload[sensor_id] = actual_power_mw

        if node["type"] == "source":
            ext_grid_id = ext_grid_id_for(node["id"])
            external_grids.append(
                {
                    "id": ext_grid_id,
                    "bus_id": bus_id,
                    "vm_pu": 1.0,
                    "name": node["label"],
                }
            )
            sensor_links.append(
                {
                    "sensor_id": sensor_id,
                    "element_type": "external_grid",
                    "element_id": ext_grid_id,
                    "measurement": "p_mw",
                }
            )
            continue

        if node["type"] == "battery":
            storage_id = storage_id_for(node["id"])
            storage.append(
                {
                    "id": storage_id,
                    "bus_id": bus_id,
                    "name": node["label"],
                    "p_mw": kw_to_mw(node["nominalPowerKw"], node["active"]),
                    "max_e_mwh": max(node["nominalPowerKw"] / 1000.0, 0.01),
                    "soc_percent": 60.0,
                    "q_mvar": kw_to_mw(node["nominalPowerKw"], node["active"]) * 0.05,
                }
            )
            sensor_links.append(
                {
                    "sensor_id": sensor_id,
                    "element_type": "storage",
                    "element_id": storage_id,
                    "measurement": "p_mw",
                }
            )
            continue

        load_id = load_id_for(node["id"])
        loads.append(
            {
                "id": load_id,
                "bus_id": bus_id,
                "name": node["label"],
                "p_mw": kw_to_mw(node["nominalPowerKw"], node["active"]),
                "q_mvar": kw_to_mw(node["nominalPowerKw"], node["active"])
                * reactive_factor(node["type"]),
            }
        )
        sensor_links.append(
            {
                "sensor_id": sensor_id,
                "element_type": "load",
                "element_id": load_id,
                "measurement": "p_mw",
            }
        )

    for edge in edges:
        if edge["source"] not in node_ids or edge["target"] not in node_ids:
            continue
        lines.append(
            {
                "id": edge["id"],
                "name": edge["id"],
                "from_bus_id": bus_id_for(edge["source"]),
                "to_bus_id": bus_id_for(edge["target"]),
                "length_km": 1.0,
                "std_type": "NA2XS2Y 1x95 RM/25 12/20 kV",
            }
        )

    network_payload = {
        "network": {
            "name": snapshot["network"]["name"],
            "f_hz": 50.0,
            "sn_mva": 1.0,
        },
        "buses": buses,
        "external_grids": external_grids,
        "lines": lines,
        "loads": loads,
        "storage": storage,
        "sensor_links": sensor_links,
    }
    return network_payload, readings_payload, sensor_to_node


def comparison_to_node_analysis(
    snapshot: dict[str, Any],
    comparison: dict[str, Any],
    sensor_to_node: dict[str, str],
) -> dict[str, Any]:
    nodes = [normalize_graph_node(node) for node in snapshot["graph"]["nodes"]]
    comparison_by_node = {
        sensor_to_node[item["sensor_id"]]: item for item in comparison["comparisons"]
    }

    node_analysis: dict[str, Any] = {}
    problems: list[dict[str, Any]] = []

    for node in nodes:
        item = comparison_by_node.get(node["id"])
        expected_mw = float(item["expected"]) if item and item["expected"] is not None else 0.0
        actual_mw = float(item["actual"]) if item and item["actual"] is not None else expected_mw
        expected_kw = expected_mw * 1000.0
        actual_kw = actual_mw * 1000.0
        delta_kw = actual_kw - expected_kw
        ratio = abs(delta_kw) / max(abs(expected_kw), 1.0)

        severity = "normal"
        message = "Stable against simulated value"
        if not node["active"]:
            severity = "off"
            message = "Turned off by operator"
        elif item and item["status"] == "missing_actual":
            severity = "low"
            message = "Missing sensor reading"
        elif ratio > 0.25:
            severity = "high" if actual_kw > expected_kw else "low"
            message = f"Actual {round(actual_kw)} kW vs expected {round(expected_kw)} kW"

        node_analysis[node["id"]] = {
            "severity": severity,
            "message": message,
            "estimatedPowerKw": round(expected_kw, 2),
        }

        if severity in {"high", "low"}:
            problems.append(
                {
                    "id": node["id"],
                    "label": node["label"],
                    "severity": severity,
                    "recommendation": (
                        "Turn off this node path or inspect the connected line."
                        if severity == "high"
                        else "Keep it active only if the lower draw is expected."
                    ),
                }
            )

    return {
        "payload": {
            "networkId": snapshot["network"]["id"],
            "graph": snapshot["graph"],
            "sensorReadings": snapshot["sensorReadings"],
            "telemetry": {
                "sentAt": snapshot["sensorReadings"][0]["timestamp"]
                if snapshot["sensorReadings"]
                else "2026-03-21T10:30:00Z",
                "mode": "service-sync",
            },
        },
        "nodes": node_analysis,
        "problems": problems,
        "summary": {
            "highCount": sum(1 for item in node_analysis.values() if item["severity"] == "high"),
            "lowCount": sum(1 for item in node_analysis.values() if item["severity"] == "low"),
            "totalNodes": len(nodes),
        },
    }


def normalize_graph_node(node: dict[str, Any]) -> dict[str, Any]:
    data = node.get("data", {})
    position = node.get("position", {})
    node_type = node.get("type")
    if node_type == "powerNode":
        node_type = data.get("kind", "sink")

    return {
        "id": node.get("id"),
        "type": node_type or data.get("kind", "sink"),
        "label": node.get("label", data.get("label", node.get("id", "Node"))),
        "x": node.get("x", position.get("x", 0)),
        "y": node.get("y", position.get("y", 0)),
        "nominalPowerKw": float(
            node.get("nominalPowerKw", data.get("nominalPowerKw", 0.0)) or 0.0
        ),
        "active": bool(node.get("active", data.get("active", True))),
    }


def reactive_factor(node_type: str) -> float:
    return {
        "transformer": 0.12,
        "transmission": 0.08,
        "sink": 0.22,
        "battery": 0.05,
        "switch": 0.0,
    }.get(node_type, 0.1)


def nominal_voltage_kv(node_type: str) -> float:
    return {
        "source": 20.0,
        "transformer": 11.0,
        "transmission": 11.0,
        "sink": 11.0,
        "battery": 11.0,
        "switch": 11.0,
    }.get(node_type, 11.0)


def kw_to_mw(power_kw: float, active: bool) -> float:
    return 0.0 if not active else max(power_kw / 1000.0, 0.0)


def bus_id_for(node_id: str) -> str:
    return f"bus_{node_id}"


def load_id_for(node_id: str) -> str:
    return f"load_{node_id}"


def storage_id_for(node_id: str) -> str:
    return f"storage_{node_id}"


def ext_grid_id_for(node_id: str) -> str:
    return f"ext_{node_id}"


def sensor_id_for(node_id: str) -> str:
    return f"sensor_{node_id}"
