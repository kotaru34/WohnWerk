from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Self

import httpx


class RoutingError(RuntimeError):
    """Raised when the configured road router cannot return a usable matrix."""


@dataclass(frozen=True, slots=True)
class RoutingPoint:
    longitude: float
    latitude: float

    def __post_init__(self) -> None:
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError("longitude must be between -180 and 180")
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError("latitude must be between -90 and 90")

    def osrm_coordinate(self) -> str:
        return f"{self.longitude:.6f},{self.latitude:.6f}"


@dataclass(frozen=True, slots=True)
class RouteEstimate:
    distance_km: float | None
    duration_minutes: float | None

    @property
    def reachable(self) -> bool:
        return self.distance_km is not None and self.duration_minutes is not None


class OSRMClient:
    """Small synchronous client for OSRM's one-to-many Table service."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 2.0,
        max_table_coordinates: int = 100,
        client: httpx.Client | None = None,
    ) -> None:
        if max_table_coordinates < 2:
            raise ValueError("max_table_coordinates must be at least 2")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_table_coordinates = max_table_coordinates
        self._client = client
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def table(
        self,
        source: RoutingPoint,
        destinations: Sequence[RoutingPoint],
    ) -> list[RouteEstimate]:
        """Return fastest-route metrics from one source to many destinations.

        OSRM's table limit counts the source and destinations together. Requests are
        chunked automatically so the default 100-coordinate server limit is respected.
        """
        if not destinations:
            return []

        batch_size = self.max_table_coordinates - 1
        results: list[RouteEstimate] = []
        for start in range(0, len(destinations), batch_size):
            results.extend(self._table_batch(source, destinations[start : start + batch_size]))
        return results

    def _table_batch(
        self,
        source: RoutingPoint,
        destinations: Sequence[RoutingPoint],
    ) -> list[RouteEstimate]:
        coordinates = [source, *destinations]
        coordinate_path = ";".join(point.osrm_coordinate() for point in coordinates)
        destination_indexes = ";".join(str(index) for index in range(1, len(coordinates)))
        url = f"{self.base_url}/table/v1/driving/{coordinate_path}"

        client = self._client
        if client is None:
            client = httpx.Client(timeout=self.timeout_seconds)
            self._client = client

        try:
            response = client.get(
                url,
                params={
                    "sources": "0",
                    "destinations": destination_indexes,
                    "annotations": "distance,duration",
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RoutingError(f"OSRM table request failed: {exc}") from exc

        if payload.get("code") != "Ok":
            message = payload.get("message") or payload.get("code") or "unknown OSRM error"
            raise RoutingError(f"OSRM table request failed: {message}")

        distances = _first_matrix_row(payload.get("distances"), "distances")
        durations = _first_matrix_row(payload.get("durations"), "durations")
        if len(distances) != len(destinations) or len(durations) != len(destinations):
            raise RoutingError("OSRM table response size does not match destinations")

        return [
            RouteEstimate(
                distance_km=None if distance is None else float(distance) / 1000.0,
                duration_minutes=None if duration is None else float(duration) / 60.0,
            )
            for distance, duration in zip(distances, durations, strict=True)
        ]


def _first_matrix_row(value: object, field: str) -> list[float | None]:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], list):
        raise RoutingError(f"OSRM table response has invalid {field}")
    return value[0]
