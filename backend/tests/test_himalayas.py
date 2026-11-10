import json
import re
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.sources import himalayas
from app.sources.fetch import FetchError, FetchResult
from app.sources.himalayas import DOMAIN, is_closed, search_jobs

SEARCH = "https://himalayas.app/jobs/api/search"
GUID = "https://himalayas.app/companies/acme/jobs/senior-devops-engineer"
PUB = 1_700_000_000
EXPIRY = 1_700_086_400


def job(slug="senior-devops-engineer", **extra):
    guid = f"https://himalayas.app/companies/acme/jobs/{slug}"
    return {
        "title": f"Engineer {slug}",
        "excerpt": "short",
        "companyName": "Acme",
        "companySlug": "acme",
        "employmentType": "Full Time",
        "minSalary": None,
        "maxSalary": None,
        "salaryPeriod": "annual",
        "currency": None,
        "seniority": ["Senior"],
        "locationRestrictions": [],
        "timezoneRestrictions": [],
        "description": "<p>Run the <b>platform</b>.</p>",
        "pubDate": PUB,
        "expiryDate": EXPIRY,
        "applicationLink": f"{guid}?utm_source=api",
        "guid": guid,
        **extra,
    }


def page(jobs, total=None):
    return {"jobs": jobs, "limit": 20, "offset": 0, "totalCount": len(jobs) if total is None else total}


def full_page(start, count=20, **extra):
    return [job(f"job-{start + index}", **extra) for index in range(count)]


@pytest.fixture
def api(monkeypatch):
    events: list[tuple] = []
    responses: list[object] = []
    domains: list[str] = []

    class FakeFetcher:
        def __init__(self, domain):
            domains.append(domain)

        def get(self, url, *, sitemap=False):
            events.append(("get", url))
            if not responses:
                raise AssertionError(f"unexpected request: {url}")
            body = responses.pop(0)
            if isinstance(body, Exception):
                raise body
            content = body if isinstance(body, bytes) else json.dumps(body).encode()
            return FetchResult(url, 200, content, "application/json")

    monkeypatch.setattr(himalayas, "SafeFetcher", FakeFetcher)
    monkeypatch.setattr(himalayas.time, "sleep", lambda seconds: events.append(("sleep", seconds)))
    return SimpleNamespace(responses=responses, events=events, domains=domains)


def requested(api):
    return [event[1] for event in api.events if event[0] == "get"]


def sleeps(api):
    return [event[1] for event in api.events if event[0] == "sleep"]


def test_job_maps_to_every_posting_field(api):
    api.responses.append(
        page(
            [
                job(
                    minSalary=60000,
                    maxSalary=84000,
                    currency="usd",
                    locationRestrictions=["Romania", "Germany", "Europe"],
                    description="<h3>Role</h3><p>Run the <b>platform</b></p><ul><li>Kubernetes</li></ul>",
                )
            ]
        )
    )

    [posting] = search_jobs("devops", "RO", set())

    assert posting.source == DOMAIN == "himalayas.app"
    assert posting.external_id == GUID
    assert posting.url == GUID
    assert posting.apply_url == f"{GUID}?utm_source=api"
    assert posting.title == "Engineer senior-devops-engineer"
    assert posting.company == "Acme"
    assert posting.locations == ["Romania", "Germany", "Europe"]
    assert posting.remote is True
    assert posting.work_mode == "remote"
    assert posting.eligible_countries == ["RO", "DE"]
    assert posting.employment_type == "Full Time"
    assert posting.description == "Role Run the platform Kubernetes"
    assert (posting.salary_min, posting.salary_max, posting.salary_currency) == (5000, 7000, "USD")
    assert posting.posted_at == datetime(2023, 11, 14, 22, 13, 20)
    assert posting.expires_at == datetime(2023, 11, 15, 22, 13, 20)
    assert posting.posted_at.tzinfo is None
    assert posting.expires_at.tzinfo is None


def test_worldwide_job_has_no_eligible_countries(api):
    api.responses.append(page([job(locationRestrictions=[])]))

    [posting] = search_jobs("devops", "RO", set())

    assert posting.locations == ["Remote"]
    assert posting.eligible_countries == []
    assert posting.remote is True
    assert posting.work_mode == "remote"


def test_country_names_map_exactly_and_non_countries_are_dropped(api):
    names = ["Niger", "Turkey", "Czechia", "Congo, The Democratic Republic of the", "Anywhere", "Romania", "Romania"]
    api.responses.append(page([job(locationRestrictions=names)]))

    [posting] = search_jobs("devops", "RO", set())

    assert posting.eligible_countries == ["NE", "TR", "CZ", "CD", "RO"]
    assert posting.locations == list(dict.fromkeys(names))


def test_location_restrictions_given_as_objects_still_map(api):
    api.responses.append(page([job(locationRestrictions=[{"alpha2": "RO", "name": "Romania", "slug": "romania"}])]))

    [posting] = search_jobs("devops", "RO", set())

    assert posting.locations == ["Romania"]
    assert posting.eligible_countries == ["RO"]


