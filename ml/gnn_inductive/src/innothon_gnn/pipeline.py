from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, f1_score

from .graph_io import EdgeRecord, build_mean_adjacency
from .graphsage import GraphWindowSnapshot, SpatioTemporalGraphSageClassifier


def train_inductive_model(
    dataset_dir: str | Path,
    model_path: str | Path,
    *,
    window_size: int = 6,
    epochs: int = 50,
    temporal_hidden_dim: int = 48,
    graph_hidden_dim: int = 48,
    graph_hidden_dim_2: int = 24,
    learning_rate: float = 0.01,
    seed: int = 7,
) -> dict[str, Any]:
    dataset_dir = Path(dataset_dir)
    model_path = Path(model_path)

    nodes_df, edges_df, timeseries_df = _load_dataset(dataset_dir)
    node_ids = nodes_df["node_id"].tolist()
    node_type_values = sorted(nodes_df["node_type"].unique())
    class_names = sorted(timeseries_df["label"].unique())
    label_to_index = {label: index for index, label in enumerate(class_names)}
    raw_feature_names = _raw_feature_names(node_type_values)

    timestamps = sorted(timeseries_df["timestamp"].unique())
    if len(timestamps) < window_size:
        raise ValueError(f"Need at least {window_size} timestamps, found {len(timestamps)}.")

    train_cutoff = max(window_size, int(len(timestamps) * 0.7))
    val_cutoff = max(train_cutoff + 1, int(len(timestamps) * 0.85))
    train_window_end_indices = list(range(window_size - 1, train_cutoff))
    val_window_end_indices = list(range(train_cutoff, val_cutoff))
    test_window_end_indices = list(range(val_cutoff, len(timestamps))) or [len(timestamps) - 1]

    rng = np.random.default_rng(seed)
    load_nodes = nodes_df.loc[nodes_df["node_type"] == "load", "node_id"].tolist()
    shuffled_load_nodes = list(load_nodes)
    rng.shuffle(shuffled_load_nodes)
    holdout_count = max(1, int(len(shuffled_load_nodes) * 0.2))
    unseen_load_nodes = set(shuffled_load_nodes[:holdout_count])
    seen_load_nodes = set(shuffled_load_nodes[holdout_count:])
    train_node_ids = [
        node_id
        for node_id in node_ids
        if node_id not in load_nodes or node_id in seen_load_nodes
    ]

    full_adjacency = _build_adjacency(node_ids, edges_df)
    train_adjacency = _build_adjacency(train_node_ids, edges_df)
    train_indices = [node_ids.index(node_id) for node_id in train_node_ids]

    train_windows_full = _build_window_snapshots(
        window_end_indices=train_window_end_indices,
        timestamps=timestamps,
        node_ids=node_ids,
        nodes_df=nodes_df,
        timeseries_df=timeseries_df,
        node_type_values=node_type_values,
        label_to_index=label_to_index,
        window_size=window_size,
    )
    train_windows = [
        GraphWindowSnapshot(
            window_features=snapshot.window_features[train_indices],
            adjacency=train_adjacency,
            labels=snapshot.labels[train_indices],
            window_end=snapshot.window_end,
        )
        for snapshot in train_windows_full
    ]

    feature_mean, feature_std = _fit_window_scaler(train_windows)
    train_windows = [_scale_window_snapshot(snapshot, feature_mean, feature_std) for snapshot in train_windows]

    val_windows = _build_window_snapshots(
        window_end_indices=val_window_end_indices,
        timestamps=timestamps,
        node_ids=node_ids,
        nodes_df=nodes_df,
        timeseries_df=timeseries_df,
        node_type_values=node_type_values,
        label_to_index=label_to_index,
        window_size=window_size,
    )
    val_windows = [
        GraphWindowSnapshot(
            window_features=_scale_window_features(snapshot.window_features[train_indices], feature_mean, feature_std),
            adjacency=train_adjacency,
            labels=snapshot.labels[train_indices],
            window_end=snapshot.window_end,
        )
        for snapshot in val_windows
    ]

    model = SpatioTemporalGraphSageClassifier(
        raw_feature_dim=len(raw_feature_names),
        window_size=window_size,
        temporal_hidden_dim=temporal_hidden_dim,
        graph_hidden_dim=graph_hidden_dim,
        graph_hidden_dim_2=graph_hidden_dim_2,
        class_count=len(class_names),
        learning_rate=learning_rate,
        seed=seed,
    )
    history = model.fit(train_windows, epochs=epochs, val_snapshots=val_windows)
    model.save(model_path)

    test_windows = _build_window_snapshots(
        window_end_indices=test_window_end_indices,
        timestamps=timestamps,
        node_ids=node_ids,
        nodes_df=nodes_df,
        timeseries_df=timeseries_df,
        node_type_values=node_type_values,
        label_to_index=label_to_index,
        window_size=window_size,
    )
    test_windows = [
        GraphWindowSnapshot(
            window_features=_scale_window_features(snapshot.window_features, feature_mean, feature_std),
            adjacency=full_adjacency,
            labels=snapshot.labels,
            window_end=snapshot.window_end,
        )
        for snapshot in test_windows
    ]
    metrics = _evaluate_inductive_test(
        model=model,
        windows=test_windows,
        node_ids=node_ids,
        load_nodes=load_nodes,
        unseen_load_nodes=unseen_load_nodes,
        class_names=class_names,
    )

    metadata = {
        "window_size": window_size,
        "raw_feature_names": raw_feature_names,
        "class_names": class_names,
        "node_type_values": node_type_values,
        "feature_mean": feature_mean.tolist(),
        "feature_std": feature_std.tolist(),
        "full_node_ids": node_ids,
        "train_node_ids": train_node_ids,
        "temporal_hidden_dim": temporal_hidden_dim,
        "graph_hidden_dim": graph_hidden_dim,
        "graph_hidden_dim_2": graph_hidden_dim_2,
        "learning_rate": learning_rate,
        "seed": seed,
        "inductive_split": {
            "seen_load_nodes": sorted(seen_load_nodes),
            "unseen_load_nodes": sorted(unseen_load_nodes),
        },
        "history": history,
        "metrics": metrics,
        "window_end_timestamps": {
            "train": [timestamps[index] for index in train_window_end_indices],
            "validation": [timestamps[index] for index in val_window_end_indices],
            "test": [timestamps[index] for index in test_window_end_indices],
        },
    }
    metadata_path = model_path.with_suffix(".meta.json")
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return {
        "model_path": str(model_path),
        "metadata_path": str(metadata_path),
        "metrics": metrics,
    }


