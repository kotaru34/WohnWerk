from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    delete,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base
from app.models import PropertyListing, Source

if TYPE_CHECKING:
    from app.internet_access import InternetAccess

IMMOSCOUT_DE_HOSTS = {"immobilienscout24.de", "www.immobilienscout24.de"}
IMMOWELT_DE_HOSTS = {"immowelt.de", "www.immowelt.de"}

EVIDENCE_PORTAL_ADDRESS_ESTIMATE = "portal_address_estimate"
EVIDENCE_LISTING_CLAIM = "listing_claim"
EVIDENCE_SOURCE_ADDRESS = "source_address"

ADDRESS_STREET_HOUSE_NUMBER = "street_house_number"

_TECHNOLOGY_LABELS = {
    "dsl": "DSL",
    "vdsl": "VDSL",
    "svvdsl": "SVVDSL",
    "kabel": "Kabel",
    "kabelinternet": "Kabel",
    "glasfaser": "Glasfaser",
    "fiber": "Glasfaser",
    "ftth": "Glasfaser",
    "hybrid": "Hybrid",
}
_KNOWN_PROVIDERS = (
    "Telekom",
    "Vodafone",
    "M-Net",
    "PYUR",
    "PŸUR",
    "Deutsche Glasfaser",
    "1&1",
)

_SPEED_TOKEN = r"\d{1,4}(?:[.,]\d{1,3})?"
_SPEED_RE = re.compile(rf"(?P<speed>{_SPEED_TOKEN})\s*M(?:bit|Bit)/s", re.IGNORECASE)
_UPLOAD_RE = re.compile(
    rf"(?:upload|im\s+upload|bis\s+zu)\D{{0,24}}(?P<speed>{_SPEED_TOKEN})\s*M(?:bit|Bit)/s",
    re.IGNORECASE,
)
_PROVIDER_TECH_SPEED_RE = re.compile(
    rf"(?P<provider>[A-ZÄÖÜ][A-Za-zÄÖÜäöüß0-9 .&+\-]{{1,35}})\s*:\s*"
    rf"(?P<tech>Glasfaser|Kabelinternet|Kabel|SVVDSL|VDSL|DSL|Hybrid)\s*"
    rf"(?:bis(?:\s+zu)?\s*)?(?P<speed>{_SPEED_TOKEN})\s*M(?:bit|Bit)/s",
    re.IGNORECASE,
)
_TECH_SPEED_RE = re.compile(
    rf"(?P<tech>Glasfaser(?:-Internet)?|Glasfaseranschluss|Kabelinternet|Kabel|SVVDSL|VDSL|DSL|Hybrid)"
    rf"[^\n|;.]{{0,85}}?(?:bis(?:\s+zu)?|max\.?|mit\s+bis\s+zu)?\s*"
    rf"(?P<speed>{_SPEED_TOKEN})\s*M(?:bit|Bit)/s",
    re.IGNORECASE,
)
_SPEED_TECH_RE = re.compile(
    rf"(?P<speed>{_SPEED_TOKEN})\s*M(?:bit|Bit)/s[^\n|;.]{{0,30}}?"
    rf"\((?P<tech>Glasfaser|Kabelinternet|Kabel|SVVDSL|VDSL|DSL|Hybrid)\)",
    re.IGNORECASE,
)
_CONNECTED_FIBER_RE = re.compile(
    r"\b(?:Glasfaser(?:anschluss)?|Glasfaser-Netz)\b[^\n.;]{0,100}"
    r"\b(?:angeschlossen|Hausanschluss|im\s+Haus|im\s+Haupthaus|im\s+Keller)\b",
    re.IGNORECASE,
)
_PROPERTY_FIBER_RE = re.compile(
    r"\bGlasfaser\b[^\n.;]{0,80}\b(?:am|auf\s+dem)\s+Grundstück\b",
    re.IGNORECASE,
)
_PLANNED_FIBER_RE = re.compile(
    r"\bGlasfaser\b[^\n.;]{0,100}\b(?:in\s+Planung|Ausbau|vorgesehen|geplant)\b",
    re.IGNORECASE,
)


