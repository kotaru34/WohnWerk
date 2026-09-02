from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import PostalCode

RTR_POSTAL_CODES_URL = "https://data.rtr.at/api/v1/tables/plz.json?size=0"


@dataclass(frozen=True, slots=True)
class PostalCodeRecord:
    postal_code: str
    name: str


def parse_rtr_postal_codes(payload: dict[str, Any]) -> list[PostalCodeRecord]:
    """Return current addressable Austrian postal codes from an RTR API payload."""
    by_code: dict[str, PostalCodeRecord] = {}

    for row in payload.get("data", []):
        if str(row.get("adressierbar", "")).strip().casefold() != "ja":
            continue

        raw_code = str(row.get("plz", "")).strip()
        if not raw_code.isdigit():
            continue

        postal_code = raw_code.zfill(4)
        if len(postal_code) != 4:
            continue

        name = str(row.get("ort", "")).strip()
        if not name:
            continue

        by_code[postal_code] = PostalCodeRecord(postal_code=postal_code, name=name)

    return [by_code[code] for code in sorted(by_code)]


def fetch_rtr_postal_codes(timeout_seconds: float = 30.0) -> list[PostalCodeRecord]:
    response = httpx.get(RTR_POSTAL_CODES_URL, timeout=timeout_seconds)
    response.raise_for_status()
    return parse_rtr_postal_codes(response.json())


def upsert_postal_codes(session: Session, records: list[PostalCodeRecord]) -> int:
    """Insert/update RTR names while deliberately preserving later geo enrichment."""
    if not records:
        return 0

    values = [
        {
            "postal_code": record.postal_code,
            "name": record.name,
            "source": "RTR",
        }
        for record in records
    ]

    statement = insert(PostalCode).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=[PostalCode.postal_code],
        set_={
            "name": statement.excluded.name,
            "source": statement.excluded.source,
        },
    )
    session.execute(statement)
    session.commit()
    return len(records)
