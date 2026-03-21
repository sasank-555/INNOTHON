from __future__ import annotations

import json
from pathlib import Path

from .exceptions import NetworkValidationError
from .models import NetworkDefinition


def load_network_definition(path: str | Path) -> NetworkDefinition:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    network = NetworkDefinition.from_dict(payload)
    _validate_network(network)
    return network


def load_readings(path: str | Path) -> dict[str, float]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {str(key): float(value) for key, value in payload.items()}


def dump_json(path: str | Path, payload: object) -> None:
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _validate_network(network: NetworkDefinition) -> None:
    if not network.buses:
        raise NetworkValidationError("At least one bus is required")

    bus_ids = {bus.id for bus in network.buses}
    if len(bus_ids) != len(network.buses):
        raise NetworkValidationError("Bus IDs must be unique")

    _ensure_known_buses("external_grids", [item.bus_id for item in network.external_grids], bus_ids)
    _ensure_known_buses("loads", [item.bus_id for item in network.loads], bus_ids)
    _ensure_known_buses("static_generators", [item.bus_id for item in network.static_generators], bus_ids)
    _ensure_known_buses("storage", [item.bus_id for item in network.storage], bus_ids)
    _ensure_known_buses("switches", [item.bus_id for item in network.switches], bus_ids)

    for line in network.lines:
        if line.from_bus_id not in bus_ids or line.to_bus_id not in bus_ids:
            raise NetworkValidationError(f"Line {line.id} references an unknown bus")

    for trafo in network.transformers:
        if trafo.hv_bus_id not in bus_ids or trafo.lv_bus_id not in bus_ids:
            raise NetworkValidationError(f"Transformer {trafo.id} references an unknown bus")


def _ensure_known_buses(section_name: str, refs: list[str], bus_ids: set[str]) -> None:
    for ref in refs:
        if ref not in bus_ids:
            raise NetworkValidationError(
                f"{section_name} contains a reference to unknown bus {ref}"
            )
