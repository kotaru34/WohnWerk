from app.jobs.concept_catalog import (
    CONCEPT_SEEDS,
    JobTextSnapshot,
    extract_concepts,
    normalize_concept_text,
)


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


def test_fem_does_not_match_female_word_fragment() -> None:
    slugs = _slugs(
        JobTextSnapshot(
            job_id=4,
            title="Female Mechanical Engineer",
            description="Inclusive engineering team.",
        )
    )

    assert ("method", "fem") not in slugs
    assert ("role", "mechanical-engineer") in slugs


def test_eplan_tool_does_not_imply_electrical_domain_by_itself() -> None:
    slugs = _slugs(
        JobTextSnapshot(
            job_id=5,
            title="E-Plan Konstrukteur im Sondermaschinenbau",
            description="Planung mit EPLAN.",
        )
    )

    assert ("tool", "eplan") in slugs
    assert ("domain", "special-machinery") in slugs
    assert ("domain", "electrical-engineering") not in slugs


def test_catalog_contains_all_normalization_dimensions() -> None:
    kinds = {seed.kind.value for seed in CONCEPT_SEEDS}

    assert kinds == {"role", "domain", "task", "method", "tool"}
