"""Parse user-exported Immowelt Suchauftrag .eml files without HTTP requests.

Usage:
    python scripts/import_immowelt_alert_eml.py mail1.eml mail2.eml > offers.jsonl
    python scripts/import_immowelt_alert_eml.py --format csv alerts/*.eml > offers.csv

The output contains discovered URLs and optional link labels, NOT verified active
house records. External URLs, redirectors, prices and account data are ignored.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from app.crawling.immowelt_mail_alerts import extract_alert_files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("emails", nargs="+", type=Path, help="Your downloaded .eml files")
    parser.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")
    args = parser.parse_args(argv)

    try:
        records = extract_alert_files(args.emails)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    if args.format == "csv":
        writer = csv.writer(sys.stdout)
        writer.writerow(("source_listing_id", "url", "title"))
        for record in records:
            writer.writerow((record.source_listing_id, record.url, record.title or ""))
    else:
        for record in records:
            print(
                json.dumps(
                    {
                        "source_listing_id": record.source_listing_id,
                        "url": record.url,
                        "title": record.title,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
    print(
        f"Parsed {len(args.emails)} local EML file(s); "
        f"discovered {len(records)} distinct direct Immowelt offer URL(s).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
