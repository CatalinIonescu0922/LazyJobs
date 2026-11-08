import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.sources.ats import Feed, find_feed, parse_ats_url, read_feed
from app.sources.fetch import FetchError, FetchResult, SafeFetcher

SR = "https://api.smartrecruiters.com/v1/companies"
GH = "https://boards-api.greenhouse.io/v1/boards"


@pytest.fixture
def api(monkeypatch):
    routes: dict[str, object] = {}
    requested: list[str] = []

    def get(self, url, *, sitemap=False):
        requested.append(url)
        if url not in routes:
            raise FetchError("source returned 404")
        body = routes[url]
        if isinstance(body, Exception):
            raise body
        content = body if isinstance(body, bytes) else json.dumps(body).encode()
        return FetchResult(url, 200, content, "application/json")

    monkeypatch.setattr(SafeFetcher, "get", get)
    return SimpleNamespace(routes=routes, requested=requested)


def sr_check_url(slug, country="ro"):
    return f"{SR}/{slug}/postings?country={country}&limit=1"


def sr_list_url(slug, offset=0, country="ro"):
    return f"{SR}/{slug}/postings?country={country}&limit=100&offset={offset}"


def sr_list(*items, total=None):
    return {"totalFound": len(items) if total is None else total, "content": list(items)}


def sr_item(posting_id, released="2026-10-01T08:00:00.000Z", country="ro", company="Acme", **location):
    return {
        "id": posting_id,
        "name": f"Engineer {posting_id}",
        "releasedDate": released,
        "company": {"identifier": company, "name": company},
        "location": {"city": "Timisoara", "region": "Timis", "country": country, **location},
        "typeOfEmployment": {"label": "Full-time"},
    }


def sr_detail(posting_id, **extra):
    return {
        "id": posting_id,
        "applyUrl": f"https://jobs.smartrecruiters.com/Acme/{posting_id}-engineer?oga=true",
        "jobAd": {
            "sections": {
                "companyDescription": {"title": "Company Description", "text": "<p>We build things.</p>"},
                "jobDescription": {"title": "Job Description", "text": "<ul><li>Write code</li><li>Ship it</li></ul>"},
            }
        },
        **extra,
    }


def gh_job(job_id, location, offices=(), published="2026-10-01T09:00:00-04:00", **extra):
    job = {
        "id": job_id,
        "title": f"Engineer {job_id}",
        "location": {"name": location},
        "offices": [{"location": office} for office in offices],
        "absolute_url": f"https://job-boards.eu.greenhouse.io/acme/jobs/{job_id}",
        "content": "",
    }
    if published:
        job["first_published"] = published
    return {**job, **extra}


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://jobs.smartrecruiters.com/Continental", Feed("smartrecruiters", "Continental")),
        ("https://jobs.smartrecruiters.com/Continental/744000012345-engineer", Feed("smartrecruiters", "Continental")),
        ("https://careers.smartrecruiters.com/BoschGroup", Feed("smartrecruiters", "BoschGroup")),
        ("https://api.smartrecruiters.com/v1/companies/Aumovio/postings", Feed("smartrecruiters", "Aumovio")),
        ("https://boards.greenhouse.io/bearingpoint/jobs/123", Feed("greenhouse", "bearingpoint")),
        ("https://job-boards.greenhouse.io/bearingpoint", Feed("greenhouse", "bearingpoint")),
        ("https://job-boards.eu.greenhouse.io/bearingpoint/jobs/4902535101", Feed("greenhouse", "bearingpoint")),
        ("https://boards-api.greenhouse.io/v1/boards/bearingpoint/jobs", Feed("greenhouse", "bearingpoint")),
        ("https://boards.greenhouse.io/embed/job_board?for=bearingpoint", Feed("greenhouse", "bearingpoint")),
    ],
)
def test_parse_ats_url_recognises_each_form(url, expected):
    assert parse_ats_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.continental.com/careers",
        "https://example.com/jobs.smartrecruiters.com/Continental",
        "https://evilsmartrecruiters.com/Continental",
        "http://jobs.smartrecruiters.com/Continental",
        "https://jobs.smartrecruiters.com/",
        "https://api.smartrecruiters.com/v1/other/Continental",
        "https://boards.greenhouse.io/embed/job_board",
        "https://boards.greenhouse.io/embed/job_board?for=",
        "not a url",
        "",
    ],
)
def test_parse_ats_url_ignores_everything_else(url):
    assert parse_ats_url(url) is None


