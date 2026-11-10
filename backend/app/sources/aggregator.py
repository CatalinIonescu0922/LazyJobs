import time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..logging import logger
from ..models import Job, JobSource, utcnow
from . import himalayas
from .crawl import _upsert_job
from .fetch import FetchError, SafeFetcher

AGGREGATORS = {himalayas.DOMAIN}
MAX_QUERIES = 2
MAX_CLOSED_CHECKS = 10
MIN_GONE_TO_DOUBT = 3
PAUSE_SECONDS = 2


def refresh_aggregator_source(db: Session, source: JobSource, country: str, titles: list[str]) -> dict[str, int | str]:
    queries = [title.strip() for title in titles if title.strip()][:MAX_QUERIES]
    if not queries or not country:
        return _failed(db, source, "set a job title and a country in your profile")
    started = utcnow()
    try:
        found = _search(db, source, country, queries)
    except FetchError as exc:
        return _failed(db, source, str(exc))
    for posting in found:
        try:
            with db.begin_nested():
                _upsert_job(db, posting)
                db.flush()
        except IntegrityError:
            logger.warning("Duplicate job skipped: source=%s external_id=%s", source.domain, posting.external_id)
    removed = _drop_closed(db, source, started)
    source.status = "active"
    source.reason = ""
    source.extraction = "api"
    source.last_refreshed_at = utcnow()
    source.posting_count = db.query(Job).filter(Job.source == source.domain).count()
    db.commit()
    logger.info("Aggregator source refreshed: source=%s queries=%s added=%s closed_removed=%s stored=%s", source.domain, queries, len(found), removed, source.posting_count)
    return {"source_id": source.id, "status": source.status, "added": len(found), "updated": 0, "failed": 0, "reason": ""}


def _search(db: Session, source: JobSource, country: str, queries: list[str]) -> list:
    known = set(db.scalars(select(Job.external_id).where(Job.source == source.domain)))
    found = []
    for position, query in enumerate(queries):
        if position:
            # The same keyless allowance is shared by every caller, so searches are never back to back.
            time.sleep(PAUSE_SECONDS)
        found += himalayas.search_jobs(query, country, known | {posting.external_id for posting in found})
    return found


def _drop_closed(db: Session, source: JobSource, started) -> int:
    # The terms require closed jobs to be removed. A job can close before its expiry date, so a few
    # of the stored ones are asked about each run, the least recently confirmed first; fetched_at is
    # moved forward when the API still lists the job. Jobs stored by this run are skipped.
    stored = db.scalars(select(Job).where(Job.source == source.domain, Job.fetched_at < started).order_by(Job.fetched_at).limit(MAX_CLOSED_CHECKS)).all()
    fetcher = SafeFetcher(himalayas.DOMAIN)
    open_jobs, gone = [], []
    for job in stored:
        time.sleep(PAUSE_SECONDS)
        try:
            closed = himalayas.is_closed(job.external_id, fetcher)
        except FetchError as exc:
            logger.warning("Closed-job check stopped: source=%s reason=%s", source.domain, exc)
            break
        (gone if closed else open_jobs).append(job)
    # Every checked job gone at once looks like a change in the API and not that many closures.
    if len(gone) >= MIN_GONE_TO_DOUBT and not open_jobs:
        logger.warning("Closed-job check ignored: source=%s every one of %s checked jobs reported gone", source.domain, len(gone))
        return 0
    for job in gone:
        db.delete(job)
    for job in open_jobs:
        job.fetched_at = utcnow()
    # Sessions here do not autoflush, and the caller counts the stored jobs next.
    db.flush()
    return len(gone)


def _failed(db: Session, source: JobSource, reason: str) -> dict[str, int | str]:
    # A source that has worked stays active, so one 429 does not take it out of the schedule for good.
    if source.posting_count:
        source.reason = f"last refresh failed: {reason}"
    else:
        source.status = "failed"
        source.reason = reason
    db.commit()
    return {"source_id": source.id, "status": source.status, "added": 0, "updated": 0, "failed": 1, "reason": source.reason}
