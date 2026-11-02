"""Destination policy exercised through the public tool, without sockets."""

import asyncio
from email.message import Message

import pytest

from delx_agent_utilities import call_util_tool
from delx_agent_utilities._internal import _helpers


@pytest.fixture
def synthetic_http(monkeypatch):
    routes = {}
    calls = []

    def single_hop(url, *, timeout, method):
        calls.append(url)
        status, headers, body = routes.get(url, (200, {}, b"synthetic response"))
        message = Message()
        for name, value in headers.items():
            message[name] = value
        return status, body, message, "Synthetic"

    def forbid_network(*args, **kwargs):
        raise AssertionError("real network is forbidden in this fixture")

    monkeypatch.setattr(_helpers.socket, "getaddrinfo", forbid_network)
    monkeypatch.setattr(_helpers.socket, "create_connection", forbid_network)
    monkeypatch.setattr(_helpers, "_request_public_http", single_hop)
    return routes, calls


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
def test_private_redirect_is_rejected_before_transport(synthetic_http, destination):
    routes, calls = synthetic_http
    start = "https://public.example/start"
    routes[start] = (302, {"location": destination}, b"")

    result = health(start)

    assert result["reachable"] is False
    assert result["code"] in {"blocked_target", "invalid_protocol"}
    assert calls == [start]


def test_unicode_numeric_initial_target_is_rejected_without_transport(synthetic_http):
    _, calls = synthetic_http

    result = health("http://１２７.０.０.１/private")

    assert result["reachable"] is False
    assert result["code"] == "blocked_target"
    assert calls == []


def test_public_relative_redirect_preserves_health_result(synthetic_http):
    routes, calls = synthetic_http
    start = "https://public.example/start"
    final = "https://public.example/ready"
    routes[start] = (307, {"location": "/ready"}, b"")
    routes[final] = (200, {"content-type": "text/plain"}, b"ok")

    result = health(start)

    assert result["reachable"] is True
    assert result["redirected"] is True
    assert result["final_url"] == final
    assert calls == [start, final]


def test_redirect_loop_is_bounded_without_fallback_retry(synthetic_http):
    routes, calls = synthetic_http
    start = "https://public.example/start"
    routes[start] = (301, {"location": start}, b"")

    result = health(start)

    assert result["reachable"] is False
    assert "redirect" in result["reason"].lower()
    assert len(calls) <= 6

