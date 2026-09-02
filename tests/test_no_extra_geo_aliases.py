from app.jobs.location_resolution_fallback import verified_sublocality_postal_codes


def test_verified_sublocality_allow_list_stays_narrow() -> None:
    assert verified_sublocality_postal_codes("Schaftenau") == ("6336",)
    assert verified_sublocality_postal_codes("Puntigam") == ("8055",)
    assert verified_sublocality_postal_codes("Kärnten") == ()
    assert verified_sublocality_postal_codes("Wels-Land") == ()