@pytest.mark.parametrize(
    ("period", "low", "high", "expected"),
    [
        ("annual", 60000, 120000, (5000, 10000)),
        ("monthly", 4000, 6000, (4000, 6000)),
        ("weekly", 1000, 1200, (4333, 5200)),
        ("hourly", 50, 60, (8000, 9600)),
        ("annual", 60000, None, (5000, None)),
        ("annual", None, 120000, (None, 10000)),
    ],
)
def test_salary_is_converted_to_monthly(api, period, low, high, expected):
    api.responses.append(page([job(salaryPeriod=period, minSalary=low, maxSalary=high, currency="EUR")]))

    [posting] = search_jobs("devops", "RO", set())

    assert (posting.salary_min, posting.salary_max) == expected
    assert posting.salary_currency == "EUR"


@pytest.mark.parametrize(
    "extra",
    [
        {"salaryPeriod": None, "minSalary": 60000, "maxSalary": 90000, "currency": "USD"},
        {"salaryPeriod": "fortnightly", "minSalary": 2000, "maxSalary": 3000, "currency": "USD"},
        {"salaryPeriod": "yearly-ish", "minSalary": 60000, "maxSalary": 90000, "currency": "USD"},
        {"minSalary": 60000, "maxSalary": 90000, "currency": None},
        {"minSalary": 60000, "maxSalary": 90000, "currency": "United States dollar"},
        {"minSalary": None, "maxSalary": None, "currency": "USD"},
        {"minSalary": -5, "maxSalary": None, "currency": "USD"},
        {"salaryPeriod": "hourly", "minSalary": 20_000_000, "maxSalary": None, "currency": "USD"},
    ],
)
def test_salary_is_left_empty_rather_than_guessed(api, extra):
    api.responses.append(page([job(**extra)]))

    [posting] = search_jobs("devops", "RO", set())

    assert (posting.salary_min, posting.salary_max, posting.salary_currency) == (None, None, "")


def test_missing_company_and_apply_link_fall_back(api):
    api.responses.append(page([job(companyName="", applicationLink=None)]))

    [posting] = search_jobs("devops", "RO", set())

    assert posting.company == DOMAIN
    assert posting.apply_url == GUID


def test_malformed_dates_become_none(api):
    api.responses.append(page([job(pubDate=None, expiryDate="soon")]))

    [posting] = search_jobs("devops", "RO", set())

    assert posting.posted_at is None
    assert posting.expires_at is None


def test_known_ids_are_skipped(api):
    api.responses.append(page([job("one"), job("two"), job("three")]))

    postings = search_jobs("devops", "RO", {"https://himalayas.app/companies/acme/jobs/two"})

    assert [posting.title for posting in postings] == ["Engineer one", "Engineer three"]


def test_a_job_repeated_on_a_later_page_is_returned_once(api):
    api.responses.extend([page(full_page(0), total=40), page(full_page(19, count=20), total=40)])

    postings = search_jobs("devops", "RO", set())

    assert len(postings) == 39
    assert len({posting.external_id for posting in postings}) == 39


def test_request_url_has_query_country_and_page(api):
    api.responses.append(page([job()]))

    search_jobs("devops engineer", "ro", set())

    assert requested(api) == [f"{SEARCH}?q=devops+engineer&country=RO&page=1"]


def test_one_fetcher_serves_every_page(api):
    api.responses.extend([page(full_page(0), total=60), page(full_page(20), total=60), page(full_page(40), total=60)])

    search_jobs("devops", "RO", set())

    assert api.domains == [DOMAIN]


def test_paging_waits_between_pages_only(api):
    api.responses.extend([page(full_page(0), total=60), page(full_page(20), total=60), page(full_page(40), total=60)])

    postings = search_jobs("devops", "RO", set())

    assert len(postings) == 60
    assert requested(api) == [f"{SEARCH}?q=devops&country=RO&page={number}" for number in (1, 2, 3)]
    assert [event[0] for event in api.events] == ["get", "sleep", "get", "sleep", "get"]
    assert sleeps(api) == [2, 2]


def test_paging_stops_at_the_page_limit(api):
    api.responses.extend([page(full_page(0), total=300), page(full_page(20), total=300), page(full_page(40), total=300)])

    postings = search_jobs("devops", "RO", set(), pages=2)

    assert len(postings) == 40
    assert len(requested(api)) == 2
    assert sleeps(api) == [2]


def test_paging_defaults_to_three_pages(api):
    api.responses.extend([page(full_page(index * 20), total=300) for index in range(4)])

    postings = search_jobs("devops", "RO", set())

    assert len(postings) == 60
    assert len(requested(api)) == 3
    assert len(api.responses) == 1


