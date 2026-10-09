"""Offline review of a real, saved public German search HTML page (no network/DB).

Usage:
  python -m scripts.inspect_public_portal_snapshot_de --provider immobilien-de \
      --frontier de-neubrandenburg --html-file /tmp/public-search.html

The output explicitly distinguishes recognized public cards from verified,
existing houses. Never enable production acquisition based only on this probe.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.sources.property.public_portals_de import (
    ImmobilienDeGermanyPropertySource,
    OhneMaklerGermanyPropertySource,
    parse_public_portal_page,
)

PROVIDERS = {
    "ohne-makler-de": OhneMaklerGermanyPropertySource,
    "immobilien-de": ImmobilienDeGermanyPropertySource,
}

MAX_SNAPSHOT_BYTES = 5_000_000


def inspect_saved_html(
    *,
    provider_name: str,
    frontier_key: str,
    html: str,
) -> dict[str, object]:
    adapter = PROVIDERS[provider_name]()
    path = adapter.frontier_paths().get(frontier_key)
    if path is None:
        raise ValueError("Unknown/unvalidated public search frontier")
    url = adapter.portal.base_url + path
    cards, seen = parse_public_portal_page(html, page_url=url, portal=adapter.portal)
    listing_ids = [item.source_listing_id for item in cards]
    return {
        "provider": provider_name,
        "frontier": frontier_key,
        "recognized_public_ids": seen,
        "eligible_price_card_ids": len(cards),
        "eligible_ids": listing_ids,
        "verified_existing_houses": 0,
        "production_activation_ready": False,
        "detail_verification": "not_performed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=PROVIDERS)
    parser.add_argument("--frontier", default="de-public-frontier")
    parser.add_argument("--html-file", type=Path, required=True)
    args = parser.parse_args()
    if args.html_file.stat().st_size > MAX_SNAPSHOT_BYTES:
        parser.error("HTML snapshot exceeds the 5 MB conservative size limit")
    html = args.html_file.read_text(encoding="utf-8")
    result = inspect_saved_html(
        provider_name=args.provider, frontier_key=args.frontier, html=html
    )
    print(f"Provider: {result['provider']}, frontier: {result['frontier']}")
    print(f"Recognized public IDs: {result['recognized_public_ids']}")
    print(f"Price-eligible unverified leads: {result['eligible_price_card_ids']}")
    for listing_id in result["eligible_ids"]:
        print(f"  candidate={listing_id}")
    print("House details NOT verified; automatic activation forbidden.")
    return 0 if result["recognized_public_ids"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
