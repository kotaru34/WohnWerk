from decimal import Decimal

from app.models import Property
from app.property_dedupe import (
    cross_source_duplicate_strategy,
    normalize_property_title,
    properties_have_compatible_duplicate_facts,
    property_duplicate_key,
)


def test_normalizes_syndicated_neuhofen_title_typography() -> None:
    left = "Neuhofen/Krems-Bieterverfahren - Sanierungsobjekt – Top Ruhelage"
    right = "Neuhofen /Krems-Bieterverfahren - Sanierungsobjekt - Top Ruhelage"

    assert normalize_property_title(left) == normalize_property_title(right)
    assert property_duplicate_key(
        postal_code="4501",
        price_eur=Decimal(200000),
        title=left,
    ) == property_duplicate_key(
        postal_code="4501",
        price_eur=Decimal("200000.00"),
        title=right,
    )


def test_short_generic_property_title_never_becomes_duplicate_key() -> None:
    assert property_duplicate_key(
        postal_code="4501",
        price_eur=Decimal(200000),
        title="Einfamilienhaus",
    ) is None


def test_explicit_conflicting_area_rejects_otherwise_equal_duplicate() -> None:
    left = Property(
        title="Neuhofen/Krems-Bieterverfahren - Sanierungsobjekt – Top Ruhelage",
        postal_code="4501",
        price_eur=Decimal(200000),
        plot_area_m2=Decimal(763),
    )
    compatible = Property(
        title="Neuhofen /Krems-Bieterverfahren - Sanierungsobjekt - Top Ruhelage",
        postal_code="4501",
        price_eur=Decimal(200000),
        plot_area_m2=None,
    )
    conflicting = Property(
        title="Neuhofen /Krems-Bieterverfahren - Sanierungsobjekt - Top Ruhelage",
        postal_code="4501",
        price_eur=Decimal(200000),
        plot_area_m2=Decimal(900),
    )

    assert properties_have_compatible_duplicate_facts(left, compatible)
    assert not properties_have_compatible_duplicate_facts(left, conflicting)



def test_exact_duplicate_key_supports_german_five_digit_plz() -> None:
    key = property_duplicate_key(
        postal_code="01067",
        price_eur=Decimal(135000),
        title="Kleines Einfamilienhaus am Elbhang mit großem Garten",
    )

    assert key is not None
    assert key.postal_code == "01067"


def test_cross_source_match_accepts_rewritten_title_with_two_numeric_area_facts() -> None:
    candidate = Property(
        title="Sanierungsobjekt mit großem Garten in ruhiger Lage bei Dresden",
        postal_code="01067",
        price_eur=Decimal(135000),
        living_area_m2=Decimal("106.2"),
        plot_area_m2=Decimal(581),
    )

    strategy = cross_source_duplicate_strategy(
        candidate,
        postal_code="01067",
        price_eur=Decimal(135500),
        title="Haus mit Garten in Dresden - viel Potenzial für Handwerker",
        living_area_m2=Decimal(106),
        plot_area_m2=Decimal(580),
    )

    assert strategy == "postal_price_living_plot_title"


def test_cross_source_match_rejects_conflicting_explicit_area() -> None:
    candidate = Property(
        title="Sanierungsobjekt mit großem Garten in ruhiger Lage bei Dresden",
        postal_code="01067",
        price_eur=Decimal(135000),
        living_area_m2=Decimal(106),
        plot_area_m2=Decimal(581),
    )

    assert cross_source_duplicate_strategy(
        candidate,
        postal_code="01067",
        price_eur=Decimal(135000),
        title="Sanierungsobjekt mit großem Garten in ruhiger Lage bei Dresden",
        living_area_m2=Decimal(145),
        plot_area_m2=Decimal(581),
    ) is None


def test_cross_source_match_does_not_merge_on_price_and_plz_alone() -> None:
    candidate = Property(
        title="Einfamilienhaus am Ortsrand",
        postal_code="01067",
        price_eur=Decimal(135000),
    )

    assert cross_source_duplicate_strategy(
        candidate,
        postal_code="01067",
        price_eur=Decimal(135000),
        title="Ein anderes Haus",
        living_area_m2=None,
        plot_area_m2=None,
    ) is None
