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


def build_model_graph(network_payload: dict[str, Any]) -> dict[str, Any]:
    network_name = str((network_payload.get("network") or {}).get("name") or "network")
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    known_node_ids: set[str] = set()
    known_edge_ids: set[str] = set()

    def add_node(node_id: str, node_type: str, label: str, **extra: Any) -> None:
        if node_id in known_node_ids:
            return
        known_node_ids.add(node_id)
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "label": label,
                **extra,
            }
        )

    def add_edge(edge_id: str, source: str, target: str, edge_type: str, **extra: Any) -> None:
        if edge_id in known_edge_ids:
            return
        known_edge_ids.add(edge_id)
        edges.append(
            {
                "id": edge_id,
                "source": source,
                "target": target,
                "type": edge_type,
                **extra,
            }
        )

    for item in network_payload.get("buses", []):
        bus_id = str(item.get("id"))
        if not bus_id:
            continue
        add_node(
            bus_id,
            "bus",
            str(item.get("name") or bus_id),
            vn_kv=item.get("vn_kv"),
        )

    for item in network_payload.get("external_grids", []):
        grid_id = str(item.get("id"))
        bus_id = str(item.get("bus_id") or "")
        if not grid_id:
            continue
        add_node(grid_id, "external_grid", str(item.get("name") or grid_id), vm_pu=item.get("vm_pu"))
        if bus_id:
            add_edge(f"edge_{grid_id}_to_{bus_id}", grid_id, bus_id, "external_grid_link")

    for item in network_payload.get("loads", []):
        load_id = str(item.get("id"))
        bus_id = str(item.get("bus_id") or "")
        if not load_id:
            continue
        add_node(
            load_id,
            "load",
            str(item.get("name") or load_id),
            p_mw=item.get("p_mw"),
            q_mvar=item.get("q_mvar"),
        )
        if bus_id:
            add_edge(f"edge_{bus_id}_to_{load_id}", bus_id, load_id, "load_link")

    for item in network_payload.get("static_generators", []):
        generator_id = str(item.get("id"))
        bus_id = str(item.get("bus_id") or "")
        if not generator_id:
            continue
        add_node(
            generator_id,
            "static_generator",
            str(item.get("name") or generator_id),
            p_mw=item.get("p_mw"),
            q_mvar=item.get("q_mvar"),
        )
        if bus_id:
            add_edge(f"edge_{bus_id}_to_{generator_id}", bus_id, generator_id, "generator_link")

    for item in network_payload.get("storage", []):
        storage_id = str(item.get("id"))
        bus_id = str(item.get("bus_id") or "")
        if not storage_id:
            continue
        add_node(
            storage_id,
            "storage",
            str(item.get("name") or storage_id),
            p_mw=item.get("p_mw"),
            soc_percent=item.get("soc_percent"),
        )
        if bus_id:
            add_edge(f"edge_{bus_id}_to_{storage_id}", bus_id, storage_id, "storage_link")

    for item in network_payload.get("lines", []):
        line_id = str(item.get("id"))
        from_bus_id = str(item.get("from_bus_id") or "")
        to_bus_id = str(item.get("to_bus_id") or "")
        if from_bus_id and to_bus_id:
            add_edge(
                line_id or f"edge_{from_bus_id}_to_{to_bus_id}",
                from_bus_id,
                to_bus_id,
                "line",
                label=str(item.get("name") or line_id or f"{from_bus_id} to {to_bus_id}"),
                length_km=item.get("length_km"),
            )

    for item in network_payload.get("transformers", []):
        transformer_id = str(item.get("id"))
        hv_bus_id = str(item.get("hv_bus_id") or "")
        lv_bus_id = str(item.get("lv_bus_id") or "")
        add_node(transformer_id, "transformer", str(item.get("name") or transformer_id))
        if hv_bus_id:
            add_edge(f"edge_{hv_bus_id}_to_{transformer_id}", hv_bus_id, transformer_id, "transformer_hv_link")
        if lv_bus_id:
            add_edge(f"edge_{transformer_id}_to_{lv_bus_id}", transformer_id, lv_bus_id, "transformer_lv_link")

    for item in network_payload.get("switches", []):
        switch_id = str(item.get("id"))
        bus_id = str(item.get("bus_id") or "")
        element_id = str(item.get("element_id") or "")
        if not switch_id:
            continue
        add_node(switch_id, "switch", str(item.get("name") or switch_id), closed=item.get("closed"))
        if bus_id:
            add_edge(f"edge_{bus_id}_to_{switch_id}", bus_id, switch_id, "switch_bus_link")
        if element_id:
            add_edge(f"edge_{switch_id}_to_{element_id}", switch_id, element_id, "switch_element_link")

    return {
        "status": "ok",
        "network_name": network_name,
        "graph": {
            "nodes": nodes,
            "edges": edges,
        },
    }


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
