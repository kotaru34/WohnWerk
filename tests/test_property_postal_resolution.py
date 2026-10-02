from app.ingestion.properties import _unique_de_postal_by_city
from app.models import PostalCode


def _postal(code: str, name: str) -> PostalCode:
    return PostalCode(postal_code=code, name=name)


def test_unique_city_postal_resolution_accepts_only_one_five_digit_code() -> None:
    resolved = _unique_de_postal_by_city(
        [
            _postal("97618", "Münnerstadt"),
            _postal("80331", "München"),
            _postal("80333", "München"),
            _postal("1010", "Wien"),
        ]
    )

    assert resolved["münnerstadt"].postal_code == "97618"
    assert "münchen" not in resolved
    assert "wien" not in resolved


def test_city_postal_resolution_normalizes_case_and_space() -> None:
    resolved = _unique_de_postal_by_city([_postal("98527", "  Suhl  ")])

    assert resolved["suhl"].postal_code == "98527"
