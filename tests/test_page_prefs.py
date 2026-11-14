"""The config panel's controls agree with `kcgx.prefs.SCHEMA`.

No browser: `index.html` declares a `[data-pref]` control for each setting
the panel has, in its tab, with what it offers written in the markup (a
choice's names, a preset's numbers, the map's rows and their weights), and
the script binds them without knowing any setting by name. So this, and not
a copy of the choices in the script, is what stops the page and the server
drifting: nothing the panel can send is something the server refuses.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from kcgx.prefs import DEFAULTS, PALETTES, SCHEMA, Choice, Flag, Number, Subset, Table

WEB = Path(__file__).parent.parent / "src" / "kcgx" / "web"
INDEX_HTML = WEB / "index.html"
SHEETS_JS = WEB / "static" / "js" / "sheets.js"
COCKPIT_CSS = WEB / "static" / "cockpit.css"

# The settings the tracks pane binds itself: its fold and its grip, the
# COLUMNS checklist and the headers that sort. The panel has no control for
# them, and its RESET ALL leaves them be.
PANE_BOUND = frozenset({"tracks_open", "tracks_pct", "track_cols", "track_sort", "track_desc"})
# The settings the panel's presets stand in for and so have no control of
# their own: each keeps what it is set to. RESET ALL puts them back.
UNSEEN = frozenset({
    "scan_size", "box_pad", "box_width", "tail_alpha", "tail_alpha_max", "tail_gs_low", "tail_gs_high",
    "ground_gs", "ground_alt", "ground_alpha",
})
# The settings the panel has a control for: all the others.
ON_THE_PAGE = {key: spec for key, spec in SCHEMA.items() if key not in PANE_BOUND | UNSEEN}

# The design's four tabs: each control's data-pref, in the order they come.
# A preset may set several settings at once; the map's rows are two lists.
TABS = {
    "DISPLAY": [
        "palette", "display", "scan_opacity", "glow_map glow_traffic glow_text",
        "font", "font_px", "ui_zoom", "boot_anim",
    ],
    "RADAR": [
        "range_nm", "view_ease", "zoom_speed", "tag_fields", "tag_px", "motion", "sort_floor",
        "follow_nm", "info_box", "tail_secs", "tail_alpha_min", "ground_mode", "ground_min",
    ],
    "MAP": ["label_min label_max", "box_fill box_border", "box_items", "map", "map"],
    "SYSTEM": [
        "clock_24h", "clock_seconds", "clock_zone", "lamps", "teletype", "short_names",
        "aa", "fps_max", "burn_in", "poll_secs",
    ],
}
TAB_OF = {key: tab for tab, prefs in TABS.items() for pref in prefs for key in pref.split()}

# The words beside each control.
ROWS = {
    "palette": "THEME",
    "display": "SCREEN",
    "scan_opacity": "SCANLINES",
    "glow_map glow_traffic glow_text": "GLOW",
    "font": "FONT",
    "font_px": "TEXT SIZE",
    "ui_zoom": "PAGE ZOOM",
    "boot_anim": "BOOT ANIMATION",
    "range_nm": "OPENING RANGE",
    "view_ease": "VIEW MOVES",
    "zoom_speed": "ZOOM SPEED",
    "tag_fields": "FLIGHT TAG SHOWS",
    "tag_px": "TAG SIZE",
    "motion": "MOTION",
    "sort_floor": "SHADE BY SORT",
    "follow_nm": "FOLLOW AT",
    "info_box": "DATA BOX",
    "tail_secs": "LENGTH",
    "tail_alpha_min": "SHADE BY SPEED",
    "ground_mode": "PARKED TRAFFIC",
    "ground_min": "AFTER",
    "label_min label_max": "LABEL SIZE",
    "box_fill box_border": "LABEL BOXES",
    "box_items": "BOX THESE",
    "clock_24h": "24 HOUR LOCAL",
    "clock_seconds": "SECONDS",
    "clock_zone": "ZONE NAME",
    "lamps": "STATUS LAMPS",
    "teletype": "TELETYPE",
    "short_names": "SHORT FEED NAMES",
    "aa": "SHARPNESS",
    "fps_max": "FRAME RATE",
    "burn_in": "BURN IN",
    "poll_secs": "RADAR UPDATES",
}
# The sections, each with a RESET of its own.
SECTIONS = [
    "LOOK", "TEXT", "START", "VIEW", "AIRCRAFT", "FOCUS", "TAILS", "PARKED",
    "LABELS", "AVIATION", "GEOGRAPHY", "CLOCKS", "PANES", "PERFORMANCE",
]

# The one choice drawn as a dropdown, for having too many names for a row of
# buttons; every other choice is buttons.
DROPDOWNS = frozenset({"font"})
TABLES = {key: spec for key, spec in ON_THE_PAGE.items() if isinstance(spec, Table)}


def offers(text: str) -> list[tuple[str, str]]:
    """data-values as sheets.js reads it: "LABEL=value" each, a label's _ a
    space, a bare word its own value."""
    out = []
    for word in (text or "").split():
        label, _, value = word.partition("=")
        out.append((label.replace("_", " "), value or label))
    return out


class Sheet(HTMLParser):
    """The `[data-pref]` controls of the page, in document order, each with
    the dialog and the tab it is in, the words of its row and (for a
    <select>) its options; the config sheet's tabs and panels; and, for a
    table, its column headings."""

    def __init__(self):
        super().__init__()
        self.controls: list[dict] = []
        self.sections: list[str] = []  # the config sheet's <h3>s
        self.ids: dict[str, str | None] = {}  # id -> the dialog it is in
        self.tablists: list[dict] = []
        self.tabs: list[dict] = []  # {id, controls, selected, text}
        self.panels: list[dict] = []  # {id, labelledby}
        self.text = ""  # everything said inside the config sheet
        self._dialog = None
        self._panel = None
        self._tab = None  # collecting a tab's words
        self._heading = None  # collecting an <h3>
        self._row = None  # the words of the row being read: its first <span>
        self._row_open = False
        self._select = None
        self._option = None
        self._table = None  # the table control being read
        self._th = None
        self._layer = None  # collecting a layer's name
        self.keep: list[str] = []  # what RESET ALL leaves be

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids[attrs["id"]] = self._dialog
        role = attrs.get("role")
        if tag == "dialog":
            self._dialog = attrs.get("id")
        elif role == "tablist":
            self.tablists.append({"dialog": self._dialog, **attrs})
        elif role == "tab":
            self._tab = {"text": "", **attrs}
            self.tabs.append(self._tab)
        elif role == "tabpanel":
            self._panel = {"id": attrs.get("id"), "labelledby": attrs.get("aria-labelledby"), "dialog": self._dialog}
            self.panels.append(self._panel)
        elif tag == "h3" and self._dialog == "config-sheet":
            self._heading = ""
        elif "field-row" in (attrs.get("class") or "").split():
            self._row, self._row_open = None, False
        elif tag == "span" and self._row is None and not self._row_open:
            self._row, self._row_open = "", True
        if tag == "th" and self._table is not None and "data-column" in attrs:
            self._th = {"attrs": attrs, "text": ""}
            self._table["headings"].append(self._th)
        if "data-row" in attrs and self.controls:
            self._layer = {"row": attrs["data-row"], "text": ""}
            self.controls[-1]["layers"].append(self._layer)
        if "data-keep" in attrs:
            self.keep = attrs["data-keep"].split()
        if "data-pref" in attrs:
            control = {
                "key": attrs["data-pref"], "tag": tag, "attrs": attrs, "options": [], "headings": [], "layers": [],
                "dialog": self._dialog, "panel": self._panel["id"] if self._panel else None,
                "section": self.sections[-1] if self.sections else None, "row": self._row,
            }
            self.controls.append(control)
            if tag == "select":
                self._select = control
            if tag == "table":
                self._table = control
        if tag == "option" and self._select is not None:
            self._option = {"value": attrs.get("value"), "text": ""}

    def handle_endtag(self, tag):
        if tag == "dialog":
            self._dialog = None
        elif tag == "section" and self._panel is not None:
            self._panel = None
        elif tag == "button" and self._tab is not None:
            self._tab["text"] = self._tab["text"].strip()
            self._tab = None
        elif tag == "h3" and self._heading is not None:
            self.sections.append(self._heading.strip())
            self._heading = None
        elif tag == "span" and self._row_open:
            self._row_open = False
        elif tag == "span" and self._layer is not None:
            self._layer = None
        elif tag == "option" and self._option is not None:
            value = self._option["value"]
            self._select["options"].append(self._option["text"].strip() if value is None else value)
            self._option = None
        elif tag == "select":
            self._select = None
        elif tag == "th" and self._th is not None:
            self._th["text"] = self._th["text"].strip()
            self._th = None
        elif tag == "table":
            self._table = None

    def handle_data(self, data):
        if self._dialog == "config-sheet":
            self.text += data
        if self._tab is not None:
            self._tab["text"] += data
        if self._heading is not None:
            self._heading += data
        if self._row_open:
            self._row += data
        if self._layer is not None:
            self._layer["text"] += data
        if self._option is not None:
            self._option["text"] += data
        if self._th is not None:
            self._th["text"] += data

    def tab_named(self, panel_id: str | None) -> str | None:
        """The words of the tab that labels a panel."""
        panel = next((p for p in self.panels if p["id"] == panel_id), None)
        if panel is None:
            return None
        return next((t["text"] for t in self.tabs if t.get("id") == panel["labelledby"]), None)


@pytest.fixture(scope="module")
def sheet() -> Sheet:
    return parsed()


def parsed() -> Sheet:
    out = Sheet()
    out.feed(INDEX_HTML.read_text())
    return out


def control(sheet: Sheet, pref: str) -> dict:
    found = [c for c in sheet.controls if c["key"] == pref]
    assert len(found) == 1, f"{pref} has {len(found)} controls"
    return found[0]


def kind_of(found: dict) -> str:
    return "select" if found["tag"] == "select" else found["attrs"].get("data-kind", "")


def names(found: dict) -> list[str]:
    """What a choice or a subset control sends, in order."""
    if found["tag"] == "select":
        return found["options"]
    return [value for _, value in offers(found["attrs"].get("data-values"))]


# What each control offers, [label, value] each, by its data-pref: for the
# browser tests, which press the buttons by their words.
OFFERS = {c["key"]: offers(c["attrs"].get("data-values")) for c in parsed().controls if c["tag"] != "select"}
KINDS = {c["key"]: kind_of(c) for c in parsed().controls}
PRESETS = [pref for pref, kind in KINDS.items() if kind == "preset"]


def preset_values(pref: str, value: str) -> dict[str, int]:
    """What a preset's button sets: one number for every key, or one each."""
    keys, numbers = pref.split(), [int(n) for n in value.split(",")]
    assert len(numbers) in (1, len(keys)), f"{pref}: {value}"
    return {key: numbers[i] if len(numbers) > 1 else numbers[0] for i, key in enumerate(keys)}


