from app.jobs.location_resolution import PostalCentroidCandidate
from app.jobs.location_resolution_fallback import resolve_from_candidates


def test_st_valentin_matches_rtr_name_despite_period_normalization() -> None:
    resolution = resolve_from_candidates(
        "St. Valentin",
        [
            PostalCentroidCandidate(
                postal_code="4300",
                name="St. Valentin",
                longitude=14.5167,
                latitude=48.1667,
                address_sample_count=100,
            )
        ],
    )

    assert resolution is not None
    assert resolution.canonical_locality == "st valentin"
    assert resolution.postal_codes == ("4300",)


def test_punctuation_fallback_stays_conservative() -> None:
    resolution = resolve_from_candidates(
        "St. Valentin",
        [
            PostalCentroidCandidate(
                postal_code="2700",
                name="St. Valentinberg",
                longitude=16.0,
                latitude=48.0,
                address_sample_count=100,
            )
        ],
    )

    assert resolution is None
