from app.jobs.location_resolution import PostalCentroidCandidate
from app.jobs.location_resolution_fallback import resolve_from_candidates


def _candidate(postal_code: str, name: str, *, longitude: float = 14.0):
    return PostalCentroidCandidate(
        postal_code=postal_code,
        name=name,
        longitude=longitude,
        latitude=48.0,
        address_sample_count=100,
    )


def test_st_valentin_matches_rtr_name_despite_period_normalization() -> None:
    resolution = resolve_from_candidates(
        "St. Valentin",
        [_candidate("4300", "St. Valentin", longitude=14.5167)],
    )

    assert resolution is not None
    assert resolution.canonical_locality == "st valentin"
    assert resolution.postal_codes == ("4300",)


def test_punctuation_fallback_stays_conservative() -> None:
    resolution = resolve_from_candidates(
        "St. Valentin",
        [_candidate("2700", "St. Valentinberg")],
    )

    assert resolution is None


def test_city_suffix_can_reuse_explicit_city_centroid() -> None:
    resolution = resolve_from_candidates(
        "Salzburg Stadt",
        [
            _candidate("5020", "Salzburg", longitude=13.04),
            _candidate("5023", "Salzburg-Gnigl", longitude=13.06),
        ],
    )

    assert resolution is not None
    assert resolution.canonical_locality == "salzburg"
    assert resolution.postal_codes == ("5020", "5023")


def test_vienna_district_label_resolves_to_vienna_without_guessing_a_district_point() -> None:
    resolution = resolve_from_candidates(
        "Wien 3. Bezirk (Landstraße)",
        [_candidate("1010", "Wien", longitude=16.37)],
    )

    assert resolution is not None
    assert resolution.canonical_locality == "wien"
    assert resolution.postal_codes == ("1010",)


def test_qualified_locality_can_drop_bezirk_hint_when_base_is_unique() -> None:
    resolution = resolve_from_candidates(
        "Niederndorf bei Kufstein",
        [_candidate("6342", "Niederndorf")],
    )

    assert resolution is not None
    assert resolution.canonical_locality == "niederndorf"
    assert resolution.postal_codes == ("6342",)


def test_qualified_locality_stays_unresolved_when_base_is_ambiguous() -> None:
    resolution = resolve_from_candidates(
        "Kirchschlag bei Linz",
        [
            _candidate("4202", "Kirchschlag"),
            _candidate("2860", "Kirchschlag in der Buckligen Welt"),
        ],
    )

    assert resolution is None
