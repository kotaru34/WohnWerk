from decimal import Decimal

import pytest
from sqlalchemy.dialects import postgresql

from app.jobs.candidate_fit import (
    CandidatePreferenceState,
    FitHardConstraint,
    JobFitResult,
)
from app.jobs.concepts import ConceptKind
from app.jobs.fit_store import JobFitView
from app.matching import (
    PropertyDistanceMatch,
    load_spatial_candidate_matches,
    nearest_properties_for_job_stmt,
)
from app.models import Job


def _fit_view(
    job_id: int,
    score: int | None,
    *,
    coverage: float = 1.0,
    hidden: bool = False,
    hard: bool = False,
    favorite: bool = False,
) -> JobFitView:
    constraints = (
        FitHardConstraint(
            kind=ConceptKind.DOMAIN,
            slug="electronics",
            state=CandidatePreferenceState.CANNOT_NOT_WANT,
        ),
    ) if hard else ()
    result = JobFitResult(
        score=score,
        signed_score=None if score is None else (score - 50) / 50,
        rated_weight=0.0 if score is None else 2.0,
        total_weight=2.0,
        preference_coverage=coverage,
        contributions=(),
        hard_constraints=constraints,
    )
    return JobFitView(
        job=Job(id=job_id, title=f"Job {job_id}", company="Beispiel GmbH"),
        result=result,
        locations=("Graz",),
        links=(),
        drivers=(),
        hard_labels=("Elektronik / Hardware",) if hard else (),
        favorite=favorite,
        hidden=hidden,
    )


def test_nearest_properties_query_is_spatial_index_first_and_not_stale_fit() -> None:
    stmt = nearest_properties_for_job_stmt(144, 50, limit=7)
    sql = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "ST_DWithin" in sql
    assert "ST_Distance" in sql
    assert "row_number() OVER" in sql
    assert "job_locations.job_id = 144" in sql
    assert "nearest_location_rank = 1" in sql
    assert "LIMIT 7" in sql
    assert "job_fit_score" not in sql


def test_nearest_properties_query_validates_inputs() -> None:
    with pytest.raises(ValueError):
        nearest_properties_for_job_stmt(0, 50)
    with pytest.raises(ValueError):
        nearest_properties_for_job_stmt(1, 0)
    with pytest.raises(ValueError):
        nearest_properties_for_job_stmt(1, 50, limit=0)


def test_spatial_candidate_matching_keeps_fit_and_geography_separate(monkeypatch) -> None:
    views = [
        _fit_view(1, 90, favorite=False),
        _fit_view(2, 95, favorite=False),
        _fit_view(3, 80, hidden=True),
        _fit_view(4, 100, hard=True),
        _fit_view(5, None),
        _fit_view(6, 70, favorite=True),
    ]
    calls: list[int] = []

    def fake_nearest(_session, job_id: int, _radius_km: float, *, limit: int):
        calls.append(job_id)
        return [
            PropertyDistanceMatch(
                property_id=job_id * 10,
                title="Haus",
                postal_code="8010",
                city="Graz",
                price_eur=Decimal(300000),
                living_area_m2=Decimal(120),
                plot_area_m2=Decimal(600),
                job_location_id=job_id * 100,
                job_postal_code="8010",
                job_city="Graz",
                job_location_text="Graz",
                distance_km=12.5,
            )
        ]

    monkeypatch.setattr("app.matching.load_live_job_fit", lambda *_args, **_kwargs: views)
    monkeypatch.setattr("app.matching.nearest_properties_for_job", fake_nearest)

    groups = load_spatial_candidate_matches(
        object(),
        radius_km=40,
        job_limit=3,
        properties_per_job=2,
    )

    # Favorite is curation, not an intrinsic-score boost. Hidden, hard and unscored jobs
    # are excluded before geography is evaluated.
    assert [group.fit.job.id for group in groups] == [2, 1, 6]
    assert calls == [2, 1, 6]
    assert groups[0].properties[0].distance_km == 12.5


def test_spatial_candidate_matching_validates_limits() -> None:
    with pytest.raises(ValueError):
        load_spatial_candidate_matches(object(), job_limit=0)
    with pytest.raises(ValueError):
        load_spatial_candidate_matches(object(), properties_per_job=0)
