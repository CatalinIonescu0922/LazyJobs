from unittest.mock import patch

import pytest

from app.sources.extract import extract_jsonld
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


def test_fetch_rejects_non_https():
    with pytest.raises(FetchError, match="https"):
        SafeFetcher("example.com").get("http://example.com/jobs/1")


def test_fetch_rejects_private_dns():
    with patch("app.sources.fetch.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("169.254.169.254", 443))]):
        with pytest.raises(FetchError, match="blocked"):
            SafeFetcher("example.com").get("https://example.com/jobs/1")