def test_find_feed_prefers_a_linked_slug_and_skips_the_name_check(api):
    page = b'<a href="https://jobs.smartrecruiters.com/AcmeGroup/744-engineer">Apply</a>'
    api.routes[sr_check_url("AcmeGroup")] = sr_list(sr_item("1", company="Totally Different Name"))
    assert find_feed("acme.com", [page], "RO") == Feed("smartrecruiters", "AcmeGroup")
    assert api.requested == [sr_check_url("AcmeGroup")]


def test_find_feed_finds_links_in_escaped_inline_json(api):
    page = b'{"apply":"https:\\/\\/boards.greenhouse.io\\/embed\\/job_board?for=acmegh"}'
    api.routes[f"{GH}/acmegh/jobs"] = {"jobs": [gh_job(1, "Timisoara, Romania")]}
    assert find_feed("acme.com", [page], "RO") == Feed("greenhouse", "acmegh")


def test_find_feed_accepts_a_correct_guess(api):
    api.routes[sr_check_url("continental")] = sr_list(sr_item("1", company="Continental AG"))
    assert find_feed("continental.com", [], "RO") == Feed("smartrecruiters", "continental")


def test_find_feed_guesses_hyphenated_domains_both_ways_for_both_providers(api):
    api.routes[f"{GH}/vitescotechnologies/jobs"] = {"jobs": [gh_job(1, "Timisoara, Romania")]}
    api.routes[f"{GH}/vitescotechnologies"] = {"name": "Vitesco Technologies"}
    assert find_feed("vitesco-technologies.com", [], "RO") == Feed("greenhouse", "vitescotechnologies")
    assert api.requested == [
        sr_check_url("vitesco-technologies"),
        f"{GH}/vitesco-technologies/jobs",
        sr_check_url("vitescotechnologies"),
        f"{GH}/vitescotechnologies/jobs",
        f"{GH}/vitescotechnologies",
    ]


def test_find_feed_uses_the_label_left_of_a_second_level_suffix(api):
    api.routes[sr_check_url("bosch")] = sr_list(sr_item("1", company="Bosch Group"))
    assert find_feed("bosch.com.ro", [], "RO") == Feed("smartrecruiters", "bosch")


def test_find_feed_rejects_a_guessed_slug_that_belongs_to_another_company(api):
    api.routes[sr_check_url("flex")] = sr_list(sr_item("1", company="Acme Robotics"))
    api.routes[f"{GH}/flex/jobs"] = {"jobs": [gh_job(1, "Cluj, Romania")]}
    api.routes[f"{GH}/flex"] = {"name": "Acme Robotics"}
    assert find_feed("flex.com", [], "RO") is None


def test_find_feed_rejects_a_feed_with_no_posting_in_the_country(api):
    api.routes[sr_check_url("acme")] = sr_list(total=0)
    api.routes[f"{GH}/acme/jobs"] = {"jobs": [gh_job(1, "Dublin, Ireland")]}
    api.routes[f"{GH}/acme"] = {"name": "Acme"}
    assert find_feed("acme.com", [], "RO") is None
    assert f"{GH}/acme" not in api.requested


@pytest.mark.parametrize(
    "location, offices, accepted",
    [
        ("Timisoara, Romania", [], True),
        ("Bucharest, RO", [], True),
        ("Bucharest", [], False),
        ("Romanian speakers wanted, Berlin", [], False),
        ("Rome, Italy", [], False),
        ("Prague, in ro", [], False),
    ],
)
def test_find_feed_matches_the_country_in_greenhouse_location_text(api, location, offices, accepted):
    api.routes[f"{GH}/acme/jobs"] = {"jobs": [gh_job(1, location, offices)]}
    api.routes[f"{GH}/acme"] = {"name": "Acme"}
    assert (find_feed("acme.com", [], "RO") == Feed("greenhouse", "acme")) is accepted


def test_find_feed_spends_at_most_ten_requests(api):
    links = "".join(f'<a href="https://jobs.smartrecruiters.com/Company{n}">x</a>' for n in range(12))
    assert find_feed("acme.com", [links.encode()], "RO") is None
    assert len(api.requested) == 10


def test_find_feed_never_raises_on_bad_responses(api):
    api.routes[sr_check_url("acme")] = b""
    api.routes[f"{GH}/acme/jobs"] = FetchError("blocked (429)")
    assert find_feed("acme.com", [], "RO") is None
    api.routes[sr_check_url("acme")] = b"not json"
    assert find_feed("acme.com", [], "RO") is None
    api.routes[sr_check_url("acme")] = b"[1, 2]"
    api.routes[f"{GH}/acme/jobs"] = {"jobs": "oops"}
    assert find_feed("acme.com", [], "RO") is None


