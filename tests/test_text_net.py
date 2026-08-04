from delx_agent_utilities._internal._tools_text_net import (
    _cidr_contains,
    _color_convert,
    _holidays,
    _html_strip,
    _ip_classify,
    _mime_lookup,
    _slugify,
    _ulid_generate,
)


def test_holidays_2026():
    r = _holidays({"year": 2026})
    assert r["count"] == 11
    assert any(h["name"] == "Independence Day" for h in r["holidays"])


def test_slugify():
    r = _slugify({"text": "Hello, World!"})
    assert r["slug"] == "hello-world"


def test_mime():
    r = _mime_lookup({"filename": "a/b/report.PDF"})
    assert r["mime_type"] == "application/pdf"


def test_color():
    r = _color_convert({"color": "#ff0000"})
    assert r["rgb"]["r"] == 255
    assert r["hex"] == "#ff0000"


def test_ip_private():
    r = _ip_classify({"ip": "10.0.0.1"})
    assert r["is_private"] is True
    assert r["classification"] == "private"


def test_cidr():
    r = _cidr_contains({"network": "10.0.0.0/8", "ip": "10.1.2.3"})
    assert r["contains"] is True


def test_ulid():
    r = _ulid_generate({"count": 2, "timestamp_ms": 1_700_000_000_000})
    assert len(r["ulids"]) == 2
    assert all(len(u) == 26 for u in r["ulids"])


def test_html_strip():
    r = _html_strip({"html": "<p>Hi <b>there</b></p><script>x</script>"})
    assert "Hi" in r["text"]
    assert "script" not in r["text"].lower()
