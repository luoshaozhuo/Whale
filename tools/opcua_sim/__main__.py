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
    """Build the CLI parser for the OPC UA simulator fleet runner."""
    parser = argparse.ArgumentParser(description="Run the repository-local OPC UA simulator fleet.")
    parser.add_argument(
        "--nodeset-path",
        default=str(DEFAULT_NODESET_PATH),
        help="Path to the NodeSet XML used to populate the simulator address space.",
    )
    parser.add_argument(
        "--config-path",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the OPC UA connection YAML file.",
    )
    parser.add_argument(
        "--namespace-uri",
        default=DEFAULT_NAMESPACE_URI,
        help="Namespace URI expected inside the NodeSet and simulator runtime.",
    )
    return parser


def main() -> int:
    """Start the OPC UA simulator fleet and keep it running until interrupted."""
    args = build_parser().parse_args()
    fleet = OpcUaFleetRuntime.from_connection_config(
        nodeset_path=args.nodeset_path,
        config_path=args.config_path,
        namespace_uri=args.namespace_uri,
    )

    with fleet:
        print(f"Simulator fleet started: {fleet.endpoints()}", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            print("Stopping simulator fleet...", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
