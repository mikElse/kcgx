"""The config sheet's controls agree with `kcgx.prefs.SCHEMA`.

No browser: `index.html` declares one `[data-pref]` control per setting,
in the tab the plan puts it, with its range or its names written in the
markup (a table: its rows, each row's columns, and each column's range or
names), and the script binds them without knowing any setting by name. So
this, and not a copy of the choices in the script, is what stops the page
and the server drifting.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from kcgx.prefs import PALETTES, SCHEMA, Choice, Flag, Number, Subset, Table

WEB = Path(__file__).parent.parent / "src" / "kcgx" / "web"
INDEX_HTML = WEB / "index.html"
SHEETS_JS = WEB / "static" / "js" / "sheets.js"
COCKPIT_CSS = WEB / "static" / "cockpit.css"

# The settings the sheet never has a control for: the tracks pane binds them
# itself, its collapse button and its grip (phase G Task 9).
PANE_BOUND = frozenset({"tracks_open", "tracks_pct"})
# The settings the sheet has a control for, in schema order: all the others.
ON_THE_PAGE = {key: spec for key, spec in SCHEMA.items() if key not in PANE_BOUND}

# The plan's settings tables: the tab each setting is in, in schema order.
TABS = {
    "GENERAL": [
        "boot_anim", "ui_zoom", "font", "font_px", "clock_24h", "clock_seconds", "clock_zone",
        "palette", "display", "scan_opacity", "scan_size", "glow_map", "glow_traffic", "glow_text",
        "aa", "burn_in", "fps_max", "poll_secs", "motion", "view_ease", "zoom_speed", "lamps", "teletype",
    ],
    "TRAFFIC": [
        "range_nm", "tag_fields", "box_items", "box_fill", "box_pad", "box_border", "box_width",
        "map", "label_min", "label_max", "tag_px", "follow_nm", "info_box",
        "tail_secs", "tail_alpha", "tail_alpha_min", "tail_alpha_max", "tail_gs_low", "tail_gs_high",
        "ground_mode", "ground_gs", "ground_alt", "ground_min", "ground_alpha",
    ],
    "TRACKS": ["track_cols", "track_sort", "track_desc", "sort_floor"],
    "FREQUENCIES": ["short_names"],
}
TAB_OF = {key: tab for tab, keys in TABS.items() for key in keys}

# The settings tables in the plan: the words beside each control.
ROWS = {
    "boot_anim": "BOOT ANIMATION",
    "ui_zoom": "UI ZOOM",
    "font": "FONT",
    "font_px": "FONT SIZE",
    "clock_24h": "24-HOUR LOCAL",
    "clock_seconds": "SECONDS",
    "clock_zone": "ZONE NAME",
    "palette": "THEME",
    "display": "DISPLAY",
    "scan_opacity": "SCANLINE OPACITY",
    "scan_size": "SCANLINE SIZE",
    "glow_map": "GLOW: MAP",
    "glow_traffic": "GLOW: TRAFFIC",
    "glow_text": "GLOW: TEXT",
    "aa": "ANTI-ALIASING",
    "burn_in": "BURN-IN",
    "fps_max": "MAX FRAME RATE",
    "poll_secs": "RADAR POLL",
    "motion": "AIRCRAFT MOTION",
    "view_ease": "VIEW MOVES",
    "zoom_speed": "ZOOM SPEED",
    "lamps": "STATUS LAMPS",
    "teletype": "TELETYPE",
    "range_nm": "RANGE",
    "tag_fields": "FLIGHT TAG",
    "box_items": "LABEL BOXES",
    "box_fill": "BOX FILL",
    "box_pad": "BOX PADDING",
    "box_border": "BOX BORDER",
    "box_width": "BORDER WIDTH",
    "map": "MAP LAYERS",
    "label_min": "LABEL MIN",
    "label_max": "LABEL MAX",
    "tag_px": "TAG SIZE",
    "follow_nm": "FOLLOW RADIUS",
    "info_box": "DATA BOX",
    "tail_secs": "TAIL LENGTH",
    "tail_alpha": "TAIL DEFAULT",
    "tail_alpha_min": "TAIL SLOW",
    "tail_alpha_max": "TAIL FAST",
    "tail_gs_low": "SLOW BELOW",
    "tail_gs_high": "FAST ABOVE",
    "ground_mode": "PARKED TRAFFIC",
    "ground_gs": "BELOW SPEED",
    "ground_alt": "BELOW ALTITUDE",
    "ground_min": "AFTER",
    "ground_alpha": "FADE TO",
    "track_cols": "COLUMNS",
    "track_sort": "SORT BY",
    "track_desc": "DESCENDING",
    "sort_floor": "DIMMEST (RADAR)",
    "short_names": "DROP THE AIRPORT FROM NAMES",
}

# The choices drawn as a dropdown, for having too many names for a row of
# buttons; every other choice is segments.
DROPDOWNS = frozenset({"palette", "font", "track_sort"})
TABLES = {key: spec for key, spec in ON_THE_PAGE.items() if isinstance(spec, Table)}


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
        if "data-pref" in attrs:
            control = {
                "key": attrs["data-pref"], "tag": tag, "attrs": attrs, "options": [], "headings": [],
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
    parsed = Sheet()
    parsed.feed(INDEX_HTML.read_text())
    return parsed


def control(sheet: Sheet, key: str) -> dict:
    found = [c for c in sheet.controls if c["key"] == key]
    assert len(found) == 1, f"{key} has {len(found)} controls"
    return found[0]


def names(found: dict) -> list[str]:
    """What a choice or a subset control offers, in order."""
    if found["tag"] == "select":
        return found["options"]
    return found["attrs"].get("data-values", "").split()


def test_every_setting_but_the_panes_has_exactly_one_control_and_no_control_is_for_anything_else(sheet):
    assert sorted(c["key"] for c in sheet.controls) == sorted(set(SCHEMA) - PANE_BOUND)


def test_the_pane_bound_settings_are_in_the_schema_and_have_no_control_in_the_sheet(sheet):
    assert PANE_BOUND <= set(SCHEMA)
    assert not PANE_BOUND & {c["key"] for c in sheet.controls}


def test_the_plans_tables_name_every_setting_on_the_page_once():
    assert sorted(TAB_OF) == sorted(ON_THE_PAGE)
    assert sum(len(keys) for keys in TABS.values()) == len(TAB_OF)
    assert set(ROWS) == set(ON_THE_PAGE)


def test_the_controls_are_in_the_config_sheet_in_the_schemas_order(sheet):
    assert {c["dialog"] for c in sheet.controls} == {"config-sheet"}
    assert [c["key"] for c in sheet.controls] == list(ON_THE_PAGE)


def test_the_sheet_has_four_tabs_each_labelling_its_panel(sheet):
    assert [t["dialog"] for t in sheet.tablists] == ["config-sheet"]
    assert [t["text"] for t in sheet.tabs] == list(TABS)
    # the first is the one shown at first, and a tab names the panel it shows
    assert [t.get("aria-selected") for t in sheet.tabs] == ["true", "false", "false", "false"]
    assert [p["id"] for p in sheet.panels] == [t["aria-controls"] for t in sheet.tabs]
    assert [p["labelledby"] for p in sheet.panels] == [t["id"] for t in sheet.tabs]
    assert {p["dialog"] for p in sheet.panels} == {"config-sheet"}
    for tab in sheet.tabs:  # the tab bar keeps the segment buttons' look
        assert {"btn", "seg"} <= set(tab["class"].split()) and tab.get("type") == "button"


@pytest.mark.parametrize("key", list(ON_THE_PAGE))
def test_a_control_sits_in_the_tab_the_plan_names(sheet, key):
    assert sheet.tab_named(control(sheet, key)["panel"]) == TAB_OF[key]


def test_output_is_gone_and_the_volume_is_not_in_the_sheet(sheet):
    """The master volume is not a pref; it is in the frequencies pane (phase
    G decision 3), and the section that held it goes."""
    assert "OUTPUT" not in sheet.sections and "MASTER VOLUME" not in sheet.text
    assert "volume" in sheet.ids and sheet.ids["volume"] is None
    assert "volume-value" in sheet.ids and sheet.ids["volume-value"] is None


def test_limits_is_gone(sheet):
    assert "LIMITS" not in sheet.text and "STREAMS AT ONCE" not in sheet.text
    assert "max-streams" not in sheet.ids


@pytest.mark.parametrize("key", list(ON_THE_PAGE))
def test_a_control_sits_in_the_row_the_plan_names(sheet, key):
    assert control(sheet, key)["row"] == ROWS[key]


def assert_slider_range(attrs: dict, spec: Number, what: str):
    """`attrs` give a slider (min, max, step), or a table's column of them
    (data-min, data-max, data-step), exactly the schema's numbers."""
    prefix = "" if "min" in attrs else "data-"
    got = (int(attrs[prefix + "min"]), int(attrs[prefix + "max"]), int(attrs.get(prefix + "step", "1")))
    # The schema's own step, so the slider offers exactly the values the
    # server takes; it lands on both ends and on the default (test_prefs).
    assert got == (spec.low, spec.high, spec.step), what


