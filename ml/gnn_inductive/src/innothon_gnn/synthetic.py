from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from .graph_io import GraphBundle, degree_by_node, graph_tree_maps, load_graph_bundle


LABELS = ("normal", "overload", "undervoltage", "sensor_fault", "outage")


@dataclass(frozen=True)
class SyntheticConfig:
    steps: int = 192
    interval_minutes: int = 5
    seed: int = 7
    anomaly_rate: float = 0.06


def generate_dataset(
    graph_path: str | Path,
    output_dir: str | Path,
    config: SyntheticConfig | None = None,
) -> dict[str, Any]:
    config = config or SyntheticConfig()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    bundle = load_graph_bundle(graph_path)
    relations = graph_tree_maps(bundle)
    node_map = {node.node_id: node for node in bundle.nodes}
    degrees = degree_by_node([node.node_id for node in bundle.nodes], bundle.edges)
    descendant_nominal_power = _descendant_nominal_power(bundle, relations)

    node_rows = []
    for node in bundle.nodes:
        nominal_power_kw = node.nominal_power_kw
        if node.node_type in {"bus", "external_grid"}:
            nominal_power_kw = descendant_nominal_power.get(node.node_id, nominal_power_kw)
        node_rows.append(
            {
                "node_id": node.node_id,
                "node_type": node.node_type,
                "label": node.label,
                "base_voltage_v": round(node.base_voltage_v, 3),
                "nominal_power_kw": round(nominal_power_kw, 3),
                "nominal_q_kvar": round(node.nominal_q_kvar, 3),
                "degree": degrees.get(node.node_id, 0),
                "parent_bus_id": relations["parent_bus_by_load"].get(node.node_id, ""),
            }
        )

    edge_rows = [
        {
            "edge_id": edge.edge_id,
            "source": edge.source,
            "target": edge.target,
            "edge_type": edge.edge_type,
            "length_km": round(edge.length_km, 4),
        }
        for edge in bundle.edges
    ]

    rng = np.random.default_rng(config.seed)
    bus_scales = {
        bus_id: 1.0 + ((_stable_number(bus_id) % 9) - 4) * 0.035
        for bus_id in relations["bus_loads"]
    }
    start_time = datetime(2026, 3, 21, 0, 0, tzinfo=UTC)

    timeseries_rows: list[dict[str, Any]] = []
    snapshots_by_timestamp: dict[str, dict[str, dict[str, Any]]] = {}
    bus_ids = [node.node_id for node in bundle.nodes if node.node_type == "bus"]
    root_bus_id = relations["root_bus_id"]

    for step in range(config.steps):
        timestamp = (start_time + timedelta(minutes=step * config.interval_minutes)).isoformat()
        time_factor = _daily_profile(step, config.interval_minutes)
        stressed_bus = None
        if rng.random() < 0.18 and relations["bus_loads"]:
            stressed_bus = rng.choice(sorted(relations["bus_loads"].keys()))

        snapshot_rows: dict[str, dict[str, Any]] = {}

        for node in bundle.nodes:
            if node.node_type != "load":
                continue

            parent_bus = relations["parent_bus_by_load"].get(node.node_id, "")
            nominal_power_kw = max(node.nominal_power_kw, 5.0)
            load_factor = time_factor * bus_scales.get(parent_bus, 1.0)
            load_factor *= 0.92 + rng.random() * 0.22
            voltage_v = node.base_voltage_v * (0.992 + rng.normal(0.0, 0.006))
            power_kw = nominal_power_kw * load_factor
            current_a = (power_kw * 1000.0) / max(voltage_v, 1.0)

            label = "normal"
            anomaly_bias = config.anomaly_rate + (0.12 if stressed_bus == parent_bus else 0.0)
            if rng.random() < anomaly_bias:
                label = _choose_anomaly_type(rng, stressed_bus == parent_bus)
                voltage_v, current_a, power_kw = _apply_anomaly(
                    rng=rng,
                    label=label,
                    voltage_v=voltage_v,
                    current_a=current_a,
                    power_kw=power_kw,
                    nominal_power_kw=nominal_power_kw,
                )

            snapshot_rows[node.node_id] = {
                "timestamp": timestamp,
                "node_id": node.node_id,
                "node_type": node.node_type,
                "voltage_v": round(max(voltage_v, 0.0), 4),
                "current_a": round(max(current_a, 0.0), 4),
                "power_kw": round(max(power_kw, 0.0), 4),
                "label": label,
                "is_anomaly": int(label != "normal"),
            }

        _populate_bus_rows(
            bundle=bundle,
            bus_ids=bus_ids,
            root_bus_id=root_bus_id,
            relations=relations,
            node_map=node_map,
            descendant_nominal_power=descendant_nominal_power,
            snapshot_rows=snapshot_rows,
            rng=rng,
        )

        grid_nodes = [node for node in bundle.nodes if node.node_type == "external_grid"]
        total_power_kw = sum(snapshot_rows[bus_id]["power_kw"] for bus_id in bus_ids if bus_id in snapshot_rows)
        total_current_a = sum(snapshot_rows[bus_id]["current_a"] for bus_id in bus_ids if bus_id in snapshot_rows)
        for grid_node in grid_nodes:
            voltage_v = grid_node.base_voltage_v * (0.998 + rng.normal(0.0, 0.002))
            label = "normal"
            if any(snapshot_rows[bus_id]["label"] == "outage" for bus_id in bus_ids if bus_id in snapshot_rows):
                label = "undervoltage"
            snapshot_rows[grid_node.node_id] = {
                "timestamp": timestamp,
                "node_id": grid_node.node_id,
                "node_type": grid_node.node_type,
                "voltage_v": round(max(voltage_v, 0.0), 4),
                "current_a": round(max(total_current_a, 0.0), 4),
                "power_kw": round(max(total_power_kw, 0.0), 4),
                "label": label,
                "is_anomaly": int(label != "normal"),
            }

        snapshots_by_timestamp[timestamp] = snapshot_rows
        timeseries_rows.extend(snapshot_rows[node.node_id] for node in sorted(bundle.nodes, key=lambda item: item.node_id))

    _write_csv(output_path / "nodes.csv", node_rows)
    _write_csv(output_path / "edges.csv", edge_rows)
    _write_csv(output_path / "timeseries.csv", timeseries_rows)

    latest_timestamp = max(snapshots_by_timestamp)
    latest_rows = list(snapshots_by_timestamp[latest_timestamp].values())
    _write_csv(output_path / "latest_snapshot.csv", sorted(latest_rows, key=lambda item: item["node_id"]))

    return {
        "network_name": bundle.network_name,
        "output_dir": str(output_path),
        "snapshots": config.steps,
        "latest_timestamp": latest_timestamp,
        "node_count": len(bundle.nodes),
        "edge_count": len(bundle.edges),
    }


