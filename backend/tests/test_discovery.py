from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.models import Company, Job, JobSource, User, utcnow
from app.sources import discovery
from app.sources.ats import Feed
from app.sources.fetch import FetchError


def make_user(db, email: str = "a@example.com") -> int:
    user = User(email=email)
    db.add(user)
    db.flush()
    return user.id


def add_source(db, user_id: int, domain: str, kind: str = "board", status: str = "active") -> None:
    db.add(JobSource(user_id=user_id, domain=domain, kind=kind, status=status))


def add_job(db, source: str, company: str, eligible: list[str] | None = None, n: list[int] = [0]) -> None:
    n[0] += 1
    db.add(Job(source=source, external_id=f"{source}/{n[0]}", url="", title="Role", company=company, eligible_countries=eligible or []))


def keys(db, user_id: int) -> dict[str, Company]:
    return {company.key: company for company in db.scalars(select(Company).where(Company.user_id == user_id))}


def test_companies_are_collected_from_board_postings_and_spellings_are_merged(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        add_source(db, user_id, "ejobs.ro")
        for name in ("Bosch Romania", "BOSCH ROMANIA SRL", "Bosch Romania"):
            add_job(db, "ejobs.ro", name)
        add_job(db, "ejobs.ro", "eMAG")
        db.commit()
        assert discovery.seed_companies(db, user_id, "RO") == 2
        found = keys(db, user_id)
        assert set(found) == {"bosch romania", "emag"}
        assert (found["bosch romania"].name, found["bosch romania"].postings) == ("Bosch Romania", 3)


def test_only_jobs_open_to_the_country_count(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        add_source(db, user_id, "remoteok.com")
        add_job(db, "remoteok.com", "Worldwide Co", eligible=[])
        add_job(db, "remoteok.com", "Romania Co", eligible=["RO", "PL"])
        add_job(db, "remoteok.com", "US Only Co", eligible=["US"])
        db.commit()
        discovery.seed_companies(db, user_id, "RO")
        assert set(keys(db, user_id)) == {"worldwide co", "romania co"}


def test_unnamed_short_and_employer_source_companies_are_left_out(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        add_source(db, user_id, "ejobs.ro")
        add_source(db, user_id, "veeamsoftware.greenhouse.io", kind="employer")
        add_source(db, user_id, "closed.example", status="failed")
        add_job(db, "ejobs.ro", "Confidential")
        add_job(db, "ejobs.ro", "ABC")
        add_job(db, "ejobs.ro", "")
        add_job(db, "veeamsoftware.greenhouse.io", "Veeam Software")
        add_job(db, "closed.example", "From Failed Source")
        add_job(db, "ejobs.ro", "Real Company")
        db.commit()
        discovery.seed_companies(db, user_id, "RO")
        assert set(keys(db, user_id)) == {"real company"}


def test_seeding_again_updates_counts_and_does_not_duplicate_or_reset_a_checked_company(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        add_source(db, user_id, "ejobs.ro")
        add_job(db, "ejobs.ro", "Acme Systems")
        db.commit()
        discovery.seed_companies(db, user_id, "RO")
        keys(db, user_id)["acme systems"].status = "none"
        add_job(db, "ejobs.ro", "Acme Systems")
        db.commit()
        assert discovery.seed_companies(db, user_id, "RO") == 0
        company = keys(db, user_id)["acme systems"]
        assert (company.postings, company.status) == (2, "none")


def test_each_user_gets_their_own_company_list(session_factory):
    with session_factory() as db:
        first, second = make_user(db, "one@example.com"), make_user(db, "two@example.com")
        add_source(db, first, "ejobs.ro")
        add_source(db, second, "hipo.ro")
        add_job(db, "ejobs.ro", "Only First")
        add_job(db, "hipo.ro", "Only Second")
        db.commit()
        discovery.seed_companies(db, first, "RO")
        discovery.seed_companies(db, second, "RO")
        assert set(keys(db, first)) == {"only first"}
        assert set(keys(db, second)) == {"only second"}


def add_company(db, user_id: int, name: str, postings: int, status: str = "unchecked", checked_days_ago: float | None = None) -> None:
    checked = utcnow() - timedelta(days=checked_days_ago) if checked_days_ago is not None else None
    db.add(Company(user_id=user_id, key=name.lower(), name=name, postings=postings, status=status, checked_at=checked))


WHOLE_PERIOD = timedelta(days=5)


def probe(db, user_id: int, finder, tick: timedelta = WHOLE_PERIOD):
    # The default tick is the whole cover period, so every company is due in the one call.
    with patch.object(discovery, "find_feed_for_company", side_effect=finder) as find, patch.object(discovery.time, "sleep") as sleep, patch.object(
        discovery, "SafeFetcher"
    ):
        created = discovery.discover_feeds(db, user_id, "RO", tick)
    return created, find, sleep


def test_a_found_feed_becomes_an_employer_source_and_the_company_is_marked(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        add_company(db, user_id, "Veeam Software", 9)
        add_company(db, user_id, "No Feed Ltd", 3)
        db.commit()
        created, _, _ = probe(db, user_id, lambda name, country, fetcher: Feed("greenhouse", "veeamsoftware") if name.startswith("Veeam") else None)
        assert [(s.domain, s.kind, s.ats_provider, s.ats_slug) for s in created] == [("veeamsoftware.greenhouse.io", "employer", "greenhouse", "veeamsoftware")]
        found = keys(db, user_id)
        assert (found["veeam software"].status, found["veeam software"].ats_slug) == ("feed", "veeamsoftware")
        assert found["no feed ltd"].status == "none" and found["no feed ltd"].checked_at is not None


def test_a_tick_probes_its_share_best_known_first(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        for number in range(25):
            add_company(db, user_id, f"Company {number:02d}", number)
        db.commit()
        asked = []
        # 25 companies over 5 days of 12 hour ticks is 10 ticks, so ceil(25 / 10) = 3 a tick.
        _, find, sleep = probe(db, user_id, lambda name, country, fetcher: asked.append(name), tick=timedelta(hours=12))
        assert asked == ["Company 24", "Company 23", "Company 22"]
        assert sleep.call_count == 2


def test_every_company_is_probed_within_the_cover_period(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        for number in range(45):
            add_company(db, user_id, f"Company {number:02d}", number)
        db.commit()
        for _ in range(10):
            probe(db, user_id, lambda name, country, fetcher: None, tick=timedelta(hours=12))
        assert db.query(Company).filter(Company.status == "unchecked").count() == 0


@pytest.mark.parametrize(
    "total, tick, expected",
    [
        (399, timedelta(minutes=30), 2),
        (240, timedelta(minutes=30), 1),
        (241, timedelta(minutes=30), 2),
        (1000, timedelta(minutes=30), 5),
        (399, timedelta(hours=12), 40),
        (0, timedelta(minutes=30), 1),
        (1, timedelta(minutes=30), 1),
    ],
)
def test_probes_per_tick_spreads_the_companies_over_the_cover_days(total, tick, expected):
    assert discovery.probes_per_tick(total, tick) == expected


def test_the_probes_of_one_cover_period_always_add_up_to_every_company():
    tick = timedelta(minutes=30)
    ticks_in_period = timedelta(days=5) / tick
    for total in range(0, 5000, 37):
        assert discovery.probes_per_tick(total, tick) * ticks_in_period >= total


def test_checked_companies_are_not_probed_again_until_a_month_has_passed(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        add_company(db, user_id, "Fresh None", 5, status="none", checked_days_ago=3)
        add_company(db, user_id, "Old None", 5, status="none", checked_days_ago=45)
        add_company(db, user_id, "Has Feed", 5, status="feed", checked_days_ago=45)
        add_company(db, user_id, "Never Asked", 1)
        db.commit()
        asked = []
        probe(db, user_id, lambda name, country, fetcher: asked.append(name))
        assert sorted(asked) == ["Never Asked", "Old None"]


def test_a_block_stops_the_run_and_leaves_the_rest_unchecked(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        add_company(db, user_id, "First", 9)
        add_company(db, user_id, "Second", 8)
        add_company(db, user_id, "Third", 7)
        db.commit()

        def finder(name, country, fetcher):
            if name == "Second":
                raise FetchError("blocked (429)")
            return None

        probe(db, user_id, finder)
        found = keys(db, user_id)
        assert found["first"].status == "none"
        assert found["second"].status == "unchecked" and found["second"].checked_at is None
        assert found["third"].status == "unchecked"


def test_a_feed_that_already_has_a_source_does_not_get_a_second_one(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        add_source(db, user_id, "emag.greenhouse.io", kind="employer")
        add_company(db, user_id, "eMAG", 19)
        db.commit()
        created, _, _ = probe(db, user_id, lambda name, country, fetcher: Feed("greenhouse", "emag"))
        assert created == []
        assert db.query(JobSource).filter(JobSource.domain == "emag.greenhouse.io").count() == 1
        assert keys(db, user_id)["emag"].status == "feed"


def lookup(db, user_id: int, answers, minimum: int = 1):
    with patch.object(discovery, "MIN_DOMAIN_BATCH", minimum), patch.object(discovery, "propose_domains", side_effect=answers) as ask:
        return discovery.enrich_domains(db, user_id, "RO"), ask


def test_a_plausible_domain_is_kept_and_an_unrelated_or_missing_one_is_stored_as_unknown(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        for name in ("eMAG", "Bosch Romania", "Made Up Ltd", "Silent Corp"):
            add_company(db, user_id, name, 5)
        db.commit()
        answers = lambda names, country: [  # noqa: E731
            {"company": "emag", "domain": "https://www.eMAG.ro/careers"},
            {"company": "bosch romania", "domain": "bosch.com"},
            {"company": "made up ltd", "domain": "totally-different.example"},
        ]
        found, _ = lookup(db, user_id, answers)
        domains = {company.name: company.domain for company in db.scalars(select(Company))}
        assert found == 2
        assert domains == {"eMAG": "emag.ro", "Bosch Romania": "bosch.com", "Made Up Ltd": "", "Silent Corp": ""}


def test_only_companies_nobody_asked_about_are_looked_up_best_known_first_and_in_batches(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        for number in range(45):
            add_company(db, user_id, f"Company {number:02d}", number)
        done = Company(user_id=user_id, key="already known", name="Already Known", postings=999, domain="")
        db.add(done)
        db.commit()
        asked = []
        lookup(db, user_id, lambda names, country: asked.append(list(names)) or [])
        assert len(asked[0]) == discovery.MAX_DOMAIN_LOOKUPS
        assert asked[0][0] == "Company 44" and "Already Known" not in asked[0]
        again = []
        lookup(db, user_id, lambda names, country: again.append(list(names)) or [])
        assert len(again[0]) == 5


def test_nothing_is_asked_when_every_company_has_an_answer(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        db.add(Company(user_id=user_id, key="done corp", name="Done Corp", postings=1, domain=""))
        db.commit()
        found, ask = lookup(db, user_id, lambda names, country: [])
        assert found == 0
        ask.assert_not_called()


def test_a_failed_lookup_leaves_the_companies_to_be_asked_again(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        add_company(db, user_id, "Retry Corp", 3)
        db.commit()

        def failing(names, country):
            raise RuntimeError("vertex down")

        with pytest.raises(RuntimeError):
            lookup(db, user_id, failing)
        assert db.scalar(select(Company.domain)) is None


@pytest.mark.parametrize(
    "name, domain, fits",
    [
        ("eMAG", "emag.ro", True),
        ("Bosch Romania", "bosch.com", True),
        ("ING Hubs Romania", "ing.com", True),
        ("KPMG in Romania", "kpmg.com", True),
        ("Orange S.A. France", "orange.com", True),
        ("Societe Generale Global Solution Centre", "societegenerale.com", True),
        ("Leroy Merlin", "leroymerlin.ro", True),
        ("EY Romania", "ey.com", True),
        ("NN Asigurari de Viata", "nn.ro", True),
        ("EY Romania", "ab.com", False),
        ("Bosch Romania", "siemens.com", False),
        ("Acme Systems", "totally-different.example", False),
        ("Anything", "co.uk", False),
    ],
)
def test_domain_fits_the_company_name(name, domain, fits):
    assert discovery.domain_fits(name, domain) is fits


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://www.Bosch.com/en/careers", "bosch.com"),
        ("emag.ro", "emag.ro"),
        ("  WWW.Veeam.com  ", "veeam.com"),
        ("not a domain", ""),
        ("", ""),
        ("localhost", ""),
    ],
)
def test_the_domain_is_reduced_to_a_bare_host(raw, expected):
    assert discovery._clean_domain(raw) == expected


def test_a_handful_of_new_companies_waits_for_a_worthwhile_batch_before_the_model_is_asked(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        for number in range(discovery.MIN_DOMAIN_BATCH - 1):
            add_company(db, user_id, f"Company {number:02d}", 1)
        db.commit()
        found, ask = lookup(db, user_id, lambda names, country: [], minimum=discovery.MIN_DOMAIN_BATCH)
        assert found == 0
        ask.assert_not_called()
        add_company(db, user_id, "The Tenth One", 1)
        db.commit()
        lookup(db, user_id, lambda names, country: [], minimum=discovery.MIN_DOMAIN_BATCH)[1].assert_called_once()


def hinted(db, user_id: int, name: str, postings: int, provider: str, token: str) -> None:
    db.add(Company(user_id=user_id, key=name.lower(), name=name, postings=postings, board_provider=provider, board_token=token))


def test_a_company_with_a_readable_directory_board_is_probed_first_and_through_that_board(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        add_company(db, user_id, "Big Unhinted", 99)
        hinted(db, user_id, "Small Hinted", 1, "greenhouse", "smallhinted")
        db.commit()
        order = []
        with patch.object(discovery, "find_feed_for_board", side_effect=lambda provider, token, country, fetcher: order.append(("board", token))) as board_probe, patch.object(
            discovery, "find_feed_for_company", side_effect=lambda name, country, fetcher: order.append(("name", name))
        ), patch.object(discovery.time, "sleep"), patch.object(discovery, "SafeFetcher"):
            discovery.discover_feeds(db, user_id, "RO", WHOLE_PERIOD)
        assert order == [("board", "smallhinted"), ("name", "Big Unhinted")]
        assert board_probe.call_args.args[:3] == ("greenhouse", "smallhinted", "RO")


def test_a_board_on_a_provider_we_cannot_read_does_not_jump_the_queue_and_is_probed_by_name(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        add_company(db, user_id, "Plain Corp", 5)
        hinted(db, user_id, "On Ashby", 1, "ashby", "onashby")
        db.commit()
        order = []
        with patch.object(discovery, "find_feed_for_board") as board_probe, patch.object(
            discovery, "find_feed_for_company", side_effect=lambda name, country, fetcher: order.append(name)
        ), patch.object(discovery.time, "sleep"), patch.object(discovery, "SafeFetcher"):
            discovery.discover_feeds(db, user_id, "RO", WHOLE_PERIOD)
        assert order == ["Plain Corp", "On Ashby"]
        board_probe.assert_not_called()


def test_a_feed_found_through_the_directory_gets_the_providers_careers_url_and_a_workday_domain(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        hinted(db, user_id, "Danaher", 3, "workday", "wd1/danaher/DanaherJobs")
        db.commit()
        feed = Feed("workday", "danaher.wd1/DanaherJobs")
        with patch.object(discovery, "find_feed_for_board", return_value=feed), patch.object(discovery.time, "sleep"), patch.object(discovery, "SafeFetcher"):
            created = discovery.discover_feeds(db, user_id, "RO", WHOLE_PERIOD)
        assert [(source.domain, source.source_url, source.ats_slug) for source in created] == [
            ("danaherjobs.danaher.myworkdayjobs.com", "https://danaher.wd1.myworkdayjobs.com/DanaherJobs", "danaher.wd1/DanaherJobs")
        ]