@pytest.mark.parametrize("key", [k for k, spec in ON_THE_PAGE.items() if isinstance(spec, Number)])
def test_a_numbers_slider_has_the_schemas_range(sheet, key):
    spec, found = SCHEMA[key], control(sheet, key)
    attrs = found["attrs"]
    assert found["tag"] == "input" and attrs.get("type") == "range"
    assert_slider_range(attrs, spec, key)


def test_the_range_moves_in_steps_of_ten(sheet):
    assert control(sheet, "range_nm")["attrs"]["step"] == "10"


@pytest.mark.parametrize("key", [k for k, spec in ON_THE_PAGE.items() if isinstance(spec, Choice)])
def test_a_choice_offers_the_schemas_names_in_order(sheet, key):
    found = control(sheet, key)
    if key in DROPDOWNS:
        assert found["tag"] == "select"
    else:
        assert found["tag"] == "div" and found["attrs"].get("data-kind") == "choice"
        assert "segments" in found["attrs"]["class"].split()
    assert names(found) == list(SCHEMA[key].names)


def test_the_theme_is_a_dropdown_and_display_is_segments(sheet):
    assert control(sheet, "palette")["tag"] == "select"
    found = control(sheet, "display")
    assert found["tag"] == "div" and "segments" in found["attrs"]["class"].split()


