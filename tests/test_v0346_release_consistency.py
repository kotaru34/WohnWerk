from app.jobs.location_resolution_fallback import VERIFIED_SUBLOCALITY_POSTAL_METHOD
from app.version import __version__


def test_v0346_release_consistency() -> None:
    assert __version__ == "0.3.46"
    assert VERIFIED_SUBLOCALITY_POSTAL_METHOD == "verified_sublocality_postal_centroid"
