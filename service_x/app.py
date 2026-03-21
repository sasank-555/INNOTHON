from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
ML_SRC = ROOT / "ml" / "src"
if str(ML_SRC) not in sys.path:
    sys.path.insert(0, str(ML_SRC))

from innothon_sim.service import compare_network_payload  # noqa: E402


app = FastAPI(title="INNOTHON Service X", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GraphUpdateRequest(BaseModel):
    networkId: str
    graph: dict[str, Any]


INITIAL_SNAPSHOT: dict[str, Any] = {
    "network": {
        "id": "network-alpha",
        "name": "North Feeder",
    },
    "graph": {
        "nodes": [
            {
                "id": "node-source-1",
                "type": "source",
                "label": "Grid Source",
                "x": 80,
                "y": 120,
                "nominalPowerKw": 120,
                "active": True,
            },
            {
                "id": "node-transformer-1",
                "type": "transformer",
                "label": "Transformer",
                "x": 360,
                "y": 120,
                "nominalPowerKw": 88,
                "active": True,
            },
            {
                "id": "node-sink-1",
                "type": "sink",
                "label": "Industrial Sink",
                "x": 680,
                "y": 120,
                "nominalPowerKw": 96,
                "active": True,
            },
        ],
        "edges": [
            {
                "id": "edge-source-transformer",
                "source": "node-source-1",
                "target": "node-transformer-1",
            },
            {
                "id": "edge-transformer-sink",
                "source": "node-transformer-1",
                "target": "node-sink-1",
            },
        ],
    },
    "sensorReadings": [
        {
            "nodeId": "node-source-1",
            "powerKw": 118,
            "voltageKv": 20,
            "timestamp": "2026-03-21T10:30:00Z",
        },
        {
            "nodeId": "node-transformer-1",
            "powerKw": 92,
            "voltageKv": 11,
            "timestamp": "2026-03-21T10:30:00Z",
        },
        {
            "nodeId": "node-sink-1",
            "powerKw": 124,
            "voltageKv": 11,
            "timestamp": "2026-03-21T10:30:00Z",
        },
    ],
}

SERVICE_STATE: dict[str, Any] = deepcopy(INITIAL_SNAPSHOT)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/service-x/state")
def get_service_state() -> dict[str, Any]:
    return build_frontend_state(SERVICE_STATE)


@app.put("/service-x/graph")
def put_service_graph(request: GraphUpdateRequest) -> dict[str, Any]:
    global SERVICE_STATE

    if request.networkId != SERVICE_STATE["network"]["id"]:
        raise HTTPException(status_code=404, detail=f"Unknown network {request.networkId}")

    SERVICE_STATE = {
        **SERVICE_STATE,
        "graph": deepcopy(request.graph),
        "sensorReadings": reconcile_sensor_readings(
            request.graph["nodes"],
            SERVICE_STATE["sensorReadings"],
        ),
    }
    return build_frontend_state(SERVICE_STATE)


def build_frontend_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    ml_network_payload, readings_payload, sensor_to_node = graph_to_ml_payload(snapshot)
    comparison = compare_network_payload(ml_network_payload, readings_payload)
    analysis = comparison_to_frontend_analysis(snapshot, comparison, sensor_to_node)
    return {
        "snapshot": snapshot,
        "analysis": analysis,
    }


def graph_to_ml_payload(
    snapshot: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, float], dict[str, str]]:
    nodes = deepcopy(snapshot["graph"]["nodes"])
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
                "q_mvar": kw_to_mw(node["nominalPowerKw"], node["active"]) * reactive_factor(node["type"]),
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


def comparison_to_frontend_analysis(
    snapshot: dict[str, Any],
    comparison: dict[str, Any],
    sensor_to_node: dict[str, str],
) -> dict[str, Any]:
    nodes = snapshot["graph"]["nodes"]
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


def reconcile_sensor_readings(
    nodes: list[dict[str, Any]],
    current_readings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current_by_node_id = {reading["nodeId"]: reading for reading in current_readings}
    next_timestamp = "2026-03-21T10:45:00Z"
    results = []
    for node in nodes:
        existing = current_by_node_id.get(node["id"], {})
        power_kw = 0 if not node["active"] else max(0, round(node["nominalPowerKw"] * sensor_factor(node["type"])))
        results.append(
            {
                "nodeId": node["id"],
                "powerKw": power_kw,
                "voltageKv": existing.get("voltageKv", nominal_voltage_kv(node["type"])),
                "timestamp": next_timestamp,
            }
        )
    return results


def sensor_factor(node_type: str) -> float:
    return {
        "source": 0.98,
        "transformer": 1.06,
        "sink": 1.28,
        "battery": 0.72,
        "transmission": 0.84,
    }.get(node_type, 1.0)


def reactive_factor(node_type: str) -> float:
    return {
        "transformer": 0.12,
        "transmission": 0.08,
        "sink": 0.22,
        "battery": 0.05,
    }.get(node_type, 0.1)


def nominal_voltage_kv(node_type: str) -> float:
    return {
        "source": 20.0,
        "transformer": 11.0,
        "transmission": 11.0,
        "sink": 11.0,
        "battery": 11.0,
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
