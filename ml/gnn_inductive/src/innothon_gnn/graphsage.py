from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class GraphWindowSnapshot:
    window_features: np.ndarray
    adjacency: np.ndarray
    labels: np.ndarray
    window_end: str


class SpatioTemporalGraphSageClassifier:
    """Window-based inductive GraphSAGE classifier.

    The model first encodes a sliding history window for each node, then
    propagates information over graph neighborhoods. It remains inductive
    because parameters depend on features and edges, not fixed node ids.
    """

    def __init__(
        self,
        *,
        raw_feature_dim: int,
        window_size: int,
        temporal_hidden_dim: int,
        graph_hidden_dim: int,
        graph_hidden_dim_2: int,
        class_count: int,
        learning_rate: float = 0.01,
        l2_penalty: float = 1e-4,
        seed: int = 7,
    ) -> None:
        self.raw_feature_dim = raw_feature_dim
        self.window_size = window_size
        self.temporal_hidden_dim = temporal_hidden_dim
        self.graph_hidden_dim = graph_hidden_dim
        self.graph_hidden_dim_2 = graph_hidden_dim_2
        self.class_count = class_count
        self.learning_rate = learning_rate
        self.l2_penalty = l2_penalty
        self.rng = np.random.default_rng(seed)
        self.encoded_dim = temporal_hidden_dim + (2 * raw_feature_dim)
        self.parameters = self._init_parameters()

    def _init_parameters(self) -> dict[str, np.ndarray]:
        temporal_input_dim = self.window_size * self.raw_feature_dim
        temporal_scale = np.sqrt(2.0 / max(temporal_input_dim, 1))
        graph_scale_0 = np.sqrt(2.0 / max(self.encoded_dim, 1))
        graph_scale_1 = np.sqrt(2.0 / max(self.graph_hidden_dim, 1))
        out_scale = np.sqrt(2.0 / max(self.graph_hidden_dim_2, 1))
        return {
            "w_temporal": self.rng.normal(0.0, temporal_scale, (temporal_input_dim, self.temporal_hidden_dim)),
            "b_temporal": np.zeros((1, self.temporal_hidden_dim), dtype=np.float64),
            "w_self_0": self.rng.normal(0.0, graph_scale_0, (self.encoded_dim, self.graph_hidden_dim)),
            "w_neigh_0": self.rng.normal(0.0, graph_scale_0, (self.encoded_dim, self.graph_hidden_dim)),
            "b_0": np.zeros((1, self.graph_hidden_dim), dtype=np.float64),
            "w_self_1": self.rng.normal(0.0, graph_scale_1, (self.graph_hidden_dim, self.graph_hidden_dim_2)),
            "w_neigh_1": self.rng.normal(0.0, graph_scale_1, (self.graph_hidden_dim, self.graph_hidden_dim_2)),
            "b_1": np.zeros((1, self.graph_hidden_dim_2), dtype=np.float64),
            "w_out": self.rng.normal(0.0, out_scale, (self.graph_hidden_dim_2, self.class_count)),
            "b_out": np.zeros((1, self.class_count), dtype=np.float64),
        }

    def fit(
        self,
        train_snapshots: list[GraphWindowSnapshot],
        *,
        epochs: int,
        val_snapshots: list[GraphWindowSnapshot] | None = None,
    ) -> list[dict[str, float]]:
        if not train_snapshots:
            raise ValueError("No training windows were supplied.")

        history: list[dict[str, float]] = []
        for epoch in range(1, epochs + 1):
            self.rng.shuffle(train_snapshots)
            losses = []
            accuracies = []
            for snapshot in train_snapshots:
                loss, accuracy = self._train_step(snapshot)
                losses.append(loss)
                accuracies.append(accuracy)

            epoch_row = {
                "epoch": float(epoch),
                "train_loss": float(np.mean(losses)),
                "train_accuracy": float(np.mean(accuracies)),
            }
            if val_snapshots:
                epoch_row.update(self.evaluate(val_snapshots))
            history.append(epoch_row)

        return history

    def evaluate(self, snapshots: list[GraphWindowSnapshot]) -> dict[str, float]:
        losses = []
        accuracies = []
        for snapshot in snapshots:
            logits, _ = self._forward(snapshot.window_features, snapshot.adjacency)
            loss, accuracy = self._loss_and_accuracy(logits, snapshot.labels)
            losses.append(loss)
            accuracies.append(accuracy)
        return {
            "val_loss": float(np.mean(losses)) if losses else 0.0,
            "val_accuracy": float(np.mean(accuracies)) if accuracies else 0.0,
        }

    def predict_proba(self, window_features: np.ndarray, adjacency: np.ndarray) -> np.ndarray:
        logits, _ = self._forward(window_features, adjacency)
        return _softmax(logits)

    def predict(self, window_features: np.ndarray, adjacency: np.ndarray) -> np.ndarray:
        return np.argmax(self.predict_proba(window_features, adjacency), axis=1)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **self.parameters)

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        raw_feature_dim: int,
        window_size: int,
        temporal_hidden_dim: int,
        graph_hidden_dim: int,
        graph_hidden_dim_2: int,
        class_count: int,
        learning_rate: float = 0.01,
        l2_penalty: float = 1e-4,
        seed: int = 7,
    ) -> "SpatioTemporalGraphSageClassifier":
        model = cls(
            raw_feature_dim=raw_feature_dim,
            window_size=window_size,
            temporal_hidden_dim=temporal_hidden_dim,
            graph_hidden_dim=graph_hidden_dim,
            graph_hidden_dim_2=graph_hidden_dim_2,
            class_count=class_count,
            learning_rate=learning_rate,
            l2_penalty=l2_penalty,
            seed=seed,
        )
        weights = np.load(Path(path))
        model.parameters = {name: weights[name] for name in weights.files}
        return model

    def _train_step(self, snapshot: GraphWindowSnapshot) -> tuple[float, float]:
        logits, cache = self._forward(snapshot.window_features, snapshot.adjacency)
        loss, accuracy = self._loss_and_accuracy(logits, snapshot.labels)
        gradients = self._backward(cache, snapshot.labels)
        self._apply_gradients(gradients)
        return loss, accuracy

    def _forward(self, window_features: np.ndarray, adjacency: np.ndarray) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        params = self.parameters
        node_count = window_features.shape[0]
        flattened = window_features.reshape(node_count, self.window_size * self.raw_feature_dim)
        z_temporal = flattened @ params["w_temporal"] + params["b_temporal"]
        h_temporal = np.maximum(z_temporal, 0.0)

        last_step = window_features[:, -1, :]
        delta_step = window_features[:, -1, :] - window_features[:, 0, :]
        encoded = np.concatenate([h_temporal, last_step, delta_step], axis=1)

        neigh_0 = adjacency @ encoded
        z_0 = encoded @ params["w_self_0"] + neigh_0 @ params["w_neigh_0"] + params["b_0"]
        h_0 = np.maximum(z_0, 0.0)

        neigh_1 = adjacency @ h_0
        z_1 = h_0 @ params["w_self_1"] + neigh_1 @ params["w_neigh_1"] + params["b_1"]
        h_1 = np.maximum(z_1, 0.0)

        logits = h_1 @ params["w_out"] + params["b_out"]
        cache = {
            "window_features": window_features,
            "flattened": flattened,
            "z_temporal": z_temporal,
            "h_temporal": h_temporal,
            "last_step": last_step,
            "delta_step": delta_step,
            "encoded": encoded,
            "adjacency": adjacency,
            "neigh_0": neigh_0,
            "z_0": z_0,
            "h_0": h_0,
            "neigh_1": neigh_1,
            "z_1": z_1,
            "h_1": h_1,
            "logits": logits,
        }
        return logits, cache

    def _loss_and_accuracy(self, logits: np.ndarray, labels: np.ndarray) -> tuple[float, float]:
        probabilities = _softmax(logits)
        sample_count = max(len(labels), 1)
        losses = -np.log(probabilities[np.arange(sample_count), labels] + 1e-12)
        loss = float(np.mean(losses))
        loss += self.l2_penalty * sum(
            float(np.sum(weight * weight))
            for key, weight in self.parameters.items()
            if key.startswith("w_")
        )
        accuracy = float(np.mean(np.argmax(probabilities, axis=1) == labels))
        return loss, accuracy

    def _backward(self, cache: dict[str, np.ndarray], labels: np.ndarray) -> dict[str, np.ndarray]:
        params = self.parameters
        logits = cache["logits"]
        probabilities = _softmax(logits)
        node_count = max(len(labels), 1)

        grad_logits = probabilities
        grad_logits[np.arange(node_count), labels] -= 1.0
        grad_logits /= node_count

        gradients: dict[str, np.ndarray] = {}
        gradients["w_out"] = cache["h_1"].T @ grad_logits + (2.0 * self.l2_penalty * params["w_out"])
        gradients["b_out"] = grad_logits.sum(axis=0, keepdims=True)

        grad_h_1 = grad_logits @ params["w_out"].T
        grad_z_1 = grad_h_1 * (cache["z_1"] > 0.0)
        gradients["w_self_1"] = cache["h_0"].T @ grad_z_1 + (2.0 * self.l2_penalty * params["w_self_1"])
        gradients["w_neigh_1"] = cache["neigh_1"].T @ grad_z_1 + (2.0 * self.l2_penalty * params["w_neigh_1"])
        gradients["b_1"] = grad_z_1.sum(axis=0, keepdims=True)

        grad_h_0 = grad_z_1 @ params["w_self_1"].T
        grad_h_0 += cache["adjacency"].T @ (grad_z_1 @ params["w_neigh_1"].T)
        grad_z_0 = grad_h_0 * (cache["z_0"] > 0.0)
        gradients["w_self_0"] = cache["encoded"].T @ grad_z_0 + (2.0 * self.l2_penalty * params["w_self_0"])
        gradients["w_neigh_0"] = cache["neigh_0"].T @ grad_z_0 + (2.0 * self.l2_penalty * params["w_neigh_0"])
        gradients["b_0"] = grad_z_0.sum(axis=0, keepdims=True)

        grad_encoded = grad_z_0 @ params["w_self_0"].T
        grad_encoded += cache["adjacency"].T @ (grad_z_0 @ params["w_neigh_0"].T)

        grad_h_temporal = grad_encoded[:, : self.temporal_hidden_dim]
        grad_last = grad_encoded[:, self.temporal_hidden_dim : self.temporal_hidden_dim + self.raw_feature_dim]
        grad_delta = grad_encoded[:, self.temporal_hidden_dim + self.raw_feature_dim :]

        grad_last_total = grad_last + grad_delta
        grad_first = -grad_delta

        grad_z_temporal = grad_h_temporal * (cache["z_temporal"] > 0.0)
        gradients["w_temporal"] = cache["flattened"].T @ grad_z_temporal + (2.0 * self.l2_penalty * params["w_temporal"])
        gradients["b_temporal"] = grad_z_temporal.sum(axis=0, keepdims=True)
        grad_flattened = grad_z_temporal @ params["w_temporal"].T
        grad_window = grad_flattened.reshape(cache["window_features"].shape)

        grad_window[:, -1, :] += grad_last_total
        grad_window[:, 0, :] += grad_first
        return gradients

    def _apply_gradients(self, gradients: dict[str, np.ndarray]) -> None:
        for name, gradient in gradients.items():
            self.parameters[name] -= self.learning_rate * gradient


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / np.maximum(exp.sum(axis=1, keepdims=True), 1e-12)
