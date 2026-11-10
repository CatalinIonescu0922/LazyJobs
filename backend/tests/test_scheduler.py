from datetime import timedelta
from unittest.mock import patch

import pytest

from app.models import JobSource, Profile, User, utcnow
from app.routers import jobs


def add_user(factory, email: str, country: str = "RO") -> int:
    with factory() as db:
        user = User(email=email)
        db.add(user)
        db.flush()
        db.add(Profile(user_id=user.id, country=country))
        db.commit()
        return user.id


def add_source(factory, user_id: int, domain: str, status: str = "active", refreshed_hours_ago: float | None = None) -> None:
    last = utcnow() - timedelta(hours=refreshed_hours_ago) if refreshed_hours_ago is not None else None
    with factory() as db:
        db.add(JobSource(user_id=user_id, domain=domain, kind="board", status=status, last_refreshed_at=last))
        db.commit()


def run_due(factory, hours: float = 12) -> list[tuple[int, list[str]]]:
    calls = []
    with patch.object(jobs, "SessionLocal", factory), patch.object(
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
    with patch.object(jobs, "SessionLocal", session_factory), patch.object(jobs, "_run_refresh", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            jobs.refresh_due_sources(timedelta(hours=12))
    assert jobs._refresh_lock.acquire(blocking=False)
    jobs._refresh_lock.release()
