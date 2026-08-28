import httpx
import pytest

from app.routing import OSRMClient, RoutingError, RoutingPoint


def test_osrm_table_returns_distance_and_duration() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.startswith("/table/v1/driving/")
        assert request.url.params["sources"] == "0"
        assert request.url.params["destinations"] == "1;2"
        assert request.url.params["annotations"] == "distance,duration"
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "distances": [[1234.0, None]],
                "durations": [[120.0, None]],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    router = OSRMClient("http://router.test", client=client)

    result = router.table(
        RoutingPoint(longitude=16.37, latitude=48.21),
        [
            RoutingPoint(longitude=16.40, latitude=48.22),
            RoutingPoint(longitude=16.50, latitude=48.30),
        ],
    )

    assert result[0].distance_km == pytest.approx(1.234)
    assert result[0].duration_minutes == pytest.approx(2.0)
    assert result[0].reachable is True
    assert result[1].distance_km is None
    assert result[1].duration_minutes is None
    assert result[1].reachable is False


def test_osrm_table_chunks_to_server_coordinate_limit() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        destination_count = len(request.url.params["destinations"].split(";"))
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "distances": [[1000.0] * destination_count],
                "durations": [[60.0] * destination_count],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    router = OSRMClient(
        "http://router.test",
        client=client,
        max_table_coordinates=3,
    )

    result = router.table(
        RoutingPoint(longitude=16.37, latitude=48.21),
        [
            RoutingPoint(longitude=16.40 + index * 0.01, latitude=48.22)
            for index in range(5)
        ],
    )

    assert len(result) == 5
    assert calls == 3


def test_osrm_table_rejects_non_ok_payload() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"code": "NoTable", "message": "No route"})
        )
    )
    router = OSRMClient("http://router.test", client=client)

    with pytest.raises(RoutingError, match="No route"):
        router.table(
            RoutingPoint(longitude=16.37, latitude=48.21),
            [RoutingPoint(longitude=16.40, latitude=48.22)],
        )


def test_routing_point_validates_coordinate_range() -> None:
    with pytest.raises(ValueError):
        RoutingPoint(longitude=181.0, latitude=48.21)

    with pytest.raises(ValueError):
        RoutingPoint(longitude=16.37, latitude=91.0)
