import html
import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qs, quote, urlparse, urlunparse

import pycountry
from bs4 import BeautifulSoup

from ..logging import logger
from .extract import _as_list, _clean, _date, _salary
from .fetch import FetchError, SafeFetcher
from .posting import Posting

SMARTRECRUITERS = "smartrecruiters"
GREENHOUSE = "greenhouse"
WORKDAY = "workday"

_API_HOSTS = {SMARTRECRUITERS: "api.smartrecruiters.com", GREENHOUSE: "boards-api.greenhouse.io"}
_API_BASES = {
    SMARTRECRUITERS: "https://api.smartrecruiters.com/v1/companies",
    GREENHOUSE: "https://boards-api.greenhouse.io/v1/boards",
}

_SMARTRECRUITERS_HOSTS = {"jobs.smartrecruiters.com", "careers.smartrecruiters.com"}
_GREENHOUSE_HOSTS = {"boards.greenhouse.io", "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io"}
_NOT_A_COMPANY = {"embed", "oneclick-ui"}
_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_ATS_LINK = re.compile(
    r"https://[a-z0-9.-]*(?:(?:smartrecruiters|greenhouse)\.(?:com|io)|myworkdayjobs\.com)/[^\s\"'<>\\)]*", re.I
)
_WORKDAY_HOST = re.compile(r"([a-z0-9][a-z0-9-]*)\.(wd\d+)\.myworkdayjobs\.com")
_WORKDAY_LOCALE = re.compile(r"[A-Za-z]{2}-[A-Za-z]{2}")
_SECOND_LEVEL_LABELS = {"co", "com", "org", "net", "gov", "edu", "ac"}

_MAX_REQUESTS = 10
_MAX_GUESSES = 4
_PAGE_SIZE = 100
_WORKDAY_PAGE_SIZE = 20
_MAX_PAGES = 5
_JOB_AD_SECTIONS = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")
_SALARY_UNITS = {"HOURLY": "hour", "DAILY": "day", "WEEKLY": "week", "MONTHLY": "month", "YEARLY": "year"}

Api = Callable[..., dict]


@dataclass(frozen=True)
class Feed:
    provider: str
    slug: str


def parse_ats_url(url: str) -> Feed | None:
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
    except (AttributeError, ValueError):
        return None
    if parsed.scheme != "https":
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]
    if host in _SMARTRECRUITERS_HOSTS:
        return _feed(SMARTRECRUITERS, segments[:1])
    if host == "api.smartrecruiters.com":
        return _feed(SMARTRECRUITERS, segments[2:3] if segments[:2] == ["v1", "companies"] else [])
    if host == "boards-api.greenhouse.io":
        return _feed(GREENHOUSE, segments[2:3] if segments[:2] == ["v1", "boards"] else [])
    if host in _GREENHOUSE_HOSTS:
        if segments[:1] == ["embed"]:
            return _feed(GREENHOUSE, parse_qs(parsed.query).get("for", [])[:1])
        return _feed(GREENHOUSE, segments[:1])
    workday = _WORKDAY_HOST.fullmatch(host)
    if workday:
        site = _feed(WORKDAY, segments[1:] if segments and _WORKDAY_LOCALE.fullmatch(segments[0]) else segments)
        return Feed(WORKDAY, f"{workday[1]}.{workday[2]}/{site.slug}") if site else None
    return None


def find_feed(domain: str, pages: list[bytes], country: str) -> Feed | None:
    fetchers: dict[str, SafeFetcher] = {}
    left = _MAX_REQUESTS

    def api(url: str, body: dict | None = None) -> dict:
        nonlocal left
        if left <= 0:
            raise FetchError("request budget spent")
        left -= 1
        host = urlparse(url).hostname or ""
        if host not in fetchers:
            fetchers[host] = SafeFetcher(host)
        return _get_json(fetchers[host], url, body)

    label = _domain_label(domain)
    for feed, guessed in _candidates(label, pages):
        if left <= 0:
            break
        try:
            reason = _rejection(feed, api, country.upper(), label if guessed else None)
        except FetchError as exc:
            reason = str(exc)
        if reason is None:
            logger.info("ATS feed accepted: domain=%s provider=%s slug=%s guessed=%s", domain, feed.provider, feed.slug, guessed)
            return feed
        logger.info("ATS feed rejected: domain=%s provider=%s slug=%s guessed=%s reason=%s", domain, feed.provider, feed.slug, guessed, reason)
    return None


