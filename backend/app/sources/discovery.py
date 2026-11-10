import time
from collections import Counter
from datetime import timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..logging import logger
from ..models import Company, Job, JobSource, utcnow
from ..textnorm import normalise
from .ats import find_feed_for_company, source_domain
from .fetch import FetchError, SafeFetcher

MAX_PROBES = 20
RECHECK_AFTER = timedelta(days=30)
PAUSE_SECONDS = 1
GREENHOUSE_API = "boards-api.greenhouse.io"
NOT_A_NAME = {"confidential", "confidentiala", "anonim", "anonymous"}


def seed_companies(db: Session, user_id: int, country: str) -> int:
    # Every company with a stored posting open to the country is known to hire there. Employer sources are
    # left out because their feed is already being read.
    domains = db.scalars(
        select(JobSource.domain).where(JobSource.user_id == user_id, JobSource.status == "active", JobSource.kind.in_(["board", "aggregator"]))
    ).all()
    names: dict[str, Counter] = {}
    for company, eligible in db.execute(select(Job.company, Job.eligible_countries).where(Job.source.in_(domains), Job.company != "")):
        key = normalise(company)
        if len(key) < 4 or key in NOT_A_NAME or (eligible and country.upper() not in eligible):
            continue
        names.setdefault(key, Counter())[company.strip()] += 1
    known = {company.key: company for company in db.scalars(select(Company).where(Company.user_id == user_id))}
    created = 0
    for key, spellings in names.items():
        company = known.get(key)
        if company is None:
            db.add(Company(user_id=user_id, key=key, name=spellings.most_common(1)[0][0], postings=sum(spellings.values())))
            created += 1
        else:
            company.postings = sum(spellings.values())
    db.commit()
    return created


def discover_feeds(db: Session, user_id: int, country: str) -> list[JobSource]:
    # The best-known companies go first. One that has no feed is asked again only after a month.
    due = db.scalars(
        select(Company)
        .where(
            Company.user_id == user_id,
            or_(Company.status == "unchecked", and_(Company.status == "none", Company.checked_at < utcnow() - RECHECK_AFTER)),
        )
        .order_by(Company.postings.desc(), Company.id)
        .limit(MAX_PROBES)
    ).all()
    fetcher = SafeFetcher(GREENHOUSE_API)
    created: list[JobSource] = []
    for position, company in enumerate(due):
        if position:
            time.sleep(PAUSE_SECONDS)
        try:
            feed = find_feed_for_company(company.name, country, fetcher)
        except FetchError as exc:
            # A block or a failed connection says nothing about the company, so it stays unchecked.
            logger.warning("Company discovery stopped: user_id=%s reason=%s", user_id, exc)
            break
        company.checked_at = utcnow()
        if feed is None:
            company.status = "none"
            continue
        company.status, company.ats_provider, company.ats_slug = "feed", feed.provider, feed.slug
        domain = source_domain(feed)
        if db.scalar(select(JobSource.id).where(JobSource.user_id == user_id, JobSource.kind == "employer", JobSource.domain == domain)) is None:
            source = JobSource(
                user_id=user_id,
                domain=domain,
                source_url=f"https://boards.greenhouse.io/{feed.slug}",
                kind="employer",
                ats_provider=feed.provider,
                ats_slug=feed.slug,
            )
            db.add(source)
            created.append(source)
    db.commit()
    logger.info("Company discovery finished: user_id=%s probed=%s new_sources=%s", user_id, len(due), [source.domain for source in created])
    return created
