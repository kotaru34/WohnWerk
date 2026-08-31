from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.jobs.concepts import ConceptKind

EXTRACTOR_VERSION = "concept-seed-2026-08-31-v4"
_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class ConceptSeed:
    kind: ConceptKind
    slug: str
    label_de: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class JobTextSnapshot:
    job_id: int
    title: str
    description: str | None


@dataclass(frozen=True, slots=True)
class ConceptMatch:
    job_id: int
    kind: ConceptKind
    slug: str
    field: str
    alias: str
    normalized_alias: str
    confidence: float


def normalize_concept_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.replace("&", " und ")
    return " ".join(_NON_WORD_RE.sub(" ", normalized).split())


CONCEPT_SEEDS: tuple[ConceptSeed, ...] = (
    ConceptSeed(
        ConceptKind.ROLE,
        "mechanical-engineer",
        "Maschinenbauingenieur",
        ("Maschinenbauingenieur", "Mechanical Engineer"),
    ),
    ConceptSeed(
        ConceptKind.ROLE,
        "mechanical-technician",
        "Maschinenbautechniker",
        (
            "Maschinenbautechniker",
            "Maschinenbautechnikerin",
            "Mechanical Technician",
            "Mechanical Engineering Technician",
        ),
    ),
    ConceptSeed(
        ConceptKind.ROLE,
        "mechanical-designer",
        "Mechanischer Konstrukteur",
        (
            "Mechanischer Konstrukteur",
            "Konstrukteur Maschinenbau",
            "Mechanical Design Engineer",
            "Mechanical Designer",
        ),
    ),
    ConceptSeed(
        ConceptKind.ROLE,
        "designer-engineer",
        "Konstrukteur / Design Engineer",
        (
            "Konstrukteur",
            "Konstrukteurin",
            "Senior Konstrukteur",
            "Senior Designer",
            "Design Engineer",
        ),
    ),
    ConceptSeed(
        ConceptKind.ROLE,
        "development-engineer",
        "Entwicklungsingenieur",
        ("Entwicklungsingenieur", "Development Engineer"),
    ),
    ConceptSeed(
        ConceptKind.ROLE,
        "industrial-engineer",
        "Industrial Engineer / Arbeitstechniker",
        ("Industrial Engineer", "Arbeitstechniker", "Arbeitstechnikerin"),
    ),
    ConceptSeed(
        ConceptKind.ROLE,
        "quality-manager",
        "Qualitätsmanager",
        ("Quality Manager", "Plant Quality Manager", "Qualitätsmanager", "Qualitätsmanagerin"),
    ),
    ConceptSeed(
        ConceptKind.ROLE,
        "calculation-engineer",
        "Berechnungsingenieur",
        (
            "Berechnungsingenieur",
            "Berechnungsingenieurin",
            "Calculation Engineer",
            "CAE Engineer",
        ),
    ),
    ConceptSeed(
        ConceptKind.ROLE,
        "project-engineer",
        "Projektingenieur",
        ("Projektingenieur", "Project Engineer"),
    ),
    ConceptSeed(
        ConceptKind.ROLE,
        "project-manager",
        "Projektleiter / Projektmanager",
        (
            "Projektleiter",
            "Projektleiterin",
            "Projektmanager",
            "Projektmanagerin",
            "Projekt Manager",
            "Project Manager",
        ),
    ),
    ConceptSeed(
        ConceptKind.ROLE,
        "technical-project-manager",
        "Technischer Projektleiter",
        (
            "Technischer Projektleiter",
            "Technical Project Manager",
            "Technical Project Lead",
        ),
    ),
    ConceptSeed(
        ConceptKind.ROLE,
        "production-manager",
        "Produktionsleiter",
        (
            "Produktionsleiter",
            "Produktionsleiterin",
            "Production Manager",
            "Manufacturing Manager",
        ),
    ),
    ConceptSeed(
        ConceptKind.ROLE,
        "service-engineer",
        "Servicetechniker / Service Engineer",
        (
            "Servicetechniker",
            "Service Techniker",
            "Service-Techniker",
            "Außendienst Service Techniker",
            "Service Engineer",
            "Field Service Engineer",
            "Field Service Technician",
        ),
    ),
    ConceptSeed(
        ConceptKind.ROLE,
        "cad-designer",
        "CAD-Konstrukteur",
        ("CAD Konstrukteur", "CAD-Konstrukteur", "CAD Designer"),
    ),
    ConceptSeed(
        ConceptKind.ROLE,
        "technical-drafter",
        "CAD-Techniker / Technischer Zeichner",
        (
            "CAD Techniker",
            "CAD-Techniker",
            "Technischer Zeichner",
            "Technische Zeichnerin",
            "Detailplaner",
            "Ausführungsplaner",
        ),
    ),
    ConceptSeed(
        ConceptKind.ROLE,
        "mechatronics-technician",
        "Mechatroniker",
        ("Mechatroniker", "Mechatronikerin", "Mechatronics Technician"),
    ),
    ConceptSeed(
        ConceptKind.ROLE,
        "metal-technician",
        "Metalltechniker",
        ("Metalltechniker", "Metalltechnikerin", "Metal Technician"),
    ),
    ConceptSeed(
        ConceptKind.ROLE,
        "fitter",
        "Schlosser / Maschinenschlosser",
        ("Schlosser", "Schlosserin", "Maschinenschlosser", "Fitter"),
    ),
    ConceptSeed(
        ConceptKind.DOMAIN,
        "mechanical-engineering",
        "Maschinenbau",
        (
            "Maschinenbau",
            "Mechanical Engineering",
            "Mechanik",
            "Maschinenbautechniker",
            "Maschinenbautechnikerin",
        ),
    ),
    ConceptSeed(
        ConceptKind.DOMAIN,
        "plant-engineering",
        "Anlagenbau",
        ("Anlagenbau", "Plant Engineering", "Plant Construction"),
    ),
    ConceptSeed(
        ConceptKind.DOMAIN,
        "steel-construction",
        "Stahlbau",
        ("Stahlbau", "Steel Construction", "Structural Steel"),
    ),
    ConceptSeed(
        ConceptKind.DOMAIN,
        "building-services",
        "Gebäudetechnik / HKLS",
        (
            "Gebäudetechnik",
            "HKLS",
            "HKLS Technik",
            "HKLS-Technik",
            "Building Services",
            "HVAC",
        ),
    ),
    ConceptSeed(
        ConceptKind.DOMAIN,
        "mechatronics",
        "Mechatronik",
        ("Mechatronik", "Mechatronics", "Mechatroniker", "Mechatronikerin"),
    ),
    ConceptSeed(
        ConceptKind.DOMAIN,
        "automotive",
        "Fahrzeugbau / Automotive",
        (
            "Fahrzeugbau",
            "Fahrzeugtechnik",
            "Automotive",
            "KFZ Technik",
            "KFZ-Technik",
            "Vehicle Engineering",
        ),
    ),
    ConceptSeed(
        ConceptKind.DOMAIN,
        "special-vehicles",
        "Sonderfahrzeugbau",
        ("Sonderfahrzeugbau", "Special Vehicle", "Special Vehicles"),
    ),
    ConceptSeed(
        ConceptKind.DOMAIN,
        "rail-vehicles",
        "Schienenfahrzeugtechnik",
        (
            "Schienenfahrzeugtechnik",
            "Schienenfahrzeugbau",
            "Rail Vehicle",
            "Railway Vehicle",
        ),
    ),
    ConceptSeed(
        ConceptKind.DOMAIN,
        "special-machinery",
        "Sondermaschinenbau",
        (
            "Sondermaschinenbau",
            "Special Machinery",
            "Special Machine",
            "Special Lifting Solutions",
            "Kransysteme",
            "Hebelösungen",
        ),
    ),
    ConceptSeed(
        ConceptKind.DOMAIN,
        "hydropower",
        "Wasserkraft",
        ("Wasserkraft", "Hydropower", "Hydro Power"),
    ),
    ConceptSeed(
        ConceptKind.DOMAIN,
        "electrical-engineering",
        "Elektrotechnik",
        (
            "Elektrotechnik",
            "Electrical Engineering",
            "Electrical Engineer",
            "Elektrokonstrukteur",
            "Elektro Konstrukteur",
            "Elektro-Konstrukteur",
            "E-Konstrukteur",
            "Electrical Design Engineer",
            "Electrical Designer",
            "EMC Engineer",
            "EMV Ingenieur",
            "EMV-Ingenieur",
        ),
    ),
    ConceptSeed(
        ConceptKind.DOMAIN,
        "electronics",
        "Elektronik / Hardware",
        (
            "Elektronik",
            "Electronics",
            "Electronics Engineer",
            "Hardware Engineer",
            "Hardware Design Engineer",
            "Hardware Engineering",
        ),
    ),
    ConceptSeed(
        ConceptKind.TASK,
        "mechanical-design",
        "Mechanische Konstruktion",
        (
            "Mechanische Konstruktion",
            "Mechanical Design",
            "Bauteilkonstruktion",
            "Baugruppenkonstruktion",
        ),
    ),
    ConceptSeed(
        ConceptKind.TASK,
        "product-development",
        "Produktentwicklung",
        (
            "Produktentwicklung",
            "Produktentwicklungsprozess",
            "Entwicklungsprojekt",
            "Entwicklungsprojekte",
            "Product Development",
        ),
    ),
    ConceptSeed(
        ConceptKind.TASK,
        "requirements-engineering",
        "Anforderungen / Lasten- und Pflichtenhefte",
        (
            "Anforderungsmanagement",
            "Technische Anforderungen",
            "Analyse von Anforderungen",
            "Requirements Engineering",
            "Lastenheft",
            "Pflichtenheft",
        ),
    ),
    ConceptSeed(
        ConceptKind.TASK,
        "supplier-coordination",
        "Lieferantenkoordination",
        (
            "Lieferantenkoordination",
            "Lieferantenmanagement",
            "Supplier Coordination",
            "Supplier Management",
        ),
    ),
    ConceptSeed(
        ConceptKind.TASK,
        "testing-validation",
        "Versuch / Erprobung / Validierung",
        (
            "Versuch",
            "Erprobung",
            "Validierung",
            "Validierungen",
            "Validation",
            "Testing",
        ),
    ),
    ConceptSeed(
        ConceptKind.TASK,
        "assembly-commissioning",
        "Montage / Inbetriebnahme",
        ("Montage", "Inbetriebnahme", "Commissioning", "Assembly"),
    ),
    ConceptSeed(
        ConceptKind.TASK,
        "maintenance",
        "Instandhaltung",
        ("Instandhaltung", "Maintenance", "Maintenance Engineering"),
    ),
    ConceptSeed(
        ConceptKind.TASK,
        "production-manufacturing",
        "Fertigung / Produktion",
        (
            "Fertigung",
            "Fertigungsprozess",
            "Fertigungsprozesse",
            "Fertigungsprozessen",
            "Fertigungsbereich",
            "Fertigungsbereiche",
            "Fertigungsbereichen",
            "Gerätefertigung",
            "Produktion",
            "Produktionsumfeld",
            "Produktionssteuerung",
            "Manufacturing",
        ),
    ),
    ConceptSeed(
        ConceptKind.TASK,
        "detailed-design",
        "Ausführungs- / Detailplanung",
        ("Ausführungsplanung", "Detailplanung", "Detailed Design"),
    ),
    ConceptSeed(
        ConceptKind.TASK,
        "tolerance-analysis",
        "Toleranzanalyse",
        ("Toleranzanalyse", "Toleranzberechnung", "Toleranzen", "Tolerance Analysis"),
    ),
    ConceptSeed(
        ConceptKind.TASK,
        "calculation-simulation",
        "Berechnung / Simulation",
        (
            "Berechnung",
            "Simulation",
            "Kostensimulation",
            "Kostensimulationen",
            "Engineering Calculation",
        ),
    ),
    ConceptSeed(
        ConceptKind.TASK,
        "technical-project-management",
        "Technische Projektsteuerung",
        (
            "Projektsteuerung",
            "Projektleitung",
            "Projektmanagement",
            "Technical Project Management",
            "Projektkoordination",
        ),
    ),
    ConceptSeed(
        ConceptKind.TASK,
        "team-leadership",
        "Fachliche Teamführung",
        ("Fachliche Führung", "Teamführung", "Team Leadership", "Technical Leadership"),
    ),
    ConceptSeed(
        ConceptKind.TASK,
        "technical-documentation",
        "Technische Dokumentation",
        (
            "Technische Dokumentation",
            "Servicedokumentation",
            "Servicedokumentationen",
            "Anwenderdokumentation",
            "Anwenderdokumentationen",
            "Technical Documentation",
        ),
    ),
    ConceptSeed(
        ConceptKind.METHOD,
        "fem",
        "FEM",
        ("FEM", "Finite Element Method", "Finite Element Analysis"),
    ),
    ConceptSeed(
        ConceptKind.METHOD,
        "fmea",
        "FMEA",
        ("FMEA", "Failure Mode and Effects Analysis"),
    ),
    ConceptSeed(
        ConceptKind.METHOD,
        "agile-development",
        "Agile Entwicklung",
        ("Agile Entwicklung", "Agile Development", "Scrum", "Sprint Planning"),
    ),
    ConceptSeed(ConceptKind.TOOL, "solidworks", "SolidWorks", ("SolidWorks",)),
    ConceptSeed(ConceptKind.TOOL, "catia", "CATIA", ("CATIA",)),
    ConceptSeed(ConceptKind.TOOL, "creo", "Creo", ("Creo", "PTC Creo")),
    ConceptSeed(ConceptKind.TOOL, "siemens-nx", "Siemens NX", ("Siemens NX", "NX CAD")),
    ConceptSeed(
        ConceptKind.TOOL,
        "inventor",
        "Autodesk Inventor",
        ("Autodesk Inventor", "Inventor"),
    ),
    ConceptSeed(ConceptKind.TOOL, "autocad", "AutoCAD", ("AutoCAD",)),
    ConceptSeed(ConceptKind.TOOL, "eplan", "EPLAN", ("EPLAN", "E-Plan")),
)


