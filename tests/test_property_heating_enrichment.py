from datetime import UTC, datetime, timedelta

from app.property_heating_enrichment import (
    DEFAULT_SOURCE_NAMES,
    SOURCE_ALLOWED_HOSTS,
    apply_heating_detail_html,
    heating_detail_due,
)


def test_detail_enrichment_persists_only_normalized_heating_evidence() -> None:
    checked_at = datetime(2026, 10, 2, 18, 0, tzinfo=UTC)
    payload = apply_heating_detail_html(
        {"format": "provider-search-v1"},
        """
        <html><body>
          <h2>Energieinformationen</h2>
          <div>Wesentlicher Energieträger</div><div>Scheitholz</div>
          <div>Befeuerung</div><div>Holz</div>
          <h2>Objektbeschreibung</h2>
          <p>This full description must never be retained.</p>
        </body></html>
        """,
        checked_at=checked_at,
    )

    assert payload["heating_types"] == ["wood"]
    assert payload["heating_enrichment_status"] == "found"
    assert payload["heating_checked_at"] == "2026-10-02T18:00:00+00:00"
    assert "description" not in payload
    assert "This full description" not in str(payload)


def test_heating_detail_refresh_is_bounded_by_checked_timestamp() -> None:
    now = datetime(2026, 10, 2, 18, 0, tzinfo=UTC)

    assert heating_detail_due(
        {},
        now=now,
        refresh_after=timedelta(days=7),
    )
    assert not heating_detail_due(
        {"heating_checked_at": "2026-10-01T18:00:00+00:00"},
        now=now,
        refresh_after=timedelta(days=7),
    )
    assert heating_detail_due(
        {"heating_checked_at": "2026-09-20T18:00:00+00:00"},
        now=now,
        refresh_after=timedelta(days=7),
    )



def test_default_heating_enrichment_skips_von_poll_blocked_details() -> None:
    assert DEFAULT_SOURCE_NAMES == (
        "kleinanzeigen-de",
        "engel-voelkers-de",
        "iad-de",
        "falc-de",
    )


def test_immowelt_heating_labels_extract_public_energy_carrier_without_description() -> None:
    checked_at = datetime(2026, 10, 4, 20, 0, tzinfo=UTC)
    payload = apply_heating_detail_html(
        {"format": "immowelt-public-search-v2"},
        """
        <html><body>
          <h2>Bausubstanz und Energie</h2>
          <div>Heizungsart</div><div>Ofen</div>
          <div>Energieträger</div><div>Öl</div>
          <h2>Über den Anbieter</h2>
          <p>Broker contact details must not be retained.</p>
        </body></html>
        """,
        checked_at=checked_at,
    )

    assert payload["heating_types"] == ["oil"]
    assert payload["heating_enrichment_status"] == "found"
    assert "Broker contact details" not in str(payload)


def test_immowelt_is_allowed_only_for_caller_owned_browser_transport() -> None:
    assert SOURCE_ALLOWED_HOSTS["immowelt-de"] == frozenset(
        {"immowelt.de", "www.immowelt.de"}
    )
    assert "immowelt-de" not in DEFAULT_SOURCE_NAMES
