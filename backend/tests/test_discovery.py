from datetime import timedelta
from unittest.mock import MagicMock, patch

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


def probe(db, user_id: int, finder):
    with patch.object(discovery, "find_feed_for_company", side_effect=finder) as find, patch.object(discovery.time, "sleep") as sleep, patch.object(
        discovery, "SafeFetcher"
    ):
        created = discovery.discover_feeds(db, user_id, "RO")
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


def test_the_best_known_companies_are_probed_first_and_only_twenty_per_run(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        for number in range(25):
            add_company(db, user_id, f"Company {number:02d}", number)
        db.commit()
        asked = []
        _, find, sleep = probe(db, user_id, lambda name, country, fetcher: asked.append(name))
        assert find.call_count == discovery.MAX_PROBES
        assert asked[0] == "Company 24" and asked[-1] == "Company 05"
        assert sleep.call_count == discovery.MAX_PROBES - 1


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
