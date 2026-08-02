from squelch.__main__ import parse_args, try_start


def test_defaults_come_from_config():
    args = parse_args([])
    assert args.feed is None
    assert args.icao is None


def test_feed_override():
    args = parse_args(["--feed", "ksea_twr"])
    assert args.feed == "ksea_twr"


def test_icao_override():
    args = parse_args(["--icao", "KSEA"])
    assert args.icao == "KSEA"


def test_try_start_reports_success_and_stays_quiet():
    warnings = []
    assert try_start(lambda: None, warnings.append, "boom") is True
    assert warnings == []


def test_try_start_degrades_instead_of_raising():
    """A model that will not load must not take the app down."""
    warnings = []

    def explode():
        raise RuntimeError("no such model")

    assert try_start(explode, warnings.append, "transcription unavailable") is False
    assert warnings == ["transcription unavailable"]
