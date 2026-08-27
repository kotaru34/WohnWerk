from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from app.database import SessionLocal
from app.models import JobSourceTenant, Source
from app.sources.job.lever import (
    EU_API_BASE,
    GLOBAL_API_BASE,
    LeverSite,
    parse_lever_posting,
)

_SOURCE_NAME = "lever-public-postings"
_DEFAULT_PATH = Path("data/job_tenants/lever_austria_candidates.json")
_NAMESPACES = frozenset({"eu", "global"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify public Lever Postings API candidates and optionally register only "
            "healthy tenant feeds. Failed checks never disable existing tenants."
        )
    )
    parser.add_argument("path", nargs="?", default=str(_DEFAULT_PATH))
    parser.add_argument("--tenant", help="Only verify one candidate tenant key.")
    parser.add_argument(
        "--namespace",
        choices=sorted(_NAMESPACES),
        help="Optionally restrict verification to the EU or global Lever API namespace.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Register verified missing tenants and refresh verifier-owned evidence.",
    )
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--hard-max-pages", type=int, default=100)
    args = parser.parse_args()
    if args.page_size <= 0:
        parser.error("--page-size must be positive")
    if args.hard_max_pages <= 0:
        parser.error("--hard-max-pages must be positive")
    return args


def _load_candidates(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read Lever candidate file {path}: {exc}") from exc
    if not isinstance(payload, list):
        raise SystemExit("Lever candidate JSON must contain a top-level array")

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, entry in enumerate(payload, start=1):
        if not isinstance(entry, dict):
            raise SystemExit(f"Candidate #{index} must be an object")

        tenant = entry.get("tenant")
        company = entry.get("company")
        namespace = entry.get("namespace", "global")
        config = entry.get("config", {})
        enabled = entry.get("enabled", True)

        if not isinstance(tenant, str) or not tenant.strip():
            raise SystemExit(f"Candidate #{index} has invalid tenant")
        if not isinstance(company, str) or not company.strip():
            raise SystemExit(f"Candidate #{index} has invalid company")
        if not isinstance(namespace, str) or namespace.strip() not in _NAMESPACES:
            raise SystemExit(f"Candidate #{index} has invalid Lever namespace")
        if not isinstance(config, dict):
            raise SystemExit(f"Candidate #{index} has invalid config")
        if not isinstance(enabled, bool):
            raise SystemExit(f"Candidate #{index} has invalid enabled flag")

        tenant = tenant.strip()
        namespace = namespace.strip()
        key = (namespace, tenant)
        if key in seen:
            raise SystemExit(f"Duplicate Lever candidate tenant: {namespace}:{tenant}")
        seen.add(key)
        result.append(
            {
                "tenant": tenant,
                "company": company.strip(),
                "namespace": namespace,
                "config": dict(config),
                "enabled": enabled,
            }
        )
    return result


def _api_base(namespace: str) -> str:
    if namespace == "eu":
        return EU_API_BASE
    if namespace == "global":
        return GLOBAL_API_BASE
    raise ValueError(f"Unsupported Lever namespace: {namespace!r}")


def _verify_feed(
    client: httpx.Client,
    *,
    tenant: str,
    company: str,
    namespace: str,
    delay: float,
    page_size: int,
    hard_max_pages: int,
) -> tuple[str, int, int, int] | None:
    site = LeverSite(site=tenant, company=company, region=namespace)
    api_url = f"{_api_base(namespace)}/{tenant}"
    seen_ids: set[str] = set()
    austrian_positions = 0

    for page_index in range(hard_max_pages):
        if page_index and delay > 0:
            time.sleep(delay)
        try:
            response = client.get(
                api_url,
                params={
                    "mode": "json",
                    "skip": page_index * page_size,
                    "limit": page_size,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError(
                    f"Lever returned {type(payload).__name__}, expected a postings list"
                )
            if not all(isinstance(item, dict) for item in payload):
                raise TypeError("Lever returned a malformed postings list")

            for posting in payload:
                posting_id = posting.get("id")
                if not isinstance(posting_id, str) or not posting_id.strip():
                    raise ValueError("Lever posting is missing a stable id")
                if posting_id in seen_ids:
                    continue
                parsed = parse_lever_posting(posting, site=site)
                seen_ids.add(posting_id)
                if parsed is not None:
                    austrian_positions += 1
        except httpx.HTTPStatusError as exc:
            print(f"  endpoint_failed={api_url} http_status={exc.response.status_code}")
            return None
        except httpx.HTTPError as exc:
            print(f"  endpoint_failed={api_url} request_error={type(exc).__name__}")
            return None
        except (TypeError, ValueError) as exc:
            print(f"  endpoint_failed={api_url} invalid_feed={type(exc).__name__}: {exc}")
            return None

        pages_fetched = page_index + 1
        if len(payload) < page_size:
            return api_url, len(seen_ids), austrian_positions, pages_fetched

    print(
        f"  endpoint_incomplete={api_url} result_cap_pages={hard_max_pages} "
        f"positions_seen={len(seen_ids)}"
    )
    return None


def _verification_record(
    *,
    checked_at: datetime,
    api_url: str,
    namespace: str,
    source_positions: int,
    austrian_positions: int,
    pages_fetched: int,
) -> dict[str, Any]:
    return {
        "status": "verified",
        "checked_at": checked_at.isoformat(),
        "api_url": api_url,
        "namespace": namespace,
        "pages_fetched": pages_fetched,
        "source_positions": source_positions,
        "austrian_positions": austrian_positions,
    }


def main() -> None:
    args = parse_args()
    candidates = _load_candidates(Path(args.path))
    if args.tenant:
        candidates = [row for row in candidates if row["tenant"] == args.tenant]
    if args.namespace:
        candidates = [row for row in candidates if row["namespace"] == args.namespace]
    if (args.tenant or args.namespace) and not candidates:
        raise SystemExit("No Lever candidate matched the requested tenant/namespace filter")

    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == _SOURCE_NAME))
        if source is None:
            raise SystemExit(
                f"Source {_SOURCE_NAME!r} does not exist; initialize the Lever runner first"
            )
        existing = {
            (row.namespace, row.tenant_key): row
            for row in session.scalars(
                select(JobSourceTenant).where(JobSourceTenant.source_id == source.id)
            )
        }

        headers = {
            "Accept": "application/json",
            "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian job search; tenant verification)",
        }
        counts: Counter[str] = Counter()
        added = 0
        refreshed = 0

        with httpx.Client(headers=headers, timeout=args.timeout, follow_redirects=True) as client:
            for candidate in candidates:
                tenant = candidate["tenant"]
                company = candidate["company"]
                namespace = candidate["namespace"]
                print(f"[checking] {namespace}:{tenant} company={company}")
                verified = _verify_feed(
                    client,
                    tenant=tenant,
                    company=company,
                    namespace=namespace,
                    delay=max(0.0, args.delay),
                    page_size=args.page_size,
                    hard_max_pages=args.hard_max_pages,
                )
                if verified is None:
                    counts["unverified"] += 1
                    print(f"[unverified] {namespace}:{tenant}")
                    continue

                api_url, source_positions, austrian_positions, pages_fetched = verified
                checked_at = datetime.now(UTC)
                counts["verified"] += 1
                print(
                    f"[verified] {namespace}:{tenant} source_positions={source_positions} "
                    f"austrian_positions={austrian_positions} pages={pages_fetched} "
                    f"api={api_url}"
                )

                if not args.apply:
                    continue

                verification = _verification_record(
                    checked_at=checked_at,
                    api_url=api_url,
                    namespace=namespace,
                    source_positions=source_positions,
                    austrian_positions=austrian_positions,
                    pages_fetched=pages_fetched,
                )
                key = (namespace, tenant)
                row = existing.get(key)
                if row is None:
                    config = dict(candidate["config"])
                    config["lever_feed_verification"] = verification
                    row = JobSourceTenant(
                        source_id=source.id,
                        namespace=namespace,
                        tenant_key=tenant,
                        company=company,
                        enabled=candidate["enabled"],
                        config=config,
                        discovered_at=checked_at,
                        last_verified_at=checked_at,
                    )
                    session.add(row)
                    existing[key] = row
                    added += 1
                else:
                    # Preserve operator-managed company/enabled/discovery configuration.
                    # Refresh only this verifier's capability evidence and timestamp.
                    config = dict(row.config or {})
                    config["lever_feed_verification"] = verification
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
