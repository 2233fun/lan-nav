"""链接连通性检测：限并发、带 TTL 缓存，结果不写入数据库。"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx

CACHE_TTL_SECONDS = 60.0
MAX_CONCURRENCY = 16
ATTEMPT_TIMEOUT_SECONDS = 2.5
TOTAL_TIMEOUT_SECONDS = 3.0
SLOW_THRESHOLD_MS = 800
MAX_REDIRECTS = 3
CACHE_MAX_ENTRIES = 4096
USER_AGENT = "LanNav/1.0 (LAN connectivity check)"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _error_text(exc: BaseException) -> str:
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(parts) < 6:
        seen.add(id(current))
        parts.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__
    return " | ".join(parts).lower()


def _is_certificate_error(exc: BaseException) -> bool:
    text = _error_text(exc)
    markers = (
        "certificate verify failed",
        "certificateverifyerror",
        "ssl: certificate",
        "unable to get local issuer",
        "certificate has expired",
        "hostname mismatch",
        "unknown ca",
        "self-signed certificate",
    )
    return any(marker in text for marker in markers)


def _describe_error(exc: BaseException) -> str:
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return "请求超时"
    if isinstance(exc, httpx.TooManyRedirects):
        return "重定向过多（最多 3 次）"
    if isinstance(exc, (httpx.UnsupportedProtocol, httpx.InvalidURL)):
        return "网址不合法"
    if _is_certificate_error(exc):
        return "证书校验失败"
    text = _error_text(exc)
    if any(marker in text for marker in (
        "name or service not known",
        "nodename nor servname",
        "temporary failure in name resolution",
        "getaddrinfo failed",
        "no address associated with hostname",
        "name resolution",
    )):
        return "DNS 解析失败"
    if "connection refused" in text or "errno 111" in text:
        return "连接被拒绝"
    if "network is unreachable" in text or "errno 113" in text:
        return "网络不可达"
    if "connection reset" in text or "errno 104" in text:
        return "连接被重置"
    if "timed out" in text or "timeout" in text:
        return "请求超时"
    return "连接失败"


class LinkChecker:
    """有界并发的 HTTP 可达性检查器。

    每个链接最多占用 TOTAL_TIMEOUT_SECONDS 秒；主请求使用证书校验，
    证书错误时使用剩余时间忽略证书重试一次。结果按 URL 缓存 TTL 秒。
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        max_concurrency: int = MAX_CONCURRENCY,
        slow_threshold_ms: int = SLOW_THRESHOLD_MS,
        attempt_timeout: float = ATTEMPT_TIMEOUT_SECONDS,
        total_timeout: float = TOTAL_TIMEOUT_SECONDS,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_concurrency = max(1, max_concurrency)
        self.slow_threshold_ms = slow_threshold_ms
        self.attempt_timeout = attempt_timeout
        self.total_timeout = max(attempt_timeout, total_timeout)
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def clear_cache(self) -> None:
        self._cache.clear()

    async def check(self, links: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique_urls: list[str] = []
        seen_urls: set[str] = set()
        for link in links:
            url = str(link.get("url", ""))
            if url not in seen_urls:
                seen_urls.add(url)
                unique_urls.append(url)

        now = time.monotonic()
        cached: dict[str, dict[str, Any]] = {}
        pending_urls: list[str] = []
        for url in unique_urls:
            entry = self._cache.get(url)
            if entry is not None and entry[0] > now:
                cached[url] = entry[1]
            else:
                self._cache.pop(url, None)
                pending_urls.append(url)

        fresh: dict[str, dict[str, Any]] = {}
        if pending_urls:
            fresh = await self._check_many(pending_urls)
            expires_at = time.monotonic() + self.ttl_seconds
            for url, result in fresh.items():
                self._cache[url] = (expires_at, result)
            self._prune_cache()

        results: list[dict[str, Any]] = []
        for link in links:
            url = str(link.get("url", ""))
            payload = fresh.get(url) or cached.get(url)
            if payload is None:
                payload = self._error_payload("检测失败", 0)
            item = dict(payload)
            item["id"] = link.get("id")
            item["cached"] = url in cached
            results.append(item)
        return results

    async def _check_many(self, urls: list[str]) -> dict[str, dict[str, Any]]:
        semaphore = asyncio.Semaphore(self.max_concurrency)
        timeout = httpx.Timeout(self.attempt_timeout)
        limits = httpx.Limits(
            max_connections=self.max_concurrency,
            max_keepalive_connections=min(10, self.max_concurrency),
        )
        common = {
            "timeout": timeout,
            "limits": limits,
            "follow_redirects": True,
            "max_redirects": MAX_REDIRECTS,
            "trust_env": False,
            "headers": {"User-Agent": USER_AGENT, "Accept": "*/*"},
        }
        async with httpx.AsyncClient(**common) as client:
            async with httpx.AsyncClient(verify=False, **common) as insecure_client:
                async def run_one(url: str) -> tuple[str, dict[str, Any]]:
                    async with semaphore:
                        return url, await self._check_url(url, client, insecure_client)

                pairs = await asyncio.gather(*(run_one(url) for url in urls))
        return dict(pairs)

    async def _check_url(
        self,
        url: str,
        client: httpx.AsyncClient,
        insecure_client: httpx.AsyncClient,
    ) -> dict[str, Any]:
        try:
            parsed = urlsplit(url)
        except ValueError:
            return self._error_payload("网址不合法", 0)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return self._error_payload("仅支持 http/https 网址", 0)

        started = time.perf_counter()
        status, _latency, error = await self._fetch_once(client, url, self.attempt_timeout)
        certificate_note = False

        if error is not None and _is_certificate_error(error):
            elapsed = time.perf_counter() - started
            remaining = self.total_timeout - elapsed
            if remaining > 0.15:
                status, _latency, error = await self._fetch_once(
                    insecure_client, url, min(self.attempt_timeout, remaining)
                )
                certificate_note = error is None
                if error is not None and not _is_certificate_error(error):
                    certificate_note = False

        latency_ms = max(0, int(round((time.perf_counter() - started) * 1000)))
        if error is not None:
            reason = _describe_error(error)
            if _is_certificate_error(error):
                reason = "证书校验失败"
            return self._error_payload(reason, latency_ms)

        assert status is not None
        return self._http_payload(status, latency_ms, certificate_note=certificate_note)

    async def _fetch_once(
        self, client: httpx.AsyncClient, url: str, timeout: float
    ) -> tuple[int | None, int, BaseException | None]:
        started = time.perf_counter()
        try:
            async def request() -> int:
                async with client.stream("GET", url, timeout=timeout) as response:
                    return response.status_code

            status = await asyncio.wait_for(request(), timeout=timeout)
            latency_ms = max(0, int(round((time.perf_counter() - started) * 1000)))
            return status, latency_ms, None
        except Exception as exc:  # noqa: BLE001 - 所有网络异常都要变成结构化结果
            latency_ms = max(0, int(round((time.perf_counter() - started) * 1000)))
            return None, latency_ms, exc

    def _http_payload(
        self, http_status: int, latency_ms: int, *, certificate_note: bool = False
    ) -> dict[str, Any]:
        base: dict[str, Any] = {
            "ok": False,
            "status": "error",
            "reachable": True,
            "latency_ms": latency_ms,
            "http_status": http_status,
            "reason": None,
            "checked_at": _iso_now(),
            "tls_insecure": certificate_note,
        }
        if 400 <= http_status <= 499:
            base["reason"] = f"HTTP {http_status}（可达但异常）"
            return base
        if 500 <= http_status <= 599:
            base["reason"] = f"HTTP {http_status}（服务端错误）"
            return base
        if http_status >= 600 or http_status < 100:
            base["reason"] = f"HTTP {http_status}（异常状态码）"
            return base

        base["ok"] = True
        base["status"] = "slow" if latency_ms >= self.slow_threshold_ms else "ok"
        if certificate_note:
            base["reason"] = "证书校验未通过，已降级重试"
        return base

    @staticmethod
    def _error_payload(reason: str, latency_ms: int) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "error",
            "reachable": False,
            "latency_ms": latency_ms,
            "http_status": None,
            "reason": reason,
            "checked_at": _iso_now(),
            "tls_insecure": False,
        }

    def _prune_cache(self) -> None:
        if len(self._cache) <= CACHE_MAX_ENTRIES:
            return
        now = time.monotonic()
        for url, (expires_at, _result) in list(self._cache.items()):
            if expires_at <= now:
                self._cache.pop(url, None)
        if len(self._cache) > CACHE_MAX_ENTRIES:
            overflow = len(self._cache) - CACHE_MAX_ENTRIES
            oldest = sorted(self._cache.items(), key=lambda item: item[1][0])[:overflow]
            for url, _entry in oldest:
                self._cache.pop(url, None)
