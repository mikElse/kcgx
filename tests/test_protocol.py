"""The shapes that cross the WebSocket, without a socket."""

from __future__ import annotations

import json

import pytest

from kcgx.airports import find, load_airports
from kcgx.prefs import DEFAULTS
from kcgx.protocol import (
    PROTOCOL,
    BadMessage,
    airport_view,
    chatter_frame,
    encode,
    feed_view,
    levels_frame,
    order_frame,
    parse_client,
    prefs_frame,
    snapshot,
    volume_frame,
)
from squelch.feeds import Feed


class Session:
    def __init__(self, ident, label, **kwargs):
        self.feed = Feed(ident=ident, label=label)
        self.name = label
        self.state = "live"
        self.muted = True
        self.soloed = False
        self.ambient = False
        self.connected = True
        self.activity = 0.0
        self.level = -96.0
        self.__dict__.update(kwargs)


def two():
    return [
        Session("kpdx3_twr", "Tower (Both)", muted=False, activity=0.3412, level=-21.37),
        Session("kpdx3_gnd", "Ground", activity=0.07, level=-60.04),
    ]


# -- server to page --------------------------------------------------------


def test_a_feed_view_carries_everything_a_row_shows():
    view = feed_view(two()[0])
    assert view == {
        "ident": "kpdx3_twr",
        "label": "Tower (Both)",
        "name": "Tower (Both)",
        "title": "Tower (Both)",
        "state": "live",
        "muted": False,
        "soloed": False,
        "ambient": False,
        "connected": True,
        "chatter": 0.341,
    }


def test_a_feed_view_takes_its_title_from_the_station():
    view = feed_view(two()[0], lambda session: session.name.upper())
    assert view["name"] == "Tower (Both)"
    assert view["title"] == "TOWER (BOTH)"


def test_the_volume_frame_carries_the_master_mute():
    assert volume_frame(0.456) == {"t": "volume", "value": 0.46, "muted": False}
    assert volume_frame(0.5, True) == {"t": "volume", "value": 0.5, "muted": True}


def test_a_snapshot_carries_the_master_mute_and_the_titles():
    frame = snapshot(
        airport=None, icao="KPDX", loading=False, sessions=two(), volume=0.5,
        muted=True, max_streams=7, audio_ok=True, log=[],
        title_of=lambda session: "T " + session.feed.ident,
    )
    assert frame["muted"] is True and frame["volume"] == 0.5
    assert [f["title"] for f in frame["feeds"]] == ["T kpdx3_twr", "T kpdx3_gnd"]


def test_a_snapshot_is_not_muted_unless_told():
    frame = snapshot(
        airport=None, icao="KPDX", loading=False, sessions=two(), volume=1,
        max_streams=7, audio_ok=True, log=[],
    )
    assert frame["muted"] is False
    assert [f["title"] for f in frame["feeds"]] == [f["name"] for f in frame["feeds"]]


def test_an_airport_view_from_the_dataset():
    view = airport_view(find("KPDX", load_airports()), "KPDX")
    assert view["icao"] == "KPDX"
    assert "Portland" in view["name"]
    assert view["lat"] == pytest.approx(45.59, abs=0.01)


def test_an_unknown_airport_still_has_its_code():
    assert airport_view(None, "ZZZZ") == {
        "icao": "ZZZZ", "iata": "", "name": "", "where": "", "lat": None, "lon": None,
    }


def test_a_snapshot_has_the_feeds_in_stack_order_and_the_protocol_version():
    frame = snapshot(
        airport=None,
        icao="KPDX",
        loading=False,
        sessions=two(),
        volume=0.8,
        max_streams=7,
        audio_ok=True,
        log=[{"z": "1955Z", "text": "hello"}],
    )
    assert frame["t"] == "snapshot"
    assert frame["protocol"] == PROTOCOL
    assert [f["ident"] for f in frame["feeds"]] == ["kpdx3_twr", "kpdx3_gnd"]
    assert frame["volume"] == 0.8
    assert frame["log"] == [{"z": "1955Z", "text": "hello"}]
    assert frame["prefs"] == DEFAULTS


def test_a_snapshot_without_prefs_has_lists_of_its_own():
    frame = snapshot(
        airport=None, icao="KPDX", loading=False, sessions=[], volume=1,
        max_streams=7, audio_ok=True, log=[],
    )
    frame["prefs"]["tag_fields"].append("DIST")
    frame["prefs"]["box_items"].append("HUD")
    assert DEFAULTS["tag_fields"] == ["CALLSIGN", "ALT"]
    assert DEFAULTS["box_items"] == []


def test_a_snapshot_carries_the_prefs_it_is_given():
    prefs = {**DEFAULTS, "palette": "MONO", "glow_map": 0, "display": "VECTOR", "range_nm": 120}
    frame = snapshot(
        airport=None, icao="KPDX", loading=False, sessions=[], volume=1,
        max_streams=7, audio_ok=True, log=[], prefs=prefs,
    )
    assert frame["prefs"] == prefs


