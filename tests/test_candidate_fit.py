from app.jobs.candidate_fit import (
    CandidatePreferenceState,
    FitEvidence,
    score_job_concepts,
)
from app.jobs.concepts import ConceptKind


def test_primary_evidence_dominates_conflicting_context() -> None:
    evidence = [
        FitEvidence(
            kind=ConceptKind.DOMAIN,
            slug="mechanical-engineering",
            scope="primary",
            confidence=1.0,
        ),
        FitEvidence(
            kind=ConceptKind.DOMAIN,
            slug="electrical-engineering",
            scope="context",
            confidence=0.55,
        ),
    ]
    preferences = {
        (ConceptKind.DOMAIN, "mechanical-engineering"): CandidatePreferenceState.CAN_WANT,
        (
            ConceptKind.DOMAIN,
            "electrical-engineering",
        ): CandidatePreferenceState.CANNOT_NOT_WANT,
    }

    result = score_job_concepts(evidence, preferences)

    assert result.score is not None
    assert result.score > 80
    assert result.preference_coverage == 1.0


def test_pure_primary_negative_domain_scores_low() -> None:
    result = score_job_concepts(
        [
            FitEvidence(
                kind=ConceptKind.DOMAIN,
                slug="electrical-engineering",
                scope="primary",
                confidence=1.0,
            )
        ],
        {
            (
                ConceptKind.DOMAIN,
                "electrical-engineering",
            ): CandidatePreferenceState.CANNOT_NOT_WANT
        },
    )

    assert result.score == 0
    assert result.signed_score == -1.0


def test_unrated_concepts_reduce_coverage_without_biasing_score() -> None:
    evidence = [
        FitEvidence(
            kind=ConceptKind.DOMAIN,
            slug="mechanical-engineering",
            scope="primary",
            confidence=1.0,
        ),
        FitEvidence(
            kind=ConceptKind.TOOL,
            slug="creo",
            scope="context",
            confidence=0.85,
        ),
    ]
    result = score_job_concepts(
        evidence,
        {
            (ConceptKind.DOMAIN, "mechanical-engineering"): CandidatePreferenceState.CAN_WANT
        },
    )

    assert result.score == 100
    assert 0.0 < result.preference_coverage < 1.0


def test_duplicate_evidence_for_one_concept_uses_strongest_signal_only() -> None:
    evidence = [
        FitEvidence(
            kind=ConceptKind.ROLE,
            slug="mechanical-engineer",
            scope="primary",
            confidence=1.0,
        ),
        FitEvidence(
            kind=ConceptKind.ROLE,
            slug="mechanical-engineer",
            scope="context",
            confidence=0.45,
        ),
    ]
    result = score_job_concepts(
        evidence,
        {
            (ConceptKind.ROLE, "mechanical-engineer"): CandidatePreferenceState.CAN_WANT
        },
    )

    assert result.score == 100
    assert len(result.contributions) == 1
    assert result.rated_weight == 1.15


def test_middle_states_remain_directionally_distinct() -> None:
    evidence = [
        FitEvidence(
            kind=ConceptKind.TASK,
            slug="example",
            scope="primary",
            confidence=1.0,
        )
    ]

    can_not_want = score_job_concepts(
        evidence,
        {(ConceptKind.TASK, "example"): CandidatePreferenceState.CAN_NOT_WANT},
    )
    cannot_want = score_job_concepts(
        evidence,
        {(ConceptKind.TASK, "example"): CandidatePreferenceState.CANNOT_WANT},
    )

    assert can_not_want.score == 40
    assert cannot_want.score == 60


def test_no_rated_evidence_returns_no_score() -> None:
    result = score_job_concepts(
        [
            FitEvidence(
                kind=ConceptKind.TOOL,
                slug="solidworks",
                scope="context",
                confidence=0.85,
            )
        ],
        {},
    )

    assert result.score is None
    assert result.preference_coverage == 0.0
