from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GermanRegion:
    key: str
    label: str
    immoscout_slug: str
    immowelt_location_id: str


@dataclass(frozen=True, slots=True)
class PropertyPriceBand:
    key: str
    minimum_eur: int
    maximum_eur: int


# The city states use Immowelt's public city location IDs because its public SEO
# taxonomy does not expose a separate state root for them.  Those locations still
# cover the complete state because Berlin, Bremen and Hamburg are city states.
GERMAN_REGIONS: tuple[GermanRegion, ...] = (
    GermanRegion("baden-wuerttemberg", "Baden-Württemberg", "baden-wuerttemberg", "AD04DE8"),
    GermanRegion("bayern", "Bayern", "bayern", "AD04DE9"),
    GermanRegion("berlin", "Berlin", "berlin", "AD08DE8634"),
    GermanRegion("brandenburg", "Brandenburg", "brandenburg", "AD04DE12"),
    GermanRegion("bremen", "Bremen", "bremen", "AD08DE2110"),
    GermanRegion("hamburg", "Hamburg", "hamburg", "AD08DE1113"),
    GermanRegion("hessen", "Hessen", "hessen", "AD04DE6"),
    GermanRegion(
        "mecklenburg-vorpommern",
        "Mecklenburg-Vorpommern",
        "mecklenburg-vorpommern",
        "AD04DE13",
    ),
    GermanRegion("niedersachsen", "Niedersachsen", "niedersachsen", "AD04DE3"),
    GermanRegion(
        "nordrhein-westfalen",
        "Nordrhein-Westfalen",
        "nordrhein-westfalen",
        "AD04DE5",
    ),
    GermanRegion("rheinland-pfalz", "Rheinland-Pfalz", "rheinland-pfalz", "AD04DE7"),
    GermanRegion("saarland", "Saarland", "saarland", "AD04DE10"),
    GermanRegion("sachsen", "Sachsen", "sachsen", "AD04DE14"),
    GermanRegion("sachsen-anhalt", "Sachsen-Anhalt", "sachsen-anhalt", "AD04DE15"),
    GermanRegion("schleswig-holstein", "Schleswig-Holstein", "schleswig-holstein", "AD04DE1"),
    GermanRegion("thueringen", "Thüringen", "thueringen", "AD04DE16"),
)


GERMANY_PROPERTY_MIN_PRICE_EUR = 30_000
GERMANY_PROPERTY_MAX_PRICE_EUR = 200_000


# The current Germany acquisition target is intentionally split into three contiguous,
# non-overlapping bands. The narrower low-price band reduces the largest legacy shard
# while preserving the existing 16 regions x 3 bands scheduler shape. Provider result
# caps remain authoritative: a capped/incomplete shard never gains disappearance authority.
PROPERTY_PRICE_BANDS: tuple[PropertyPriceBand, ...] = (
    PropertyPriceBand("030000-099999", GERMANY_PROPERTY_MIN_PRICE_EUR, 99_999),
    PropertyPriceBand("100000-149999", 100_000, 149_999),
    PropertyPriceBand("150000-200000", 150_000, GERMANY_PROPERTY_MAX_PRICE_EUR),
)


REGIONS_BY_KEY = {region.key: region for region in GERMAN_REGIONS}
PRICE_BANDS_BY_KEY = {band.key: band for band in PROPERTY_PRICE_BANDS}
