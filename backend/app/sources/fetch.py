import ipaddress
import socket
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from ..config import settings

MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_SITEMAP_BYTES = 20 * 1024 * 1024
MAX_REDIRECTS = 5


class FetchError(Exception):
    pass


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    content: bytes
    content_type: str


class SafeFetcher:
    def __init__(self, source_domain: str):
        self.source_domain = _canonical_host(source_domain)
        self._robots: dict[str, RobotFileParser] = {}
        self._last_request: dict[str, float] = {}

    def get(self, url: str, *, sitemap: bool = False) -> FetchResult:
        current = _validate_url(url)
        for _ in range(MAX_REDIRECTS + 1):
            host = _canonical_host(urlparse(current).hostname or "")
            if not _same_source_host(host, self.source_domain):
                raise FetchError("redirect left the source host")
            self._check_address(host)
            if not self._allowed(current, host):
                raise FetchError("disallowed by robots.txt")
            self._polite_wait(host)
            try:
                with httpx.Client(timeout=20, follow_redirects=False, headers={"User-Agent": settings.user_agent}) as client:
                    response = client.get(current)
            except httpx.HTTPError as exc:
                raise FetchError("source request failed") from exc
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise FetchError("redirect had no location")
                current = _validate_url(urljoin(current, location))
                continue
            if response.status_code in {403, 429}:
                raise FetchError(f"blocked ({response.status_code})")
            if response.status_code >= 400:
                raise FetchError(f"source returned {response.status_code}")
            limit = MAX_SITEMAP_BYTES if sitemap else MAX_PAGE_BYTES
            if len(response.content) > limit:
                raise FetchError("response was too large")
            return FetchResult(current, response.status_code, response.content, response.headers.get("content-type", ""))
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
            parser.set_url(response.url)
            parser.parse(response.text.splitlines() if response.status_code < 400 else [])
            self._robots[host] = parser
        return self._robots[host].can_fetch(settings.user_agent, url)

    def _fetch_robots(self, url: str, source_host: str) -> httpx.Response:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            parsed = urlparse(current)
            host = _canonical_host(parsed.hostname or "")
            if parsed.scheme != "https" or not _same_source_host(host, source_host):
                raise FetchError("robots.txt redirect left the source host")
            self._check_address(host)
            self._polite_wait(host)
            try:
                with httpx.Client(timeout=15, follow_redirects=False, headers={"User-Agent": settings.user_agent}) as client:
                    response = client.get(current)
            except httpx.HTTPError as exc:
                raise FetchError("robots.txt could not be read") from exc
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
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
        now = time.monotonic()
        delay = settings.source_request_delay - (now - self._last_request.get(host, 0))
        if delay > 0:
            time.sleep(delay)
        self._last_request[host] = time.monotonic()


def _validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise FetchError("only https URLs are supported")
    return url


def _canonical_host(host: str) -> str:
    return host.lower().strip().removeprefix("www.")


def _same_source_host(host: str, source: str) -> bool:
    return host == source or host == f"www.{source}".removeprefix("www.")
