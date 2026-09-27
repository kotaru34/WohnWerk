from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from app.database import SessionLocal
from app.internet_access import BBA_DATASET_DATE, publish_breitbandatlas_evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Publish compact source-backed Internet evidence from the official "
            "Bundesnetzagentur Breitbandatlas GeoPackage."
        )
    )
    parser.add_argument("--gpkg", type=Path, required=True)
    parser.add_argument(
        "--dataset-date",
        type=date.fromisoformat,
        default=BBA_DATASET_DATE,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        source_rows, matched_properties = publish_breitbandatlas_evidence(
            session,
            gpkg_path=args.gpkg,
            dataset_date=args.dataset_date,
        )
    print(
        "internet_import "
        f"dataset_date={args.dataset_date.isoformat()} "
        f"source_rows={source_rows} "
        f"matched_precise_properties={matched_properties}"
    )


if __name__ == "__main__":
    main()
