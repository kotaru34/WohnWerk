from __future__ import annotations

import argparse
from pathlib import Path

from app.database import SessionLocal
from app.postal_centroids import load_bev_postal_centroids, update_postal_centroids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Derive approximate Austrian postal-code locations from the free BEV "
            "Adressregister Stichtagsdaten snapshot."
        )
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Path to the BEV snapshot ZIP or an extracted ADRESSE.csv file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = args.source.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Source file does not exist: {source}")

    centroids = load_bev_postal_centroids(source)
    total_samples = sum(item.sample_count for item in centroids)

    with SessionLocal() as session:
        updated = update_postal_centroids(session, centroids)

    print(
        f"Derived {len(centroids)} postal-code centroids from "
        f"{total_samples:,} geocoded BEV addresses; updated {updated} RTR rows."
    )


if __name__ == "__main__":
    main()
