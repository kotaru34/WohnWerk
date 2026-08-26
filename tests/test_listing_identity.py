from app.ingestion.listing_identity import stable_external_identity


def test_sreal_identity_ignores_scheme_www_slug_and_query() -> None:
    variants = [
        "http://sreal.at/de/immobilie/2838-2215/old-slug?tracking=1",
        "https://www.sreal.at/de/immobilie/2838-2215/new-slug",
        "https://sreal.at/de/immobilie/2838-2215/another-slug#ignored",
    ]

    assert {stable_external_identity(url) for url in variants} == {"sreal.at:2838-2215"}


def test_unknown_provider_has_no_stable_identity() -> None:
    assert stable_external_identity("https://example.com/de/immobilie/2838-2215/foo") is None
