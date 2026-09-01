from types import SimpleNamespace

from app.jobs.location_cleanup import is_redundant_country_code_location


def _location(
    *,
    row_id: int,
    city: str | None,
    postal_code: str | None = None,
    location=None,
    remote: bool = False,
):
    return SimpleNamespace(
        id=row_id,
        city=city,
        postal_code=postal_code,
        location=location,
        remote=remote,
    )


def test_nonremote_at_artifact_is_redundant_when_job_has_concrete_sibling() -> None:
    artifact = _location(row_id=2, city="AT")
    salzburg = _location(row_id=1, city="Salzburg", location="POINT(13.04 47.80)")

    assert is_redundant_country_code_location(artifact, [salzburg, artifact]) is True


def test_country_code_is_kept_when_it_is_the_only_location_evidence() -> None:
    artifact = _location(row_id=2, city="AT")

    assert is_redundant_country_code_location(artifact, [artifact]) is False


def test_countrywide_remote_scope_is_not_pruned() -> None:
    remote_scope = _location(row_id=2, city="AT", remote=True)
    salzburg = _location(row_id=1, city="Salzburg", location="POINT(13.04 47.80)")

    assert is_redundant_country_code_location(remote_scope, [salzburg, remote_scope]) is False


def test_normal_unresolved_city_is_never_pruned_as_country_code() -> None:
    unresolved = _location(row_id=2, city="Kärnten")
    salzburg = _location(row_id=1, city="Salzburg", location="POINT(13.04 47.80)")

    assert is_redundant_country_code_location(unresolved, [salzburg, unresolved]) is False
