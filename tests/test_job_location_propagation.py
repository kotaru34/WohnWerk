from types import SimpleNamespace

from app.jobs.location_propagation import resolved_postal_peer


def _location(
    *,
    job_id: int = 1,
    city: str = "Niederranna",
    postal: str | None = None,
    resolved: bool = False,
    remote: bool = False,
):
    return SimpleNamespace(
        job_id=job_id,
        city=city,
        postal_code=postal,
        location=object() if resolved else None,
        remote=remote,
    )


def test_reuses_unambiguous_resolved_same_city_postal() -> None:
    target = _location()
    peer = _location(postal="4085", resolved=True)

    assert resolved_postal_peer(target, [target, peer]) is peer


def test_conflicting_same_city_postals_fail_closed() -> None:
    target = _location()
    upper_austria = _location(postal="4085", resolved=True)
    lower_austria = _location(postal="3622", resolved=True)

    assert resolved_postal_peer(target, [target, upper_austria, lower_austria]) is None


def test_does_not_copy_resolution_between_different_jobs_or_remote_modes() -> None:
    target = _location(job_id=1, remote=False)
    other_job = _location(job_id=2, postal="4085", resolved=True)
    remote_peer = _location(job_id=1, postal="4085", resolved=True, remote=True)

    assert resolved_postal_peer(target, [target, other_job, remote_peer]) is None
