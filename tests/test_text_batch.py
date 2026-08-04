from delx_agent_utilities._internal._tools_text_batch import (
    _dedupe_lines,
    _extract_emails,
    _extract_urls,
    _hex_convert,
    _levenshtein,
    _normalize_whitespace,
    _number_base,
    _random_choice,
    _random_int,
    _reading_time,
    _rot13,
    _sort_lines,
    _text_truncate,
    _url_encode,
)


def test_levenshtein():
    r = _levenshtein({"a": "kitten", "b": "sitting"})
    assert r["distance"] == 3


def test_normalize():
    r = _normalize_whitespace({"text": "a   b\n\n\nc", "mode": "collapse"})
    assert "  " not in r["text"]


def test_extract_urls():
    r = _extract_urls({"text": "see https://ex.com/a and www.foo.com"})
    assert r["count"] >= 2


def test_extract_emails():
    r = _extract_emails({"text": "mail me@ex.com now"})
    assert r["emails"] == ["me@ex.com"]


def test_url_encode():
    r = _url_encode({"text": "a b", "action": "encode"})
    assert r["result"] == "a%20b"


def test_hex():
    r = _hex_convert({"text": "hi", "action": "encode"})
    assert r["result"] == "6869"


def test_number_base():
    r = _number_base({"value": "255", "from_base": 10, "to_base": 16})
    assert r["result"] == "ff"


def test_dedupe():
    r = _dedupe_lines({"text": "a\nb\na\nc"})
    assert r["lines_after"] == 3


def test_sort():
    r = _sort_lines({"text": "b\na\nc"})
    assert r["text"] == "a\nb\nc"


def test_random_int():
    r = _random_int({"min": 1, "max": 1, "count": 2})
    assert r["values"] == [1, 1]


def test_rot13():
    r = _rot13({"text": "Hello"})
    assert r["result"] == "Uryyb"


def test_truncate():
    r = _text_truncate({"text": "abcdef", "max_length": 5, "ellipsis": "…"})
    assert r["truncated"] is True
    assert len(r["text"]) == 5


def test_reading_time():
    r = _reading_time({"text": "word " * 200, "wpm": 200})
    assert r["minutes"] == 1.0


def test_random_choice():
    r = _random_choice({"items": ["a", "b", "c"], "count": 2})
    assert len(r["choices"]) == 2
    assert len(set(r["choices"])) == 2