def predict_from_dataset(
    dataset_dir: str | Path,
    model_path: str | Path,
    *,
    output_csv: str | Path,
    timestamp: str | None = None,
) -> dict[str, Any]:
    dataset_dir = Path(dataset_dir)
    output_csv = Path(output_csv)

    nodes_df, edges_df, timeseries_df = _load_dataset(dataset_dir)
    metadata = json.loads(model_path.with_suffix(".meta.json").read_text(encoding="utf-8"))
    node_ids = nodes_df["node_id"].tolist()
    timestamps = sorted(timeseries_df["timestamp"].unique())
    timestamp = timestamp or timestamps[-1]
    if timestamp not in timestamps:
        raise ValueError(f"Timestamp {timestamp} not found in dataset.")

    window_end_index = timestamps.index(timestamp)
    window_size = int(metadata["window_size"])
    if window_end_index + 1 < window_size:
        raise ValueError(
            f"Timestamp {timestamp} does not have enough history for window size {window_size}."
        )

    snapshot = _build_window_snapshots(
        window_end_indices=[window_end_index],
        timestamps=timestamps,
        node_ids=node_ids,
        nodes_df=nodes_df,
        timeseries_df=timeseries_df,
        node_type_values=metadata["node_type_values"],
        label_to_index={label: index for index, label in enumerate(metadata["class_names"])},
        window_size=window_size,
    )[0]
    adjacency = _build_adjacency(node_ids, edges_df)
    window_features = _scale_window_features(
        snapshot.window_features,
        np.asarray(metadata["feature_mean"], dtype=np.float64),
        np.asarray(metadata["feature_std"], dtype=np.float64),
    )

    model = SpatioTemporalGraphSageClassifier.load(
        model_path,
        raw_feature_dim=len(metadata["raw_feature_names"]),
        window_size=window_size,
        temporal_hidden_dim=int(metadata["temporal_hidden_dim"]),
        graph_hidden_dim=int(metadata["graph_hidden_dim"]),
        graph_hidden_dim_2=int(metadata["graph_hidden_dim_2"]),
        class_count=len(metadata["class_names"]),
        learning_rate=float(metadata["learning_rate"]),
        seed=int(metadata["seed"]),
    )
    probabilities = model.predict_proba(window_features, adjacency)
    predictions = np.argmax(probabilities, axis=1)
    normal_index = metadata["class_names"].index("normal") if "normal" in metadata["class_names"] else None
    window_start = timestamps[window_end_index - window_size + 1]

    output_rows = []
    for index, node_id in enumerate(node_ids):
        predicted_label = metadata["class_names"][int(predictions[index])]
        anomaly_score = (
            1.0 - float(probabilities[index, normal_index])
            if normal_index is not None
            else float(probabilities[index].max())
        )
        output_rows.append(
            {
                "window_start": window_start,
                "window_end": timestamp,
                "node_id": node_id,
                "node_type": nodes_df.iloc[index]["node_type"],
                "predicted_label": predicted_label,
                "predicted_probability": round(float(probabilities[index].max()), 6),
                "anomaly_score": round(anomaly_score, 6),
            }
        )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(output_rows).to_csv(output_csv, index=False)
    return {
        "window_start": window_start,
        "window_end": timestamp,
        "output_csv": str(output_csv),
        "row_count": len(output_rows),
    }


