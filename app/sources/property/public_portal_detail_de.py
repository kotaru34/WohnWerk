"""Conservative evidence gate for *individual* public German house detail pages.

Only a manually enabled, low-volume diagnostic/ingestion may read detail pages.
No contact details, descriptions, photos or HTML are persisted. If an existing
house cannot be independently confirmed, the card is not activated as a house.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.sources.property.immmo import _DOMParser, _decimal


@dataclass(frozen=True, slots=True)
class PublicHouseEvidence:
    verified: bool
    reason: str


_BUILDER_OFFER = re.compile(
    r"(?:bauleistungsbeschreibung|hausbauvertrag|kosten (?:f[üu]r |der )?grundst[üu]ck"
    r".{0,80}(?:auftraggeber|[üu]bernehmen)|"
    r"bauen (?:sie |wir |ihr )?(?:ihr |unser )?traumhaus|"
    r"grundst[üu]ckssuche|"
    r"hauspreis ohne grundst[üu]ck)",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\bBaujahr\b[^0-9]{0,45}\b((?:18|19|20)\d{2})\b", re.IGNORECASE)
_PRICE_BEFORE_LABEL = re.compile(
    r"(?<!\w)([\d.]+(?:,\d{1,2})?)\s*€\s*Kaufpreis\b", re.IGNORECASE
)
_PRICE_AFTER_LABEL = re.compile(
    r"\bKaufpreis\b\s*[:|]?\s*([\d.]+(?:,\d{1,2})?)\s*€", re.IGNORECASE
)


def _public_text(html: str) -> str:
    parser = _DOMParser()
    parser.feed(html)
    body = next(
        (node for node in parser.root.walk() if node.tag == "main"), None
    )
    return (body or parser.root).text()


def verify_public_house_detail(
    html: str,
    *,
    provider_name: str,
    listing_id: str,
    price_eur: Decimal,
    postal_code: str,
) -> PublicHouseEvidence:
    """Verify one detail as an existing DE house at its advertised ask.

    Both source listing ID and asking price must be present in the public detail.
    Builders advertising a hypothetical turnkey project and a separate plot are
    excluded, even if an attractive price and a city PLZ are displayed.
    """
    text = _public_text(html)
    if provider_name == "ohne-makler-de":
        id_pattern = rf"\bOM-\s*{re.escape(listing_id)}\b"
    elif provider_name == "immobilien-de":
        id_pattern = rf"\b(?:immobilien\.de\s+Nr\.|Obj\.-Nr\.)\s*{re.escape(listing_id)}\b"
    else:
        return PublicHouseEvidence(False, "unsupported_provider")
    if not re.search(id_pattern, text, re.IGNORECASE):
        return PublicHouseEvidence(False, "listing_id_unverified")
    if not re.search(rf"(?<!\d){re.escape(postal_code)}(?!\d)", text):
        return PublicHouseEvidence(False, "postcode_unverified")
    if _BUILDER_OFFER.search(text):
        return PublicHouseEvidence(False, "construction_only")

    # Check a source-backed asking price, not financing examples or €/m² figures.
    if provider_name == "immobilien-de":
        price_match = _PRICE_BEFORE_LABEL.search(text) or _PRICE_AFTER_LABEL.search(text)
    else:
        price_match = _PRICE_AFTER_LABEL.search(text)
    if price_match is None or _decimal(price_match.group(1)) != price_eur:
        return PublicHouseEvidence(False, "asking_price_unverified")

    # A full detail must prove a *built house* and its real plot.
    if not re.search(r"\bWohnfl[äa]che\b", text, re.IGNORECASE):
        return PublicHouseEvidence(False, "living_area_unverified")
    if not re.search(r"\bGrundst[üu]cksfl[äa]che\b", text, re.IGNORECASE):
        return PublicHouseEvidence(False, "land_area_unverified")
    years = [
        int(year) for year in _YEAR.findall(text)
        if int(year) <= date.today().year
    ]
    if not years:
        return PublicHouseEvidence(False, "existing_building_unverified")
    if re.search(r"nicht Hauptwohnsitz|nur Feriennutzung", text, re.IGNORECASE):
        return PublicHouseEvidence(False, "no_primary_residence")
    return PublicHouseEvidence(True, "verified_existing_house")
