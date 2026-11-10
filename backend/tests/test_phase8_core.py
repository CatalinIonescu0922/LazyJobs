from unittest.mock import patch

import httpx
import pytest

from app import llm
from app.sources.extract import _country_code, extract_jsonld
from app.sources.fetch import FetchError, SafeFetcher
from app.textnorm import fingerprint, normalise


JSONLD = b'''<script type="application/ld+json">{"@graph":[{"@type":"JobPosting","title":"Python Engineer (m/f)","description":"<p>Build services</p>","hiringOrganization":{"name":"Example SRL"},"jobLocation":{"address":{"addressLocality":"Cluj-Napoca","addressCountry":"RO"}},"datePosted":"2026-10-01","baseSalary":{"currency":"EUR","value":{"minValue":24000,"maxValue":36000,"unitText":"YEAR"}}}]}</script>'''


def test_normalise_and_fingerprint_are_stable():
    assert normalise("ERPA PREMIUM VISION S.R.L.") == "erpa premium vision"
    assert fingerprint("Example SRL", "Python Engineer (m/f)", "Cluj") == fingerprint("Example", "Python Engineer", "Cluj")
    assert fingerprint("Example", "Python Engineer", "Cluj") != fingerprint("Example", "Python Engineer", "Bucharest")


def test_extract_jsonld_graph_salary_and_plain_description():
    posting = extract_jsonld(JSONLD, url="https://example.com/jobs/1", source="example.com")
    assert posting is not None
    assert posting.title == "Python Engineer (m/f)"
    assert posting.description == "Build services"
    assert posting.eligible_countries == ["RO"]
    assert posting.salary_min == 2000
    assert posting.salary_max == 3000


def test_country_values_are_real_iso_alpha2_codes():
    assert _country_code("RO") == "RO"
    assert _country_code("DE") == "DE"
    assert _country_code("Romania") == "RO"
    assert _country_code("XX") == ""
    assert _country_code("Anywhere") == ""
    assert _country_code("Worldwide") == ""


def test_fetch_rejects_non_https():
    with pytest.raises(FetchError, match="https"):
        SafeFetcher("example.com").get("http://example.com/jobs/1")


def test_fetch_rejects_private_dns():
    with patch("app.sources.fetch.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("169.254.169.254", 443))]):
        with pytest.raises(FetchError, match="blocked"):
            SafeFetcher("example.com").get("https://example.com/jobs/1")


def test_robots_parser_accepts_httpx_response_url():
    response = httpx.Response(
        200,
        text="User-agent: *\nAllow: /\n",
        request=httpx.Request("GET", "https://example.com/robots.txt"),
    )
    fetcher = SafeFetcher("example.com")
    with patch.object(fetcher, "_fetch_robots", return_value=response):
        assert fetcher._allowed("https://example.com/jobs/1", "example.com")


def test_extract_profile_retries_a_transient_vertex_failure():
    response = type("Response", (), {"text": '{"full_name":"Ada Lovelace","headline":"Engineer","summary":"","titles":[],"skills":[],"years_experience":0,"country":"","city":"","salary_currency":""}'})()
    client = type("Client", (), {"models": type("Models", (), {"generate_content": lambda self, **kwargs: response})()})()

    with patch.object(llm.settings, "google_cloud_project", "project"), patch.object(
        llm.genai, "Client", side_effect=[RuntimeError("credentials warming up"), client]
    ) as create_client:
        extracted = llm.extract_profile("Ada Lovelace")

    assert extracted.full_name == "Ada Lovelace"
    assert create_client.call_count == 2


def test_post_json_sends_the_body_and_never_touches_the_cache(real_client):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.content))
        return httpx.Response(200, json={"ok": True})

    fetcher = SafeFetcher("example.com")
    with patch("app.sources.fetch.httpx.Client", side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs)), patch.object(
        fetcher, "_allowed", return_value=True
    ), patch.object(fetcher, "_check_address"), patch.object(fetcher, "_polite_wait"):
        fetcher.post_json("https://example.com/jobs", {"q": 1})
        fetcher.post_json("https://example.com/jobs", {"q": 2})

    assert [method for method, _ in seen] == ["POST", "POST"]
    assert b'"q":2' in seen[1][1].replace(b" ", b"")
