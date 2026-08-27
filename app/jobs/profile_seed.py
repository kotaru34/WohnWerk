from __future__ import annotations

import re

PatternSet = tuple[tuple[str, re.Pattern[str]], ...]


# Generalized discovery seed for the target professional neighbourhood.
# Keep this deliberately broader than a CV title list: the durable profile will
# later be learned from reviewed concepts in the vacancy corpus.
STRONG_TITLE_PATTERNS: PatternSet = (
    ("maschinenbauingenieur", re.compile(r"\bmaschinenbau(?:ingenieur|techniker)\w*")),
    (
        "konstruktionsingenieur",
        re.compile(r"\bkonstruktions?(?:ingenieur|techniker)\w*"),
    ),
    ("konstrukteur", re.compile(r"\b(?:entwicklungs[-\s]*)?konstrukteur\w*")),
    ("entwicklungsingenieur", re.compile(r"\bentwicklungsingenieur\w*")),
    ("berechnungsingenieur", re.compile(r"\bberechnungsingenieur\w*")),
    ("mechanical_engineer", re.compile(r"\bmechanical\s+engineer\w*")),
    (
        "mechanical_design_engineer",
        re.compile(r"\bmechanical\s+design\s+engineer\w*"),
    ),
    ("cad_konstrukteur", re.compile(r"\bcad[-\s]*(?:konstrukteur|designer)\w*")),
    (
        "vehicle_development_engineer",
        re.compile(
            r"\b(?:vehicle|automotive|fahrzeug)\w*\s+(?:development\s+)?engineer\w*"
        ),
    ),
    (
        "rail_vehicle_engineer",
        re.compile(
            r"\b(?:rail|rolling\s+stock|schienenfahrzeug)\w*\s+(?:engineer|ingenieur)\w*"
        ),
    ),
    ("mechatronik", re.compile(r"\bmechatronik(?:er|ingenieur|techniker)?\w*")),
)


# Roles that are plausible only when the vacancy also shows engineering-domain
# or method/tool evidence. Generic "engineer" is intentional for recall, with
# negative-context damping in the classifier.
ADJACENT_ROLE_PATTERNS: PatternSet = (
    (
        "technical_project_lead",
        re.compile(
            r"\b(?:technical|technisch\w*)\s+(?:project|projekt)\s*"
            r"(?:lead|leiter|manager)\w*"
        ),
    ),
    ("project_engineer", re.compile(r"\b(?:project\s+engineer|projektingenieur)\w*")),
    (
        "project_manager",
        re.compile(r"\b(?:project\s+manager|projektleiter|projektmanager)\w*"),
    ),
    ("development_engineer", re.compile(r"\bdevelopment\s+engineer\w*")),
    ("design_engineer", re.compile(r"\bdesign\s+engineer\w*")),
    ("product_engineer", re.compile(r"\bproduct\s+engineer\w*")),
    ("application_engineer", re.compile(r"\bapplication\s+engineer\w*")),
    ("simulation_engineer", re.compile(r"\bsimulation\s+engineer\w*")),
    ("r_and_d_engineer", re.compile(r"\br\s*[&/]\s*d\s+engineer\w*")),
    ("systems_engineer", re.compile(r"\bsystems?\s+engineer\w*")),
    (
        "systems_specialist",
        re.compile(
            r"\b(?:self[-\s]*driving\s+)?systems?\s+(?:specialist|expert)\w*"
            r"|\bsds\s+specialist\w*"
        ),
    ),
    ("technical_specialist", re.compile(r"\btechnical\s+(?:specialist|expert)\w*")),
    (
        "technischer_spezialist",
        re.compile(r"\btechnisch\w*\s+(?:spezialist|experte)\w*"),
    ),
    ("technician", re.compile(r"\b(?:technician|techniker)\w*")),
    ("engineer", re.compile(r"\b(?:engineer|ingenieur)\w*")),
    ("team_lead", re.compile(r"\b(?:team\s*lead|teamleiter)\w*")),
)