def read_feed(feed: Feed, domain: str, country: str, known: set[str], limit: int = 100, *, city: str = "") -> list[Posting]:
    if limit <= 0:
        return []
    if feed.provider == SMARTRECRUITERS:
        return _read_smartrecruiters(feed.slug, domain, country.upper(), known, limit)
    if feed.provider == GREENHOUSE:
        return _read_greenhouse(feed.slug, domain, country.upper(), known, limit)
    if feed.provider == WORKDAY:
        return _read_workday(feed.slug, domain, country.upper(), known, limit, city)
    raise ValueError(f"unknown ATS provider: {feed.provider}")


def _feed(provider: str, candidates: list[str]) -> Feed | None:
    if candidates and candidates[0] not in _NOT_A_COMPANY and _SLUG.fullmatch(candidates[0]):
        return Feed(provider, candidates[0])
    return None


def _domain_label(domain: str) -> str:
    parts = domain.lower().removeprefix("www.").split(".")
    if len(parts) > 2 and len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL_LABELS:
        parts = parts[:-1]
    return parts[-2] if len(parts) > 1 else parts[0]


def _candidates(label: str, pages: list[bytes]) -> list[tuple[Feed, bool]]:
    linked = []
    for page in pages:
        # Inline JSON escapes slashes, so a link there reads https:\/\/host\/slug.
        text = page.decode("utf-8", errors="replace").replace("\\/", "/")
        linked.extend(parse_ats_url(match.rstrip(".,;")) for match in _ATS_LINK.findall(text))
    slugs = dict.fromkeys([label, label.replace("-", "")])
    guessed = [Feed(provider, slug) for slug in slugs if _SLUG.fullmatch(slug) for provider in (SMARTRECRUITERS, GREENHOUSE)]

    seen: set[tuple[str, str]] = set()
    guesses = 0
    candidates = []
    for feed, is_guess in [(feed, False) for feed in linked if feed] + [(feed, True) for feed in guessed]:
        key = (feed.provider, feed.slug.lower())
        if key in seen or (is_guess and guesses == _MAX_GUESSES):
            continue
        seen.add(key)
        guesses += is_guess
        candidates.append((feed, is_guess))
    return candidates


def _rejection(feed: Feed, api: Api, country: str, label: str | None) -> str | None:
    # label is None for a slug linked from the company's own pages, which needs no name check.
    if feed.provider == WORKDAY:
        return _workday_rejection(feed.slug, api, country)
    base = f"{_API_BASES[feed.provider]}/{quote(feed.slug, safe='')}"
    if feed.provider == SMARTRECRUITERS:
        data = api(f"{base}/postings?country={country.lower()}&limit=1")
        if _int(data.get("totalFound")) < 1:
            return "no posting in country"
        first = (_dicts(data.get("content")) or [{}])[0]
        name = _clean(_dict(first.get("company")).get("name"))
        return None if label is None or _names_agree(name, label) else f"company name {name!r} does not match"
    jobs = _dicts(api(f"{base}/jobs").get("jobs"))
    pattern = _country_pattern(country)
    if not any(pattern.search(text) for job in jobs for text in _greenhouse_places(job)[1]):
        return "no posting in country"
    if label is None:
        return None
    name = _clean(api(base).get("name"))
    return None if _names_agree(name, label) else f"company name {name!r} does not match"


def _names_agree(name: str, label: str) -> bool:
    if not name:
        return True
    name, label = _squash(name), _squash(label)
    return bool(name and label) and (label in name or name in label)


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


