import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Job, JobSource, utcnow
from ..textnorm import fingerprint
from .extract import extract_jsonld
from .fetch import FetchError, SafeFetcher
from .posting import Posting

MAX_POSTINGS = 100


def sitemap_urls(fetcher: SafeFetcher, sitemap_url: str) -> list[tuple[str, str | None]]:
    result = fetcher.get(sitemap_url, sitemap=True)
    root = ET.fromstring(result.content)
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    tags = {child.tag.rsplit("}", 1)[-1] for child in root}
    urls: list[tuple[str, str | None]] = []
    if "sitemap" in tags:
        children = [child.findtext("s:loc", namespaces=namespace) for child in root.findall("s:sitemap", namespace)]
        for child_url in children[:20]:
            if child_url:
                urls.extend(sitemap_urls(fetcher, child_url))
    else:
        for item in root.findall("s:url", namespace):
            loc = item.findtext("s:loc", namespaces=namespace)
            lastmod = item.findtext("s:lastmod", namespaces=namespace)
            if loc:
                urls.append((loc, lastmod))
    return urls


def refresh_source(db: Session, source: JobSource) -> dict[str, int | str]:
    fetcher = SafeFetcher(source.domain)
    if source.status != "active":
        validate_source(db, source)
    if source.status != "active":
        return {"source_id": source.id, "status": source.status, "added": 0, "updated": 0, "failed": 0, "reason": source.reason}

    urls = sitemap_urls(fetcher, source.sitemap_url)
    urls.sort(key=lambda item: item[1] or "", reverse=True)
    added = updated = failed = 0
    for url, _ in urls[:MAX_POSTINGS]:
        if source.posting_prefix and not url.startswith(source.posting_prefix):
            continue
        existing = db.scalar(select(Job).where(Job.source == source.domain, Job.external_id == url))
        if existing:
            continue
        try:
            posting = extract_jsonld(fetcher.get(url).content, url=url, source=source.domain)
        except (FetchError, ET.ParseError):
            failed += 1
            continue
        if not posting or not posting.title or not posting.description:
            failed += 1
            continue
        _upsert_job(db, posting)
        added += 1
    source.last_refreshed_at = utcnow()
    source.posting_count = db.query(Job).filter(Job.source == source.domain).count()
    db.commit()
    return {"source_id": source.id, "status": source.status, "added": added, "updated": updated, "failed": failed, "reason": source.reason}


def validate_source(db: Session, source: JobSource) -> None:
    fetcher = SafeFetcher(source.domain)
    try:
        sitemap = source.sitemap_url or discover_sitemap(fetcher, source.domain)
        if not sitemap:
            raise FetchError("no sitemap")
        urls = sitemap_urls(fetcher, sitemap)
        samples = urls[:3]
        if not samples:
            raise FetchError("no postings found")
        successful = 0
        for url, _ in samples:
            posting = extract_jsonld(fetcher.get(url).content, url=url, source=source.domain)
            if posting and posting.title and posting.description:
                successful += 1
        if successful < 2:
            raise FetchError("no postings found")
        source.sitemap_url = sitemap
        source.extraction = "jsonld"
        source.status = "active"
        source.reason = ""
    except (FetchError, ET.ParseError) as exc:
        source.status = "failed"
        source.reason = str(exc)
    db.commit()


def discover_sitemap(fetcher: SafeFetcher, domain: str) -> str:
    result = fetcher.get(f"https://{domain}/robots.txt")
    for line in result.content.decode("utf-8", "ignore").splitlines():
        if line.lower().startswith("sitemap:"):
            return line.split(":", 1)[1].strip()
    fallback = f"https://{domain}/sitemap.xml"
    fetcher.get(fallback, sitemap=True)
    return fallback


def _upsert_job(db: Session, posting: Posting) -> None:
    city = posting.locations[0] if posting.locations else ""
    item = db.scalar(select(Job).where(Job.source == posting.source, Job.external_id == posting.external_id))
    values = {
        "source": posting.source,
        "external_id": posting.external_id,
        "url": posting.url,
        "apply_url": posting.apply_url,
        "title": posting.title,
        "company": posting.company,
        "locations": posting.locations,
        "remote": posting.remote,
        "eligible_countries": posting.eligible_countries,
        "employment_type": posting.employment_type,
        "description": posting.description,
        "posted_at": posting.posted_at,
        "expires_at": posting.expires_at,
        "salary_min": posting.salary_min,
        "salary_max": posting.salary_max,
        "salary_currency": posting.salary_currency,
        "fingerprint": fingerprint(posting.company, posting.title, city),
    }
    if item is None:
        db.add(Job(**values))
    else:
        for key, value in values.items():
            if key not in {"source", "external_id", "first_seen_at"}:
                setattr(item, key, value)