def test_a_prefs_frame_is_flat():
    assert prefs_frame({**DEFAULTS, "palette": "AMBER"}) == {"t": "prefs", **DEFAULTS, "palette": "AMBER"}


def test_levels_are_keyed_by_ident_and_rounded():
    assert levels_frame(two()) == {"t": "levels", "v": {"kpdx3_twr": -21.4, "kpdx3_gnd": -60.0}}


def test_chatter_is_keyed_by_ident():
    assert chatter_frame(two())["v"] == {"kpdx3_twr": 0.341, "kpdx3_gnd": 0.07}


def test_order_is_a_list_of_idents():
    assert order_frame(two()) == {"t": "order", "idents": ["kpdx3_twr", "kpdx3_gnd"]}


def test_encoding_is_compact_and_keeps_unicode():
    text = encode({"t": "message", "text": "LiveATC streams 7 feeds at once — 2 parked (‖)"})
    assert " " not in text.split('"text"')[0]
    assert "—" in text and "‖" in text
    assert json.loads(text)["t"] == "message"


# -- page to server --------------------------------------------------------


@pytest.mark.parametrize("kind", ["select", "mute", "solo", "ambient", "open_feed"])
def test_ident_actions_parse(kind):
    assert parse_client(json.dumps({"t": kind, "ident": "kpdx3_twr"})) == {
        "t": kind, "ident": "kpdx3_twr",
    }


@pytest.mark.parametrize("on", [True, False])
def test_master_mute_parses(on):
    assert parse_client(json.dumps({"t": "master_mute", "on": on})) == {"t": "master_mute", "on": on}


def test_input_parses():
    assert parse_client('{"t":"input"}') == {"t": "input"}


@pytest.mark.parametrize("value, expected", [(0.5, 0.5), (0, 0.0), (1, 1.0), (1.7, 1.0), (-0.2, 0.0)])
def test_volume_is_clamped_to_the_unit_range(value, expected):
    assert parse_client(json.dumps({"t": "volume", "value": value})) == {
        "t": "volume", "value": expected,
    }


def test_prefs_parse_one_or_more_known_names():
    assert parse_client('{"t":"prefs","palette":"MATRIX"}') == {"t": "prefs", "palette": "MATRIX"}
    assert parse_client('{"t":"prefs","glow_traffic":0,"display":"CRT"}') == {
        "t": "prefs", "glow_traffic": 0, "display": "CRT",
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"palette": "MONO"},  # a choice
        {"lamps": True},  # a flag
        {"teletype": False},
        {"range_nm": 250},  # a number
        {"scan_opacity": 0},
        {"tag_fields": ["CALLSIGN", "TYPE", "DIST"]},  # a subset
        {"box_items": []},
        {"box_fill": 0, "box_pad": 12, "box_border": 100, "box_width": 5, "scan_size": 2},
        {"map": {"COAST": {"alpha": 60}}},  # a table, in part
        {"map": {"CLASS_D": {"line": "DASH", "width": 5}, "HOME": {"show": False, "label": 32}}},
        {"map": {}},
        {"glow_map": 0, "glow_traffic": 100, "glow_text": 50},
        {"poll_secs": 120, "fps_max": 15, "aa": "SUPER", "boot_anim": False},
    ],
)
def test_prefs_parse_every_kind_of_setting(changes):
    assert parse_client(json.dumps({"t": "prefs", **changes})) == {"t": "prefs", **changes}


def test_a_subset_from_a_page_is_put_in_schema_order_without_repeats():
    assert parse_client('{"t":"prefs","tag_fields":["DIST","ALT","DIST","CALLSIGN"]}') == {
        "t": "prefs", "tag_fields": ["CALLSIGN", "ALT", "DIST"],
    }


@pytest.mark.parametrize(
    "key, bad",
    [
        ("palette", "PLAID"),
        ("palette", "amber"),
        ("glow_map", 101),
        ("display", None),
        ("lamps", 1),
        ("lamps", "true"),
        ("teletype", None),
        ("range_nm", 9),
        ("range_nm", 251),
        ("range_nm", 40.0),
        ("range_nm", "40"),
        ("range_nm", 45),  # off its steps of 10
        ("poll_secs", 17),
        ("scan_size", True),
        ("box_width", 0),
        ("tag_fields", ["CALLSIGN", "COLOUR"]),
        ("tag_fields", "CALLSIGN"),
        ("tag_fields", ["callsign"]),
        ("box_items", {"HUD": True}),
        ("box_items", [["HUD"]]),
        ("box_items", None),
        ("poll_secs", 10),
        ("map", "SOLID"),
        ("map", []),
    ],
)
def test_a_bad_pref_is_refused_by_name(key, bad):
    with pytest.raises(BadMessage) as refused:
        parse_client(json.dumps({"t": "prefs", key: bad}))
    assert str(refused.value).startswith(key + " must be ")


