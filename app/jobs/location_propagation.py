from __future__ import annotations

from collections.abc import Iterable

from app.models import JobLocation


def normalized_city(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def resolved_postal_peer(
    target: JobLocation,
    candidates: Iterable[JobLocation],
) -> JobLocation | None:
    """Return one unambiguous resolved same-city peer for the same canonical job.

    Cross-source vacancies often preserve the same human locality while only one board
    exposes a PLZ. Reuse that stronger source-backed evidence only when every resolved peer
    for the exact same city agrees on one non-empty postal code. Conflicts fail closed.
    """
    city = normalized_city(target.city)
    if not city:
        return None

    peers = [
        item
        for item in candidates
        if item is not target
        and item.job_id == target.job_id
        and item.remote == target.remote
        and item.location is not None
        and item.postal_code
        and normalized_city(item.city) == city
    ]
    postal_codes = {item.postal_code for item in peers}
    if len(postal_codes) != 1:
        return None
    return peers[0]
