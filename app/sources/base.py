from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(slots=True)
class RawProperty:
    source_listing_id: str
    url: str
    title: str
    description: str | None = None
    price_eur: Decimal | None = None
    living_area_m2: Decimal | None = None
    plot_area_m2: Decimal | None = None
    postal_code: str | None = None
    city: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RawJobLocation:
    postal_code: str | None = None
    city: str | None = None
    location_text: str | None = None
    remote: bool = False


@dataclass(slots=True)
class RawJob:
    source_listing_id: str
    url: str
    title: str
    company: str | None = None
    description: str | None = None
    salary_text: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    salary_payment_count: int | None = None
    salary_provenance: str | None = None
    salary_confidence: Decimal | None = None
    salary_is_minimum_only: bool | None = None
    locations: list[RawJobLocation] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourceShardSpec:
    key: str
    params: dict[str, Any] = field(default_factory=dict)
    result_cap: int | None = None
    priority: int = 100


@dataclass(slots=True)
class SourceBatch[T]:
    items: list[T]
    next_cursor: dict[str, Any] = field(default_factory=dict)
    source_reported_count: int | None = None
    coverage_complete: bool = False
    result_cap_hit: bool = False
    pages_fetched: int = 1

    def __post_init__(self) -> None:
        # A provider-reported total may be flaky across pagination (Workday CXS is
        # known to return zero on later pages). It must never under-report rows that
        # the adapter has actually materialized in this batch.
        if self.source_reported_count is not None:
            self.source_reported_count = max(self.source_reported_count, len(self.items))


class SourceFetchError(RuntimeError):
    """Source failure that preserves useful progress from a partially fetched shard."""

    def __init__(
        self,
        message: str,
        *,
        pages_fetched: int = 0,
        items_seen: int = 0,
        source_reported_count: int | None = None,
        next_cursor: dict[str, Any] | None = None,
        partial_items: list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.pages_fetched = pages_fetched
        self.items_seen = items_seen
        self.source_reported_count = source_reported_count
        self.next_cursor = next_cursor or {}
        self.partial_items = partial_items or []


class PropertySource(ABC):
    """Contract implemented by every Austrian property source adapter."""

    name: str

    @abstractmethod
    def default_shards(self) -> list[SourceShardSpec]:
        """Return a deterministic initial partition of the source search space."""

    @abstractmethod
    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawProperty]:
        """Fetch one shard and report whether coverage is actually complete."""

    async def check_active(self, source_listing_id: str) -> bool | None:
        """Return True/False when status can be checked safely, otherwise None."""
        return None


class JobSource(ABC):
    """Contract implemented by every Austrian job source adapter."""

    name: str

    @abstractmethod
    def default_shards(self) -> list[SourceShardSpec]:
        """Return a deterministic initial partition of the source search space."""

    @abstractmethod
    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawJob]:
        """Fetch one shard and report whether coverage is actually complete."""

    async def check_active(self, source_listing_id: str) -> bool | None:
        """Return True/False when status can be checked safely, otherwise None."""
        return None
