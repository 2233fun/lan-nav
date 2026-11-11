from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.checker import LinkChecker

from .helpers import make_group, make_link


class _CheckerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hits: Counter[str] = Counter()
        self.hits_lock = threading.Lock()

    def record_hit(self, path: str) -> None:
        with self.hits_lock:
            self.hits[path] += 1

    def hit_count(self) -> int:
        with self.hits_lock:
            return sum(self.hits.values())


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        self.server.record_hit(self.path)

        delay = 0.0
        if parsed.path in {"/slow", "/delay", "/hang"}:
            default = "1.1" if parsed.path == "/slow" else "0.25"
            delay = float(query.get("delay", [default])[0])
        if parsed.path == "/hang":
            delay = max(delay, 3.0)
        if delay:
            time.sleep(delay)

        if parsed.path in {"/redirect", "/redirect-loop"}:
            self.send_response(302)
            self.send_header(
                "Location", "/ok?redirected=1" if parsed.path == "/redirect" else self.path
            )
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        status = 200
        if parsed.path == "/500":
            status = 500
        elif parsed.path == "/404":
            status = 404
        body = f"status={status}".encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


@pytest.fixture()
def local_http_server():
    server = _CheckerHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield server, f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _closed_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_normal_slow_http_error_redirect_and_cache(
    client: TestClient,
    local_http_server,
):
    server, base = local_http_server
    group = make_group(client, "检测目标")
    ok = make_link(client, group["id"], "正常", f"{base}/ok?case=ok")
    slow = make_link(client, group["id"], "慢", f"{base}/slow?case=slow")
    fivexx = make_link(client, group["id"], "500", f"{base}/500")
    fourxx = make_link(client, group["id"], "404", f"{base}/404")
    redirect = make_link(client, group["id"], "跳转", f"{base}/redirect")
    redirect_loop = make_link(client, group["id"], "重定向过多", f"{base}/redirect-loop")
    ids = [ok["id"], slow["id"], fivexx["id"], fourxx["id"], redirect["id"], redirect_loop["id"]]

    started = time.perf_counter()
    response = client.post("/api/check-links", json={"ids": ids})
    elapsed = time.perf_counter() - started
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["count"] == 6
    assert data["cached"] == 0
    by_id = {result["id"]: result for result in data["results"]}

    assert by_id[ok["id"]]["status"] == "ok"
    assert by_id[ok["id"]]["ok"] is True
    assert by_id[ok["id"]]["http_status"] == 200
    assert by_id[ok["id"]]["reason"] is None
    assert by_id[ok["id"]]["latency_ms"] >= 0

    assert by_id[slow["id"]]["status"] == "slow"
    assert by_id[slow["id"]]["ok"] is True
    assert by_id[slow["id"]]["latency_ms"] >= 700
    assert elapsed < 4.0

    assert by_id[fivexx["id"]]["status"] == "error"
    assert by_id[fivexx["id"]]["ok"] is False
    assert by_id[fivexx["id"]]["reachable"] is True
    assert by_id[fivexx["id"]]["http_status"] == 500
    assert "500" in by_id[fivexx["id"]]["reason"]

    assert by_id[fourxx["id"]]["status"] == "error"
    assert by_id[fourxx["id"]]["ok"] is False
    assert by_id[fourxx["id"]]["reachable"] is True
    assert by_id[fourxx["id"]]["http_status"] == 404
    assert "可达但异常" in by_id[fourxx["id"]]["reason"]

    assert by_id[redirect["id"]]["status"] == "ok"
    assert by_id[redirect["id"]]["http_status"] == 200

    assert by_id[redirect_loop["id"]]["status"] == "error"
    assert by_id[redirect_loop["id"]]["ok"] is False
    assert "重定向过多" in by_id[redirect_loop["id"]]["reason"]

    hits_after_first = server.hit_count()
    started = time.perf_counter()
    cached_response = client.post("/api/check-links", json={"ids": ids})
    cached_elapsed = time.perf_counter() - started
    assert cached_response.status_code == 200
    cached_data = cached_response.json()
    assert cached_data["cached"] == 6
    assert all(result["cached"] is True for result in cached_data["results"])
    assert server.hit_count() == hits_after_first
    assert cached_elapsed < elapsed


