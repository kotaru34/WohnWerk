import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from app.jobs import location_resolution as lr
from app.jobs import location_resolution_fallback as fallback


def _load_resolution_label():
    path = Path(__file__).resolve().parents[1] / "scripts" / "resolve_job_locations.py"
    spec = importlib.util.spec_from_file_location("test_resolve_job_locations", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module._resolution_label


_resolution_label = _load_resolution_label()


def _candidate(
    postal: str,
    name: str,
    longitude: float,
    latitude: float,
    samples: int = 100,
) -> lr.PostalCentroidCandidate:
    return lr.PostalCentroidCandidate(
        postal_code=postal,
        name=name,
        longitude=longitude,
        latitude=latitude,
        address_sample_count=samples,
    )


def test_source_sankt_spelling_matches_official_st_locality_exactly() -> None:
    candidates = [
        _candidate("3100", "St. Pölten", 15.63, 48.20),
        _candidate("4782", "St. Florian am Inn", 13.44, 48.44),
    ]

    poelten = fallback.resolve_from_candidates("Sankt Pölten", candidates)
    florian = fallback.resolve_from_candidates("Sankt Florian am Inn", candidates)

    assert poelten is not None
    assert poelten.postal_codes == ("3100",)
    assert florian is not None
    assert florian.postal_codes == ("4782",)


def test_statistics_austria_postal_membership_resolves_known_locality_labels() -> None:
    candidates = [
        _candidate("5280", "Braunau am Inn", 13.04, 48.25, 300),
        _candidate("5282", "Braunau Süd", 13.01, 48.22, 100),
        _candidate("8224", "Kaindorf", 15.91, 47.22),
        _candidate("8265", "Großsteinbach", 15.88, 47.15),
        _candidate("8770", "Sankt Michael in Obersteiermark", 15.02, 47.34),
        _candidate("8772", "Timmersdorf", 14.99, 47.38),
        _candidate("8792", "Sankt Peter-Freienstein", 15.01, 47.39),
        _candidate("8141", "Unterpremstätten", 15.40, 46.96),
        _candidate("9065", "Ebenthal/Ktn.", 14.36, 46.61),
    ]

    expected = {
        "Ranshofen": ("5280", "5282"),
        "Blaindorf": ("8224", "8265"),
        "Traboch": ("8770", "8772", "8792"),
        "Premstätten": ("8141",),
        "Ebenthal in Kärnten": ("9065",),
    }

    for label, postals in expected.items():
        resolution = fallback.resolve_from_candidates(label, candidates)
        assert resolution is not None
        assert resolution.postal_codes == postals
        assert resolution.method == fallback.OFFICIAL_LOCALITY_POSTAL_METHOD


def test_verified_sublocalities_use_only_their_evidence_backed_postal_centroid() -> None:
    candidates = [
        _candidate("6336", "Langkampfen", 12.10, 47.55, 500),
        _candidate("8055", "Graz", 15.43, 47.02, 900),
        _candidate("6020", "Innsbruck", 11.39, 47.26, 1000),
    ]

    schaftenau = fallback.resolve_from_candidates("Schaftenau", candidates)
    puntigam = fallback.resolve_from_candidates("Puntigam", candidates)

    assert schaftenau is not None
    assert schaftenau.canonical_locality == "schaftenau"
    assert schaftenau.postal_codes == ("6336",)
    assert schaftenau.method == fallback.VERIFIED_SUBLOCALITY_POSTAL_METHOD
    assert schaftenau.source == fallback.VERIFIED_SUBLOCALITY_LOCATION_SOURCE

    assert puntigam is not None
    assert puntigam.canonical_locality == "puntigam"
    assert puntigam.postal_codes == ("8055",)
    assert puntigam.method == fallback.VERIFIED_SUBLOCALITY_POSTAL_METHOD
    assert puntigam.source == fallback.VERIFIED_SUBLOCALITY_LOCATION_SOURCE


def test_region_labels_are_not_smuggled_into_point_fallbacks() -> None:
    candidates = [
        _candidate("9020", "Klagenfurt am Wörthersee", 14.31, 46.62),
        _candidate("4600", "Wels", 14.02, 48.16),
    ]

    assert fallback.resolve_from_candidates("Kärnten", candidates) is None
    assert fallback.resolve_from_candidates("Wels-Land", candidates) is None
    assert fallback.resolve_from_candidates("Bezirk Wels-Land", candidates) is None
    assert fallback.resolve_from_candidates("Graz Umgebung-West", candidates) is None


def test_location_text_can_supply_concrete_locality_without_inventing_city() -> None:
    concrete = SimpleNamespace(city=None, location_text="Wien")
    countrywide = SimpleNamespace(city=None, location_text="Kärnten")
    structured = SimpleNamespace(city="Ranshofen", location_text="Ranshofen, Oberösterreich, AT")

    assert _resolution_label(concrete) == "Wien"
    assert _resolution_label(countrywide) is None
    assert _resolution_label(structured) == "Ranshofen"
