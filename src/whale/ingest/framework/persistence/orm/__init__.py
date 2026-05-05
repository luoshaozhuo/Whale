"""Ingest ORM models — fully consolidated into whale.shared.persistence.orm.

All former ingest ORM models have been replaced by shared-ORM equivalents:
  - whale.shared.persistence.orm.AcquisitionTask     (table acq_task)
  - whale.shared.persistence.orm.DOState             (table acq_do_state)
  - whale.shared.persistence.orm.StateSnapshotOutbox (table acq_outbox)
"""

__all__: list[str] = []
