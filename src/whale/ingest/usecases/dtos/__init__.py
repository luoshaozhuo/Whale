"""DTOs for ingest use cases."""

from whale.ingest.usecases.dtos.acquired_node_state import AcquiredNodeState
from whale.ingest.usecases.dtos.source_acquisition_request import (
    AcquisitionExecutionOptions,
    AcquisitionItemData,
    SourceAcquisitionRequest,
)
from whale.ingest.usecases.dtos.source_acquisition_start_result import (
    SourceAcquisitionStartResult,
)
from whale.ingest.usecases.dtos.source_connection_data import SourceConnectionData

__all__ = [
    "AcquisitionItemData",
    "AcquisitionExecutionOptions",
    "AcquiredNodeState",
    "SourceAcquisitionRequest",
    "SourceAcquisitionStartResult",
    "SourceConnectionData",
]
