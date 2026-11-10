import math
import re
import time
from collections import Counter
from datetime import timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..llm import propose_domains
from ..logging import logger
from ..models import Company, Job, JobSource, utcnow
from ..textnorm import normalise
from .ats import _domain_label, find_feed_for_company, source_domain
from .fetch import FetchError, SafeFetcher

MAX_DOMAIN_LOOKUPS = 40
MIN_DOMAIN_BATCH = 10
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


def probes_per_tick(total: int, tick: timedelta) -> int:
    # Spread the companies evenly over DISCOVERY_COVER_DAYS: with 399 companies, 5 days and a tick every
    # 30 minutes that is ceil(399 / 240) = 2 companies a tick, about 3.5 requests, and never a burst.
    ticks = timedelta(days=settings.discovery_cover_days) / tick
    return max(1, math.ceil(total / ticks))


def discover_feeds(db: Session, user_id: int, country: str, tick: timedelta) -> list[JobSource]:
    # The best-known companies go first. One that has no feed is asked again only after a month.
    total = db.scalar(select(func.count()).select_from(Company).where(Company.user_id == user_id)) or 0
    due = db.scalars(
        select(Company)
        .where(
            Company.user_id == user_id,
            or_(Company.status == "unchecked", and_(Company.status == "none", Company.checked_at < utcnow() - RECHECK_AFTER)),
        )
        .order_by(Company.postings.desc(), Company.id)
        .limit(probes_per_tick(total, tick))
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


def enrich_domains(db: Session, user_id: int, country: str) -> int:
    # Only for the logo on the Companies screen. The model proposes a domain and the code keeps it only
    # when it plausibly belongs to the company, so a made-up one is stored as unknown. It waits for a
    # worthwhile batch, so a handful of new names does not cost a model call on every tick.
    pending = db.scalar(select(func.count()).select_from(Company).where(Company.user_id == user_id, Company.domain.is_(None))) or 0
    if pending < MIN_DOMAIN_BATCH:
        return 0
    todo = db.scalars(
        select(Company).where(Company.user_id == user_id, Company.domain.is_(None)).order_by(Company.postings.desc(), Company.id).limit(MAX_DOMAIN_LOOKUPS)
    ).all()
    if not todo:
        return 0
    answers = {normalise(str(answer.get("company", ""))): str(answer.get("domain", "")) for answer in propose_domains([company.name for company in todo], country)}
    found = 0
    for company in todo:
        domain = _clean_domain(answers.get(company.key, ""))
        company.domain = domain if domain and domain_fits(company.name, domain) else ""
        found += bool(company.domain)
    db.commit()
    logger.info("Company domains looked up: user_id=%s asked=%s kept=%s", user_id, len(todo), found)
    return found


def domain_fits(name: str, domain: str) -> bool:
    words = [word for word in normalise(name).split() if word not in {"romania", "romanian"}] or normalise(name).split()
    squashed = "".join(words)
    label = re.sub(r"[^a-z0-9]", "", _domain_label(domain))
    first = words[0] if words else ""
    # A two-letter brand (EY, NN) is accepted only when it is exactly the first word of the name.
    return (len(label) >= 3 or label == first) and (label in squashed or squashed in label or (len(first) >= 3 and label.startswith(first)))


def _clean_domain(raw: str) -> str:
    host = re.sub(r"^https?://", "", raw.strip().lower()).split("/")[0].removeprefix("www.")
    return host if re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,}", host) else ""
