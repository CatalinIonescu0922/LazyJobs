from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.models import Company, JobSource, User, utcnow
from app.routers.companies import list_companies


def make_user(db, email: str = "a@example.com") -> User:
    user = User(email=email)
    db.add(user)
    db.flush()
    return user


def company(db, user: User, name: str, postings: int = 1, status: str = "unchecked", domain: str | None = None, provider: str = "", slug: str = "", board: str | None = None) -> Company:
    item = Company(
        user_id=user.id, key=name.lower(), name=name, postings=postings, status=status, domain=domain, ats_provider=provider, ats_slug=slug, board_provider=board,
        checked_at=utcnow() if status != "unchecked" else None,
    )
    db.add(item)
    return item


def feed(db, user: User, domain: str, provider: str, slug: str, jobs: int = 10, status: str = "active", hours_ago: float | None = 1) -> JobSource:
    source = JobSource(
        user_id=user.id, domain=domain, kind="employer", status=status, ats_provider=provider, ats_slug=slug, posting_count=jobs,
        source_url=f"https://boards.greenhouse.io/{slug}", last_refreshed_at=utcnow() - timedelta(hours=hours_ago) if hours_ago is not None else None,
    )
    db.add(source)
    return source


def call(db, user: User, **params):
    arguments = {"status": "all", "search": "", "limit": 60, "offset": 0}
    arguments.update(params)
    return list_companies(user=user, db=db, **arguments)


def test_counts_cover_every_status_and_ignore_the_filter(session_factory):
    with session_factory() as db:
        user = make_user(db)
        company(db, user, "A Corp", status="feed")
        company(db, user, "B Corp", status="none")
        company(db, user, "C Corp", status="none")
        company(db, user, "D Corp")
        db.commit()
        result = call(db, user, status="none")
        assert result.counts.model_dump() == {"total": 4, "feed": 1, "none": 2, "unchecked": 1}
        assert result.total_matching == 2
        assert {item.name for item in result.companies} == {"B Corp", "C Corp"}


def test_companies_are_sorted_by_postings_then_name_and_paged(session_factory):
    with session_factory() as db:
        user = make_user(db)
        for name, postings in (("Zeta", 5), ("Alpha", 5), ("Big", 50), ("Small", 1)):
            company(db, user, name, postings=postings)
        db.commit()
        assert [item.name for item in call(db, user).companies] == ["Big", "Alpha", "Zeta", "Small"]
        second = call(db, user, limit=2, offset=2)
        assert [item.name for item in second.companies] == ["Zeta", "Small"]
        assert second.total_matching == 4


def test_search_matches_part_of_a_name_without_regard_to_case_and_treats_wildcards_literally(session_factory):
    with session_factory() as db:
        user = make_user(db)
        company(db, user, "Veeam Software")
        company(db, user, "Bosch Romania")
        company(db, user, "100% Cotton Ltd")
        db.commit()
        assert [item.name for item in call(db, user, search="VEEAM").companies] == ["Veeam Software"]
        assert [item.name for item in call(db, user, search="%").companies] == ["100% Cotton Ltd"]
        assert call(db, user, search="nothing like this").total_matching == 0


def test_each_user_only_sees_their_own_companies(session_factory):
    with session_factory() as db:
        first, second = make_user(db, "one@example.com"), make_user(db, "two@example.com")
        company(db, first, "Mine")
        company(db, second, "Theirs")
        db.commit()
        result = call(db, first)
        assert [item.name for item in result.companies] == ["Mine"]
        assert result.counts.total == 1


def test_a_company_with_a_feed_carries_the_jobs_and_status_of_its_source(session_factory):
    with session_factory() as db:
        user = make_user(db)
        company(db, user, "eMAG", postings=19, status="feed", domain="emag.ro", provider="greenhouse", slug="emag")
        feed(db, user, "emag.greenhouse.io", "greenhouse", "emag", jobs=18)
        db.commit()
        card = call(db, user).companies[0]
        assert (card.status, card.provider, card.provider_label, card.jobs, card.source_status) == ("feed", "greenhouse", "Greenhouse", 18, "active")
        assert card.logo_url == "https://www.google.com/s2/favicons?domain=emag.ro&sz=64"


