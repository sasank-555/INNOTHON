from __future__ import annotations

import argparse
import json

from .io import dump_json, load_readings


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
    from .service import compare_network_payload, simulate_network_payload

    args = build_parser().parse_args()
    if args.command == "simulate":
        with open(args.network_json, encoding="utf-8") as file:
            network_payload = json.load(file)
        response = simulate_network_payload(network_payload)
        payload = response["snapshot"]
        if args.output:
            dump_json(args.output, payload)
        else:
            print(json.dumps(payload, indent=2))
        return 0

    with open(args.network_json, encoding="utf-8") as file:
        network_payload = json.load(file)
    readings = load_readings(args.readings_json)
    response = compare_network_payload(network_payload, readings)
    payload = response["comparisons"]
    if args.output:
        dump_json(args.output, payload)
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