def test_read_smartrecruiters_skips_known_ids_before_any_detail_request(api):
    known_url = "https://jobs.smartrecruiters.com/BoschGroup/400"
    api.routes[sr_list_url("BoschGroup")] = sr_list(
        sr_item("100", released="2026-10-01T08:00:00.000Z"),
        sr_item("200", released="2026-10-05T08:00:00.000Z", hybrid=True),
        sr_item("300", released=None),
        sr_item("400", released="2026-10-09T08:00:00.000Z"),
        sr_item("500", released="2026-10-08T08:00:00.000Z", country="de"),
        sr_item("600", released="2026-09-01T08:00:00.000Z"),
    )
    api.routes[f"{SR}/BoschGroup/postings/100"] = sr_detail("100")
    api.routes[f"{SR}/BoschGroup/postings/200"] = sr_detail(
        "200", compensation={"min": 60000, "max": 84000, "currency": "RON", "period": "YEARLY"}
    )

    postings = read_feed(Feed("smartrecruiters", "BoschGroup"), "bosch.ro", "RO", {known_url}, limit=2)

    assert [p.external_id for p in postings] == [
        "https://jobs.smartrecruiters.com/BoschGroup/200",
        "https://jobs.smartrecruiters.com/BoschGroup/100",
    ]
    detail_requests = [url for url in api.requested if "/postings/" in url]
    assert detail_requests == [f"{SR}/BoschGroup/postings/200", f"{SR}/BoschGroup/postings/100"]


def test_read_smartrecruiters_maps_the_posting(api):
    api.routes[sr_list_url("BoschGroup")] = sr_list(sr_item("200", released="2026-10-05T08:00:00.000Z", hybrid=True))
    api.routes[f"{SR}/BoschGroup/postings/200"] = sr_detail(
        "200", compensation={"min": 60000, "max": 84000, "currency": "RON", "period": "YEARLY"}
    )

    (posting,) = read_feed(Feed("smartrecruiters", "BoschGroup"), "bosch.ro", "RO", set())

    assert posting.source == "bosch.ro"
    assert posting.url == posting.external_id == "https://jobs.smartrecruiters.com/BoschGroup/200"
    assert posting.apply_url == "https://jobs.smartrecruiters.com/Acme/200-engineer?oga=true"
    assert posting.title == "Engineer 200"
    assert posting.company == "Acme"
    assert posting.locations == ["Timisoara, Timis, RO"]
    assert posting.eligible_countries == ["RO"]
    assert (posting.work_mode, posting.remote) == ("hybrid", True)
    assert posting.employment_type == "Full-time"
    assert (posting.salary_min, posting.salary_max, posting.salary_currency) == (5000, 7000, "RON")
    assert posting.posted_at == datetime(2026, 10, 5, 8, 0)
    assert posting.expires_at is None
    assert posting.description == "Company Description\nWe build things.\n\nJob Description\nWrite code Ship it"


def test_read_smartrecruiters_defaults_when_the_feed_is_sparse(api):
    item = {"id": "7", "name": "Tester", "location": {"country": "ro"}}
    api.routes[sr_list_url("acme")] = sr_list(item)
    api.routes[f"{SR}/acme/postings/7"] = {"id": "7", "jobAd": {"sections": {}}}

    (posting,) = read_feed(Feed("smartrecruiters", "acme"), "acme.ro", "RO", set())

    assert posting.company == "acme.ro"
    assert posting.apply_url == posting.url
    assert (posting.work_mode, posting.remote) == ("onsite", False)
    assert posting.employment_type == ""
    assert (posting.salary_min, posting.salary_max, posting.salary_currency) == (None, None, "")
    assert posting.posted_at is None
    assert posting.description == ""


def test_read_smartrecruiters_skips_a_posting_whose_detail_request_fails(api):
    api.routes[sr_list_url("acme")] = sr_list(sr_item("1", released="2026-10-02T00:00:00Z"), sr_item("2"))
    api.routes[f"{SR}/acme/postings/1"] = FetchError("blocked (429)")
    api.routes[f"{SR}/acme/postings/2"] = sr_detail("2")

    postings = read_feed(Feed("smartrecruiters", "acme"), "acme.ro", "RO", set())

    assert [p.external_id for p in postings] == ["https://jobs.smartrecruiters.com/acme/2"]


def test_read_smartrecruiters_lets_a_list_failure_through(api):
    api.routes[sr_list_url("acme")] = FetchError("disallowed by robots.txt")
    with pytest.raises(FetchError, match="robots"):
        read_feed(Feed("smartrecruiters", "acme"), "acme.ro", "RO", set())


