from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from io import BytesIO, TextIOWrapper
from zipfile import BadZipFile, ZipFile

import httpx
from geoalchemy2.elements import WKTElement
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import PostalCode

GEONAMES_DE_POSTAL_URL = "https://download.geonames.org/export/zip/DE.zip"
GEONAMES_SOURCE = "GeoNames"
GEONAMES_LOCATION_SOURCE = "GeoNames DE postal code dump"
GEONAMES_LOCATION_METHOD = "postal_place_mean"
GEONAMES_UPSERT_BATCH_SIZE = 1000


@dataclass(frozen=True, slots=True)
class GermanPostalCodeRecord:
    postal_code: str
    name: str
    longitude: float
    latitude: float
    sample_count: int


def parse_geonames_de_postal_zip(payload: bytes) -> list[GermanPostalCodeRecord]:
    """Parse GeoNames' DE postal export into one approximate centroid per PLZ.

    GeoNames may contain multiple place rows for a postal code. WohnWerk keeps
    the most common place label and averages all valid supplied WGS84 points.
    These are postal-area approximations, not street-accurate coordinates.
    """
    try:
        archive = ZipFile(BytesIO(payload))
    except BadZipFile as exc:
        raise ValueError("Invalid GeoNames DE postal ZIP") from exc

    with archive:
        candidates = [
            name for name in archive.namelist() if name.casefold().endswith("de.txt")
        ]
        if not candidates:
            raise ValueError("GeoNames DE postal ZIP contains no DE.txt")
        member = min(candidates, key=len)
        with archive.open(member, "r") as binary:
            handle = TextIOWrapper(binary, encoding="utf-8", newline="")
            reader = csv.reader(handle, delimiter="\t")
            points: dict[str, list[tuple[float, float]]] = defaultdict(list)
            names: dict[str, Counter[str]] = defaultdict(Counter)

            for row in reader:
                if len(row) < 11 or row[0].strip().upper() != "DE":
                    continue
                postal_code = row[1].strip()
                if len(postal_code) != 5 or not postal_code.isdigit():
                    continue
                name = row[2].strip()
                try:
                    latitude = float(row[9])
                    longitude = float(row[10])
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(latitude) or not math.isfinite(longitude):
                    continue
                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    continue

                points[postal_code].append((longitude, latitude))
                if name:
                    names[postal_code][name] += 1

    records: list[GermanPostalCodeRecord] = []
    for postal_code in sorted(points):
        samples = points[postal_code]
        if not samples:
            continue
        longitude = sum(point[0] for point in samples) / len(samples)
        latitude = sum(point[1] for point in samples) / len(samples)
        label_counts = names.get(postal_code)
        name = (
            min(
                label_counts.items(),
                key=lambda item: (-item[1], item[0].casefold()),
            )[0]
            if label_counts
            else postal_code
        )
        records.append(
            GermanPostalCodeRecord(
                postal_code=postal_code,
                name=name,
                longitude=longitude,
                latitude=latitude,
                sample_count=len(samples),
            )
        )
    return records


def fetch_geonames_de_postal_codes(
    timeout_seconds: float = 60.0,
) -> list[GermanPostalCodeRecord]:
    response = httpx.get(
        GEONAMES_DE_POSTAL_URL,
        timeout=timeout_seconds,
        follow_redirects=True,
    )
    response.raise_for_status()
    return parse_geonames_de_postal_zip(response.content)


def upsert_german_postal_codes(
    session: Session,
    records: list[GermanPostalCodeRecord],
) -> int:
    if not records:
        return 0

    values = [
        {
            "postal_code": record.postal_code,
            "name": record.name,
            "location": WKTElement(
                f"POINT({record.longitude:.8f} {record.latitude:.8f})",
                srid=4326,
            ),
            "source": GEONAMES_SOURCE,
            "location_source": GEONAMES_LOCATION_SOURCE,
            "location_method": GEONAMES_LOCATION_METHOD,
            "location_sample_count": record.sample_count,
        }
        for record in records
    ]

    # PostgreSQL/DBAPI protocols have finite bind-parameter limits.  Building one
    # multi-VALUES ON CONFLICT statement for the full German PLZ dump creates tens
    # of thousands of binds, so keep each statement deliberately bounded while
    # retaining one transaction and one commit for all-or-nothing import semantics.
    for start in range(0, len(values), GEONAMES_UPSERT_BATCH_SIZE):
        batch = values[start : start + GEONAMES_UPSERT_BATCH_SIZE]
        statement = insert(PostalCode).values(batch)
        statement = statement.on_conflict_do_update(
            index_elements=[PostalCode.postal_code],
            set_={
                "name": statement.excluded.name,
                "location": statement.excluded.location,
                "source": statement.excluded.source,
                "location_source": statement.excluded.location_source,
                "location_method": statement.excluded.location_method,
                "location_sample_count": statement.excluded.location_sample_count,
            },
        )
        session.execute(statement)

    session.commit()
    return len(records)
