from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from sqlalchemy import select

from app.models import Job, JobSource, User, utcnow
from app.routers import jobs as jobs_router
from app.routers.sources import add_source
from app.schemas import SourceCreate
from app.sources import aggregator
from app.sources.fetch import FetchError
from app.sources.posting import Posting

DOMAIN = aggregator.himalayas.DOMAIN


def posting(name: str) -> Posting:
    url = f"https://himalayas.app/companies/acme/jobs/{name}"
    return Posting(
        source=DOMAIN, external_id=url, url=url, apply_url=f"{url}?utm_source=api", title=f"Role {name}", company="Acme",
        locations=["Remote"], remote=True, work_mode="remote", eligible_countries=[], employment_type="Full Time",
        description="Run the pipelines.", salary_min=None, salary_max=None, salary_currency="", posted_at=None, expires_at=None,
    )


def make_source(db, posting_count: int = 0, status: str = "candidate") -> JobSource:
    user = User(email="a@example.com")
    db.add(user)
    db.flush()
    source = JobSource(user_id=user.id, domain=DOMAIN, kind="aggregator", status=status, posting_count=posting_count)
    db.add(source)
    db.commit()
    return source


def store(db, name: str, fetched_hours_ago: float) -> Job:
    item = posting(name)
    job = Job(
        source=DOMAIN, external_id=item.external_id, url=item.url, title=item.title, company="Acme", locations=["Remote"],
        fetched_at=utcnow() - timedelta(hours=fetched_hours_ago),
    )
    db.add(job)
    db.commit()
    return job


def refresh(db, source, titles, search=None, closed=None, country="RO"):
    search = search or MagicMock(return_value=[])
    closed = closed or MagicMock(return_value=False)
    with patch.object(aggregator.himalayas, "search_jobs", search), patch.object(aggregator.himalayas, "is_closed", closed), patch.object(
        aggregator.time, "sleep"
    ) as sleep:
        result = aggregator.refresh_aggregator_source(db, source, country, titles)
    return result, search, closed, sleep


def test_new_postings_are_stored_and_the_source_becomes_active(session_factory):
    with session_factory() as db:
        source = make_source(db)
        search = MagicMock(side_effect=[[posting("a"), posting("b")], [posting("c")]])
        result, search, _, sleep = refresh(db, source, ["DevOps Engineering", "Team Leader", "Ignored Third"], search=search)
        assert result["added"] == 3
        assert (source.status, source.extraction, source.reason, source.posting_count) == ("active", "api", "", 3)
        assert search.call_count == aggregator.MAX_QUERIES
        # The second search already knows what the first one found.
        assert {item.external_id for item in [posting("a"), posting("b")]} <= search.call_args_list[1].args[2]
        assert sleep.call_count >= 1
        assert db.scalar(select(Job.id).where(Job.external_id == posting("c").external_id)) is not None


def test_a_profile_without_titles_or_country_fails_in_plain_words(session_factory):
    with session_factory() as db:
        source = make_source(db)
        result, search, _, _ = refresh(db, source, ["  "])
        assert result["status"] == "failed"
        assert result["reason"] == "set a job title and a country in your profile"
        search.assert_not_called()
        second, _, _, _ = refresh(db, source, ["DevOps"], country="")
        assert second["reason"] == "set a job title and a country in your profile"


def test_a_first_failure_marks_the_source_failed(session_factory):
    with session_factory() as db:
        source = make_source(db)
        result, _, _, _ = refresh(db, source, ["DevOps"], search=MagicMock(side_effect=FetchError("blocked (429)")))
        assert (result["status"], source.status, source.reason) == ("failed", "failed", "blocked (429)")


def test_a_source_that_has_worked_stays_active_after_one_failure(session_factory):
    with session_factory() as db:
        source = make_source(db, posting_count=40, status="active")
        result, _, _, _ = refresh(db, source, ["DevOps"], search=MagicMock(side_effect=FetchError("blocked (429)")))
        assert (result["status"], source.status) == ("active", "active")
        assert source.reason == "last refresh failed: blocked (429)"
        success, _, _, _ = refresh(db, source, ["DevOps"])
        assert (success["status"], source.reason) == ("active", "")


