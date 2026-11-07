from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import BeautifulSoup
import pycountry
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..logging import logger, timed
from ..models import Job, JobSource, utcnow
from .crawl import _upsert_job
from .extract import extract_jsonld
from .fetch import FetchError, SafeFetcher

MAX_CAREER_LINKS = 40
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
            for child in _discovery_links(result.content, result.url, source.domain, country, city):
                if child not in seen_pages and child not in queued and len(queued) < MAX_CAREER_LINKS * 2:
                    queued.append(child)
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

        if not added:
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
        url = urljoin(base_url, str(anchor["href"]))
        parsed = urlparse(url)
        text = f"{anchor.get_text(' ', strip=True)} {url}".lower()
        path = parsed.path.rstrip("/").lower()
        collection_route = path in {"/jobs", "/careers", "/career", "/locations", "/location", "/country"}
        if parsed.scheme == "https" and parsed.hostname and parsed.hostname.removeprefix("www.") == domain and not collection_route and any(word in text for word in CAREER_WORDS):
            if url not in links:
                links.append(url)
    return links


@timed
def _discovery_links(content: bytes, base_url: str, domain: str, country: str, city: str) -> list[str]:
    return list(dict.fromkeys(
        _career_links(content, base_url, domain)
        + _location_links(content, base_url, domain, country)
        + _search_links(content, base_url, domain, country, city)
    ))


def _location_links(content: bytes, base_url: str, domain: str, country: str) -> list[str]:
    country_name = _country_name(country).lower()
    country_code = country.lower()
    soup = BeautifulSoup(content, "html.parser")
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        url = urljoin(base_url, str(anchor["href"]))
        parsed = urlparse(url)
        path = unquote(parsed.path).lower()
        text = f"{anchor.get_text(' ', strip=True)} {path}".lower()
        if (
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.hostname.removeprefix("www.") == domain
            and ("/location" in path or "/country" in path)
            and (country_name in text or country_code in text)
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
        url = urljoin(base_url, str(anchor["href"]))
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname.removeprefix("www.") != domain:
            continue
        query_text = parsed.query.lower()
        if "/jobs" not in parsed.path or "country" not in query_text:
            continue
        if country_name.lower() not in query_text and country.lower() not in query_text:
            continue
        if url not in links:
            links.append(url)
    return list(dict.fromkeys(links))


def _country_name(code: str) -> str:
    country = pycountry.countries.get(alpha_2=code.upper()) if code else None
    return country.name if country else ""


def _looks_like_js_shell(content: bytes) -> bool:
    soup = BeautifulSoup(content, "html.parser")
    text = soup.get_text(" ", strip=True)
    scripts = len(soup.find_all("script"))
    return len(text) < 300 and scripts >= 2