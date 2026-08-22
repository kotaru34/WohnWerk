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
    locations: list[RawJobLocation] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)


class PropertySource(ABC):
    """Contract implemented by every Austrian property source adapter."""

    name: str

    @abstractmethod
    async def fetch_recent(self) -> list[RawProperty]:
        """Return newly discoverable/recent listings according to source policy."""

    async def check_active(self, source_listing_id: str) -> bool | None:
        """Return True/False when status can be checked safely, otherwise None."""
        return None


class JobSource(ABC):
    """Contract implemented by every Austrian job source adapter."""

    name: str

    @abstractmethod
    async def fetch_recent(self) -> list[RawJob]:
        """Return newly discoverable/recent vacancies according to source policy."""

    async def check_active(self, source_listing_id: str) -> bool | None:
        """Return True/False when status can be checked safely, otherwise None."""
        return None
