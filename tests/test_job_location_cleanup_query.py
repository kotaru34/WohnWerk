from types import SimpleNamespace

from app.jobs.location_cleanup import is_redundant_country_code_location


def test_aut_country_code_variant_requires_same_concrete_sibling_proof() -> None:
    artifact = SimpleNamespace(
        id=4,
        city="AUT",
        postal_code=None,
        location=None,
        remote=False,
    )
    concrete = SimpleNamespace(
        id=3,
        city="Linz",
        postal_code="4020",
        location=None,
        remote=False,
    )

    assert is_redundant_country_code_location(artifact, [concrete, artifact]) is True
