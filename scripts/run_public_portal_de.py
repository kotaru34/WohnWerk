"""Manual-only activation of a conservative public German portal frontier."""

from __future__ import annotations


from sqlalchemy import select

from app.crawling.property_runner import run_property_source
from app.database import SessionLocal
from app.models import Source, SourceCategory
from app.sources.property.public_portals_de import (
    IMMOBILIEN_DE,
    OHNE_MAKLER,
    ImmobilienDeGermanyPropertySource,
    OhneMaklerGermanyPropertySource,
)


PORTALS = {
    "ohne-makler-de": (
        OHNE_MAKLER,
        OhneMaklerGermanyPropertySource,
        "app.sources.property.public_portals_de.OhneMaklerGermanyPropertySource",
    ),
    "immobilien-de": (
        IMMOBILIEN_DE,
        ImmobilienDeGermanyPropertySource,
        "app.sources.property.public_portals_de.ImmobilienDeGermanyPropertySource",
    ),
}


async def run_portal(source_name: str) -> int:
    portal, adapter_type, adapter_path = PORTALS[source_name]
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == source_name))
        if source is None:
            source = Source(
                name=source_name,
                category=SourceCategory.PROPERTY,
                adapter=adapter_path,
                base_url=portal.base_url,
                enabled=False,
                poll_interval_minutes=240,
                config={
                    "country_code": "DE",
                    "coverage": "single public page, frontier-only, never disappearance authority",
                    "retention": "public ID, link, title, asking price and source-backed PLZ/city/areas",
                    "operator_note": "Manual diagnostic only; activation requires a separately validated live sample",
                },
            )
            session.add(source)
            session.commit()
            session.refresh(source)
        # A manual run does not silently enable recurring acquisition.
        run, summary = await run_property_source(
            session,
            source=source,
            adapter=adapter_type(),
            reconciliation=False,
        )
        print(f"source={source.name} run={run.id} status={summary.run_status}")
        print(f"seen={summary.items_seen} pages={summary.pages_fetched}")
        return 0 if summary.run_status != "failed" else 1
