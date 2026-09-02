from decimal import Decimal

import pytest

from app.jobs.salary import enrich_raw_job_salary
from app.sources.job.palfinger import (
    parse_palfinger_detail_page,
    parse_palfinger_listing_page,
)


def test_palfinger_listing_parser_finds_jobs_and_pagination() -> None:
    html = """
    <html><body>
      <a href="/worldwide/en/career/jobs/experienced-mechanical-engineer--f-m-d-_9001.html">
        Experienced Mechanical Engineer
      </a>
      <a href="https://www.palfinger.com/worldwide/en/career/jobs/experienced-mechanical-engineer--f-m-d-_9001.html">
        Duplicate
      </a>
      <a href="/worldwide/en/career/jobs/projekt-manager-special-lifting-solutions_8829.html">
        Projekt Manager
      </a>
      <a href="/worldwide/en/career/jobs.html?area=&amp;city=&amp;country=austria&amp;page=2">2</a>
      <a href="/worldwide/en/career/jobs.html?area=&amp;city=&amp;country=austria&amp;page=5">5</a>
    </body></html>
    """

    postings, max_page = parse_palfinger_listing_page(html)

    assert postings == [
        (
            "9001",
            (
                "https://www.palfinger.com/worldwide/en/career/jobs/"
                "experienced-mechanical-engineer--f-m-d-_9001.html"
            ),
        ),
        (
            "8829",
            (
                "https://www.palfinger.com/worldwide/en/career/jobs/"
                "projekt-manager-special-lifting-solutions_8829.html"
            ),
        ),
    ]
    assert max_page == 5


def test_palfinger_detail_parser_extracts_mechanical_job_salary_and_location() -> None:
    html = """
    <html><body>
      <nav>Career Jobs</nav>
      <h2>About Us Close</h2>
      <h1>Experienced Mechanical Engineer (f/m/d)</h1>
      <div>Köstendorf | Posted on 27.08.2026</div>
      <p>Zur Verstärkung unseres Teams suchen wir eine:n Experienced Mechanical Engineer.</p>
      <h2>WAS DICH ERWARTET</h2>
      <ul>
        <li>Entwickle und konstruiere Systemlösungen und Kransysteme.</li>
        <li>Übernimm die Leitung anspruchsvoller Entwicklungsprojekte in der mechanischen Vorentwicklung.</li>
        <li>Führe FEM-Berechnungen durch und begleite Prototypen bis zur Serienfertigung.</li>
      </ul>
      <h2>WAS DU MITBRINGST</h2>
      <ul>
        <li>Technische Ausbildung im Bereich Maschinenbau oder Stahlbau.</li>
        <li>Projektmanagement von Entwicklungsprojekten und internationale Teams.</li>
      </ul>
      <h2>WAS WIR BIETEN</h2>
      <p>Flexible Arbeitszeiten und Home-Office.</p>
      <p>Wir bieten ein attraktives und leistungsbezogenes Gehalt. KV-Minimum auf Basis
      einer Vollzeitbeschäftigung ist EUR 47.546,94 brutto pro Jahr.</p>
      <div>Quick Application</div>
      <div>Köstendorf</div>
      <div>Location</div>
      <div>Palfinger Europe GmbH Moosmühlstraße 1 , 5203 Köstendorf</div>
      <div>AT</div>
    </body></html>
    """

    job = parse_palfinger_detail_page(
        html,
        posting_id="9001",
        url=(
            "https://www.palfinger.com/worldwide/en/career/jobs/"
            "experienced-mechanical-engineer--f-m-d-_9001.html"
        ),
    )

    assert job.source_listing_id == "palfinger:9001"
    assert job.title == "Experienced Mechanical Engineer (f/m/d)"
    assert job.company == "PALFINGER"
    assert job.locations[0].postal_code == "5203"
    assert job.locations[0].city == "Köstendorf"
    assert job.locations[0].location_text == "5203 Köstendorf, AT"
    assert job.description is not None
    assert "mechanischen Vorentwicklung" in job.description
    assert "Maschinenbau" in job.description
    assert "Quick Application" not in job.description
    assert job.raw_payload["palfinger_posting_id"] == "9001"
    assert job.raw_payload["wohnwerk_stable_identity"] == "direct:palfinger:9001"

    assert enrich_raw_job_salary(job) is True
    assert job.salary_min == Decimal("47546.94")
    assert job.salary_max is None
    assert job.salary_currency == "EUR"
    assert job.salary_period == "year"
    assert job.salary_is_minimum_only is True