# Titles that are operational/manual-support roles rather than the target
# engineering neighbourhood. Strong mechanical titles are checked before this
# list, so a genuinely engineering-specific title can still win.
LOW_RELEVANCE_TITLE_PATTERNS: PatternSet = (
    (
        "depot_operations",
        re.compile(r"\b(?:depot\s+(?:specialist|operator|worker)|depotmitarbeiter)\w*"),
    ),
    (
        "safety_driver",
        re.compile(
            r"\b(?:sicherheitsfahrer|safety\s+driver|safety\s+operator|vehicle\s+driver)\w*"
        ),
    ),
    ("field_survey", re.compile(r"\b(?:field\s+surveyor|field\s+data\s+collection)\w*")),
)


DOMAIN_PATTERNS: PatternSet = (
    (
        "maschinenbau",
        re.compile(r"\bmaschinenbau\w*|\bmachine\s+(?:building|engineering)\b"),
    ),
    ("mechanical", re.compile(r"\bmechanical\b|\bmechanik\w*")),
    ("vehicle_engineering", re.compile(r"\b(?:vehicle|automotive|fahrzeug)\w*")),
    ("special_vehicle", re.compile(r"\b(?:sonderfahrzeug|special\s+vehicle)\w*")),
    (
        "rail_vehicle",
        re.compile(
            r"\b(?:schienenfahrzeug|rolling\s+stock|rail\s+vehicle|railway\s+vehicle)\w*"
        ),
    ),
    (
        "autonomous_vehicle_systems",
        re.compile(
            r"\b(?:autonomous\s+(?:vehicle|driving)|self[-\s]*driving|adas|"
            r"advanced\s+driver\s+assistance)\w*"
        ),
    ),
    (
        "vehicle_electronics",
        re.compile(r"\b(?:automotive\s+electronics|fahrzeugelektronik|vehicle\s+electronics)\w*"),
    ),
    (
        "fixture_tooling",
        re.compile(
            r"\b(?:\w*vorrichtung\w*|fixtures?\w*|jigs?\w*|"
            r"(?:production|manufacturing|assembly|weld(?:ing)?)\s+tooling)\b"
        ),
    ),
    (
        "plant_engineering",
        re.compile(r"\b(?:anlagenbau|plant\s+engineering|plant\s+design)\w*"),
    ),
    (
        "special_machinery",
        re.compile(r"\b(?:sondermaschinenbau|special\s+machinery|special\s+machine)\w*"),
    ),
    (
        "metal_engineering",
        re.compile(r"\b(?:metallbau|metal\s+engineering|metal\s+construction)\w*"),
    ),
    ("welding", re.compile(r"\b(?:schweiß|schweiss|weld)\w*")),
    ("assembly", re.compile(r"\b(?:montage|assembly)\w*")),
    (
        "manufacturing",
        re.compile(r"\b(?:fertigung|manufactur|production\s+engineering)\w*"),
    ),
    (
        "product_development",
        re.compile(r"\b(?:produktentwick|product\s+development)\w*"),
    ),
    (
        "component_development",
        re.compile(
            r"\b(?:baugruppe|bauteil|component\s+development|mechanical\s+component)\w*"
        ),
    ),
    (
        "chassis_structure",
        re.compile(
            r"\b(?:chassis|fahrgestell|wagenkasten|carbody|vehicle\s+structure)\w*"
        ),
    ),
    (
        "wheel_development",
        re.compile(r"\b(?:radentwicklung|wheel\s+development|wheel\s+design)\w*"),
    ),
    (
        "stage_systems",
        re.compile(r"\b(?:bühnentechnik|buehnentechnik|stage\s+(?:systems?|engineering))\w*"),
    ),
)


