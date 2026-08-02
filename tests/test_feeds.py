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


def test_label_survives_intervening_ad_table():
    """Regression test: a "nearest preceding <table>" heuristic would latch
    onto an injected ad block's own <table> and return its text (e.g.
    "Sponsored") instead of skipping past it to the real feed label.
    """
    feeds = parse_airport_page((FIXTURES / "kpdx_adversarial.html").read_text())
    by_ident = {f.ident: f.label for f in feeds}
    assert by_ident["kpdx_nested_table_test"] == "KPDX Nested Table Test"


def test_label_extraction_handles_strong_attributes_and_case():
    """<strong class="..."> and <STRONG> must both extract the label text,
    not fall through to the title-cased-ident fallback.
    """
    feeds = parse_airport_page((FIXTURES / "kpdx_adversarial.html").read_text())
    by_ident = {f.ident: f.label for f in feeds}
    assert by_ident["kpdx_attr_strong_test"] == "KPDX Attr Strong Test"

    html = (
        '<table class="body"><tbody><tr><td bgcolor="lightblue">'
        "<STRONG>Uppercase Tag Test</STRONG></td></tr>"
        '<tr><td><a href="/play/kpdx_uppercase_tag_test.pls">'
        "(launches your MP3 player)</a></td></tr></tbody></table>"
    )
    feeds = parse_airport_page(html)
    assert feeds[0].label == "Uppercase Tag Test"


def test_label_falls_back_to_ident_when_no_strong_present():
    feeds = parse_airport_page((FIXTURES / "kpdx_adversarial.html").read_text())
    by_ident = {f.ident: f.label for f in feeds}
    assert by_ident["kpdx_no_strong_test"] == "KPDX NO STRONG TEST"