def test_read_smartrecruiters_stops_paging_once_it_has_enough(api):
    api.routes[sr_list_url("acme")] = sr_list(*[sr_item(str(n)) for n in range(5)], total=1000)
    read_feed(Feed("smartrecruiters", "acme"), "acme.ro", "RO", set(), limit=3)
    assert [url for url in api.requested if "/postings?" in url] == [sr_list_url("acme")]


def test_read_smartrecruiters_never_reads_more_than_five_pages(api):
    for offset in range(0, 600, 100):
        api.routes[sr_list_url("acme", offset)] = sr_list(*[sr_item(str(offset + n)) for n in range(100)], total=1000)

    read_feed(Feed("smartrecruiters", "acme"), "acme.ro", "RO", set(), limit=1000)

    pages = [url for url in api.requested if "/postings?" in url]
    assert pages == [sr_list_url("acme", offset) for offset in range(0, 500, 100)]


def test_read_greenhouse_keeps_in_country_postings_newest_first_up_to_the_limit(api):
    escaped = "&lt;p&gt;Build &amp;amp; run services&lt;/p&gt;"
    jobs = [
        gh_job(1, "Timisoara", ["Timisoara, Timis, Romania"], content=escaped, company_name="Acme Romania", application_deadline="2026-12-01"),
        gh_job(2, "Remote - Romania", published="2026-10-05T09:00:00-04:00"),
        gh_job(3, "Dublin", ["Dublin, Dublin, Ireland"], published="2026-10-09T09:00:00-04:00"),
        gh_job(4, "Bucharest, Romania", published="2026-10-08T09:00:00-04:00"),
        gh_job(5, "Cluj, Romania (Hybrid)", published=None, updated_at="2026-09-01T09:00:00-04:00"),
        gh_job(6, "Bucharest, Romania", published="2026-08-01T09:00:00-04:00"),
        gh_job(7, "Bucharest, Romania", published=None),
    ]
    jobs[0]["absolute_url"] = "https://job-boards.eu.greenhouse.io/acme/jobs/1?gh_src=abc#apply"
    jobs[5]["absolute_url"] = "https://careers.acme.com/open?utm_source=x&gh_jid=6#apply"
    api.routes[f"{GH}/acme/jobs?content=true"] = {"jobs": jobs}
    known = {"https://job-boards.eu.greenhouse.io/acme/jobs/4"}

    postings = read_feed(Feed("greenhouse", "acme"), "acme.ro", "RO", known, limit=4)

    assert [p.external_id for p in postings] == [
        "https://job-boards.eu.greenhouse.io/acme/jobs/2",
        "https://job-boards.eu.greenhouse.io/acme/jobs/1",
        "https://job-boards.eu.greenhouse.io/acme/jobs/5",
        "https://careers.acme.com/open?gh_jid=6",
    ]
    assert api.requested == [f"{GH}/acme/jobs?content=true"]
    assert {p.source for p in postings} == {"acme.ro"}
    assert all(p.eligible_countries == ["RO"] for p in postings)
    assert [(p.work_mode, p.remote) for p in postings] == [("remote", True), ("onsite", False), ("hybrid", True), ("onsite", False)]


def test_read_greenhouse_maps_the_posting(api):
    escaped = "&lt;h2&gt;Role&lt;/h2&gt;&lt;p&gt;Build &amp;amp; run services&lt;/p&gt;"
    job = gh_job(1, "Timisoara", ["Timisoara, Timis, Romania"], content=escaped, company_name="Acme Romania", application_deadline="2026-12-01")
    job["absolute_url"] = "https://job-boards.eu.greenhouse.io/acme/jobs/1?gh_src=abc#apply"
    api.routes[f"{GH}/acme/jobs?content=true"] = {"jobs": [job, gh_job(2, "Cluj, Romania")]}

    postings = read_feed(Feed("greenhouse", "acme"), "acme.ro", "RO", set())

    first = next(p for p in postings if p.title == "Engineer 1")
    assert first.url == first.external_id == "https://job-boards.eu.greenhouse.io/acme/jobs/1"
    assert first.apply_url == "https://job-boards.eu.greenhouse.io/acme/jobs/1?gh_src=abc#apply"
    assert first.company == "Acme Romania"
    assert first.locations == ["Timisoara"]
    assert first.description == "Role Build & run services"
    assert first.employment_type == ""
    assert (first.salary_min, first.salary_max, first.salary_currency) == (None, None, "")
    assert first.posted_at == datetime(2026, 10, 1, 9, 0)
    assert first.expires_at == datetime(2026, 12, 1)
    second = next(p for p in postings if p.title == "Engineer 2")
    assert second.company == "acme.ro"
    assert second.expires_at is None


