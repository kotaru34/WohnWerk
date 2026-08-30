from app.sources.job import successfactors

SITE = successfactors.SuccessFactorsSite(
    tenant="andritz-professionals",
    company="ANDRITZ",
    origin="https://careers.andritz.com",
    search_path="/go/Professionals/924202",
)


def test_search_page_extracts_total_and_austrian_row_context() -> None:
    html = """
    <html><body>
      <div>Results 26 – 50 of 446 Page 2 of 18</div>
      <table>
        <tr class="data-row">
          <td><a href="/andritz/job/Vienna-Mechanical-Engineer-Vien/1354678857/">Mechanical Engineer</a></td>
          <td>Vienna, Vienna, AT</td>
        </tr>
        <tr class="data-row">
          <td><a href="/andritz/job/Berlin-Software-Engineer-BE/1354679999/">Software Engineer</a></td>
          <td>Berlin, Berlin, DE</td>
        </tr>
      </table>
    </body></html>
    """

    postings, total = successfactors._parse_search_page(html, base_url=SITE.origin)

    assert total == 446
    assert len(postings) == 2
    assert postings[0].url.endswith("/1354678857/")
    assert "Vienna, Vienna, AT" in postings[0].row_text
    assert "Berlin, Berlin, DE" in postings[1].row_text


def test_parse_austrian_detail_uses_requisition_id_and_description() -> None:
    html = """
    <html><body>
      <h1>Bezeichnung: Senior Projektleiter (m/w/d) Wasserkraft</h1>
      <div>Job Familie:</div><div>Project &amp; Site Management</div>
      <div>Arbeitsvertraglicher Standort:</div><div>Vienna, Vienna, AT</div>
      <div>Beschreibung:</div>
      <p>Wir suchen eine technische Projektleitung.</p>
      <h2>IHRE AUFGABEN</h2>
      <ul><li>Projektleitung und Inbetriebnahme von Anlagen.</li></ul>
      <div>Ansprechperson:</div><div>Example Recruiter</div>
      <div>Stellenanforderungs-ID:</div><div>19221</div>
    </body></html>
    """

    job = successfactors.parse_successfactors_detail(
        html,
        site=SITE,
        url=(
            "https://careers.andritz.com/andritz/job/Vienna-Senior-Projektleiter-"
            "Vien/1352079157/"
        ),
    )

    assert job is not None
    assert job.source_listing_id == "andritz-professionals:19221"
    assert job.title == "Senior Projektleiter (m/w/d) Wasserkraft"
    assert job.company == "ANDRITZ"
    assert len(job.locations) == 1
    assert job.locations[0].city == "Vienna"
    assert job.locations[0].location_text == "Vienna, Vienna, AT"
    assert "technische Projektleitung" in (job.description or "")
    assert "Projektleitung und Inbetriebnahme" in (job.description or "")
    assert "Example Recruiter" not in (job.description or "")
    assert job.raw_payload["successfactors_requisition_id"] == "19221"
    assert (
        job.raw_payload["wohnwerk_stable_identity"]
        == "successfactors:andritz-professionals:req:19221"
    )


def test_parse_non_austrian_detail_is_filtered() -> None:
    html = """
    <html><body>
      <h1>Job title: Mechanical Engineer</h1>
      <div>Contract location:</div><div>Berlin, Berlin, DE</div>
      <div>Job description:</div><p>Mechanical product development.</p>
      <div>Job requisition ID:</div><div>999</div>
    </body></html>
    """

    job = successfactors.parse_successfactors_detail(
        html,
        site=SITE,
        url="https://careers.andritz.com/andritz/job/Berlin-Test/1350000000/",
    )

    assert job is None


def test_successfactors_source_shards_are_tenant_specific() -> None:
    source = successfactors.SuccessFactorsJobSource(
        sites=[
            SITE,
            successfactors.SuccessFactorsSite(
                tenant="other",
                company="Other AG",
                origin="https://jobs.example.com",
                search_path="/go/Professionals/123",
            ),
        ]
    )

    shards = source.default_shards()

    assert [shard.key for shard in shards] == ["andritz-professionals", "other"]
    assert shards[0].params["company"] == "ANDRITZ"
    assert shards[0].params["page_size"] == 25
