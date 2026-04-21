"""Acquisition role for maintain-source-state use case."""

from __future__ import annotations

from whale.ingest.ports.source.source_acquisition_port import SourceAcquisitionPort
from whale.ingest.usecases.dtos.source_config_data import SourceConfigData
from whale.ingest.usecases.dtos.source_state_data import SourceStateData


class AcquisitionRole:
    """Acquire source states into shared use-case data."""

    def __init__(
        self,
        data: SourceStateData,
        acquisition_port: SourceAcquisitionPort,
    ) -> None:
        """Bind the role to source-state data and acquisition port."""
        self._data = data
        self._acquisition_port = acquisition_port

    def acquire(self) -> None:
        """Acquire source states and store them in shared data."""
        if not self._data.enabled:
            self._data.acquired_states = []
            self._data.received_count = 0
            self._data.updated_count = 0
            self._data.acquisition_status = "DISABLED"
            self._data.last_error = None
            return

        try:
            states = self._acquisition_port.read_once(self._build_source_config())
        except Exception as exc:
            self._data.acquired_states = []
            self._data.received_count = 0
            self._data.acquisition_status = "FAILED"
            self._data.last_error = str(exc)
            return

        self._data.acquired_states = states
        self._data.received_count = len(states)
        self._data.last_error = None
        self._data.acquisition_status = "SUCCEEDED" if states else "EMPTY"

    def _build_source_config(self) -> SourceConfigData:
        """Build an acquisition-ready config snapshot from shared data."""
        return SourceConfigData(
            source_id=self._data.source_id,
            source_name=self._data.source_name,
            protocol=self._data.protocol,
            endpoint=self._data.endpoint,
            security_policy=self._data.security_policy,
            security_mode=self._data.security_mode,
            update_interval_ms=self._data.update_interval_ms,
            enabled=self._data.enabled,
        )
