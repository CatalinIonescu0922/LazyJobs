import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.models import AtsBoard, Company, User, utcnow
from app.sources import directory
from app.sources.fetch import FetchError, FetchResult


@pytest.fixture(autouse=True)
def fresh_backoff_and_small_minimum():
    directory._retry_not_before = None
    with patch.object(directory, "MIN_ROWS", 2):
        yield
    directory._retry_not_before = None


def board(platform: str, token: str, company: str, roles: int = 10) -> dict:
    return {"platform": platform, "token": token, "company": company, "open_roles": roles, "board_url": "https://ignored.example", "api_url": "https://ignored.example/api"}


GOOD = [
    board("greenhouse", "veeamsoftware", "Veeam Software", 195),
    board("workable", "european-dynamics", "European Dynamics", 172),
    board("workday", "wd1/danaher/DanaherJobs", "danaher", 1432),
]


def fake_fetcher(payload) -> MagicMock:
    fetcher = MagicMock()
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    fetcher.get.return_value = FetchResult("https://x", 200, body, "application/json")
    return fetcher


def run_import(db, payload):
    fetcher = fake_fetcher(payload)
    with patch.object(directory, "SafeFetcher", return_value=fetcher):
        return directory.import_directory(db), fetcher


def make_user(db, email: str = "a@example.com") -> int:
    user = User(email=email)
    db.add(user)
    db.flush()
    return user.id


def test_a_valid_directory_is_stored_with_the_keys_used_for_matching(session_factory):
    with session_factory() as db:
        count, fetcher = run_import(db, GOOD)
        assert count == 3
        assert fetcher.get.call_args.kwargs == {"sitemap": True}
        rows = {(row.provider, row.token): row for row in db.scalars(select(AtsBoard))}
        veeam = rows[("greenhouse", "veeamsoftware")]
        assert (veeam.key, veeam.token_key, veeam.open_roles) == ("veeamsoftware", "veeamsoftware", 195)
        danaher = rows[("workday", "wd1/danaher/DanaherJobs")]
        assert danaher.token_key == "danaher"


@pytest.mark.parametrize(
    "bad",
    [
        board("greenhouse", "has space", "X"),
        board("greenhouse", "-leadingdash", "X"),
        board("greenhouse", "a" * 300, "X"),
        board("workday", "danaher/DanaherJobs", "X"),
        board("workday", "wd1/danaher", "X"),
        board("", "token", "X"),
        {"platform": "greenhouse"},
        "not an object",
    ],
)
def test_rows_with_unsafe_or_malformed_tokens_are_dropped(session_factory, bad):
    with session_factory() as db:
        count, _ = run_import(db, [*GOOD, bad])
        assert count == 3


def test_a_negative_or_missing_role_count_becomes_zero(session_factory):
    with session_factory() as db:
        run_import(db, [board("greenhouse", "alpha", "Alpha", -5), {"platform": "lever", "token": "beta", "company": "Beta"}])
        assert [row.open_roles for row in db.scalars(select(AtsBoard))] == [0, 0]


def test_a_fresh_copy_is_not_downloaded_again_and_an_old_one_is(session_factory):
    with session_factory() as db:
        run_import(db, GOOD)
        count, fetcher = run_import(db, GOOD)
        assert count is None
        fetcher.get.assert_not_called()
        for row in db.scalars(select(AtsBoard)):
            row.imported_at = utcnow() - directory.REFRESH_AFTER - timedelta(days=1)
        db.commit()
        count, fetcher = run_import(db, GOOD + [board("ashby", "plaid", "Plaid")])
        assert count == 4
        fetcher.get.assert_called_once()


