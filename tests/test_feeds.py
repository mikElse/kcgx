from pathlib import Path

import pytest

from squelch.feeds import (
    Feed,
    FeedError,
    airport_url,
    fetch_feeds,
    parse_airport_page,
    parse_pls,
    pls_url,
    resolve_stream,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_pls_url():
    assert pls_url("kpdx_twr") == "https://www.liveatc.net/play/kpdx_twr.pls"


def test_airport_url_lowercases():
    assert airport_url("KPDX") == "https://www.liveatc.net/search/?icao=kpdx"


def test_parse_pls_extracts_first_stream():
    text = "[playlist]\nNumberOfEntries=1\nFile1=https://s1-bos.liveatc.net/kpdx_twr\nLength1=-1\n"
    assert parse_pls(text) == "https://s1-bos.liveatc.net/kpdx_twr"


def test_parse_pls_rejects_empty():
    with pytest.raises(FeedError):
        parse_pls("[playlist]\nNumberOfEntries=0\n")


def test_parse_real_pls_fixture():
    url = parse_pls((FIXTURES / "kpdx_twr.pls").read_text())
    assert url.startswith("http")


def test_parse_airport_page_finds_tower():
    feeds = parse_airport_page((FIXTURES / "kpdx.html").read_text())
    idents = [f.ident for f in feeds]
    assert "kpdx3_twr" in idents
    assert len(idents) == len(set(idents)), "idents must be deduplicated"
    assert all(f.ident.islower() for f in feeds)
    assert all(f.label for f in feeds), "every feed needs a non-empty label"


def test_fetch_feeds_uses_injected_fetcher():
    calls = []

    def fake(url):
        calls.append(url)
        return (FIXTURES / "kpdx.html").read_text()

    feeds = fetch_feeds("KPDX", fake)
    assert calls == ["https://www.liveatc.net/search/?icao=kpdx"]
    assert any(f.ident == "kpdx3_twr" for f in feeds)


def test_resolve_stream_uses_injected_fetcher():
    def fake(url):
        assert url == "https://www.liveatc.net/play/kpdx_twr.pls"
        return "[playlist]\nFile1=https://example.test/stream\n"

    assert resolve_stream("kpdx_twr", fake) == "https://example.test/stream"
