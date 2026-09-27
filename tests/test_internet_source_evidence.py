from __future__ import annotations

from app.internet_source_evidence import (
    ADDRESS_STREET_HOUSE_NUMBER,
    EVIDENCE_LISTING_CLAIM,
    EVIDENCE_PORTAL_ADDRESS_ESTIMATE,
    parse_immoscout_de_internet_evidence,
    parse_immowelt_de_internet_evidence,
)


def test_immoscout_structured_portal_estimate_preserves_address_semantics() -> None:
    body = """
    <html><body>
      <script>
        {
          "obj_telekomInternetAvailable":"true",
          "obj_telekomInternetSpeed":"1000 MBit/s",
          "obj_street":"Würzburger Straße",
          "obj_houseNumber":"35",
          "obj_zipCode":"97990",
          "obj_regio3":"Weikersheim"
        }
      </script>
      <section>
        <h2>Internet Geschwindigkeit</h2>
        <div>Bis zu 1000 MBit/s Glasfaser-Internet</div>
      </section>
    </body></html>
    """

    parsed = parse_immoscout_de_internet_evidence(
        "https://www.immobilienscout24.de/expose/170438210",
        body,
    )

    assert parsed.source_address == "Würzburger Straße 35, 97990 Weikersheim"
    assert parsed.address_precision == ADDRESS_STREET_HOUSE_NUMBER
    assert len(parsed.claims) == 1
    claim = parsed.claims[0]
    assert claim.evidence_kind == EVIDENCE_PORTAL_ADDRESS_ESTIMATE
    assert claim.availability_status == "available"
    assert claim.claim_semantics == "non_binding_address_estimate"
    assert claim.provider_name == "Telekom"
    assert claim.technology == "Glasfaser"
    assert claim.max_download_mbps == 1000


def test_immoscout_no_information_is_not_negative_evidence() -> None:
    body = """
    <script>
      {
        "obj_telekomInternetAvailable":null,
        "obj_telekomInternetSpeed":"no_information",
        "obj_street":"no_information",
        "obj_houseNumber":"no_information",
        "obj_zipCode":"01067"
      }
    </script>
    """

    parsed = parse_immoscout_de_internet_evidence(
        "https://www.immobilienscout24.de/expose/170000001",
        body,
    )

    assert parsed.claims == ()
    assert parsed.source_address is None
    assert parsed.address_precision is None


def test_immoscout_explicit_false_is_preserved_without_invented_speed() -> None:
    body = """
    <script>
      {
        "obj_telekomInternetAvailable":false,
        "obj_telekomInternetSpeed":null,
        "obj_street":"Musterweg",
        "obj_houseNumber":"8",
        "obj_zipCode":"01067",
        "obj_regio3":"Dresden"
      }
    </script>
    """

    parsed = parse_immoscout_de_internet_evidence(
        "https://www.immobilienscout24.de/expose/170000002",
        body,
    )

    assert len(parsed.claims) == 1
    claim = parsed.claims[0]
    assert claim.availability_status == "unavailable"
    assert claim.max_download_mbps is None
    assert parsed.source_address == "Musterweg 8, 01067 Dresden"


def test_immowelt_provider_rows_are_kept_as_distinct_expose_claims() -> None:
    body = """
    <html><body>
      <h2>Internet</h2>
      <div>M-Net: Glasfaser 1.000 MBit/s</div>
      <div>Vodafone: Kabel 1.000 MBit/s</div>
      <div>Telekom: DSL 100 MBit/s</div>
    </body></html>
    """

    parsed = parse_immowelt_de_internet_evidence(
        "https://www.immowelt.de/expose/1ad2c8c6-1a7b-4218-b71c-c814c367d8f1",
        body,
    )

    assert len(parsed.claims) == 3
    assert {
        (claim.provider_name, claim.technology, claim.max_download_mbps)
        for claim in parsed.claims
    } == {
        ("M-Net", "Glasfaser", 1000),
        ("Vodafone", "Kabel", 1000),
        ("Telekom", "DSL", 100),
    }
    assert all(claim.evidence_kind == EVIDENCE_LISTING_CLAIM for claim in parsed.claims)


def test_immowelt_narrative_download_upload_and_fiber_connection_are_distinct() -> None:
    body = """
    <html><body>
      <p>Im Haus ist Internet per DSL (max. 250 MBit/s im Download, bis zu 40 MBit/s im Upload) möglich.</p>
      <p>Per Kabel lassen sich Bandbreiten von 1000 MBit/s im Download und max. 75 MBit/s im Upload erreichen.</p>
      <p>Das Gebäude ist bereits an das Glasfaser-Netz angeschlossen.</p>
    </body></html>
    """

    parsed = parse_immowelt_de_internet_evidence(
        "https://www.immowelt.de/expose/example123456",
        body,
    )

    dsl = next(claim for claim in parsed.claims if claim.technology == "DSL")
    assert dsl.max_download_mbps == 250
    assert dsl.max_upload_mbps == 40
    fiber = next(
        claim
        for claim in parsed.claims
        if claim.technology == "Glasfaser" and claim.availability_status == "connected"
    )
    assert fiber.max_download_mbps is None


def test_immowelt_json_ld_exact_address_is_source_address_evidence() -> None:
    body = """
    <html><head>
      <script type="application/ld+json">
        {
          "@context":"https://schema.org",
          "@type":"House",
          "address":{
            "@type":"PostalAddress",
            "streetAddress":"Dorstener Str. 376c",
            "postalCode":"44809",
            "addressLocality":"Bochum"
          }
        }
      </script>
    </head><body>
      <div>Internet: Kabelinternet bis 1.000 MBit/s laut Verfügbarkeitscheck</div>
    </body></html>
    """

    parsed = parse_immowelt_de_internet_evidence(
        "https://www.immowelt.de/expose/e0cd96f7-e486-4da5-9c33-83d0d639fa9a",
        body,
    )

    assert parsed.source_address == "Dorstener Str. 376c, 44809 Bochum"
    assert parsed.address_precision == ADDRESS_STREET_HOUSE_NUMBER
    claim = next(claim for claim in parsed.claims if claim.max_download_mbps == 1000)
    assert claim.technology == "Kabel"
    assert claim.claim_semantics == "availability_check"


def test_austrian_hosts_are_out_of_scope_for_source_internet_parser() -> None:
    body = '<div>Internet Geschwindigkeit Bis zu 1000 MBit/s Glasfaser-Internet</div>'

    assert (
        parse_immoscout_de_internet_evidence(
            "https://www.immobilienscout24.at/expose/123",
            body,
        ).claims
        == ()
    )
