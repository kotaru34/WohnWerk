import pytest

from app.geo import radius_metres


def test_radius_metres_converts_km() -> None:
    assert radius_metres(50) == 50_000
    assert radius_metres(100) == 100_000


def test_radius_metres_rejects_non_positive_values() -> None:
    with pytest.raises(ValueError):
        radius_metres(0)

    with pytest.raises(ValueError):
        radius_metres(-1)
