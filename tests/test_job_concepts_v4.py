from app.jobs.candidate_profile_seed import PROFILE_PREFERENCES
from app.jobs.concept_catalog import JobTextSnapshot, extract_concepts
from app.jobs.concepts import ConceptKind


def _slugs(title: str, description: str | None = None) -> set[tuple[str, str]]:
    return {
        (match.kind.value, match.slug)
        for match in extract_concepts(
            JobTextSnapshot(job_id=1, title=title, description=description)
        )
    }


def test_industrial_engineer_is_a_neutral_role_with_manufacturing_context() -> None:
    slugs = _slugs(
        "Industrial Engineer (w/m/d)",
        "Maschinenbau, Produktionsumfeld und kontinuierliche Prozessverbesserung.",
    )

    assert ("role", "industrial-engineer") in slugs
    assert ("domain", "mechanical-engineering") in slugs
    assert ("task", "production-manufacturing") in slugs


def test_arbeitstechniker_industrial_engineer_keeps_real_engineering_tasks() -> None:
    slugs = _slugs(
        "Arbeitstechniker / Industrial Engineer (w/m/d)",
        (
            "Vorkenntnisse von Fertigungsprozessen, Beratung im Produktentwicklungsprozess, "
            "Kostensimulationen, Verbesserungen in Fertigungsbereichen und Produktionssteuerung."
        ),
    )

    assert ("role", "industrial-engineer") in slugs
    assert ("task", "product-development") in slugs
    assert ("task", "production-manufacturing") in slugs
    assert ("task", "calculation-simulation") in slugs


def test_plant_quality_manager_has_neutral_role_and_fmea_method() -> None:
    slugs = _slugs(
        "Plant Quality Manager (w/m/d)",
        "Qualitätsstrategie, Risikoanalysen und FMEA für Produkt- und Prozesskonformität.",
    )

    assert ("role", "quality-manager") in slugs
    assert ("method", "fmea") in slugs


def test_spaced_projekt_manager_special_lifting_maps_to_existing_semantics() -> None:
    slugs = _slugs(
        "Projekt Manager - Special Lifting Solutions (m/w/d)",
        (
            "Leitung komplexer Entwicklungsprojekte und Projektmanagement mit Verantwortung "
            "für Zeit, Budget und Ressourcen."
        ),
    )

    assert ("role", "project-manager") in slugs
    assert ("domain", "special-machinery") in slugs
    assert ("task", "product-development") in slugs
    assert ("task", "technical-project-management") in slugs


def test_crane_and_vehicle_development_title_exposes_both_domains() -> None:
    slugs = _slugs(
        "Entwicklungsingenieur Kransysteme oder Fahrzeugtechnik (w/m/d)",
        "Konstruktion und Berechnung mechanischer Systeme mit PTC Creo.",
    )

    assert ("role", "development-engineer") in slugs
    assert ("domain", "special-machinery") in slugs
    assert ("domain", "automotive") in slugs
    assert ("task", "calculation-simulation") in slugs
    assert ("tool", "creo") in slugs


def test_service_diagnostic_tool_development_keeps_engineering_evidence() -> None:
    slugs = _slugs(
        "Development Engineer - Service & Diagnostic Tools (w/m/d)",
        (
            "Analyse von Anforderungen und Umsetzung in technische Lösungen für Mechanik und "
            "Elektronik, Validierungen, Anwenderdokumentationen und Konstruktion mit Creo."
        ),
    )

    assert ("role", "development-engineer") in slugs
    assert ("domain", "mechanical-engineering") in slugs
    assert ("domain", "electronics") in slugs
    assert ("task", "requirements-engineering") in slugs
    assert ("task", "testing-validation") in slugs
    assert ("task", "technical-documentation") in slugs
    assert ("tool", "creo") in slugs


def test_new_industrial_and_quality_roles_are_not_silently_rated() -> None:
    assert (ConceptKind.ROLE, "industrial-engineer") not in PROFILE_PREFERENCES
    assert (ConceptKind.ROLE, "quality-manager") not in PROFILE_PREFERENCES