def run_full_pipeline(
    *,
    dataset_dir: str | Path,
    model_path: str | Path,
    prediction_csv: str | Path,
    window_size: int = 6,
    epochs: int = 50,
    temporal_hidden_dim: int = 48,
    graph_hidden_dim: int = 48,
    graph_hidden_dim_2: int = 24,
    learning_rate: float = 0.01,
    seed: int = 7,
) -> dict[str, Any]:
    train_result = train_inductive_model(
        dataset_dir=dataset_dir,
        model_path=model_path,
        window_size=window_size,
        epochs=epochs,
        temporal_hidden_dim=temporal_hidden_dim,
        graph_hidden_dim=graph_hidden_dim,
        graph_hidden_dim_2=graph_hidden_dim_2,
        learning_rate=learning_rate,
        seed=seed,
    )
    predict_result = predict_from_dataset(
        dataset_dir=dataset_dir,
        model_path=model_path,
        output_csv=prediction_csv,
    )
    return {
        "train": train_result,
        "predict": predict_result,
    }


def _load_dataset(dataset_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    nodes_df = pd.read_csv(dataset_dir / "nodes.csv")
    edges_df = pd.read_csv(dataset_dir / "edges.csv")
    timeseries_df = pd.read_csv(dataset_dir / "timeseries.csv")
    nodes_df = nodes_df.sort_values("node_id").reset_index(drop=True)
    edges_df = edges_df.sort_values(["source", "target", "edge_id"]).reset_index(drop=True)
    timeseries_df = timeseries_df.sort_values(["timestamp", "node_id"]).reset_index(drop=True)
    return nodes_df, edges_df, timeseries_df


def _build_adjacency(node_ids: list[str], edges_df: pd.DataFrame) -> np.ndarray:
    edges = [
        EdgeRecord(
            edge_id=str(row.edge_id),
            source=str(row.source),
            target=str(row.target),
            edge_type=str(row.edge_type),
            length_km=float(row.length_km),
        )
        for row in edges_df.itertuples(index=False)
    ]
    return build_mean_adjacency(node_ids, edges)


def _build_window_snapshots(
    *,
    window_end_indices: list[int],
    timestamps: list[str],
    node_ids: list[str],
    nodes_df: pd.DataFrame,
    timeseries_df: pd.DataFrame,
    node_type_values: list[str],
    label_to_index: dict[str, int],
    window_size: int,
) -> list[GraphWindowSnapshot]:
    nodes_index = nodes_df.set_index("node_id")
    time_node_index = timeseries_df.set_index(["timestamp", "node_id"])
    snapshots: list[GraphWindowSnapshot] = []

    for window_end_index in window_end_indices:
        if window_end_index + 1 < window_size:
            continue

        window_timestamps = timestamps[window_end_index - window_size + 1 : window_end_index + 1]
        node_windows = []
        labels = []
        for node_id in node_ids:
            static_row = nodes_index.loc[node_id]
            node_window = []
            label_index = 0
            for step_index, timestamp in enumerate(window_timestamps):
                dynamic_row = time_node_index.loc[(timestamp, node_id)]
                raw_features = _raw_feature_vector(
                    static_row=static_row,
                    dynamic_row=dynamic_row,
                    node_type_values=node_type_values,
                )
                node_window.append(raw_features)
                if step_index == window_size - 1:
                    label_index = label_to_index[str(dynamic_row["label"])]
            node_windows.append(node_window)
            labels.append(label_index)

        snapshots.append(
            GraphWindowSnapshot(
                window_features=np.asarray(node_windows, dtype=np.float64),
                adjacency=np.empty((0, 0), dtype=np.float64),
                labels=np.asarray(labels, dtype=np.int64),
                window_end=timestamps[window_end_index],
            )
        )

    return snapshots


def _raw_feature_vector(
    *,
    static_row: pd.Series,
    dynamic_row: pd.Series,
    node_type_values: list[str],
) -> list[float]:
    base_voltage = max(float(static_row["base_voltage_v"]), 1.0)
    nominal_power = max(float(static_row["nominal_power_kw"]), 1.0)
    nominal_current = max((nominal_power * 1000.0) / base_voltage, 0.05)
    node_type = str(static_row["node_type"])
    type_one_hot = [1.0 if node_type == known else 0.0 for known in node_type_values]
    return [
        float(dynamic_row["voltage_v"]),
        float(dynamic_row["current_a"]),
        float(dynamic_row["power_kw"]),
        float(dynamic_row["power_kw"]) / nominal_power,
        float(dynamic_row["voltage_v"]) / base_voltage,
        float(dynamic_row["current_a"]) / nominal_current,
        float(static_row["nominal_power_kw"]),
        float(static_row["base_voltage_v"]) / 1000.0,
        float(static_row["degree"]),
        *type_one_hot,
    ]


def _fit_window_scaler(snapshots: list[GraphWindowSnapshot]) -> tuple[np.ndarray, np.ndarray]:
    stacked = np.concatenate([snapshot.window_features.reshape(-1, snapshot.window_features.shape[-1]) for snapshot in snapshots], axis=0)
    mean = stacked.mean(axis=0)
    std = stacked.std(axis=0)
    std[std < 1e-6] = 1.0
    return mean, std


def _scale_window_features(window_features: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return (window_features - mean.reshape(1, 1, -1)) / std.reshape(1, 1, -1)


def _scale_window_snapshot(snapshot: GraphWindowSnapshot, mean: np.ndarray, std: np.ndarray) -> GraphWindowSnapshot:
    return GraphWindowSnapshot(
        window_features=_scale_window_features(snapshot.window_features, mean, std),
        adjacency=snapshot.adjacency,
        labels=snapshot.labels,
        window_end=snapshot.window_end,
    )


def _raw_feature_names(node_type_values: list[str]) -> list[str]:
    return [
        "voltage_v",
        "current_a",
        "power_kw",
        "power_ratio",
        "voltage_ratio",
        "current_ratio",
        "nominal_power_kw",
        "base_voltage_kv",
        "degree",
        *[f"type_{node_type}" for node_type in node_type_values],
    ]


def _evaluate_inductive_test(
    *,
    model: SpatioTemporalGraphSageClassifier,
    windows: list[GraphWindowSnapshot],
    node_ids: list[str],
    load_nodes: list[str],
    unseen_load_nodes: set[str],
    class_names: list[str],
) -> dict[str, Any]:
    load_indices = [node_ids.index(node_id) for node_id in load_nodes]
    unseen_indices = [node_ids.index(node_id) for node_id in load_nodes if node_id in unseen_load_nodes]

    true_all: list[int] = []
    pred_all: list[int] = []
    true_unseen: list[int] = []
    pred_unseen: list[int] = []

    for window in windows:
        predictions = model.predict(window.window_features, window.adjacency)
        true_all.extend(window.labels[load_indices].tolist())
        pred_all.extend(predictions[load_indices].tolist())
        true_unseen.extend(window.labels[unseen_indices].tolist())
        pred_unseen.extend(predictions[unseen_indices].tolist())

    return {
        "all_load_nodes": {
            "accuracy": float(accuracy_score(true_all, pred_all)),
            "macro_f1": float(f1_score(true_all, pred_all, average="macro", zero_division=0)),
            "report": classification_report(
                true_all,
                pred_all,
                labels=list(range(len(class_names))),
                target_names=class_names,
                zero_division=0,
                output_dict=True,
            ),
        },
        "unseen_load_nodes": {
            "accuracy": float(accuracy_score(true_unseen, pred_unseen)) if true_unseen else 0.0,
            "macro_f1": float(f1_score(true_unseen, pred_unseen, average="macro", zero_division=0)) if true_unseen else 0.0,
            "report": classification_report(
                true_unseen,
                pred_unseen,
                labels=list(range(len(class_names))),
                target_names=class_names,
                zero_division=0,
                output_dict=True,
            ) if true_unseen else {},
        },
    }
