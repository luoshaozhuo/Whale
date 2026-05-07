"""RuntimeDiagnosticsRole — 采集运行时诊断记录."""

from __future__ import annotations

from datetime import UTC, datetime

from whale.ingest.ports.diagnostics import IngestRuntimeDiagnosticsPort
from whale.ingest.usecases.roles.acquisition_failure_classifier_role import (
    AcquisitionFailureClassifierRole,
)


class RuntimeDiagnosticsRole:
    """调用 IngestRuntimeDiagnosticsPort，记录 failure/success/recovered.

    不做异常分类（交给 AcquisitionFailureClassifierRole），不做采集，不做重试。
    """

    def __init__(
        self,
        diagnostics_port: IngestRuntimeDiagnosticsPort,
        classifier: AcquisitionFailureClassifierRole | None = None,
    ) -> None:
        self._port = diagnostics_port
        self._classifier = classifier or AcquisitionFailureClassifierRole()

    def record_success(
        self,
        task_id: int,
        ld_instance_id: int,
        acquisition_mode: str,
    ) -> None:
        self._port.mark_success(task_id, ld_instance_id, acquisition_mode)

    def record_failure(
        self,
        task_id: int,
        ld_instance_id: int,
        acquisition_mode: str,
        exception: Exception,
        protocol: str | None = None,
    ) -> None:
        classification = self._classifier.classify(exception, protocol=protocol)
        self._port.record_failure(
            task_id=task_id,
            ld_instance_id=ld_instance_id,
            acquisition_mode=acquisition_mode,
            failure_category=classification.category,
            error_code=classification.code,
            error_message=str(exception),
        )

    def record_recovered(
        self,
        task_id: int,
        ld_instance_id: int,
        acquisition_mode: str,
    ) -> None:
        self._port.record_recovered(task_id, ld_instance_id, acquisition_mode)

    def record_keepalive(
        self,
        task_id: int,
        ld_instance_id: int,
        acquisition_mode: str,
    ) -> None:
        self._port.mark_alive(task_id, ld_instance_id, acquisition_mode)

    def record_success_at(
        self,
        task_id: int,
        ld_instance_id: int,
        acquisition_mode: str,
        at: datetime | None = None,
    ) -> None:
        self.record_success(task_id, ld_instance_id, acquisition_mode)
