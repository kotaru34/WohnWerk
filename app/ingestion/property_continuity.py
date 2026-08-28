from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PropertyContinuityObservation:
    token: Hashable
    postal_code: str | None
    title: str
    price_eur: Decimal | None
    living_area_m2: Decimal | None


@dataclass(frozen=True, slots=True)
class PropertyContinuityMatch:
    previous_token: Hashable
    current_token: Hashable
    strategy: str


def normalize_property_title(value: str) -> str:
    return " ".join(value.casefold().split())


def _strategy_key(
    row: PropertyContinuityObservation,
    strategy: str,
) -> tuple[object, ...] | None:
    postal_code = (row.postal_code or "").strip()
    title = normalize_property_title(row.title)
    if not postal_code or not title:
        return None

    if strategy == "exact":
        if row.price_eur is None and row.living_area_m2 is None:
            return None
        return postal_code, title, row.price_eur, row.living_area_m2

    if strategy == "title_area":
        if row.living_area_m2 is None or len(title) < 16:
            return None
        return postal_code, title, row.living_area_m2

    raise ValueError(f"Unknown continuity strategy: {strategy}")


def match_property_continuity(
    previous: list[PropertyContinuityObservation],
    current: list[PropertyContinuityObservation],
) -> list[PropertyContinuityMatch]:
    """Match property observations conservatively across mutable external URLs.

    The matcher is deliberately one-to-one and staged. At every stage a key is accepted
    only when exactly one unmatched previous row and exactly one unmatched current row
    share it. Provider rotation is accepted when the full metadata fingerprint matches or
    when postal code, title, and living area match exactly despite a price change.

    Price-only continuity is intentionally rejected. Production IMMMO audits showed that
    some downstream providers can expose plot/useful area in the field currently parsed as
    living area, producing very large apparent area changes for otherwise identical cards.
    """

    previous_remaining = {row.token: row for row in previous}
    current_remaining = {row.token: row for row in current}
    matches: list[PropertyContinuityMatch] = []

    for strategy in ("exact", "title_area"):
        previous_groups: dict[tuple[object, ...], list[Hashable]] = defaultdict(list)
        current_groups: dict[tuple[object, ...], list[Hashable]] = defaultdict(list)

        for token, row in previous_remaining.items():
            key = _strategy_key(row, strategy)
            if key is not None:
                previous_groups[key].append(token)

        for token, row in current_remaining.items():
            key = _strategy_key(row, strategy)
            if key is not None:
                current_groups[key].append(token)

        stage_matches: list[PropertyContinuityMatch] = []
        for key in previous_groups.keys() & current_groups.keys():
            old_tokens = previous_groups[key]
            new_tokens = current_groups[key]
            if len(old_tokens) != 1 or len(new_tokens) != 1:
                continue
            stage_matches.append(
                PropertyContinuityMatch(
                    previous_token=old_tokens[0],
                    current_token=new_tokens[0],
                    strategy=strategy,
                )
            )

        for match in stage_matches:
            previous_remaining.pop(match.previous_token, None)
            current_remaining.pop(match.current_token, None)
        matches.extend(stage_matches)

    return matches
