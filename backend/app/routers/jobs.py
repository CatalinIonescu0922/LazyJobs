import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from datetime import datetime, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal, get_db
from ..llm import propose_employers, propose_job_boards
from ..logging import logger, timed
from ..models import Job, JobSource, Profile, User, utcnow
from ..schemas import JobResponse, JobSearchRequest, JobSearchResponse
from ..session import current_user
from ..textnorm import fingerprint
from ..sources.aggregator import refresh_aggregator_source
from ..sources.crawl import refresh_source
from ..sources.career import refresh_career_source

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
_refresh_lock = Lock()


@router.get("", response_model=JobSearchResponse)
def list_jobs(
    query: str = "",
    location: str = "",
    mode: str = "hybrid_onsite",
    days: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> JobSearchResponse:
    profile = _profile(db, user)
    request = JobSearchRequest(query=query, location=location, mode=mode, days=days)
    result = _search(db, user, profile, request)
    logger.info("Job list completed: user_id=%s filters=%s result_count=%s", user.id, _filter_summary(request), len(result.jobs))
    return result


@router.post("/search", response_model=JobSearchResponse)
def search_jobs(
    payload: JobSearchRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> JobSearchResponse:
    profile = _profile(db, user)
    refreshed = False
    if payload.refresh:
        _refresh_user_sources(db, user, profile)
        refreshed = True
    result = _search(db, user, profile, payload)
    logger.info("Job search completed: user_id=%s refreshed=%s filters=%s result_count=%s", user.id, refreshed, _filter_summary(payload), len(result.jobs))
    return result.model_copy(update={"refreshed": refreshed})


def _profile(db: Session, user: User) -> Profile:
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile is None:
        raise HTTPException(status_code=400, detail="Upload a CV before searching for jobs")
    return profile


def _refresh_user_sources(db: Session, user: User, profile: Profile) -> None:
    with _refresh_lock:
        _refresh_user_sources_locked(db, user, profile)


@timed
def _refresh_user_sources_locked(db: Session, user: User, profile: Profile) -> None:
    sources = db.scalars(
        select(JobSource).where(JobSource.user_id == user.id, JobSource.status.in_(["active", "candidate"]))
    ).all()
    logger.info("Job refresh started: user_id=%s source_count=%s profile_city=%s profile_country=%s", user.id, len(sources), profile.city, profile.country)
    if not sources:
        if not profile.country:
            raise HTTPException(status_code=400, detail="Set your country before searching for jobs")
        for proposal in propose_job_boards(profile.country):
            domain = _domain(str(proposal.get("domain", "")))
            if not domain:
                continue
            existing = db.scalar(select(JobSource).where(JobSource.user_id == user.id, JobSource.domain == domain, JobSource.kind == "board"))
            if existing is None:
                existing = JobSource(user_id=user.id, domain=domain, kind="board")
                db.add(existing)
                db.flush()
            sources.append(existing)
        db.commit()
        logger.info("Job sources discovered: user_id=%s source_count=%s", user.id, len(sources))
    if profile.city and not any(source.kind == "employer" for source in sources):
        for proposal in propose_employers(profile.country, profile.city, profile.titles, profile.skills):
            source_url = _source_url(str(proposal.get("website", "")))
            domain = _domain(source_url)
            if not domain:
                continue
            existing = db.scalar(select(JobSource).where(JobSource.user_id == user.id, JobSource.domain == domain, JobSource.kind == "employer"))
            if existing is None:
                existing = JobSource(user_id=user.id, domain=domain, source_url=source_url, kind="employer")
                db.add(existing)
                db.flush()
            sources.append(existing)
        db.commit()
        logger.info("Employer sources discovered: user_id=%s source_count=%s", user.id, sum(source.kind == "employer" for source in sources))
    refresh_candidates = not any(source.status == "active" for source in sources)
    sources_to_refresh = [
        source for source in sources
        if source.status == "active" or refresh_candidates
    ]
    logger.info("Job refresh plan: user_id=%s refresh_count=%s skipped_failed=%s", user.id, len(sources_to_refresh), len(sources) - len(sources_to_refresh))
    terms = _profile_terms(profile)
    with ThreadPoolExecutor(max_workers=settings.crawl_workers, thread_name_prefix="source-refresh") as executor:
        futures = {
            executor.submit(_refresh_one_source, source.id, profile.country, profile.city, terms): source.domain
            for source in sources_to_refresh
        }
        for future in as_completed(futures):
            domain = futures[future]
            try:
                result = future.result()
                logger.info("Job source refreshed: user_id=%s source=%s status=%s added=%s failed=%s posting_count=%s", user.id, domain, result["status"], result["added"], result["failed"], result["posting_count"])
            except Exception:
                logger.exception("Automatic job refresh failed for source=%s", domain)
    logger.info("Job refresh completed: user_id=%s active_sources=%s", user.id, sum(source.status == "active" for source in sources))


def _refresh_one_source(source_id: int, country: str, city: str, terms: list[str]) -> dict[str, int | str]:
    db = SessionLocal()
    try:
        source = db.get(JobSource, source_id)
        if source is None:
            raise RuntimeError(f"source {source_id} disappeared")
        result = refresh_career_source(db, source, country, city) if source.kind in {"career", "employer"} else refresh_source(db, source, terms)
        return {**result, "posting_count": source.posting_count}
    except Exception as exc:
        db.rollback()
        source = db.get(JobSource, source_id)
        if source is not None:
            source.status = "failed"
            source.reason = f"unexpected error: {type(exc).__name__}: {str(exc)[:300]}"
            db.commit()
        raise
    finally:
        db.close()


@timed
def _search(db: Session, user: User, profile: Profile, request: JobSearchRequest) -> JobSearchResponse:
    if request.mode not in {"all", "profile_default", "remote", "hybrid", "onsite", "hybrid_onsite"}:
        raise HTTPException(status_code=400, detail="Invalid job mode")
    sources = db.scalars(select(JobSource).where(JobSource.user_id == user.id, JobSource.status == "active")).all()
    domains = [source.domain for source in sources]
    if not domains:
        return JobSearchResponse(jobs=[])
    loaded = db.scalars(select(Job).where(Job.source.in_(domains)).order_by(Job.posted_at.desc().nullslast(), Job.first_seen_at.desc()).limit(500)).all()
    jobs = _without_duplicates(loaded, {source.domain for source in sources if source.kind in {"employer", "career"}})
    logger.info("Job deduplication: user_id=%s loaded=%s kept=%s", user.id, len(loaded), len(jobs))
    query = request.query.strip().lower()
    location = (request.location.strip() or ("" if request.mode == "all" else profile.city or (profile.preferred_locations or [""])[0])).lower()
    profile_terms = _profile_terms(profile)
    cutoff = utcnow() - timedelta(days=request.days) if request.days else None
    search_terms = [query] if query else ([] if request.mode == "all" else profile_terms)
    filtered, rejected = _filter_jobs(jobs, search_terms, location, profile.country, request.mode, cutoff)
    match_scope = "profile_and_location"
    if not filtered and not query:
        filtered, rejected = _filter_jobs(jobs, profile_terms, "", profile.country, request.mode, cutoff)
        match_scope = "profile_any_location"
    if not filtered and not query:
        filtered, rejected = _filter_jobs(jobs, [], location, profile.country, request.mode, cutoff)
        match_scope = "location_and_mode"
    if not filtered and not query and profile.country:
        filtered, rejected = _filter_jobs(jobs, [], "", profile.country, request.mode, cutoff)
        match_scope = "country_and_mode"
    logger.info("Job filtering: user_id=%s loaded=%s profile_terms=%s location=%s mode=%s scope=%s rejected=%s returned=%s", user.id, len(jobs), len(profile_terms), location or "any", request.mode, match_scope, rejected, len(filtered))
    return JobSearchResponse(jobs=filtered, match_scope=match_scope)


def _filter_jobs(
    jobs: list[Job],
    search_terms: list[str],
    location: str,
    country: str,
    mode: str,
    cutoff,
) -> tuple[list[JobResponse], dict[str, int]]:
    filtered = []
    rejected = {"terms": 0, "location": 0, "country": 0, "mode": 0, "age": 0}
    for job in jobs:
        job_text = " ".join([job.title, job.company, job.description]).lower()
        if search_terms and not any(term in job_text for term in search_terms):
            rejected["terms"] += 1
            continue
        city_matches = not location or any(location in item.lower() for item in (job.locations or []))
        if mode != "profile_default" and location and not city_matches:
            rejected["location"] += 1
            continue
        if country and job.eligible_countries and country.upper() not in job.eligible_countries:
            rejected["country"] += 1
            continue
        mode_matches = (
            mode == "all"
            or mode == job.work_mode
            or mode == "hybrid_onsite" and job.work_mode in {"hybrid", "onsite"}
            or mode == "profile_default" and (job.work_mode == "remote" or job.work_mode in {"hybrid", "onsite"} and city_matches)
        )
        if not mode_matches:
            rejected["mode"] += 1
            continue
        if cutoff and (job.posted_at is None or job.posted_at < cutoff):
            rejected["age"] += 1
            continue
        filtered.append(_job_response(job))
    return filtered, rejected


def _filter_summary(request: JobSearchRequest) -> dict[str, str | int | None]:
    return {"query": request.query, "location": request.location, "mode": request.mode, "days": request.days}


def _profile_terms(profile: Profile) -> list[str]:
    values = [
        *(profile.titles or []),
        *(profile.skills or []),
        *(profile.extra_keywords or []),
        profile.headline,
    ]
    return [value.strip().lower() for value in values if value and len(value.strip()) >= 3]


def _job_response(job: Job) -> JobResponse:
def _without_duplicates(jobs: list[Job], employer_domains: set[str]) -> list[Job]:
    # A job with no company name has nothing to tell it apart from another employer's, so it is never merged.
    keyed = [(job, _same_job_key(job) if job.company.strip() else f"unnamed:{position}") for position, job in enumerate(jobs)]
    best: dict[str, Job] = {}
    for job, key in keyed:
        current = best.get(key)
        if current is None or _preference(job, employer_domains) < _preference(current, employer_domains):
            best[key] = job
    return [job for job, key in keyed if best[key] is job]


def _same_job_key(job: Job) -> str:
    # Boards write a location differently ("Bucuresti, Bucuresti, RO" against "BUCURESTI ,, RO"),
    # so only the city name is compared, not the whole address that the stored fingerprint uses.
    city = (job.locations or [""])[0].split(",")[0]
    return fingerprint(job.company, job.title, city)


def _preference(job: Job, employer_domains: set[str]) -> tuple[bool, datetime]:
    # The employer's own posting carries its direct apply link; otherwise the earliest one seen is the original.
    return job.source not in employer_domains, job.first_seen_at


    return JobResponse(
        id=job.id,
        title=job.title,
        company=job.company,
        logo_url=f"https://www.google.com/s2/favicons?domain={job.source}&sz=64",
        locations=job.locations or [],
        work_mode=job.work_mode,
        experience_level=_experience_level(job.title, job.description),
        employment_type=job.employment_type,
        description=job.description,
        url=job.url,
        apply_url=job.apply_url,
        posted_at=job.posted_at,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_currency=job.salary_currency,
        source=job.source,
    )


def _experience_level(title: str, description: str) -> str | None:
    text = f"{title} {description}".lower()
    for pattern, label in ((r"\b(intern|internship|trainee)\b", "Intern"), (r"\b(junior|jr\.?|entry[- ]level)\b", "Junior"), (r"\b(senior|sr\.?|lead|principal|staff)\b", "Senior"), (r"\b(mid[- ]level|medior)\b", "Mid-level")):
        if re.search(pattern, text):
            return label
    return None


def _domain(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.hostname or "").lower().removeprefix("www.")


def _source_url(value: str) -> str:
    value = value.strip()
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    return value