from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from app.database import SessionLocal
from app.internet_access import BBA_DATASET_DATE, publish_breitbandatlas_cache


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish a validated German Breitbandatlas GeoPackage as WohnWerk source cache."
    )
    parser.add_argument("--gpkg", required=True, type=Path)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("/var/lib/wohnwerk/broadband"),
    )
    parser.add_argument(
        "--dataset-date",
        type=date.fromisoformat,
        default=BBA_DATASET_DATE,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        path = publish_breitbandatlas_cache(
            session,
            args.gpkg,
            cache_dir=args.cache_dir,
            dataset_date=args.dataset_date,
        )
    print(
        "internet_dataset "
        f"country=DE dataset_date={args.dataset_date.isoformat()} "
        f"coverage_status=ok path={path}"
    )


if __name__ == "__main__":
    main()
