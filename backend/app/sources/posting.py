from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Posting:
    source: str
    external_id: str
    url: str
    apply_url: str
    title: str
    company: str
    locations: list[str]
    remote: bool
    eligible_countries: list[str]
    employment_type: str
    description: str
    salary_min: int | None
    salary_max: int | None
    salary_currency: str
    posted_at: datetime | None
    expires_at: datetime | None
