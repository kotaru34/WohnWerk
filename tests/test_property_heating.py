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



def test_english_broker_energy_source_fields_are_normalized() -> None:
    oil = extract_heating_evidence_from_text(
        "Energy efficiency information | Energy source | Central heating, Oil heating"
    )
    gas = extract_heating_evidence_from_text("Energy source | Gas heating")
    pump = extract_heating_evidence_from_text("Energy source | Heat pump")

    assert oil.types == ("oil",)
    assert gas.types == ("gas",)
    assert pump.types == ("heat_pump",)


def test_negated_planned_and_removed_heating_mentions_do_not_become_current() -> None:
    negated = extract_heating_evidence_from_text(
        "Keine Gasheizung vorhanden. Beheizung durch Wärmepumpe."
    )
    planned = extract_heating_evidence_from_text(
        "Gasheizung geplant, aktuell Nachtspeicheröfen."
    )
    removed = extract_heating_evidence_from_text(
        "Die alte Ölheizung wurde entfernt. Heute Elektroheizung."
    )
    historical = extract_heating_evidence_from_text(
        "Früher mit Öl beheizt; inzwischen Fernwärme."
    )

    assert negated.types == ("heat_pump",)
    assert planned.types == ("electric",)
    assert removed.types == ("electric",)
    assert historical.types == ("district",)


def test_unrelated_gas_and_electric_words_are_not_heating_evidence() -> None:
    evidence = extract_heating_evidence_from_text(
        "Gasherd in der Küche, Wallbox für Elektroauto und neuer Stromanschluss."
    )
    assert evidence.types == ()


def test_current_old_but_operating_gas_heating_is_not_mistaken_for_historical() -> None:
    evidence = extract_heating_evidence_from_text(
        "Die vorhandene Gasheizung stammt aus dem Jahr 2010 und ist in Betrieb."
    )
    assert evidence.types == ("gas",)
