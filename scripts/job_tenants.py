from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

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
            config = f" config={json.dumps(row.config, sort_keys=True)}" if row.config else ""
            print(
                f"  [{row.namespace}:{row.tenant_key}] {state} "
                f"company={row.company!r} verified={verified}{config}"
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


def _config_set(args: argparse.Namespace) -> None:
    try:
        value = json.loads(args.value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Config value must be valid JSON: {exc}") from exc

    with SessionLocal() as session:
        source = _source(session, args.source)
        row = _tenant(
            session,
            source=source,
            namespace=args.namespace,
            tenant_key=args.tenant,
        )
        config = dict(row.config or {})
        config[args.key] = value
        row.config = config
        session.commit()
        print(
            f"config-set: {source.name} [{row.namespace}:{row.tenant_key}] "
            f"{args.key}={json.dumps(value, sort_keys=True)}"
        )


def _config_unset(args: argparse.Namespace) -> None:
    with SessionLocal() as session:
        source = _source(session, args.source)
        row = _tenant(
            session,
            source=source,
            namespace=args.namespace,
            tenant_key=args.tenant,
        )
        config = dict(row.config or {})
        existed = args.key in config
        config.pop(args.key, None)
        row.config = config
        session.commit()
        outcome = "removed" if existed else "already absent"
        print(
            f"config-unset: {source.name} [{row.namespace}:{row.tenant_key}] "
            f"{args.key} ({outcome})"
        )


def _import_json(args: argparse.Namespace) -> None:
    path = Path(args.path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read tenant import file {path}: {exc}") from exc

    if not isinstance(payload, list):
        raise SystemExit("Tenant import JSON must contain a top-level array")

    with SessionLocal() as session:
        source = _source(session, args.source)
        existing = {
            (row.namespace, row.tenant_key)
            for row in session.scalars(
                select(JobSourceTenant).where(JobSourceTenant.source_id == source.id)
            )
        }
        now = datetime.now(UTC)
        added = 0
        skipped = 0

        for index, entry in enumerate(payload, start=1):
            if not isinstance(entry, dict):
                raise SystemExit(f"Tenant import entry #{index} must be an object")

            tenant = entry.get("tenant")
            company = entry.get("company")
            namespace = entry.get("namespace", "default")
            enabled = entry.get("enabled", True)
            config = entry.get("config", {})

            if not isinstance(tenant, str) or not tenant.strip():
                raise SystemExit(f"Tenant import entry #{index} has invalid tenant")
            if not isinstance(company, str) or not company.strip():
                raise SystemExit(f"Tenant import entry #{index} has invalid company")
            if not isinstance(namespace, str) or not namespace.strip():
                raise SystemExit(f"Tenant import entry #{index} has invalid namespace")
            if not isinstance(enabled, bool):
                raise SystemExit(f"Tenant import entry #{index} has non-boolean enabled")
            if not isinstance(config, dict):
                raise SystemExit(f"Tenant import entry #{index} has non-object config")

            key = (namespace, tenant)
            if key in existing:
                skipped += 1
                continue

            row = JobSourceTenant(
                source_id=source.id,
                namespace=namespace,
                tenant_key=tenant,
                company=company,
                enabled=enabled,
                config=dict(config),
                discovered_at=now,
            )
            session.add(row)
            existing.add(key)
            added += 1

        session.commit()
        print(f"imported: source={source.name} added={added} skipped_existing={skipped}")


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

    config_set_parser = subparsers.add_parser(
        "config-set", help="Set one tenant config value from a JSON literal."
    )
    config_set_parser.add_argument("source")
    config_set_parser.add_argument("tenant")
    config_set_parser.add_argument("key")
    config_set_parser.add_argument("value")
    config_set_parser.add_argument("--namespace", default="default")
    config_set_parser.set_defaults(func=_config_set)

    config_unset_parser = subparsers.add_parser(
        "config-unset", help="Remove one tenant config key."
    )
    config_unset_parser.add_argument("source")
    config_unset_parser.add_argument("tenant")
    config_unset_parser.add_argument("key")
    config_unset_parser.add_argument("--namespace", default="default")
    config_unset_parser.set_defaults(func=_config_unset)

    import_parser = subparsers.add_parser(
        "import-json", help="Insert missing tenants from a JSON array without overwriting existing rows."
    )
    import_parser.add_argument("source")
    import_parser.add_argument("path")
    import_parser.set_defaults(func=_import_json)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
