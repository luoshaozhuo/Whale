"""Command-line entry point for running the repository-local OPC UA simulator fleet."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from tools.opcua_sim.fleet_runtime import OpcUaFleetRuntime
from tools.opcua_sim.server_runtime import DEFAULT_NAMESPACE_URI

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_NODESET_PATH = TEMPLATE_DIR / "OPCUANodeSet.xml"
DEFAULT_CONFIG_PATH = TEMPLATE_DIR / "OPCUA_client_connections.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the repository-local OPC UA simulator fleet."
    )
    parser.add_argument(
        "--from-db",
        action="store_true",
        help="Read turbine configurations and variable definitions from the whale database "
             "(acq_task + v_measurement_point).  Default: use YAML + static NodeSet.",
    )
    parser.add_argument(
        "--nodeset-path",
        default=str(DEFAULT_NODESET_PATH),
        help="Path to the NodeSet XML (ignored when --from-db is set).",
    )
    parser.add_argument(
        "--config-path",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the OPC UA connection YAML file (ignored when --from-db is set).",
    )
    parser.add_argument(
        "--namespace-uri",
        default=DEFAULT_NAMESPACE_URI,
        help="Namespace URI expected inside the NodeSet and simulator runtime.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.from_db:
        fleet = OpcUaFleetRuntime.from_database(namespace_uri=args.namespace_uri)
    else:
        fleet = OpcUaFleetRuntime.from_connection_config(
            nodeset_path=args.nodeset_path,
            config_path=args.config_path,
            namespace_uri=args.namespace_uri,
        )

    with fleet:
        endpoints = fleet.endpoints()
        print(f"Simulator fleet started ({len(endpoints)} servers):", flush=True)
        for name, ep in endpoints.items():
            print(f"  {name}: {ep}", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            print("Stopping simulator fleet...", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
