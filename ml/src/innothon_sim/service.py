from __future__ import annotations

from typing import Any

from .compare import compare_readings
from .io import network_definition_from_payload, readings_from_payload
from .pandapower_adapter import run_simulation


def simulate_network_payload(network_payload: dict[str, Any]) -> dict[str, Any]:
    definition = network_definition_from_payload(network_payload)
    artifacts = run_simulation(definition)
    return {
        "status": "ok",
        "network_name": definition.network.name,
        "converged": bool(artifacts.snapshot["network"]["meta"]["converged"]),
        "snapshot": artifacts.snapshot,
    }


def compare_network_payload(
    network_payload: dict[str, Any],
    readings_payload: dict[str, Any],
) -> dict[str, Any]:
    definition = network_definition_from_payload(network_payload)
    artifacts = run_simulation(definition)
    readings = readings_from_payload(readings_payload)
    comparisons = compare_readings(definition, artifacts.snapshot, readings)
    return {
        "status": "ok",
        "network_name": definition.network.name,
        "converged": bool(artifacts.snapshot["network"]["meta"]["converged"]),
        "snapshot": artifacts.snapshot,
        "comparisons": comparisons,
    }