@lru_cache
def _country_pattern(country: str) -> re.Pattern:
    record = pycountry.countries.get(alpha_2=country)
    names = {getattr(record, attr, "") for attr in ("name", "official_name", "common_name")} if record else set()
    # Names match any case, but the two-letter code only as upper case: "in" or "it" in running text is not a country.
    alternatives = [f"(?i:{re.escape(name)})" for name in sorted(names) if name] + [re.escape(country)]
    return re.compile(rf"(?<![A-Za-z])(?:{'|'.join(alternatives)})(?![A-Za-z])")


def _get_json(fetcher: SafeFetcher, url: str, body: dict | None = None) -> dict:
    content = (fetcher.get(url) if body is None else fetcher.post_json(url, body)).content
    try:
        data = json.loads(content)
    except ValueError as exc:
        raise FetchError("feed was not valid JSON") from exc
    if not isinstance(data, dict):
        raise FetchError("feed had an unexpected shape")
    return data


def _read_smartrecruiters(slug: str, domain: str, country: str, known: set[str], limit: int) -> list[Posting]:
    fetcher = SafeFetcher(_API_HOSTS[SMARTRECRUITERS])
    base = f"{_API_BASES[SMARTRECRUITERS]}/{quote(slug, safe='')}"
    fresh = []
    for offset in range(0, _PAGE_SIZE * _MAX_PAGES, _PAGE_SIZE):
        data = _get_json(fetcher, f"{base}/postings?country={country.lower()}&limit={_PAGE_SIZE}&offset={offset}")
        items = _dicts(data.get("content"))
        for item in items:
            posting_id = str(item.get("id") or "")
            item_country = str(_dict(item.get("location")).get("country") or "").upper()
            if posting_id and _smartrecruiters_url(slug, posting_id) not in known and item_country in {"", country}:
                fresh.append(item)
        # The list is taken to be newest first, so stopping once there are enough keeps the newest.
        if len(fresh) >= limit or not items or offset + len(items) >= _int(data.get("totalFound")):
            break
    fresh.sort(key=lambda item: _date(item.get("releasedDate")) or datetime.min, reverse=True)

    postings = []
    for item in fresh[:limit]:
        try:
            detail = _get_json(fetcher, f"{base}/postings/{quote(str(item['id']), safe='')}")
        except FetchError:
            continue
        postings.append(_smartrecruiters_posting(slug, domain, country, {**item, **detail}))
    return postings


def _smartrecruiters_url(slug: str, posting_id: str) -> str:
    return f"https://jobs.smartrecruiters.com/{slug}/{posting_id}"


def _smartrecruiters_posting(slug: str, domain: str, country: str, ad: dict) -> Posting:
    url = _smartrecruiters_url(slug, str(ad["id"]))
    location = _dict(ad.get("location"))
    place = ", ".join(part for part in (_clean(location.get("city")), _clean(location.get("region")), country) if part)
    work_mode = "hybrid" if location.get("hybrid") else "remote" if location.get("remote") else "onsite"
    salary_min, salary_max, currency = _smartrecruiters_salary(_dict(ad.get("compensation")))
    sections = _dict(_dict(ad.get("jobAd")).get("sections"))
    description = "\n\n".join(filter(None, (_section_text(_dict(sections.get(name))) for name in _JOB_AD_SECTIONS)))
    return Posting(
        source=domain,
        external_id=url,
        url=url,
        apply_url=str(ad.get("applyUrl") or ad.get("postingUrl") or url),
        title=_clean(ad.get("name")),
        company=_clean(_dict(ad.get("company")).get("name")) or domain,
        locations=[place],
        remote=work_mode != "onsite",
        work_mode=work_mode,
        eligible_countries=[country],
        employment_type=_clean(_dict(ad.get("typeOfEmployment")).get("label")),
        description=description,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
        posted_at=_date(ad.get("releasedDate")),
        expires_at=None,
    )


def _smartrecruiters_salary(compensation: dict) -> tuple[int | None, int | None, str]:
    low, high = compensation.get("min"), compensation.get("max")
    if low is None and high is None:
        return None, None, ""
    unit = _SALARY_UNITS.get(compensation.get("period"), "")
    return _salary({"currency": compensation.get("currency") or "", "value": {"minValue": low, "maxValue": high, "unitText": unit}})


