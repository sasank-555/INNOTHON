from __future__ import annotations

import argparse
import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib import error, request

from app.config import settings
from app.replay_service import get_training_load_stream_templates


LOGGER = logging.getLogger(__name__)
POWER_FACTOR = 0.92
DEFAULT_INGEST_URL = "http://127.0.0.1:8000/ingest/http"
DEFAULT_STREAM_COUNT = 5
MIN_LOOP_SECONDS = 0.25


@dataclass
class SensorAssignment:
    stream_id: str
    source_load_id: str
    cursor: int
    power_scale: float
    voltage_bias_v: float
    points: list[dict[str, Any]]


class FileBackedFakeSensor:
    def __init__(
        self,
        ingest_url: str,
        interval_seconds: float,
        stream_count: int,
        hardware_ids: set[str] | None = None,
    ) -> None:
        self.ingest_url = ingest_url
        self.interval_seconds = max(interval_seconds, MIN_LOOP_SECONDS)
        self.hardware_ids = hardware_ids or set()
        self.templates = get_training_load_stream_templates(limit=max(1, stream_count))
        self.assignments_by_sensor_id: dict[str, SensorAssignment] = {}
        self.cycle_index = 0

    def run_forever(self, cycles: int | None = None) -> None:
        emitted_cycles = 0
        while cycles is None or emitted_cycles < cycles:
            self.emit_cycle()
            emitted_cycles += 1
            if cycles is None or emitted_cycles < cycles:
                time.sleep(self.interval_seconds)

    def emit_cycle(self) -> None:
        devices = self._load_devices()
        if not devices:
            LOGGER.warning("No eligible building devices found for fake sensor replay.")
            return

        self.cycle_index += 1
        active_load_ids_by_network: dict[str, set[str]] = {}
        emitted_device_count = 0

        for device in devices:
            hardware_id = str(device.get("hardware_id") or "")
            device_auth_token = str(device.get("device_auth_token") or "")
            if not hardware_id or not device_auth_token:
                continue

            network_name = str(device.get("network_name") or "NITW")
            active_load_ids = active_load_ids_by_network.get(network_name)
            if active_load_ids is None:
                from app.database import get_network_payload

                payload = get_network_payload(network_name) or {"loads": []}
                active_load_ids = {
                    str(load["id"])
                    for load in payload.get("loads", [])
                    if load.get("id") and load.get("is_active", True) is not False
                }
                active_load_ids_by_network[network_name] = active_load_ids

            readings: list[dict[str, Any]] = []
            for manifest_item in device.get("sensor_manifest", []):
                sensor_id = str(manifest_item.get("sensorId") or "")
                load_id = str(manifest_item.get("loadId") or "")
                if not sensor_id:
                    continue
                if load_id and load_id not in active_load_ids:
                    continue

                assignment = self._assignment_for_sensor(sensor_id)
                point = assignment.points[assignment.cursor]
                assignment.cursor = (assignment.cursor + 1) % len(assignment.points)
                power_mw, voltage_v, current_a = _scaled_metrics(
                    point,
                    assignment,
                    sensor_id,
                    self.cycle_index,
                )
                readings.append(
                    {
                        "sensorId": sensor_id,
                        "sensorType": str(manifest_item.get("sensorType") or "p_mw"),
                        "value": power_mw,
                        "unit": str(manifest_item.get("unit") or "MW"),
                        "metadata": {
                            "streamId": assignment.stream_id,
                            "sourceLoadId": assignment.source_load_id,
                            "templateTimestamp": point.get("timestamp"),
                            "powerMw": power_mw,
                            "voltageV": voltage_v,
                            "currentA": current_a,
                            "label": point.get("label"),
                            "isAnomaly": int(point.get("is_anomaly") or 0),
                            "simulated": True,
                            "source": "file-backed-fake-sensor",
                        },
                    }
                )

            if not readings:
                continue

            self._post_payload(
                {
                    "hardwareId": hardware_id,
                    "deviceAuthToken": device_auth_token,
                    "espTimestamp": datetime.now(timezone.utc).isoformat(),
                    "signalStrength": _signal_strength(hardware_id, self.cycle_index),
                    "readings": readings,
                }
            )
            emitted_device_count += 1

        LOGGER.info("Fake sensor cycle %s emitted telemetry for %s device(s).", self.cycle_index, emitted_device_count)

    def _load_devices(self) -> list[dict[str, Any]]:
        from app.database import sold_devices_collection

        query: dict[str, Any] = {"node_kind": "building"}
        if self.hardware_ids:
            query["hardware_id"] = {"$in": sorted(self.hardware_ids)}
        return list(sold_devices_collection().find(query).sort("hardware_id", 1))

    def _assignment_for_sensor(self, sensor_id: str) -> SensorAssignment:
        assignment = self.assignments_by_sensor_id.get(sensor_id)
        if assignment is not None:
            return assignment

        template = self.templates[_stable_number(sensor_id) % len(self.templates)]
        assignment = SensorAssignment(
            stream_id=str(template["stream_id"]),
            source_load_id=str(template["source_load_id"]),
            cursor=_stable_number(f"{sensor_id}:offset") % max(len(template["points"]), 1),
            power_scale=round(0.95 + (_stable_number(f"{sensor_id}:power") % 16) / 100, 3),
            voltage_bias_v=round(((_stable_number(f"{sensor_id}:voltage") % 121) - 60) / 10, 1),
            points=[dict(point) for point in template["points"]],
        )
        self.assignments_by_sensor_id[sensor_id] = assignment
        return assignment

    def _post_payload(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            self.ingest_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=10) as response:
                response.read()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            LOGGER.error("Fake sensor ingest failed with %s: %s", exc.code, detail)
        except error.URLError as exc:
            LOGGER.error("Fake sensor could not reach %s: %s", self.ingest_url, exc.reason)


