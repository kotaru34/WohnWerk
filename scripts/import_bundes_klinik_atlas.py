from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from app.database import SessionLocal
from app.hospital_access import (
    BKA_DATASET_DATE,
    BKA_EXPORT_URL,
    BKA_OPEN_DATA_URL,
    download_bundes_klinik_atlas_zip,
    parse_bundes_klinik_atlas_zip,
    upsert_bundes_klinik_atlas_snapshot,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import one complete official Bundes-Klinik-Atlas hospital snapshot."
    )
    parser.add_argument(
        "--zip",
        type=Path,
        help="Use a local export ZIP instead of downloading the pinned official release.",
    )
    parser.add_argument(
        "--url",
        default=BKA_EXPORT_URL,
        help="Official export ZIP URL used when --zip is omitted.",
    )
    parser.add_argument(
        "--dataset-date",
        type=date.fromisoformat,
        default=BKA_DATASET_DATE,
        help=f"Snapshot date (default: {BKA_DATASET_DATE.isoformat()}).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = (
        args.zip.read_bytes()
        if args.zip is not None
        else download_bundes_klinik_atlas_zip(url=args.url)
    )
    records = parse_bundes_klinik_atlas_zip(payload)
    with SessionLocal() as session:
        count = upsert_bundes_klinik_atlas_snapshot(
            session,
            records,
            dataset_date=args.dataset_date,
            source_url=BKA_OPEN_DATA_URL,
        )
    print(
        "hospital_import_status=ok "
        f"source=bundes-klinik-atlas dataset_date={args.dataset_date.isoformat()} "
        f"facilities={count}"
    )


if __name__ == "__main__":
    main()