def _section_text(section: dict) -> str:
    text = _plain_text(section.get("text"))
    return f"{_clean(section.get('title'))}\n{text}".strip() if text else ""


def _read_greenhouse(slug: str, domain: str, country: str, known: set[str], limit: int) -> list[Posting]:
    fetcher = SafeFetcher(_API_HOSTS[GREENHOUSE])
    data = _get_json(fetcher, f"{_API_BASES[GREENHOUSE]}/{quote(slug, safe='')}/jobs?content=true")
    pattern = _country_pattern(country)
    fresh = []
    for job in _dicts(data.get("jobs")):
        url = _greenhouse_url(job)
        if url and url not in known and any(pattern.search(text) for text in _greenhouse_places(job)[1]):
            fresh.append(job)
    fresh.sort(key=lambda job: _greenhouse_posted(job) or datetime.min, reverse=True)
    return [_greenhouse_posting(job, domain, country) for job in fresh[:limit]]


def _greenhouse_url(job: dict) -> str:
    parsed = urlparse(str(job.get("absolute_url") or ""))
    if not parsed.netloc:
        return ""
    # Boards on a company's own domain tell jobs apart only by ?gh_jid=, so that one parameter must stay.
    gh_jid = parse_qs(parsed.query).get("gh_jid")
    query = f"gh_jid={quote(gh_jid[0], safe='')}" if gh_jid else ""
    return urlunparse(parsed._replace(query=query, fragment=""))


def _greenhouse_places(job: dict) -> tuple[list[str], list[str]]:
    # location.name is often a bare city. The office entry spells out the country, but the API sends
    # offices only with content=true, so the lighter list used by find_feed sees location.name alone.
    name = _clean(_dict(job.get("location")).get("name"))
    offices = [text for text in (_clean(_dict(office).get("location")) for office in _dicts(job.get("offices"))) if text]
    return ([name] if name else offices), [name, *offices]


def _greenhouse_posted(job: dict) -> datetime | None:
    return _date(job.get("first_published")) or _date(job.get("updated_at"))


def _greenhouse_posting(job: dict, domain: str, country: str) -> Posting:
    url = _greenhouse_url(job)
    locations, searchable = _greenhouse_places(job)
    title = _clean(job.get("title"))
    words = " ".join([title, *searchable]).lower()
    work_mode = "hybrid" if "hybrid" in words else "remote" if "remote" in words else "onsite"
    return Posting(
        source=domain,
        external_id=url,
        url=url,
        apply_url=str(job.get("absolute_url")),
        title=title,
        company=_clean(job.get("company_name")) or domain,
        locations=locations,
        remote=work_mode != "onsite",
        work_mode=work_mode,
        eligible_countries=[country],
        employment_type="",
        description=_plain_text(html.unescape(str(job.get("content") or ""))),
        salary_min=None,
        salary_max=None,
        salary_currency="",
        posted_at=_greenhouse_posted(job),
        expires_at=_date(job.get("application_deadline")),
    )


def _workday_rejection(slug: str, api: Api, country: str) -> str | None:
    api_base = _workday_parts(slug)[1]
    data = api(f"{api_base}/jobs", _workday_query(_workday_search("", country), 1, 0))
    items = _dicts(data.get("jobPostings"))
    path = _workday_path(items[0]) if items else ""
    if _int(data.get("total")) < 1 or not path:
        return "no posting in country"
    info = _dict(api(f"{api_base}{path}").get("jobPostingInfo"))
    return None if _workday_in_country(info, country) else "no posting in country"


