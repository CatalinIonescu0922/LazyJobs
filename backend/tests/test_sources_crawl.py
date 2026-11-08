from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.models import JobSource
from app.sources import crawl
from app.sources.fetch import FetchError, FetchResult
from app.sources.posting import Posting

NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
POSTING_PAGE = b'<script type="application/ld+json">{"@type":"JobPosting","title":"DevOps Engineer","description":"<p>Run CI</p>","hiringOrganization":{"name":"Acme"}}</script>'
LANDING_PAGE = b"<html><body>Jobs in Arad</body></html>"


def urlset(*urls: str) -> bytes:
    return f"<urlset {NS}>{''.join(f'<url><loc>{url}</loc></url>' for url in urls)}</urlset>".encode()


def index(*urls: str) -> bytes:
    return f"<sitemapindex {NS}>{''.join(f'<sitemap><loc>{url}</loc></sitemap>' for url in urls)}</sitemapindex>".encode()


class FakeFetcher:
    def __init__(self, pages: dict[str, bytes]):
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url: str, *, sitemap: bool = False) -> FetchResult:
        self.requested.append(url)
        if url not in self.pages:
            raise FetchError("source returned 404")
        return FetchResult(url, 200, self.pages[url], "text/xml")


def validate(pages: dict[str, bytes], root: str = "https://board.ro/sitemap.xml") -> tuple[JobSource, FakeFetcher]:
    fetcher = FakeFetcher(pages)
    source = JobSource(domain="board.ro", sitemap_url=root, kind="board", status="candidate", reason="", extraction="", posting_prefix="")
    with patch.object(crawl, "SafeFetcher", return_value=fetcher):
        crawl.validate_source(MagicMock(), source)
    return source, fetcher


def test_read_sitemap_separates_child_sitemaps_from_pages():
    fetcher = FakeFetcher({"https://board.ro/index.xml": index("https://board.ro/a.xml"), "https://board.ro/a.xml": urlset("https://board.ro/jobs/1")})
    assert crawl.read_sitemap(fetcher, "https://board.ro/index.xml") == (["https://board.ro/a.xml"], [])
    assert crawl.read_sitemap(fetcher, "https://board.ro/a.xml") == ([], [("https://board.ro/jobs/1", None)])


def test_read_sitemap_reports_invalid_xml_in_plain_words():
    with pytest.raises(FetchError, match="not valid XML"):
        crawl.read_sitemap(FakeFetcher({"https://board.ro/x": b"<html>"}), "https://board.ro/x")


def test_job_sitemaps_drop_landing_page_files_and_keep_posting_files():
    bestjobs = [f"https://www.bestjobs.eu/sitemap/sitemap.{name}.xml" for name in ("pages", "jobs_by_cities.ro", "jobs_by_employer.ro", "jobs.ro", "jobs.en", "jobs_by_skills.ro")]
    assert crawl.job_sitemaps(bestjobs) == ["https://www.bestjobs.eu/sitemap/sitemap.jobs.ro.xml", "https://www.bestjobs.eu/sitemap/sitemap.jobs.en.xml"]
    hipo = [f"https://www.hipo.ro/sitemap_{name}.xml" for name in ("general", "cities", "joburi", "lastjobs", "articles", "employers")]
    assert crawl.job_sitemaps(hipo) == ["https://www.hipo.ro/sitemap_joburi.xml", "https://www.hipo.ro/sitemap_lastjobs.xml"]
    assert crawl.job_sitemaps(["https://x.ro/sitemap-expired-listings.xml", "https://x.ro/sitemap-listings-it.xml"]) == ["https://x.ro/sitemap-listings-it.xml"]


def test_numbered_shards_take_the_first_ones_without_asking_the_model():
    shards = [f"https://remoteok.com/sitemap-jobs-{n}.xml" for n in range(1, 16)]
    with patch.object(crawl, "pick_sitemaps", side_effect=AssertionError("model must not be called")):
        assert crawl._choose_sitemaps(shards, ["python"]) == shards[: crawl.MAX_JOB_SITEMAPS]


def test_category_sitemaps_use_the_model_choice_and_survive_its_failure():
    categories = [f"https://ejobs.ro/sitemap-listings-{name}.xml" for name in ("achizitii", "agricultura", "banci", "it-software", "juridic", "marketing", "telecomunicatii")]
    with patch.object(crawl, "pick_sitemaps", return_value=[categories[3], categories[6]]):
        assert crawl._choose_sitemaps(categories, ["devops"]) == [categories[3], categories[6]]
    with patch.object(crawl, "pick_sitemaps", side_effect=RuntimeError("vertex down")):
        assert crawl._choose_sitemaps(categories, ["devops"]) == categories[: crawl.MAX_JOB_SITEMAPS]