class PropertyInternetSourceEvidence(Base):
    """Source-backed Internet claim tied to one property listing."""

    __tablename__ = "property_internet_source_evidence"
    __table_args__ = (
        UniqueConstraint(
            "property_listing_id",
            "evidence_key",
            name="uq_property_internet_source_evidence_listing_key",
        ),
        Index(
            "ix_property_internet_source_evidence_property_kind",
            "property_id",
            "evidence_kind",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_listing_id: Mapped[int] = mapped_column(
        ForeignKey("property_listings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    evidence_key: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    availability_status: Mapped[str | None] = mapped_column(String(32))
    claim_semantics: Mapped[str | None] = mapped_column(String(48))
    provider_name: Mapped[str | None] = mapped_column(String(120))
    technology: Mapped[str | None] = mapped_column(String(48))
    max_download_mbps: Mapped[int | None] = mapped_column(Integer)
    max_upload_mbps: Mapped[int | None] = mapped_column(Integer)
    source_address: Mapped[str | None] = mapped_column(String(500))
    address_precision: Mapped[str | None] = mapped_column(String(48))
    evidence_text: Mapped[str | None] = mapped_column(Text)
    normalized_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    source_url: Mapped[str] = mapped_column(String(1200), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True, slots=True)
class ParsedInternetClaim:
    evidence_kind: str
    availability_status: str | None = None
    claim_semantics: str | None = None
    provider_name: str | None = None
    technology: str | None = None
    max_download_mbps: int | None = None
    max_upload_mbps: int | None = None
    evidence_text: str | None = None

    @property
    def evidence_key(self) -> str:
        material = json.dumps(
            {
                "kind": self.evidence_kind,
                "availability": self.availability_status,
                "semantics": self.claim_semantics,
                "provider": self.provider_name,
                "technology": self.technology,
                "download": self.max_download_mbps,
                "upload": self.max_upload_mbps,
                "text": self.evidence_text,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(material).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class ParsedInternetDetail:
    claims: tuple[ParsedInternetClaim, ...] = ()
    source_address: str | None = None
    address_precision: str | None = None
    normalized_payload: dict[str, Any] | None = None

    @property
    def has_evidence(self) -> bool:
        return bool(self.claims or self.source_address)


@dataclass(frozen=True, slots=True)
class InternetSourceEvidence:
    property_id: int
    property_listing_id: int
    source_name: str
    source_url: str
    evidence_kind: str
    availability_status: str | None
    claim_semantics: str | None
    provider_name: str | None
    technology: str | None
    max_download_mbps: int | None
    max_upload_mbps: int | None
    source_address: str | None
    address_precision: str | None
    evidence_text: str | None
    observed_at: datetime

    @property
    def kind_label_de(self) -> str:
        if self.evidence_kind == EVIDENCE_PORTAL_ADDRESS_ESTIMATE:
            return "Portal-Schätzung"
        if self.evidence_kind == EVIDENCE_LISTING_CLAIM:
            return "Angabe im Exposé"
        if self.evidence_kind == EVIDENCE_SOURCE_ADDRESS:
            return "Quelladresse"
        return "Quellenangabe"

    @property
    def speed_label_de(self) -> str | None:
        if self.max_download_mbps is None:
            return None
        prefix = self.technology or "Festnetz"
        return f"{prefix} bis {self.max_download_mbps} Mbit/s"

    @property
    def rank(self) -> tuple[int, int, int, int]:
        kind_rank = {
            EVIDENCE_PORTAL_ADDRESS_ESTIMATE: 300,
            EVIDENCE_LISTING_CLAIM: 200,
            EVIDENCE_SOURCE_ADDRESS: 50,
        }.get(self.evidence_kind, 0)
        availability_rank = {
            "connected": 4,
            "available": 3,
            "at_property": 2,
            "planned": 1,
            "unavailable": 0,
        }.get(self.availability_status or "", 0)
        return (
            kind_rank,
            1 if self.max_download_mbps is not None else 0,
            availability_rank,
            self.max_download_mbps or 0,
        )


class _VisibleHtml(HTMLParser):
    _BLOCKS = frozenset({
        "address",
        "article",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "h1",
        "h2",
        "h3",
        "h4",
        "li",
        "p",
        "section",
        "tr",
    })

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0
        self._json_ld_depth = 0
        self._json_ld_parts: list[str] = []
        self.json_ld_documents: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if tag in {"style", "noscript", "template"}:
            self._hidden_depth += 1
            return
        if tag == "script":
            script_type = attributes.get("type", "").casefold()
            if script_type == "application/ld+json":
                self._json_ld_depth += 1
                self._json_ld_parts = []
            else:
                self._hidden_depth += 1
            return
        if not self._hidden_depth and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"style", "noscript", "template"}:
            self._hidden_depth = max(0, self._hidden_depth - 1)
            return
        if tag == "script":
            if self._json_ld_depth:
                self._json_ld_depth -= 1
                value = "".join(self._json_ld_parts).strip()
                if value:
                    self.json_ld_documents.append(value)
                self._json_ld_parts = []
            else:
                self._hidden_depth = max(0, self._hidden_depth - 1)
            return
        if not self._hidden_depth and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._json_ld_depth:
            self._json_ld_parts.append(data)
            return
        if self._hidden_depth:
            return
        if data.strip():
            self.parts.append(data)

    @property
    def lines(self) -> tuple[str, ...]:
        text = "".join(self.parts).replace("\xa0", " ")
        return tuple(
            line
            for raw in text.splitlines()
            if (line := " ".join(raw.split()))
        )


def _clean_token(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.replace("_", " ").split()).strip()
    if not cleaned or cleaned.casefold() in {"no_information", "null", "none", "unknown"}:
        return None
    return cleaned


def _localized_speed(value: str | None) -> int | None:
    if not value:
        return None
    match = _SPEED_RE.search(value)
    if match is None:
        token = value.strip()
    else:
        token = match.group("speed")
    token = token.replace(" ", "")
    if "." in token and "," not in token:
        parts = token.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            token = "".join(parts)
    token = token.replace(",", ".")
    try:
        speed = float(token)
    except ValueError:
        return None
    if speed <= 0 or speed > 100_000:
        return None
    return round(speed)


def _json_scalar(text: str, key: str) -> str | bool | None:
    match = re.search(
        rf'"{re.escape(key)}"\s*:\s*'
        rf'(?:"(?P<quoted>[^"\\]*(?:\\.[^"\\]*)*)"|'
        rf'(?P<bool>true|false)|(?P<null>null)|(?P<number>-?\d+(?:\.\d+)?))',
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    if match.group("quoted") is not None:
        return match.group("quoted").replace(r"\u0026", "&").replace(r"\/", "/")
    if match.group("bool") is not None:
        return match.group("bool").casefold() == "true"
    if match.group("number") is not None:
        return match.group("number")
    return None


def _normalize_technology(value: str | None) -> str | None:
    cleaned = _clean_token(value)
    if not cleaned:
        return None
    token = re.sub(r"[^a-z0-9]+", "", cleaned.casefold())
    if token.startswith("glasfaser"):
        return "Glasfaser"
    if token.startswith("kabel"):
        return "Kabel"
    if token in {"svvdsl", "svdsl"}:
        return "SVVDSL"
    if token == "vdsl":
        return "VDSL"
    if token == "dsl":
        return "DSL"
    if token == "hybrid":
        return "Hybrid"
    return _TECHNOLOGY_LABELS.get(token, cleaned[:48])


def _known_provider(segment: str) -> str | None:
    folded = segment.casefold()
    for provider in _KNOWN_PROVIDERS:
        if provider.casefold() in folded:
            return "PYUR" if provider == "PŸUR" else provider
    return None


def _compact_evidence_text(value: str) -> str:
    return " ".join(value.split())[:500]


def _source_address_from_json_ld(documents: list[str]) -> tuple[str | None, str | None]:
    def visit(value: Any) -> tuple[str | None, str | None]:
        if isinstance(value, dict):
            if str(value.get("@type") or "").casefold() == "postaladdress":
                street = _clean_token(str(value.get("streetAddress") or ""))
                postal = _clean_token(str(value.get("postalCode") or ""))
                locality = _clean_token(str(value.get("addressLocality") or ""))
                if street and re.search(r"\d", street):
                    suffix = " ".join(part for part in (postal, locality) if part)
                    address = f"{street}, {suffix}" if suffix else street
                    return address, ADDRESS_STREET_HOUSE_NUMBER
            for item in value.values():
                result = visit(item)
                if result[0]:
                    return result
        elif isinstance(value, list):
            for item in value:
                result = visit(item)
                if result[0]:
                    return result
        return None, None

    for document in documents:
        try:
            value = json.loads(document)
        except (TypeError, ValueError):
            continue
        address, precision = visit(value)
        if address:
            return address, precision
    return None, None


def parse_immoscout_de_internet_evidence(url: str, body: str) -> ParsedInternetDetail:
    host = (urlparse(url).hostname or "").casefold()
    if host not in IMMOSCOUT_DE_HOSTS:
        return ParsedInternetDetail()

    available_raw = _json_scalar(body, "obj_telekomInternetAvailable")
    if isinstance(available_raw, str) and available_raw.casefold() in {"true", "false"}:
        available_raw = available_raw.casefold() == "true"
    speed_raw = _clean_token(
        str(_json_scalar(body, "obj_telekomInternetSpeed") or "")
    )
    speed = _localized_speed(speed_raw)

    street = _clean_token(str(_json_scalar(body, "obj_street") or ""))
    house_number = _clean_token(str(_json_scalar(body, "obj_houseNumber") or ""))
    postal_code = _clean_token(str(_json_scalar(body, "obj_zipCode") or ""))
    locality = _clean_token(str(_json_scalar(body, "obj_regio3") or ""))

    source_address = None
    address_precision = None
    if street and house_number:
        locality_part = " ".join(part for part in (postal_code, locality) if part)
        source_address = f"{street} {house_number}"
        if locality_part:
            source_address += f", {locality_part}"
        address_precision = ADDRESS_STREET_HOUSE_NUMBER

    claims: list[ParsedInternetClaim] = []
    if isinstance(available_raw, bool) or speed is not None:
        technology = None
        # The structured speed field itself does not consistently name the access
        # technology. Only promote Glasfaser when the rendered Internet block says so.
        parser = _VisibleHtml()
        parser.feed(body)
        rendered = " ".join(parser.lines)
        if re.search(
            r"Internet\s+Geschwindigkeit.{0,1200}?Glasfaser-Internet",
            rendered,
            re.IGNORECASE,
        ):
            technology = "Glasfaser"
        availability = (
            "available"
            if speed is not None or available_raw is True
            else "unavailable"
            if available_raw is False
            else None
        )
        claims.append(
            ParsedInternetClaim(
                evidence_kind=EVIDENCE_PORTAL_ADDRESS_ESTIMATE,
                availability_status=availability,
                claim_semantics="non_binding_address_estimate",
                provider_name="Telekom",
                technology=technology,
                max_download_mbps=speed,
                evidence_text=(
                    f"Telekom portal estimate: {speed_raw}"
                    if speed_raw
                    else "Telekom portal availability flag"
                ),
            )
        )

    payload = {
        "telekom_internet_available": (
            available_raw if isinstance(available_raw, bool) else None
        ),
        "telekom_internet_speed_raw": speed_raw,
        "source_address_fields": {
            "street": street,
            "house_number": house_number,
            "postal_code": postal_code,
            "locality": locality,
        },
    }
    return ParsedInternetDetail(
        claims=tuple(claims),
        source_address=source_address,
        address_precision=address_precision,
        normalized_payload=payload,
    )


def _segment_upload_speed(segment: str, download_speed: int | None) -> int | None:
    lowered = segment.casefold()
    upload_pos = lowered.find("upload")
    if upload_pos < 0:
        return None
    for match in _SPEED_RE.finditer(segment[upload_pos:]):
        speed = _localized_speed(match.group(0))
        if speed is not None and speed != download_speed:
            return speed
    return None


def _immowelt_claims_from_line(line: str) -> list[ParsedInternetClaim]:
    if "mbit/s" not in line.casefold():
        return []

    claims: list[ParsedInternetClaim] = []
    seen: set[tuple[str | None, str | None, int | None, int | None]] = set()

    def add(
        *,
        provider: str | None,
        technology: str | None,
        download: int | None,
        upload: int | None,
    ) -> None:
        key = (provider, technology, download, upload)
        if key in seen or download is None:
            return
        seen.add(key)
        semantics = (
            "availability_check"
            if re.search(r"Verfügbarkeits(?:check|prüfung)|laut\s+Verfügbarkeit", line, re.IGNORECASE)
            else "listing_statement"
        )
        claims.append(
            ParsedInternetClaim(
                evidence_kind=EVIDENCE_LISTING_CLAIM,
                availability_status="available",
                claim_semantics=semantics,
                provider_name=provider,
                technology=technology,
                max_download_mbps=download,
                max_upload_mbps=upload,
                evidence_text=_compact_evidence_text(line),
            )
        )

    for match in _PROVIDER_TECH_SPEED_RE.finditer(line):
        provider = _clean_token(match.group("provider"))
        technology = _normalize_technology(match.group("tech"))
        download = _localized_speed(match.group("speed"))
        add(
            provider=provider,
            technology=technology,
            download=download,
            upload=_segment_upload_speed(line, download),
        )

    for pattern in (_TECH_SPEED_RE, _SPEED_TECH_RE):
        for match in pattern.finditer(line):
            technology = _normalize_technology(match.group("tech"))
            download = _localized_speed(match.group("speed"))
            add(
                provider=_known_provider(line),
                technology=technology,
                download=download,
                upload=_segment_upload_speed(line, download),
            )

    return claims


def parse_immowelt_de_internet_evidence(url: str, body: str) -> ParsedInternetDetail:
    host = (urlparse(url).hostname or "").casefold()
    if host not in IMMOWELT_DE_HOSTS:
        return ParsedInternetDetail()

    parser = _VisibleHtml()
    parser.feed(body)
    source_address, address_precision = _source_address_from_json_ld(
        parser.json_ld_documents
    )

    claims: list[ParsedInternetClaim] = []
    claim_keys: set[str] = set()
    internet_lines: list[str] = []
    for line in parser.lines:
        if not re.search(r"Internet|DSL|VDSL|Kabel|Glasfaser|MBit/s", line, re.IGNORECASE):
            continue
        internet_lines.append(line)
        for claim in _immowelt_claims_from_line(line):
            if claim.evidence_key not in claim_keys:
                claim_keys.add(claim.evidence_key)
                claims.append(claim)

        fiber_status: tuple[str, str] | None = None
        if _CONNECTED_FIBER_RE.search(line):
            fiber_status = ("connected", "listing_connection_claim")
        elif _PROPERTY_FIBER_RE.search(line):
            fiber_status = ("at_property", "listing_property_boundary_claim")
        elif _PLANNED_FIBER_RE.search(line):
            fiber_status = ("planned", "listing_planned_claim")
        if fiber_status is not None:
            status, semantics = fiber_status
            claim = ParsedInternetClaim(
                evidence_kind=EVIDENCE_LISTING_CLAIM,
                availability_status=status,
                claim_semantics=semantics,
                provider_name=_known_provider(line),
                technology="Glasfaser",
                evidence_text=_compact_evidence_text(line),
            )
            if claim.evidence_key not in claim_keys:
                claim_keys.add(claim.evidence_key)
                claims.append(claim)

    return ParsedInternetDetail(
        claims=tuple(claims),
        source_address=source_address,
        address_precision=address_precision,
        normalized_payload={
            "internet_lines": internet_lines[:20],
            "claim_count": len(claims),
        },
    )


def replace_listing_internet_source_evidence(
    session: Session,
    *,
    listing: PropertyListing,
    source_name: str,
    parsed: ParsedInternetDetail,
    observed_at: datetime | None = None,
) -> int:
    """Replace the successful parse result for one listing atomically in the caller tx."""

    session.execute(
        delete(PropertyInternetSourceEvidence).where(
            PropertyInternetSourceEvidence.property_listing_id == listing.id
        )
    )
    observed = observed_at or datetime.now(UTC)
    claims = list(parsed.claims)
    if parsed.source_address and not claims:
        claims.append(
            ParsedInternetClaim(
                evidence_kind=EVIDENCE_SOURCE_ADDRESS,
                availability_status=None,
                claim_semantics="source_address_only",
                evidence_text=parsed.source_address,
            )
        )

    for claim in claims:
        session.add(
            PropertyInternetSourceEvidence(
                property_id=listing.property_id,
                property_listing_id=listing.id,
                source_name=source_name,
                country_code="DE",
                evidence_key=claim.evidence_key,
                evidence_kind=claim.evidence_kind,
                availability_status=claim.availability_status,
                claim_semantics=claim.claim_semantics,
                provider_name=claim.provider_name,
                technology=claim.technology,
                max_download_mbps=claim.max_download_mbps,
                max_upload_mbps=claim.max_upload_mbps,
                source_address=parsed.source_address,
                address_precision=parsed.address_precision,
                evidence_text=claim.evidence_text,
                normalized_payload=dict(parsed.normalized_payload or {}),
                source_url=listing.url,
                observed_at=observed,
            )
        )
    return len(claims)


def load_property_internet_source_evidence(
    session: Session,
    property_ids: set[int],
) -> dict[int, tuple[InternetSourceEvidence, ...]]:
    if not property_ids:
        return {}

    rows = session.execute(
        select(
            PropertyInternetSourceEvidence,
            Source.name,
        )
        .join(
            PropertyListing,
            PropertyListing.id == PropertyInternetSourceEvidence.property_listing_id,
        )
        .join(Source, Source.id == PropertyListing.source_id)
        .where(
            PropertyInternetSourceEvidence.property_id.in_(property_ids),
            PropertyInternetSourceEvidence.country_code == "DE",
        )
        .order_by(
            PropertyInternetSourceEvidence.property_id,
            PropertyInternetSourceEvidence.observed_at.desc(),
            PropertyInternetSourceEvidence.id,
        )
    )

    grouped: dict[int, list[InternetSourceEvidence]] = {}
    for row, current_source_name in rows:
        item = InternetSourceEvidence(
            property_id=row.property_id,
            property_listing_id=row.property_listing_id,
            source_name=current_source_name or row.source_name,
            source_url=row.source_url,
            evidence_kind=row.evidence_kind,
            availability_status=row.availability_status,
            claim_semantics=row.claim_semantics,
            provider_name=row.provider_name,
            technology=row.technology,
            max_download_mbps=row.max_download_mbps,
            max_upload_mbps=row.max_upload_mbps,
            source_address=row.source_address,
            address_precision=row.address_precision,
            evidence_text=row.evidence_text,
            observed_at=row.observed_at,
        )
        grouped.setdefault(row.property_id, []).append(item)

    return {
        property_id: tuple(sorted(values, key=lambda item: item.rank, reverse=True))
        for property_id, values in grouped.items()
    }


def primary_property_internet_source_evidence(
    evidence: tuple[InternetSourceEvidence, ...],
) -> InternetSourceEvidence | None:
    return next(
        (
            item
            for item in evidence
            if item.max_download_mbps is not None
            or item.availability_status in {"connected", "available", "at_property"}
        ),
        None,
    )


@dataclass(frozen=True, slots=True)
class InternetEvidenceBundle:
    source_claims: tuple[InternetSourceEvidence, ...]
    official_grid: InternetAccess | None

    @property
    def primary_source(self) -> InternetSourceEvidence | None:
        return primary_property_internet_source_evidence(self.source_claims)


def load_property_internet_evidence_bundles(
    session: Session,
    property_ids: set[int],
) -> dict[int, InternetEvidenceBundle]:
    from app.internet_access import load_property_internet_access

    source = load_property_internet_source_evidence(session, property_ids)
    official = load_property_internet_access(session, property_ids)
    return {
        property_id: InternetEvidenceBundle(
            source_claims=source.get(property_id, ()),
            official_grid=official.get(property_id),
        )
        for property_id in property_ids
    }


def fixed_minimum_evidence_established(
    bundle: InternetEvidenceBundle | None,
    minimum_download_mbps: int | None,
) -> bool:
    if bundle is None:
        return False

    if minimum_download_mbps is None:
        if any(
            item.availability_status in {"available", "connected", "at_property"}
            or item.max_download_mbps is not None
            for item in bundle.source_claims
        ):
            return True
        return bool(
            bundle.official_grid
            and bundle.official_grid.max_any_download_mbps is not None
        )

    if any(
        item.max_download_mbps is not None
        and item.max_download_mbps >= minimum_download_mbps
        and item.availability_status != "unavailable"
        for item in bundle.source_claims
    ):
        return True
    return bool(
        bundle.official_grid
        and bundle.official_grid.minimum_established(minimum_download_mbps)
    )


def starlink_fallback_reason_for_bundle(
    bundle: InternetEvidenceBundle | None,
    *,
    minimum_download_mbps: int | None,
) -> str | None:
    if fixed_minimum_evidence_established(bundle, minimum_download_mbps):
        return None
    if bundle is None:
        return "fixed_unknown"

    has_positive_source = any(
        item.availability_status in {"available", "connected", "at_property"}
        or item.max_download_mbps is not None
        for item in bundle.source_claims
    )
    has_official = bool(
        bundle.official_grid
        and bundle.official_grid.max_any_download_mbps is not None
    )
    if not has_positive_source and not has_official:
        return "fixed_unknown"
    return "minimum_not_established"