@pytest.mark.parametrize(
    "cells, said",
    [
        ({"COAST": {"alpha": 101}}, "map.COAST.alpha must be a whole number from 0 to 100"),  # fails its spec
        ({"COAST": {"alpha": 60.0}}, "map.COAST.alpha must be a whole number from 0 to 100"),
        ({"COAST": {"line": "dash"}}, "map.COAST.line must be one of SOLID, DASH, DOT"),
        ({"COAST": {"label": 12}}, "map.COAST.label "),  # a column COAST does not have
        ({"COAST": {"colour": "red"}}, "map.COAST.colour "),  # a column nothing has
        ({"NOWHERE": {"alpha": 1}}, "map.NOWHERE "),  # an unknown row
        ({"COAST": True}, "map.COAST "),
    ],
)
def test_a_bad_cell_refuses_the_whole_message_naming_the_cell(cells, said):
    with pytest.raises(BadMessage) as refused:
        parse_client(json.dumps({"t": "prefs", "palette": "MONO", "map": {"LAKE": {"alpha": 10}, **cells}}))
    assert str(refused.value).startswith(said), str(refused.value)


def test_glow_the_choice_is_an_unknown_setting_now():
    with pytest.raises(BadMessage, match="^unknown setting: glow$"):
        parse_client('{"t": "prefs", "glow": "LOW"}')


def test_one_bad_pref_refuses_the_whole_message():
    with pytest.raises(BadMessage, match="^range_nm must be a whole number from 10 to 250 in steps of 10$"):
        parse_client('{"t":"prefs","palette":"MONO","range_nm":1000}')


def test_prefs_with_no_setting_are_refused():
    with pytest.raises(BadMessage, match="^prefs needs at least one setting$"):
        parse_client('{"t": "prefs"}')


@pytest.mark.parametrize(
    "text",
    [
        '{"t": "prefs", "theme": "WOPR"}',  # alone
        '{"t": "prefs", "palette": "MONO", "theme": "WOPR"}',  # after a known one
        '{"t": "prefs", "theme": "WOPR", "range_nm": 120}',  # before one
        '{"t": "prefs", "theme": "WOPR", "range_nm": 1000}',  # beside a bad one
    ],
)
def test_an_unknown_setting_refuses_the_whole_message(text):
    with pytest.raises(BadMessage, match="^unknown setting: theme$"):
        parse_client(text)


def test_a_setting_is_named_exactly():
    with pytest.raises(BadMessage, match="^unknown setting: rangenm$"):
        parse_client('{"t": "prefs", "palette": "MONO", "rangenm": 5}')
    with pytest.raises(BadMessage, match="^unknown setting: Palette$"):
        parse_client('{"t": "prefs", "Palette": "MONO"}')


@pytest.mark.parametrize(
    "text",
    [
        '{"t": "prefs"}',
        '{"t": "prefs", "palette": "PLAID"}',
        '{"t": "prefs", "palette": "amber"}',
        '{"t": "prefs", "glow": "LOW"}',
        '{"t": "prefs", "map": {"COAST": {"alpha": 101}}}',
        '{"t": "prefs", "display": "CRT", "palette": null}',
        '{"t": "prefs", "theme": "WOPR"}',
        "not json",
        "[1, 2]",
        '{"t": "explode"}',
        '{"ident": "kpdx3_twr"}',
        '{"t": "mute"}',
        '{"t": "mute", "ident": 7}',
        '{"t": "mute", "ident": "KPDX3_TWR"}',
        '{"t": "mute", "ident": "kpdx twr"}',
        '{"t": "mute", "ident": "../etc"}',
        json.dumps({"t": "mute", "ident": "a" * 65}),
        '{"t": "volume"}',
        '{"t": "volume", "value": "loud"}',
        '{"t": "volume", "value": true}',
        '{"t": "volume", "value": NaN}',
        '{"t": "volume", "value": Infinity}',
        '{"t": "select"}',
        '{"t": "select", "ident": "KPDX3_TWR"}',
        '{"t": "master_mute"}',
        '{"t": "master_mute", "on": 1}',
        '{"t": "master_mute", "on": "true"}',
        '{"t": "master_mute", "on": null}',
    ],
)
def test_anything_else_is_refused(text):
    with pytest.raises(BadMessage):
        parse_client(text)


def test_json_nested_too_deep_to_read_is_refused_as_not_json():
    # json.loads gives up on this with RecursionError, which is no ValueError.
    for text in ("[" * 200_000, '{"t":' * 200_000, "[" * 200_000 + "]" * 200_000):
        with pytest.raises(BadMessage, match="^not JSON$"):
            parse_client(text)
