from app.jobs.concept_catalog import (
    CONCEPT_SEEDS,
    JobTextSnapshot,
    extract_concepts,
    normalize_concept_text,
)
from app.jobs.concepts import ConceptEvidenceScope, ConceptKind, concept_evidence_semantics


def _slugs(snapshot: JobTextSnapshot) -> set[tuple[str, str]]:
    return {(match.kind.value, match.slug) for match in extract_concepts(snapshot)}


def test_normalizer_handles_umlauts_punctuation_and_spacing() -> None:
    assert normalize_concept_text("  KFZ-Technik & FEM-Berechnung ") == (
        "kfz technik und fem berechnung"
    )


def test_german_and_english_role_synonyms_converge() -> None:
    german = _slugs(
        JobTextSnapshot(
            job_id=1,
            title="Maschinenbauingenieur (m/w/d)",
            description=None,
        )
    )
    english = _slugs(
        JobTextSnapshot(
            job_id=2,
            title="Mechanical Engineer m|f|d",
            description=None,
        )
    )

    assert ("role", "mechanical-engineer") in german
    assert ("role", "mechanical-engineer") in english


def test_title_and_description_keep_separate_recomputable_evidence() -> None:
    matches = extract_concepts(
        JobTextSnapshot(
            job_id=3,
            title="Entwicklungsingenieur Maschinenbau",
            description=(
                "Produktentwicklung mit FEM, FMEA, Lieferantenkoordination und SolidWorks."
            ),
        )
    )

    assert any(
        match.slug == "development-engineer"
        and match.field == "title"
        and match.confidence == 1.0
        for match in matches
    )
    assert any(
        match.slug == "fem" and match.field == "description" and match.confidence == 0.8
        for match in matches
    )
    assert any(match.slug == "solidworks" and match.field == "description" for match in matches)


def test_evidence_scope_distinguishes_identity_from_description_context() -> None:
    title_scope, title_confidence = concept_evidence_semantics(ConceptKind.ROLE, "title")
    role_scope, role_confidence = concept_evidence_semantics(ConceptKind.ROLE, "description")
    domain_scope, domain_confidence = concept_evidence_semantics(
        ConceptKind.DOMAIN, "description"
    )
    task_scope, task_confidence = concept_evidence_semantics(ConceptKind.TASK, "description")

    assert (title_scope, title_confidence) == (ConceptEvidenceScope.PRIMARY, 1.0)
    assert (role_scope, role_confidence) == (ConceptEvidenceScope.CONTEXT, 0.45)
    assert (domain_scope, domain_confidence) == (ConceptEvidenceScope.CONTEXT, 0.55)
    assert (task_scope, task_confidence) == (ConceptEvidenceScope.CONTEXT, 0.80)


def test_description_education_alternative_is_context_not_primary_domain() -> None:
    matches = extract_concepts(
        JobTextSnapshot(
            job_id=4,
            title="Entwicklungsingenieur Maschinenbau",
            description="Studium Maschinenbau, Mechatronik oder Elektrotechnik erforderlich.",
        )
    )
    electrical = next(
        match
        for match in matches
        if match.slug == "electrical-engineering" and match.field == "description"
    )
    scope, confidence = concept_evidence_semantics(electrical.kind, electrical.field)

    assert scope == ConceptEvidenceScope.CONTEXT
    assert confidence == 0.55


def test_fem_does_not_match_female_word_fragment() -> None:
    slugs = _slugs(
        JobTextSnapshot(
            job_id=5,
            title="Female Mechanical Engineer",
            description="Inclusive engineering team.",
        )
    )

    assert ("method", "fem") not in slugs
    assert ("role", "mechanical-engineer") in slugs


def test_eplan_tool_does_not_imply_electrical_domain_by_itself() -> None:
    slugs = _slugs(
        JobTextSnapshot(
            job_id=6,
            title="E-Plan Konstrukteur im Sondermaschinenbau",
            description="Planung mit EPLAN.",
        )
    )

    assert ("tool", "eplan") in slugs
    assert ("role", "designer-engineer") in slugs
    assert ("domain", "special-machinery") in slugs
    assert ("domain", "electrical-engineering") not in slugs


def test_maschinenbautechniker_maps_to_role_and_mechanical_domain() -> None:
    slugs = _slugs(
        JobTextSnapshot(
            job_id=7,
            title="Maschinenbautechniker/in (m/w/d)",
            description=None,
        )
    )

    assert ("role", "mechanical-technician") in slugs
    assert ("domain", "mechanical-engineering") in slugs


def test_spaced_service_techniker_is_normalized_as_service_role() -> None:
    slugs = _slugs(
        JobTextSnapshot(
            job_id=8,
            title="Außendienst Service Techniker - Pharma & Life Sciences (m/w/d)",
            description=None,
        )
    )

    assert ("role", "service-engineer") in slugs


def test_generic_konstrukteur_role_does_not_imply_mechanical_domain() -> None:
    slugs = _slugs(
        JobTextSnapshot(
            job_id=9,
            title="Senior Konstrukteur (m/w/d)",
            description=None,
        )
    )

    assert ("role", "designer-engineer") in slugs
    assert ("domain", "mechanical-engineering") not in slugs


def test_real_unmatched_patterns_gain_neutral_concepts() -> None:
    plant_designer = _slugs(
        JobTextSnapshot(
            job_id=10,
            title="Senior Konstrukteur (m/w/d) im Maschinen- & Anlagenbau",
            description=None,
        )
    )
    calculation = _slugs(
        JobTextSnapshot(
            job_id=11,
            title="Berechnungsingenieur Toleranzen 2D/3D (m/w/d)",
            description=None,
        )
    )
    building_services = _slugs(
        JobTextSnapshot(
            job_id=12,
            title="Ingenieur:in Gebäudetechnik / HKLS-Technik (m/w/d)",
            description=None,
        )
    )

    assert ("role", "designer-engineer") in plant_designer
    assert ("domain", "plant-engineering") in plant_designer
    assert ("role", "calculation-engineer") in calculation
    assert ("task", "tolerance-analysis") in calculation
    assert ("domain", "building-services") in building_services


def test_catalog_contains_all_normalization_dimensions() -> None:
    kinds = {seed.kind.value for seed in CONCEPT_SEEDS}

    assert kinds == {"role", "domain", "task", "method", "tool"}
