from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..logging import logger
from ..models import Job, JobSource, utcnow
from .crawl import _upsert_job
from .extract import extract_jsonld
from .fetch import FetchError, SafeFetcher

MAX_CAREER_LINKS = 40
CAREER_WORDS = ("career", "careers", "job", "jobs", "opening", "openings", "position", "vacancy", "work-with-us")


def refresh_career_source(db: Session, source: JobSource) -> dict[str, int | str]:
    source_url = source.source_url or f"https://{source.domain}"
    fetcher = SafeFetcher(source.domain)
    try:
        root = fetcher.get(source_url)
        pages = [(root.url, root.content)]
        for link in _career_links(root.content, root.url, source.domain)[:MAX_CAREER_LINKS]:
            try:
                result = fetcher.get(link)
            except FetchError:
                continue
            pages.append((result.url, result.content))

        added = 0
        seen_urls: set[str] = set()
        for page_url, content in pages:
            posting = extract_jsonld(content, url=page_url, source=source.domain)
            if not posting or not posting.title or not posting.description or posting.external_id in seen_urls:
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
        if parsed.scheme == "https" and parsed.hostname and parsed.hostname.removeprefix("www.") == domain and any(word in text for word in CAREER_WORDS):
            if url not in links:
                links.append(url)
    return links


def _looks_like_js_shell(content: bytes) -> bool:
    soup = BeautifulSoup(content, "html.parser")
    text = soup.get_text(" ", strip=True)
    scripts = len(soup.find_all("script"))
    return len(text) < 300 and scripts >= 2