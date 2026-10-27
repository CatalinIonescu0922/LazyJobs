from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..llm import propose_job_boards
from ..models import JobSource, Profile, User
from ..schemas import SourceCreate, SourceDiscoveryResponse, SourceResponse, SourceRefreshResponse, SourceUpdate
from ..session import current_user
from ..sources.crawl import refresh_source

router = APIRouter(prefix="/api/sources", tags=["sources"])
UNSUPPORTED_DOMAINS = {
    "linkedin.com",
    "indeed.com",
    "glassdoor.com",
    "jooble.org",
    "facebook.com",
}


@router.get("", response_model=list[SourceResponse])
def list_sources(user: User = Depends(current_user), db: Session = Depends(get_db)):
    sources = db.scalars(select(JobSource).where(JobSource.user_id == user.id).order_by(JobSource.created_at)).all()
    return [_source_response(source, db) for source in sources if not _is_unsupported(source.domain)]


@router.post("", response_model=SourceResponse, status_code=201)
def add_source(payload: SourceCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    domain = _domain(payload.domain)
    if _is_unsupported(domain):
        raise HTTPException(status_code=400, detail="This platform is not supported by the safe public crawler")
    existing = db.scalar(select(JobSource).where(JobSource.user_id == user.id, JobSource.domain == domain, JobSource.kind == payload.kind))
    if existing:
        return _source_response(existing, db)
    source = JobSource(user_id=user.id, domain=domain, kind=payload.kind)
    db.add(source)
    db.commit()
    db.refresh(source)
    return _source_response(source, db)


@router.post("/discover", response_model=SourceDiscoveryResponse)
def discover_sources(kind: str = "boards", user: User = Depends(current_user), db: Session = Depends(get_db)):
    if kind != "boards":
        raise HTTPException(status_code=400, detail="Phase 8 supports board discovery only")
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if not profile or not profile.country:
        raise HTTPException(status_code=400, detail="Set your profile country before discovering boards")
    proposals = propose_job_boards(profile.country)
    created = 0
    for proposal in proposals:
        try:
            domain = _domain(proposal.get("domain", ""))
        except HTTPException:
            continue
        if not domain:
            continue
        if _is_unsupported(domain):
            continue
        existing = db.scalar(select(JobSource).where(JobSource.user_id == user.id, JobSource.domain == domain, JobSource.kind == "board"))
        if existing is None:
            db.add(JobSource(user_id=user.id, domain=domain, kind="board"))
            created += 1
    db.commit()
    return SourceDiscoveryResponse(created=created, proposed=len(proposals))


@router.patch("/{source_id}", response_model=SourceResponse)
def update_source(source_id: int, payload: SourceUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    source = _owned_source(source_id, user, db)
    if payload.enabled is not None:
        source.status = "candidate" if payload.enabled else "disabled"
        source.reason = "" if payload.enabled else "disabled by user"
    db.commit()
    db.refresh(source)
    return _source_response(source, db)


@router.post("/{source_id}/refresh", response_model=SourceRefreshResponse)
def refresh(source_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    source = _owned_source(source_id, user, db)
    if _is_unsupported(source.domain):
        source.status = "failed"
        source.reason = "not supported by the safe public crawler"
        db.commit()
        return SourceRefreshResponse(
            source_id=source.id,
            status=source.status,
            added=0,
            updated=0,
            failed=0,
            reason=source.reason,
        )
    result = refresh_source(db, source)
    return SourceRefreshResponse.model_validate(result)


def _owned_source(source_id: int, user: User, db: Session) -> JobSource:
    source = db.scalar(select(JobSource).where(JobSource.id == source_id, JobSource.user_id == user.id))
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


def _domain(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value if "://" in value else f"https://{value}")
    domain = (parsed.hostname or "").lower().removeprefix("www.")
    if not domain or "." not in domain or any(char.isspace() for char in domain):
        raise HTTPException(status_code=400, detail="Enter a valid domain")
    return domain


def _is_unsupported(domain: str) -> bool:
    return domain in UNSUPPORTED_DOMAINS or any(domain.endswith(f".{blocked}") for blocked in UNSUPPORTED_DOMAINS)


def _source_response(source: JobSource, db: Session) -> SourceResponse:
    return SourceResponse(
        id=source.id,
        domain=source.domain,
        kind=source.kind,
        status=source.status,
        reason=source.reason,
        extraction=source.extraction,
        posting_count=source.posting_count,
        last_refreshed_at=source.last_refreshed_at,
    )
