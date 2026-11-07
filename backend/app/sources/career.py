from urllib.parse import parse_qs, urldefrag, unquote, urljoin, urlparse

from bs4 import BeautifulSoup
import pycountry
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..logging import logger, timed
from ..models import Job, JobSource, utcnow
from .crawl import _upsert_job
from .extract import extract_jsonld
from .fetch import FetchError, SafeFetcher

MAX_CAREER_LINKS = 80
CAREER_WORDS = ("career", "careers", "job", "jobs", "opening", "openings", "position", "vacancy", "work-with-us")


@timed
def refresh_career_source(db: Session, source: JobSource, country: str = "", city: str = "") -> dict[str, int | str]:
    source_url = source.source_url or f"https://{source.domain}"
    fetcher = SafeFetcher(source.domain)
    try:
        root = fetcher.get(source_url)
        pages = [(root.url, root.content)]
        queued = _discovery_links(root.content, root.url, source.domain, country, city)
        logger.info("Career discovery started: source=%s initial_links=%s country=%s city=%s", source.domain, len(queued), country, city)
        seen_pages = {root.url}
        cursor = 0
        while cursor < len(queued) and len(pages) < MAX_CAREER_LINKS:
            link = queued[cursor]
            cursor += 1
            if link in seen_pages:
                continue
            seen_pages.add(link)
            try:
                result = fetcher.get(link)
            except FetchError:
                continue
            pages.append((result.url, result.content))
            children = _discovery_links(result.content, result.url, source.domain, country, city)
            fresh_children = [child for child in children if child not in seen_pages and child not in queued]
            if fresh_children:
                queued[cursor:cursor] = fresh_children
            if len(pages) <= 5 or len(pages) % 10 == 0:
                logger.info("Career discovery progress: source=%s pages=%s queued_links=%s last_url=%s", source.domain, len(pages), len(queued), result.url)
        logger.info("Career discovery completed: source=%s pages=%s queued_links=%s", source.domain, len(pages), len(queued))

        added = 0
        seen_urls: set[str] = set()
        for page_url, content in pages:
            posting = extract_jsonld(content, url=page_url, source=source.domain)
            if not posting or not posting.title or not posting.description or posting.external_id in seen_urls:
                continue
            if country and posting.eligible_countries and country.upper() not in posting.eligible_countries:
                logger.info("Career posting skipped by country: source=%s country=%s eligible=%s url=%s", source.domain, country, posting.eligible_countries, page_url)
                continue
            seen_urls.add(posting.external_id)
            with db.begin_nested():
                _upsert_job(db, posting)
                db.flush()
            added += 1

        if not added and source.posting_count == 0:
            source.status = "failed"
            source.reason = "needs browser rendering" if _looks_like_js_shell(root.content) else "no JobPosting data found"
            source.extraction = ""
        else:
            source.status = "active"
            source.reason = ""
            source.extraction = "jsonld"
        source.last_refreshed_at = utcnow()
        source.posting_count = db.query(Job).filter(Job.source == source.domain).count()
        db.commit()
        logger.info("Career source refreshed: source=%s pages=%s added=%s status=%s", source.domain, len(pages), added, source.status)
        return {"source_id": source.id, "status": source.status, "added": added, "updated": 0, "failed": 0, "reason": source.reason}
    except FetchError as exc:
        source.status = "failed"
        source.reason = str(exc)
        db.commit()
        return {"source_id": source.id, "status": source.status, "added": 0, "updated": 0, "failed": 1, "reason": source.reason}


def _career_links(content: bytes, base_url: str, domain: str) -> list[str]:
    soup = BeautifulSoup(content, "html.parser")
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        url = urldefrag(urljoin(base_url, str(anchor["href"])))[0]
        parsed = urlparse(url)
        text = f"{anchor.get_text(' ', strip=True)} {parsed.path} {parsed.query}".lower()
        path = parsed.path.rstrip("/").lower()
        collection_route = path in {"/jobs", "/careers", "/career", "/locations", "/location", "/country"}
        if parsed.scheme == "https" and parsed.hostname and parsed.hostname.removeprefix("www.") == domain and not collection_route and any(word in text for word in CAREER_WORDS):
            if url not in links:
                links.append(url)
    return links


@timed
def _discovery_links(content: bytes, base_url: str, domain: str, country: str, city: str) -> list[str]:
    search_links = _search_links(content, base_url, domain, country, city)
    location_links = _location_links(content, base_url, domain, country)
    career_links = _career_links(content, base_url, domain) if _is_country_search_url(base_url, country) else []
    detail_links = [link for link in career_links if _is_job_detail(link)]
    other_links = [link for link in career_links if not _is_job_detail(link)]
    return list(dict.fromkeys(search_links + location_links + detail_links + other_links))


def _is_country_search_url(url: str, country: str) -> bool:
    parsed = urlparse(url)
    country_name = _country_name(country).lower()
    values = [value.lower() for values in parse_qs(parsed.query).values() for value in values]
    return "/jobs" in parsed.path and any(value in {country_name, country.lower()} for value in values)


def _is_job_detail(url: str) -> bool:
    path = urlparse(url).path.rstrip("/").lower()
    parts = [part for part in path.split("/") if part]
    return len(parts) >= 2 and parts[-2] in {"job", "jobs", "position", "positions", "vacancy", "opening", "openings"}


def _location_links(content: bytes, base_url: str, domain: str, country: str) -> list[str]:
    country_name = _country_name(country).lower()
    country_code = country.lower()
    soup = BeautifulSoup(content, "html.parser")
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        url = urldefrag(urljoin(base_url, str(anchor["href"])))[0]
        parsed = urlparse(url)
        path = unquote(parsed.path).lower()
        path_parts = {part for part in path.split("/") if part}
        text = anchor.get_text(" ", strip=True).lower()
        if (
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.hostname.removeprefix("www.") == domain
            and ("/location" in path or "/country" in path)
            and (country_name in text or country_name in path or country_code in path_parts)
            and url not in links
        ):
            links.append(url)
    return links


def _search_links(content: bytes, base_url: str, domain: str, country: str, city: str) -> list[str]:
    """Find filtered job-search pages and their pagination links."""
    country_name = _country_name(country)
    if not country_name:
        return []
    soup = BeautifulSoup(content, "html.parser")
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        url = urldefrag(urljoin(base_url, str(anchor["href"])))[0]
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname.removeprefix("www.") != domain:
            continue
        query_text = parsed.query.lower()
        if "/jobs" not in parsed.path or "country" not in query_text:
            continue
        query_values = [value.lower() for values in parse_qs(parsed.query).values() for value in values]
        if not any(country_name.lower() == value or country.lower() == value for value in query_values):
            continue
        if url not in links:
            links.append(url)
    unique_links = list(dict.fromkeys(links))
    return sorted(unique_links, key=_result_page_size, reverse=True)


def _result_page_size(url: str) -> int:
    query = parse_qs(urlparse(url).query)
    for key in ("perPage", "per_page", "limit", "pageSize", "page_size"):
        values = query.get(key, [])
        for value in values:
            try:
                return int(value)
            except ValueError:
                continue
    return 0


def _country_name(code: str) -> str:
    country = pycountry.countries.get(alpha_2=code.upper()) if code else None
    return country.name if country else ""


def _looks_like_js_shell(content: bytes) -> bool:
    soup = BeautifulSoup(content, "html.parser")
    text = soup.get_text(" ", strip=True)
    scripts = len(soup.find_all("script"))
    return len(text) < 300 and scripts >= 2