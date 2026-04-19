"""Helpers for starting multiple simulator servers from one YAML config."""

from __future__ import annotations

from pathlib import Path

import yaml

from tools.opcua_sim.server_runtime import (
    DEFAULT_NAMESPACE_URI,
    OpcUaServerRuntime,
    load_server_config,
)


class OpcUaFleetRuntime:
    """Manage a group of simulator servers defined in one connection YAML file."""

    def __init__(self, runtimes: list[OpcUaServerRuntime]) -> None:
        """Store the concrete runtimes that belong to the fleet."""
        self._runtimes = runtimes

    @classmethod
    def from_connection_config(
        cls,
        nodeset_path: str | Path,
        config_path: str | Path,
        namespace_uri: str = DEFAULT_NAMESPACE_URI,
    ) -> "OpcUaFleetRuntime":
        """Build one runtime per connection entry found in the YAML config."""
        raw_config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        connections = raw_config.get("connections", []) if isinstance(raw_config, dict) else []
        runtimes = [
            OpcUaServerRuntime(
                nodeset_path=nodeset_path,
                config=load_server_config(config_path, str(item["name"])),
                namespace_uri=namespace_uri,
            )
            for item in connections
        ]
        return cls(runtimes)

    def start(self) -> "OpcUaFleetRuntime":
        """Start every server runtime in the fleet."""
        for runtime in self._runtimes:
            runtime.start()
        return self

    def stop(self) -> None:
        """Stop every server runtime in reverse order."""
        for runtime in reversed(self._runtimes):
            runtime.stop()

    def endpoints(self) -> dict[str, str]:
        """Return the resolved endpoint by logical server name."""
        return {runtime.name: runtime.endpoint for runtime in self._runtimes}

    def __enter__(self) -> "OpcUaFleetRuntime":
        """Start the fleet as a context manager."""
        return self.start()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Stop the fleet as a context manager."""
        self.stop()
