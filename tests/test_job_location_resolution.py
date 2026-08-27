from app.jobs.location_resolution import (
    PostalCentroidCandidate,
    canonicalize_locality,
    combine_postal_centroids,
    locality_name_matches,
)


def test_vienna_alias_normalizes_to_wien() -> None:
    assert canonicalize_locality("Vienna") == "wien"
    assert canonicalize_locality("Wien") == "wien"


def test_countrywide_remote_scope_does_not_become_a_city() -> None:
    assert canonicalize_locality("Home Office (Austria)") is None
    assert canonicalize_locality("Austria") is None


def test_wien_does_not_match_wiener_neustadt() -> None:
    assert locality_name_matches("Wien Innere Stadt", "wien") is True
    assert locality_name_matches("Wien", "wien") is True
    assert locality_name_matches("Wiener Neustadt", "wien") is False


def test_locality_centroid_is_weighted_by_bev_address_samples() -> None:
    resolution = combine_postal_centroids(
        "Vienna",
        "wien",
        [
            PostalCentroidCandidate("1010", "Wien Innere Stadt", 16.37, 48.21, 100),
            PostalCentroidCandidate("1020", "Wien Leopoldstadt", 16.40, 48.22, 300),
            PostalCentroidCandidate("2700", "Wiener Neustadt", 16.25, 47.81, 500),
        ],
    )

    assert resolution is not None
    assert resolution.postal_codes == ("1010", "1020")
    assert resolution.address_sample_count == 400
    assert round(resolution.longitude, 4) == 16.3925
    assert round(resolution.latitude, 4) == 48.2175
