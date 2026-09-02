from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_STABLE_IDENTITY_KEY = "wohnwerk_stable_identity"


def smartrecruiters_job_ad_identity(tenant: object, job_ad_id: object) -> str | None:
    """Return the durable SmartRecruiters job-ad identity used across republishes.

    A SmartRecruiters posting/publication id may change when the same job ad is
    re-published. `jobAdId` identifies the underlying job ad, so tenant + jobAdId
    is deliberately narrower and safer than fuzzy title/company matching.
    """
    if not isinstance(tenant, str) or not isinstance(job_ad_id, str):
        return None
    tenant_value = tenant.strip()
    job_ad_value = job_ad_id.strip()
    if not tenant_value or not job_ad_value:
        return None
    return f"smartrecruiters:{tenant_value}:jobad:{job_ad_value}"


def workday_requisition_identity(
    tenant: object,
    site: object,
    requisition_id: object,
) -> str | None:
    """Return a source-backed Workday identity for one requisition on one career site."""
    if not all(isinstance(value, str) for value in (tenant, site, requisition_id)):
        return None
    tenant_value = tenant.strip()
    site_value = site.strip()
    requisition_value = requisition_id.strip()
    if not tenant_value or not site_value or not requisition_value:
        return None
    return f"workday:{tenant_value}:{site_value}:req:{requisition_value}"


def stable_identity_from_payload(payload: Mapping[str, Any] | None) -> str | None:
    """Read a source-backed canonical identity, including legacy SR payloads."""
    if not payload:
        return None

    explicit = payload.get(_STABLE_IDENTITY_KEY)
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    smartrecruiters = smartrecruiters_job_ad_identity(
        payload.get("wohnwerk_smartrecruiters_tenant"),
        payload.get("smartrecruiters_job_ad_id"),
    )
    if smartrecruiters is not None:
        return smartrecruiters

    return workday_requisition_identity(
        payload.get("wohnwerk_workday_tenant"),
        payload.get("wohnwerk_workday_site"),
        payload.get("workday_job_req_id"),
    )


def with_stable_identity(payload: dict[str, Any], identity: str | None) -> dict[str, Any]:
    """Return a copy with an explicit identity when one is available."""
    result = dict(payload)
    if identity:
        result[_STABLE_IDENTITY_KEY] = identity
    return result
