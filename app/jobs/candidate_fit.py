from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.jobs.concepts import ConceptKind, JobConcept


class CandidatePreferenceState(StrEnum):
    CAN_WANT = "can_want"
    CAN_NOT_WANT = "can_not_want"
    CANNOT_WANT = "cannot_want"
    CANNOT_NOT_WANT = "cannot_not_want"


class CandidateProfile(Base):
    """Candidate-specific preference profile kept separate from job normalization."""

    __tablename__ = "candidate_profiles"
    __table_args__ = (Index("ix_candidate_profiles_enabled", "enabled"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    label_de: Mapped[str] = mapped_column(String(240), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    preferences: Mapped[list[CandidateConceptPreference]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class CandidateConceptPreference(Base):
    """One four-state can/want rating for a canonical concept."""

    __tablename__ = "candidate_concept_preferences"
    __table_args__ = (
        UniqueConstraint(
            "profile_id", "concept_id", name="uq_candidate_preference_profile_concept"
        ),
        CheckConstraint(
            "state IN ('can_want', 'can_not_want', 'cannot_want', 'cannot_not_want')",
            name="ck_candidate_preference_state",
        ),
        Index("ix_candidate_preferences_profile_state", "profile_id", "state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    concept_id: Mapped[int] = mapped_column(
        ForeignKey("job_concepts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    profile: Mapped[CandidateProfile] = relationship(back_populates="preferences")
    concept: Mapped[JobConcept] = relationship()


@dataclass(frozen=True, slots=True)
class FitPolicy:
    version: str
    state_values: dict[CandidatePreferenceState, float]
    scope_weights: dict[str, float]
    kind_weights: dict[ConceptKind, float]
    positive_evidence_budget: float
    hard_primary_incompatibility_cap: int
    hard_incompatibility_kinds: frozenset[ConceptKind]


DEFAULT_FIT_POLICY = FitPolicy(
    version="candidate-fit-2026-08-28-v3",
    # Desire is intentionally slightly stronger than current capability: an aspirational
    # concept is mildly positive, while a known-but-unwanted concept is mildly negative.
    state_values={
        CandidatePreferenceState.CAN_WANT: 1.0,
        CandidatePreferenceState.CAN_NOT_WANT: -0.20,
        CandidatePreferenceState.CANNOT_WANT: 0.20,
        CandidatePreferenceState.CANNOT_NOT_WANT: -1.0,
    },
    # Context evidence is useful but must not redefine the vacancy identity.
    scope_weights={"primary": 1.0, "context": 0.35},
    kind_weights={
        ConceptKind.ROLE: 1.15,
        ConceptKind.DOMAIN: 1.25,
        ConceptKind.TASK: 1.0,
        ConceptKind.METHOD: 0.75,
        ConceptKind.TOOL: 0.75,
    },
    # Positive fit claims need corroboration. A single generic role/domain should not
    # saturate to 100; roughly role + domain + task is enough for full positive confidence.
    positive_evidence_budget=3.0,
    # A primary role/domain that the candidate both cannot and does not want is a hard
    # incompatibility. Transferable positive skills remain visible in contributions, but
    # they must not turn the vacancy into a recommendation candidate.
    hard_primary_incompatibility_cap=25,
    hard_incompatibility_kinds=frozenset({ConceptKind.ROLE, ConceptKind.DOMAIN}),
)


@dataclass(frozen=True, slots=True)
class FitEvidence:
    kind: ConceptKind
    slug: str
    scope: str
    confidence: float


@dataclass(frozen=True, slots=True)
class FitContribution:
    kind: ConceptKind
    slug: str
    state: CandidatePreferenceState
    scope: str
    evidence_weight: float
    contribution: float


@dataclass(frozen=True, slots=True)
class FitHardConstraint:
    kind: ConceptKind
    slug: str
    state: CandidatePreferenceState


@dataclass(frozen=True, slots=True)
class JobFitResult:
    score: int | None
    signed_score: float | None
    rated_weight: float
    total_weight: float
    preference_coverage: float
    contributions: tuple[FitContribution, ...]
    hard_constraints: tuple[FitHardConstraint, ...]


def score_job_concepts(
    evidence: list[FitEvidence],
    preferences: dict[tuple[ConceptKind, str], CandidatePreferenceState],
    *,
    policy: FitPolicy = DEFAULT_FIT_POLICY,
) -> JobFitResult:
    """Score normalized job evidence against one candidate profile.

    Repeated title/description evidence for the same concept is collapsed to its strongest
    signal. Scope attenuates contribution amplitude, while normalization uses the unscoped
    evidence strength so context cannot become an extreme identity signal by itself.

    Positive scores additionally use a minimum evidence budget: one attractive generic
    concept can move a job above neutral but cannot prove an exceptional fit alone. Primary
    role/domain evidence rated cannot+not-want is exposed as a hard incompatibility and caps
    the score even when transferable positive evidence exists. Context mentions never create
    a hard incompatibility. Unrated concepts do not bias score but reduce preference coverage.
    """

    strongest: dict[tuple[ConceptKind, str], tuple[float, float, str]] = {}
    for item in evidence:
        scope_weight = policy.scope_weights.get(item.scope)
        if scope_weight is None:
            continue
        kind_weight = policy.kind_weights[item.kind]
        confidence = max(0.0, min(1.0, item.confidence))
        normalization_weight = kind_weight * confidence
        effective_weight = normalization_weight * scope_weight
        key = (item.kind, item.slug)
        current = strongest.get(key)
        if current is None or effective_weight > current[1]:
            strongest[key] = (normalization_weight, effective_weight, item.scope)

    total_weight = sum(normalization for normalization, _effective, _scope in strongest.values())
    rated_weight = 0.0
    signed_total = 0.0
    contributions: list[FitContribution] = []
    hard_constraints: list[FitHardConstraint] = []

    for key, (normalization_weight, effective_weight, scope) in strongest.items():
        state = preferences.get(key)
        if state is None:
            continue
        rated_weight += normalization_weight
        contribution = effective_weight * policy.state_values[state]
        signed_total += contribution
        contributions.append(
            FitContribution(
                kind=key[0],
                slug=key[1],
                state=state,
                scope=scope,
                evidence_weight=effective_weight,
                contribution=contribution,
            )
        )
        if (
            scope == "primary"
            and key[0] in policy.hard_incompatibility_kinds
            and state == CandidatePreferenceState.CANNOT_NOT_WANT
        ):
            hard_constraints.append(
                FitHardConstraint(kind=key[0], slug=key[1], state=state)
            )

    coverage = rated_weight / total_weight if total_weight else 0.0
    if rated_weight == 0.0:
        return JobFitResult(
            score=None,
            signed_score=None,
            rated_weight=0.0,
            total_weight=total_weight,
            preference_coverage=coverage,
            contributions=(),
            hard_constraints=(),
        )

    normalization_denominator = rated_weight
    if signed_total > 0.0:
        normalization_denominator = max(rated_weight, policy.positive_evidence_budget)

    signed_score = max(-1.0, min(1.0, signed_total / normalization_denominator))
    if hard_constraints:
        cap_signed_score = (policy.hard_primary_incompatibility_cap - 50.0) / 50.0
        signed_score = min(signed_score, cap_signed_score)

    score = round(50.0 + 50.0 * signed_score)
    contributions.sort(key=lambda item: abs(item.contribution), reverse=True)
    hard_constraints.sort(key=lambda item: (item.kind.value, item.slug))
    return JobFitResult(
        score=score,
        signed_score=signed_score,
        rated_weight=rated_weight,
        total_weight=total_weight,
        preference_coverage=coverage,
        contributions=tuple(contributions),
        hard_constraints=tuple(hard_constraints),
    )
