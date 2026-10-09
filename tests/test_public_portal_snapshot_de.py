"""Saved public-search snapshots are inspectable offline without false activation."""

import pytest

from scripts.inspect_public_portal_snapshot_de import inspect_saved_html

SNAPSHOT = """
<main>
<article><a href="/expose/9794876">
Haus mit Keller und Grundstück in Neubrandenburg</a>
<p>139.000 €Kaufpreis</p><p>17034 Neubrandenburg</p>
<p>Wohnfläche 96m² Grundstück 650m²</p></article>
<article><a href="/expose/10043535">Teurer Neubau am Stadtrand</a>
<p>310.000 €Kaufpreis</p><p>17034 Neubrandenburg</p></article>
</main>
"""


def test_offline_saved_immobilien_html_reports_candidates_not_confirmed_houses() -> None:
    results = inspect_saved_html(
        provider_name="immobilien-de",
        frontier_key="de-neubrandenburg",
        html=SNAPSHOT,
    )
    assert results["recognized_public_ids"] == 2
    assert results["eligible_price_card_ids"] == 1
    assert results["eligible_ids"] == ["9794876"]
    assert results["verified_existing_houses"] == 0
    assert results["production_activation_ready"] is False


def test_offline_snapshot_rejects_untrusted_shard_path() -> None:
    with pytest.raises(ValueError, match="Unknown/unvalidated"):
        inspect_saved_html(
            provider_name="immobilien-de",
            frontier_key="../../../../expose/9794876",
            html=SNAPSHOT,
        )
