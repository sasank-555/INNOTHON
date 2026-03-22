from __future__ import annotations

import csv
from collections import OrderedDict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
GNN_TIMESERIES_PATH = ROOT / "ml" / "gnn_inductive" / "generated" / "dataset" / "timeseries.csv"


@lru_cache(maxsize=1)
def _load_training_replay() -> dict[str, Any]:
    if not GNN_TIMESERIES_PATH.exists():
        raise FileNotFoundError(f"Replay dataset not found at {GNN_TIMESERIES_PATH}")

    frames_by_timestamp: "OrderedDict[str, list[dict[str, Any]]]" = OrderedDict()
    with GNN_TIMESERIES_PATH.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("node_type") != "load":
                continue
            timestamp = str(row["timestamp"])
            frames_by_timestamp.setdefault(timestamp, []).append(
                {
                    "load_id": str(row["node_id"]),
                    "voltage_v": round(float(row["voltage_v"]), 4),
                    "current_a": round(float(row["current_a"]), 4),
                    "power_mw": round(float(row["power_kw"]) / 1000.0, 6),
                    "label": str(row["label"]),
                    "is_anomaly": int(row["is_anomaly"]),
                }
            )

    timestamps = list(frames_by_timestamp.keys())
    if not timestamps:
        raise ValueError("Replay dataset does not contain any load rows.")

    step_seconds = 0
    if len(timestamps) > 1:
        step_seconds = int(
            (
                datetime.fromisoformat(timestamps[1]).timestamp()
                - datetime.fromisoformat(timestamps[0]).timestamp()
            )
        )

    return {
        "dataset_path": str(GNN_TIMESERIES_PATH),
        "timestamps": timestamps,
        "frames_by_timestamp": frames_by_timestamp,
        "step_seconds": step_seconds,
    }


def get_training_replay_window(cursor: int | None = None, window_size: int = 8) -> dict[str, Any]:
    dataset = _load_training_replay()
    timestamps: list[str] = dataset["timestamps"]
    frames_by_timestamp: "OrderedDict[str, list[dict[str, Any]]]" = dataset["frames_by_timestamp"]

    normalized_window_size = max(1, min(int(window_size), len(timestamps)))
    minimum_cursor = normalized_window_size - 1
    default_cursor = minimum_cursor
    if cursor is None:
        normalized_cursor = default_cursor
    else:
        normalized_cursor = max(minimum_cursor, min(int(cursor), len(timestamps) - 1))

    window_start_index = normalized_cursor - normalized_window_size + 1
    window_timestamps = timestamps[window_start_index : normalized_cursor + 1]
    frames = [
        {
            "timestamp": timestamp,
            "loads": frames_by_timestamp[timestamp],
        }
        for timestamp in window_timestamps
    ]
    next_cursor = normalized_cursor + 1 if normalized_cursor + 1 < len(timestamps) else minimum_cursor

    return {
        "status": "ok",
        "source": "gnn-training-replay",
        "dataset_path": dataset["dataset_path"],
        "cursor": normalized_cursor,
        "next_cursor": next_cursor,
        "window_size": normalized_window_size,
        "window_start": window_timestamps[0],
        "window_end": window_timestamps[-1],
        "step_seconds": dataset["step_seconds"],
        "frame_count": len(frames),
        "load_count": len(frames[-1]["loads"]) if frames else 0,
        "frames": frames,
    }


def get_training_stream_collection(limit: int = 5) -> dict[str, Any]:
    streams = get_training_load_stream_templates(limit=limit)
    dataset = _load_training_replay()
    return {
        "status": "ok",
        "source": "gnn-file-stream-collection",
        "dataset_path": dataset["dataset_path"],
        "stream_count": len(streams),
        "streams": streams,
    }


@lru_cache(maxsize=4)
def get_training_load_stream_templates(limit: int | None = None) -> list[dict[str, Any]]:
    dataset = _load_training_replay()
    timestamps: list[str] = dataset["timestamps"]
    frames_by_timestamp: "OrderedDict[str, list[dict[str, Any]]]" = dataset["frames_by_timestamp"]

    points_by_load_id: "OrderedDict[str, list[dict[str, Any]]]" = OrderedDict()
    for timestamp in timestamps:
        for load_row in frames_by_timestamp[timestamp]:
            points_by_load_id.setdefault(load_row["load_id"], []).append(
                {
                    "timestamp": timestamp,
                    "voltage_v": load_row["voltage_v"],
                    "current_a": load_row["current_a"],
                    "power_mw": load_row["power_mw"],
                    "label": load_row["label"],
                    "is_anomaly": load_row["is_anomaly"],
                }
            )

    if not points_by_load_id:
        raise ValueError("Replay dataset does not contain any load streams.")

    stream_count = len(points_by_load_id) if limit is None else max(1, min(int(limit), len(points_by_load_id)))
    templates: list[dict[str, Any]] = []
    for index, (load_id, points) in enumerate(list(points_by_load_id.items())[:stream_count], start=1):
        templates.append(
            {
                "stream_id": f"stream_{index:03d}",
                "source_load_id": load_id,
                "step_seconds": dataset["step_seconds"],
                "point_count": len(points),
                "points": points,
            }
        )
    return templates
