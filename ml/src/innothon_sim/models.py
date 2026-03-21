from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _normalize_kwargs(payload: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key in allowed}


@dataclass(slots=True)
class NetworkMeta:
    name: str
    f_hz: float = 50.0
    sn_mva: float = 1.0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NetworkMeta":
        if "name" not in payload:
            raise ValueError("network.name is required")
        return cls(
            name=str(payload["name"]),
            f_hz=float(payload.get("f_hz", 50.0)),
            sn_mva=float(payload.get("sn_mva", 1.0)),
        )


@dataclass(slots=True)
class BusSpec:
    id: str
    name: str
    vn_kv: float
    type: str = "b"
    zone: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BusSpec":
        return cls(
            id=str(payload["id"]),
            name=str(payload.get("name", payload["id"])),
            vn_kv=float(payload["vn_kv"]),
            type=str(payload.get("type", "b")),
            zone=payload.get("zone"),
        )


@dataclass(slots=True)
class ExternalGridSpec:
    id: str
    bus_id: str
    name: str
    vm_pu: float = 1.0
    va_degree: float = 0.0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExternalGridSpec":
        return cls(
            id=str(payload["id"]),
            bus_id=str(payload["bus_id"]),
            name=str(payload.get("name", payload["id"])),
            vm_pu=float(payload.get("vm_pu", 1.0)),
            va_degree=float(payload.get("va_degree", 0.0)),
        )


@dataclass(slots=True)
class LineSpec:
    id: str
    from_bus_id: str
    to_bus_id: str
    length_km: float
    std_type: str
    name: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LineSpec":
        return cls(
            id=str(payload["id"]),
            from_bus_id=str(payload["from_bus_id"]),
            to_bus_id=str(payload["to_bus_id"]),
            length_km=float(payload["length_km"]),
            std_type=str(payload["std_type"]),
            name=str(payload.get("name", payload["id"])),
        )


@dataclass(slots=True)
class TransformerSpec:
    id: str
    hv_bus_id: str
    lv_bus_id: str
    std_type: str
    name: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TransformerSpec":
        return cls(
            id=str(payload["id"]),
            hv_bus_id=str(payload["hv_bus_id"]),
            lv_bus_id=str(payload["lv_bus_id"]),
            std_type=str(payload["std_type"]),
            name=str(payload.get("name", payload["id"])),
        )


@dataclass(slots=True)
class LoadSpec:
    id: str
    bus_id: str
    name: str
    p_mw: float
    q_mvar: float
    controllable: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LoadSpec":
        return cls(
            id=str(payload["id"]),
            bus_id=str(payload["bus_id"]),
            name=str(payload.get("name", payload["id"])),
            p_mw=float(payload["p_mw"]),
            q_mvar=float(payload.get("q_mvar", 0.0)),
            controllable=bool(payload.get("controllable", False)),
        )


@dataclass(slots=True)
class StaticGeneratorSpec:
    id: str
    bus_id: str
    name: str
    p_mw: float
    q_mvar: float = 0.0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StaticGeneratorSpec":
        return cls(
            id=str(payload["id"]),
            bus_id=str(payload["bus_id"]),
            name=str(payload.get("name", payload["id"])),
            p_mw=float(payload["p_mw"]),
            q_mvar=float(payload.get("q_mvar", 0.0)),
        )


@dataclass(slots=True)
class StorageSpec:
    id: str
    bus_id: str
    name: str
    p_mw: float
    max_e_mwh: float
    soc_percent: float
    q_mvar: float = 0.0

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StorageSpec":
        return cls(
            id=str(payload["id"]),
            bus_id=str(payload["bus_id"]),
            name=str(payload.get("name", payload["id"])),
            p_mw=float(payload["p_mw"]),
            max_e_mwh=float(payload["max_e_mwh"]),
            soc_percent=float(payload["soc_percent"]),
            q_mvar=float(payload.get("q_mvar", 0.0)),
        )


@dataclass(slots=True)
class SwitchSpec:
    id: str
    bus_id: str
    element_type: str
    element_id: str
    closed: bool
    et: str
    name: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SwitchSpec":
        return cls(
            id=str(payload["id"]),
            bus_id=str(payload["bus_id"]),
            element_type=str(payload["element_type"]),
            element_id=str(payload["element_id"]),
            closed=bool(payload.get("closed", True)),
            et=str(payload.get("et", "l")),
            name=str(payload.get("name", payload["id"])),
        )


@dataclass(slots=True)
class SensorLinkSpec:
    sensor_id: str
    element_type: str
    element_id: str
    measurement: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SensorLinkSpec":
        return cls(
            sensor_id=str(payload["sensor_id"]),
            element_type=str(payload["element_type"]),
            element_id=str(payload["element_id"]),
            measurement=str(payload["measurement"]),
        )


@dataclass(slots=True)
class NetworkDefinition:
    network: NetworkMeta
    buses: list[BusSpec]
    external_grids: list[ExternalGridSpec] = field(default_factory=list)
    lines: list[LineSpec] = field(default_factory=list)
    transformers: list[TransformerSpec] = field(default_factory=list)
    loads: list[LoadSpec] = field(default_factory=list)
    static_generators: list[StaticGeneratorSpec] = field(default_factory=list)
    storage: list[StorageSpec] = field(default_factory=list)
    switches: list[SwitchSpec] = field(default_factory=list)
    sensor_links: list[SensorLinkSpec] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NetworkDefinition":
        return cls(
            network=NetworkMeta.from_dict(payload["network"]),
            buses=[BusSpec.from_dict(item) for item in payload.get("buses", [])],
            external_grids=[
                ExternalGridSpec.from_dict(item)
                for item in payload.get("external_grids", [])
            ],
            lines=[LineSpec.from_dict(item) for item in payload.get("lines", [])],
            transformers=[
                TransformerSpec.from_dict(item) for item in payload.get("transformers", [])
            ],
            loads=[LoadSpec.from_dict(item) for item in payload.get("loads", [])],
            static_generators=[
                StaticGeneratorSpec.from_dict(item)
                for item in payload.get("static_generators", [])
            ],
            storage=[StorageSpec.from_dict(item) for item in payload.get("storage", [])],
            switches=[SwitchSpec.from_dict(item) for item in payload.get("switches", [])],
            sensor_links=[
                SensorLinkSpec.from_dict(item) for item in payload.get("sensor_links", [])
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "network": asdict(self.network),
            "buses": [asdict(item) for item in self.buses],
            "external_grids": [asdict(item) for item in self.external_grids],
            "lines": [asdict(item) for item in self.lines],
            "transformers": [asdict(item) for item in self.transformers],
            "loads": [asdict(item) for item in self.loads],
            "static_generators": [asdict(item) for item in self.static_generators],
            "storage": [asdict(item) for item in self.storage],
            "switches": [asdict(item) for item in self.switches],
            "sensor_links": [asdict(item) for item in self.sensor_links],
        }


PANDAPOWER_ALLOWED_FIELDS: dict[str, set[str]] = {
    "bus": {"name", "vn_kv", "type", "zone"},
    "ext_grid": {"name", "vm_pu", "va_degree"},
    "line": {"name", "length_km", "std_type"},
    "trafo": {"name", "std_type"},
    "load": {"name", "p_mw", "q_mvar", "controllable"},
    "sgen": {"name", "p_mw", "q_mvar"},
    "storage": {"name", "p_mw", "q_mvar", "max_e_mwh", "soc_percent"},
    "switch": {"name", "closed", "et"},
}


def filter_pandapower_kwargs(element_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _normalize_kwargs(payload, PANDAPOWER_ALLOWED_FIELDS[element_type])