def _scaled_metrics(
    point: dict[str, Any],
    assignment: SensorAssignment,
    sensor_id: str,
    cycle_index: int,
) -> tuple[float, float, float]:
    base_power_mw = max(float(point.get("power_mw") or 0.0), 0.001)
    base_voltage_v = max(float(point.get("voltage_v") or 0.0), 1.0)
    phase = (_stable_number(sensor_id) % 31) / 7
    power_wave = math.sin(cycle_index / 3.4 + phase) * 0.015
    voltage_wave = math.cos(cycle_index / 4.1 + phase) * 1.8

    power_mw = round(max(0.001, base_power_mw * assignment.power_scale * (1 + power_wave)), 4)
    voltage_v = round(_clamp(base_voltage_v + assignment.voltage_bias_v + voltage_wave, 110.0, 455.0), 1)
    current_a = round((power_mw * 1_000_000) / (math.sqrt(3) * max(voltage_v, 1.0) * POWER_FACTOR), 2)
    return power_mw, voltage_v, current_a


def _signal_strength(hardware_id: str, cycle_index: int) -> int:
    baseline = -73 - (_stable_number(hardware_id) % 7)
    wave = math.sin(cycle_index / 4.5 + _stable_number(hardware_id) / 41) * 4
    return int(round(_clamp(baseline + wave, -88, -55)))


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def _stable_number(value: str) -> int:
    return sum(ord(character) * (index + 1) for index, character in enumerate(value))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay CSV-backed telemetry as if it were coming from external sensors over HTTP.")
    parser.add_argument("--ingest-url", default=DEFAULT_INGEST_URL, help="Backend HTTP ingest URL.")
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=settings.simulator_interval_seconds,
        help="Delay between telemetry cycles.",
    )
    parser.add_argument(
        "--stream-count",
        type=int,
        default=DEFAULT_STREAM_COUNT,
        help="How many file streams to reuse across the fake sensors.",
    )
    parser.add_argument(
        "--hardware-id",
        action="append",
        dest="hardware_ids",
        default=[],
        help="Limit replay to one or more building hardware IDs.",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=None,
        help="Optional number of cycles to emit before exiting.",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()
    emitter = FileBackedFakeSensor(
        ingest_url=str(args.ingest_url),
        interval_seconds=float(args.interval_seconds),
        stream_count=int(args.stream_count),
        hardware_ids={str(item) for item in args.hardware_ids if str(item).strip()},
    )
    emitter.run_forever(cycles=args.cycles)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