def test_read_greenhouse_lets_a_list_failure_through(api):
    api.routes[f"{GH}/acme/jobs?content=true"] = b"not json"
    with pytest.raises(FetchError):
        read_feed(Feed("greenhouse", "acme"), "acme.ro", "RO", set())


WD = "https://acme.wd3.myworkdayjobs.com"
WD_API = f"{WD}/wday/cxs/acme/Careers"
WD_FEED = Feed("workday", "acme.wd3/Careers")


@pytest.fixture
def workday(api, monkeypatch):
    lists: dict[tuple[str, int], object] = {}
    posts: list[tuple[str, dict]] = []

    def post_json(self, url, body):
        posts.append((url, body))
        key = (body["searchText"], body["offset"])
        if key not in lists:
            raise FetchError("source returned 404")
        reply = lists[key]
        if isinstance(reply, Exception):
            raise reply
        return FetchResult(url, 200, json.dumps(reply).encode(), "application/json")

    monkeypatch.setattr(SafeFetcher, "post_json", post_json)
    return SimpleNamespace(lists=lists, posts=posts, routes=api.routes, requested=api.requested)


def wd_query(search, offset=0, limit=20):
    return {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": search}


def wd_item(n, posted="Posted 30+ Days Ago"):
    return {
        "title": f"Engineer {n}",
        "externalPath": f"/job/Timisoara/Engineer-{n}_R{n}",
        "postedOn": posted,
        "bulletFields": [f"R{n}"],
    }


def wd_page(*items, total=None):
    return {"total": len(items) if total is None else total, "jobPostings": list(items)}


def wd_detail_url(n):
    return f"{WD_API}/job/Timisoara/Engineer-{n}_R{n}"


def wd_public_url(n):
    return f"{WD}/Careers/job/Timisoara/Engineer-{n}_R{n}"


def wd_detail(n, start="2026-10-01", country="Romania", location="Timisoara", **info):
    return {
        "jobPostingInfo": {
            "title": f"Engineer {n}",
            "jobDescription": "<p>Build &amp; run <b>services</b></p><ul><li>One</li><li>Two</li></ul>",
            "location": location,
            "additionalLocations": [],
            "startDate": start,
            "timeType": "Full time",
            "country": {"descriptor": country},
            "externalUrl": wd_public_url(n),
            **info,
        },
        "hiringOrganization": {"name": "Acme Romania SRL"},
    }


def wd_stock(workday, count, overrides=None):
    for n in range(1, count + 1):
        workday.routes[wd_detail_url(n)] = wd_detail(n, **(overrides or {}).get(n, {}))


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://flextronics.wd1.myworkdayjobs.com/Careers?source=x", Feed("workday", "flextronics.wd1/Careers")),
        ("https://accenture.wd103.myworkdayjobs.com/AccentureCareers", Feed("workday", "accenture.wd103/AccentureCareers")),
        ("https://accenture.wd103.myworkdayjobs.com/en-US/AccentureCareers/job/x", Feed("workday", "accenture.wd103/AccentureCareers")),
        ("https://accenture.wd103.myworkdayjobs.com/ro-RO/AccentureCareers", Feed("workday", "accenture.wd103/AccentureCareers")),
        ("https://Accenture.WD103.myworkdayjobs.com/AccentureCareers", Feed("workday", "accenture.wd103/AccentureCareers")),
        ("https://acme.wd5.myworkdayjobs.com/External_Careers/job/Timisoara/x_1", Feed("workday", "acme.wd5/External_Careers")),
    ],
)
def test_parse_ats_url_recognises_workday_forms(url, expected):
    assert parse_ats_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://acme.wd3.myworkdayjobs.com",
        "https://acme.wd3.myworkdayjobs.com/",
        "https://acme.wd3.myworkdayjobs.com/en-US",
        "https://acme.wd3.myworkdayjobs.com/en-US/",
        "http://acme.wd3.myworkdayjobs.com/Careers",
        "https://acme.myworkdayjobs.com/Careers",
        "https://acme.wdx.myworkdayjobs.com/Careers",
        "https://myworkdayjobs.com/Careers",
        "https://acme.wd3.myworkdayjobs.com.evil.com/Careers",
        "https://example.com/acme.wd3.myworkdayjobs.com/Careers",
        "https://evilmyworkdayjobs.com/Careers",
    ],
)
def test_parse_ats_url_ignores_what_is_not_a_workday_site(url):
    assert parse_ats_url(url) is None


