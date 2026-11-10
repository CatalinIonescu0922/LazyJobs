from unittest.mock import MagicMock, patch

from app.models import JobSource
from app.sources import career
from app.sources.fetch import FetchError


def feed_source(status: str = "active", posting_count: int = 18, provider: str = "greenhouse") -> JobSource:
    return JobSource(id=1, domain="emag.greenhouse.io", kind="employer", status=status, ats_provider=provider, ats_slug="emag", posting_count=posting_count, reason="")


def refresh_failing(source: JobSource, error: str = "blocked (429)") -> dict:
    db = MagicMock()
    db.scalars.return_value = []
    with patch.object(career, "read_feed", side_effect=FetchError(error)):
        return career.refresh_career_source(db, source, "RO", "Timisoara")


def test_a_working_feed_stays_active_after_one_failure_and_waits_for_the_next_interval():
    source = feed_source()
    result = refresh_failing(source)
    assert (source.status, result["status"]) == ("active", "active")
    assert source.reason == "last refresh failed: blocked (429)"
    assert source.last_refreshed_at is not None


def test_a_feed_that_has_not_been_read_yet_stays_a_candidate_so_the_schedule_retries_it():
    source = feed_source(status="candidate", posting_count=0)
    refresh_failing(source, "source request failed (ConnectError)")
    assert source.status == "candidate"
    assert source.reason == "last refresh failed: source request failed (ConnectError)"
    assert source.last_refreshed_at is not None


def test_a_career_page_without_a_feed_is_still_marked_failed():
    source = JobSource(id=2, domain="company.example", kind="employer", status="candidate", ats_provider="", posting_count=0, reason="")
    fetcher = MagicMock()
    fetcher.get.side_effect = FetchError("source returned 404")
    with patch.object(career, "SafeFetcher", return_value=fetcher), patch.object(career, "find_feed", return_value=None):
        career.refresh_career_source(MagicMock(), source, "RO", "Timisoara")
    assert (source.status, source.reason) == ("failed", "source returned 404")
    assert source.last_refreshed_at is None
