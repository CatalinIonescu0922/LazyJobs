import re
from datetime import timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..llm import propose_job_boards
from ..logging import logger
from ..models import Job, JobSource, Profile, User, utcnow
from ..schemas import JobResponse, JobSearchRequest, JobSearchResponse
from ..session import current_user
from ..sources.crawl import refresh_source

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


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
    return _search(db, user, profile, JobSearchRequest(query=query, location=location, mode=mode, days=days))


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
    return result.model_copy(update={"refreshed": refreshed})


def _profile(db: Session, user: User) -> Profile:
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile is None:
        raise HTTPException(status_code=400, detail="Upload a CV before searching for jobs")
    return profile


def _refresh_user_sources(db: Session, user: User, profile: Profile) -> None:
    sources = db.scalars(select(JobSource).where(JobSource.user_id == user.id, JobSource.status != "disabled")).all()
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
    for source in sources:
        try:
            refresh_source(db, source)
        except Exception as exc:
            db.rollback()
            source.status = "failed"
            source.reason = str(exc)[:500] or "source refresh failed"
            db.commit()
            logger.exception("Automatic job refresh failed for source=%s", source.domain)


def _search(db: Session, user: User, profile: Profile, request: JobSearchRequest) -> JobSearchResponse:
    if request.mode not in {"all", "remote", "hybrid", "onsite", "hybrid_onsite"}:
        raise HTTPException(status_code=400, detail="Invalid job mode")
    sources = db.scalars(select(JobSource).where(JobSource.user_id == user.id, JobSource.status == "active")).all()
    domains = [source.domain for source in sources]
    if not domains:
        return JobSearchResponse(jobs=[])
    jobs = db.scalars(select(Job).where(Job.source.in_(domains)).order_by(Job.posted_at.desc().nullslast(), Job.first_seen_at.desc()).limit(500)).all()
    query = request.query.strip().lower()
    location = (request.location.strip() or profile.city or (profile.preferred_locations or [""])[0]).lower()
    profile_terms = _profile_terms(profile)
    cutoff = utcnow() - timedelta(days=request.days) if request.days else None
    filtered = []
    for job in jobs:
        job_text = " ".join([job.title, job.company, job.description]).lower()
        search_terms = [query] if query else profile_terms
        if search_terms and not any(term in job_text for term in search_terms):
            continue
        if location and not any(location in item.lower() for item in (job.locations or [])):
            continue
        if request.mode == "remote" and job.work_mode != "remote":
            continue
        if request.mode == "hybrid" and job.work_mode != "hybrid":
            continue
        if request.mode == "onsite" and job.work_mode != "onsite":
            continue
        if request.mode == "hybrid_onsite" and job.work_mode not in {"hybrid", "onsite"}:
            continue
        if cutoff and (job.posted_at is None or job.posted_at < cutoff):
            continue
        filtered.append(_job_response(job))
    return JobSearchResponse(jobs=filtered)


def _profile_terms(profile: Profile) -> list[str]:
    values = [
        *(profile.titles or []),
        *(profile.skills or []),
        *(profile.extra_keywords or []),
        profile.headline,
    ]
    return [value.strip().lower() for value in values if value and len(value.strip()) >= 3]


def _job_response(job: Job) -> JobResponse:
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