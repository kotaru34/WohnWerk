from app.property_images import _ImageMetaParser, _safe_http_url


def test_image_meta_parser_prefers_source_page_metadata() -> None:
    parser = _ImageMetaParser()
    parser.feed(
        """
        <html><head>
          <meta property="og:image" content="https://images.example.test/house.webp">
          <meta name="twitter:image" content="https://images.example.test/other.webp">
        </head></html>
        """
    )

    assert parser.image_url == "https://images.example.test/house.webp"


def test_image_fetch_rejects_obvious_local_and_private_targets() -> None:
    assert _safe_http_url("http://127.0.0.1/image.jpg") is None
    assert _safe_http_url("http://10.0.0.8/image.jpg") is None
    assert _safe_http_url("http://169.254.1.2/image.jpg") is None
    assert _safe_http_url("http://localhost/image.jpg") is None
    assert _safe_http_url("http://cache.local/image.jpg") is None
    assert _safe_http_url("file:///tmp/image.jpg") is None


def test_image_fetch_accepts_normal_public_http_urls() -> None:
    assert (
        _safe_http_url("https://images.example.test/property/123.webp")
        == "https://images.example.test/property/123.webp"
    )
