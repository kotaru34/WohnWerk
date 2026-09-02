from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.jobs.location_propagation import resolved_postal_peer
from app.models import JobLocation


def main() -> None:
    with SessionLocal() as session:
        locations = list(session.scalars(select(JobLocation).order_by(JobLocation.job_id, JobLocation.id)))
        by_job: dict[int, list[JobLocation]] = {}
        for location in locations:
            by_job.setdefault(location.job_id, []).append(location)

        considered = 0
        propagated = 0
        for location in locations:
            if location.location is not None or not location.city:
                continue
            considered += 1
            peer = resolved_postal_peer(location, by_job.get(location.job_id, ()))
            if peer is None:
                continue
            location.postal_code = peer.postal_code
            location.location = peer.location
            propagated += 1
            print(
                f"job={location.job_id} location={location.id} city={location.city!r} "
                f"postal={peer.postal_code} evidence=resolved_same_city_peer"
            )

        session.commit()
        print(f"considered={considered}")
        print(f"propagated={propagated}")


if __name__ == "__main__":
    main()
