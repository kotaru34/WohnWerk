from app.jobs.discovery import classify_job_candidate
from app.sources.job import personio

SITE = personio.PersonioSite(tenant="example-at", company="Example Engineering GmbH")
AUSTRIAN_LOCALITIES = {"graz", "wien", "linz", "hohenberg", "anif"}


def _position(xml: str):
    return personio.ET.fromstring(xml)


def test_personio_unverified_site_tries_current_then_legacy_domain() -> None:
    assert personio.personio_feed_urls(SITE) == (
        "https://example-at.jobs.personio.com/xml",
        "https://example-at.jobs.personio.de/xml",
    )


def test_personio_verified_base_url_is_pinned() -> None:
    site = personio.PersonioSite(
        tenant="example-at",
        company="Example Engineering GmbH",
        base_url="https://example-at.jobs.personio.de",
    )

    assert personio.personio_feed_urls(site) == (
        "https://example-at.jobs.personio.de/xml",
    )


def test_personio_city_only_austrian_office_is_kept() -> None:
    item = personio.parse_personio_position(
        _position(
            """
            <position>
              <id>123</id>
              <office>Graz</office>
              <department>Mechanics</department>
              <name>Senior Mechanical Engineer (w/m/d)</name>
              <jobDescriptions>
                <jobDescription>
                  <name>Deine Mission</name>
                  <value><![CDATA[<p>Mechanische Konstruktion, CAD und FEM.</p>]]></value>
                </jobDescription>
              </jobDescriptions>
              <employmentType>permanent</employmentType>
              <schedule>full-time</schedule>
            </position>
            """
        ),
        site=SITE,
        austrian_localities=AUSTRIAN_LOCALITIES,
    )

    assert item is not None
    assert item.source_listing_id == "example-at:123"
    assert item.title == "Senior Mechanical Engineer (w/m/d)"
    assert item.company == "Example Engineering GmbH"
    assert item.locations[0].city == "graz"
    assert item.url == "https://example-at.jobs.personio.com/job/123?language=de"
    assert "Mechanische Konstruktion" in (item.description or "")
    assert item.raw_payload["personio_department"] == "Mechanics"
    assert item.raw_payload["personio_xml_language"] == "de"


def test_personio_vienna_alias_is_kept_without_country_suffix() -> None:
    item = personio.parse_personio_position(
        _position(
            """
            <position>
              <id>124</id>
              <office>Vienna</office>
              <name>Project Engineer</name>
            </position>
            """
        ),
        site=SITE,
        austrian_localities=AUSTRIAN_LOCALITIES,
    )

    assert item is not None
    assert item.locations[0].city == "wien"


def test_personio_vienna_alias_inside_venue_label_is_kept() -> None:
    item = personio.parse_personio_position(
        _position(
            """
            <position>
              <id>125</id>
              <office>Austria Center Vienna</office>
              <name>Ingenieur:in Gebäudetechnik</name>
            </position>
            """
        ),
        site=SITE,
        austrian_localities=AUSTRIAN_LOCALITIES,
    )

    assert item is not None
    assert item.locations[0].city == "wien"
    assert item.locations[0].location_text == "Austria Center Vienna"


def test_personio_explicit_austria_office_is_kept() -> None:
    item = personio.parse_personio_position(
        _position(
            """
            <position>
              <id>456</id>
              <office>Hohenberg, Österreich</office>
              <name>Techniker Maschinenbau</name>
            </position>
            """
        ),
        site=SITE,
        austrian_localities=AUSTRIAN_LOCALITIES,
    )

    assert item is not None
    assert item.locations[0].city == "hohenberg"
    assert item.locations[0].location_text == "Hohenberg, Österreich"


def test_personio_parenthesized_austria_office_is_kept() -> None:
    item = personio.parse_personio_position(
        _position(
            """
            <position>
              <id>457</id>
              <office>Linz (Österreich)</office>
              <name>Techniker Maschinenbau</name>
            </position>
            """
        ),
        site=SITE,
        austrian_localities=AUSTRIAN_LOCALITIES,
    )

    assert item is not None
    assert item.locations[0].city == "linz"


def test_personio_non_austrian_four_digit_postcode_is_not_austria_evidence() -> None:
    item = personio.parse_personio_position(
        _position(
            """
            <position>
              <id>458</id>
              <office>8000 Zürich</office>
              <name>Mechanical Engineer</name>
            </position>
            """
        ),
        site=SITE,
        austrian_localities=AUSTRIAN_LOCALITIES,
    )

    assert item is None


def test_personio_non_austrian_office_is_rejected() -> None:
    item = personio.parse_personio_position(
        _position(
            """
            <position>
              <id>789</id>
              <office>Munich</office>
              <name>Konstrukteur Maschinenbau</name>
            </position>
            """
        ),
        site=SITE,
        austrian_localities=AUSTRIAN_LOCALITIES,
    )

    assert item is None


