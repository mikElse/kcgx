"""The config sheet's controls agree with `kcgx.prefs.SCHEMA`.

No browser: `index.html` declares one `[data-pref]` control per setting,
with its range or its names written in the markup, and the script binds
them without knowing any setting by name. So this, and not a copy of the
choices in the script, is what stops the page and the server drifting.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from kcgx.prefs import PALETTES, SCHEMA, Choice, Flag, Number, Subset

WEB = Path(__file__).parent.parent / "src" / "kcgx" / "web"
INDEX_HTML = WEB / "index.html"
SHEETS_JS = WEB / "static" / "js" / "sheets.js"
COCKPIT_CSS = WEB / "static" / "cockpit.css"

# The settings table in the plan: the words beside each control.
ROWS = {
    "palette": "THEME",
    "glow": "GLOW",
    "display": "DISPLAY",
    "scan_opacity": "SCANLINE OPACITY",
    "scan_size": "SCANLINE SIZE",
    "lamps": "STATUS LAMPS",
    "teletype": "TELETYPE",
    "range_nm": "RANGE",
    "tag_fields": "FLIGHT TAG",
    "box_items": "LABEL BOXES",
    "box_fill": "BOX FILL",
    "box_pad": "BOX PADDING",
    "box_border": "BOX BORDER",
    "box_width": "BORDER WIDTH",
}

SECTIONS = {
    "OUTPUT": [],
    "LOOK": ["palette", "glow", "display", "scan_opacity", "scan_size"],
    "LAYOUT": ["lamps", "teletype"],
    "RADAR": ["range_nm", "tag_fields", "box_items", "box_fill", "box_pad", "box_border", "box_width"],
}


class Sheet(HTMLParser):
    """The `[data-pref]` controls of the page, in document order, each with
    the dialog it is in, the section heading above it, the words of its row
    and (for a <select>) its options."""

    def __init__(self):
        super().__init__()
        self.controls: list[dict] = []
        self.sections: list[str] = []  # the config sheet's <h3>s
        self.ids: set[str] = set()
        self.text = ""  # everything said inside the config sheet
        self._dialog = None
        self._heading = None  # collecting an <h3>
        self._row = None  # the words of the row being read: its first <span>
        self._row_open = False
        self._select = None
        self._option = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "dialog":
            self._dialog = attrs.get("id")
        elif tag == "h3" and self._dialog == "config-sheet":
            self._heading = ""
        elif "field-row" in (attrs.get("class") or "").split():
            self._row, self._row_open = None, False
        elif tag == "span" and self._row is None and not self._row_open:
            self._row, self._row_open = "", True
        if "data-pref" in attrs:
            control = {
                "key": attrs["data-pref"], "tag": tag, "attrs": attrs, "options": [],
                "dialog": self._dialog, "section": self.sections[-1] if self.sections else None,
                "row": self._row,
            }
            self.controls.append(control)
            if tag == "select":
                self._select = control
        if tag == "option" and self._select is not None:
            self._option = {"value": attrs.get("value"), "text": ""}

    def handle_endtag(self, tag):
        if tag == "dialog":
            self._dialog = None
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

    def handle_data(self, data):
        if self._dialog == "config-sheet":
            self.text += data
        if self._heading is not None:
            self._heading += data
        if self._row_open:
            self._row += data
        if self._option is not None:
            self._option["text"] += data


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


def test_every_setting_has_exactly_one_control_and_no_control_is_for_anything_else(sheet):
    assert sorted(c["key"] for c in sheet.controls) == sorted(SCHEMA)


def test_the_controls_are_in_the_config_sheet_in_the_schemas_order(sheet):
    assert {c["dialog"] for c in sheet.controls} == {"config-sheet"}
    assert [c["key"] for c in sheet.controls] == list(SCHEMA)


def test_the_sheets_sections_are_output_look_layout_and_radar(sheet):
    assert sheet.sections == list(SECTIONS)
    for section, keys in SECTIONS.items():
        assert [c["key"] for c in sheet.controls if c["section"] == section] == keys, section
    assert "volume" in sheet.ids  # OUTPUT holds the master volume, which is not a pref


def test_limits_is_gone(sheet):
    assert "LIMITS" not in sheet.text and "STREAMS AT ONCE" not in sheet.text
    assert "max-streams" not in sheet.ids


@pytest.mark.parametrize("key", list(SCHEMA))
def test_a_control_sits_in_the_row_the_plan_names(sheet, key):
    assert control(sheet, key)["row"] == ROWS[key]


@pytest.mark.parametrize("key", [k for k, spec in SCHEMA.items() if isinstance(spec, Number)])
def test_a_numbers_slider_has_the_schemas_range(sheet, key):
    spec, found = SCHEMA[key], control(sheet, key)
    attrs = found["attrs"]
    assert found["tag"] == "input" and attrs.get("type") == "range"
    assert (int(attrs["min"]), int(attrs["max"])) == (spec.low, spec.high)
    # Whole steps that land on both ends and on the default, so the slider
    # can show every value it starts at and send only whole numbers.
    step = int(attrs.get("step", "1"))
    assert step >= 1
    assert (spec.high - spec.low) % step == 0 and (spec.default - spec.low) % step == 0


def test_the_range_moves_in_steps_of_ten(sheet):
    assert control(sheet, "range_nm")["attrs"]["step"] == "10"


@pytest.mark.parametrize("key", [k for k, spec in SCHEMA.items() if isinstance(spec, Choice)])
def test_a_choice_offers_the_schemas_names_in_order(sheet, key):
    found = control(sheet, key)
    assert found["tag"] == "select" or found["attrs"].get("data-kind") == "choice"
    assert names(found) == list(SCHEMA[key].names)


def test_the_theme_is_a_dropdown_and_glow_and_display_are_segments(sheet):
    assert control(sheet, "palette")["tag"] == "select"
    for key in ("glow", "display"):
        found = control(sheet, key)
        assert found["tag"] == "div" and "segments" in found["attrs"]["class"].split()


@pytest.mark.parametrize("key", [k for k, spec in SCHEMA.items() if isinstance(spec, Subset)])
def test_a_subset_offers_the_schemas_names_in_order(sheet, key):
    found = control(sheet, key)
    assert found["attrs"].get("data-kind") == "subset"
    assert names(found) == list(SCHEMA[key].names)


@pytest.mark.parametrize("key", [k for k, spec in SCHEMA.items() if isinstance(spec, Flag)])
def test_a_flag_is_declared_a_flag(sheet, key):
    found = control(sheet, key)
    assert found["attrs"].get("data-kind") == "flag"
    assert "data-values" not in found["attrs"]


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