def test_palfinger_detail_parser_handles_source_backed_slash_locality() -> None:
    html = """
    <html><body>
      <h1>Entwicklungsingenieur Kransysteme oder Fahrzeugtechnik (w/m/d)</h1>
      <h2>Was dich erwartet:</h2>
      <p>Konzipierung und konstruktive Ausarbeitung von Kransystemen und Fahrzeugaufbauten.</p>
      <h2>Was du mitbringst:</h2>
      <p>Technische Ausbildung in Maschinenbau oder Fahrzeugtechnik.</p>
      <div>Quick Application</div>
      <div>Elsbethen</div>
      <div>Location</div>
      <div>Epsilon Kran GmbH Christophorusstraße 30 , 5061 Elsbethen/Glasenbach</div>
      <div>AT</div>
    </body></html>
    """

    job = parse_palfinger_detail_page(
        html,
        posting_id="8689",
        url=(
            "https://www.palfinger.com/worldwide/en/career/jobs/"
            "entwicklungsingenieur-kransysteme-oder-fahrzeugtechnik--w-m-d-_8689.html"
        ),
    )

    assert job.locations[0].postal_code == "5061"
    assert job.locations[0].city == "Elsbethen/Glasenbach"
    assert job.locations[0].location_text == "5061 Elsbethen/Glasenbach, AT"
    assert job.description is not None
    assert "Kransystemen" in job.description


def test_palfinger_detail_parser_handles_special_lifting_salary_spacing() -> None:
    html = """
    <html><body>
      <h1>Projekt Manager - Special Lifting Solutions (m/w/d)</h1>
      <h2>WAS SIE ERWARTET</h2>
      <p>Initiieren, Leiten und Steuern globaler Projekte im Bereich spezieller Hebelösungen.</p>
      <p>Planung, Zuweisung und Überwachung von Zeit, Budget und Ressourcen.</p>
      <h2>WAS SIE MITBRINGEN</h2>
      <p>Mindestens 3 Jahre Erfahrung im Projektmanagement mit Gesamtverantwortung.</p>
      <h2>WAS WIR BIETEN</h2>
      <p>KV-Minimum auf Basis einer Vollzeitbeschäftigung ist EUR EUR 53 241,02 brutto pro Jahr.</p>
      <div>Quick Application</div>
      <div>Palfinger Europe GmbH Moosmühlstraße 1, 5203 Köstendorf</div>
      <div>AT</div>
    </body></html>
    """

    job = parse_palfinger_detail_page(
        html,
        posting_id="8829",
        url=(
            "https://www.palfinger.com/worldwide/en/career/jobs/"
            "projekt-manager---special-lifting-solutions--m-w-d-_8829.html"
        ),
    )

    assert enrich_raw_job_salary(job) is True
    assert job.salary_min == Decimal("53241.02")
    assert job.salary_currency == "EUR"
    assert job.salary_period == "year"


def test_palfinger_detail_parser_requires_job_h1_not_navigation_heading() -> None:
    html = """
    <html><body>
      <h2>About Us Close</h2>
      <h3>Career Navigation</h3>
      <h2>WAS DICH ERWARTET</h2>
      <p>Mechanical product development.</p>
      <div>Palfinger Europe GmbH Moosmühlstraße 1, 5203 Köstendorf</div>
      <div>AT</div>
    </body></html>
    """

    with pytest.raises(ValueError, match="no job title"):
        parse_palfinger_detail_page(
            html,
            posting_id="1",
            url="https://www.palfinger.com/worldwide/en/career/jobs/test_1.html",
        )


def test_palfinger_detail_parser_requires_source_backed_austrian_location() -> None:
    html = """
    <html><body>
      <h1>Experienced Mechanical Engineer</h1>
      <h2>WAS DICH ERWARTET</h2>
      <p>Mechanical product development.</p>
      <div>Quick Application</div>
    </body></html>
    """

    with pytest.raises(ValueError, match="source-backed AT location"):
        parse_palfinger_detail_page(
            html,
            posting_id="1",
            url="https://www.palfinger.com/worldwide/en/career/jobs/test_1.html",
        )
