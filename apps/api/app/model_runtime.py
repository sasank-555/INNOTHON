from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
ML_SRC = ROOT / "ml" / "src"

for candidate in (ROOT, ML_SRC):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from innothon_sim.service import compare_network_payload, simulate_network_payload  # noqa: E402
from model_service.graph_adapter import comparison_to_node_analysis, graph_to_ml_payload  # noqa: E402


def simulate_model_network(network_payload: dict[str, Any]) -> dict[str, Any]:
    return simulate_network_payload(network_payload)


def compare_model_network(
    network_payload: dict[str, Any],
    readings_payload: dict[str, Any],
) -> dict[str, Any]:
    return compare_network_payload(network_payload, readings_payload)


def analyze_model_graph(snapshot: dict[str, Any]) -> dict[str, Any]:
    network_payload, readings_payload, sensor_to_node = graph_to_ml_payload(snapshot)
    comparison = compare_network_payload(network_payload, readings_payload)
    analysis = comparison_to_node_analysis(
        snapshot,
        comparison,
        sensor_to_node,
    )
    return {
        "status": "ok",
        "network_payload": network_payload,
        "readings_payload": readings_payload,
        "comparison": comparison,
        "analysis": analysis,
    }


def sample_graph_snapshot() -> dict[str, Any]:
    return {
        "network": {
            "id": "network-beta",
            "name": "Smart Distribution Grid",
        },
        "graph": {
            "nodes": [
                {
                    "id": "source-grid",
                    "type": "source",
                    "label": "Main Grid",
                    "x": 50,
                    "y": 200,
                    "nominalPowerKw": 500,
                    "active": True,
                },
                {
                    "id": "source-solar",
                    "type": "source",
                    "label": "Solar Plant",
                    "x": 50,
                    "y": 50,
                    "nominalPowerKw": 150,
                    "active": True,
                },
                {
                    "id": "transformer-1",
                    "type": "transformer",
                    "label": "T1",
                    "x": 250,
                    "y": 200,
                    "nominalPowerKw": 300,
                    "active": True,
                },
                {
                    "id": "switch-1",
                    "type": "switch",
                    "label": "Switch A",
                    "x": 420,
                    "y": 200,
                    "active": True,
                },
                {
                    "id": "sink-industrial-1",
                    "type": "sink",
                    "label": "Factory A",
                    "x": 650,
                    "y": 200,
                    "nominalPowerKw": 180,
                    "active": True,
                },
            ],
            "edges": [
                {"id": "e1", "source": "source-grid", "target": "transformer-1"},
                {"id": "e2", "source": "transformer-1", "target": "switch-1"},
                {"id": "e3", "source": "switch-1", "target": "sink-industrial-1"},
                {"id": "e4", "source": "source-solar", "target": "transformer-1"},
            ],
        },
        "sensorReadings": [
            {
                "nodeId": "source-grid",
                "powerKw": 470,
                "voltageKv": 33,
                "timestamp": "2026-03-21T10:30:00Z",
            },
            {
                "nodeId": "source-solar",
                "powerKw": 110,
                "voltageKv": 11,
                "timestamp": "2026-03-21T10:30:00Z",
            },
            {
                "nodeId": "transformer-1",
                "powerKw": 310,
                "voltageKv": 11,
                "timestamp": "2026-03-21T10:30:00Z",
            },
            {
                "nodeId": "sink-industrial-1",
                "powerKw": 210,
                "voltageKv": 11,
                "timestamp": "2026-03-21T10:30:00Z",
            },
        ],
    }