def test_the_controls_are_the_designs_in_its_order_each_in_the_config_panel(sheet):
    assert [c["key"] for c in sheet.controls] == [pref for prefs in TABS.values() for pref in prefs]
    assert {c["dialog"] for c in sheet.controls} == {"config-sheet"}


def test_every_setting_has_one_control_but_those_bound_elsewhere_or_stood_in_for(sheet):
    keys = [key for c in sheet.controls if c["key"] != "map" for key in c["key"].split()]
    assert sorted(keys + ["map"]) == sorted(ON_THE_PAGE), "a setting with no control, or with two"
    assert not (PANE_BOUND | UNSEEN) & set(keys)
    assert PANE_BOUND | UNSEEN <= set(SCHEMA)


def test_reset_all_keeps_exactly_the_tracks_panes_own_settings(sheet):
    assert sorted(sheet.keep) == sorted(PANE_BOUND)


def test_the_panel_has_four_tabs_each_labelling_its_panel(sheet):
    assert [t["dialog"] for t in sheet.tablists] == ["config-sheet"]
    assert [t["text"] for t in sheet.tabs] == list(TABS)
    # the first is the one shown at first, and a tab names the panel it shows
    assert [t.get("aria-selected") for t in sheet.tabs] == ["true", "false", "false", "false"]
    assert [p["id"] for p in sheet.panels] == [t["aria-controls"] for t in sheet.tabs]
    assert [p["labelledby"] for p in sheet.panels] == [t["id"] for t in sheet.tabs]
    assert {p["dialog"] for p in sheet.panels} == {"config-sheet"}
    for tab in sheet.tabs:
        assert tab.get("type") == "button"


