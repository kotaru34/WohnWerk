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


def card_thumbnail_url(card: Any, *, page_url: str) -> str | None:
    """Choose a balanced, source-backed preview image from one result card."""

    ranked: list[tuple[int, int, str]] = []
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

        score = 0
        if from_srcset:
            score += 6
        if node.tag == "img":
            score += 3
        if attributes.get("alt", "").strip():
            score += 2
        if any(token in marker_text for token in ("image", "photo", "gallery", "property")):
            score += 1
        if width is not None and width >= 300:
            score += 1

        ranked.append((score, -index, image_url))

    if not ranked:
        return None
    return max(ranked)[2]
