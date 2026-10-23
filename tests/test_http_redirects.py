"""Destination policy exercised through the public tool, without sockets."""

import asyncio
import io
from email.message import Message
from urllib.response import addinfourl

import httpx
import pytest

from delx_agent_utilities import call_util_tool
from delx_agent_utilities._internal import _helpers


@pytest.fixture
def synthetic_http(monkeypatch):
    real_client = httpx.AsyncClient
    real_build_opener = _helpers.urllib_request.build_opener
    routes = {}
    calls = {"httpx": [], "urllib": []}
    mode = {"fallback": False}

    def response_for(url, transport):
        calls[transport].append(url)
        return routes.get(url, (200, {}, b"synthetic private response"))

    def handle(request):
        if mode["fallback"]:
            raise httpx.ConnectError("synthetic transport unavailable", request=request)
        status, headers, body = response_for(str(request.url), "httpx")
        return httpx.Response(status, headers=headers, content=body)

    def forbid_socket(*args, **kwargs):
        raise AssertionError("real network is forbidden in this fixture")

    monkeypatch.setattr(_helpers.socket, "create_connection", forbid_socket)

    class SyntheticHTTP(_helpers.urllib_request.HTTPHandler, _helpers.urllib_request.HTTPSHandler):
        def http_open(self, request):
            status, headers, body = response_for(request.full_url, "urllib")
            message = Message()
            for name, value in headers.items():
                message[name] = value
            response = addinfourl(io.BytesIO(body), message, request.full_url, status)
            response.msg = "Synthetic"
            return response

        https_open = http_open

    def build_opener(*handlers):
        return real_build_opener(SyntheticHTTP(), *handlers)

    monkeypatch.setattr(_helpers.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handle), **kwargs
    ))
    monkeypatch.setattr(_helpers.urllib_request, "build_opener", build_opener)
    monkeypatch.setattr(_helpers.urllib_request, "_opener", build_opener())
    return routes, calls, mode


def health(url):
    return asyncio.run(call_util_tool("util_url_health", {"url": url}))


@pytest.mark.parametrize("destination", [
    "http://127.0.0.1/private", "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/private", "http://localhost/private", "http://printer.local/private",
    "http://2130706433/private", "http://127.1/private",
    "http://0x7f000001/private", "http://0177.0.0.1/private",
    "http://127.0.0.1./private",
    "http://%31%32%37.0.0.1/private", "http://%6cocalhost/private",
    "file:///etc/passwd",
])
@pytest.mark.parametrize("transport", ["httpx", "urllib"])
def test_private_redirect_is_rejected_before_transport(synthetic_http, destination, transport):
    routes, calls, mode = synthetic_http
    mode["fallback"] = transport == "urllib"
    start = "https://public.example/start"
    routes[start] = (302, {"location": destination}, b"")

    result = health(start)

    assert result["reachable"] is False
    assert result["code"] in {"blocked_target", "invalid_protocol"}
    assert calls[transport] == [start]
    if transport == "httpx":
        assert calls["urllib"] == [], "security rejection must not enter fallback"


def test_unicode_numeric_initial_target_is_rejected_without_transport(synthetic_http):
    _, calls, _ = synthetic_http

    result = health("http://１２７.０.０.１/private")

    assert result["reachable"] is False
    assert result["code"] == "blocked_target"
    assert calls == {"httpx": [], "urllib": []}


@pytest.mark.parametrize("transport", ["httpx", "urllib"])
def test_public_relative_redirect_preserves_health_result(synthetic_http, transport):
    routes, calls, mode = synthetic_http
    mode["fallback"] = transport == "urllib"
    start = "https://public.example/start"
    final = "https://public.example/ready"
    routes[start] = (307, {"location": "/ready"}, b"")
    routes[final] = (200, {"content-type": "text/plain"}, b"ok")

    result = health(start)

    assert result["reachable"] is True
    assert result["redirected"] is True
    assert result["final_url"] == final
    assert calls[transport] == [start, final]


@pytest.mark.parametrize("transport", ["httpx", "urllib"])
def test_redirect_loop_is_bounded_without_fallback_retry(synthetic_http, transport):
    routes, calls, mode = synthetic_http
    mode["fallback"] = transport == "urllib"
    start = "https://public.example/start"
    routes[start] = (301, {"location": start}, b"")

    result = health(start)

    assert result["reachable"] is False
    assert "redirect" in result["reason"].lower()
    assert len(calls[transport]) <= 6
    if transport == "httpx":
        assert calls["urllib"] == []
