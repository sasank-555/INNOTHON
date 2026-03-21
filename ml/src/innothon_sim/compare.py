from __future__ import annotations

from typing import Any

from .models import NetworkDefinition, SensorLinkSpec


def compare_readings(
    definition: NetworkDefinition,
    snapshot: dict[str, dict[str, dict[str, float | str | bool | None]]],
    readings: dict[str, float],
) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    energized_bus_ids = _energized_bus_ids(definition)
    for link in definition.sensor_links:
        if _has_topology_issue(definition, link, energized_bus_ids):
            actual = readings.get(link.sensor_id)
            comparisons.append(
                {
                    "sensor_id": link.sensor_id,
                    "element_type": link.element_type,
                    "element_id": link.element_id,
                    "measurement": link.measurement,
                    "expected": None,
                    "actual": actual,
                    "delta": None,
                    "absolute_delta": None,
                    "status": "topology_issue",
                }
            )
            continue

        expected = _lookup_expected(snapshot, link)
        actual = readings.get(link.sensor_id)
        delta = None if actual is None or expected is None else actual - expected
        abs_delta = None if delta is None else abs(delta)
        comparisons.append(
            {
                "sensor_id": link.sensor_id,
                "element_type": link.element_type,
                "element_id": link.element_id,
                "measurement": link.measurement,
                "expected": expected,
                "actual": actual,
                "delta": delta,
                "absolute_delta": abs_delta,
                "status": _status(link, actual, expected, abs_delta),
            }
        )
    return comparisons


def _lookup_expected(
    snapshot: dict[str, dict[str, dict[str, float | str | bool | None]]],
    link: SensorLinkSpec,
) -> float | None:
    section = _snapshot_section_name(link.element_type)
    element_data = snapshot.get(section, {}).get(link.element_id)
    if element_data is None:
        return None
    value = element_data.get(link.measurement)
    if isinstance(value, bool) or value is None:
        return None
    return float(value)


def _snapshot_section_name(element_type: str) -> str:
    mapping = {
        "bus": "buses",
        "line": "lines",
        "load": "loads",
        "transformer": "transformers",
        "static_generator": "static_generators",
        "storage": "storage",
        "external_grid": "external_grids",
    }
    return mapping[element_type]


def _status(
    link: SensorLinkSpec,
    actual: float | None,
    expected: float | None,
    absolute_delta: float | None,
) -> str:
    if expected is None:
        return "missing_expected"
    if actual is None:
        return "missing_actual"
    if absolute_delta is None:
        return "unknown"
    if absolute_delta <= _tolerance(link, expected):
        return "match"
    return "deviation"


def _energized_bus_ids(definition: NetworkDefinition) -> set[str]:
    adjacency: dict[str, set[str]] = {}

    def connect(left: str, right: str) -> None:
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)

    for line in definition.lines:
        connect(line.from_bus_id, line.to_bus_id)

    for transformer in definition.transformers:
        connect(transformer.hv_bus_id, transformer.lv_bus_id)

    visited = {item.bus_id for item in definition.external_grids}
    stack = list(visited)

    while stack:
        bus_id = stack.pop()
        for neighbor in adjacency.get(bus_id, set()):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            stack.append(neighbor)

    return visited


def _has_topology_issue(
    definition: NetworkDefinition,
    link: SensorLinkSpec,
    energized_bus_ids: set[str],
) -> bool:
    if link.element_type == "bus":
        return link.element_id not in energized_bus_ids

    if link.element_type == "load":
        load = next((item for item in definition.loads if item.id == link.element_id), None)
        return load is not None and load.bus_id not in energized_bus_ids

    if link.element_type == "external_grid":
        return False

    return False


def _tolerance(link: SensorLinkSpec, expected: float) -> float:
    baseline = max(abs(expected), 1e-6)

    if link.measurement == "p_mw":
        return max(0.01, baseline * 0.05)
    if link.measurement == "q_mvar":
        return max(0.01, baseline * 0.05)
    if link.measurement == "vm_pu":
        return 0.01
    if link.measurement == "loading_percent":
        return 2.0

    return max(1e-4, baseline * 0.01)