def test_find_feed_accepts_a_linked_workday_feed_with_a_posting_in_the_country(workday):
    page = b'<a href="https://acme.wd3.myworkdayjobs.com/en-US/Careers?source=site">Careers</a>'
    workday.lists[("Romania", 0)] = wd_page(wd_item(1), total=34)
    workday.routes[wd_detail_url(1)] = wd_detail(1)

    assert find_feed("acme.com", [page], "RO") == WD_FEED

    assert workday.posts == [(f"{WD_API}/jobs", wd_query("Romania", limit=1))]
    assert workday.requested == [wd_detail_url(1)]


def test_find_feed_rejects_a_workday_feed_with_no_posting_at_all(workday):
    page = b'<a href="https://flextronics.wd1.myworkdayjobs.com/Careers?source=Flex_Career_Site">Careers</a>'
    workday.lists[("Romania", 0)] = wd_page(total=0)

    assert find_feed("flex.com", [page], "RO") is None

    assert len(workday.posts) == 1
    assert not [url for url in workday.requested if "myworkdayjobs" in url]


@pytest.mark.parametrize(
    "info, accepted",
    [
        ({}, True),
        ({"country": {}, "jobRequisitionLocation": {"country": {"alpha2Code": "RO"}}}, True),
        ({"country": {}, "location": "Bucharest, Romania"}, True),
        ({"country": {"descriptor": "Germany"}, "location": "Berlin", "additionalLocations": ["Cluj, Romania"]}, True),
        ({"country": {}, "location": "Bucharest"}, False),
        ({"country": {"descriptor": "Germany"}, "location": "Berlin"}, False),
        ({"country": {"descriptor": "Italy"}, "location": "Rome, Italy"}, False),
        ({"country": {}, "location": "Romanian speakers wanted, Berlin"}, False),
    ],
)
def test_find_feed_confirms_the_country_of_the_first_workday_posting(workday, info, accepted):
    page = b'<a href="https://acme.wd3.myworkdayjobs.com/Careers">Careers</a>'
    workday.lists[("Romania", 0)] = wd_page(wd_item(1))
    workday.routes[wd_detail_url(1)] = wd_detail(1, **info)
    assert (find_feed("acme.com", [page], "RO") == WD_FEED) is accepted


def test_find_feed_never_guesses_a_workday_feed_from_the_domain(workday):
    assert find_feed("acme.com", [], "RO") is None
    assert workday.posts == []
    assert not [url for url in workday.requested if "myworkdayjobs" in url]


def test_find_feed_counts_workday_requests_against_the_shared_budget(workday):
    links = "".join(f'<a href="https://acme.wd3.myworkdayjobs.com/Site{n}">x</a>' for n in range(8))
    workday.lists[("Romania", 0)] = wd_page(wd_item(1))

    assert find_feed("acme.com", [links.encode()], "RO") is None

    assert len(workday.posts) == 5
    assert len(workday.posts) + len(workday.requested) == 10


def test_find_feed_survives_a_workday_failure_and_tries_the_next_candidate(workday):
    page = b'<a href="https://acme.wd3.myworkdayjobs.com/Careers">x</a><a href="https://jobs.smartrecruiters.com/AcmeGroup">x</a>'
    workday.lists[("Romania", 0)] = FetchError("blocked (429)")
    workday.routes[sr_check_url("AcmeGroup")] = sr_list(sr_item("1"))
    assert find_feed("acme.com", [page], "RO") == Feed("smartrecruiters", "AcmeGroup")


def test_read_workday_skips_known_postings_before_any_detail_request(workday):
    workday.lists[("Timisoara", 0)] = wd_page(
        wd_item(1, "Posted 3 Days Ago"),
        wd_item(2, "Posted Today"),
        wd_item(3, "Posted 30+ Days Ago"),
        wd_item(4, "Posted Yesterday"),
    )
    wd_stock(workday, 4, {1: {"start": "2026-10-09"}, 2: {"start": "2026-10-05"}})

    postings = read_feed(WD_FEED, "acme.ro", "RO", {wd_public_url(4)}, limit=2, city="Timisoara")

    assert workday.requested == [wd_detail_url(2), wd_detail_url(1)]
    assert [p.external_id for p in postings] == [wd_public_url(1), wd_public_url(2)]
    assert len(workday.posts) == 1


