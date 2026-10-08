from __future__ import annotations

from email.message import EmailMessage

import pytest

from app.crawling.immowelt_mail_alerts import (
    canonical_alert_url,
    extract_alert_files,
    extract_alert_listings,
)

EXPOSE_ID = "12345678-1234-1234-1234-123456789abc"
OTHER_ID = "abcdef123456"


def _message(*, plain: str = "", html: str | None = None) -> bytes:
    m = EmailMessage()
    m["From"] = "Hinweis <updates@immowelt.de>"
    m["To"] = "private@example.invalid"
    m["Subject"] = "Your saved search"
    m.set_content(plain)
    if html is not None:
        m.add_alternative(html, subtype="html")
    return m.as_bytes()


@pytest.mark.parametrize(
    "url",
    [
        "http://www.immowelt.de/expose/" + EXPOSE_ID,
        "https://www.immowelt.de.evil.invalid/expose/" + EXPOSE_ID,
        "https://click.example.invalid/?next=https://www.immowelt.de/expose/" + EXPOSE_ID,
        "https://www.immowelt.de@evil.invalid/expose/" + EXPOSE_ID,
        "https://www.immowelt.de:8443/expose/" + EXPOSE_ID,
        "https://www.immowelt.de/projekte/expose/" + EXPOSE_ID,
        "https://www.immowelt.de/expose/not-an-offer",
        "javascript:alert(1)",
    ],
)
def test_reject_unsafe_or_unsupported_urls(url: str) -> None:
    assert canonical_alert_url(url) is None


def test_canonicalize_supported_expose_link_without_tracking_query() -> None:
    assert canonical_alert_url(
        "https://immowelt.de/expose/" + EXPOSE_ID.upper() + "?utm_source=mail#hero"
    ) == (EXPOSE_ID, "https://www.immowelt.de/expose/" + EXPOSE_ID)


def test_extract_html_and_plain_text_deduplicates_without_external_requests() -> None:
    mail = _message(
        plain="Saved listing: https://www.immowelt.de/expose/" + EXPOSE_ID,
        html=(
            '<a href="https://www.immowelt.de/expose/' + EXPOSE_ID + '?t=email">'
            "Kleines Haus in Dresden</a>"
            '<a href="https://click.example.invalid/track?id=' + OTHER_ID + '">'
            "Tracked offer</a>"
            '<a href="https://www.immowelt.de/expose/' + OTHER_ID + '">'
            "Haus in Berlin</a>"
            '<a href="https://evil.invalid/">Privacy link</a>'
        ),
    )
    items = extract_alert_listings(mail)
    assert len(items) == 2
    assert [p.source_listing_id for p in items] == [EXPOSE_ID, OTHER_ID]
    assert items[0].title == "Kleines Haus in Dresden"
    assert items[1].title == "Haus in Berlin"
    assert items[0].url == "https://www.immowelt.de/expose/" + EXPOSE_ID


def test_malformed_attachment_does_not_trigger_fetch() -> None:
    m = EmailMessage()
    m.set_content("No offers here")
    m.add_attachment(
        b"https://www.immowelt.de/expose/" + EXPOSE_ID.encode(),
        maintype="application",
        subtype="octet-stream",
        filename="hidden.eml",
    )
    assert extract_alert_listings(m.as_bytes()) == []


def test_local_batch_dedup_and_reject_other_files(tmp_path) -> None:
    first = tmp_path / "one.eml"
    second = tmp_path / "two.eml"
    first.write_bytes(_message(plain="https://www.immowelt.de/expose/" + EXPOSE_ID))
    second.write_bytes(
        _message(
            html='<a href="https://www.immowelt.de/expose/'
            + EXPOSE_ID
            + '">Ein schönes Haus</a>'
        )
    )
    result = extract_alert_files([first, second])
    assert len(result) == 1
    assert result[0].title == "Ein schönes Haus"
    with pytest.raises(ValueError, match="Expected .eml"):
        extract_alert_files([tmp_path / "not-email.txt"])
