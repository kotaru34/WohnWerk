from decimal import Decimal

from app.jobs.fit_store import annual_salary_label
from app.jobs.salary import enrich_raw_job_salary, parse_salary_text
from app.models import Job
from app.sources.base import RawJob


def test_extracts_austrian_monthly_minimum_with_explicit_14_payments() -> None:
    parsed = parse_salary_text(
        "Das kollektivvertragliche Mindestgehalt beträgt EUR 4.673,74 brutto pro Monat "
        "bei 14 Gehältern. Eine Überzahlung ist je nach Erfahrung möglich."
    )

    assert parsed is not None
    assert parsed.minimum == Decimal("4673.74")
    assert parsed.maximum is None
    assert parsed.period == "month"
    assert parsed.payment_count == 14
    assert parsed.minimum_only is True


def test_extracts_annual_salary_range() -> None:
    parsed = parse_salary_text(
        "Wir bieten ein Jahresbruttogehalt von € 65.000 bis € 80.000 abhängig von Erfahrung."
    )

    assert parsed is not None
    assert parsed.minimum == Decimal(65000)
    assert parsed.maximum == Decimal(80000)
    assert parsed.period == "year"
    assert parsed.minimum_only is False


def test_extracts_monthly_salary_with_amount_first_wording() -> None:
    parsed = parse_salary_text(
        "Für diese Position sind ab 4.500 € brutto monatlich vorgesehen; Überzahlung möglich."
    )

    assert parsed is not None
    assert parsed.minimum == Decimal(4500)
    assert parsed.period == "month"
    assert parsed.minimum_only is True


def test_trusted_source_salary_text_does_not_need_generic_salary_word() -> None:
    parsed = parse_salary_text("ab 4.500 € pro Monat", trusted=True)

    assert parsed is not None
    assert parsed.minimum == Decimal(4500)
    assert parsed.period == "month"
    assert parsed.minimum_only is True


def test_willhaben_salary_marks_overpayment_amount_as_minimum() -> None:
    parsed = parse_salary_text(
        "Bruttogehalt:€ 5.000 monatlich, mit Bereitschaft zur Überzahlung",
        trusted=True,
    )

    assert parsed is not None
    assert parsed.minimum == Decimal(5000)
    assert parsed.period == "month"
    assert parsed.minimum_only is True


def test_work_schedule_does_not_become_weekly_salary_period() -> None:
    assert parse_salary_text(
        "Geboten wird ein marktübliches Bruttogehalt (40 Std./Woche, KV IT & Consulting) "
        "abhängig von individueller Qualifikation und beruflicher Erfahrung ab 3500 EUR."
    ) is None


def test_ignores_non_salary_euro_amounts_even_with_a_period() -> None:
    assert parse_salary_text(
        "Für Weiterbildungen steht ein Budget von 5.000 € pro Jahr zur Verfügung."
    ) is None


def test_raw_job_text_enrichment_does_not_override_structured_salary() -> None:
    item = RawJob(
        source_listing_id="1",
        url="https://example.test/job/1",
        title="Projektleiter",
        description="Mindestgehalt € 4.500 brutto pro Monat.",
        salary_min=Decimal(70000),
        salary_currency="EUR",
        salary_period="year",
        salary_provenance="EXPLICIT",
    )

    assert enrich_raw_job_salary(item) is False
    assert item.salary_min == Decimal(70000)
    assert item.salary_period == "year"


def test_salary_label_preserves_source_monthly_semantics() -> None:
    job = Job(
        title="Projektleiter",
        salary_min=Decimal("4673.74"),
        salary_currency="EUR",
        salary_period="month",
        salary_payment_count=14,
        salary_is_minimum_only=True,
    )

    assert annual_salary_label(job) == "ab 4.673,74 € / Monat · 14×"


def test_salary_label_formats_annual_range() -> None:
    job = Job(
        title="Projektleiter",
        salary_min=Decimal(65000),
        salary_max=Decimal(80000),
        salary_currency="EUR",
        salary_period="year",
    )

    assert annual_salary_label(job) == "65.000 € – 80.000 € / Jahr"
