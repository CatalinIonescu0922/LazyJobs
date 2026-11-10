import json
import math
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urlparse

import pycountry
from bs4 import BeautifulSoup

from .extract import _clean, _country_code, _number, _salary
from .fetch import FetchError, SafeFetcher
from .posting import Posting

DOMAIN = "himalayas.app"

_SEARCH_URL = f"https://{DOMAIN}/jobs/api/search"
_PAGE_SIZE = 20
_PAGE_DELAY_SECONDS = 2
_MAX_SALARY = 2_000_000_000
_GONE = {"source returned 410", "source returned 404"}
# "fortnightly" is a documented period too, but extract._salary has no unit for it, so those jobs keep no salary.
_PERIOD_UNITS = {"hourly": "hour", "weekly": "week", "monthly": "month", "annual": "year"}
# pycountry renamed Turkey to Turkiye; the API still sends the old name.
_RENAMED = {"Turkey": "TR"}


def search_jobs(query: str, country: str, known: set[str], *, pages: int = 3) -> list[Posting]:
    fetcher = SafeFetcher(DOMAIN)
    seen = set(known)
    postings = []
    read = 0
    for page in range(1, pages + 1):
        if page > 1:
            # The API is shared by every keyless caller and its data refreshes only every 24 hours.
            time.sleep(_PAGE_DELAY_SECONDS)
        params = urlencode({"q": query, "country": country.upper(), "page": page})
        data = _get_json(fetcher, f"{_SEARCH_URL}?{params}")
        jobs = data.get("jobs")
        jobs = jobs if isinstance(jobs, list) else []
        read += len(jobs)
        for job in jobs:
            guid = _clean(job.get("guid")) if isinstance(job, dict) else ""
            if not guid or guid in seen:
                continue
            posting = _posting(job, guid)
            if posting:
                seen.add(guid)
                postings.append(posting)
        total = data.get("totalCount")
        if len(jobs) < _PAGE_SIZE or (isinstance(total, int) and read >= total):
            break
    return postings


def is_closed(external_id: str, fetcher: SafeFetcher | None = None) -> bool:
    parsed = urlparse(external_id)
    host = (parsed.hostname or "").removeprefix("www.")
    if parsed.scheme != "https" or host != DOMAIN or not parsed.path.startswith("/companies/"):
        raise FetchError("not a Himalayas job URL")
    try:
        (fetcher or SafeFetcher(DOMAIN)).get(f"https://{DOMAIN}/jobs/api{parsed.path}")
    except FetchError as exc:
        # 410 is a closed job. 404 is "no job at this path in the API", which for a job the feed once
        # listed means it was taken down without a 410.
        if str(exc) in _GONE:
            return True
        raise
    return False


def _get_json(fetcher: SafeFetcher, url: str) -> dict:
    try:
        data = json.loads(fetcher.get(url).content)
    except ValueError as exc:
        raise FetchError("feed was not valid JSON") from exc
    if not isinstance(data, dict):
        raise FetchError("feed had an unexpected shape")
    return data


def _posting(job: dict, guid: str) -> Posting | None:
    title = _clean(job.get("title"))
    description = _plain_text(job.get("description"))
    if not title or not description:
        return None
    places = list(dict.fromkeys(name for name in map(_place_name, _list(job.get("locationRestrictions"))) if name))
    salary_min, salary_max, currency = _monthly_salary(job)
    return Posting(
        source=DOMAIN,
        external_id=guid,
        url=guid,
        # The terms require applicants to go through applicationLink and not to the employer's own page.
        apply_url=_clean(job.get("applicationLink")) or guid,
        title=title,
        company=_clean(job.get("companyName")) or DOMAIN,
        locations=places or ["Remote"],
        remote=True,
        work_mode="remote",
        eligible_countries=list(dict.fromkeys(code for code in map(_iso_code, places) if code)),
        employment_type=_clean(job.get("employmentType")),
        description=description,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
        posted_at=_utc(job.get("pubDate")),
        expires_at=_utc(job.get("expiryDate")),
    )


def _monthly_salary(job: dict) -> tuple[int | None, int | None, str]:
    # The documented default period is annual, but the API sends it even when no salary is stated,
    # so a missing or unknown period leaves the salary empty and is never assumed.
    unit = _PERIOD_UNITS.get(str(job.get("salaryPeriod") or "").lower())
    low, high = _figure(job.get("minSalary")), _figure(job.get("maxSalary"))
    currency = str(job.get("currency") or "").strip().upper()
    if unit is None or (low is None and high is None) or len(currency) != 3 or not currency.isalpha():
        return None, None, ""
    monthly = _salary({"currency": currency, "value": {"minValue": low, "maxValue": high, "unitText": unit}})
    if max(figure or 0 for figure in monthly[:2]) > _MAX_SALARY:
        return None, None, ""
    return monthly


def _figure(value: Any) -> float | None:
    number = _number(value)
    return number if number is not None and math.isfinite(number) and number >= 0 else None


def _place_name(entry: Any) -> str:
    # The docs show {alpha2, name, slug} objects, but the live API sends plain country names.
    return _clean(entry.get("name") if isinstance(entry, dict) else entry)


def _iso_code(name: str) -> str:
    # _country_code searches fuzzily and turns Niger into Nigeria, so an exact ISO name goes first.
    record = pycountry.countries.get(name=name)
    return record.alpha_2 if record else _RENAMED.get(name) or _country_code(name)


def _utc(seconds: Any) -> datetime | None:
    if not seconds:
        return None
    try:
        return datetime.fromtimestamp(float(seconds), timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _plain_text(value: Any) -> str:
    return BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []
