from app.property_heating import (
    extract_heating_evidence_from_html,
    extract_heating_evidence_from_text,
    heating_evidence_from_payload,
    merge_heating_into_payload,
)


def test_extracts_labelled_wood_and_oil_without_inventing_unknown_types() -> None:
    evidence = extract_heating_evidence_from_text(
        "Energieinformationen Heizungsart Zentralheizung "
        "Wesentlicher Energieträger Scheitholz / Heizöl"
    )

    assert evidence.types == ("wood", "oil")
    assert evidence.labels_de == ("Holz", "Öl")
    assert evidence.wood_preferred is True


def test_extracts_common_provider_energy_fields_from_html() -> None:
    evidence = extract_heating_evidence_from_html(
        """
        <html><body>
          <h2>Energieinformationen</h2>
          <div>Wesentlicher Energieträger</div><div>Gas</div>
          <div>Befeuerung</div><div>Gas</div>
          <div>Heizungsart</div><div>Zentralheizung</div>
        </body></html>
        """
    )

    assert evidence.types == ("gas",)
    assert evidence.wood_preferred is False
    assert evidence.evidence


def test_heat_pump_and_electric_are_distinct() -> None:
    evidence = extract_heating_evidence_from_text(
        "Heizung: Wärmepumpe mit elektrischem Zusatzheizstab"
    )

    assert evidence.types == ("electric", "heat_pump")


def test_payload_merge_preserves_previous_source_backed_evidence() -> None:
    merged = merge_heating_into_payload(
        {"heating_types": ["oil"], "heating_evidence": ["Befeuerung: Öl"]},
        extract_heating_evidence_from_text("Wesentlicher Energieträger: Scheitholz"),
    )

    evidence = heating_evidence_from_payload(merged)
    assert evidence.types == ("wood", "oil")
    assert evidence.wood_preferred
    assert merged["heating_evidence"] == [
        "Befeuerung: Öl",
        "Wesentlicher Energieträger: Scheitholz",
    ]



def test_explicit_heating_appliances_are_source_backed_evidence() -> None:
    wood = extract_heating_evidence_from_text(
        "Die Einliegerwohnung wurde bislang mit einem Holzofen beheizt."
    )
    gas = extract_heating_evidence_from_text("Warmwasser und Heizung über Gastherme.")
    electric = extract_heating_evidence_from_text("Beheizung durch Nachtspeicherofen.")

    assert wood.types == ("wood",)
    assert wood.wood_preferred
    assert gas.types == ("gas",)
    assert electric.types == ("electric",)
