from app.jobs.location_resolution_fallback import (
    VERIFIED_SUBLOCALITY_POSTAL_METHOD,
    verified_sublocality_postal_codes,
)
from app.version import __version__


def test_v0346_geo_policy_marker() -> None:
    assert __version__ == "0.3.46"
    assert VERIFIED_SUBLOCALITY_POSTAL_METHOD == "verified_sublocality_postal_centroid"
    assert verified_sublocality_postal_codes("Schaftenau") == ("6336",)
    assert verified_sublocality_postal_codes("Puntigam") == ("8055",)
