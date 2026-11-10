from datetime import datetime

import pycountry
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cv_filename: str
    full_name: str
    headline: str
    summary: str
    titles: list[str]
    skills: list[str]
    years_experience: float
    country: str
    city: str
    salary_currency: str
    preferred_locations: list[str]
    remote_only: bool
    min_salary: int
    extra_keywords: list[str]
    has_cv: bool = False


class ProfileUpdate(BaseModel):
    full_name: str | None = None
    headline: str | None = None
    summary: str | None = None
    titles: list[str] | None = None
    skills: list[str] | None = None
    years_experience: float | None = Field(default=None, ge=0)
    country: str | None = None
    city: str | None = None
    salary_currency: str | None = None
    preferred_locations: list[str] | None = None
    remote_only: bool | None = None
    min_salary: int | None = Field(default=None, ge=0)
    extra_keywords: list[str] | None = None

    @field_validator("country")
    @classmethod
    def validate_country(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip().upper()
            if value and (len(value) != 2 or not value.isalpha() or pycountry.countries.get(alpha_2=value) is None):
                raise ValueError("country must be an ISO alpha-2 code")
        return value

    @field_validator("salary_currency")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip().upper()
            if value and (len(value) != 3 or not value.isalpha()):
                raise ValueError("salary_currency must be an ISO 4217 code")
        return value


class ExtractedProfile(BaseModel):
    full_name: str = ""
    headline: str = ""
    summary: str = ""
    titles: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    years_experience: float = Field(default=0, ge=0)
    country: str = ""
    city: str = ""
    salary_currency: str = ""

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        value = value.strip().upper()
        if value and pycountry.countries.get(alpha_2=value) is None:
            raise ValueError("country must be an ISO alpha-2 code")
        return value

    @field_validator("salary_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()


class SourceCreate(BaseModel):
    domain: str = ""
    url: str = ""
    kind: str = "career"


class SourceUpdate(BaseModel):
    enabled: bool | None = None


class SourceResponse(BaseModel):
    id: int
    domain: str
    source_url: str
    kind: str
    status: str
    reason: str
    extraction: str
    posting_count: int
    last_refreshed_at: datetime | None


class SourceDiscoveryResponse(BaseModel):
    created: int
    proposed: int


class SourceRefreshResponse(BaseModel):
    source_id: int
    status: str
    added: int
    updated: int
    failed: int
    reason: str = ""


class JobSearchRequest(BaseModel):
    query: str = ""
    location: str = ""
    mode: str = "hybrid_onsite"
    days: int | None = Field(default=None, ge=1, le=365)
    refresh: bool = False


class JobResponse(BaseModel):
    id: int
    title: str
    company: str
    logo_url: str
    locations: list[str]
    work_mode: str
    experience_level: str | None
    employment_type: str
    description: str
    url: str
    apply_url: str
    posted_at: datetime | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str
    source: str


class JobSearchResponse(BaseModel):
    jobs: list[JobResponse]
    refreshed: bool = False
    match_scope: str = "profile_and_location"


class CompanyCounts(BaseModel):
    total: int
    feed: int
    none: int
    unchecked: int


class FeedCard(BaseModel):
    source_id: int
    name: str
    provider: str
    provider_label: str
    slug: str
    status: str
    reason: str
    jobs: int
    last_refreshed_at: datetime | None
    domain: str
    logo_url: str
    careers_url: str


class CompanyCard(BaseModel):
    id: int
    name: str
    postings: int
    status: str
    provider: str
    provider_label: str
    slug: str
    domain: str
    logo_url: str
    checked_at: datetime | None
    jobs: int | None
    source_status: str | None


class CompaniesResponse(BaseModel):
    counts: CompanyCounts
    feeds: list[FeedCard]
    companies: list[CompanyCard]
    total_matching: int