def _descendant_nominal_power(bundle: GraphBundle, relations: dict[str, Any]) -> dict[str, float]:
    node_map = {node.node_id: node for node in bundle.nodes}
    bus_children = relations["bus_children"]
    bus_loads = relations["bus_loads"]

    cache: dict[str, float] = {}

    def sum_bus(bus_id: str) -> float:
        if bus_id in cache:
            return cache[bus_id]
        total = sum(node_map[load_id].nominal_power_kw for load_id in bus_loads.get(bus_id, []))
        for child_bus in bus_children.get(bus_id, []):
            total += sum_bus(child_bus)
        cache[bus_id] = total
        return total

    for bus_id in bus_children:
        sum_bus(bus_id)

    root_bus_id = relations.get("root_bus_id")
    if root_bus_id:
        total_root = cache.get(root_bus_id, sum_bus(root_bus_id))
        for node in bundle.nodes:
            if node.node_type == "external_grid":
                cache[node.node_id] = total_root

    return cache


def _populate_bus_rows(
    *,
    bundle: GraphBundle,
    bus_ids: list[str],
    root_bus_id: str,
    relations: dict[str, Any],
    node_map: dict[str, Any],
    descendant_nominal_power: dict[str, float],
    snapshot_rows: dict[str, dict[str, Any]],
    rng: np.random.Generator,
) -> None:
    bus_children = relations["bus_children"]
    bus_loads = relations["bus_loads"]

    def build_bus(bus_id: str) -> dict[str, Any]:
        child_bus_rows = [build_bus(child_bus) for child_bus in bus_children.get(bus_id, [])]
        child_load_rows = [snapshot_rows[load_id] for load_id in bus_loads.get(bus_id, [])]
        nominal_power_kw = max(descendant_nominal_power.get(bus_id, 1.0), 1.0)
        power_kw = sum(item["power_kw"] for item in child_bus_rows + child_load_rows)
        current_a = sum(item["current_a"] for item in child_bus_rows + child_load_rows)
        load_ratio = power_kw / nominal_power_kw

        voltage_v = node_map[bus_id].base_voltage_v * (1.0 - min(load_ratio, 1.8) * 0.018)
        voltage_v *= 0.996 + rng.normal(0.0, 0.003)

        child_labels = [item["label"] for item in child_bus_rows + child_load_rows]
        overload_count = sum(1 for label in child_labels if label == "overload")
        undervoltage_count = sum(1 for label in child_labels if label == "undervoltage")
        outage_count = sum(1 for label in child_labels if label == "outage")
        sensor_fault_count = sum(1 for label in child_labels if label == "sensor_fault")

        label = "normal"
        if outage_count >= 1 and power_kw < nominal_power_kw * 0.35:
            label = "outage"
        elif voltage_v < node_map[bus_id].base_voltage_v * 0.9 or undervoltage_count >= 2:
            label = "undervoltage"
        elif overload_count >= 2 or load_ratio > 1.25:
            label = "overload"
        elif sensor_fault_count >= 2:
            label = "sensor_fault"

        row = {
            "timestamp": child_load_rows[0]["timestamp"] if child_load_rows else child_bus_rows[0]["timestamp"],
            "node_id": bus_id,
            "node_type": "bus",
            "voltage_v": round(max(voltage_v, 0.0), 4),
            "current_a": round(max(current_a, 0.0), 4),
            "power_kw": round(max(power_kw, 0.0), 4),
            "label": label,
            "is_anomaly": int(label != "normal"),
        }
        snapshot_rows[bus_id] = row
        return row

    if root_bus_id:
        build_bus(root_bus_id)
    else:
        for bus_id in bus_ids:
            if bus_id not in snapshot_rows:
                build_bus(bus_id)


