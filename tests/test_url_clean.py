"""Unit tests for url_canonicalize."""

import pytest

from delx_agent_utilities import url_canonicalize


def test_lowercases_scheme_and_host():
    assert (
        url_canonicalize("HTTPS://Example.COM/Path")
        == "https://example.com/Path"
    )


def test_adds_https_when_scheme_missing():
    assert url_canonicalize("example.com/page") == "https://example.com/page"


def test_strips_utm_params_and_known_trackers():
    url = (
        "https://example.com/article?utm_source=newsletter&utm_medium=email"
        "&utm_campaign=spring&gclid=abc&fbclid=def&mc_eid=xyz&ref=twitter"
        "&id=42"
    )
    assert url_canonicalize(url) == "https://example.com/article?id=42"


def test_keeps_non_tracking_query_and_sorts_keys():
    url = "https://example.com/x?z=3&a=1&m=2"
    assert url_canonicalize(url) == "https://example.com/x?a=1&m=2&z=3"


def test_drops_default_ports():
    assert url_canonicalize("http://example.com:80/x") == "http://example.com/x"
    assert (
        url_canonicalize("https://example.com:443/x")
        == "https://example.com/x"
    )


def test_keeps_non_default_port():
    assert (
        url_canonicalize("http://example.com:8080/x")
        == "http://example.com:8080/x"
    )


def test_strips_fragment_by_default_and_keeps_when_asked():
    assert (
        url_canonicalize("https://example.com/page#section")
        == "https://example.com/page"
    )
    assert (
        url_canonicalize("https://example.com/page#section", keep_fragment=True)
        == "https://example.com/page#section"
    )


def test_extra_tracking_params_drop_custom_keys():
    url = "https://example.com/?utm_source=x&affid=99&id=1"
    out = url_canonicalize(url, extra_tracking_params=["affid"])
    assert out == "https://example.com/?id=1"


def test_invalid_input_raises():
    with pytest.raises(TypeError):
        url_canonicalize(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        url_canonicalize("   ")


def test_userinfo_is_preserved():
    out = url_canonicalize("https://user:pass@Example.com:443/path?utm_a=1")
    assert out == "https://user:pass@example.com/path"


def test_empty_path_defaults_to_slash():
    assert url_canonicalize("https://example.com") == "https://example.com/"
