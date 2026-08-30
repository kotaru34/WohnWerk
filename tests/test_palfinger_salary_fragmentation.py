from decimal import Decimal

from app.jobs.salary import enrich_raw_job_salary
from app.sources.job.palfinger import parse_palfinger_detail_page


def test_palfinger_salary_sentence_can_span_several_inline_nodes() -> None:
    html = """
    <html><body>
      <h1>Team Lead Application Management PLM&amp;E (f/m/d)</h1>
      <h2>Your Responsibilities</h2>
      <p>Lead global PLM implementations and a team of technical experts.</p>
      <h2>Your Qualifications</h2>
      <p>Experience in technical projects and PLM systems.</p>
      <h2>What We Offer</h2>
      <div>Minimum yearly gross salary</div>
      <span>according to Austrian metal industry collective agreement</span>
      <span>is</span>
      <strong>EUR</strong>
      <span>60 962,30</span>
      <span>based on full-time employment.</span>
      <div>Quick Application</div>
      <div>PALFINGER AG Lamprechtshausener Bundesstr. 8 , 5101 Bergheim</div>
      <div>AT</div>
    </body></html>
    """

    job = parse_palfinger_detail_page(
        html,
        posting_id="7226",
        url=(
            "https://www.palfinger.com/worldwide/en/career/jobs/"
            "team-lead-application-management-plm-e---f-m-d-_7226.html"
        ),
    )

    assert enrich_raw_job_salary(job) is True
    assert job.salary_min == Decimal("60962.30")
    assert job.salary_max is None
    assert job.salary_currency == "EUR"
    assert job.salary_period == "year"
    assert job.salary_is_minimum_only is True
