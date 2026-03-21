from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import predict_from_dataset, run_full_pipeline, train_inductive_model
from .synthetic import SyntheticConfig, generate_dataset


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inductive GNN anomaly pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser("generate", help="Generate synthetic telemetry from a graph JSON")
    generate_parser.add_argument("--graph-path", required=True)
    generate_parser.add_argument("--output-dir", required=True)
    generate_parser.add_argument("--steps", type=int, default=192)
    generate_parser.add_argument("--interval-minutes", type=int, default=5)
    generate_parser.add_argument("--seed", type=int, default=7)
    generate_parser.add_argument("--anomaly-rate", type=float, default=0.06)

    train_parser = subparsers.add_parser("train", help="Train the window-based inductive spatio-temporal GNN")
    train_parser.add_argument("--dataset-dir", required=True)
    train_parser.add_argument("--model-path", required=True)
    train_parser.add_argument("--window-size", type=int, default=6)
    train_parser.add_argument("--epochs", type=int, default=50)
    train_parser.add_argument("--temporal-hidden-dim", type=int, default=48)
    train_parser.add_argument("--graph-hidden-dim", type=int, default=48)
    train_parser.add_argument("--graph-hidden-dim-2", type=int, default=24)
    train_parser.add_argument("--learning-rate", type=float, default=0.01)
    train_parser.add_argument("--seed", type=int, default=7)

    predict_parser = subparsers.add_parser("predict", help="Predict anomaly labels from a history window")
    predict_parser.add_argument("--dataset-dir", required=True)
    predict_parser.add_argument("--model-path", required=True)
    predict_parser.add_argument("--output-csv", required=True)
    predict_parser.add_argument("--timestamp")

    pipeline_parser = subparsers.add_parser("pipeline", help="Run generation, windowed training, and prediction together")
    pipeline_parser.add_argument("--graph-path", required=True)
    pipeline_parser.add_argument("--output-dir", required=True)
    pipeline_parser.add_argument("--steps", type=int, default=192)
    pipeline_parser.add_argument("--interval-minutes", type=int, default=5)
    pipeline_parser.add_argument("--seed", type=int, default=7)
    pipeline_parser.add_argument("--anomaly-rate", type=float, default=0.06)
    pipeline_parser.add_argument("--window-size", type=int, default=6)
    pipeline_parser.add_argument("--epochs", type=int, default=50)
    pipeline_parser.add_argument("--temporal-hidden-dim", type=int, default=48)
    pipeline_parser.add_argument("--graph-hidden-dim", type=int, default=48)
    pipeline_parser.add_argument("--graph-hidden-dim-2", type=int, default=24)
    pipeline_parser.add_argument("--learning-rate", type=float, default=0.01)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "generate":
        result = generate_dataset(
            graph_path=args.graph_path,
            output_dir=args.output_dir,
            config=SyntheticConfig(
                steps=args.steps,
                interval_minutes=args.interval_minutes,
                seed=args.seed,
                anomaly_rate=args.anomaly_rate,
            ),
        )
        print(json.dumps(result, indent=2))
        return

    if args.command == "train":
        result = train_inductive_model(
            dataset_dir=args.dataset_dir,
            model_path=args.model_path,
            window_size=args.window_size,
            epochs=args.epochs,
            temporal_hidden_dim=args.temporal_hidden_dim,
            graph_hidden_dim=args.graph_hidden_dim,
            graph_hidden_dim_2=args.graph_hidden_dim_2,
            learning_rate=args.learning_rate,
            seed=args.seed,
        )
        print(json.dumps(result, indent=2))
        return

    if args.command == "predict":
        result = predict_from_dataset(
            dataset_dir=args.dataset_dir,
            model_path=args.model_path,
            output_csv=args.output_csv,
            timestamp=args.timestamp,
        )
        print(json.dumps(result, indent=2))
        return

    if args.command == "pipeline":
        output_dir = Path(args.output_dir)
        dataset_dir = output_dir / "dataset"
        model_path = output_dir / "graphsage_inductive_model.npz"
        prediction_csv = output_dir / "latest_predictions.csv"

        generate_dataset(
            graph_path=args.graph_path,
            output_dir=dataset_dir,
            config=SyntheticConfig(
                steps=args.steps,
                interval_minutes=args.interval_minutes,
                seed=args.seed,
                anomaly_rate=args.anomaly_rate,
            ),
        )
        result = run_full_pipeline(
            dataset_dir=dataset_dir,
            model_path=model_path,
            prediction_csv=prediction_csv,
            window_size=args.window_size,
            epochs=args.epochs,
            temporal_hidden_dim=args.temporal_hidden_dim,
            graph_hidden_dim=args.graph_hidden_dim,
            graph_hidden_dim_2=args.graph_hidden_dim_2,
            learning_rate=args.learning_rate,
            seed=args.seed,
        )
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
