from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from .exceptions import PandapowerUnavailableError
from .models import NetworkDefinition


@dataclass(slots=True)
class SimulationArtifacts:
    net: Any
    index_map: dict[str, dict[str, int]]
    snapshot: dict[str, dict[str, dict[str, float | str | bool | None]]]


def run_simulation(definition: NetworkDefinition) -> SimulationArtifacts:
    pp = _get_pandapower()

    net = pp.create_empty_network(
        name=definition.network.name,
        f_hz=definition.network.f_hz,
        sn_mva=definition.network.sn_mva,
    )
    index_map = _build_network(net, definition)
    pp.runpp(net)
    snapshot = _extract_snapshot(net, definition, index_map)
    return SimulationArtifacts(net=net, index_map=index_map, snapshot=snapshot)


def _get_pandapower() -> Any:
    try:
        return import_module("pandapower")
    except ModuleNotFoundError as error:  # pragma: no cover - environment dependent
        raise PandapowerUnavailableError(
            "pandapower is not installed. Install ml/requirements.txt first."
        ) from error


def _build_network(net: Any, definition: NetworkDefinition) -> dict[str, dict[str, int]]:
    index_map: dict[str, dict[str, int]] = {
        "bus": {},
        "external_grid": {},
        "line": {},
        "transformer": {},
        "load": {},
        "static_generator": {},
        "storage": {},
        "switch": {},
    }

    for bus in definition.buses:
        index_map["bus"][bus.id] = pp.create_bus(
            net,
            vn_kv=bus.vn_kv,
            name=bus.name,
            type=bus.type,
            zone=bus.zone,
        )

    for ext_grid in definition.external_grids:
        index_map["external_grid"][ext_grid.id] = pp.create_ext_grid(
            net,
            bus=index_map["bus"][ext_grid.bus_id],
            name=ext_grid.name,
            vm_pu=ext_grid.vm_pu,
            va_degree=ext_grid.va_degree,
        )

    for line in definition.lines:
        index_map["line"][line.id] = pp.create_line(
            net,
            from_bus=index_map["bus"][line.from_bus_id],
            to_bus=index_map["bus"][line.to_bus_id],
            length_km=line.length_km,
            std_type=line.std_type,
            name=line.name,
        )

    for transformer in definition.transformers:
        index_map["transformer"][transformer.id] = pp.create_transformer(
            net,
            hv_bus=index_map["bus"][transformer.hv_bus_id],
            lv_bus=index_map["bus"][transformer.lv_bus_id],
            std_type=transformer.std_type,
            name=transformer.name,
        )

    for load in definition.loads:
        index_map["load"][load.id] = pp.create_load(
            net,
            bus=index_map["bus"][load.bus_id],
            p_mw=load.p_mw,
            q_mvar=load.q_mvar,
            name=load.name,
            controllable=load.controllable,
        )

    for generator in definition.static_generators:
        index_map["static_generator"][generator.id] = pp.create_sgen(
            net,
            bus=index_map["bus"][generator.bus_id],
            p_mw=generator.p_mw,
            q_mvar=generator.q_mvar,
            name=generator.name,
        )

    for storage in definition.storage:
        index_map["storage"][storage.id] = pp.create_storage(
            net,
            bus=index_map["bus"][storage.bus_id],
            p_mw=storage.p_mw,
            max_e_mwh=storage.max_e_mwh,
            soc_percent=storage.soc_percent,
            q_mvar=storage.q_mvar,
            name=storage.name,
        )

    for switch in definition.switches:
        element_map_name = _switch_element_map_name(switch.element_type)
        index_map["switch"][switch.id] = pp.create_switch(
            net,
            bus=index_map["bus"][switch.bus_id],
            element=index_map[element_map_name][switch.element_id],
            et=switch.et,
            closed=switch.closed,
            name=switch.name,
        )

    return index_map


def _extract_snapshot(
    net: Any,
    definition: NetworkDefinition,
    index_map: dict[str, dict[str, int]],
) -> dict[str, dict[str, dict[str, float | str | bool | None]]]:
    return {
        "network": {
            "meta": {
                "name": definition.network.name,
                "converged": bool(getattr(net, "converged", False)),
            }
        },
        "buses": {
            bus.id: _row_to_dict(net.res_bus.loc[index_map["bus"][bus.id]])
            for bus in definition.buses
        },
        "external_grids": {
            item.id: _row_to_dict(net.res_ext_grid.loc[index_map["external_grid"][item.id]])
            for item in definition.external_grids
        },
        "lines": {
            item.id: _row_to_dict(net.res_line.loc[index_map["line"][item.id]])
            for item in definition.lines
        },
        "transformers": {
            item.id: _row_to_dict(net.res_trafo.loc[index_map["transformer"][item.id]])
            for item in definition.transformers
        },
        "loads": {
            item.id: _row_to_dict(net.res_load.loc[index_map["load"][item.id]])
            for item in definition.loads
        },
        "static_generators": {
            item.id: _row_to_dict(net.res_sgen.loc[index_map["static_generator"][item.id]])
            for item in definition.static_generators
        },
        "storage": {
            item.id: _row_to_dict(net.res_storage.loc[index_map["storage"][item.id]])
            for item in definition.storage
        },
    }


def _row_to_dict(row: Any) -> dict[str, float | str | bool | None]:
    result: dict[str, float | str | bool | None] = {}
    for key, value in row.to_dict().items():
        if hasattr(value, "item"):
            value = value.item()
        result[str(key)] = value
    return result


def _switch_element_map_name(element_type: str) -> str:
    mapping = {
        "line": "line",
        "transformer": "transformer",
    }
    if element_type not in mapping:
        raise ValueError(f"Unsupported switch element type: {element_type}")
    return mapping[element_type]
