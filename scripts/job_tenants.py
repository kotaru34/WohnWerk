from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import select

from app.database import SessionLocal
from app.models import JobSourceTenant, Source


def _source(session, name: str) -> Source:
    source = session.scalar(select(Source).where(Source.name == name))
    if source is None:
        raise SystemExit(f"Unknown source: {name}")
    return source


def _tenant(
    session,
    *,
    source: Source,
    namespace: str,
    tenant_key: str,
) -> JobSourceTenant:
    row = session.scalar(
        select(JobSourceTenant).where(
            JobSourceTenant.source_id == source.id,
            JobSourceTenant.namespace == namespace,
            JobSourceTenant.tenant_key == tenant_key,
        )
    )
    if row is None:
        raise SystemExit(
            f"Unknown tenant: source={source.name} namespace={namespace} tenant={tenant_key}"
        )
    return row


def _list(args: argparse.Namespace) -> None:
    with SessionLocal() as session:
        source = _source(session, args.source)
        rows = list(
            session.scalars(
                select(JobSourceTenant)
                .where(JobSourceTenant.source_id == source.id)
                .order_by(JobSourceTenant.namespace, JobSourceTenant.tenant_key)
            )
        )
        print(f"source={source.name} tenants={len(rows)}")
        for row in rows:
            state = "enabled" if row.enabled else "disabled"
            verified = row.last_verified_at.isoformat() if row.last_verified_at else "never"
            print(
                f"  [{row.namespace}:{row.tenant_key}] {state} "
                f"company={row.company!r} verified={verified}"
            )


def _set_enabled(args: argparse.Namespace, enabled: bool) -> None:
    with SessionLocal() as session:
        source = _source(session, args.source)
        row = _tenant(
            session,
            source=source,
            namespace=args.namespace,
            tenant_key=args.tenant,
        )
        row.enabled = enabled
        session.commit()
        state = "enabled" if enabled else "disabled"
        print(f"{state}: {source.name} [{row.namespace}:{row.tenant_key}] {row.company}")


def _add(args: argparse.Namespace) -> None:
    with SessionLocal() as session:
        source = _source(session, args.source)
        existing = session.scalar(
            select(JobSourceTenant).where(
                JobSourceTenant.source_id == source.id,
                JobSourceTenant.namespace == args.namespace,
                JobSourceTenant.tenant_key == args.tenant,
            )
        )
        if existing is not None:
            raise SystemExit(
                f"Tenant already exists: {source.name} "
                f"[{existing.namespace}:{existing.tenant_key}]"
            )

        row = JobSourceTenant(
            source_id=source.id,
            namespace=args.namespace,
            tenant_key=args.tenant,
            company=args.company,
            enabled=not args.disabled,
            config={},
            discovered_at=datetime.now(UTC),
        )
        session.add(row)
        session.commit()
        state = "disabled" if args.disabled else "enabled"
        print(f"added {state}: {source.name} [{row.namespace}:{row.tenant_key}] {row.company}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage DB-backed job-source tenants.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List tenants for one source.")
    list_parser.add_argument("source")
    list_parser.set_defaults(func=_list)

    for command, enabled in (("enable", True), ("disable", False)):
        state_parser = subparsers.add_parser(command, help=f"{command.title()} one tenant.")
        state_parser.add_argument("source")
        state_parser.add_argument("tenant")
        state_parser.add_argument("--namespace", default="default")
        state_parser.set_defaults(func=lambda args, value=enabled: _set_enabled(args, value))

    add_parser = subparsers.add_parser("add", help="Add a tenant to an existing source.")
    add_parser.add_argument("source")
    add_parser.add_argument("tenant")
    add_parser.add_argument("company")
    add_parser.add_argument("--namespace", default="default")
    add_parser.add_argument("--disabled", action="store_true")
    add_parser.set_defaults(func=_add)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
