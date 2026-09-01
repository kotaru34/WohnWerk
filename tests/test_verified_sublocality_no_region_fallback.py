from app.jobs import location_resolution as lr
from app.jobs import location_resolution_fallback as fallback


def test_verified_sublocality_does_not_make_broad_region_resolvable() -> None:
    candidates = [
        lr.PostalCentroidCandidate(
            postal_code="8055",
            name="Graz",
            longitude=15.43,
            latitude=47.02,
            address_sample_count=900,
        )
    ]

    assert fallback.resolve_from_candidates("Puntigam", candidates) is not None
    assert fallback.resolve_from_candidates("Steiermark", candidates) is None
    assert fallback.resolve_from_candidates("Graz Umgebung-West", candidates) is None
