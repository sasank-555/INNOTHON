from __future__ import annotations

from typing import Any

from .models import NetworkDefinition, SensorLinkSpec


def compare_readings(
    definition: NetworkDefinition,
    snapshot: dict[str, dict[str, dict[str, float | str | bool | None]]],
    readings: dict[str, float],
) -> list[dict[str, Any]]:
    comparisons: list[dict[str, Any]] = []
    for link in definition.sensor_links:
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
                "status": _status(actual, expected, abs_delta),
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
    if absolute_delta < 1e-6:
        return "match"
    return "deviation"
