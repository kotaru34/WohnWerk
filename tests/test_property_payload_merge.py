from app.ingestion.properties import _merge_listing_payload


def test_sparse_discovery_preserves_detail_enrichment() -> None:
    existing = {
        "detail_enriched": True,
        "detail_living_area_m2": "120",
        "detail_plot_area_m2": "650",
        "detail_price_eur": "499000",
    }
    incoming = {
        "format": "sreal-search-discovery-v3",
        "search_metadata_complete": False,
    }

    merged = _merge_listing_payload(existing, incoming)

    assert merged["detail_enriched"] is True
    assert merged["detail_living_area_m2"] == "120"
    assert merged["detail_plot_area_m2"] == "650"
    assert merged["detail_price_eur"] == "499000"
    assert merged["search_metadata_complete"] is False


def test_transient_detail_failure_does_not_downgrade_previous_success() -> None:
    existing = {
        "detail_enriched": True,
        "detail_living_area_m2": "120",
    }
    incoming = {
        "detail_enriched": False,
        "detail_enrichment_error": "HTTPStatusError: temporary 503",
    }

    merged = _merge_listing_payload(existing, incoming)

    assert merged["detail_enriched"] is True
    assert merged["detail_living_area_m2"] == "120"
    assert "detail_enrichment_error" not in merged
    assert merged["detail_enrichment_last_error"] == "HTTPStatusError: temporary 503"


def test_successful_detail_refresh_clears_old_error() -> None:
    existing = {
        "detail_enriched": False,
        "detail_enrichment_error": "old error",
        "detail_enrichment_last_error": "older error",
    }
    incoming = {
        "detail_enriched": True,
        "detail_living_area_m2": "130",
    }

    merged = _merge_listing_payload(existing, incoming)

    assert merged["detail_enriched"] is True
    assert merged["detail_living_area_m2"] == "130"
    assert "detail_enrichment_error" not in merged
    assert "detail_enrichment_last_error" not in merged
