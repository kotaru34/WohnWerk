from types import SimpleNamespace

from app.jobs.location_cleanup import is_redundant_country_code_location


def test_lam_style_salzburg_plus_at_keeps_real_location_and_prunes_only_artifact() -> None:
    salzburg = SimpleNamespace(
        id=172,
        city="Salzburg",
        postal_code=None,
        location="POINT(13.04387009 47.8015246)",
        remote=False,
    )
    country_code = SimpleNamespace(
        id=173,
        city="AT",
        postal_code=None,
        location=None,
        remote=False,
    )

    siblings = [salzburg, country_code]

    assert is_redundant_country_code_location(salzburg, siblings) is False
    assert is_redundant_country_code_location(country_code, siblings) is True