def test_few_candidates_are_all_read_without_asking_the_model():
    candidates = ["https://hipo.ro/sitemap_joburi.xml", "https://hipo.ro/sitemap_lastjobs.xml"]
    with patch.object(crawl, "pick_sitemaps", side_effect=AssertionError("model must not be called")):
        assert crawl._choose_sitemaps(candidates, []) == candidates


def test_common_prefix_stops_at_the_first_differing_folder():
    urls = [
        "https://www.hipo.ro/locuri-de-munca/locuri_de_munca/273795/BCR/Partener",
        "https://www.hipo.ro/locuri-de-munca/locuri_de_munca/273796/BCR/Analyst",
    ]
    assert crawl._common_prefix(urls) == "https://www.hipo.ro/locuri-de-munca/locuri_de_munca/"
    assert crawl._common_prefix(["https://x.ro/a/1", "https://x.ro/b/2"]) == ""


def test_rank_puts_profile_matches_first_then_newest():
    entries = [
        ("https://x.ro/jobs/sales-agent-1", "2026-11-08"),
        ("https://x.ro/jobs/devops-engineer-2", "2026-11-01"),
        ("https://x.ro/jobs/kubernetes-devops-3", "2026-10-01"),
        ("https://x.ro/jobs/driver-4", "2026-11-07"),
    ]
    ranked = [url for url, _ in crawl._rank(entries, ["DevOps Engineering", "Kubernetes"])]
    assert ranked == ["https://x.ro/jobs/kubernetes-devops-3", "https://x.ro/jobs/devops-engineer-2", "https://x.ro/jobs/sales-agent-1", "https://x.ro/jobs/driver-4"]


def test_rank_never_reaches_past_the_freshest_window_for_a_relevant_old_url():
    fresh = [(f"https://x.ro/jobs/driver-{n}", "2026-11-08") for n in range(crawl.MAX_POSTINGS * 3)]
    old_match = ("https://x.ro/jobs/devops-engineer-0", "2020-01-01")
    ranked = crawl._rank([*fresh, old_match], ["DevOps"])
    assert old_match not in ranked


def test_rank_keeps_document_order_when_lastmod_is_missing():
    entries = [(f"https://x.ro/jobs/role-{n}", "1970-01-01T00:00:00+00:00") for n in range(5)]
    assert crawl._rank(entries, [])[:3] == entries[:3]


def test_validation_skips_a_landing_page_sitemap_and_records_the_posting_prefix():
    landing = [f"https://board.ro/jobs/in/{city}" for city in ("arad", "cluj", "iasi", "oradea")]
    postings = [f"https://board.ro/locuri/{n}/devops-{n}" for n in range(100, 106)]
    pages = {
        "https://board.ro/sitemap.xml": index("https://board.ro/sitemap_pages.xml", "https://board.ro/sitemap_joburi.xml", "https://board.ro/sitemap_lastjobs.xml"),
        "https://board.ro/sitemap_joburi.xml": urlset(*landing),
        "https://board.ro/sitemap_lastjobs.xml": urlset(*postings),
        **{url: LANDING_PAGE for url in landing},
        **{url: POSTING_PAGE for url in postings},
    }
    source, fetcher = validate(pages)
    assert (source.status, source.reason, source.extraction) == ("active", "", "jsonld")
    assert source.sitemap_url == "https://board.ro/sitemap.xml"
    assert source.posting_prefix == "https://board.ro/locuri/"
    assert "https://board.ro/sitemap_pages.xml" not in fetcher.requested


def test_validation_of_a_flat_sitemap_samples_past_the_home_page():
    postings = [f"https://remote.example/remote-jobs/role-{n}" for n in range(20)]
    pages = {"https://board.ro/sitemap.xml": urlset("https://remote.example/", *postings), **{url: POSTING_PAGE for url in postings}}
    source, fetcher = validate(pages)
    assert source.status == "active"
    assert source.posting_prefix == "https://remote.example/remote-jobs/"
    assert "https://remote.example/" not in fetcher.requested


