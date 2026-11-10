import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Company, JobSource, User
from ..schemas import CompaniesResponse, CompanyCard, CompanyCounts, FeedCard
from ..session import current_user
from ..sources.directory import READABLE

router = APIRouter(prefix="/api/companies", tags=["companies"])
PROVIDER_LABELS = {"greenhouse": "Greenhouse", "workday": "Workday", "smartrecruiters": "SmartRecruiters", "ashby": "Ashby", "workable": "Workable", "recruitee": "Recruitee", "lever": "Lever", "personio": "Personio", "rippling": "Rippling"}
STATUSES = {"all", "feed", "none", "unchecked"}
MAX_LIMIT = 200


@router.get("", response_model=CompaniesResponse)
def list_companies(
    status: str = "all",
    search: str = "",
    limit: int = 60,
    offset: int = 0,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> CompaniesResponse:
    if status not in STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status filter")
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)

    counts = dict(db.execute(select(Company.status, func.count()).where(Company.user_id == user.id).group_by(Company.status)).all())
    feed_sources = db.scalars(
        select(JobSource)
        .where(JobSource.user_id == user.id, JobSource.kind == "employer", JobSource.ats_provider != "")
        .order_by(JobSource.last_refreshed_at.desc().nullslast(), JobSource.id)
    ).all()
    by_feed = {(source.ats_provider, source.ats_slug): source for source in feed_sources}

    query = select(Company).where(Company.user_id == user.id)
    if status != "all":
        query = query.where(Company.status == status)
    if search.strip():
        query = query.where(func.lower(Company.name).contains(search.strip().lower(), autoescape=True))
    total_matching = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Company.postings.desc(), Company.name).limit(limit).offset(offset)).all()

    return CompaniesResponse(
        counts=CompanyCounts(
            total=sum(counts.values()), feed=counts.get("feed", 0), none=counts.get("none", 0), unchecked=counts.get("unchecked", 0)
        ),
        feeds=[_feed_card(db, user.id, source) for source in feed_sources],
        companies=[_company_card(company, by_feed.get((company.ats_provider, company.ats_slug))) for company in rows],
        total_matching=total_matching,
    )


def _company_card(company: Company, source: JobSource | None) -> CompanyCard:
    domain = company.domain or ""
    return CompanyCard(
        id=company.id,
        name=company.name,
        postings=company.postings,
        status=company.status,
        provider=company.ats_provider,
        provider_label=_label(company.ats_provider),
        slug=company.ats_slug,
        domain=domain,
        logo_url=_logo(domain),
        checked_at=company.checked_at,
        jobs=source.posting_count if source else None,
        source_status=source.status if source else None,
        known_board=_label(company.board_provider or ""),
        known_board_readable=(company.board_provider or "") in READABLE,
    )


def _feed_card(db: Session, user_id: int, source: JobSource) -> FeedCard:
    company = _company_of(db, user_id, source)
    domain = (company.domain if company else "") or ""
    return FeedCard(
        source_id=source.id,
        name=company.name if company else _tenant(source).title(),
        provider=source.ats_provider,
        provider_label=_label(source.ats_provider),
        slug=source.ats_slug,
        status=source.status,
        reason=source.reason,
        jobs=source.posting_count,
        last_refreshed_at=source.last_refreshed_at,
        domain=domain,
        logo_url=_logo(domain),
        careers_url=source.source_url,
    )


def _company_of(db: Session, user_id: int, source: JobSource) -> Company | None:
    exact = db.scalar(select(Company).where(Company.user_id == user_id, Company.ats_provider == source.ats_provider, Company.ats_slug == source.ats_slug))
    if exact:
        return exact
    # A feed added by hand has no company row of its own, so look for the company by name.
    tenant = _tenant(source)
    candidates = db.scalars(select(Company).where(Company.user_id == user_id, Company.key.like(f"{tenant[:4]}%")).order_by(Company.postings.desc())).all()
    squashed = {company.id: re.sub(r"[^a-z0-9]", "", company.key) for company in candidates}
    return next((company for company in candidates if squashed[company.id] == tenant), None) or next(
        (company for company in candidates if squashed[company.id].startswith(tenant)), None
    )


def _tenant(source: JobSource) -> str:
    return source.ats_slug.split("/")[0].split(".")[0].lower()


def _label(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider.title())


def _logo(domain: str) -> str:
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=64" if domain else ""
