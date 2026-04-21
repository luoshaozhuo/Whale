"""Executable entrypoint for the ingest runtime."""

from __future__ import annotations

from whale.ingest.adapters.config.db_source_config_adapter import (
    DbSourceConfigAdapter,
)
from whale.ingest.adapters.config.db_source_runtime_config_adapter import (
    DbSourceRuntimeConfigAdapter,
)
from whale.ingest.adapters.source.opcua_source_acquisition_adapter import (
    OpcUaSourceAcquisitionAdapter,
)
from whale.ingest.adapters.store.noop_source_state_repository_adapter import (
    NoOpSourceStateRepositoryAdapter,
)
from whale.ingest.framework.persistence.init_db import init_db
from whale.ingest.runtime.scheduler import SourceScheduler
from whale.ingest.usecases.maintain_source_state_usecase import (
    MaintainSourceStateUseCase,
)


def main() -> None:
    """Build runtime dependencies and start the ingest scheduler."""
    init_db()

    runtime_config_port = DbSourceRuntimeConfigAdapter()
    source_config_port = DbSourceConfigAdapter()
    acquisition_port = OpcUaSourceAcquisitionAdapter()
    state_repository_port = NoOpSourceStateRepositoryAdapter()

    use_case = MaintainSourceStateUseCase(
        source_config_port=source_config_port,
        acquisition_port=acquisition_port,
        store_port=state_repository_port,
    )
    scheduler = SourceScheduler(
        runtime_config_port=runtime_config_port,
        use_case=use_case,
    )
    scheduler.run()


if __name__ == "__main__":
    main()
