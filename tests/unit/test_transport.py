import socket
import threading
from collections import Counter
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests
from urllib3.connection import HTTPConnection
from urllib3.exceptions import NewConnectionError

from dotmatics_api import Browser, Inventory


@contextmanager
def server():
    calls = Counter()

    class Handler(BaseHTTPRequestHandler):
        def handle_request(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            key = (self.command, self.path)
            calls[key] += 1
            if "status" in self.path:
                self.send_response(503 if "retry-after" in self.path else 500)
                self.send_header("Retry-After", "0")
                self.end_headers()
                return
            if calls[key] == 1:
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

        do_GET = handle_request
        do_POST = handle_request
        do_PUT = handle_request
        do_DELETE = handle_request

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join()


def client(cls, url, **kwargs):
    options = {"lazy": True} if cls is Browser else {}
    value = cls(
        user="demo",
        token="test-token",
        dotmatics_instance=url,
        connect_retries=1,
        read_retries=1,
        **options,
        **kwargs,
    )
    value._session.trust_env = False
    value._idempotent_session.trust_env = False
    return value


@pytest.mark.transport
@pytest.mark.parametrize("cls", [Browser, Inventory])
def test_get_retries_real_dropped_connection(cls):
    with server() as (url, calls), client(cls, url) as value:
        assert value._get("retry") == {"ok": True}
        assert sum(calls.values()) == 2


@pytest.mark.transport
def test_read_only_post_retries_real_dropped_connection():
    with server() as (url, calls), client(Browser, url) as value:
        assert value._post("query/test", {}, data={"data": "[]"}, idempotent=True) == {
            "ok": True
        }
        assert sum(calls.values()) == 2


@pytest.mark.transport
@pytest.mark.parametrize("cls", [Browser, Inventory])
@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_ambiguous_writes_are_not_replayed(cls, method):
    with server() as (url, calls), client(cls, url) as value:
        with pytest.raises(requests.ConnectionError):
            getattr(value, "_" + method)("write")
        assert sum(calls.values()) == 1


@pytest.mark.transport
@pytest.mark.parametrize("cls", [Browser, Inventory])
@pytest.mark.parametrize("endpoint", ["status", "status-retry-after"])
def test_http_status_not_retried(cls, endpoint):
    with server() as (url, calls), client(cls, url) as value:
        with pytest.raises(ValueError):
            value._get(endpoint)
        assert sum(calls.values()) == 1


@pytest.mark.transport
def test_connect_attempts_are_bounded_even_for_writes(monkeypatch):
    attempts = []

    def fail(connection):
        attempts.append(connection)
        raise NewConnectionError(connection, "controlled pre-send connect failure")

    monkeypatch.setattr(HTTPConnection, "connect", fail)
    with client(Inventory, "http://127.0.0.1:1") as value:
        with pytest.raises(requests.ConnectionError):
            value._post("write")
    assert len(attempts) == 2


@pytest.mark.parametrize("cls", [Browser, Inventory])
@pytest.mark.parametrize(
    "url",
    [
        "https://",
        "https://u:p@demo.example.org",
        "https://demo.example.org:99999",
        "https://demo.example.org/path",
        "https://demo.example.org?q=1",
        "https://demo.example.org#x",
        "https://demo .example.org",
    ],
)
def test_rejects_invalid_urls(cls, url):
    with pytest.raises(ValueError):
        client(cls, url)


@pytest.mark.parametrize("cls", [Browser, Inventory])
def test_instance_required_and_custom_url_normalized(cls):
    with pytest.raises(TypeError):
        cls(user="demo", token="test-token")
    with client(cls, "https://custom.example.org:8443/") as value:
        assert value._make_request_path("version").startswith(
            "https://custom.example.org:8443/"
        )
        assert "//" not in value.api_url.split("://", 1)[1]


@pytest.mark.parametrize("cls", [Browser, Inventory])
def test_failed_authentication_closes_sessions(cls, monkeypatch):
    from unittest.mock import Mock

    from dotmatics_api.base import DotmaticsClient

    sessions = [Mock(), Mock()]
    monkeypatch.setattr(
        DotmaticsClient, "_build_retry_session", lambda *args, **kwargs: sessions.pop(0)
    )
    created = sessions.copy()

    def fail(*args, **kwargs):
        raise ValueError("authentication failed")

    monkeypatch.setattr(cls, "_authenticate", fail)
    with pytest.raises(ValueError, match="authentication failed"):
        cls(
            user="demo",
            password="test-only",
            dotmatics_instance="https://demo.example.org",
        )
    for session in created:
        session.close.assert_called_once()


def test_close_releases_sessions_and_executor(monkeypatch):
    value = client(Browser, "https://demo.example.org")
    closed = []
    monkeypatch.setattr(value._session, "close", lambda: closed.append("normal"))
    monkeypatch.setattr(
        value._idempotent_session, "close", lambda: closed.append("query")
    )
    value.close()
    assert closed == ["normal", "query"]
    with pytest.raises(RuntimeError):
        value.threadpool.submit(lambda: None)