METHOD_TOOL_PATTERNS: PatternSet = (
    ("cad", re.compile(r"\bcad\b")),
    ("catia", re.compile(r"\bcatia(?:\s*v5)?\b")),
    ("creo", re.compile(r"\bcreo(?:\s+elements)?\b")),
    ("solidworks", re.compile(r"\bsolidworks\b")),
    ("inventor", re.compile(r"\b(?:autodesk\s+)?inventor\b")),
    ("siemens_nx", re.compile(r"\b(?:siemens\s+)?nx(?:\s+cad)?\b")),
    ("fem_fea", re.compile(r"\b(?:fem|fea|finite\s+element)\w*")),
    (
        "strength_analysis",
        re.compile(
            r"\b(?:festigkeitsberechnung|festigkeitsbewertung|"
            r"strength\s+(?:analysis|calculation|assessment))\w*"
        ),
    ),
    ("fmea", re.compile(r"\b(?:design[-\s]*fmea|prozess[-\s]*fmea|process[-\s]*fmea|fmea)\b")),
    ("pdm", re.compile(r"\bpdm(?:[-\s]*system)?\w*")),
    ("plm", re.compile(r"\bplm(?:[-\s]*system)?\w*")),
    (
        "requirements_specification",
        re.compile(
            r"\b(?:lastenheft|pflichtenheft|requirements?\s+"
            r"(?:specification|engineering|management))\w*"
        ),
    ),
    (
        "technical_drawing",
        re.compile(r"\b(?:technisch\w*\s+zeichnung|technical\s+drawing)\w*"),
    ),
    (
        "concept_development",
        re.compile(r"\b(?:konzeptentwick|concept\s+development|conceptual\s+design)\w*"),
    ),
    ("diagnostics", re.compile(r"\b(?:diagnostik|diagnostics?|troubleshooting)\w*")),
    ("calibration", re.compile(r"\b(?:kalibrier|calibrat)\w*")),
    (
        "system_integration",
        re.compile(r"\b(?:systemintegration|system\s+integration|integration\s+testing)\w*"),
    ),
    ("can_bus", re.compile(r"\b(?:can\s+bus|fahrzeugnetzwerk|vehicle\s+network)\w*")),
    ("validation", re.compile(r"\b(?:validier|validation|verification)\w*")),
    (
        "testing",
        re.compile(r"\b(?:versuch|testing|test\s+engineering|prototype\s+test)\w*"),
    ),
    ("commissioning", re.compile(r"\b(?:inbetriebnahme|commissioning)\w*")),
    (
        "supplier_coordination",
        re.compile(
            r"\b(?:lieferanten(?:steuerung|koordination|betreuung)|"
            r"supplier\s+(?:management|coordination|development))\w*"
        ),
    ),
    (
        "interface_management",
        re.compile(r"\b(?:schnittstellenmanagement|interface\s+management)\w*"),
    ),
    (
        "milestone_planning",
        re.compile(r"\b(?:meilenstein|milestone|terminsteuerung|schedule\s+management)\w*"),
    ),
    (
        "series_readiness",
        re.compile(r"\b(?:serienreife|serienproduktion|series\s+(?:readiness|production))\w*"),
    ),
)


# These are not absolute exclusions. They only prevent one weak domain token such
# as "automotive" from making an otherwise clearly software/commercial vacancy
# look mechanically relevant.
NEGATIVE_CONTEXT_PATTERNS: PatternSet = (
    (
        "software",
        re.compile(
            r"\b(?:software|backend|frontend|full[-\s]*stack|devops|devsecops|cloud|"
            r"kubernetes|terraform)\w*"
        ),
    ),
    (
        "data_ai",
        re.compile(
            r"\b(?:data\s+(?:scientist|engineer)|machine\s+learning|"
            r"artificial\s+intelligence|\bai\b)\w*"
        ),
    ),
    (
        "enterprise_it",
        re.compile(
            r"\b(?:crm|salesforce|java|javascript|typescript|python\s+developer|"
            r"sap\s+(?:developer|consultant))\w*"
        ),
    ),
    (
        "sales",
        re.compile(r"\b(?:sales|vertrieb|business\s+development|account\s+manager)\w*"),
    ),
    ("hr", re.compile(r"\b(?:human\s+resources|recruit|talent\s+acquisition|hr\s+)\w*")),
    (
        "finance",
        re.compile(r"\b(?:accountant|accounting|finance|financial|controlling)\w*"),
    ),
)