def test_read_workday_keeps_in_country_postings_newest_first_with_undated_last(workday):
    workday.lists[("Romania", 0)] = wd_page(wd_item(1), wd_item(2), wd_item(3), wd_item(4), wd_item(5))
    wd_stock(
        workday,
        5,
        {
            1: {"start": "2026-10-01"},
            2: {"country": "Germany", "location": "Berlin", "start": "2026-10-20"},
            3: {"start": None},
            4: {"start": "2026-10-08"},
            5: {"start": "2026-09-01"},
        },
    )

    postings = read_feed(WD_FEED, "acme.ro", "RO", set())

    assert [p.external_id for p in postings] == [wd_public_url(n) for n in (4, 1, 5, 3)]
    assert wd_detail_url(2) in workday.requested
    assert {p.source for p in postings} == {"acme.ro"}
    assert all(p.eligible_countries == ["RO"] for p in postings)


def test_read_workday_does_not_count_foreign_postings_against_the_limit(workday):
    workday.lists[("Romania", 0)] = wd_page(wd_item(1), wd_item(2), wd_item(3))
    foreign = {"country": "Germany", "location": "Berlin"}
    wd_stock(workday, 3, {1: foreign, 2: foreign})

    postings = read_feed(WD_FEED, "acme.ro", "RO", set(), limit=1)

    assert [p.external_id for p in postings] == [wd_public_url(3)]
    assert workday.requested == [wd_detail_url(1), wd_detail_url(2), wd_detail_url(3)]


def test_read_workday_maps_the_posting(workday):
    workday.lists[("Romania", 0)] = wd_page(wd_item(1))
    workday.routes[wd_detail_url(1)] = wd_detail(
        1,
        additionalLocations=["Cluj-Napoca", "Timisoara"],
        remoteType="Hybrid",
        externalUrl=f"{WD}/en-US/Careers/job/Timisoara/Engineer-1_R1?source=x",
    )

    (posting,) = read_feed(WD_FEED, "acme.ro", "RO", set())

    assert posting.source == "acme.ro"
    assert posting.url == posting.external_id == wd_public_url(1)
    assert posting.apply_url == f"{WD}/en-US/Careers/job/Timisoara/Engineer-1_R1?source=x"
    assert posting.title == "Engineer 1"
    assert posting.company == "Acme Romania SRL"
    assert posting.locations == ["Timisoara", "Cluj-Napoca"]
    assert posting.eligible_countries == ["RO"]
    assert (posting.work_mode, posting.remote) == ("hybrid", True)
    assert posting.employment_type == "Full time"
    assert (posting.salary_min, posting.salary_max, posting.salary_currency) == (None, None, "")
    assert posting.posted_at == datetime(2026, 10, 1)
    assert posting.expires_at is None
    assert posting.description == "Build & run services One Two"


def test_read_workday_defaults_when_the_detail_is_sparse(workday):
    workday.lists[("Romania", 0)] = wd_page(wd_item(1))
    workday.routes[wd_detail_url(1)] = {"jobPostingInfo": {"title": "Tester", "country": {"descriptor": "Romania"}}}

    (posting,) = read_feed(WD_FEED, "acme.ro", "RO", set())

    assert posting.company == "acme.ro"
    assert posting.apply_url == posting.url == wd_public_url(1)
    assert posting.locations == []
    assert (posting.work_mode, posting.remote) == ("onsite", False)
    assert posting.employment_type == ""
    assert posting.posted_at is None
    assert posting.description == ""


@pytest.mark.parametrize(
    "location, remote_type, expected",
    [
        ("Timisoara", "Remote", "remote"),
        ("Timisoara", "Hybrid", "hybrid"),
        ("Timisoara", "On-site", "onsite"),
        ("Remote - Romania", "", "remote"),
        ("Timisoara (Hybrid)", "", "hybrid"),
    ],
)
def test_read_workday_takes_the_work_mode_from_the_location_and_remote_type(workday, location, remote_type, expected):
    workday.lists[("Romania", 0)] = wd_page(wd_item(1))
    workday.routes[wd_detail_url(1)] = wd_detail(1, location=location, remoteType=remote_type)
    (posting,) = read_feed(WD_FEED, "acme.ro", "RO", set())
    assert posting.work_mode == expected


@pytest.mark.parametrize("city", ["Timi\u0219oara", "Timi\u015foara", "  Timisoara "])
def test_read_workday_searches_by_the_city_with_diacritics_folded(workday, city):
    workday.lists[("Timisoara", 0)] = wd_page()
    assert read_feed(WD_FEED, "acme.ro", "RO", set(), city=city) == []
    assert workday.posts == [(f"{WD_API}/jobs", wd_query("Timisoara"))]


