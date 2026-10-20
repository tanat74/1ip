"""Tests for the IP info service."""

import ipaddress
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

import app


# ---------------------------------------------------------------------------
# is_trusted
# ---------------------------------------------------------------------------

def test_is_trusted_with_trusted_network(monkeypatch):
    monkeypatch.setattr(
        app, "TRUSTED", [ipaddress.ip_network("192.168.88.0/24")]
    )
    assert app.is_trusted("192.168.88.49")
    assert not app.is_trusted("192.168.89.49")
    assert not app.is_trusted("not-an-ip")


def test_is_trusted_empty_list(monkeypatch):
    monkeypatch.setattr(app, "TRUSTED", [])
    assert not app.is_trusted("192.168.88.49")


# ---------------------------------------------------------------------------
# client_ip
# ---------------------------------------------------------------------------

def make_handler(peer, headers=None):
    return SimpleNamespace(
        client_address=(peer, 12345),
        headers=headers or {},
    )


def test_client_ip_direct_peer(monkeypatch):
    monkeypatch.setattr(app, "TRUSTED", [])
    handler = make_handler("203.0.113.42")
    assert app.client_ip(handler) == "203.0.113.42"


def test_client_ip_direct_peer_ignores_xff(monkeypatch):
    # Untrusted peer: X-Forwarded-For must be ignored.
    monkeypatch.setattr(app, "TRUSTED", [])
    handler = make_handler(
        "203.0.113.42",
        {"X-Forwarded-For": "198.51.100.7"},
    )
    assert app.client_ip(handler) == "203.0.113.42"


def test_client_ip_trusted_proxy_no_xff(monkeypatch):
    monkeypatch.setattr(
        app, "TRUSTED", [ipaddress.ip_network("192.168.88.0/24")]
    )
    handler = make_handler("192.168.88.49")
    assert app.client_ip(handler) == "192.168.88.49"


def test_client_ip_trusted_proxy_with_xff(monkeypatch):
    monkeypatch.setattr(
        app, "TRUSTED", [ipaddress.ip_network("192.168.88.0/24")]
    )
    handler = make_handler(
        "192.168.88.49",
        {"X-Forwarded-For": "203.0.113.42, 198.51.100.7"},
    )
    # Right to left: 198.51.100.7 is untrusted -> it wins.
    assert app.client_ip(handler) == "198.51.100.7"


def test_client_ip_trusted_proxy_skips_trusted_chain(monkeypatch):
    monkeypatch.setattr(
        app, "TRUSTED", [ipaddress.ip_network("192.168.88.0/24")]
    )
    handler = make_handler(
        "192.168.88.49",
        {"X-Forwarded-For": "203.0.113.42, 192.168.88.50"},
    )
    # 192.168.88.50 is trusted, so we keep walking and find 203.0.113.42.
    assert app.client_ip(handler) == "203.0.113.42"


def test_client_ip_all_trusted_chain(monkeypatch):
    monkeypatch.setattr(
        app, "TRUSTED", [ipaddress.ip_network("192.168.88.0/24")]
    )
    handler = make_handler(
        "192.168.88.49",
        {"X-Forwarded-For": "192.168.88.50"},
    )
    # Every address in the chain is trusted -> fall back to chain[0].
    assert app.client_ip(handler) == "192.168.88.50"


def test_client_ip_invalid_xff_falls_back_to_peer(monkeypatch):
    monkeypatch.setattr(
        app, "TRUSTED", [ipaddress.ip_network("192.168.88.0/24")]
    )
    handler = make_handler(
        "192.168.88.49",
        {"X-Forwarded-For": "not-an-ip"},
    )
    assert app.client_ip(handler) == "192.168.88.49"


# ---------------------------------------------------------------------------
# get_geo / cache
# ---------------------------------------------------------------------------

def test_get_geo_caches_success(monkeypatch):
    app.clear_cache()
    calls = []

    def fake_fetch(ip):
        calls.append(ip)
        return {"success": True, "ip": ip}

    monkeypatch.setattr(app, "fetch_geo", fake_fetch)

    first = app.get_geo("203.0.113.42")
    second = app.get_geo("203.0.113.42")

    assert first == {"success": True, "ip": "203.0.113.42"}
    assert second == first
    assert len(calls) == 1  # second call served from cache


def test_get_geo_caches_error(monkeypatch):
    app.clear_cache()
    calls = []

    def fake_fetch(ip):
        calls.append(ip)
        raise ValueError("boom")

    monkeypatch.setattr(app, "fetch_geo", fake_fetch)

    first = app.get_geo("203.0.113.42")
    second = app.get_geo("203.0.113.42")

    assert first is None
    assert second is None
    assert len(calls) == 1  # error also cached


def test_get_geo_cache_expiry(monkeypatch):
    app.clear_cache()
    calls = []

    def fake_fetch(ip):
        calls.append(ip)
        return {"success": True}

    monkeypatch.setattr(app, "fetch_geo", fake_fetch)
    monkeypatch.setattr(app, "TTL", 0)  # expire immediately

    app.get_geo("203.0.113.42")
    app.get_geo("203.0.113.42")

    assert len(calls) == 2  # TTL=0 -> cache entry expired


def test_fetch_geo_rejects_private_ip():
    with pytest.raises(ValueError):
        app.fetch_geo("192.168.1.1")


def test_fetch_geo_parses_upstream(monkeypatch):
    payload = json.dumps(
        {"success": True, "ip": "8.8.8.8", "country": "US"}
    ).encode()

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return payload

    def fake_urlopen(req, timeout=None):
        assert req.full_url == app.GEO_API_URL + "8.8.8.8"
        assert req.get_header("User-agent") == app.USER_AGENT
        return FakeResponse()

    monkeypatch.setattr(app.urllib.request, "urlopen", fake_urlopen)
    result = app.fetch_geo("8.8.8.8")
    assert result == {"success": True, "ip": "8.8.8.8", "country": "US"}


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

def test_render_with_data():
    data = {
        "success": True,
        "country": "Россия",
        "region": "Московская область",
        "city": "Москва",
        "flag": {"emoji": "🇷🇺"},
        "connection": {
            "isp": "Some ISP",
            "org": "Some Org",
            "asn": 12345,
        },
    }
    html = app.render("203.0.113.42", data)
    assert "203.0.113.42" in html
    assert "Россия" in html
    assert "Москва" in html
    assert "AS12345" in html
    assert "Some ISP" in html


def test_render_escapes_html():
    data = {
        "success": True,
        "country": "<script>alert(1)</script>",
        "city": "A&B",
        "connection": {},
    }
    html = app.render("203.0.113.42", data)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "A&amp;B" in html


def test_render_without_data():
    html = app.render("203.0.113.42", None)
    assert "Геоданные временно недоступны" in html
    assert "203.0.113.42" in html


# ---------------------------------------------------------------------------
# HTTP server (integration)
# ---------------------------------------------------------------------------

@pytest.fixture()
def live_server(monkeypatch):
    """Start the real server on a random port with a stubbed geo lookup."""
    monkeypatch.setattr(app, "fetch_geo", lambda ip: None)

    server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_api_endpoint(live_server):
    with urllib.request.urlopen(
        f"http://127.0.0.1:{live_server}/api", timeout=5
    ) as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/plain")
        body = resp.read().decode().strip()
    assert body == "127.0.0.1"


def test_http_page_endpoint(live_server):
    with urllib.request.urlopen(
        f"http://127.0.0.1:{live_server}/", timeout=5
    ) as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/html")
        body = resp.read().decode()
    assert "127.0.0.1" in body
    assert "Мой IP" in body
