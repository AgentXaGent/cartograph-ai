"""Hostility fixtures: synthetic adversarial servers (issue: bench-is-a-mirror,
Run 03 scorecard Finding 3).

The default bench is built from self-selected, well-behaved sources, so a
zero-crash rate proves fit to the anticipated state-space, not robustness
against web entropy. These tests drive a local server that misbehaves on
purpose (redirect loops, tarpits, mid-stream resets, oversized bodies) and
assert cartograph degrades to a structured result, never an exception or an
unbounded hang.

Marked ``hostile`` and deselected by default (like ``network``); run with
``-m hostile``. The server binds 127.0.0.1 only; no external traffic, no
egress, fully deterministic.
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from cartograph_ai.stages.http_probe import probe_http

pytestmark = pytest.mark.hostile

_BODY_CAP = 5_000_000  # mirrors http_probe._BODY_MAX_BYTES


class _HostileHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence test-server noise
        pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path
        if path.startswith("/redirect-loop"):
            self.send_response(302)
            self.send_header("Location", "/redirect-loop")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path.startswith("/hang"):
            # tarpit: sleep well past any sane client timeout
            time.sleep(5)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
        elif path.startswith("/reset"):
            # promise a body, deliver none, slam the connection
            self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 4096\r\n\r\n")
            self.wfile.flush()
            self.close_connection = True
            try:
                self.connection.close()
            except OSError:
                pass
        elif path.startswith("/huge"):
            body = b"a" * (_BODY_CAP + 1_000_000)  # > 5 MB cap
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()


@pytest.fixture(scope="module")
def hostile_base():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _HostileHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    host, port = srv.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        srv.shutdown()
        srv.server_close()


def _client(timeout: float = 2.0, max_redirects: int = 5) -> httpx.Client:
    # trust_env=False so a localhost probe is never routed through an
    # ambient SOCKS/HTTP proxy (the sandbox sets one).
    return httpx.Client(
        trust_env=False,
        timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)),
        follow_redirects=True,
        max_redirects=max_redirects,
    )


def test_infinite_redirect_loop_degrades_to_structured_error(hostile_base):
    client = _client(max_redirects=5)
    try:
        findings = probe_http(
            hostile_base + "/redirect-loop", client=client, polite_delay=0.0
        )
    finally:
        client.close()
    assert findings["error"], "redirect loop must surface a structured error"
    assert findings["status"] is None
    assert "redirect" in findings["error"].lower()


def test_tarpit_read_timeout_degrades_to_structured_error(hostile_base):
    client = _client(timeout=1.0)
    try:
        findings = probe_http(hostile_base + "/hang", client=client, polite_delay=0.0)
    finally:
        client.close()
    assert findings["error"], "a tarpit must time out into a structured error"
    assert "timeout" in findings["error"].lower()


def test_midstream_connection_reset_degrades_to_structured_error(hostile_base):
    client = _client(timeout=3.0)
    try:
        findings = probe_http(hostile_base + "/reset", client=client, polite_delay=0.0)
    finally:
        client.close()
    assert findings["error"], "a mid-stream reset must surface a structured error"


def test_oversized_body_is_truncated_not_crashed(hostile_base):
    client = _client(timeout=10.0)
    try:
        findings = probe_http(hostile_base + "/huge", client=client, polite_delay=0.0)
    finally:
        client.close()
    assert findings.get("error") is None
    assert findings["status"] == 200
    assert findings["body_truncated"] is True
    assert findings["body_size_bytes"] > _BODY_CAP
    assert len(findings["body"]) <= _BODY_CAP
