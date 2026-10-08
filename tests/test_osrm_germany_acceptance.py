"""Acceptance probe checks geographical coverage without editing the server."""

from app.routing import RouteEstimate
from scripts.check_osrm_germany import CITIES, assess_routes


class _Router:
    def __init__(self, *, bad: bool = False) -> None:
        self.bad = bad
        self.calls = []

    def table(self, origin, destinations):
        self.calls.append((origin, destinations))
        if origin == CITIES["munich"].point:
            return [
                RouteEstimate(distance_km=600.0, duration_minutes=360.0),
                RouteEstimate(
                    distance_km=190.0 if self.bad else 790.0,
                    duration_minutes=470.0,
                ),
                RouteEstimate(distance_km=580.0, duration_minutes=340.0),
            ]
        return [
            RouteEstimate(distance_km=300.0, duration_minutes=210.0),
            RouteEstimate(distance_km=490.0, duration_minutes=300.0),
        ]


def test_osrm_probe_checks_two_origins_and_all_five_routes(capsys) -> None:
    router = _Router()
    assert assess_routes(router) == []
    assert len(router.calls) == 2
    assert "München" in capsys.readouterr().out


def test_osrm_probe_rejects_implausibly_short_german_route() -> None:
    result = assess_routes(_Router(bad=True))
    assert len(result) == 1
    assert "Hamburg" in result[0]
    assert "190.0 km" in result[0]