def test_read_workday_searches_by_the_country_name_when_there_is_no_city(workday):
    workday.lists[("Romania", 0)] = wd_page()
    assert read_feed(WD_FEED, "acme.ro", "RO", set()) == []
    assert read_feed(WD_FEED, "acme.ro", "ro", set(), city="") == []
    assert workday.posts == [(f"{WD_API}/jobs", wd_query("Romania"))] * 2


def test_read_workday_picks_the_newest_by_posted_text_when_there_are_more_candidates_than_the_limit(workday):
    workday.lists[("Romania", 0)] = wd_page(
        wd_item(1, "Posted 30+ Days Ago"),
        wd_item(2, "Posted 12 Days Ago"),
        wd_item(3, "Posted Today"),
        wd_item(4, "Posted a while back"),
        wd_item(5, "Posted Yesterday"),
    )
    wd_stock(workday, 5)

    read_feed(WD_FEED, "acme.ro", "RO", set(), limit=3)

    assert workday.requested == [wd_detail_url(3), wd_detail_url(5), wd_detail_url(2)]


def test_read_workday_stops_paging_once_it_has_enough_candidates(workday):
    workday.lists[("Romania", 0)] = wd_page(*[wd_item(n) for n in range(20)], total=1000)
    read_feed(WD_FEED, "acme.ro", "RO", set(), limit=3)
    assert [body["offset"] for _, body in workday.posts] == [0]


def test_read_workday_never_reads_more_than_five_pages(workday):
    for offset in range(0, 120, 20):
        workday.lists[("Romania", offset)] = wd_page(*[wd_item(offset + n) for n in range(20)], total=1000 if offset == 0 else 0)

    read_feed(WD_FEED, "acme.ro", "RO", set(), limit=1000)

    assert [body["offset"] for _, body in workday.posts] == [0, 20, 40, 60, 80]
    assert all(body["limit"] == 20 for _, body in workday.posts)


@pytest.mark.parametrize("total, offsets", [(34, [0, 20]), (40, [0, 20]), (41, [0, 20, 40]), (5, [0])])
def test_read_workday_stops_at_the_total_the_first_page_reports(workday, total, offsets):
    # Live, the pages after the first report total 0 and an offset past the end repeats the first page.
    for offset in range(0, 100, 20):
        size = max(0, min(20, total - offset))
        workday.lists[("Romania", offset)] = wd_page(*[wd_item(offset + n) for n in range(size)], total=total if offset == 0 else 0)

    read_feed(WD_FEED, "acme.ro", "RO", set(), limit=1000)

    assert [body["offset"] for _, body in workday.posts] == offsets


def test_read_workday_skips_a_posting_whose_detail_request_fails(workday):
    workday.lists[("Romania", 0)] = wd_page(wd_item(1, "Posted Today"), wd_item(2))
    workday.routes[wd_detail_url(1)] = FetchError("blocked (429)")
    workday.routes[wd_detail_url(2)] = wd_detail(2)

    postings = read_feed(WD_FEED, "acme.ro", "RO", set())

    assert [p.external_id for p in postings] == [wd_public_url(2)]


def test_read_workday_lets_a_list_failure_through(workday):
    workday.lists[("Romania", 0)] = FetchError("blocked (429)")
    with pytest.raises(FetchError, match="429"):
        read_feed(WD_FEED, "acme.ro", "RO", set())


def test_read_workday_ignores_a_posting_without_a_usable_path(workday):
    workday.lists[("Romania", 0)] = wd_page({"title": "No path"}, {"title": "Odd", "externalPath": "job/relative"}, wd_item(1))
    wd_stock(workday, 1)
    postings = read_feed(WD_FEED, "acme.ro", "RO", set())
    assert [p.external_id for p in postings] == [wd_public_url(1)]


def test_read_feed_ignores_city_for_greenhouse_and_smartrecruiters(api, workday):
    api.routes[sr_list_url("acme")] = sr_list(sr_item("7"))
    api.routes[f"{SR}/acme/postings/7"] = sr_detail("7")
    api.routes[f"{GH}/acme/jobs?content=true"] = {"jobs": [gh_job(1, "Timisoara, Romania")]}

    for feed in (Feed("smartrecruiters", "acme"), Feed("greenhouse", "acme")):
        plain = read_feed(feed, "acme.ro", "RO", set())
        assert plain
        assert read_feed(feed, "acme.ro", "RO", set(), city="Timi\u0219oara") == plain

    assert workday.posts == []


def test_read_feed_takes_the_city_by_keyword_only():
    with pytest.raises(TypeError):
        read_feed(WD_FEED, "acme.ro", "RO", set(), 10, "Timisoara")
