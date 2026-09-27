from __future__ import annotations

import argparse

from app.database import SessionLocal
from app.internet_access import enrich_precise_properties_from_breitbandatlas


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Persist German Breitbandatlas grid evidence only for properties with "
            "address/parcel-scale location provenance."
        )
    )
    parser.add_argument("--property-id", type=int, action="append", default=[])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    property_ids = set(args.property_id) or None
    with SessionLocal() as session:
        updated, no_grid = enrich_precise_properties_from_breitbandatlas(
            session,
            property_ids=property_ids,
        )
    print(f"internet_enrichment updated={updated} no_grid={no_grid}")


if __name__ == "__main__":
    main()