def test_the_sections_are_the_designs(sheet):
    assert sheet.sections == SECTIONS


@pytest.mark.parametrize("tab", list(TABS))
def test_a_control_sits_in_the_tab_the_design_puts_it(sheet, tab):
    assert [c["key"] for c in sheet.controls if sheet.tab_named(c["panel"]) == tab] == TABS[tab]


def test_output_is_gone_and_the_volume_is_not_in_the_panel(sheet):
    """The master volume is not a pref; it is in the frequencies pane (phase
    G decision 3), and the section that held it goes."""
    assert "OUTPUT" not in sheet.sections and "MASTER VOLUME" not in sheet.text
    assert "volume" in sheet.ids and sheet.ids["volume"] is None
    assert "volume-value" in sheet.ids and sheet.ids["volume-value"] is None


def test_limits_is_gone(sheet):
    assert "LIMITS" not in sheet.text and "STREAMS AT ONCE" not in sheet.text
    assert "max-streams" not in sheet.ids


@pytest.mark.parametrize("pref", list(ROWS))
def test_a_control_sits_in_the_row_the_design_names(sheet, pref):
    assert control(sheet, pref)["row"] == ROWS[pref]


def test_every_control_but_the_layers_has_a_row():
    assert set(ROWS) == set(KINDS) - {"map"}


