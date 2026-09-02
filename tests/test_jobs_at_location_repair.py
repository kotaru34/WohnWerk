from app.jobs.jobs_at_location_repair import parse_jobs_at_visible_location


def test_visible_jobs_at_header_recovers_klagenfurt_from_region_only_page() -> None:
    content = """
    <html><body>
      <h1>SENIOR KONSTRUKTEUR MIT OPTION TEAMLEITUNG (m/w/d)</h1>
      <div>ISG Personalmanagement GmbH</div>
      <div>Klagenfurt - Heute</div>
      <div>Vollzeit ab 5.000€ pro Monat</div>
    </body></html>
    """

    location = parse_jobs_at_visible_location(content)

    assert location is not None
    assert location.city == "Klagenfurt"
    assert location.postal_code is None
    assert location.location_text == "Klagenfurt"


def test_visible_jobs_at_header_ignores_non_header_text() -> None:
    content = """
    <html><body>
      <p>Unser Büro liegt in Klagenfurt - moderne Arbeitsplätze inklusive.</p>
    </body></html>
    """

    assert parse_jobs_at_visible_location(content) is None
