import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from urllib.parse import urldefrag, urlparse

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..llm import pick_sitemaps
from ..logging import logger, timed
from ..models import Job, JobSource, utcnow
from ..textnorm import fingerprint
from .extract import extract_jsonld
from .fetch import FetchError, SafeFetcher
from .posting import Posting

MAX_POSTINGS = 100
MAX_JOB_SITEMAPS = 5
MAX_PROBED_SITEMAPS = 4
MAX_PAGE_GROUPS = 2
SAMPLES = 3

Entry = tuple[str, str | None]

# Sitemap files named like these list landing pages, not postings. "by" catches the
# jobs_by_city and jobs_by_employer style that boards use for their landing pages.
_NOT_POSTINGS = ("tag", "user", "compan", "employer", "cit", "domain", "skill", "article", "page", "general", "section", "categor", "predefined", "expired", "blog", "news")
_POSTINGS = ("job", "listing", "vacan", "posting", "position", "opening", "anunt", "locuri")


@timed
def read_sitemap(fetcher: SafeFetcher, url: str) -> tuple[list[str], list[Entry]]:
    content = fetcher.get(url, sitemap=True).content
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise FetchError("sitemap is not valid XML") from exc
    children: list[str] = []
    entries: list[Entry] = []
    for item in root:
        fields = {field.tag.rsplit("}", 1)[-1]: (field.text or "").strip() for field in item}
        if not fields.get("loc"):
            continue
        kind = item.tag.rsplit("}", 1)[-1]
        if kind == "sitemap":
            children.append(fields["loc"])
        elif kind == "url":
            entries.append((fields["loc"], fields.get("lastmod") or None))
    return children, entries


def job_sitemaps(children: list[str]) -> list[str]:
    kept = []
    for url in children:
        words = re.findall(r"[a-z0-9]+", _file_name(url))
        if "by" not in words and not any(word.startswith(_NOT_POSTINGS) for word in words):
            kept.append(url)
    return sorted(kept, key=lambda url: not any(word in _file_name(url) for word in _POSTINGS))


def _file_name(url: str) -> str:
    return urlparse(url).path.rsplit("/", 1)[-1].lower()


def _choose_sitemaps(candidates: list[str], terms: list[str]) -> list[str]:
    if len(candidates) <= MAX_JOB_SITEMAPS:
        return candidates
    # Numbered shards (sitemap-jobs-1.xml, sitemap-jobs-2.xml) say nothing about their
    # content, and the first shard holds the newest postings.
    if len({re.sub(r"\d+", "", url) for url in candidates}) == 1:
        return candidates[:MAX_JOB_SITEMAPS]
    try:
        chosen = pick_sitemaps(candidates, terms, MAX_JOB_SITEMAPS)
    except Exception:
        logger.warning("Sitemap selection failed, reading the first ones", exc_info=True)
        chosen = []
    return chosen or candidates[:MAX_JOB_SITEMAPS]


def _posting_entries(fetcher: SafeFetcher, source: JobSource, terms: list[str]) -> list[Entry]:
    children, entries = read_sitemap(fetcher, source.sitemap_url)
    if entries:
        return entries
    for child in _choose_sitemaps(job_sitemaps(children), terms):
        try:
            entries.extend(read_sitemap(fetcher, child)[1])
        except FetchError as exc:
            logger.warning("Child sitemap skipped: source=%s url=%s reason=%s", source.domain, child, exc)
    return entries


def _rank(entries: list[Entry], terms: list[str]) -> list[Entry]:
    words = {word for term in terms for word in re.findall(r"[a-z0-9]{4,}", term.lower())}
    # Relevance only reorders the freshest window. Some sitemaps carry no real lastmod
    # (RemoteOK says 1970 for every entry) and keep their newest postings first, so
    # ranking all of it by relevance would reach back to expired postings.
    newest_first = sorted(entries, key=lambda entry: entry[1] or "", reverse=True)[: MAX_POSTINGS * 3]
    return sorted(newest_first, key=lambda entry: -len(words & set(re.findall(r"[a-z0-9]+", urlparse(entry[0]).path.lower()))))


@timed
def refresh_source(db: Session, source: JobSource, terms: list[str] | None = None) -> dict[str, int | str]:
    terms = terms or []
    logger.info("Crawl started: source=%s status=%s sitemap=%s", source.domain, source.status, bool(source.sitemap_url))
    fetcher = SafeFetcher(source.domain)
    if source.status != "active":
        validate_source(db, source)
    if source.status != "active":
        return {"source_id": source.id, "status": source.status, "added": 0, "updated": 0, "failed": 0, "reason": source.reason}

    entries = _posting_entries(fetcher, source, terms)
    stored = set(db.scalars(select(Job.external_id).where(Job.source == source.domain)))
    fresh = list(dict.fromkeys(entry for entry in entries if entry[0].startswith(source.posting_prefix) and urldefrag(entry[0])[0] not in stored))
    added = failed = 0
    for url, _ in _rank(fresh, terms)[:MAX_POSTINGS]:
        try:
            posting = extract_jsonld(fetcher.get(url).content, url=url, source=source.domain)
        except FetchError:
            failed += 1
            continue
        if not posting or not posting.title or not posting.description:
            failed += 1
            continue
        try:
            with db.begin_nested():
                _upsert_job(db, posting)
                db.flush()
            added += 1
        except IntegrityError:
            logger.warning("Duplicate job skipped: source=%s external_id=%s", source.domain, url)
    source.last_refreshed_at = utcnow()
    source.posting_count = db.query(Job).filter(Job.source == source.domain).count()
    db.commit()
    logger.info("Crawl completed: source=%s status=%s sitemap_urls=%s new_urls=%s added=%s failed=%s stored=%s", source.domain, source.status, len(entries), len(fresh), added, failed, source.posting_count)
    return {"source_id": source.id, "status": source.status, "added": added, "updated": 0, "failed": failed, "reason": source.reason}