def test_paging_stops_on_a_short_page(api):
    api.responses.extend([page(full_page(0), total=300), page(full_page(20, count=5), total=300), page(full_page(25))])

    postings = search_jobs("devops", "RO", set())

    assert len(postings) == 25
    assert len(requested(api)) == 2
    assert sleeps(api) == [2]


def test_paging_stops_when_total_count_is_read(api):
    api.responses.extend([page(full_page(0), total=40), page(full_page(20), total=40), page(full_page(40))])

    postings = search_jobs("devops", "RO", set())

    assert len(postings) == 40
    assert len(requested(api)) == 2
    assert sleeps(api) == [2]


def test_one_full_page_that_is_the_whole_result_makes_one_request_and_no_wait(api):
    api.responses.append(page(full_page(0), total=20))

    assert len(search_jobs("devops", "RO", set())) == 20

    assert len(requested(api)) == 1
    assert sleeps(api) == []


def test_known_jobs_still_count_toward_the_page_and_total(api):
    first_page = full_page(0)
    api.responses.append(page(first_page, total=20))

    postings = search_jobs("devops", "RO", {item["guid"] for item in first_page})

    assert postings == []
    assert len(requested(api)) == 1


def test_empty_result_returns_nothing(api):
    api.responses.append(page([], total=0))

    assert search_jobs("devops", "RO", set()) == []
    assert sleeps(api) == []


def test_malformed_jobs_are_skipped_and_the_rest_kept(api):
    bad = [
        {k: v for k, v in job("no-guid").items() if k != "guid"},
        job("no-title", title=""),
        {k: v for k, v in job("no-description").items() if k != "description"},
        job("blank-description", description="   "),
        job("blank-guid", guid=" "),
        "not a job",
        None,
        {"guid": None},
    ]
    api.responses.append(page([job("good-one"), *bad, job("good-two")]))

    postings = search_jobs("devops", "RO", set())

    assert [posting.title for posting in postings] == ["Engineer good-one", "Engineer good-two"]


def test_a_job_with_odd_field_types_does_not_raise(api):
    api.responses.append(
        page([job("odd", locationRestrictions="Romania", salaryPeriod=["annual"], minSalary="lots", currency=5, employmentType=None)])
    )

    [posting] = search_jobs("devops", "RO", set())

    assert posting.locations == ["Remote"]
    assert posting.eligible_countries == []
    assert posting.salary_min is None
    assert posting.employment_type == ""


def test_a_fetch_error_on_the_first_page_propagates(api):
    api.responses.append(FetchError("blocked (429)"))

    with pytest.raises(FetchError, match=r"blocked \(429\)"):
        search_jobs("devops", "RO", set())

    assert sleeps(api) == []


def test_a_fetch_error_on_a_later_page_propagates_without_retry(api):
    api.responses.extend([page(full_page(0), total=60), FetchError("blocked (429)")])

    with pytest.raises(FetchError, match=r"blocked \(429\)"):
        search_jobs("devops", "RO", set())

    assert len(requested(api)) == 2
    assert sleeps(api) == [2]


@pytest.mark.parametrize("body", [b"<html>nope</html>", b"[]", b""])
def test_a_body_that_is_not_a_json_object_is_a_fetch_error(api, body):
    api.responses.append(body)

    with pytest.raises(FetchError):
        search_jobs("devops", "RO", set())


@pytest.mark.parametrize("message", ["source returned 410", "source returned 404"])
def test_is_closed_is_true_for_a_410_and_for_a_404(api, message):
    api.responses.append(FetchError(message))

    assert is_closed(GUID) is True


def test_is_closed_is_false_for_an_open_job(api):
    api.responses.append({"job": job()})

    assert is_closed(GUID) is False


def test_is_closed_builds_the_documented_url(api):
    api.responses.append({"job": job()})

    is_closed("https://himalayas.app/companies/linear/jobs/senior-product-engineer")

    assert api.domains == [DOMAIN]
    assert requested(api) == ["https://himalayas.app/jobs/api/companies/linear/jobs/senior-product-engineer"]
    assert sleeps(api) == []


def test_is_closed_ignores_a_query_string_on_the_id(api):
    api.responses.append({"job": job()})

    is_closed(f"{GUID}?utm_source=api")

    assert requested(api) == ["https://himalayas.app/jobs/api/companies/acme/jobs/senior-devops-engineer"]


@pytest.mark.parametrize("message", ["blocked (429)", "blocked (403)", "source returned 500", "disallowed by robots.txt"])
def test_is_closed_lets_any_other_fetch_error_through(api, message):
    api.responses.append(FetchError(message))

    with pytest.raises(FetchError, match=re.escape(message)):
        is_closed(GUID)


@pytest.mark.parametrize(
    "external_id",
    ["", "not a url", "http://himalayas.app/companies/a/jobs/b", "https://example.com/companies/a/jobs/b", "https://himalayas.app/jobs/api"],
)
def test_is_closed_refuses_ids_that_are_not_himalayas_job_urls(api, external_id):
    with pytest.raises(FetchError):
        is_closed(external_id)

    assert api.events == []
