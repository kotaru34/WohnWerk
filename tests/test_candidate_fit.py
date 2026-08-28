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
    assert result.score > 60
    assert result.preference_coverage == 1.0
    assert result.hard_constraints == ()


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
    assert [(item.kind, item.slug) for item in result.hard_constraints] == [
        (ConceptKind.DOMAIN, "electrical-engineering")
    ]


def test_primary_hard_incompatibility_caps_transferable_positive_fit() -> None:
    evidence = [
        FitEvidence(
            kind=ConceptKind.DOMAIN,
            slug="electronics",
            scope="primary",
            confidence=1.0,
        ),
        FitEvidence(
            kind=ConceptKind.ROLE,
            slug="development-engineer",
            scope="primary",
            confidence=1.0,
        ),
        FitEvidence(
            kind=ConceptKind.TASK,
            slug="product-development",
            scope="primary",
            confidence=1.0,
        ),
    ]
    preferences = {
        (ConceptKind.DOMAIN, "electronics"): CandidatePreferenceState.CANNOT_NOT_WANT,
        (ConceptKind.ROLE, "development-engineer"): CandidatePreferenceState.CAN_WANT,
        (ConceptKind.TASK, "product-development"): CandidatePreferenceState.CAN_WANT,
    }

    result = score_job_concepts(evidence, preferences)

    assert result.score == 25
    assert result.signed_score == -0.5
    assert [(item.kind, item.slug) for item in result.hard_constraints] == [
        (ConceptKind.DOMAIN, "electronics")
    ]
    assert any(item.contribution > 0.0 for item in result.contributions)


def test_context_only_negative_domain_is_attenuated() -> None:
    result = score_job_concepts(
        [
            FitEvidence(
                kind=ConceptKind.DOMAIN,
                slug="electrical-engineering",
                scope="context",
                confidence=0.55,
            )
        ],
        {
            (
                ConceptKind.DOMAIN,
                "electrical-engineering",
            ): CandidatePreferenceState.CANNOT_NOT_WANT
        },
    )

    assert result.score == 32
    assert result.signed_score == -0.35
    assert result.hard_constraints == ()


def test_single_positive_concept_cannot_saturate_score() -> None:
    role_only = score_job_concepts(
        [
            FitEvidence(
                kind=ConceptKind.ROLE,
                slug="development-engineer",
                scope="primary",
                confidence=1.0,
            )
        ],
        {
            (ConceptKind.ROLE, "development-engineer"): CandidatePreferenceState.CAN_WANT
        },
    )
    domain_only = score_job_concepts(
        [
            FitEvidence(
                kind=ConceptKind.DOMAIN,
                slug="mechanical-engineering",
                scope="primary",
                confidence=1.0,
            )
        ],
        {
            (ConceptKind.DOMAIN, "mechanical-engineering"): CandidatePreferenceState.CAN_WANT
        },
    )

    assert role_only.score == 69
    assert domain_only.score == 71


def test_corroborating_role_domain_and_task_can_reach_full_positive_fit() -> None:
    evidence = [
        FitEvidence(
            kind=ConceptKind.ROLE,
            slug="mechanical-designer",
            scope="primary",
            confidence=1.0,
        ),
        FitEvidence(
            kind=ConceptKind.DOMAIN,
            slug="mechanical-engineering",
            scope="primary",
            confidence=1.0,
        ),
        FitEvidence(
            kind=ConceptKind.TASK,
            slug="mechanical-design",
            scope="primary",
            confidence=1.0,
        ),
    ]
    preferences = {
        (ConceptKind.ROLE, "mechanical-designer"): CandidatePreferenceState.CAN_WANT,
        (ConceptKind.DOMAIN, "mechanical-engineering"): CandidatePreferenceState.CAN_WANT,
        (ConceptKind.TASK, "mechanical-design"): CandidatePreferenceState.CAN_WANT,
    }

    result = score_job_concepts(evidence, preferences)

    assert result.score == 100
    assert result.hard_constraints == ()


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

    assert result.score == 71
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

    assert result.score == 69
    assert len(result.contributions) == 1
    assert result.contributions[0].scope == "primary"
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
    assert cannot_want.score == 53


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
    assert result.hard_constraints == ()
