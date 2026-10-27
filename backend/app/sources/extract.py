import json
import re
from datetime import datetime
from typing import Any

import pycountry
from bs4 import BeautifulSoup

from .posting import Posting

_REMOTE_WORDS = ("remote", "de acasa", "de acasă", "telemunca", "tele­munca", "hibrid")


def extract_jsonld(html: bytes | str, *, url: str, source: str) -> Posting | None:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        try:
            data = json.loads(node.string or node.get_text(), strict=False)
        except (TypeError, json.JSONDecodeError):
            continue
        for job in _walk_jsonld(data):
            if _has_type(job, "JobPosting"):
                return _posting_from_job(job, url=url, source=source)
    return None


def _walk_jsonld(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_jsonld(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_jsonld(child)


def _has_type(value: dict, expected: str) -> bool:
    types = value.get("@type", [])
    return expected in ([types] if isinstance(types, str) else types)


def _posting_from_job(job: dict, *, url: str, source: str) -> Posting:
    locations = []
    countries = []
    for location in _as_list(job.get("jobLocation")):
        address = location.get("address", {}) if isinstance(location, dict) else {}
        if isinstance(address, str):
            locations.append(address)
            continue
        parts = [address.get(key, "") for key in ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry")]
        locations.append(", ".join(str(part) for part in parts if part))
        country = _country_code(address.get("addressCountry"))
        if country:
            countries.append(country)
    for requirement in _as_list(job.get("applicantLocationRequirements")):
        country = _country_code(requirement.get("name") if isinstance(requirement, dict) else requirement)
        if country:
            countries.append(country)
    description = BeautifulSoup(str(job.get("description", "")), "html.parser").get_text(" ", strip=True)
    title = _clean(job.get("title"))
    company = job.get("hiringOrganization", {})
    company = company.get("name", "") if isinstance(company, dict) else str(company or "")
    remote = str(job.get("jobLocationType", "")).upper() == "TELECOMMUTE" or any(word in _plain(" ".join([title, description, *locations])) for word in _REMOTE_WORDS)
    salary_min, salary_max, currency = _salary(job.get("baseSalary"))
    return Posting(
        source=source,
        external_id=url,
        url=url,
        apply_url=str(job.get("url") or url),
        title=title,
        company=_clean(company),
        locations=[location for location in locations if location],
        remote=remote,
        eligible_countries=sorted(set(countries)),
        employment_type=_clean(job.get("employmentType")),
        description=description,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
        posted_at=_date(job.get("datePosted")),
        expires_at=_date(job.get("validThrough")),
    )


def _salary(value: Any) -> tuple[int | None, int | None, str]:
    if not isinstance(value, dict):
        return None, None, ""
    currency = str(value.get("currency", "")).upper()
    details = value.get("value", value)
    if not isinstance(details, dict):
        return None, None, currency
    low = _number(details.get("minValue", details.get("value")))
    high = _number(details.get("maxValue", details.get("value")))
    unit = str(details.get("unitText", details.get("unitCode", "month"))).lower()
    factor = {"year": 1 / 12, "month": 1, "week": 52 / 12, "day": 365 / 12, "hour": 160}.get(unit)
    if factor is None:
        return None, None, currency
    return (_round_salary(low, factor), _round_salary(high, factor), currency)


def _round_salary(value: float | None, factor: float) -> int | None:
    return round(value * factor) if value is not None else None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _country_code(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("value")
    text = str(value or "").strip()
    if len(text) == 2:
        return text.upper()
    match = pycountry.countries.search_fuzzy(text) if text else []
    return match[0].alpha_2 if match else ""


def _date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _plain(value: str) -> str:
    return re.sub(r"[^a-z0-9ăâîșț ]", " ", value.lower())


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else ([value] if value else [])