def test_glow_the_choice_has_no_control(sheet):
    """Glow is three numbers now (phase G decision 15), each a slider."""
    assert "glow" not in [c["key"] for c in sheet.controls]
    assert "glow" not in SCHEMA


@pytest.mark.parametrize("key", [k for k, spec in ON_THE_PAGE.items() if isinstance(spec, Subset)])
def test_a_subset_offers_the_schemas_names_in_order(sheet, key):
    found = control(sheet, key)
    assert found["attrs"].get("data-kind") == "subset"
    assert names(found) == list(SCHEMA[key].names)


@pytest.mark.parametrize("key", [k for k, spec in ON_THE_PAGE.items() if isinstance(spec, Flag)])
def test_a_flag_is_declared_a_flag(sheet, key):
    found = control(sheet, key)
    assert found["attrs"].get("data-kind") == "flag"
    assert "data-values" not in found["attrs"]


# -- tables ------------------------------------------------------------------------


def table_rows(found: dict) -> dict[str, list[str]]:
    """data-rows: each row's name and its columns, as `ROW:col,col ROW:col`."""
    out = {}
    for item in found["attrs"].get("data-rows", "").split():
        row, _, columns = item.partition(":")
        out[row] = columns.split(",") if columns else []
    return out


@pytest.mark.parametrize("key", list(TABLES))
def test_a_table_is_declared_a_table(sheet, key):
    found = control(sheet, key)
    assert found["tag"] == "table" and found["attrs"].get("data-kind") == "table"


@pytest.mark.parametrize("key", list(TABLES))
def test_a_table_declares_the_schemas_rows_in_order_each_with_exactly_its_columns(sheet, key):
    spec, found = SCHEMA[key], control(sheet, key)
    rows = table_rows(found)
    assert list(rows) == list(spec.rows)
    for row, columns in rows.items():
        # in the table's column order, so the grid's cells line up under their headings
        assert columns == [c for c in spec.columns if c in spec.rows[row]], row


@pytest.mark.parametrize("key", list(TABLES))
def test_a_tables_columns_are_the_schemas_in_order_each_with_a_heading(sheet, key):
    spec, found = SCHEMA[key], control(sheet, key)
    assert found["attrs"].get("data-columns", "").split() == list(spec.columns)
    assert [h["attrs"]["data-column"] for h in found["headings"]] == list(spec.columns)
    for heading in found["headings"]:
        assert heading["text"] == heading["attrs"]["data-column"].upper()


@pytest.mark.parametrize("key", list(TABLES))
def test_a_tables_column_declares_its_kind_and_the_schemas_range_or_names(sheet, key):
    spec, found = SCHEMA[key], control(sheet, key)
    for heading in found["headings"]:
        attrs, column = heading["attrs"], spec.columns[heading["attrs"]["data-column"]]
        if isinstance(column, Number):
            assert attrs.get("data-kind") == "number", attrs
            assert "data-unit" in attrs, attrs
            assert_slider_range(attrs, column, attrs["data-column"])
        elif isinstance(column, Flag):
            assert attrs.get("data-kind") == "flag" and "data-values" not in attrs, attrs
        else:
            assert isinstance(column, Choice)
            assert attrs.get("data-kind") == "choice", attrs
            assert attrs.get("data-values", "").split() == list(column.names)


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