@pytest.mark.parametrize("key", [k for k, spec in ON_THE_PAGE.items() if isinstance(spec, Choice)])
def test_a_choice_offers_the_schemas_names_in_order(sheet, key):
    found = control(sheet, key)
    if key in DROPDOWNS:
        assert found["tag"] == "select"
    else:
        assert found["tag"] == "div" and found["attrs"].get("data-kind") == "choice"
    assert names(found) == list(SCHEMA[key].names)


def test_the_theme_is_swatches_and_the_screen_is_segments(sheet):
    theme = control(sheet, "palette")
    assert theme["attrs"].get("data-look") == "swatches" and "swatches" in theme["attrs"]["class"].split()
    assert "segments" in control(sheet, "display")["attrs"]["class"].split()


@pytest.mark.parametrize("key", [k for k, spec in ON_THE_PAGE.items() if isinstance(spec, Subset)])
def test_a_subset_offers_the_schemas_names_in_order(sheet, key):
    found = control(sheet, key)
    assert found["attrs"].get("data-kind") == "subset"
    assert names(found) == list(SCHEMA[key].names)
    assert all(label == value for label, value in OFFERS[key])


@pytest.mark.parametrize("key", [k for k, spec in ON_THE_PAGE.items() if isinstance(spec, Flag)])
def test_a_flag_is_declared_a_flag(sheet, key):
    found = control(sheet, key)
    assert found["attrs"].get("data-kind") == "flag"
    assert "data-values" not in found["attrs"]


# -- presets -----------------------------------------------------------------------


def test_every_number_on_the_page_is_set_by_a_preset():
    numbers = {key for key, spec in ON_THE_PAGE.items() if isinstance(spec, Number)}
    assert {key for pref in PRESETS for key in pref.split()} == numbers


@pytest.mark.parametrize("pref", PRESETS)
def test_a_presets_numbers_are_ones_the_schema_takes(pref):
    """The server refuses a number out of its setting's range or off its
    step, so a button that sent one would do nothing."""
    assert OFFERS[pref], pref
    for label, value in OFFERS[pref]:
        for key, number in preset_values(pref, value).items():
            assert SCHEMA[key].check(number) == number, f"{pref} {label}"


@pytest.mark.parametrize("pref", PRESETS)
def test_one_of_a_presets_buttons_is_the_default_and_no_two_are_the_same(pref):
    """So the panel opens on the defaults with a button lit in every row."""
    sets = [preset_values(pref, value) for _, value in OFFERS[pref]]
    assert {key: DEFAULTS[key] for key in pref.split()} in sets
    assert len({tuple(s.items()) for s in sets}) == len(sets)
    assert len({label for label, _ in OFFERS[pref]}) == len(sets)


def test_a_preset_drawn_as_a_switch_is_off_then_on(sheet):
    switches = [c for c in sheet.controls if c["attrs"].get("data-look") == "toggle"]
    assert [c["key"] for c in switches] == ["tail_alpha_min"]
    for found in switches:
        assert [label for label, _ in OFFERS[found["key"]]] == ["OFF", "ON"]