def test_a_new_import_replaces_the_old_boards_and_rematches_companies_that_are_not_feeds(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        db.add(Company(user_id=user_id, key="a", name="A", status="none", board_provider="greenhouse", board_token="old"))
        db.add(Company(user_id=user_id, key="b", name="B", status="feed", board_provider="greenhouse", board_token="kept"))
        db.commit()
        run_import(db, GOOD)
        for row in db.scalars(select(AtsBoard)):
            row.imported_at = utcnow() - directory.REFRESH_AFTER - timedelta(days=1)
        db.commit()
        run_import(db, [board("greenhouse", "only-one", "Only One"), board("lever", "two", "Two")])
        assert sorted(row.token for row in db.scalars(select(AtsBoard))) == ["only-one", "two"]
        companies = {company.key: company for company in db.scalars(select(Company))}
        assert (companies["a"].board_provider, companies["a"].board_token) == (None, None)
        assert (companies["b"].board_provider, companies["b"].board_token) == ("greenhouse", "kept")


@pytest.mark.parametrize("payload", [b"<html>not json</html>", {"not": "a list"}, [board("greenhouse", "only-one", "One")]])
def test_a_broken_download_keeps_the_stored_copy_and_waits_before_trying_again(session_factory, payload):
    with session_factory() as db:
        run_import(db, GOOD)
        for row in db.scalars(select(AtsBoard)):
            row.imported_at = utcnow() - directory.REFRESH_AFTER - timedelta(days=1)
        db.commit()
        count, _ = run_import(db, payload)
        assert count is None
        assert db.query(AtsBoard).count() == 3
        again, fetcher = run_import(db, GOOD)
        assert again is None
        fetcher.get.assert_not_called()


def test_a_failed_fetch_is_handled_and_backs_off(session_factory):
    with session_factory() as db:
        fetcher = MagicMock()
        fetcher.get.side_effect = FetchError("blocked (429)")
        with patch.object(directory, "SafeFetcher", return_value=fetcher):
            assert directory.import_directory(db) is None
            assert directory.import_directory(db) is None
        assert fetcher.get.call_count == 1
        assert db.query(AtsBoard).count() == 0


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Veeam Software", ["veeamsoftware"]),
        ("Bosch Romania", ["bosch"]),
        ("ROBERT BOSCH SRL", ["robertbosch"]),
        ("Societe Generale Global Solution Centre", ["societegeneraleglobalsolutioncentre", "societegenerale"]),
        ("eMAG", ["emag"]),
        ("AB", []),
    ],
)
def test_name_keys_are_the_whole_name_or_its_first_two_words(name, expected):
    assert directory.name_keys(name) == expected


def add_company(db, user_id: int, name: str) -> None:
    db.add(Company(user_id=user_id, key=name.lower(), name=name, postings=1))


def matched(db) -> dict[str, tuple]:
    return {company.name: (company.board_provider, company.board_token) for company in db.scalars(select(Company))}


def test_a_company_is_matched_by_its_whole_name_and_never_by_a_first_word(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        for name in ("Veeam Software", "ROBERT BOSCH SRL", "TODAY SOFTWARE SOLUTIONS SRL", "Nebius"):
            add_company(db, user_id, name)
        db.commit()
        run_import(db, [board("greenhouse", "veeamsoftware", "Veeam Software"), board("recruitee", "robert", ""), board("workable", "today", "Today"), board("greenhouse", "nebius", "Nebius")])
        assert directory.match_companies(db, user_id) == 2
        assert matched(db) == {
            "Veeam Software": ("greenhouse", "veeamsoftware"),
            "ROBERT BOSCH SRL": ("", ""),
            "TODAY SOFTWARE SOLUTIONS SRL": ("", ""),
            "Nebius": ("greenhouse", "nebius"),
        }


def test_a_board_on_a_provider_we_can_read_beats_one_we_cannot_then_the_one_with_more_roles(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        add_company(db, user_id, "Extend")
        add_company(db, user_id, "Plaid")
        db.commit()
        run_import(
            db,
            [board("ashby", "extend", "Extend", 500), board("greenhouse", "extend", "Extend", 5), board("ashby", "plaid", "Plaid", 10), board("lever", "plaid", "Plaid", 90)],
        )
        directory.match_companies(db, user_id)
        assert matched(db) == {"Extend": ("greenhouse", "extend"), "Plaid": ("lever", "plaid")}


def test_a_company_is_also_matched_through_the_workday_tenant(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        add_company(db, user_id, "Danaher")
        db.commit()
        run_import(db, GOOD)
        directory.match_companies(db, user_id)
        assert matched(db) == {"Danaher": ("workday", "wd1/danaher/DanaherJobs")}


def test_nothing_is_matched_while_the_directory_is_empty_and_each_company_is_matched_once(session_factory):
    with session_factory() as db:
        user_id = make_user(db)
        add_company(db, user_id, "Nebius")
        db.commit()
        assert directory.match_companies(db, user_id) == 0
        assert matched(db) == {"Nebius": (None, None)}
        run_import(db, [board("greenhouse", "nebius", "Nebius"), board("lever", "other", "Other")])
        assert directory.match_companies(db, user_id) == 1
        assert directory.match_companies(db, user_id) == 0


def test_each_user_gets_their_own_matches(session_factory):
    with session_factory() as db:
        first, second = make_user(db, "one@example.com"), make_user(db, "two@example.com")
        add_company(db, first, "Nebius")
        add_company(db, second, "Nebius")
        db.commit()
        run_import(db, [board("greenhouse", "nebius", "Nebius"), board("lever", "other", "Other")])
        directory.match_companies(db, first)
        companies = db.scalars(select(Company).order_by(Company.user_id)).all()
        assert (companies[0].board_provider, companies[1].board_provider) == ("greenhouse", None)
