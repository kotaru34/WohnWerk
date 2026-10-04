from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

_TARGET_WIDTH_PX = 720.0
_BAD_IMAGE_MARKERS = (
    "avatar",
    "badge",
    "icon",
    "logo",
    "placeholder",
    "profile",
    "sprite",
)
_POSITIVE_CONTAINER_MARKERS = (
    "gallery",
    "image",
    "media",
    "photo",
    "picture",
    "carousel",
)
_NEGATIVE_CONTAINER_MARKERS = (
    "agent",
    "broker",
    "brand",
    "company",
    "contact",
    "logo",
    "makler",
    "profile",
    "provider",
)
_LISTING_TOKEN_RE = re.compile(r"[a-z0-9äöüß]+", re.IGNORECASE)
_LISTING_STOPWORDS = {
    "zum",
    "zur",
    "kauf",
    "haus",
    "häuser",
    "einfamilienhaus",
    "mehrfamilienhaus",
    "reihenhaus",
    "doppelhaushälfte",
    "zimmer",
    "grundstück",
}


def _balanced_srcset_url(value: str) -> str | None:
    widths: list[tuple[float, float, str]] = []
    densities: list[tuple[float, float, str]] = []
    undescribed: list[str] = []

    for raw in value.split(","):
        parts = raw.strip().split()
        if not parts:
            continue
        url = parts[0]
        if len(parts) == 1:
            undescribed.append(url)
            continue
        descriptor = parts[-1].casefold()
        try:
            if descriptor.endswith("w"):
                width = float(descriptor[:-1])
                widths.append((abs(width - _TARGET_WIDTH_PX), width, url))
            elif descriptor.endswith("x"):
                density = float(descriptor[:-1])
                densities.append((abs(density - 1.5), -density, url))
            else:
                undescribed.append(url)
        except ValueError:
            undescribed.append(url)

    if widths:
        return min(widths, key=lambda item: (item[0], item[1]))[2]
    if densities:
        return min(densities, key=lambda item: (item[0], item[1]))[2]
    return undescribed[0] if undescribed else None


def _image_attr_candidate(attributes: dict[str, str]) -> tuple[str | None, bool]:
    for key in ("data-srcset", "srcset"):
        value = attributes.get(key, "").strip()
        if value and (candidate := _balanced_srcset_url(value)):
            return candidate, True
    for key in ("data-src", "data-lazy-src", "data-original", "src"):
        value = attributes.get(key, "").strip()
        if value and not value.casefold().startswith("data:"):
            return value, False
    return None, False


def _safe_image_url(value: str | None, *, page_url: str) -> str | None:
    if not value:
        return None
    absolute = urljoin(page_url, value)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return absolute


def _numeric_dimension(value: str | None) -> float | None:
    if not value:
        return None
    match = re.match(r"\s*(\d+(?:\.\d+)?)", value)
    return float(match.group(1)) if match else None


def _semantic_tokens(value: str | None) -> set[str]:
    if not value:
        return set()
    return {
        token
        for token in _LISTING_TOKEN_RE.findall(value.casefold())
        if len(token) >= 3 and token not in _LISTING_STOPWORDS
    }


def _container_marker_text(node: Any, *, depth: int = 5) -> str:
    parts: list[str] = []
    current = getattr(node, "parent", None)
    for _ in range(depth):
        if current is None:
            break
        attrs = getattr(current, "attrs", {}) or {}
        parts.extend(
            (
                str(attrs.get("data-testid", "")),
                str(attrs.get("class", "")),
                str(attrs.get("aria-label", "")),
            )
        )
        current = getattr(current, "parent", None)
    return " ".join(parts).casefold()


def _listing_affinity(attributes: dict[str, str], listing_text: str | None) -> tuple[int, bool]:
    listing_tokens = _semantic_tokens(listing_text)
    candidate_text = " ".join(
        (attributes.get("alt", ""), attributes.get("title", ""))
    ).strip()
    candidate_tokens = _semantic_tokens(candidate_text)
    overlap = len(listing_tokens & candidate_tokens)

    # Immowelt's real-estate photo alt text commonly carries listing facts while
    # broker logos carry only the provider name. Numeric listing evidence makes
    # that distinction stronger without hard-coding any broker brand.
    has_listing_measure = bool(
        re.search(r"\b\d[\d.,]*\s*(?:€|m(?:²|2))\b", candidate_text, re.IGNORECASE)
    )
    strong = overlap >= 2 or (overlap >= 1 and has_listing_measure)
    return overlap, strong


def card_thumbnail_url(
    card: Any,
    *,
    page_url: str,
    listing_text: str | None = None,
) -> str | None:
    """Choose the property photo, not arbitrary branding inside a result card."""

    ranked: list[tuple[int, int, int, str]] = []
    for index, node in enumerate(card.walk()):
        if node.tag not in {"img", "source"}:
            continue

        attributes = node.attrs
        raw_url, from_srcset = _image_attr_candidate(attributes)
        image_url = _safe_image_url(raw_url, page_url=page_url)
        if image_url is None:
            continue

        marker_text = " ".join(
            (
                attributes.get("alt", ""),
                attributes.get("title", ""),
                attributes.get("class", ""),
                image_url,
            )
        ).casefold()
        if any(marker in marker_text for marker in _BAD_IMAGE_MARKERS):
            continue

        width = _numeric_dimension(attributes.get("width"))
        height = _numeric_dimension(attributes.get("height"))
        if width is not None and height is not None and max(width, height) < 120:
            continue

        container_text = _container_marker_text(node)
        overlap, strong_listing_match = _listing_affinity(attributes, listing_text)

        score = 0
        if from_srcset:
            score += 6
        if node.tag == "img":
            score += 3
        if attributes.get("alt", "").strip():
            score += 2
        if any(token in marker_text for token in ("image", "photo", "gallery", "property")):
            score += 1
        if any(token in container_text for token in _POSITIVE_CONTAINER_MARKERS):
            score += 4
        if any(token in container_text for token in _NEGATIVE_CONTAINER_MARKERS):
            score -= 12
        score += min(12, overlap * 3)
        if width is not None and width >= 300:
            score += 1
        if width is not None and height is not None:
            smaller = min(width, height)
            larger = max(width, height)
            if larger <= 220 and smaller / max(larger, 1) >= 0.75:
                score -= 5

        # A semantic match with the exact card title outranks generic branding even
        # when the branding appears earlier in the DOM and has its own srcset.
        ranked.append((1 if strong_listing_match else 0, score, -index, image_url))

    if not ranked:
        return None
    return max(ranked)[3]
