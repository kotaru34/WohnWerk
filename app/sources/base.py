from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Generic, TypeVar


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
    locations: list[RawJobLocation] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourceShardSpec:
    key: str
    params: dict[str, Any] = field(default_factory=dict)
    result_cap: int | None = None
    priority: int = 100


T = TypeVar("T")


@dataclass(slots=True)
class SourceBatch(Generic[T]):
    items: list[T]
    next_cursor: dict[str, Any] = field(default_factory=dict)
    source_reported_count: int | None = None
    coverage_complete: bool = False
    result_cap_hit: bool = False
    pages_fetched: int = 1


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