def _read_workday(slug: str, domain: str, country: str, known: set[str], limit: int, city: str) -> list[Posting]:
    host, api_base, site = _workday_parts(slug)
    fetcher = SafeFetcher(host)
    search = _workday_search(city, country)
    fresh: dict[str, dict] = {}
    total = 0
    for offset in range(0, _WORKDAY_PAGE_SIZE * _MAX_PAGES, _WORKDAY_PAGE_SIZE):
        data = _get_json(fetcher, f"{api_base}/jobs", _workday_query(search, _WORKDAY_PAGE_SIZE, offset))
        # Only the first page carries total (later pages say 0), and an offset past the end wraps
        # back to the first page, so the first page's total is what ends the paging.
        if offset == 0:
            total = _int(data.get("total"))
        items = _dicts(data.get("jobPostings"))
        for item in items:
            path = _workday_path(item)
            if path and _workday_url(host, site, path) not in known:
                fresh.setdefault(path, item)
        if len(fresh) >= limit or not items or offset + len(items) >= total:
            break

    # The list is ranked by relevance and has no date, only "Posted 12 Days Ago", so that text picks
    # which postings are worth a detail request and startDate from the detail orders the result.
    postings = []
    for path, item in sorted(fresh.items(), key=lambda pair: _workday_age(pair[1])):
        if len(postings) == limit:
            break
        try:
            detail = _get_json(fetcher, f"{api_base}{path}")
        except FetchError:
            continue
        posting = _workday_posting(detail, _workday_url(host, site, path), domain, country)
        if posting:
            postings.append(posting)
    postings.sort(key=lambda posting: posting.posted_at or datetime.min, reverse=True)
    return postings


def _workday_parts(slug: str) -> tuple[str, str, str]:
    label, _, site = slug.partition("/")
    host = f"{label}.myworkdayjobs.com"
    return host, f"https://{host}/wday/cxs/{label.partition('.')[0]}/{site}", site


def _workday_url(host: str, site: str, path: str) -> str:
    return f"https://{host}/{site}{path}"


def _workday_path(item: dict) -> str:
    path = urlparse(str(item.get("externalPath") or "")).path
    return path if path.startswith("/") else ""


def _workday_query(search: str, limit: int, offset: int) -> dict:
    return {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": search}


def _workday_search(city: str, country: str) -> str:
    record = pycountry.countries.get(alpha_2=country)
    country_name = getattr(record, "common_name", None) or getattr(record, "name", country)
    return _fold(city) or _fold(country_name)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return _clean("".join(char for char in decomposed if not unicodedata.combining(char)))


def _workday_age(item: dict) -> int:
    text = str(item.get("postedOn") or "").lower()
    if "today" in text:
        return 0
    if "yesterday" in text:
        return 1
    days = re.search(r"\d+", text)
    return int(days.group()) if days else 10**6


def _workday_locations(info: dict) -> list[str]:
    names = [_clean(name) for name in [info.get("location"), *_as_list(info.get("additionalLocations"))]]
    return list(dict.fromkeys(name for name in names if name))


def _workday_in_country(info: dict, country: str) -> bool:
    requisition = _dict(_dict(info.get("jobRequisitionLocation")).get("country"))
    texts = [
        _dict(info.get("country")).get("descriptor"),
        requisition.get("descriptor"),
        _clean(requisition.get("alpha2Code")).upper(),
        *_workday_locations(info),
    ]
    pattern = _country_pattern(country)
    return any(pattern.search(_clean(text)) for text in texts)


def _workday_posting(detail: dict, url: str, domain: str, country: str) -> Posting | None:
    info = _dict(detail.get("jobPostingInfo"))
    title = _clean(info.get("title"))
    if not title or not _workday_in_country(info, country):
        return None
    locations = _workday_locations(info)
    words = " ".join([title, *locations, _clean(info.get("remoteType"))]).lower()
    work_mode = "hybrid" if "hybrid" in words else "remote" if "remote" in words else "onsite"
    return Posting(
        source=domain,
        external_id=url,
        url=url,
        apply_url=str(info.get("externalUrl") or url),
        title=title,
        company=_clean(_dict(detail.get("hiringOrganization")).get("name")) or domain,
        locations=locations,
        remote=work_mode != "onsite",
        work_mode=work_mode,
        eligible_countries=[country],
        employment_type=_clean(info.get("timeType")),
        description=_plain_text(info.get("jobDescription")),
        salary_min=None,
        salary_max=None,
        salary_currency="",
        posted_at=_date(info.get("startDate")),
        expires_at=None,
    )


def _plain_text(value: Any) -> str:
    return BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _dicts(value: Any) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _int(value: Any) -> int:
    return value if isinstance(value, int) else 0
