import pytest

from app.http_normalization import NormalizeHouseQueryMiddleware, normalize_house_query_string


def test_blank_optional_house_numbers_are_omitted() -> None:
    raw = (
        b"ort=Graz&preis_von=&preis_bis=150000&wohn_von=90&wohn_bis="
        b"&grund_von=300&grund_bis=&seite=2"
    )

    assert normalize_house_query_string(raw) == (
        b"ort=Graz&preis_bis=150000&wohn_von=90&grund_von=300&seite=2"
    )


def test_nonblank_values_are_preserved() -> None:
    raw = b"preis_von=100000.50&wohn_bis=120&ort=St.+P%C3%B6lten"

    assert normalize_house_query_string(raw) == raw


@pytest.mark.asyncio
async def test_middleware_only_normalizes_house_catalog() -> None:
    captured: list[bytes] = []

    async def downstream(scope, receive, send):
        del receive, send
        captured.append(scope["query_string"])

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        del message

    middleware = NormalizeHouseQueryMiddleware(downstream)
    query = b"preis_von=&preis_bis=150000"

    await middleware(
        {"type": "http", "path": "/houses", "query_string": query},
        receive,
        send,
    )
    await middleware(
        {"type": "http", "path": "/jobs", "query_string": query},
        receive,
        send,
    )

    assert captured == [b"preis_bis=150000", query]
