from datetime import datetime

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
            if value and (len(value) != 2 or not value.isalpha()):
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
        return value.strip().upper()

    @field_validator("salary_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()


class SourceCreate(BaseModel):
    domain: str
    kind: str = "board"


class SourceUpdate(BaseModel):
    enabled: bool | None = None


class SourceResponse(BaseModel):
    id: int
    domain: str
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
