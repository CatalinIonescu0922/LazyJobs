from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.models import Job, JobSource, Profile, User, utcnow
from app.routers import jobs
from app.sources import discovery
from app.sources.ats import Feed


def add_user(factory, email: str, country: str = "RO") -> int:
    with factory() as db:
        user = User(email=email)
        db.add(user)
        db.flush()
        db.add(Profile(user_id=user.id, country=country))
        db.commit()
        return user.id


def add_source(factory, user_id: int, domain: str, status: str = "active", refreshed_hours_ago: float | None = None, ats_provider: str = "") -> None:
    last = utcnow() - timedelta(hours=refreshed_hours_ago) if refreshed_hours_ago is not None else None
    with factory() as db:
        db.add(JobSource(user_id=user_id, domain=domain, kind="board", status=status, last_refreshed_at=last, ats_provider=ats_provider))
        db.commit()


def run_due(factory, hours: float = 12) -> list[tuple[int, list[str]]]:
    calls = []
    with patch.object(jobs, "SessionLocal", factory), patch.object(jobs, "_discover_companies", return_value=[]), patch.object(
        jobs, "_run_refresh", side_effect=lambda user_id, profile, sources: calls.append((user_id, sorted(s.domain for s in sources)))
    ):
        jobs.refresh_due_sources(timedelta(hours=hours))
    return calls


def test_only_active_sources_past_the_interval_are_refreshed(session_factory):
    user_id = add_user(session_factory, "a@example.com")
    add_source(session_factory, user_id, "never-refreshed.example")
    add_source(session_factory, user_id, "stale.example", refreshed_hours_ago=13)
    add_source(session_factory, user_id, "fresh.example", refreshed_hours_ago=1)
    add_source(session_factory, user_id, "failed.example", status="failed", refreshed_hours_ago=48)
    add_source(session_factory, user_id, "candidate.example", status="candidate")
    assert run_due(session_factory) == [(user_id, ["never-refreshed.example", "stale.example"])]


def test_nothing_runs_when_every_source_is_fresh(session_factory):
    user_id = add_user(session_factory, "a@example.com")
    add_source(session_factory, user_id, "fresh.example", refreshed_hours_ago=2)
    assert run_due(session_factory) == []


def test_a_user_without_a_country_is_skipped(session_factory):
    without = add_user(session_factory, "no-country@example.com", country="")
    with_country = add_user(session_factory, "ok@example.com")
    add_source(session_factory, without, "a.example")
    add_source(session_factory, with_country, "b.example")
    assert run_due(session_factory) == [(with_country, ["b.example"])]


def test_each_user_is_refreshed_with_their_own_sources(session_factory):
    first = add_user(session_factory, "one@example.com")
    second = add_user(session_factory, "two@example.com")
    add_source(session_factory, first, "one.example")
    add_source(session_factory, second, "two.example")
    assert run_due(session_factory) == [(first, ["one.example"]), (second, ["two.example"])]


def test_the_scheduled_refresh_waits_when_a_manual_refresh_is_running(session_factory):
    user_id = add_user(session_factory, "a@example.com")
    add_source(session_factory, user_id, "due.example")
    with jobs._refresh_lock:
        assert run_due(session_factory) == []
    assert run_due(session_factory) == [(user_id, ["due.example"])]


def test_the_lock_is_released_even_when_the_refresh_fails(session_factory):
    user_id = add_user(session_factory, "a@example.com")
    add_source(session_factory, user_id, "due.example")
    with patch.object(jobs, "SessionLocal", session_factory), patch.object(jobs, "_discover_companies", return_value=[]), patch.object(
        jobs, "_run_refresh", side_effect=RuntimeError("boom")
    ):
        with pytest.raises(RuntimeError):
            jobs.refresh_due_sources(timedelta(hours=12))
    assert jobs._refresh_lock.acquire(blocking=False)
    jobs._refresh_lock.release()


def test_discovery_runs_on_a_refreshing_tick_and_its_new_sources_are_refreshed_too(session_factory):
    user_id = add_user(session_factory, "a@example.com")
    add_source(session_factory, user_id, "due.example")
    calls = []
    new = JobSource(domain="veeamsoftware.greenhouse.io", kind="employer")
    with patch.object(jobs, "SessionLocal", session_factory), patch.object(jobs, "_discover_companies", return_value=[new]) as discover, patch.object(
        jobs, "_run_refresh", side_effect=lambda uid, profile, sources: calls.append(sorted(s.domain for s in sources))
    ):
        jobs.refresh_due_sources(timedelta(hours=12))
    discover.assert_called_once()
    assert calls == [["due.example", "veeamsoftware.greenhouse.io"]]


def test_discovery_still_trickles_on_a_tick_where_nothing_is_due(session_factory):
    user_id = add_user(session_factory, "a@example.com")
    add_source(session_factory, user_id, "fresh.example", refreshed_hours_ago=1)
    with patch.object(jobs, "SessionLocal", session_factory), patch.object(jobs, "_discover_companies", return_value=[]) as discover, patch.object(
        jobs, "_run_refresh"
    ) as run:
        jobs.refresh_due_sources(timedelta(hours=12))
    discover.assert_called_once()
    run.assert_not_called()


