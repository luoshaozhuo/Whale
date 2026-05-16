"""asyncua-based OPC UA source simulator backend."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from asyncua import ua  # type: ignore[import-untyped]
from asyncua.sync import Server  # type: ignore[import-untyped]

from tools.source_lab.opcua.address_space import (
    build_address_space,
    logical_path,
    opcua_data_type,
    render_nodeset_xml,
)
from tools.source_lab.model import SimulatedPoint, SimulatedSource


class AsyncuaSourceSimulatorError(ValueError):
    """Raised when asyncua simulator startup parameters are invalid."""


class _VariableNode(Protocol):
    def write_value(self, value: object) -> object: ...

    def set_writable(self) -> object: ...


class AsyncuaSourceSimulator:
    """OPC UA simulator backend implemented with asyncua."""

    def __init__(self, source: SimulatedSource) -> None:
        normalized_protocol = (
            source.connection.protocol.strip().lower().replace("_", "").replace("-", "")
        )
        if normalized_protocol != "opcua":
            raise AsyncuaSourceSimulatorError(
                "AsyncuaSourceSimulator only supports `opcua` sources"
            )

        self._source = source
        self._address_space = build_address_space(source)
        self._server: Server | None = None
        self._temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self._write_targets_by_key: dict[str, tuple[_VariableNode, SimulatedPoint]] = {}

    @property
    def endpoint(self) -> str:
        """Return OPC UA server endpoint."""
        return self._address_space.endpoint

    @property
    def name(self) -> str:
        """Return simulator source name."""
        return self._source.connection.name

    def start(self) -> "AsyncuaSourceSimulator":
        """Start asyncua OPC UA server."""
        if self._server is not None:
            return self

        nodeset_path = self._build_nodeset_file()

        server = Server()
        server.set_endpoint(self.endpoint)
        self._apply_security(server)
        server.import_xml(path=str(nodeset_path))
        server.start()

        self._server = server
        self._write_targets_by_key = {}

        for node, point in self._build_variable_specs(server):
            full_path = logical_path(self._source.connection, point)
            target = (node, point)
            self._write_targets_by_key[point.key] = target
            self._write_targets_by_key[full_path] = target

        return self

    def stop(self) -> None:
        """Stop asyncua OPC UA server and clean temporary files."""
        if self._server is None:
            return

        self._server.stop()
        self._server = None
        self._write_targets_by_key = {}

        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None

    def __enter__(self) -> "AsyncuaSourceSimulator":
        return self.start()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stop()

    def writes(self, values_by_key: dict[str, str | int | float | bool]) -> None:
        """Write simulated point values.

        Args:
            values_by_key: Mapping from point key or full logical path to value.

        Raises:
            RuntimeError: If simulator is not started.
        """
        if self._server is None:
            raise RuntimeError("Simulator runtime must be started before writes()")

        batch_timestamp = datetime.now(tz=UTC)

        for key, value in values_by_key.items():
            target = self._write_targets_by_key.get(key)
            if target is None:
                continue

            node, point = target

            try:
                node.write_value(self._build_data_value_from_value(point, value, batch_timestamp))
            except Exception:
                # 单点写入失败不影响其他点位。
                continue

    def _build_nodeset_file(self) -> Path:
        """Build temporary NodeSet XML file."""
        self._temp_dir = tempfile.TemporaryDirectory(prefix="opcua_source_sim_")
        nodeset_path = Path(self._temp_dir.name) / f"{self.name}.nodeset.xml"
        nodeset_path.write_text(
            render_nodeset_xml(self._address_space),
            encoding="utf-8",
        )
        return nodeset_path

    def _apply_security(self, server: Server) -> None:
        """Apply OPC UA security settings from source connection."""
        security_policy = self._source.connection.security.policy
        security_mode = self._source.connection.security.mode

        if (
            self._source.connection.security.enabled
            and security_policy
            and security_mode
            and security_policy != "None"
            and security_mode != "None"
        ):
            try:
                server.set_security_policy(
                    [
                        ua.SecurityPolicyType[security_policy],
                        ua.MessageSecurityMode[security_mode],
                    ]
                )
            except (KeyError, AttributeError):
                pass

    def _build_variable_specs(
        self,
        server: Server,
    ) -> tuple[tuple[_VariableNode, SimulatedPoint], ...]:
        """Resolve variable nodes imported from NodeSet XML."""
        namespace_index = server.get_namespace_index(self._address_space.namespace_uri)
        specs: list[tuple[_VariableNode, SimulatedPoint]] = []

        for point in self._source.points:
            full_path = logical_path(self._source.connection, point)
            node = cast(_VariableNode, server.get_node(f"ns={namespace_index};s={full_path}"))

            try:
                node.set_writable()
            except Exception:
                pass

            specs.append((node, point))

        return tuple(specs)

    def _build_data_value_from_value(
        self,
        point: SimulatedPoint,
        value: str | int | float | bool | None,
        timestamp: datetime | None = None,
    ) -> ua.DataValue:
        """Build OPC UA DataValue from simulated point value."""
        now = timestamp or datetime.now(tz=UTC)

        return ua.DataValue(
            Value=self._build_variant_from_value(point, value),
            StatusCode_=ua.StatusCode(ua.StatusCodes.Good),
            SourceTimestamp=now,
        )

    def _build_variant_from_value(
        self,
        point: SimulatedPoint,
        value: str | int | float | bool | None,
    ) -> ua.Variant:
        """Build OPC UA Variant from simulated point value."""
        return ua.Variant(
            self._cast_value(point, value),
            self._variant_type_from_point(point),
        )

    def _variant_type_from_point(self, point: SimulatedPoint) -> ua.VariantType:
        """Infer OPC UA VariantType from point data type."""
        opcua_type_name = opcua_data_type(point.data_type)

        if opcua_type_name == "Boolean":
            return ua.VariantType.Boolean

        if opcua_type_name == "Int32":
            return ua.VariantType.Int32

        if opcua_type_name == "String":
            return ua.VariantType.String

        return ua.VariantType.Double

    def _cast_value(
        self,
        point: SimulatedPoint,
        value: str | int | float | bool | None,
    ) -> str | int | float | bool:
        """Cast external value to OPC UA scalar value."""
        opcua_type_name = opcua_data_type(point.data_type)

        if opcua_type_name == "Boolean":
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)

        if opcua_type_name == "Int32":
            casted = int(float(value or 0))
            return max(-2147483648, min(2147483647, casted))

        if opcua_type_name == "String":
            return str(value or "")

        return float(value or 0.0)
