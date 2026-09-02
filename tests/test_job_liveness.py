from datetime import UTC, datetime

from app.jobs.liveness import (
    assess_http_page,
    closed_page_markers,
    parse_iso_datetime,
    released_age_days,
)


def test_closed_page_markers_cover_english_and_german_closure_text() -> None:
    assert "no_longer_accepting_applications" in closed_page_markers(
        "This job is no longer accepting applications."
    )
    assert "applications_closed" in closed_page_markers("Applications are closed")
    assert "stelle_nicht_mehr_verfuegbar" in closed_page_markers(
        "Diese Stelle ist nicht mehr verfügbar."
    )
    assert "bewerbungsfrist_abgelaufen" in closed_page_markers(
        "Die Bewerbungsfrist ist leider abgelaufen."
    )


def test_live_page_without_closure_marker_is_live() -> None:
    assessment = assess_http_page(200, "Jetzt bewerben – offene Stelle")
    assert assessment.state == "live"
    assert assessment.reasons == ()


def test_404_and_410_are_dead_but_access_controls_are_unknown() -> None:
    assert assess_http_page(404, "").state == "dead"
    assert assess_http_page(410, "").state == "dead"
    assert assess_http_page(403, "Forbidden").state == "unknown"
    assert assess_http_page(429, "Too many requests").state == "unknown"


def test_closed_marker_wins_even_on_http_200() -> None:
    assessment = assess_http_page(
        200,
        "Thank you for your interest. This position is no longer available.",
    )
    assert assessment.state == "dead"
    assert "no_longer_available" in assessment.reasons


def test_iso_release_date_parsing_and_age() -> None:
    released = parse_iso_datetime("2026-08-01T12:00:00Z")
    assert released == datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    assert released_age_days(
        "2026-08-01T12:00:00Z",
        now=datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
    ) == 26


def test_invalid_release_date_is_unknown() -> None:
    assert parse_iso_datetime("not-a-date") is None
    assert released_age_days(None) is None
