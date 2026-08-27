import importlib.util
import json
from pathlib import Path

import httpx
import pytest


def _load_verifier_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_lever_candidates.py"
    spec = importlib.util.spec_from_file_location("verify_lever_candidates", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_verifier = _load_verifier_module()
_api_base = _verifier._api_base
_load_candidates = _verifier._load_candidates
_verify_feed = _verifier._verify_feed


def _posting(posting_id: str, *, country: str, location: str) -> dict:
    return {
        "id": posting_id,
        "text": "Mechanical Design Engineer",
        "hostedUrl": f"https://jobs.lever.co/example/{posting_id}",
        "country": country,
        "categories": {
            "location": location,
            "allLocations": [location],
        },
    }


def test_load_lever_candidates_uses_namespace_as_part_of_identity(tmp_path: Path) -> None:
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps(
            [
                {"tenant": "example", "company": "Example EU", "namespace": "eu"},
                {
                    "tenant": "example",
                    "company": "Example Global",
                    "namespace": "global",
                },
            ]
        ),
        encoding="utf-8",
    )

    rows = _load_candidates(path)

    assert [(row["namespace"], row["tenant"]) for row in rows] == [
        ("eu", "example"),
        ("global", "example"),
    ]


def test_load_lever_candidates_rejects_unknown_namespace(tmp_path: Path) -> None:
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps([{"tenant": "example", "company": "Example", "namespace": "us"}]),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="invalid Lever namespace"):
        _load_candidates(path)


def test_lever_candidate_verification_traverses_to_completion() -> None:
    requests: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        skip = int(request.url.params["skip"])
        requests.append(skip)
        if skip == 0:
            return httpx.Response(
                200,
                json=[
                    _posting("at-1", country="AT", location="Graz"),
                    _posting("de-1", country="DE", location="Munich, Germany"),
                ],
            )
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        verified = _verify_feed(
            client,
            tenant="example",
            company="Example GmbH",
            namespace="global",
            delay=0,
            page_size=2,
            hard_max_pages=5,
        )

    assert verified == (
        "https://api.lever.co/v0/postings/example",
        2,
        1,
        2,
    )
    assert requests == [0, 2]


def test_lever_candidate_verification_rejects_incomplete_capped_feed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        skip = int(request.url.params["skip"])
        return httpx.Response(
            200,
            json=[
                _posting(f"at-{skip}", country="AT", location="Vienna, Austria"),
                _posting(f"at-{skip + 1}", country="AT", location="Graz, Austria"),
            ],
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        verified = _verify_feed(
            client,
            tenant="example",
            company="Example GmbH",
            namespace="eu",
            delay=0,
            page_size=2,
            hard_max_pages=2,
        )

    assert verified is None
    assert _api_base("eu") == "https://api.eu.lever.co/v0/postings"
    assert _api_base("global") == "https://api.lever.co/v0/postings"
