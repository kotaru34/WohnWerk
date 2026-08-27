import xml.etree.ElementTree as ET

from app.sources.job.personio import PersonioSite, parse_personio_feed, parse_personio_position


SITE = PersonioSite(tenant="example-at", company="Example Engineering GmbH")
AUSTRIAN_LOCALITIES = {"graz", "wien", "linz", "hohenberg", "anif"}


def _position(xml: str) -> ET.Element:
    return ET.fromstring(xml)


def test_personio_city_only_austrian_office_is_kept() -> None:
    item = parse_personio_position(
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
    assert "Mechanische Konstruktion" in (item.description or "")
    assert item.raw_payload["personio_department"] == "Mechanics"


def test_personio_explicit_austria_office_is_kept() -> None:
    item = parse_personio_position(
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


def test_personio_non_austrian_office_is_rejected() -> None:
    item = parse_personio_position(
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

    items, total = parse_personio_feed(
        payload,
        site=SITE,
        austrian_localities=AUSTRIAN_LOCALITIES,
    )

    assert total == 2
    assert [item.source_listing_id for item in items] == ["example-at:1"]
    assert items[0].locations[0].city == "wien"
