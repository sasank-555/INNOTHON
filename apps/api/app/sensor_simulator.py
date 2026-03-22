from __future__ import annotations

import asyncio
import logging
import math
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.database import (
    get_network_payload,
    simulated_sensor_assignments_collection,
    simulated_stream_templates_collection,
    sold_devices_collection,
    utc_now,
)
from app.replay_service import get_training_load_stream_templates
from app.schemas import TelemetryReading
from app.services import ingest_telemetry


LOGGER = logging.getLogger(__name__)
POWER_FACTOR = 0.92
MIN_LOOP_SECONDS = 0.25


class SensorSimulatorService:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._cursor_by_sensor_id: dict[str, int] = {}
        self._cycle_index = 0

    async def start(self) -> None:
        if not settings.simulator_enabled:
            LOGGER.info("Sensor simulator disabled by configuration.")
            return
        await asyncio.to_thread(self._ensure_seed_data)
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop(), name="sensor-simulator")
        LOGGER.info("Sensor simulator started with %s stream templates.", settings.simulator_stream_count)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run_loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self._emit_cycle)
            except Exception:
                LOGGER.exception("Sensor simulator cycle failed.")
            await asyncio.sleep(max(settings.simulator_interval_seconds, MIN_LOOP_SECONDS))

    def _ensure_seed_data(self) -> None:
        self._ensure_stream_templates()
        self._ensure_sensor_assignments()

    def _ensure_stream_templates(self) -> None:
        collection = simulated_stream_templates_collection()
        templates = get_training_load_stream_templates(settings.simulator_stream_count)
        if collection.count_documents({}) == len(templates):
            return

        timestamp = utc_now()
        collection.delete_many({})
        if not templates:
            return
        collection.insert_many(
            [
                {
                    "stream_id": template["stream_id"],
                    "source_load_id": template["source_load_id"],
                    "step_seconds": template["step_seconds"],
                    "point_count": template["point_count"],
                    "points": [dict(point) for point in template["points"]],
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
                for template in templates
            ]
        )

    def _ensure_sensor_assignments(self) -> None:
        templates = list(
            simulated_stream_templates_collection()
            .find({}, {"_id": 0, "stream_id": 1, "source_load_id": 1, "point_count": 1})
            .sort("stream_id", 1)
        )
        if not templates:
            return

        collection = simulated_sensor_assignments_collection()
        devices = list(sold_devices_collection().find({"node_kind": "building"}).sort("hardware_id", 1))
        timestamp = utc_now()
        valid_sensor_ids: set[str] = set()

        for device in devices:
            hardware_id = str(device.get("hardware_id") or "")
            network_name = str(device.get("network_name") or "NITW")
            for manifest_item in device.get("sensor_manifest", []):
                sensor_id = str(manifest_item.get("sensorId") or "")
                if not sensor_id:
                    continue
                valid_sensor_ids.add(sensor_id)
                template = templates[_stable_number(f"{hardware_id}:{sensor_id}:stream") % len(templates)]
                point_count = max(int(template.get("point_count") or 1), 1)
                collection.update_one(
                    {"sensor_id": sensor_id},
                    {
                        "$set": {
                            "hardware_id": hardware_id,
                            "network_name": network_name,
                            "sensor_id": sensor_id,
                            "load_id": manifest_item.get("loadId"),
                            "building_id": manifest_item.get("buildingId"),
                            "stream_id": template["stream_id"],
                            "source_load_id": template.get("source_load_id"),
                            "start_offset": _stable_number(f"{sensor_id}:offset") % point_count,
                            "power_scale": round(0.95 + (_stable_number(f"{sensor_id}:power") % 16) / 100, 3),
                            "voltage_bias_v": round(((_stable_number(f"{sensor_id}:voltage") % 121) - 60) / 10, 1),
                            "updated_at": timestamp,
                        },
                        "$setOnInsert": {
                            "created_at": timestamp,
                        },
                    },
                    upsert=True,
                )

        if valid_sensor_ids:
            collection.delete_many({"sensor_id": {"$nin": list(valid_sensor_ids)}})
        else:
            collection.delete_many({})

    def _emit_cycle(self) -> None:
        self._cycle_index += 1
        if self._cycle_index == 1 or self._cycle_index % 10 == 0:
            self._ensure_sensor_assignments()

        templates_by_stream_id = {
            str(row["stream_id"]): row
            for row in simulated_stream_templates_collection().find({})
        }
        assignments_by_sensor_id = {
            str(row["sensor_id"]): row
            for row in simulated_sensor_assignments_collection().find({})
        }
        if not templates_by_stream_id or not assignments_by_sensor_id:
            return

        active_load_ids_by_network: dict[str, set[str]] = {}
        building_devices = list(sold_devices_collection().find({"node_kind": "building"}).sort("hardware_id", 1))
        if not building_devices:
            return

        now = datetime.now(timezone.utc)
        for device in building_devices:
            hardware_id = str(device.get("hardware_id") or "")
            device_auth_token = str(device.get("device_auth_token") or "")
            if not hardware_id or not device_auth_token:
                continue

            network_name = str(device.get("network_name") or "NITW")
            active_load_ids = active_load_ids_by_network.get(network_name)
            if active_load_ids is None:
                payload = get_network_payload(network_name) or {"loads": []}
                active_load_ids = {
                    str(load["id"])
                    for load in payload.get("loads", [])
                    if load.get("id") and load.get("is_active", True) is not False
                }
                active_load_ids_by_network[network_name] = active_load_ids

            readings: list[TelemetryReading] = []
            for manifest_item in device.get("sensor_manifest", []):
                sensor_id = str(manifest_item.get("sensorId") or "")
                load_id = manifest_item.get("loadId")
                if not sensor_id:
                    continue
                if load_id and str(load_id) not in active_load_ids:
                    continue

                assignment = assignments_by_sensor_id.get(sensor_id)
                if assignment is None:
                    continue
                template = templates_by_stream_id.get(str(assignment.get("stream_id")))
                if template is None:
                    continue

                point = self._next_point(sensor_id, template, int(assignment.get("start_offset") or 0))
                power_mw, voltage_v, current_a = _scaled_metrics(point, assignment, sensor_id, self._cycle_index)
                readings.append(
                    TelemetryReading(
                        sensorId=sensor_id,
                        sensorType=str(manifest_item.get("sensorType") or "p_mw"),
                        value=power_mw,
                        unit=str(manifest_item.get("unit") or "MW"),
                        metadata={
                            "streamId": assignment.get("stream_id"),
                            "sourceLoadId": assignment.get("source_load_id"),
                            "templateTimestamp": point.get("timestamp"),
                            "powerMw": power_mw,
                            "voltageV": voltage_v,
                            "currentA": current_a,
                            "label": point.get("label"),
                            "isAnomaly": int(point.get("is_anomaly") or 0),
                            "simulated": True,
                        },
                    )
                )

            if not readings:
                continue

            ingest_telemetry(
                hardware_id,
                device_auth_token,
                now,
                readings,
                _signal_strength(hardware_id, self._cycle_index),
            )

    def _next_point(self, sensor_id: str, template: dict[str, Any], start_offset: int) -> dict[str, Any]:
        points = list(template.get("points") or [])
        if not points:
            raise ValueError(f"Stream template {template.get('stream_id')} does not contain any points.")

        cursor = self._cursor_by_sensor_id.get(sensor_id, start_offset % len(points))
        point = dict(points[cursor])
        # Loop back to the start so each assigned stream replays forever.
        self._cursor_by_sensor_id[sensor_id] = (cursor + 1) % len(points)
        return point


def _scaled_metrics(
    point: dict[str, Any],
    assignment: dict[str, Any],
    sensor_id: str,
    cycle_index: int,
) -> tuple[float, float, float]:
    base_power_mw = max(float(point.get("power_mw") or 0.0), 0.001)
    base_voltage_v = max(float(point.get("voltage_v") or 0.0), 1.0)
    power_scale = float(assignment.get("power_scale") or 1.0)
    voltage_bias_v = float(assignment.get("voltage_bias_v") or 0.0)
    phase = (_stable_number(sensor_id) % 31) / 7
    power_wave = math.sin(cycle_index / 3.4 + phase) * 0.015
    voltage_wave = math.cos(cycle_index / 4.1 + phase) * 1.8

    power_mw = round(max(0.001, base_power_mw * power_scale * (1 + power_wave)), 4)
    voltage_v = round(_clamp(base_voltage_v + voltage_bias_v + voltage_wave, 110.0, 455.0), 1)
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


sensor_simulator = SensorSimulatorService()
