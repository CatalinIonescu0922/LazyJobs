from unittest.mock import MagicMock, patch

import pytest

from app.sources import ats
from app.sources.ats import Feed, find_feed_for_company, parse_ats_url, source_domain
from app.sources.fetch import FetchError

BASE = "https://boards-api.greenhouse.io/v1/boards"


def board(responses: dict):
    requested = []

    def fake(fetcher, url, body=None):
        requested.append(url)
        answer = responses.get(url, FetchError("source returned 404"))
        if isinstance(answer, Exception):
            raise answer
        return answer

    return fake, requested


def jobs_in(*places: str) -> dict:
    return {"jobs": [{"location": {"name": place}} for place in places]}


def find(name: str, responses: dict, country: str = "RO"):
    fake, requested = board(responses)
    with patch.object(ats, "_get_json", fake):
        return find_feed_for_company(name, country, MagicMock()), requested


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Bosch Romania", ["bosch"]),
        ("Veeam Software", ["veeamsoftware", "veeam"]),
        ("ING Hubs Romania", ["inghubs"]),
        ("BLACKLINE SYSTEMS SRL", ["blacklinesystems", "blackline"]),
        ("KPMG in Romania", ["kpmgin", "kpmg"]),
        ("Romania", ["romania"]),
        ("", []),
    ],
)
def test_slugs_come_from_the_name_without_legal_suffixes_and_the_country(name, expected):
    assert ats._name_slugs(name) == expected


def test_a_board_with_a_job_in_the_country_and_a_matching_name_is_accepted():
    feed, requested = find(
        "Veeam Software",
        {f"{BASE}/veeamsoftware/jobs": jobs_in("San Jose, CA, USA", "Bucharest, Romania"), f"{BASE}/veeamsoftware": {"name": "Veeam Software"}},
    )
    assert feed == Feed("greenhouse", "veeamsoftware")
    assert all(url.startswith(BASE) for url in requested)


def test_an_unknown_first_slug_falls_through_to_the_next_one():
    feed, _ = find(
        "Veeam Software",
        {f"{BASE}/veeam/jobs": jobs_in("Remote - Romania"), f"{BASE}/veeam": {"name": "Veeam"}},
    )
    assert feed == Feed("greenhouse", "veeam")


def test_a_board_with_no_job_in_the_country_is_rejected():
    feed, _ = find("Wise Payments", {f"{BASE}/wisepayments/jobs": jobs_in("London, United Kingdom", "Tallinn, Estonia")})
    assert feed is None


def test_a_board_of_another_company_is_rejected_even_with_a_job_in_the_country():
    feed, _ = find("Mega Image", {f"{BASE}/megaimage/jobs": jobs_in("Bucharest, Romania"), f"{BASE}/megaimage": {"name": "Something Else Entirely"}})
    assert feed is None


def test_a_block_is_not_swallowed():
    fake, _ = board({f"{BASE}/emag/jobs": FetchError("blocked (429)")})
    with patch.object(ats, "_get_json", fake), pytest.raises(FetchError, match="blocked"):
        find_feed_for_company("eMAG", "RO", MagicMock())


def test_a_failed_connection_is_not_swallowed():
    fake, _ = board({f"{BASE}/emag/jobs": FetchError("source request failed (ConnectError)")})
    with patch.object(ats, "_get_json", fake), pytest.raises(FetchError):
        find_feed_for_company("eMAG", "RO", MagicMock())


def test_the_source_domain_is_unique_per_company_and_per_workday_site():
    assert source_domain(Feed("greenhouse", "VeeamSoftware")) == "veeamsoftware.greenhouse.io"
    assert source_domain(Feed("smartrecruiters", "BoschGroup")) == "boschgroup.smartrecruiters.com"
    one = parse_ats_url("https://accenture.wd103.myworkdayjobs.com/AccentureCareers")
    other = parse_ats_url("https://accenture.wd103.myworkdayjobs.com/AvanadeCareers")
    assert source_domain(one) == "accenturecareers.accenture.myworkdayjobs.com"
    assert source_domain(one) != source_domain(other)


def board_api(responses: dict):
    fake, requested = board(responses)
    return fake, requested


def verify(provider: str, token: str, responses: dict, country: str = "RO"):
    fake, requested = board_api(responses)
    with patch.object(ats, "_get_json", fake), patch.object(ats, "SafeFetcher"):
        return ats.find_feed_for_board(provider, token, country, MagicMock()), requested


def test_a_directory_greenhouse_board_with_a_job_in_the_country_is_accepted_without_a_name_check():
    feed, requested = verify("greenhouse", "veeamsoftware", {f"{BASE}/veeamsoftware/jobs": jobs_in("Bucharest, Romania")})
    assert feed == Feed("greenhouse", "veeamsoftware")
    assert requested == [f"{BASE}/veeamsoftware/jobs"]


def test_a_directory_board_with_no_job_in_the_country_or_that_is_gone_is_rejected():
    assert verify("greenhouse", "wise", {f"{BASE}/wise/jobs": jobs_in("London, United Kingdom")})[0] is None
    assert verify("greenhouse", "gone", {})[0] is None


def test_a_block_on_a_directory_board_is_not_swallowed():
    fake, _ = board({f"{BASE}/nebius/jobs": FetchError("blocked (429)")})
    with patch.object(ats, "_get_json", fake), pytest.raises(FetchError):
        ats.find_feed_for_board("greenhouse", "nebius", "RO", MagicMock())


def test_a_directory_workday_triple_becomes_the_feed_slug_and_reads_its_own_host():
    fetchers = []
    with patch.object(ats, "SafeFetcher", side_effect=lambda host: fetchers.append(host) or MagicMock()), patch.object(ats, "_rejection", return_value=None) as rejection:
        feed = ats.find_feed_for_board("workday", "wd1/danaher/DanaherJobs", "ro", MagicMock())
    assert feed == Feed("workday", "danaher.wd1/DanaherJobs")
    assert fetchers == ["danaher.wd1.myworkdayjobs.com"]
    assert rejection.call_args.args[2:] == ("RO", None)


@pytest.mark.parametrize("provider, token", [("workday", "danaher/DanaherJobs"), ("workable", "european-dynamics"), ("ashby", "plaid"), ("lever", "x")])
def test_a_board_we_cannot_read_or_a_malformed_workday_token_gives_no_feed(provider, token):
    assert ats.find_feed_for_board(provider, token, "RO", MagicMock()) is None


def test_careers_urls_point_at_each_providers_public_page():
    assert ats.careers_url(Feed("greenhouse", "emag")) == "https://boards.greenhouse.io/emag"
    assert ats.careers_url(Feed("workday", "danaher.wd1/DanaherJobs")) == "https://danaher.wd1.myworkdayjobs.com/DanaherJobs"
    assert ats.careers_url(Feed("smartrecruiters", "BoschGroup")) == "https://jobs.smartrecruiters.com/BoschGroup"
