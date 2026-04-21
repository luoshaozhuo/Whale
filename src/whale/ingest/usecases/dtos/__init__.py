"""DTOs for ingest use cases."""

from whale.ingest.usecases.dtos.maintain_source_state_command import (
    MaintainSourceStateCommand,
)
from whale.ingest.usecases.dtos.maintain_source_state_result import (
    MaintainSourceStateResult,
)
from whale.ingest.usecases.dtos.source_config_data import SourceConfigData
from whale.ingest.usecases.dtos.source_runtime_config_data import (
    SourceRuntimeConfigData,
)
from whale.ingest.usecases.dtos.source_state_data import SourceStateData

__all__ = [
    "MaintainSourceStateCommand",
    "MaintainSourceStateResult",
    "SourceConfigData",
    "SourceRuntimeConfigData",
    "SourceStateData",
]