def test_validation_of_a_mixed_flat_sitemap_samples_the_job_folder():
    jobs = [f"https://remote.example/remote-jobs/role-{n}" for n in range(6)]
    companies = [f"https://remote.example/company/firm-{n}" for n in range(30)]
    articles = [f"https://remote.example/day-in-the-life-{n}" for n in range(10)]
    pages = {
        "https://board.ro/sitemap.xml": urlset("https://remote.example/", *companies, *jobs, *articles),
        **{url: POSTING_PAGE for url in jobs},
        **{url: LANDING_PAGE for url in companies + articles},
    }
    source, _ = validate(pages)
    assert source.status == "active"
    assert source.posting_prefix == "https://remote.example/remote-jobs/"


def test_validation_handles_postings_without_a_folder():
    postings = [f"https://board.ro/devops-engineer-{n}" for n in range(6)]
    pages = {"https://board.ro/sitemap.xml": urlset(*postings), **{url: POSTING_PAGE for url in postings}}
    source, _ = validate(pages)
    assert source.status == "active"
    assert source.posting_prefix == ""


def test_validation_reports_missing_structured_data_in_plain_words():
    postings = [f"https://board.ro/loc-de-munca/job-{n}" for n in range(6)]
    pages = {"https://board.ro/sitemap.xml": urlset(*postings), **{url: LANDING_PAGE for url in postings}}
    source, _ = validate(pages)
    assert source.status == "failed"
    assert source.reason == "job pages have no JobPosting data"


def test_validation_reports_a_block_instead_of_blaming_the_pages():
    postings = [f"https://board.ro/jobs/{n}" for n in range(6)]
    pages = {"https://board.ro/sitemap.xml": urlset(*postings)}
    source, _ = validate(pages)
    assert source.status == "failed"
    assert source.reason == "source returned 404"


def test_validation_without_job_sitemaps_says_so():
    pages = {"https://board.ro/sitemap.xml": index("https://board.ro/sitemap_pages.xml", "https://board.ro/sitemap_articles.xml")}
    source, _ = validate(pages)
    assert source.status == "failed"
    assert source.reason == "no job sitemap found"


def test_missing_sitemap_names_the_cause():
    fetcher = FakeFetcher({"https://board.ro/robots.txt": b"User-agent: *\nAllow: /\n"})
    with pytest.raises(FetchError, match=r"no sitemap found \(source returned 404\)"):
        crawl.discover_sitemap(fetcher, "board.ro")


def test_pasted_workday_url_gets_one_domain_per_careers_site():
    from app.routers.sources import _ats_domain
    from app.sources.ats import parse_ats_url

    feed = parse_ats_url("https://accenture.wd103.myworkdayjobs.com/en-US/AccentureCareers/job/x")
    assert _ats_domain(feed) == "accenturecareers.accenture.myworkdayjobs.com"
    other = parse_ats_url("https://accenture.wd103.myworkdayjobs.com/AvanadeCareers")
    assert _ats_domain(other) != _ats_domain(feed)
    assert _ats_domain(parse_ats_url("https://boards.greenhouse.io/BearingPoint")) == "bearingpoint.greenhouse.io"


def test_career_failure_reason_names_an_unsupported_ats_and_a_rejected_linked_feed():
    from app.sources.career import _failure_reason

    page = b'<a href="https://career5.successfactors.eu/careers?company=Atos">Jobs</a>'
    assert _failure_reason([("https://atos.example/", page)]) == "careers site uses SuccessFactors, which is not supported yet"
    workday = b'<a href="https://flextronics.wd1.myworkdayjobs.com/Careers">Jobs</a>'
    assert _failure_reason([("https://flex.example/", workday)]) == "linked Workday feed has no posting in your country or cannot be read"


def make_posting(url: str, source: str = "board.ro") -> Posting:
    return Posting(
        source=source, external_id=url, url=url, apply_url=url, title="DevOps Engineer", company="Acme", locations=["Timisoara"],
        remote=False, work_mode="onsite", eligible_countries=["RO"], employment_type="", description="Run CI for a large team of engineers.",
        salary_min=None, salary_max=None, salary_currency="", posted_at=None, expires_at=None,
    )


def test_modified_ignores_placeholder_and_malformed_dates():
    assert crawl._modified("2026-11-08") is not None
    assert crawl._modified("2026-11-08T10:00:00+02:00") is not None
    assert crawl._modified("1970-01-01T00:00:00+00:00") is None
    assert crawl._modified("0001-01-01") is None
    assert crawl._modified("garbage") is None
    assert crawl._modified(None) is None


