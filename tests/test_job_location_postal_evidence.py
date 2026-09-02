import json

from app.jobs.location_postal_evidence import explicit_postal_for_locality
from app.sources.job.karriere_at import parse_karriere_detail_page


def test_explicit_postal_for_locality_requires_unique_adjacent_evidence() -> None:
    assert (
        explicit_postal_for_locality(
            "<div>Global Hydro Energy GmbH<br>4085 Niederranna 41. Austria</div>",
            "Niederranna",
        )
        == "4085"
    )
    assert (
        explicit_postal_for_locality(
            "<div>4085 Niederranna</div><div>3622 Niederranna</div>",
            "Niederranna",
        )
        is None
    )
    assert explicit_postal_for_locality("<div>4085 Wesenufer</div>", "Niederranna") is None


def test_karriere_recovers_postal_printed_next_to_exact_dienstort() -> None:
    posting = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Mechanischer Konstrukteur (m/w/d)",
        "description": "<p>Konstruktion von Wasserkraftanlagen.</p>",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Global Hydro Energy GmbH",
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Niederranna",
                "addressCountry": "AT",
            },
        },
    }
    content = (
        "<html><head>"
        f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        "</head><body>"
        "<div>Dienstort</div><div>Niederranna</div>"
        "<footer>Global Hydro Energy GmbH 4085 Niederranna 41. Austria</footer>"
        "</body></html>"
    )

    job = parse_karriere_detail_page(
        content,
        job_id="10025898",
        url="https://www.karriere.at/jobs/10025898",
        search_title="Mechanischer Konstrukteur (m/w/d)",
        search_label="Mechanischer Konstrukteur",
    )

    assert len(job.locations) == 1
    assert job.locations[0].city == "Niederranna"
    assert job.locations[0].postal_code == "4085"
    # Preserve the source's human-readable locality rather than relabelling it as the
    # RTR delivery-office name (4085 is commonly listed as Wesenufer there).
    assert job.locations[0].location_text == "Niederranna, AT"
