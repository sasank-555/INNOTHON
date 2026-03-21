from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class NodeRecord:
    node_id: str
    node_type: str
    label: str
    base_voltage_v: float
    nominal_power_kw: float
    nominal_q_kvar: float


@dataclass(frozen=True)
class EdgeRecord:
    edge_id: str
    source: str
    target: str
    edge_type: str
    length_km: float


@dataclass(frozen=True)
class GraphBundle:
    network_name: str
    nodes: list[NodeRecord]
    edges: list[EdgeRecord]


def load_graph_bundle(path: str | Path) -> GraphBundle:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    graph = raw.get("graph", raw)
    nodes_raw = list(graph.get("nodes", []))
    edges_raw = list(graph.get("edges", []))

    bus_voltage_by_id = {
        node["id"]: float(node.get("vn_kv", 20.0)) * 1000.0
        for node in nodes_raw
        if node.get("type") == "bus"
    }
    parent_bus_by_load = {
        edge["target"]: edge["source"]
        for edge in edges_raw
        if edge.get("type") == "load_link"
    }

    nodes: list[NodeRecord] = []
    for node in nodes_raw:
        node_id = str(node["id"])
        node_type = str(node.get("type", "unknown"))
        nominal_power_kw = float(node.get("p_mw", 0.0)) * 1000.0
        nominal_q_kvar = float(node.get("q_mvar", 0.0)) * 1000.0
        if node_type == "bus":
            base_voltage_v = float(node.get("vn_kv", 20.0)) * 1000.0
        elif node_type == "load":
            parent_bus = parent_bus_by_load.get(node_id)
            base_voltage_v = float(bus_voltage_by_id.get(parent_bus, 20_000.0))
        elif node_type == "external_grid":
            base_voltage_v = 20_000.0 * float(node.get("vm_pu", 1.0))
        else:
            base_voltage_v = 20_000.0

        nodes.append(
            NodeRecord(
                node_id=node_id,
                node_type=node_type,
                label=str(node.get("label", node_id)),
                base_voltage_v=base_voltage_v,
                nominal_power_kw=nominal_power_kw,
                nominal_q_kvar=nominal_q_kvar,
            )
        )

    edges = [
        EdgeRecord(
            edge_id=str(edge.get("id", f"{edge['source']}_{edge['target']}")),
            source=str(edge["source"]),
            target=str(edge["target"]),
            edge_type=str(edge.get("type", "link")),
            length_km=float(edge.get("length_km", 0.0) or 0.0),
        )
        for edge in edges_raw
    ]

    return GraphBundle(
        network_name=str(raw.get("network_name") or raw.get("network", {}).get("name") or "graph"),
        nodes=nodes,
        edges=edges,
    )


def build_mean_adjacency(node_ids: list[str], edges: list[EdgeRecord]) -> np.ndarray:
    index_by_node = {node_id: index for index, node_id in enumerate(node_ids)}
    adjacency = np.zeros((len(node_ids), len(node_ids)), dtype=np.float64)

    for edge in edges:
        if edge.source not in index_by_node or edge.target not in index_by_node:
            continue
        left = index_by_node[edge.source]
        right = index_by_node[edge.target]
        adjacency[left, right] = 1.0
        adjacency[right, left] = 1.0

    degree = adjacency.sum(axis=1, keepdims=True)
    degree[degree == 0.0] = 1.0
    return adjacency / degree


def degree_by_node(node_ids: list[str], edges: list[EdgeRecord]) -> dict[str, int]:
    degrees = {node_id: 0 for node_id in node_ids}
    for edge in edges:
        if edge.source in degrees:
            degrees[edge.source] += 1
        if edge.target in degrees:
            degrees[edge.target] += 1
    return degrees


def graph_tree_maps(bundle: GraphBundle) -> dict[str, Any]:
    bus_ids = {node.node_id for node in bundle.nodes if node.node_type == "bus"}
    load_ids = {node.node_id for node in bundle.nodes if node.node_type == "load"}
    grid_ids = {node.node_id for node in bundle.nodes if node.node_type == "external_grid"}

    bus_children: dict[str, list[str]] = {bus_id: [] for bus_id in bus_ids}
    bus_loads: dict[str, list[str]] = {bus_id: [] for bus_id in bus_ids}
    parent_bus_by_load: dict[str, str] = {}
    root_bus_id = next(iter(bus_ids), "")

    for edge in bundle.edges:
        if edge.edge_type == "external_grid_link" and edge.target in bus_ids and edge.source in grid_ids:
            root_bus_id = edge.target
        if edge.edge_type == "load_link" and edge.source in bus_ids and edge.target in load_ids:
            parent_bus_by_load[edge.target] = edge.source
            bus_loads.setdefault(edge.source, []).append(edge.target)

    bus_neighbors: dict[str, set[str]] = {bus_id: set() for bus_id in bus_ids}
    for edge in bundle.edges:
        if edge.edge_type == "line" and edge.source in bus_ids and edge.target in bus_ids:
            bus_neighbors[edge.source].add(edge.target)
            bus_neighbors[edge.target].add(edge.source)

    parent_by_bus: dict[str, str | None] = {root_bus_id: None} if root_bus_id else {}
    queue = [root_bus_id] if root_bus_id else []
    while queue:
        current = queue.pop(0)
        for neighbor in sorted(bus_neighbors.get(current, set())):
            if neighbor in parent_by_bus:
                continue
            parent_by_bus[neighbor] = current
            bus_children.setdefault(current, []).append(neighbor)
            queue.append(neighbor)

    return {
        "root_bus_id": root_bus_id,
        "bus_children": bus_children,
        "bus_loads": bus_loads,
        "parent_bus_by_load": parent_bus_by_load,
        "parent_by_bus": parent_by_bus,
    }
