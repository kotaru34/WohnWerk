from decimal import Decimal

from app.jobs.salary import enrich_raw_job_salary
from app.sources.job.tgw import parse_tgw_detail_page, parse_tgw_listing_page


def test_tgw_listing_parser_finds_and_deduplicates_public_job_links() -> None:
    html = """
    <html><body>
      <a href="/en/career/jobs/detail/project-manager-mechatronic-product-development-830/">
        Project Manager
      </a>
      <a href="https://www.tgw-group.com/en/career/jobs/detail/project-manager-mechatronic-product-development-830/">
        Duplicate
      </a>
      <a href="/en/career/jobs/detail/technical-support-engineer-mechanics-901/">
        Technical Support Engineer Mechanics
      </a>
      <a href="/en/career/jobs/">Back</a>
    </body></html>
    """

    assert parse_tgw_listing_page(html) == [
        (
            "830",
            (
                "https://www.tgw-group.com/en/career/jobs/detail/"
                "project-manager-mechatronic-product-development-830/"
            ),
        ),
        (
            "901",
            (
                "https://www.tgw-group.com/en/career/jobs/detail/"
                "technical-support-engineer-mechanics-901/"
            ),
        ),
    ]


def test_tgw_detail_parser_extracts_source_backed_austrian_job() -> None:
    html = """
    <html><body>
      <nav>Company Career Jobs</nav>
      <h2>Join Team Possible!</h2>
      <h2>Strategic (Senior) Project Manager – Mechatronics Product Development (M/F/D)*</h2>
      <div>Project Management</div>
      <div>Experienced Professionals</div>
      <div>Wels, Austria</div>
      <h3>What you'll be handling:</h3>
      <ul>
        <li>Management of strategic technological projects.</li>
        <li>Interface management with international stakeholders.</li>
      </ul>
      <h3>What you'll need:</h3>
      <ul>
        <li>Technical education in mechatronics or mechanical engineering.</li>
        <li>Experience in product development and project management.</li>
      </ul>
      <h3>What you'll receive:</h3>
      <p>Benefits and training.</p>
      <p>Ready to start? We're looking forward to meeting you.</p>
      <p>We offer an attractive salary in line with the market, which can be above the
      collective agreement depending on qualifications and experience. The minimum gross
      basic salary based on full-time employment per year is 64.830 Euro.</p>
    </body></html>
    """

    job = parse_tgw_detail_page(
        html,
        posting_id="932",
        url=(
            "https://www.tgw-group.com/en/career/jobs/detail/"
            "strategic-senior-project-manager-mechatronics-product-development-932/"
        ),
    )

    assert job is not None
    assert job.source_listing_id == "tgw:932"
    assert job.title == (
        "Strategic (Senior) Project Manager – Mechatronics Product Development (M/F/D)"
    )
    assert job.company == "TGW Logistics"
    assert len(job.locations) == 1
    assert job.locations[0].city == "Wels"
    assert job.locations[0].location_text == "Wels, Austria"
    assert job.description is not None
    assert "Management of strategic technological projects." in job.description
    assert "mechanical engineering" in job.description
    assert "Benefits and training" not in job.description
    assert "64.830 Euro" not in job.description
    assert job.salary_text is not None
    assert "minimum gross basic salary" in job.salary_text
    assert "64.830 Euro" in job.salary_text
    assert enrich_raw_job_salary(job) is True
    assert job.salary_min == Decimal(64830)
    assert job.salary_max is None
    assert job.salary_currency == "EUR"
    assert job.salary_period == "year"
    assert job.salary_payment_count is None
    assert job.salary_is_minimum_only is True
    assert job.raw_payload["tgw_posting_id"] == "932"
    assert job.raw_payload["wohnwerk_stable_identity"] == "direct:tgw:932"


def test_tgw_detail_parser_ignores_non_austrian_job() -> None:
    html = """
    <html><body>
      <h2>Join Team Possible!</h2>
      <h2>Project Engineer II*</h2>
      <div>Engineering</div>
      <div>Experienced Professionals</div>
      <div>Grand Rapids, United States</div>
      <h3>What you'll be handling:</h3>
      <p>Mechanical project engineering.</p>
      <h3>What you'll need:</h3>
      <p>Mechanical engineering degree.</p>
      <h3>What you'll receive:</h3>
      <p>Benefits.</p>
    </body></html>
    """

    assert (
        parse_tgw_detail_page(
            html,
            posting_id="555",
            url="https://www.tgw-group.com/en/career/jobs/detail/project-engineer-ii-555/",
        )
        is None
    )
