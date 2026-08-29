from decimal import Decimal

from app.sources.job.detail_salary import parse_salary_detail_html


def test_stepstone_rehrl_annual_minimum_salary() -> None:
    parsed = parse_salary_detail_html(
        """
        <html><body>
          <p>Jahresbruttogehalt ab € 75.000.- abhängig von beruflicher Qualifikation
          und Erfahrung.</p>
        </body></html>
        """
    )

    assert parsed is not None
    assert parsed.minimum == Decimal(75000)
    assert parsed.period == "year"
    assert parsed.minimum_only is True


def test_stepstone_flach_monthly_overpayment_is_minimum() -> None:
    parsed = parse_salary_detail_html(
        """
        <html><body>
          <p>Geboten wird ein monatliches Bruttogehalt von € 4.000,-- mit der
          ausdrücklichen Bereitschaft zur Überzahlung je nach Qualifikation.</p>
        </body></html>
        """
    )

    assert parsed is not None
    assert parsed.minimum == Decimal(4000)
    assert parsed.period == "month"
    assert parsed.minimum_only is True


def test_stepstone_vahle_annual_overpayment_is_minimum() -> None:
    parsed = parse_salary_detail_html(
        """
        <html><body>
          <div>Vergütung bei 50.000 EUR Jahresbrutto mit Bereitschaft zur Überzahlung</div>
        </body></html>
        """
    )

    assert parsed is not None
    assert parsed.minimum == Decimal(50000)
    assert parsed.period == "year"
    assert parsed.minimum_only is True


def test_willhaben_full_context_keeps_overpayment_clause() -> None:
    parsed = parse_salary_detail_html(
        """
        <html><body>
          <div>Bruttogehalt:</div>
          <div>€ 5.000 monatlich, mit Bereitschaft zur Überzahlung</div>
        </body></html>
        """
    )

    assert parsed is not None
    assert parsed.minimum == Decimal(5000)
    assert parsed.period == "month"
    assert parsed.minimum_only is True
