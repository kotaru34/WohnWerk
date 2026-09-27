from __future__ import annotations

import argparse
from pathlib import Path

from app.database import SessionLocal
from app.hospital_access import import_bka_archive


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import Bundes-Klinik-Atlas Open Data into WohnWerk."
    )
    parser.add_argument(
        "archive",
        type=Path,
        help="Path to Bundes-Klinik-Atlas_Datenexport_YYYYMMDD.zip",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        result = import_bka_archive(session, args.archive)
    print(
        "hospital_import "
        f"snapshot={result.snapshot_date.isoformat()} "
        f"imported={result.imported} removed={result.removed}"
    )


if __name__ == "__main__":
    main()
