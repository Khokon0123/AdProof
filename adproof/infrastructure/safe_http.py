"""Bounded, SSRF-resistant fetching of the user-supplied page and image.

Rules: HTTPS only, no credentials in URLs, default port only, host allowlist by
default, every resolved address must be public, at most 3 redirects (each one
re-validated), streamed byte limits, content-type checks, deadline enforced.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx

MAX_REDIRECTS = 3
LIMITS = {"image": 8 * 1024 * 1024, "html": 2 * 1024 * 1024}
ALLOWED_TYPES = {
    "image": ("image/png", "image/jpeg"),
    # raw.githubusercontent.com serves .html as text/plain; we parse it as HTML/text either way.
    "html": ("text/html", "text/plain", "application/xhtml+xml"),
}


class FetchError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    content_type: str
    body: bytes
    fetched_at: float


class Fetcher(Protocol):
    async def fetch(self, url: str, kind: str, deadline: float) -> FetchResult: ...


def _is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
                or addr.is_reserved or addr.is_unspecified or (addr.version == 6 and addr.ipv4_mapped
                and not _is_public(str(addr.ipv4_mapped))))


def validate_url(url: str, allowed_hosts: tuple[str, ...], allow_public: bool) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise FetchError("UNSAFE_URL", "Only https:// URLs are accepted.")
    if parts.username or parts.password:
        raise FetchError("UNSAFE_URL", "URLs with credentials are not accepted.")
    if parts.port not in (None, 443):
        raise FetchError("UNSAFE_URL", "Only the default HTTPS port is accepted.")
    host = (parts.hostname or "").lower()
    if not host:
        raise FetchError("UNSAFE_URL", "URL has no host.")
    try:  # literal IPs are never allowed
        ipaddress.ip_address(host)
        raise FetchError("UNSAFE_URL", "IP-address URLs are not accepted.")
    except ValueError:
        pass
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".internal"):
        raise FetchError("UNSAFE_URL", "Local hosts are not accepted.")
    if not allow_public and host not in allowed_hosts:
        raise FetchError("HOST_NOT_ALLOWED", f"Host '{host}' is not on the allowlist (ADPROOF_ALLOWED_HOSTS).")
    return host


async def assert_resolves_public(host: str) -> None:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError("DNS_FAILED", f"Could not resolve {host}.", retryable=True) from exc
    ips = {i[4][0] for i in infos}
    if not ips or not all(_is_public(ip) for ip in ips):
        raise FetchError("UNSAFE_URL", f"{host} resolves to a non-public address.")


class SafeFetcher:
    def __init__(self, allowed_hosts: tuple[str, ...], allow_public: bool = False):
        self.allowed_hosts, self.allow_public = allowed_hosts, allow_public

    async def fetch(self, url: str, kind: str, deadline: float) -> FetchResult:
        limit, types = LIMITS[kind], ALLOWED_TYPES[kind]
        current = url
        async with httpx.AsyncClient(follow_redirects=False, headers={"Accept-Encoding": "identity",
                                     "User-Agent": "AdProof/1.0 (hackathon prototype)"}) as client:
            for _ in range(MAX_REDIRECTS + 1):
                host = validate_url(current, self.allowed_hosts, self.allow_public)
                await assert_resolves_public(host)
                remaining = deadline - time.time()
                if remaining <= 0.5:
                    raise FetchError("DEADLINE_EXCEEDED", "No time left to fetch the source.")
                try:
                    async with client.stream("GET", current, timeout=min(10.0, remaining)) as resp:
                        if resp.status_code in (301, 302, 303, 307, 308):
                            current = urljoin(current, resp.headers.get("location", ""))
                            continue
                        if resp.status_code >= 400:
                            raise FetchError("HTTP_ERROR", f"Source returned HTTP {resp.status_code}.",
                                             retryable=resp.status_code >= 500)
                        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                        if ctype not in types:
                            raise FetchError("UNSUPPORTED_TYPE", f"Unsupported content type '{ctype}' for {kind}.")
                        if resp.headers.get("content-encoding", "identity") not in ("identity", ""):
                            raise FetchError("UNSUPPORTED_ENCODING", "Compressed responses are not accepted.")
                        declared = resp.headers.get("content-length")
                        if declared and declared.isdigit() and int(declared) > limit:
                            raise FetchError("TOO_LARGE", f"Source is larger than {limit} bytes.")
                        chunks, total = [], 0
                        async for chunk in resp.aiter_bytes():
                            total += len(chunk)
                            if total > limit:
                                raise FetchError("TOO_LARGE", f"Source is larger than {limit} bytes.")
                            chunks.append(chunk)
                        return FetchResult(url, current, ctype, b"".join(chunks), time.time())
                except httpx.TimeoutException as exc:
                    raise FetchError("TIMEOUT", "The source took too long to respond.", retryable=True) from exc
                except httpx.HTTPError as exc:
                    raise FetchError("NETWORK_ERROR", f"Network error: {type(exc).__name__}.", retryable=True) from exc
        raise FetchError("TOO_MANY_REDIRECTS", "More than 3 redirects.")


class StaticFetcher:
    """Test/mock fetcher: serves bytes from a dict {url: (content_type, bytes)}. Never used in LIVE."""

    def __init__(self, table: dict[str, tuple[str, bytes]]):
        self.table = table
        self.calls: list[str] = []

    async def fetch(self, url: str, kind: str, deadline: float) -> FetchResult:
        self.calls.append(url)
        if url not in self.table:
            raise FetchError("HTTP_ERROR", "Source returned HTTP 404.")
        ctype, body = self.table[url]
        if ctype not in ALLOWED_TYPES[kind]:
            raise FetchError("UNSUPPORTED_TYPE", f"Unsupported content type '{ctype}' for {kind}.")
        if len(body) > LIMITS[kind]:
            raise FetchError("TOO_LARGE", f"Source is larger than {LIMITS[kind]} bytes.")
        return FetchResult(url, url, ctype, body, time.time())