def test_recent_drops_old_entries_but_keeps_undated_ones():
    today = date.today().isoformat()
    old = (date.today() - timedelta(days=crawl.MAX_AGE_DAYS + 5)).isoformat()
    entries = [("https://x.ro/a", today), ("https://x.ro/b", old), ("https://x.ro/c", None), ("https://x.ro/d", "1970-01-01T00:00:00+00:00")]
    assert [url for url, _ in crawl._recent(entries)] == ["https://x.ro/a", "https://x.ro/c", "https://x.ro/d"]


def test_validation_refuses_a_sitemap_of_only_old_postings():
    old = (date.today() - timedelta(days=crawl.MAX_AGE_DAYS + 30)).isoformat()
    postings = [f"https://board.ro/locuri/{n}/role" for n in range(6)]
    body = f"<urlset {NS}>{''.join(f'<url><loc>{url}</loc><lastmod>{old}</lastmod></url>' for url in postings)}</urlset>".encode()
    source, fetcher = validate({"https://board.ro/sitemap.xml": body, **{url: POSTING_PAGE for url in postings}})
    assert source.status == "failed"
    assert source.reason == f"sitemap has no postings from the last {crawl.MAX_AGE_DAYS} days"
    assert fetcher.requested == ["https://board.ro/sitemap.xml"]


def llm_pages(count: int = 6) -> dict[str, bytes]:
    urls = [f"https://board.ro/loc-de-munca/job-{n}" for n in range(count)]
    return {"https://board.ro/sitemap.xml": urlset(*urls), **{url: LANDING_PAGE for url in urls}}


def test_validation_falls_back_to_the_model_when_pages_have_no_json_ld():
    fake = MagicMock(side_effect=lambda content, *, url, source: make_posting(url))
    with patch.object(crawl, "extract_llm", fake), patch.object(crawl.settings, "google_cloud_project", "project"):
        source, _ = validate(llm_pages())
    assert (source.status, source.extraction) == ("active", "llm")
    assert source.posting_prefix == "https://board.ro/loc-de-munca/"
    assert fake.call_count == crawl.SAMPLES


def test_validation_does_not_ask_the_model_when_json_ld_works():
    urls = [f"https://board.ro/locuri/{n}/role" for n in range(6)]
    pages = {"https://board.ro/sitemap.xml": urlset(*urls), **{url: POSTING_PAGE for url in urls}}
    fake = MagicMock()
    with patch.object(crawl, "extract_llm", fake), patch.object(crawl.settings, "google_cloud_project", "project"):
        source, _ = validate(pages)
    assert (source.status, source.extraction) == ("active", "jsonld")
    fake.assert_not_called()


def test_validation_does_not_ask_the_model_when_it_is_not_configured():
    fake = MagicMock()
    with patch.object(crawl, "extract_llm", fake), patch.object(crawl.settings, "google_cloud_project", ""):
        source, _ = validate(llm_pages())
    assert source.status == "failed"
    assert source.reason == "job pages have no JobPosting data"
    fake.assert_not_called()


def test_validation_says_when_the_model_found_no_posting_either():
    with patch.object(crawl, "extract_llm", MagicMock(return_value=None)), patch.object(crawl.settings, "google_cloud_project", "project"):
        source, _ = validate(llm_pages())
    assert source.status == "failed"
    assert source.reason == "job pages have no JobPosting data and the model found no posting in them"


def test_refresh_of_a_model_read_source_stops_at_the_lower_cap():
    urls = [f"https://board.ro/loc-de-munca/job-{n}" for n in range(crawl.MAX_LLM_POSTINGS + 20)]
    fetcher = FakeFetcher({"https://board.ro/sitemap.xml": urlset(*urls), **{url: LANDING_PAGE for url in urls}})
    source = JobSource(id=1, domain="board.ro", sitemap_url="https://board.ro/sitemap.xml", kind="board", status="active", reason="", extraction="llm", posting_prefix="https://board.ro/loc-de-munca/")
    db = MagicMock()
    db.scalars.return_value = []
    db.scalar.return_value = None
    fake = MagicMock(side_effect=lambda content, *, url, source: make_posting(url))
    with patch.object(crawl, "SafeFetcher", return_value=fetcher), patch.object(crawl, "extract_llm", fake):
        result = crawl.refresh_source(db, source, [])
    assert result["added"] == crawl.MAX_LLM_POSTINGS
    assert fake.call_count == crawl.MAX_LLM_POSTINGS
    assert len(fetcher.requested) == 1 + crawl.MAX_LLM_POSTINGS
