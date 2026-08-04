from delx_agent_utilities._internal._tools_text_more import (
    _case_convert,
    _clamp,
    _diff_lines,
    _duration_parse,
    _isbn_check,
    _luhn_check,
    _markdown_to_text,
    _percent_change,
    _query_string,
    _semver_compare,
    _url_join,
    _word_count,
)


def test_semver():
    r = _semver_compare({"a": "1.2.3", "b": "1.2.10"})
    assert r["relation"] == "lt"


def test_word_count():
    r = _word_count({"text": "hello world\n\nnext"})
    assert r["words"] == 3


def test_markdown():
    r = _markdown_to_text({"markdown": "# Hi\n\n**bold** [x](http://a)"})
    assert "Hi" in r["text"]
    assert "**" not in r["text"]


def test_duration():
    r = _duration_parse({"duration": "1h30m"})
    assert r["seconds"] == 5400


def test_case():
    r = _case_convert({"text": "HelloWorld", "case": "snake"})
    assert r["result"] == "hello_world"


def test_query():
    r = _query_string({"action": "parse", "query": "a=1&b=2"})
    assert r["params"]["a"] == "1"
    r2 = _query_string({"action": "build", "params": {"a": 1, "b": 2}})
    assert "a=1" in r2["query"]


def test_url_join():
    r = _url_join({"base": "https://ex.com/a/", "path": "../b"})
    assert r["url"].startswith("https://")


def test_percent():
    r = _percent_change({"from": 100, "to": 110})
    assert r["percent_change"] == 10.0


def test_clamp():
    r = _clamp({"value": 15, "min": 0, "max": 10})
    assert r["result"] == 10
    assert r["clamped"] is True


def test_luhn():
    # known valid Visa test number checksum
    r = _luhn_check({"number": "4111111111111111"})
    assert r["valid"] is True
    assert r["redacted"].endswith("1111")


def test_isbn():
    r = _isbn_check({"isbn": "978-0-306-40615-7"})
    assert r["valid"] is True


def test_diff():
    r = _diff_lines({"a": "a\nb\nc", "b": "a\nx\nc"})
    assert r["added"] == 1
    assert r["removed"] == 1
