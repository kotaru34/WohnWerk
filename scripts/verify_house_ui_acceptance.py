from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path.cwd()))

from app.config import get_settings
from app.database import SessionLocal
from app.models import ListingStatus, PropertyListing, Source
from app.property_images import PropertyImage
from app.templates_runtime import templates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify one production house location, provenance badge, grouped facts and media."
    )
    parser.add_argument("--property-id", type=int, default=62724)
    parser.add_argument("--listing-id", default="960-75511")
    parser.add_argument("--postal-code", default="2225")
    parser.add_argument("--city", default="Loidesthal")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    return parser.parse_args()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def template_contract() -> None:
    partial, _filename, _uptodate = templates.env.loader.get_source(
        templates.env, "_house_fact_groups.html"
    )
    labels = ("Objekt", "Heizung", "Distanzen", "Internet")
    positions = [partial.index(f"<span>{label}</span>") for label in labels]
    require(positions == sorted(positions), "fact-group template order regression")

    for name in ("houses.html", "house_detail.html"):
        source, _filename, _uptodate = templates.env.loader.get_source(templates.env, name)
        include_at = source.index('{% include "_house_source_badges.html" %}')
        seen_at = source.index("Gesehen", include_at)
        require(include_at < seen_at, f"{name}: source badge no longer precedes seen status")
        require('{% include "_house_fact_groups.html" %}' in source, f"{name}: fact groups missing")

    badge, _filename, _uptodate = templates.env.loader.get_source(
        templates.env, "_house_source_badges.html"
    )
    for needle in ("source-badge", "source-icon", "source.brand.color", "source.brand.label"):
        require(needle in badge, f"badge partial missing {needle}")


def article_for_property(document: str, property_id: int) -> str:
    marker = f'id="house-{property_id}"'
    marker_at = document.find(marker)
    require(marker_at >= 0, f"catalog does not contain property {property_id}")
    start = document.rfind("<article", 0, marker_at)
    end = document.find("</article>", marker_at)
    require(start >= 0 and end >= 0, "could not isolate catalog house article")
    return document[start : end + len("</article>")]


def seen_position(fragment: str) -> int:
    positions = [
        pos
        for label in ("Gesehen", "Noch nicht angesehen")
        if (pos := fragment.find(label)) >= 0
    ]
    require(bool(positions), "seen/unseen status missing")
    return min(positions)


def verify_badge(fragment: str, source_url: str, *, context: str) -> None:
    badge_at = fragment.find("source-badge")
    require(badge_at >= 0, f"{context}: source-badge class missing")
    require("source-icon" in fragment, f"{context}: source-icon missing")
    require("s REAL" in fragment, f"{context}: s REAL label missing")
    require("--source-color:" in fragment, f"{context}: inline source color missing")
    escaped_url = html.escape(source_url, quote=True)
    require(
        f'href="{escaped_url}"' in fragment,
        f"{context}: original s REAL href missing",
    )
    require(badge_at < seen_position(fragment), f"{context}: badge is not before seen status")


def main() -> None:
    args = parse_args()
    template_contract()

    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == "sreal.at"))
        require(source is not None, "sreal.at source missing")

        listing = session.scalar(
            select(PropertyListing).where(
                PropertyListing.source_id == source.id,
                PropertyListing.source_listing_id == args.listing_id,
                PropertyListing.status == ListingStatus.ACTIVE,
            )
        )
        require(listing is not None, "active s REAL listing missing")
        property_row = listing.property
        require(property_row.id == args.property_id, "listing points to unexpected property")
        require(property_row.postal_code == args.postal_code, "persisted postal code mismatch")
        require(property_row.city == args.city, "persisted city mismatch")

        payload = listing.raw_payload or {}
        require(payload.get("source_postal_code") == args.postal_code, "source_postal_code mismatch")
        require(payload.get("detail_postal_code") == args.postal_code, "detail_postal_code mismatch")
        require(payload.get("detail_city") == args.city, "detail_city mismatch")
        require(
            payload.get("targeted_location_repair_policy") == "sreal-detail-location-repair-v1",
            "targeted repair policy marker missing",
        )
        source_url = listing.url

        image_row = session.scalar(
            select(PropertyImage).where(PropertyImage.property_id == args.property_id)
        )
        image_expected = bool(
            image_row is not None
            and image_row.status == "cached"
            and image_row.local_filename
        )

    settings = get_settings()
    require(bool(settings.admin_password), "admin password is not configured")

    auth = (settings.admin_username, settings.admin_password)
    with httpx.Client(
        base_url=args.base_url,
        auth=auth,
        timeout=15.0,
        follow_redirects=True,
    ) as client:
        catalog = client.get(
            "/houses",
            params={
                "country": "AT",
                "ort": args.city,
                "ansicht": "alle",
                "sortierung": "neuheit",
                "richtung": "desc",
            },
        )
        require(catalog.status_code == 200, f"catalog HTTP {catalog.status_code}")
        article = article_for_property(catalog.text, args.property_id)
        verify_badge(article, source_url, context="catalog")
        require(
            f"{args.postal_code} {args.city}" in article,
            "catalog does not render repaired location",
        )
        require("Objekt" in article and "Heizung" in article, "catalog fact groups missing")

        detail = client.get(
            f"/houses/{args.property_id}",
            params={"country": "AT"},
        )
        require(detail.status_code == 200, f"detail HTTP {detail.status_code}")
        verify_badge(detail.text, source_url, context="detail")
        require(
            f"{args.postal_code} {args.city}" in detail.text,
            "detail does not render repaired location",
        )
        require("Objekt" in detail.text and "Heizung" in detail.text, "detail fact groups missing")

        image_status = "not-cached"
        if image_expected:
            image = client.get(f"/media/properties/{args.property_id}")
            require(image.status_code == 200, f"property image HTTP {image.status_code}")
            content_type = image.headers.get("content-type", "")
            require(content_type.startswith("image/"), f"property image type {content_type!r}")
            image_status = f"200 {content_type}"

    print(f"property={args.property_id} location={args.postal_code} {args.city}")
    print(
        "repair_evidence="
        f"source_postal_code={args.postal_code} "
        f"detail_postal_code={args.postal_code} detail_city={args.city}"
    )
    print("template_contract=ok")
    print("catalog_http=200 badge=s_REAL-before-seen location=ok facts=ok")
    print("detail_http=200 badge=s_REAL-before-seen location=ok facts=ok")
    print(f"property_image={image_status}")
    print("acceptance=ok")


if __name__ == "__main__":
    main()
