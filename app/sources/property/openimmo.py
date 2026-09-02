from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any
from zipfile import BadZipFile, ZipFile

import httpx

from app.sources.base import PropertySource, RawProperty, SourceBatch, SourceShardSpec


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element: ET.Element | None, name: str) -> ET.Element | None:
    if element is None:
        return None
    for child in element:
        if _local_name(child.tag) == name:
            return child
    return None


def _path(element: ET.Element | None, *names: str) -> ET.Element | None:
    current = element
    for name in names:
        current = _child(current, name)
        if current is None:
            return None
    return current


def _text(element: ET.Element | None, *names: str) -> str | None:
    target = _path(element, *names)
    if target is None or target.text is None:
        return None
    value = target.text.strip()
    return value or None


def _decimal_text(element: ET.Element | None, *names: str) -> Decimal | None:
    value = _text(element, *names)
    if value is None:
        return None
    normalized = value.replace(" ", "").replace(".", "").replace(",", ".")
    if value.count(".") == 1 and value.count(",") == 0:
        normalized = value
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _is_true(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "ja", "yes"}


def _extract_xml(payload: bytes) -> bytes:
    if payload[:2] != b"PK":
        return payload

    try:
        with ZipFile(BytesIO(payload)) as archive:
            candidates = [name for name in archive.namelist() if name.lower().endswith(".xml")]
            if not candidates:
                raise ValueError("OpenImmo ZIP contains no XML file")
            candidates.sort(key=lambda name: ("openimmo" not in name.casefold(), len(name)))
            return archive.read(candidates[0])
    except BadZipFile as exc:
        raise ValueError("Invalid ZIP payload returned for OpenImmo feed") from exc


def openimmo_is_full_export(xml_payload: bytes) -> bool:
    """Trust reconciliation only when OpenImmo explicitly declares a full export."""
    root = ET.fromstring(xml_payload)
    transfer = next(
        (element for element in root.iter() if _local_name(element.tag) == "uebertragung"),
        None,
    )
    if transfer is None:
        return False
    return str(transfer.attrib.get("umfang", "")).strip().casefold() == "voll"


def parse_openimmo_properties(xml_payload: bytes, *, fallback_url: str) -> list[RawProperty]:
    """Parse residential houses for sale from an OpenImmo 1.x XML payload."""
    root = ET.fromstring(xml_payload)
    records: list[RawProperty] = []

    for element in root.iter():
        if _local_name(element.tag) != "immobilie":
            continue

        category = _child(element, "objektkategorie")
        marketing = _child(category, "vermarktungsart")
        object_types = _child(category, "objektart")
        house = _child(object_types, "haus")

        if marketing is None or not _is_true(marketing.attrib.get("KAUF")):
            continue
        if house is None:
            continue

        technical = _child(element, "verwaltung_techn")
        source_id = _text(technical, "objektnr_extern") or _text(technical, "objektnr_intern")
        if source_id is None:
            continue

        free_text = _child(element, "freitexte")
        title = _text(free_text, "objekttitel") or f"Haus {source_id}"
        descriptions = [
            _text(free_text, "objektbeschreibung"),
            _text(free_text, "lage"),
            _text(free_text, "sonstige_angaben"),
        ]
        description = "\n\n".join(part for part in descriptions if part) or None

        geo = _child(element, "geo")
        prices = _child(element, "preise")
        areas = _child(element, "flaechen")

        listing_url = fallback_url
        links = _child(element, "links")
        if links is not None:
            for link in links:
                if _local_name(link.tag) != "link":
                    continue
                candidate = _text(link, "url") or _text(link, "link")
                if candidate and candidate.startswith(("http://", "https://")):
                    listing_url = candidate
                    break

        records.append(
            RawProperty(
                source_listing_id=source_id,
                url=listing_url,
                title=title,
                description=description,
                price_eur=_decimal_text(prices, "kaufpreis"),
                living_area_m2=_decimal_text(areas, "wohnflaeche"),
                plot_area_m2=_decimal_text(areas, "grundstuecksflaeche"),
                postal_code=_text(geo, "plz"),
                city=_text(geo, "ort"),
                raw_payload={
                    "format": "openimmo",
                    "house_type": house.attrib.get("haustyp"),
                },
            )
        )

    return records


class OpenImmoFeedPropertySource(PropertySource):
    """OpenImmo feed adapter for Austrian brokers and portals."""

    def __init__(self, *, name: str, feed_url: str, timeout_seconds: float = 60.0) -> None:
        self.name = name
        self.feed_url = feed_url
        self.timeout_seconds = timeout_seconds

    def default_shards(self) -> list[SourceShardSpec]:
        return [SourceShardSpec(key="full-feed", params={"feed_url": self.feed_url})]

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawProperty]:
        del cursor, reconciliation
        if shard.key != "full-feed":
            raise ValueError(f"Unknown OpenImmo shard: {shard.key}")

        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
            response = await client.get(self.feed_url)
            response.raise_for_status()

        xml_payload = _extract_xml(response.content)
        items = parse_openimmo_properties(xml_payload, fallback_url=self.feed_url)
        is_full_export = openimmo_is_full_export(xml_payload)
        return SourceBatch(
            items=items,
            source_reported_count=len(items),
            coverage_complete=is_full_export,
            result_cap_hit=False,
            pages_fetched=1,
        )