def test_personio_feed_reports_all_positions_but_returns_only_austrian_jobs() -> None:
    payload = b"""
    <workzag-jobs>
      <position>
        <id>1</id><office>Wien</office><name>Project Engineer</name>
      </position>
      <position>
        <id>2</id><office>Berlin</office><name>Project Engineer</name>
      </position>
    </workzag-jobs>
    """

    items, total = personio.parse_personio_feed(
        payload,
        site=SITE,
        austrian_localities=AUSTRIAN_LOCALITIES,
    )

    assert total == 2
    assert [item.source_listing_id for item in items] == ["example-at:1"]
    assert items[0].locations[0].city == "wien"


def test_personio_english_feed_sets_english_job_url() -> None:
    item = personio.parse_personio_position(
        _position(
            """
            <position>
              <id>900</id>
              <office>Vienna</office>
              <name>Test Engineer</name>
              <jobDescriptions>
                <jobDescription>
                  <name>Responsibilities</name>
                  <value><![CDATA[<p>Testing and qualification of mechanical systems.</p>]]></value>
                </jobDescription>
              </jobDescriptions>
            </position>
            """
        ),
        site=SITE,
        austrian_localities=AUSTRIAN_LOCALITIES,
        language="en",
    )

    assert item is not None
    assert item.url.endswith("/job/900?language=en")
    assert item.raw_payload["personio_xml_language"] == "en"


def test_personio_language_merge_falls_back_to_english_description() -> None:
    de_item = personio.parse_personio_position(
        _position(
            """
            <position>
              <id>901</id><office>Vienna</office><name>Electrical Engineer</name>
            </position>
            """
        ),
        site=SITE,
        austrian_localities=AUSTRIAN_LOCALITIES,
        language="de",
    )
    en_item = personio.parse_personio_position(
        _position(
            """
            <position>
              <id>901</id><office>Vienna</office><name>Electrical Engineer</name>
              <jobDescriptions>
                <jobDescription>
                  <name>Responsibilities</name>
                  <value><![CDATA[
                    <p>Design and development for automotive systems, verification and testing.</p>
                  ]]></value>
                </jobDescription>
              </jobDescriptions>
            </position>
            """
        ),
        site=SITE,
        austrian_localities=AUSTRIAN_LOCALITIES,
        language="en",
    )

    assert de_item is not None
    assert en_item is not None
    merged = personio.merge_personio_language_items({"de": [de_item], "en": [en_item]})

    assert len(merged) == 1
    assert merged[0].description == en_item.description
    assert merged[0].url.endswith("?language=en")
    assert merged[0].raw_payload["personio_xml_languages"] == ["de", "en"]
    assert merged[0].raw_payload["personio_primary_description_language"] == "en"
    decision = classify_job_candidate(merged[0])
    assert decision.accepted is True
    assert "vehicle_engineering" in decision.domain_matches
    assert "validation" in decision.method_tool_matches
    assert "testing" in decision.method_tool_matches


def test_personio_language_merge_preserves_german_primary_and_english_discovery_text() -> None:
    de_item = personio.parse_personio_position(
        _position(
            """
            <position>
              <id>902</id><office>Wien</office><name>Project Engineer</name>
              <jobDescriptions>
                <jobDescription><name>Aufgabe</name><value>Technische Projektarbeit.</value></jobDescription>
              </jobDescriptions>
            </position>
            """
        ),
        site=SITE,
        austrian_localities=AUSTRIAN_LOCALITIES,
        language="de",
    )
    en_item = personio.parse_personio_position(
        _position(
            """
            <position>
              <id>902</id><office>Vienna</office><name>Project Engineer</name>
              <jobDescriptions>
                <jobDescription>
                  <name>Role</name><value>Supplier coordination and commissioning of machinery.</value>
                </jobDescription>
              </jobDescriptions>
            </position>
            """
        ),
        site=SITE,
        austrian_localities=AUSTRIAN_LOCALITIES,
        language="en",
    )

    assert de_item is not None
    assert en_item is not None
    merged = personio.merge_personio_language_items({"de": [de_item], "en": [en_item]})[0]

    assert merged.description == de_item.description
    assert merged.url.endswith("?language=de")
    assert merged.raw_payload["personio_description_languages"] == ["de", "en"]
    assert merged.raw_payload["wohnwerk_discovery_extra_text"] == [en_item.description]
    decision = classify_job_candidate(merged)
    assert decision.accepted is True
    assert "supplier_coordination" in decision.method_tool_matches
    assert "commissioning" in decision.method_tool_matches
