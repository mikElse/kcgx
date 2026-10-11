import urllib.error
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


def test_parse_the_html5_player_page():
    """LiveATC's page as of 2026-10-10: no /play/*.pls links, only the HTML5
    player's myHTML5Popup('<ident>', ...). It parsed to nothing."""
    feeds = parse_airport_page((FIXTURES / "kord_html5.html").read_text())
    by_ident = {f.ident: f.label for f in feeds}
    assert len(feeds) == 30
    assert by_ident["kord1n2_app_133625"] == "Chicago Approach (10R/28C)"
    assert by_ident["kord1n1_app_133625"] == "Chicago Approach (10R/28C) #2"
    assert all(f.label for f in feeds)


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


# -- retry and cache -------------------------------------------------------
#
# LiveATC fronts /search/ with Cloudflare bot protection that rejects most
# non-browser clients: measured, roughly one request in four gets through,
# and neither a browser User-Agent nor spacing requests out changes that.
# /play/*.pls is unprotected, which is why streaming works regardless.


def test_http_get_retries_a_403_and_succeeds_on_a_later_attempt():
    from squelch.feeds import http_get_with_retry

    attempts = []

    def flaky(url):
        attempts.append(url)
        if len(attempts) < 3:
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        return "<html>ok</html>"

    slept = []
    assert (
        http_get_with_retry(
            "https://example.test/x", get=flaky, sleep=slept.append, attempts=5
        )
        == "<html>ok</html>"
    )
    assert len(attempts) == 3
    assert slept, "retries must back off rather than hammer the site"


def test_http_get_gives_up_after_the_attempt_budget():
    from squelch.feeds import http_get_with_retry

    def always_403(url):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        http_get_with_retry(
            "https://example.test/x", get=always_403, sleep=lambda s: None, attempts=3
        )


def test_http_get_does_not_retry_a_real_error():
    """A 404 is an answer, not a challenge -- retrying it just wastes time."""
    from squelch.feeds import http_get_with_retry

    calls = []

    def not_found(url):
        calls.append(url)
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        http_get_with_retry(
            "https://example.test/x", get=not_found, sleep=lambda s: None, attempts=5
        )
    assert len(calls) == 1


def test_feeds_round_trip_through_the_cache(tmp_path):
    from squelch.feeds import read_cached_feeds, write_cached_feeds

    feeds = [Feed(ident="kpdx3_twr", label="KPDX Tower (Both)"), Feed("a", "B")]
    write_cached_feeds("KPDX", feeds, directory=tmp_path)
    assert read_cached_feeds("KPDX", directory=tmp_path) == feeds


def test_reading_a_missing_cache_returns_none(tmp_path):
    from squelch.feeds import read_cached_feeds

    assert read_cached_feeds("KPDX", directory=tmp_path) is None


def test_a_corrupt_cache_is_ignored_rather_than_fatal(tmp_path):
    from squelch.feeds import cache_path, read_cached_feeds

    path = cache_path("KPDX", directory=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    assert read_cached_feeds("KPDX", directory=tmp_path) is None


def test_cache_age_is_reported_so_staleness_can_be_judged(tmp_path):
    from squelch.feeds import cached_age_seconds, write_cached_feeds

    write_cached_feeds("KPDX", [Feed("a", "B")], directory=tmp_path)
    age = cached_age_seconds("KPDX", directory=tmp_path)
    assert age is not None and age < 60


def test_cache_age_is_none_when_there_is_no_cache(tmp_path):
    from squelch.feeds import cached_age_seconds

    assert cached_age_seconds("KPDX", directory=tmp_path) is None


def test_the_first_feed_is_not_labelled_with_a_page_section_heading():
    """Regression, seen against the live page.

    The window for the first feed starts at the top of the document, which
    on the real KPDX page contains section headings ("KPDX ADS-B Flight
    Tracking", "KPDX Airport Info"). Those are not boilerplate by the
    ends-with-colon rule, so taking the *first* non-boilerplate <strong>
    labelled the first feed "KPDX ADS-B Flight Tracking" instead of
    "KPDX App/Dep (South)".

    The feed name is the *last* non-boilerplate <strong> before the link:
    a feed's own boilerplate (Feed Status:/UP/Listeners:) sits between its
    name and its link, and anything earlier belongs to the page or to the
    previous feed.
    """
    html = """
    <strong>KPDX METAR Weather:</strong>
    <strong>KPDX ADS-B Flight Tracking</strong>
    <strong>KPDX Airport Info</strong>
    <table><tr><td><strong>KPDX App/Dep (South)</strong></td></tr>
    <tr><td><strong>Feed Status:</strong> <strong>UP</strong>
    <strong>Listeners:</strong> 3</td></tr>
    <tr><td><a href="/play/kpdx_app_118100.pls">Play</a></td></tr></table>
    <strong>Archive Access:</strong>
    <table><tr><td><strong>KPDX Ground</strong></td></tr>
    <tr><td><strong>Feed Status:</strong> <strong>UP</strong></td></tr>
    <tr><td><a href="/play/kpdx3_gnd.pls">Play</a></td></tr></table>
    """
    feeds = parse_airport_page(html)
    labels = {f.ident: f.label for f in feeds}
    assert labels["kpdx_app_118100"] == "KPDX App/Dep (South)", (
        "the first feed picked up a page heading instead of its own name"
    )
    assert labels["kpdx3_gnd"] == "KPDX Ground"


def test_a_first_visit_gets_more_coin_flips_than_a_revisit(tmp_path):
    """No cache means no fallback, so it is worth re-flipping more times."""
    import urllib.error

    from squelch.feeds import (
        COLD_FETCH_ATTEMPTS,
        FETCH_ATTEMPTS,
        Feed,
        fetch_feeds,
        write_cached_feeds,
    )

    attempts = []

    def always_blocked(url):
        attempts.append(url)
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    # Cold: no cache for KORD.
    attempts.clear()
    try:
        fetch_feeds("KORD", cache_dir=tmp_path, get=always_blocked,
                    sleep=lambda _s: None)
    except urllib.error.HTTPError:
        pass
    assert len(attempts) == COLD_FETCH_ATTEMPTS

    # Warm: a cache exists, so a failure is survivable.
    write_cached_feeds("KSEA", [Feed("ksea_twr", "KSEA Tower")], directory=tmp_path)
    attempts.clear()
    try:
        fetch_feeds("KSEA", cache_dir=tmp_path, get=always_blocked,
                    sleep=lambda _s: None)
    except urllib.error.HTTPError:
        pass
    assert len(attempts) == FETCH_ATTEMPTS
    assert COLD_FETCH_ATTEMPTS > FETCH_ATTEMPTS
