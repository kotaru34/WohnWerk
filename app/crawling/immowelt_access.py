"""Classify explicit Immowelt access restrictions without guessing CAPTCHA outcomes.

This module handles visible upstream responses only; it does not attempt to
solve challenges, modify browser fingerprints or change network routing.
"""

from __future__ import annotations

_RESTRICTION_PHRASES = (
    "der zugriff ist vorübergehend eingeschränkt",
    "your access has been temporarily restricted",
    "your access is temporarily restricted",
)


def immowelt_access_restricted(text: str) -> bool:
    """Return true only for an explicit provider restriction, not a generic CAPTCHA."""
    normalized = " ".join(text.casefold().split())
    return any(phrase in normalized for phrase in _RESTRICTION_PHRASES)