def test_a_company_without_a_feed_has_no_jobs_and_no_logo_when_its_domain_is_unknown(session_factory):
    with session_factory() as db:
        user = make_user(db)
        company(db, user, "Unknown Ltd", status="none", domain="")
        company(db, user, "Never Asked Ltd", domain=None)
        db.commit()
        for card in call(db, user).companies:
            assert (card.jobs, card.source_status, card.domain, card.logo_url, card.provider_label) == (None, None, "", "", "")


def test_feeds_list_every_employer_feed_regardless_of_filter_and_newest_first(session_factory):
    with session_factory() as db:
        user = make_user(db)
        feed(db, user, "old.greenhouse.io", "greenhouse", "old", hours_ago=30)
        feed(db, user, "new.greenhouse.io", "greenhouse", "new", hours_ago=2)
        feed(db, user, "never.greenhouse.io", "greenhouse", "never", hours_ago=None, status="candidate")
        db.add(JobSource(user_id=user.id, domain="ejobs.ro", kind="board", status="active"))
        db.add(JobSource(user_id=user.id, domain="plain.example", kind="employer", status="active"))
        db.commit()
        result = call(db, user, status="none", search="zzz")
        assert [item.provider_label for item in result.feeds] == ["Greenhouse"] * 3
        assert [item.slug for item in result.feeds] == ["new", "old", "never"]
        assert result.companies == []


def test_a_feed_is_named_and_given_a_logo_from_its_company(session_factory):
    with session_factory() as db:
        user = make_user(db)
        company(db, user, "eMAG", status="feed", domain="emag.ro", provider="greenhouse", slug="emag")
        feed(db, user, "emag.greenhouse.io", "greenhouse", "emag")
        db.commit()
        card = call(db, user).feeds[0]
        assert (card.name, card.domain) == ("eMAG", "emag.ro")
        assert card.logo_url.endswith("domain=emag.ro&sz=64")
        assert card.careers_url == "https://boards.greenhouse.io/emag"


def test_a_feed_added_by_hand_is_matched_to_its_company_by_name(session_factory):
    with session_factory() as db:
        user = make_user(db)
        company(db, user, "Veeam Software", postings=9, domain="veeam.com")
        feed(db, user, "veeamsoftware.greenhouse.io", "greenhouse", "veeamsoftware")
        db.commit()
        card = call(db, user).feeds[0]
        assert (card.name, card.domain) == ("Veeam Software", "veeam.com")


def test_a_workday_feed_uses_its_tenant_as_the_name_when_no_company_matches(session_factory):
    with session_factory() as db:
        user = make_user(db)
        feed(db, user, "accenturecareers.accenture.myworkdayjobs.com", "workday", "accenture.wd103/AccentureCareers", jobs=34)
        db.commit()
        card = call(db, user).feeds[0]
        assert (card.name, card.provider_label, card.logo_url, card.jobs) == ("Accenture", "Workday", "", 34)


def test_an_unknown_status_is_refused_and_the_page_size_is_clamped(session_factory):
    with session_factory() as db:
        user = make_user(db)
        for number in range(3):
            company(db, user, f"Company {number}")
        db.commit()
        with pytest.raises(HTTPException) as refused:
            call(db, user, status="everything")
        assert refused.value.status_code == 400
        assert len(call(db, user, limit=0).companies) == 1
        assert len(call(db, user, limit=10_000).companies) == 3
        assert len(call(db, user, offset=-5).companies) == 3


def test_a_company_reports_the_board_the_directory_knows_and_whether_it_is_readable(session_factory):
    with session_factory() as db:
        user = make_user(db)
        company(db, user, "On Ashby", postings=5, board="ashby")
        company(db, user, "On Greenhouse", postings=4, board="greenhouse")
        company(db, user, "Not Listed", postings=3, board="")
        company(db, user, "Not Matched Yet", postings=2, board=None)
        db.commit()
        cards = {card.name: card for card in call(db, user).companies}
        assert (cards["On Ashby"].known_board, cards["On Ashby"].known_board_readable) == ("Ashby", False)
        assert (cards["On Greenhouse"].known_board, cards["On Greenhouse"].known_board_readable) == ("Greenhouse", True)
        for name in ("Not Listed", "Not Matched Yet"):
            assert (cards[name].known_board, cards[name].known_board_readable) == ("", False)
