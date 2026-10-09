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
