from __future__ import annotations

from app.jobs.candidate_fit import CandidatePreferenceState
from app.jobs.concepts import ConceptKind

PROFILE_SEED_VERSION = "candidate-profile-2026-08-28-v2"
PROFILE_SLUG = "mechanical-project-engineer"
PROFILE_LABEL_DE = "Maschinenbau / technische Projektleitung"

# This seed contains only preferences already established for the candidate profile.
# Uncertain concepts intentionally remain unrated and can later be set in the admin UI.
PROFILE_PREFERENCES: dict[tuple[ConceptKind, str], CandidatePreferenceState] = {
    (ConceptKind.ROLE, "mechanical-engineer"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.ROLE, "mechanical-designer"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.ROLE, "development-engineer"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.ROLE, "project-engineer"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.ROLE, "technical-project-manager"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.DOMAIN, "mechanical-engineering"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.DOMAIN, "automotive"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.DOMAIN, "special-vehicles"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.DOMAIN, "rail-vehicles"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.DOMAIN, "special-machinery"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.DOMAIN, "electrical-engineering"): CandidatePreferenceState.CANNOT_NOT_WANT,
    (ConceptKind.DOMAIN, "electronics"): CandidatePreferenceState.CANNOT_NOT_WANT,
    (ConceptKind.TASK, "mechanical-design"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.TASK, "product-development"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.TASK, "requirements-engineering"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.TASK, "supplier-coordination"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.TASK, "testing-validation"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.TASK, "assembly-commissioning"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.TASK, "calculation-simulation"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.TASK, "technical-project-management"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.TASK, "team-leadership"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.TASK, "technical-documentation"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.METHOD, "fem"): CandidatePreferenceState.CAN_WANT,
    (ConceptKind.METHOD, "fmea"): CandidatePreferenceState.CAN_WANT,
}
