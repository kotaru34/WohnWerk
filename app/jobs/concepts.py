from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ConceptKind(StrEnum):
    ROLE = "role"
    DOMAIN = "domain"
    TASK = "task"
    METHOD = "method"
    TOOL = "tool"


class ConceptEvidenceScope(StrEnum):
    PRIMARY = "primary"
    CONTEXT = "context"


class JobConcept(Base):
    """Canonical vocabulary item used for job normalization and later candidate fit."""

    __tablename__ = "job_concepts"
    __table_args__ = (
        UniqueConstraint("kind", "slug", name="uq_job_concepts_kind_slug"),
        Index("ix_job_concepts_kind_enabled", "kind", "enabled"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    label_de: Mapped[str] = mapped_column(String(240), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    aliases: Mapped[list[JobConceptAlias]] = relationship(
        back_populates="concept", cascade="all, delete-orphan"
    )
    evidence: Mapped[list[JobConceptEvidence]] = relationship(
        back_populates="concept", cascade="all, delete-orphan"
    )


class JobConceptAlias(Base):
    """Surface form that maps source wording to one canonical concept."""

    __tablename__ = "job_concept_aliases"
    __table_args__ = (
        UniqueConstraint(
            "concept_id",
            "normalized_alias",
            name="uq_job_concept_aliases_concept_normalized",
        ),
        Index("ix_job_concept_aliases_enabled", "enabled"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    concept_id: Mapped[int] = mapped_column(
        ForeignKey("job_concepts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    alias: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(240), nullable=False)
    language: Mapped[str | None] = mapped_column(String(8))
    source: Mapped[str] = mapped_column(String(40), default="seed", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    concept: Mapped[JobConcept] = relationship(back_populates="aliases")
    evidence: Mapped[list[JobConceptEvidence]] = relationship(back_populates="alias")


class JobConceptEvidence(Base):
    """Recomputable evidence that a canonical job expresses a normalized concept."""

    __tablename__ = "job_concept_evidence"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "concept_id",
            "field",
            "extractor_version",
            name="uq_job_concept_evidence_job_concept_field_version",
        ),
        Index("ix_job_concept_evidence_job_version", "job_id", "extractor_version"),
        Index("ix_job_concept_evidence_concept", "concept_id"),
        Index("ix_job_concept_evidence_scope", "scope"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    concept_id: Mapped[int] = mapped_column(
        ForeignKey("job_concepts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    alias_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_concept_aliases.id", ondelete="SET NULL"), index=True
    )
    field: Mapped[str] = mapped_column(String(24), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    matched_text: Mapped[str] = mapped_column(String(240), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    concept: Mapped[JobConcept] = relationship(back_populates="evidence")
    alias: Mapped[JobConceptAlias | None] = relationship(back_populates="evidence")
