from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    and_,
    false,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.country_scope import DEFAULT_COUNTRY, selected_country
from app.database import Base
from app.hospital_access import (
    hospital_distance_rejection_condition,
    load_confirmed_emergency_access,
)
from app.models import ListingStatus, Property, PropertyListing, Source
from app.property_acquisition import property_budget_limits
from app.property_visibility import product_visible_property_condition

_MASK_RE = re.compile(r"^[0-9xX]{5}$")
_SPLIT_RE = re.compile(r"[\s,;]+")
_SOURCE_REASON_LABELS = {
    "auction": "Versteigerung",
    "price_above_max": "Preis über Budget",
    "price_below_min": "Preis unter Mindestbudget",
    "price_unknown": "Preis unbekannt",
    "source_url_missing": "Originalanzeige fehlt",
    "source_dead": "Quelle nicht mehr erreichbar",
    "source_liveness_unverified": "Quellenstatus ungeprüft",
    "source_policy": "Quellenregel abgelehnt",
}


class CandidateHousePolicy(Base):
    """Profile-scoped local house suitability rules.

    These rules never mutate source lifecycle state. They only decide whether an otherwise
    current canonical property belongs in the normal father-facing catalogue or in the
    rejected/filtered view.
    """

    __tablename__ = "candidate_house_policies"
    __table_args__ = (Index("ix_candidate_house_policies_profile_id", "profile_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    de_plz_blacklist: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    max_hospital_distance_km: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    hospital_distance_fail_closed: Mapped[bool] = mapped_column(default=False, nullable=False)
    min_internet_download_mbps: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


@dataclass(frozen=True, slots=True)
class HouseSuitabilityPolicy:
    de_plz_blacklist: tuple[str, ...] = ()
    max_hospital_distance_km: Decimal | None = None
    hospital_distance_fail_closed: bool = False
    min_internet_download_mbps: int | None = None


@dataclass(frozen=True, slots=True)
class HouseRejectionReason:
    code: str
    label_de: str


def parse_de_plz_blacklist(raw: str) -> tuple[str, ...]:
    """Normalize exact German PLZ values and x/X single-digit masks."""
    tokens = [token for token in _SPLIT_RE.split(raw.strip()) if token]
    normalized: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        mask = token.casefold()
        if not _MASK_RE.fullmatch(mask):
            raise ValueError(
                f"Ungültige PLZ-Sperrregel „{token}“. Erlaubt sind genau fünf Stellen "
                "aus Ziffern und x, z. B. 01067 oder 0xxxx."
            )
        if mask in seen:
            continue
        seen.add(mask)
        normalized.append(mask)
    return tuple(normalized)


def format_de_plz_blacklist(masks: tuple[str, ...]) -> str:
    return "\n".join(masks)


def load_house_suitability_policy(session: Session, profile_id: int) -> HouseSuitabilityPolicy:
    row = session.scalar(
        select(CandidateHousePolicy).where(CandidateHousePolicy.profile_id == profile_id)
    )
    if row is None:
        return HouseSuitabilityPolicy()
    return HouseSuitabilityPolicy(
        de_plz_blacklist=tuple(str(value).casefold() for value in (row.de_plz_blacklist or [])),
        max_hospital_distance_km=row.max_hospital_distance_km,
        hospital_distance_fail_closed=bool(row.hospital_distance_fail_closed),
        min_internet_download_mbps=row.min_internet_download_mbps,
    )


def save_de_plz_blacklist(
    session: Session,
    profile_id: int,
    raw: str,
    *,
    commit: bool = True,
) -> HouseSuitabilityPolicy:
    masks = parse_de_plz_blacklist(raw)
    row = session.scalar(
        select(CandidateHousePolicy).where(CandidateHousePolicy.profile_id == profile_id)
    )
    if row is None:
        row = CandidateHousePolicy(profile_id=profile_id, de_plz_blacklist=list(masks))
        session.add(row)
    else:
        row.de_plz_blacklist = list(masks)
    if commit:
        session.commit()
    return load_house_suitability_policy(session, profile_id)


def _parse_hospital_distance(raw: str) -> Decimal | None:
    normalized = raw.strip().replace(",", ".")
    if not normalized:
        return None
    try:
        value = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError("Ungültige Krankenhausentfernung.") from exc
    if value <= 0 or value > Decimal(250):
        raise ValueError("Krankenhausentfernung muss zwischen 0 und 250 km liegen.")
    return value.quantize(Decimal("0.01"))


def save_hospital_distance_policy(
    session: Session,
    profile_id: int,
    raw_distance_km: str,
    *,
    fail_closed: bool,
    commit: bool = True,
) -> HouseSuitabilityPolicy:
    max_distance = _parse_hospital_distance(raw_distance_km)
    row = session.scalar(
        select(CandidateHousePolicy).where(CandidateHousePolicy.profile_id == profile_id)
    )
    if row is None:
        row = CandidateHousePolicy(
            profile_id=profile_id,
            de_plz_blacklist=[],
            max_hospital_distance_km=max_distance,
            hospital_distance_fail_closed=fail_closed,
        )
        session.add(row)
    else:
        row.max_hospital_distance_km = max_distance
        row.hospital_distance_fail_closed = fail_closed
    if commit:
        session.commit()
    return load_house_suitability_policy(session, profile_id)





_INTERNET_SPEEDS = frozenset({10, 16, 30, 50, 100, 200, 400, 1000})


def save_internet_policy(
    session: Session,
    profile_id: int,
    raw_minimum_mbps: str,
    *,
    commit: bool = True,
) -> HouseSuitabilityPolicy:
    normalized = raw_minimum_mbps.strip()
    minimum: int | None = None
    if normalized:
        try:
            minimum = int(normalized)
        except ValueError as exc:
            raise ValueError("Ungültige Internet-Mindestgeschwindigkeit.") from exc
        if minimum not in _INTERNET_SPEEDS:
            raise ValueError(
                "Internet-Mindestgeschwindigkeit muss 10, 16, 30, 50, 100, "
                "200, 400 oder 1000 Mbit/s sein."
            )

    row = session.scalar(
        select(CandidateHousePolicy).where(CandidateHousePolicy.profile_id == profile_id)
    )
    if row is None:
        row = CandidateHousePolicy(
            profile_id=profile_id,
            de_plz_blacklist=[],
            min_internet_download_mbps=minimum,
        )
        session.add(row)
    else:
        row.min_internet_download_mbps = minimum
    if commit:
        session.commit()
    return load_house_suitability_policy(session, profile_id)


def active_internet_policy(policy: HouseSuitabilityPolicy) -> int | None:
    if (selected_country() or DEFAULT_COUNTRY) != "DE":
        return None
    return policy.min_internet_download_mbps


def active_de_plz_blacklist(policy: HouseSuitabilityPolicy) -> tuple[str, ...]:
    return policy.de_plz_blacklist if (selected_country() or DEFAULT_COUNTRY) == "DE" else ()


def active_hospital_distance_policy(
    policy: HouseSuitabilityPolicy,
) -> tuple[Decimal | None, bool]:
    if (selected_country() or DEFAULT_COUNTRY) != "DE":
        return None, False
    return policy.max_hospital_distance_km, policy.hospital_distance_fail_closed


def matches_de_plz_blacklist(postal_code: str | None, masks: tuple[str, ...]) -> bool:
    if postal_code is None or not re.fullmatch(r"\d{5}", postal_code):
        return False
    return any(
        all(mask_char == "x" or mask_char == value for mask_char, value in zip(mask, postal_code, strict=True))
        for mask in masks
    )


def plz_blacklist_property_condition(masks: tuple[str, ...]):
    if not masks:
        return false()
    comparisons = []
    for mask in masks:
        if "x" in mask:
            comparisons.append(Property.postal_code.like(mask.replace("x", "_")))
        else:
            comparisons.append(Property.postal_code == mask)
    return and_(Property.postal_code.is_not(None), or_(*comparisons))


def accepted_property_condition(
    masks: tuple[str, ...] = (),
    *,
    max_hospital_distance_km: Decimal | None = None,
    hospital_fail_closed: bool = False,
):
    conditions = [product_visible_property_condition()]
    if masks:
        conditions.append(~plz_blacklist_property_condition(masks))
    hospital_rejected = hospital_distance_rejection_condition(
        max_hospital_distance_km,
        fail_closed=hospital_fail_closed,
    )
    if hospital_rejected is not None:
        conditions.append(~hospital_rejected)
    return and_(*conditions)


def rejected_property_condition(
    masks: tuple[str, ...] = (),
    *,
    max_hospital_distance_km: Decimal | None = None,
    hospital_fail_closed: bool = False,
):
    conditions = [~product_visible_property_condition()]
    if masks:
        conditions.append(plz_blacklist_property_condition(masks))
    hospital_rejected = hospital_distance_rejection_condition(
        max_hospital_distance_km,
        fail_closed=hospital_fail_closed,
    )
    if hospital_rejected is not None:
        conditions.append(hospital_rejected)
    return or_(*conditions)


def _reason(
    code: str,
    *,
    postal_code: str | None = None,
    hospital_distance_km: float | None = None,
    hospital_limit_km: Decimal | None = None,
) -> HouseRejectionReason:
    if code == "plz_blacklist":
        location = f" {postal_code}" if postal_code else ""
        return HouseRejectionReason(code=code, label_de=f"PLZ{location} auf Sperrliste")
    if code == "hospital_too_far" and hospital_limit_km is not None:
        distance = (
            f"{hospital_distance_km:.1f} km"
            if hospital_distance_km is not None
            else "außerhalb des Limits"
        )
        return HouseRejectionReason(
            code=code,
            label_de=(
                f"Notfallversorgung {distance} · Limit {hospital_limit_km:g} km Luftlinie"
            ),
        )
    if code == "hospital_unknown":
        return HouseRejectionReason(
            code=code,
            label_de="Notfallversorgung unbekannt · Fail-closed aktiv",
        )
    return HouseRejectionReason(
        code=code,
        label_de=_SOURCE_REASON_LABELS.get(code, "Lokale Auswahlregel"),
    )


def rejection_reasons_for_property(
    property_row: Property,
    *,
    country_code: str,
    plz_blacklist: tuple[str, ...],
    source_payloads: tuple[dict, ...] = (),
    max_hospital_distance_km: Decimal | None = None,
    hospital_fail_closed: bool = False,
    hospital_distance_km: float | None = None,
) -> tuple[HouseRejectionReason, ...]:
    """Derive explainable reasons without changing canonical/source lifecycle state."""
    codes: list[str] = []

    minimum, maximum = property_budget_limits(country_code)
    price: Decimal | None = property_row.price_eur
    if price is None:
        codes.append("price_unknown")
    elif price < minimum:
        codes.append("price_below_min")
    elif price > maximum:
        codes.append("price_above_max")

    if country_code == "DE" and "versteigerung" in (property_row.title or "").casefold():
        codes.append("auction")

    has_accepted_source = any(payload.get("product_visible") is True for payload in source_payloads)
    if not has_accepted_source:
        for payload in source_payloads:
            raw_reasons = payload.get("product_visibility_reasons")
            if isinstance(raw_reasons, list):
                codes.extend(str(value) for value in raw_reasons if value and value != "accepted")
            else:
                value = payload.get("product_visibility_reason")
                if value and value != "accepted":
                    codes.append(str(value))

    if country_code == "DE" and matches_de_plz_blacklist(
        property_row.postal_code,
        plz_blacklist,
    ):
        codes.append("plz_blacklist")

    if country_code == "DE" and max_hospital_distance_km is not None:
        if hospital_distance_km is None:
            if hospital_fail_closed:
                codes.append("hospital_unknown")
        elif hospital_distance_km > float(max_hospital_distance_km):
            codes.append("hospital_too_far")

    unique: list[str] = []
    for code in codes:
        if code not in unique:
            unique.append(code)
    if not unique:
        unique.append("source_policy")
    return tuple(
        _reason(
            code,
            postal_code=property_row.postal_code,
            hospital_distance_km=hospital_distance_km,
            hospital_limit_km=max_hospital_distance_km,
        )
        for code in unique
    )


def load_property_rejection_reasons(
    session: Session,
    properties: list[Property],
    plz_blacklist: tuple[str, ...],
    *,
    max_hospital_distance_km: Decimal | None = None,
    hospital_fail_closed: bool = False,
) -> dict[int, tuple[HouseRejectionReason, ...]]:
    if not properties:
        return {}

    country_code = selected_country() or DEFAULT_COUNTRY
    ids = {row.id for row in properties}
    source_country = func.upper(
        func.coalesce(Source.config["country_code"].astext, DEFAULT_COUNTRY)
    )
    payloads: dict[int, list[dict]] = {property_id: [] for property_id in ids}
    for property_id, payload in session.execute(
        select(PropertyListing.property_id, PropertyListing.raw_payload)
        .join(Source, Source.id == PropertyListing.source_id)
        .where(
            PropertyListing.property_id.in_(ids),
            PropertyListing.status == ListingStatus.ACTIVE,
            source_country == country_code,
        )
    ):
        if isinstance(payload, dict):
            payloads[int(property_id)].append(payload)

    hospital_access = load_confirmed_emergency_access(
        session,
        ids,
        country_code=country_code,
    )
    return {
        row.id: rejection_reasons_for_property(
            row,
            country_code=country_code,
            plz_blacklist=plz_blacklist,
            source_payloads=tuple(payloads.get(row.id, ())),
            max_hospital_distance_km=max_hospital_distance_km,
            hospital_fail_closed=hospital_fail_closed,
            hospital_distance_km=(
                hospital_access[row.id].air_distance_km if row.id in hospital_access else None
            ),
        )
        for row in properties
    }