def test_refused_dns_timeout_and_illegal_scheme(client: TestClient, app, local_http_server):
    _server, base = local_http_server
    group = make_group(client, "异常目标")
    refused = make_link(client, group["id"], "拒绝", f"http://127.0.0.1:{_closed_port()}/")
    dns = make_link(client, group["id"], "DNS", "http://lan-nav-check.invalid/")

    response = client.post("/api/check-links", json={"ids": [refused["id"], dns["id"]]})
    assert response.status_code == 200, response.text
    by_id = {result["id"]: result for result in response.json()["results"]}
    assert by_id[refused["id"]]["status"] == "error"
    assert by_id[refused["id"]]["reachable"] is False
    assert by_id[refused["id"]]["reason"] == "连接被拒绝"
    assert by_id[dns["id"]]["status"] == "error"
    assert by_id[dns["id"]]["reason"] == "DNS 解析失败"

    # 用缩短超时的 checker 验证超时路径，不拖慢测试。
    app.state.link_checker = LinkChecker(attempt_timeout=0.25, total_timeout=0.3)
    timeout_link = make_link(client, group["id"], "超时", f"{base}/hang")
    response = client.post("/api/check-links", json={"ids": [timeout_link["id"]]})
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "error"
    assert result["reason"] == "请求超时"

    checker = LinkChecker(attempt_timeout=0.25, total_timeout=0.3)
    direct = asyncio.run(checker.check([{"id": 99, "url": "ftp://example.com"}]))[0]
    assert direct["status"] == "error"
    assert direct["reachable"] is False
    assert "http/https" in direct["reason"]


def test_batch_limit_missing_and_empty_input(client: TestClient):
    too_many = client.post("/api/check-links", json={"ids": list(range(1, 52))})
    assert too_many.status_code == 422
    assert "请求参数不合法" in too_many.json()["detail"]

    empty = client.post("/api/check-links", json={"ids": []})
    assert empty.status_code == 422

    missing = client.post("/api/check-links", json={"ids": [999999]})
    assert missing.status_code == 404
    assert "链接不存在" in missing.json()["detail"]


def test_concurrency_is_bounded_not_serial(client: TestClient, local_http_server):
    _server, base = local_http_server
    group = make_group(client, "并发目标")
    ids = [
        make_link(client, group["id"], f"并发 {index}", f"{base}/delay?delay=0.35&i={index}")["id"]
        for index in range(8)
    ]

    started = time.perf_counter()
    response = client.post("/api/check-links", json={"ids": ids})
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    results = response.json()["results"]
    assert all(item["ok"] for item in results), results
    # 串行至少约 2.8 秒；服务端有界并发下应显著更快。
    assert elapsed < 1.8, results


def test_check_does_not_modify_database(client: TestClient, local_http_server):
    _server, base = local_http_server
    group = make_group(client, "不写库")
    link = make_link(client, group["id"], "只检测", f"{base}/ok?db=1")
    before = client.get("/api/export").json()

    response = client.post("/api/check-links", json={"ids": [link["id"]]})
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "ok"

    after = client.get("/api/export").json()
    assert after["groups"] == before["groups"]
    assert after["links"] == before["links"]


def test_cache_ttl_expiry(local_http_server):
    server, base = local_http_server
    checker = LinkChecker(ttl_seconds=0.15, attempt_timeout=1.0, total_timeout=1.2)
    url = f"{base}/ok?ttl=expire"

    first = asyncio.run(checker.check([{"id": 1, "url": url}]))[0]
    assert first["cached"] is False
    hits = server.hit_count()
    second = asyncio.run(checker.check([{"id": 1, "url": url}]))[0]
    assert second["cached"] is True
    assert server.hit_count() == hits
    time.sleep(0.2)
    third = asyncio.run(checker.check([{"id": 1, "url": url}]))[0]
    assert third["cached"] is False
    assert server.hit_count() == hits + 1