def _contains_alias(normalized_text: str, normalized_alias: str) -> bool:
    if not normalized_text or not normalized_alias:
        return False
    pattern = rf"(?<![a-z0-9]){re.escape(normalized_alias)}(?![a-z0-9])"
    return re.search(pattern, normalized_text) is not None


def extract_concepts(
    snapshot: JobTextSnapshot,
    *,
    catalog: tuple[ConceptSeed, ...] = CONCEPT_SEEDS,
) -> list[ConceptMatch]:
    fields = (
        ("title", normalize_concept_text(snapshot.title), 1.0),
        ("description", normalize_concept_text(snapshot.description), 0.8),
    )
    matches: list[ConceptMatch] = []
    for concept in catalog:
        aliases = sorted(
            ((alias, normalize_concept_text(alias)) for alias in concept.aliases),
            key=lambda item: len(item[1]),
            reverse=True,
        )
        for field, normalized_text, confidence in fields:
            best: tuple[str, str] | None = None
            for alias, normalized_alias in aliases:
                if _contains_alias(normalized_text, normalized_alias):
                    best = (alias, normalized_alias)
                    break
            if best is None:
                continue
            matches.append(
                ConceptMatch(
                    job_id=snapshot.job_id,
                    kind=concept.kind,
                    slug=concept.slug,
                    field=field,
                    alias=best[0],
                    normalized_alias=best[1],
                    confidence=confidence,
                )
            )
    return matches