def validate_source(db: Session, source: JobSource) -> None:
    fetcher = SafeFetcher(source.domain)
    try:
        root = source.sitemap_url or discover_sitemap(fetcher, source.domain)
        children, entries = read_sitemap(fetcher, root)
        failure = FetchError("no job sitemap found")
        for batch in _candidate_entries(fetcher, entries, children):
            for group in _page_groups(batch):
                try:
                    prefix = _verified_prefix(fetcher, source.domain, group)
                except FetchError as exc:
                    failure = exc
                    continue
                if prefix is not None:
                    source.sitemap_url = root
                    source.posting_prefix = prefix
                    source.extraction = "jsonld"
                    source.status = "active"
                    source.reason = ""
                    db.commit()
                    return
                failure = FetchError("job pages have no JobPosting data")
        raise failure
    except FetchError as exc:
        source.status = "failed"
        source.reason = str(exc)
        logger.warning("Source validation failed: source=%s reason=%s", source.domain, source.reason)
    db.commit()


def _candidate_entries(fetcher: SafeFetcher, entries: list[Entry], children: list[str]) -> Iterator[list[Entry]]:
    if entries:
        yield entries
        return
    for child in job_sitemaps(children)[:MAX_PROBED_SITEMAPS]:
        try:
            yield read_sitemap(fetcher, child)[1]
        except FetchError as exc:
            logger.warning("Child sitemap skipped: url=%s reason=%s", child, exc)


def _page_groups(entries: list[Entry]) -> list[list[Entry]]:
    # A flat sitemap can hold postings next to company and article pages. Grouping by top
    # folder lets the samples come from one kind of page, job-looking folders first.
    groups: dict[str, list[Entry]] = {}
    for entry in entries:
        segments = urlparse(entry[0]).path.strip("/").split("/")
        if segments != [""]:
            groups.setdefault(segments[0] if len(segments) > 1 else "", []).append(entry)
    usable = [(folder, group) for folder, group in groups.items() if len(group) >= 2]
    usable.sort(key=lambda item: (not any(word in item[0].lower() for word in _POSTINGS), -len(item[1])))
    return [group for _, group in usable[:MAX_PAGE_GROUPS]]


def _verified_prefix(fetcher: SafeFetcher, domain: str, entries: list[Entry]) -> str | None:
    pages = [url for url, _ in entries]
    # Spread the samples: the first few entries of a shard can be unrepresentative.
    samples = pages[:: max(1, (len(pages) - 1) // (SAMPLES - 1))][:SAMPLES]
    good: list[str] = []
    error: FetchError | None = None
    fetched = 0
    for url in samples:
        try:
            content = fetcher.get(url).content
        except FetchError as exc:
            error = exc
            continue
        fetched += 1
        posting = extract_jsonld(content, url=url, source=domain)
        if posting and posting.title and posting.description:
            good.append(url)
    if not fetched and error:
        raise error
    return _common_prefix(good) if len(good) >= 2 else None


def _common_prefix(urls: list[str]) -> str:
    folders = [urlparse(url).path.strip("/").split("/")[:-1] for url in urls]
    shared: list[str] = []
    for parts in zip(*folders):
        if len(set(parts)) != 1:
            break
        shared.append(parts[0])
    if not shared:
        return ""
    first = urlparse(urls[0])
    return f"{first.scheme}://{first.netloc}/{'/'.join(shared)}/"


def discover_sitemap(fetcher: SafeFetcher, domain: str) -> str:
    result = fetcher.get(f"https://{domain}/robots.txt")
    for line in result.content.decode("utf-8", "ignore").splitlines():
        if line.lower().startswith("sitemap:"):
            return line.split(":", 1)[1].strip()
    fallback = f"https://{domain}/sitemap.xml"
    try:
        fetcher.get(fallback, sitemap=True)
    except FetchError as exc:
        raise FetchError(f"no sitemap found ({exc})") from exc
    return fallback


def _upsert_job(db: Session, posting: Posting) -> None:
    canonical_external_id = urldefrag(posting.external_id)[0]
    city = posting.locations[0] if posting.locations else ""
    item = db.scalar(select(Job).where(Job.source == posting.source, Job.external_id == canonical_external_id))
    values = {
        "source": posting.source,
        "external_id": canonical_external_id,
        "url": urldefrag(posting.url)[0],
        "apply_url": posting.apply_url,
        "title": posting.title,
        "company": posting.company,
        "locations": posting.locations,
        "remote": posting.remote,
        "work_mode": posting.work_mode,
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