def _choose_anomaly_type(rng: np.random.Generator, stressed: bool) -> str:
    if stressed:
        return str(rng.choice(["overload", "undervoltage", "sensor_fault"], p=[0.58, 0.27, 0.15]))
    return str(rng.choice(["overload", "undervoltage", "sensor_fault", "outage"], p=[0.38, 0.27, 0.2, 0.15]))


def _apply_anomaly(
    *,
    rng: np.random.Generator,
    label: str,
    voltage_v: float,
    current_a: float,
    power_kw: float,
    nominal_power_kw: float,
) -> tuple[float, float, float]:
    if label == "overload":
        power_kw *= float(rng.uniform(1.45, 2.2))
        voltage_v *= float(rng.uniform(0.93, 0.985))
        current_a = (power_kw * 1000.0) / max(voltage_v, 1.0)
        current_a *= float(rng.uniform(1.02, 1.1))
        return voltage_v, current_a, power_kw

    if label == "undervoltage":
        voltage_v *= float(rng.uniform(0.8, 0.9))
        current_a *= float(rng.uniform(1.1, 1.45))
        power_kw = voltage_v * current_a / 1000.0
        return voltage_v, current_a, power_kw

    if label == "sensor_fault":
        mode = str(rng.choice(["stuck_low", "spike", "flat_voltage"]))
        if mode == "stuck_low":
            voltage_v *= float(rng.uniform(0.3, 0.55))
            current_a *= float(rng.uniform(0.2, 0.5))
        elif mode == "spike":
            voltage_v *= float(rng.uniform(0.95, 1.05))
            current_a *= float(rng.uniform(2.4, 3.6))
        else:
            voltage_v = voltage_v * float(rng.uniform(0.985, 1.015))
            current_a *= float(rng.uniform(0.6, 1.8))
        power_kw = min(nominal_power_kw * 2.4, voltage_v * current_a / 1000.0)
        return voltage_v, current_a, power_kw

    if label == "outage":
        voltage_v *= float(rng.uniform(0.02, 0.08))
        current_a *= float(rng.uniform(0.0, 0.05))
        power_kw *= float(rng.uniform(0.0, 0.03))
        return voltage_v, current_a, power_kw

    return voltage_v, current_a, power_kw


def _daily_profile(step: int, interval_minutes: int) -> float:
    minutes = (step * interval_minutes) % 1440
    phase = (2.0 * math.pi * minutes) / 1440.0
    base = 0.82 + 0.18 * math.sin(phase - math.pi / 2.0) + 0.08 * math.sin(2.0 * phase)
    return min(max(base, 0.45), 1.28)


def _stable_number(value: str) -> int:
    return sum((index + 1) * ord(char) for index, char in enumerate(value))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
