"""Read-only public source inspector does not require a database or login."""

from app.sources.property.public_portals_de import (
    ImmobilienDeGermanyPropertySource,
    OhneMaklerGermanyPropertySource,
)
from scripts.inspect_public_portals_de import selected_shards


def test_inspector_defaults_to_one_public_page_per_provider() -> None:
    for adapter in (OhneMaklerGermanyPropertySource(), ImmobilienDeGermanyPropertySource()):
        assert [s.key for s in selected_shards(adapter, regional=False)] == [
            "de-public-frontier"
        ]


def test_inspector_can_explicitly_include_whitelisted_regional_pages() -> None:
    adapter = ImmobilienDeGermanyPropertySource()
    assert len(selected_shards(adapter, regional=True)) == 5
    assert {s.key for s in selected_shards(adapter, regional=True)} == set(
        adapter.frontier_paths()
    )


def test_staged_public_portals_are_not_automatically_scheduled() -> None:
    from app.refresh import source_is_scheduled, source_operational_note

    for name in ("ohne-makler-de", "immobilien-de"):
        assert source_is_scheduled(name) is False
        note = source_operational_note(name)
        assert note is not None
        assert "Gesamtpreis" in note


def test_inspector_can_probe_exactly_one_known_region() -> None:
    adapter = OhneMaklerGermanyPropertySource()
    shards = selected_shards(
        adapter, regional=False, frontier_key="de-mecklenburg-vorpommern"
    )
    assert len(shards) == 1
    assert shards[0].key == "de-mecklenburg-vorpommern"


def test_inspector_refuses_unlisted_region_paths() -> None:
    import pytest

    with pytest.raises(ValueError, match="Unknown whitelisted frontier"):
        selected_shards(
            ImmobilienDeGermanyPropertySource(),
            regional=True,
            frontier_key="../../admin",
        )