def test_closed_jobs_are_removed_and_confirmed_ones_move_forward(session_factory):
    with session_factory() as db:
        source = make_source(db, posting_count=3, status="active")
        oldest, middle, newest = store(db, "oldest", 30), store(db, "middle", 20), store(db, "newest", 10)
        before = middle.fetched_at
        def answer(external_id, fetcher):
            if external_id.endswith("/oldest"):
                return True
            if external_id.endswith("/middle"):
                return False
            raise FetchError("blocked (429)")

        closed = MagicMock(side_effect=answer)
        refresh(db, source, ["DevOps"], closed=closed)
        names = {job.external_id.rsplit("/", 1)[-1] for job in db.scalars(select(Job)).all()}
        assert "oldest" not in names
        assert source.posting_count == 2
        assert middle.fetched_at > before
        # The 429 on the third job stopped the checks, so it was left as it was.
        assert newest.fetched_at < utcnow() - timedelta(hours=9)
        assert closed.call_count == 3


def test_a_run_where_every_checked_job_is_gone_deletes_nothing(session_factory):
    with session_factory() as db:
        source = make_source(db, posting_count=3, status="active")
        for name in ("a", "b", "c"):
            store(db, name, 30)
        refresh(db, source, ["DevOps"], closed=MagicMock(return_value=True))
        assert db.query(Job).count() == 3


def test_several_gone_jobs_are_removed_when_others_are_still_open(session_factory):
    with session_factory() as db:
        source = make_source(db, posting_count=4, status="active")
        for name, hours in (("a", 40), ("b", 30), ("c", 20), ("open", 10)):
            store(db, name, hours)
        closed = MagicMock(side_effect=lambda external_id, fetcher: not external_id.endswith("/open"))
        refresh(db, source, ["DevOps"], closed=closed)
        assert [job.external_id.rsplit("/", 1)[-1] for job in db.scalars(select(Job)).all()] == ["open"]


def test_jobs_stored_by_this_run_are_not_asked_about(session_factory):
    with session_factory() as db:
        source = make_source(db)
        asked = []
        closed = MagicMock(side_effect=lambda external_id, fetcher: asked.append(external_id) or False)
        refresh(db, source, ["DevOps"], search=MagicMock(return_value=[posting("fresh")]), closed=closed)
        assert asked == []


def test_at_most_ten_stored_jobs_are_checked_per_run(session_factory):
    with session_factory() as db:
        source = make_source(db, posting_count=15, status="active")
        for number in range(15):
            store(db, f"job{number}", 100 - number)
        _, _, closed, _ = refresh(db, source, ["DevOps"])
        assert closed.call_count == aggregator.MAX_CLOSED_CHECKS


def test_refresh_any_sends_each_kind_to_its_own_reader():
    source = MagicMock(spec=JobSource)
    with patch.object(jobs_router, "refresh_aggregator_source", return_value={"k": "aggregator"}) as agg, patch.object(
        jobs_router, "refresh_career_source", return_value={"k": "career"}
    ) as career, patch.object(jobs_router, "refresh_source", return_value={"k": "board"}) as board:
        source.kind = "aggregator"
        assert jobs_router.refresh_any(MagicMock(), source, "RO", "Timisoara", ["x"], ["DevOps"]) == {"k": "aggregator"}
        agg.assert_called_once()
        assert agg.call_args.args[2:] == ("RO", ["DevOps"])
        for kind in ("employer", "career"):
            source.kind = kind
            assert jobs_router.refresh_any(MagicMock(), source, "RO", "Timisoara", ["x"], ["DevOps"]) == {"k": "career"}
        source.kind = "board"
        assert jobs_router.refresh_any(MagicMock(), source, "RO", "Timisoara", ["x"], ["DevOps"]) == {"k": "board"}
        assert career.call_count == 2 and board.call_count == 1


def test_adding_himalayas_creates_an_aggregator_source(session_factory):
    with session_factory() as db:
        user = User(email="a@example.com")
        db.add(user)
        db.commit()
        response = add_source(SourceCreate(url="https://himalayas.app"), user, db)
        assert (response.kind, response.domain) == ("aggregator", DOMAIN)
        assert db.scalar(select(JobSource.kind).where(JobSource.domain == DOMAIN)) == "aggregator"
