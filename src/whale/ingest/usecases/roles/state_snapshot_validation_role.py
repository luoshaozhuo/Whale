"""StateSnapshotValidationRole — 发布前校验 latest-state snapshot 有效性."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from whale.ingest.usecases.dtos.cached_source_state import CachedSourceState


class SnapshotStatus:
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"


class ItemQuality:
    GOOD = "GOOD"
    STALE = "STALE"
    UNKNOWN_AGE = "UNKNOWN_AGE"


@dataclass(slots=True)
class SnapshotValidationResult:
    """snapshot 校验结果."""

    status: str  # HEALTHY / DEGRADED / INVALID
    stale_item_count: int = 0
    invalid_item_count: int = 0
    max_age_ms: int | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ItemValidation:
    quality: str
    validity: str
    age_ms: int | None


class StateSnapshotValidationRole:
    """读取 latest-state 后根据 acquisition_mode 判断数据是否可用.

    POLLING / READ_ONCE：看 ingested_at 与 freshness_timeout_ms。
    SUBSCRIBE：看 source_health.last_alive_at 与 alive_timeout_ms。
    """

    def validate(
        self,
        snapshot: list[CachedSourceState],
        *,
        acquisition_mode: str | None = None,
        last_alive_at: datetime | None = None,
        freshness_timeout_ms: int = 30000,
        alive_timeout_ms: int = 60000,
    ) -> SnapshotValidationResult:
        if not snapshot:
            return SnapshotValidationResult(
                status=SnapshotStatus.INVALID,
                invalid_item_count=0,
                warnings=["snapshot is empty"],
            )

        now = datetime.now(tz=UTC)
        stale_count = 0
        invalid_count = 0
        max_age_ms = 0
        warnings: list[str] = []

        is_subscribe = (acquisition_mode or "").upper() == "SUBSCRIBE"

        for item in snapshot:
            age_ms = self._compute_age_ms(item, now)

            if age_ms is not None and age_ms > max_age_ms:
                max_age_ms = age_ms

            if is_subscribe:
                item_quality = self._judge_subscribe_item(
                    item, last_alive_at, alive_timeout_ms, now
                )
            else:
                item_quality = self._judge_polling_item(
                    item, age_ms, freshness_timeout_ms
                )

            if item_quality == ItemQuality.STALE:
                stale_count += 1

        if stale_count == len(snapshot):
            return SnapshotValidationResult(
                status=SnapshotStatus.INVALID,
                stale_item_count=stale_count,
                invalid_item_count=invalid_count,
                max_age_ms=max_age_ms,
                warnings=["all items are stale"],
            )

        if stale_count > 0:
            return SnapshotValidationResult(
                status=SnapshotStatus.DEGRADED,
                stale_item_count=stale_count,
                invalid_item_count=invalid_count,
                max_age_ms=max_age_ms,
                warnings=[f"{stale_count} items are stale"],
            )

        return SnapshotValidationResult(
            status=SnapshotStatus.HEALTHY,
            stale_item_count=0,
            invalid_item_count=0,
            max_age_ms=max_age_ms,
        )

    @staticmethod
    def _compute_age_ms(
        item: CachedSourceState,
        now: datetime,
    ) -> int | None:
        observed_at = item.source_observed_at
        if observed_at is None:
            return None
        return int((now - observed_at).total_seconds() * 1000)

    @staticmethod
    def _judge_polling_item(
        item: CachedSourceState,
        age_ms: int | None,
        freshness_timeout_ms: int,
    ) -> str:
        if age_ms is None:
            return ItemQuality.UNKNOWN_AGE
        if age_ms > freshness_timeout_ms:
            return ItemQuality.STALE
        return ItemQuality.GOOD

    @staticmethod
    def _judge_subscribe_item(
        item: CachedSourceState,
        last_alive_at: datetime | None,
        alive_timeout_ms: int,
        now: datetime,
    ) -> str:
        if last_alive_at is None:
            return ItemQuality.UNKNOWN_AGE
        alive_age_ms = (now - last_alive_at).total_seconds() * 1000
        if alive_age_ms > alive_timeout_ms:
            return ItemQuality.STALE
        return ItemQuality.GOOD