def test_a_discovery_failure_does_not_stop_the_refresh(session_factory):
    user_id = add_user(session_factory, "a@example.com")
    add_source(session_factory, user_id, "due.example")
    calls = []
    with patch.object(jobs, "SessionLocal", session_factory), patch.object(jobs, "seed_companies", side_effect=RuntimeError("boom")), patch.object(
        jobs, "_run_refresh", side_effect=lambda uid, profile, sources: calls.append(sorted(s.domain for s in sources))
    ):
        jobs.refresh_due_sources(timedelta(hours=12))
    assert calls == [["due.example"]]


def test_a_candidate_with_a_known_feed_is_scheduled_but_one_without_is_not(session_factory):
    user_id = add_user(session_factory, "a@example.com")
    add_source(session_factory, user_id, "feed-candidate.example", status="candidate", ats_provider="greenhouse")
    add_source(session_factory, user_id, "plain-candidate.example", status="candidate")
    add_source(session_factory, user_id, "disabled.example", status="disabled", ats_provider="greenhouse")
    add_source(session_factory, user_id, "failed.example", status="failed", ats_provider="greenhouse")
    assert run_due(session_factory) == [(user_id, ["feed-candidate.example"])]


def test_a_discovered_company_is_refreshed_at_once_and_then_every_interval(session_factory):
    user_id = add_user(session_factory, "a@example.com")
    with session_factory() as db:
        db.add(JobSource(user_id=user_id, domain="ejobs.ro", kind="board", status="active"))
        db.add(Job(source="ejobs.ro", external_id="1", url="", title="Role", company="eMAG"))
        db.commit()
    runs = []
    record = lambda uid, profile, sources: runs.append(sorted(source.domain for source in sources))  # noqa: E731
    with patch.object(jobs, "SessionLocal", session_factory), patch.object(jobs, "_run_refresh", side_effect=record), patch.object(
        jobs, "enrich_domains"
    ), patch.object(discovery, "find_feed_for_company", return_value=Feed("greenhouse", "emag")) as find, patch.object(
        discovery, "SafeFetcher"
    ), patch.object(discovery.time, "sleep"):
        jobs.refresh_due_sources(timedelta(hours=12))
        with session_factory() as db:
            # What the run did: the new feed was read once, and a whole interval has now passed for both sources.
            for source in db.scalars(select(JobSource)).all():
                source.status, source.last_refreshed_at = "active", utcnow() - timedelta(hours=13)
            db.commit()
        jobs.refresh_due_sources(timedelta(hours=12))
    assert runs == [["ejobs.ro", "emag.greenhouse.io"], ["ejobs.ro", "emag.greenhouse.io"]]
    # The company was asked about once; its answer is stored and not looked up again.
    assert find.call_count == 1


def test_a_failed_domain_lookup_does_not_keep_feeds_from_being_found(session_factory):
    user_id = add_user(session_factory, "a@example.com")
    with session_factory() as db:
        feed = JobSource(user_id=user_id, domain="found.greenhouse.io", kind="employer")
        with patch.object(jobs, "seed_companies"), patch.object(
            jobs, "enrich_domains", side_effect=RuntimeError("vertex down")
        ), patch.object(
            jobs, "discover_feeds", return_value=[feed]
        ) as discover:
            assert jobs._discover_companies(db, user_id, "RO", timedelta(minutes=30)) == [feed]
    discover.assert_called_once()
    assert discover.call_args.args[3] == timedelta(minutes=30)


@pytest.mark.parametrize(
    "sources, expected",
    [(0, 1), (1, 1), (9, 1), (24, 1), (25, 2), (60, 3), (300, 13)],
)
def test_the_refresh_budget_spreads_sources_over_the_interval(sources, expected):
    assert jobs.refresh_budget(sources, timedelta(hours=12), timedelta(minutes=30)) == expected


def test_one_tick_refreshes_the_most_overdue_sources_first_and_only_its_share(session_factory):
    user_id = add_user(session_factory, "a@example.com")
    add_source(session_factory, user_id, "never.example")
    add_source(session_factory, user_id, "oldest.example", refreshed_hours_ago=40)
    add_source(session_factory, user_id, "older.example", refreshed_hours_ago=30)
    add_source(session_factory, user_id, "recent.example", refreshed_hours_ago=20)
    batches = []
    record = lambda uid, profile, sources: batches.append([source.domain for source in sources])  # noqa: E731
    with patch.object(jobs, "SessionLocal", session_factory), patch.object(jobs, "_discover_companies", return_value=[]), patch.object(
        jobs, "_run_refresh", side_effect=record
    ):
        for _ in range(4):
            jobs.refresh_due_sources(timedelta(hours=12), timedelta(minutes=30))
            with session_factory() as db:
                for source in db.scalars(select(JobSource)).all():
                    if source.domain in {name for batch in batches for name in batch}:
                        source.last_refreshed_at = utcnow()
                db.commit()
    # Four sources over 24 ticks is one a tick: never refreshed first, then oldest to newest, one by one.
    assert batches == [["never.example"], ["oldest.example"], ["older.example"], ["recent.example"]]


def test_a_larger_fleet_is_refreshed_in_slices(session_factory):
    user_id = add_user(session_factory, "a@example.com")
    for number in range(60):
        add_source(session_factory, user_id, f"source-{number:02d}.example")
    batches = []
    with patch.object(jobs, "SessionLocal", session_factory), patch.object(jobs, "_discover_companies", return_value=[]), patch.object(
        jobs, "_run_refresh", side_effect=lambda uid, profile, sources: batches.append(len(sources))
    ):
        jobs.refresh_due_sources(timedelta(hours=12), timedelta(minutes=30))
    assert batches == [3]
