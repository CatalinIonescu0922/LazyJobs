import ipaddress
import socket
import threading
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from ..config import settings
from ..logging import logger, timed

MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_SITEMAP_BYTES = 20 * 1024 * 1024
MAX_REDIRECTS = 5


@dataclass
class _HostState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_request: float = 0.0
    delay: float = settings.source_request_delay
    retry_after: float = 0.0


@dataclass(frozen=True)
class _CachedResponse:
    result: "FetchResult"
    expires_at: float
    etag: str = ""
    last_modified: str = ""


_host_states: dict[str, _HostState] = {}
_host_states_lock = threading.Lock()
_response_cache: dict[tuple[str, bool], _CachedResponse] = {}
_response_cache_lock = threading.Lock()


class FetchError(Exception):
    pass


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    content: bytes
    content_type: str
    headers: dict[str, str] = field(default_factory=dict)


class SafeFetcher:
    def __init__(self, source_domain: str):
        self.source_domain = _canonical_host(source_domain)
        self._robots: dict[str, RobotFileParser] = {}

    @timed
    def get(self, url: str, *, sitemap: bool = False) -> FetchResult:
        current = _validate_url(url)
        for _ in range(MAX_REDIRECTS + 1):
            host = _canonical_host(urlparse(current).hostname or "")
            if not _same_source_host(host, self.source_domain):
                raise FetchError(f"site redirects to {host}")
            self._check_address(host)
            if not self._allowed(current, host):
                raise FetchError("disallowed by robots.txt")
            cache_key = (current, sitemap)
            cached = _get_cached(cache_key)
            request_headers = {"User-Agent": settings.user_agent}
            if cached:
                if cached.etag:
                    request_headers["If-None-Match"] = cached.etag
                if cached.last_modified:
                    request_headers["If-Modified-Since"] = cached.last_modified
            self._polite_wait(host)
            try:
                with httpx.Client(timeout=20, follow_redirects=False, headers=request_headers) as client:
                    response = client.get(current)
            except httpx.HTTPError as exc:
                _release_host(host)
                raise FetchError(f"source request failed ({type(exc).__name__})") from exc
            if response.status_code in {301, 302, 303, 307, 308}:
                _release_host(host)
                location = response.headers.get("location")
                if not location:
                    raise FetchError("redirect had no location")
                current = _validate_url(urljoin(current, location))
                continue
            if response.status_code == 304 and cached:
                _release_host(host)
                return cached.result
            if response.status_code in {403, 429}:
                _release_host(host)
                _set_retry_after(host, response.headers.get("retry-after", ""))
                raise FetchError(f"blocked ({response.status_code})")
            if response.status_code >= 400:
                _release_host(host)
                raise FetchError(f"source returned {response.status_code}")
            limit = MAX_SITEMAP_BYTES if sitemap else MAX_PAGE_BYTES
            if len(response.content) > limit:
                _release_host(host)
                raise FetchError("response was too large")
            result = FetchResult(current, response.status_code, response.content, response.headers.get("content-type", ""), dict(response.headers))
            _cache_response(cache_key, result)
            _release_host(host)
            logger.info("Fetch completed: host=%s url=%s status=%s bytes=%s", host, current, response.status_code, len(response.content))
            return result
        raise FetchError("too many redirects")

    def robots_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        host = _canonical_host(parsed.hostname or "")
        return self._allowed(url, host)

    def _allowed(self, url: str, host: str) -> bool:
        if host not in self._robots:
            robots_url = f"https://{host}/robots.txt"
            response = self._fetch_robots(robots_url, host)
            if response.status_code in {401, 403, 429}:
                raise FetchError("disallowed by robots.txt")
            parser = RobotFileParser()
            parser.set_url(str(response.url))
            lines = response.text.splitlines() if response.status_code < 400 else []
            parser.parse(lines)
            delay = _crawl_delay(lines)
            _host_state(host).delay = max(settings.source_request_delay, delay or 0)
            self._robots[host] = parser
        return self._robots[host].can_fetch(settings.user_agent, url)

    def _fetch_robots(self, url: str, source_host: str) -> httpx.Response:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            parsed = urlparse(current)
            host = _canonical_host(parsed.hostname or "")
            if parsed.scheme != "https" or not _same_source_host(host, source_host):
                raise FetchError(f"robots.txt redirects to {host}")
            self._check_address(host)
            self._polite_wait(host)
            try:
                with httpx.Client(timeout=15, follow_redirects=False, headers={"User-Agent": settings.user_agent}) as client:
                    response = client.get(current)
            except httpx.HTTPError as exc:
                _release_host(host)
                raise FetchError(f"robots.txt could not be read ({type(exc).__name__})") from exc
            if response.status_code not in {301, 302, 303, 307, 308}:
                _release_host(host)
                return response
            _release_host(host)
            location = response.headers.get("location")
            if not location:
                raise FetchError("robots.txt redirect had no location")
            current = _validate_url(urljoin(current, location))
        raise FetchError("too many robots.txt redirects")

    def _check_address(self, host: str) -> None:
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        except socket.gaierror as exc:
            raise FetchError("source host could not be resolved") from exc
        for address in addresses:
            parsed = ipaddress.ip_address(address)
            if parsed.is_private or parsed.is_loopback or parsed.is_link_local or parsed.is_reserved or parsed.is_multicast or parsed.is_unspecified:
                raise FetchError("source resolves to a blocked address")

    def _polite_wait(self, host: str) -> None:
        state = _host_state(host)
        state.lock.acquire()
        now = time.monotonic()
        delay = max(state.delay, state.retry_after) - (now - state.last_request)
        if delay > 0:
            time.sleep(delay)
        state.retry_after = 0
        state.last_request = time.monotonic()


def _host_state(host: str) -> _HostState:
    with _host_states_lock:
        return _host_states.setdefault(host, _HostState())


def _release_host(host: str) -> None:
    state = _host_state(host)
    if state.lock.locked():
        state.lock.release()


def _set_retry_after(host: str, value: str) -> None:
    state = _host_state(host)
    try:
        state.retry_after = max(0.0, float(value))
    except ValueError:
        try:
            state.retry_after = max(0.0, (parsedate_to_datetime(value).timestamp() - time.time()))
        except (TypeError, ValueError, OverflowError):
            state.retry_after = state.delay * 2


def _crawl_delay(lines: list[str]) -> float:
    for line in lines:
        key, _, value = line.partition(":")
        if key.strip().lower() == "crawl-delay":
            try:
                return max(0.0, float(value.strip()))
            except ValueError:
                return 0.0
    return 0.0


def _get_cached(key: tuple[str, bool]) -> _CachedResponse | None:
    with _response_cache_lock:
        cached = _response_cache.get(key)
        if cached and cached.expires_at > time.monotonic():
            return cached
        if cached:
            _response_cache.pop(key, None)
    return None


def _cache_response(key: tuple[str, bool], result: FetchResult) -> None:
    with _response_cache_lock:
        _response_cache[key] = _CachedResponse(
            result=result,
            expires_at=time.monotonic() + settings.source_cache_ttl_seconds,
            etag=result.headers.get("etag", ""),
            last_modified=result.headers.get("last-modified", ""),
        )


def _validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise FetchError("only https URLs are supported")
    return url


def _canonical_host(host: str) -> str:
    return host.lower().strip().removeprefix("www.")


def _same_source_host(host: str, source: str) -> bool:
    return host == source or host == f"www.{source}".removeprefix("www.")
