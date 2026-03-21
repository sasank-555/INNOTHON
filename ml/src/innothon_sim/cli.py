from __future__ import annotations

import argparse
import json

from .compare import compare_readings
from .io import dump_json, load_network_definition, load_readings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="INNOTHON pandapower helper CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    simulate_parser = subparsers.add_parser("simulate", help="Run load flow on a network JSON")
    simulate_parser.add_argument("network_json", help="Path to the network definition JSON")
    simulate_parser.add_argument(
        "--output",
        help="Optional path for writing the serialized simulation snapshot",
    )

    compare_parser = subparsers.add_parser(
        "compare",
        help="Compare a network simulation against a sensor readings JSON",
    )
    compare_parser.add_argument("network_json", help="Path to the network definition JSON")
    compare_parser.add_argument("readings_json", help="Path to sensor readings JSON")
    compare_parser.add_argument(
        "--output",
        help="Optional path for writing comparison results",
    )

    return parser


def main() -> int:
    from .pandapower_adapter import run_simulation

    args = build_parser().parse_args()
    if args.command == "simulate":
        definition = load_network_definition(args.network_json)
        artifacts = run_simulation(definition)
        payload = artifacts.snapshot
        if args.output:
            dump_json(args.output, payload)
        else:
            print(json.dumps(payload, indent=2))
        return 0

    definition = load_network_definition(args.network_json)
    artifacts = run_simulation(definition)
    readings = load_readings(args.readings_json)
    payload = compare_readings(definition, artifacts.snapshot, readings)
    if args.output:
        dump_json(args.output, payload)
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
