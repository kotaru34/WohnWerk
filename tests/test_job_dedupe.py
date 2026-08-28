from app.jobs.dedupe import (
    DuplicateJobSnapshot,
    duplicate_evidence,
    normalize_company,
    normalize_job_title,
    normalize_locality,
)


def _snapshot(
    job_id: int,
    *,
    title: str,
    company: str | None,
    description: str | None = None,
    postal: str | None = None,
    city: str | None = None,
    source: str | None = None,
) -> DuplicateJobSnapshot:
    return DuplicateJobSnapshot(
        job_id=job_id,
        title=title,
        company=company,
        description=description,
        postal_codes=frozenset([postal]) if postal else frozenset(),
        cities=frozenset([normalize_locality(city)]) if city else frozenset(),
        sources=(source or f"source-{job_id}",),
    )


def test_normalizers_remove_gender_and_company_legal_suffix_noise() -> None:
    assert normalize_job_title("Mechanical Engineer (m/w/d)") == "mechanical engineer"
    assert normalize_job_title("Mechanical Engineer m|f|d") == "mechanical engineer"
    assert normalize_company("Example Engineering GmbH & Co KG") == "example engineering"


def test_locality_normalizer_equates_klagenfurt_variants() -> None:
    assert normalize_locality("Klagenfurt") == normalize_locality("Klagenfurt am Wörthersee")


def test_cross_source_same_company_title_and_location_is_high_confidence() -> None:
    left = _snapshot(
        1,
        title="Entwicklungsingenieur für Maschinenbau/KFZ-Technik (m/w/d) bei Oberaigner",
        company="Oberaigner Automotive GmbH",
        city="Nebelberg",
    )
    right = _snapshot(
        2,
        title="Entwicklungsingenieur für Maschinenbau/KFZ-Technik (m/w/d) at Oberaigner",
        company="Oberaigner Automotive GmbH",
        city="Nebelberg",
    )

    evidence = duplicate_evidence(left, right)

    assert evidence is not None
    assert evidence.confidence == "high"
    assert evidence.company_match is True
    assert evidence.location_match is True
    assert evidence.title_similarity == 1.0
    assert evidence.shared_source is False


def test_same_title_but_different_companies_is_not_a_duplicate() -> None:
    left = _snapshot(
        1,
        title="Mechanical Engineer (m/w/d)",
        company="Alpha GmbH",
        city="Wien",
    )
    right = _snapshot(
        2,
        title="Mechanical Engineer (all genders)",
        company="Beta GmbH",
        city="Wien",
    )

    assert duplicate_evidence(left, right) is None


def test_same_company_and_title_with_conflicting_postal_codes_is_not_a_duplicate() -> None:
    left = _snapshot(
        1,
        title="Konstrukteur Maschinenbau (m/w/d)",
        company="Example GmbH",
        postal="1010",
    )
    right = _snapshot(
        2,
        title="Konstrukteur Maschinenbau (m/w/d)",
        company="Example GmbH",
        postal="8010",
    )

    assert duplicate_evidence(left, right) is None


def test_same_company_similar_title_without_location_is_medium_confidence() -> None:
    left = _snapshot(
        1,
        title="Senior Konstrukteur Maschinenbau",
        company="Example GmbH",
    )
    right = _snapshot(
        2,
        title="Senior Konstrukteur im Maschinenbau",
        company="Example GmbH",
    )

    evidence = duplicate_evidence(left, right)

    assert evidence is not None
    assert evidence.confidence == "medium"


def test_generic_title_without_location_overlap_stays_medium() -> None:
    left = _snapshot(
        1,
        title="Konstrukteur (m/w/d)",
        company="Trenkwalder Personaldienste GmbH",
    )
    right = _snapshot(
        2,
        title="Konstrukteur (m/w/d)",
        company="Trenkwalder Personaldienste GmbH",
        city="Klagenfurt",
    )

    evidence = duplicate_evidence(left, right)

    assert evidence is not None
    assert evidence.confidence == "medium"
    assert evidence.generic_title is True


def test_cross_source_generic_title_with_equivalent_location_is_high_confidence() -> None:
    left = _snapshot(
        1,
        title="Konstrukteur (m/w/d)",
        company="Trenkwalder Personaldienste GmbH",
        city="Klagenfurt",
    )
    right = _snapshot(
        2,
        title="Konstrukteur (m/w/d)",
        company="Trenkwalder Personaldienste GmbH",
        city="Klagenfurt am Wörthersee",
    )

    evidence = duplicate_evidence(left, right)

    assert evidence is not None
    assert evidence.confidence == "high"
    assert evidence.location_match is True


def test_same_source_same_title_and_location_without_body_overlap_is_medium() -> None:
    left = _snapshot(
        1,
        title="Senior Autonomous Vehicle Technician - Fleet Maintenance",
        company="Example GmbH",
        description="First distinct opening with a maintenance focus and enough descriptive words to count for similarity analysis.",
        city="Wien",
        source="lever",
    )
    right = _snapshot(
        2,
        title="Senior Autonomous Vehicle Technician (Fleet Maintenance)",
        company="Example GmbH",
        description="Second separate vacancy with unrelated operational responsibilities and enough other wording to count for comparison.",
        city="Wien",
        source="lever",
    )

    evidence = duplicate_evidence(left, right)

    assert evidence is not None
    assert evidence.confidence == "medium"
    assert evidence.shared_source is True


def test_same_source_strong_description_overlap_can_be_high() -> None:
    body = (
        "Mechanical product development CAD construction supplier coordination testing "
        "commissioning validation documentation project support manufacturing assemblies"
    )
    left = _snapshot(
        1,
        title="Junior Konstrukteur Maschinenbau - dein Design, unsere Zukunft!",
        company="Example GmbH",
        description=body,
        source="jobs.at",
    )
    right = _snapshot(
        2,
        title="Junior Konstrukteur Maschinenbau – dein Design, unsere Zukunft!",
        company="Example GmbH",
        description=body + " additional detail",
        source="jobs.at",
    )

    evidence = duplicate_evidence(left, right)

    assert evidence is not None
    assert evidence.confidence == "high"
    assert evidence.shared_source is True
    assert evidence.description_similarity >= 0.82
