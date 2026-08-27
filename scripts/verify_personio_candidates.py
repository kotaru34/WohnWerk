from __future__ import annotations

import argparse
import json
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select

from app.database import SessionLocal
from app.jobs.location_resolution import canonicalize_locality
from app.models import JobSourceTenant, PostalCode, Source
from app.sources.job.personio import (
    PERSONIO_LANGUAGES,
    PersonioSite,
    merge_personio_language_items,
    parse_personio_feed,
    personio_feed_urls,
)

_SOURCE_NAME = "personio-public-xml"
_DEFAULT_PATH = Path("data/job_tenants/personio_austria_candidates.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify public Personio XML capability for discovery candidates and optionally "
            "register only healthy feeds. Failed checks never disable existing tenants."
        )
    )
    parser.add_argument("path", nargs="?", default=str(_DEFAULT_PATH))
    parser.add_argument("--tenant", help="Only verify one candidate tenant key.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Register verified missing tenants and refresh verification evidence on existing rows.",
    )
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def _load_candidates(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read Personio candidate file {path}: {exc}") from exc
    if not isinstance(payload, list):
        raise SystemExit("Personio candidate JSON must contain a top-level array")

    result: list[dict] = []
    seen: set[str] = set()
    for index, entry in enumerate(payload, start=1):
        if not isinstance(entry, dict):
            raise SystemExit(f"Candidate #{index} must be an object")
        tenant = entry.get("tenant")
        company = entry.get("company")
        config = entry.get("config", {})
        enabled = entry.get("enabled", True)
        if not isinstance(tenant, str) or not tenant.strip():
            raise SystemExit(f"Candidate #{index} has invalid tenant")
        if tenant in seen:
            raise SystemExit(f"Duplicate Personio candidate tenant: {tenant}")
        if not isinstance(company, str) or not company.strip():
            raise SystemExit(f"Candidate #{index} has invalid company")
        if not isinstance(config, dict):
            raise SystemExit(f"Candidate #{index} has invalid config")
        if not isinstance(enabled, bool):
            raise SystemExit(f"Candidate #{index} has invalid enabled flag")
        seen.add(tenant)
        result.append(
            {
                "tenant": tenant.strip(),
                "company": company.strip(),
                "config": dict(config),
                "enabled": enabled,
            }
        )
    return result


def _austrian_localities(session) -> set[str]:
    names = set(session.scalars(select(PostalCode.name)))
    result = {
        canonical
        for value in names
        if (canonical := canonicalize_locality(value)) is not None
    }
    if not result:
        raise SystemExit("No Austrian postal localities are loaded")
    return result


def _verification_record(
    *,
    checked_at: datetime,
    feed_url: str,
    source_positions: int,
    austrian_positions: int,
    languages: list[str],
    language_source_positions: dict[str, int],
) -> dict:
    return {
        "status": "verified",
        "checked_at": checked_at.isoformat(),
        "feed_url": feed_url,
        "languages": languages,
        "language_source_positions": language_source_positions,
        "source_positions": source_positions,
        "austrian_positions": austrian_positions,
    }


def _verify_feed(
    client: httpx.Client,
    *,
    tenant: str,
    company: str,
    localities: set[str],
    delay: float,
) -> tuple[str, int, int, list[str], dict[str, int]] | None:
    site = PersonioSite(tenant=tenant, company=company)
    for feed_url in personio_feed_urls(site):
        resolved_site = PersonioSite(
            tenant=tenant,
            company=company,
            base_url=feed_url.removesuffix("/xml"),
        )
        language_items: dict[str, list] = {}
        language_counts: dict[str, int] = {}

        for language in PERSONIO_LANGUAGES:
            if delay > 0:
                time.sleep(delay)
            try:
                response = client.get(feed_url, params={"language": language})
                response.raise_for_status()
                items, source_positions = parse_personio_feed(
                    response.content,
                    site=resolved_site,
                    austrian_localities=localities,
                    language=language,
                )
            except httpx.HTTPStatusError as exc:
                print(
                    f"  endpoint_failed={feed_url}?language={language} "
                    f"http_status={exc.response.status_code}"
                )
                continue
            except httpx.HTTPError as exc:
                print(
                    f"  endpoint_failed={feed_url}?language={language} "
                    f"request_error={type(exc).__name__}"
                )
                continue
            except (ET.ParseError, TypeError, ValueError) as exc:
                print(
                    f"  endpoint_failed={feed_url}?language={language} "
                    f"invalid_feed={type(exc).__name__}: {exc}"
                )
                continue
            language_items[language] = items
            language_counts[language] = source_positions

        if not language_items:
            continue

        merged_items = merge_personio_language_items(language_items)
        languages = [
            language for language in PERSONIO_LANGUAGES if language in language_items
        ]
        source_positions = max(language_counts.values())
        return (
            feed_url,
            source_positions,
            len(merged_items),
            languages,
            language_counts,
        )
    return None


def main() -> None:
    args = parse_args()
    candidates = _load_candidates(Path(args.path))
    if args.tenant:
        candidates = [row for row in candidates if row["tenant"] == args.tenant]
        if not candidates:
            raise SystemExit(f"Candidate tenant not found in file: {args.tenant}")

    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == _SOURCE_NAME))
        if source is None:
            raise SystemExit(
                f"Source {_SOURCE_NAME!r} does not exist; initialize the Personio runner first"
            )
        localities = _austrian_localities(session)
        existing = {
            row.tenant_key: row
            for row in session.scalars(
                select(JobSourceTenant).where(
                    JobSourceTenant.source_id == source.id,
                    JobSourceTenant.namespace == "default",
                )
            )
        }

        headers = {
            "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.1",
            "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian job search; tenant verification)",
        }
        counts: Counter[str] = Counter()
        added = 0
        refreshed = 0

        with httpx.Client(headers=headers, timeout=args.timeout, follow_redirects=True) as client:
            for candidate in candidates:
                tenant = candidate["tenant"]
                company = candidate["company"]
                print(f"[checking] {tenant} company={company}")
                verified = _verify_feed(
                    client,
                    tenant=tenant,
                    company=company,
                    localities=localities,
                    delay=max(0.0, args.delay),
                )
                if verified is None:
                    counts["unverified"] += 1
                    print(f"[unverified] {tenant}")
                    continue

                (
                    feed_url,
                    source_positions,
                    austrian_positions,
                    languages,
                    language_source_positions,
                ) = verified
                checked_at = datetime.now(UTC)
                counts["verified"] += 1
                print(
                    f"[verified] {tenant} source_positions={source_positions} "
                    f"austrian_positions={austrian_positions} languages={','.join(languages)} "
                    f"feed={feed_url}"
                )

                if not args.apply:
                    continue

                verification = _verification_record(
                    checked_at=checked_at,
                    feed_url=feed_url,
                    source_positions=source_positions,
                    austrian_positions=austrian_positions,
                    languages=languages,
                    language_source_positions=language_source_positions,
                )
                row = existing.get(tenant)
                if row is None:
                    config = dict(candidate["config"])
                    config["personio_feed_verification"] = verification
                    row = JobSourceTenant(
                        source_id=source.id,
                        namespace="default",
                        tenant_key=tenant,
                        company=company,
                        enabled=candidate["enabled"],
                        config=config,
                        discovered_at=checked_at,
                        last_verified_at=checked_at,
                    )
                    session.add(row)
                    existing[tenant] = row
                    added += 1
                else:
                    # Preserve operator-managed company/enabled/discovery config. Only
                    # refresh this script's capability evidence and verification time.
                    config = dict(row.config or {})
                    config["personio_feed_verification"] = verification
                    row.config = config
                    row.last_verified_at = checked_at
                    refreshed += 1

        if args.apply:
            session.commit()

        print("summary:")
        print(f"  candidates={len(candidates)}")
        for state, count in sorted(counts.items()):
            print(f"  state[{state}]={count}")
        if args.apply:
            print(f"  registry_added={added}")
            print(f"  registry_verification_refreshed={refreshed}")
        else:
            print("  mode=dry-run; registry unchanged")
        print("note=failed verification never disables or removes an existing tenant")


if __name__ == "__main__":
    main()
