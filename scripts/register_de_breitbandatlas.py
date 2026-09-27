from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from app.database import SessionLocal
from app.internet_access import publish_breitbandatlas_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and register the pinned German Breitbandatlas GeoPackage."
    )
    parser.add_argument("--gpkg", type=Path, required=True)
    parser.add_argument("--dataset-date", type=date.fromisoformat, default=date(2025, 12, 31))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        info = publish_breitbandatlas_dataset(
            session,
            args.gpkg,
            dataset_date=args.dataset_date,
        )
    print(
        "internet_dataset "
        f"date={args.dataset_date.isoformat()} "
        f"features={info.feature_count} "
        f"sha256={info.artifact_sha256}"
    )


if __name__ == "__main__":
    main()