@pytest.mark.parametrize("attr", ["data-only-when", "data-not-when"])
def test_a_control_that_waits_on_settings_names_ones_the_schema_has(sheet, attr):
    waiting = [c for c in sheet.controls if attr in c["attrs"]]
    assert waiting
    for found in waiting:
        for pair in found["attrs"][attr].split(","):
            key, _, value = pair.partition("=")
            spec = SCHEMA[key]
            spec.check(int(value) if isinstance(spec, Number) else value)


# -- the map's layers ----------------------------------------------------------------


def scales(text: str) -> dict[str, list[int]]:
    return {word.partition("=")[0]: [int(n) for n in word.partition("=")[2].split(",")] for word in text.split()}


def weight_cells(found: dict, row: str, weight: int) -> dict[str, int]:
    """A weight's cells for a row, as sheets.js makes them: the row's own
    defaults, each scaled by its column's percent and held to its most."""
    normal, most = SCHEMA["map"].rows[row], scales(found["attrs"]["data-most"])
    return {
        column: min(most.get(column, [10**9])[0], int(normal[column] * percents[weight] / 100 + 0.5))
        for column, percents in scales(found["attrs"]["data-scales"]).items() if column in normal
    }


def layer_controls(sheet: Sheet) -> list[dict]:
    return [c for c in sheet.controls if c["key"] == "map"]


def test_the_layers_are_every_row_of_the_map_once_under_aviation_and_geography(sheet):
    found = layer_controls(sheet)
    assert [c["section"] for c in found] == ["AVIATION", "GEOGRAPHY"]
    assert all(c["attrs"].get("data-kind") == "layers" for c in found)
    rows = [layer["row"] for c in found for layer in c["layers"]]
    assert sorted(rows) == sorted(SCHEMA["map"].rows)
    assert all(layer["text"].strip() for c in found for layer in c["layers"])


def test_a_layers_weights_scale_number_columns_and_normal_is_the_default(sheet):
    table = SCHEMA["map"]
    for found in layer_controls(sheet):
        weights = [label for label, _ in offers(found["attrs"]["data-values"])]
        assert weights == ["FAINT", "NORMAL", "BOLD"]
        for column, percents in scales(found["attrs"]["data-scales"]).items():
            assert isinstance(table.columns[column], Number), column
            assert len(percents) == len(weights) and percents[weights.index("NORMAL")] == 100
        for column, (most,) in scales(found["attrs"]["data-most"]).items():
            assert most <= table.columns[column].high, column


def test_every_weight_of_every_layer_is_cells_the_schema_takes_and_no_two_are_the_same(sheet):
    table = SCHEMA["map"]
    for found in layer_controls(sheet):
        for layer in found["layers"]:
            row = layer["row"]
            sets = [weight_cells(found, row, weight) for weight in range(3)]
            for cells in sets:
                assert table.check({row: cells}) == {row: cells}
            assert sets[1] == {column: table.rows[row][column] for column in sets[1]}, row
            assert len({tuple(cells.items()) for cells in sets}) == 3, f"{row}: two weights draw alike"
            assert "show" in table.rows[row]


def test_the_script_keeps_no_copy_of_the_choices():
    script = SHEETS_JS.read_text()
    assert "CHOICES" not in script
    for name in PALETTES:
        assert name not in script, f"sheets.js names the palette {name}"


def test_the_first_paint_draws_the_default_scanlines():
    """Until the script has the server's prefs, the stylesheet's own values
    draw the page: they are the defaults, so nothing jumps when it does."""
    css = COCKPIT_CSS.read_text()
    found = {name: value for name, value in re.findall(r"--(scan-[a-z]+):\s*([^;}]+)", css)}
    size = SCHEMA["scan_size"].default
    assert found == {
        "scan-alpha": str(SCHEMA["scan_opacity"].default / 100),
        "scan-size": f"{size}px",
        "scan-line": f"{max(1, round(size / 3))}px",
    }


def test_the_first_paint_reads_the_default_range():
    html = INDEX_HTML.read_text()
    assert f'<span id="radar-range">RNG {SCHEMA["range_nm"].default} NM</span>' in html
