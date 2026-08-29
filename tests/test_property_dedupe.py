from decimal import Decimal

from app.models import Property
from app.property_dedupe import (
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
