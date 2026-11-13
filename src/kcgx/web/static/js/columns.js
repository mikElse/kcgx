// Every column the tracks table can show (phase G, Task 8), keyed by the
// names prefs.track_cols and prefs.track_sort use, in the schema's order
// (kcgx.prefs.TRACK_COLS). The table and the radar's data box (Task 12) both
// read an aircraft through these, so a value reads the same in each.
//
// Each column has:
//   key     the schema's name: "ALT"
//   title   the header: "ALT FT"
//   text    (ac) => the cell's text; "" for anything the aircraft does not
//           report, including fields the server does not send yet
//   sort    (ac) => the value the table sorts by
//   filter  "text" (a case-insensitive substring) or "number" (min and max)
//   num     true when the cell is set right-aligned, as figures are
//
// The aircraft is one entry of an aircraft frame's `ac` (kcgx.radar
// Radar.frame): hex, label, type, lat, lon, alt (feet, or "GND"), gs, trk,
// sq, age, dist, brg; and from Task 7, reg, desc, oper, vs, cat and still.

const blank = (value) => value === null || value === undefined;
const plain = (value) => (blank(value) ? "" : String(value));
const three = (value) => (blank(value) ? "" : String(value).padStart(3, "0"));
const fixed = (places) => (value) => (blank(value) ? "" : Number(value).toFixed(places));
const figure = (value) => (blank(value) ? -1 : value);

function textColumn(key, title, field, extra = {}) {
  const text = (ac) => plain(ac[field]);
  return { key, title, filter: "text", num: false, text, sort: text, ...extra };
}

function numberColumn(key, title, field, show = plain, extra = {}) {
  return {
    key, title, filter: "number", num: true,
    text: (ac) => show(ac[field]),
    sort: (ac) => figure(ac[field]),
    ...extra,
  };
}

export const COLUMNS = [
  textColumn("CALLSIGN", "CALLSIGN", "label"),
  textColumn("TYPE", "TYPE", "type"),
  textColumn("REG", "REG", "reg"),
  numberColumn("ALT", "ALT FT", "alt", plain, { sort: (ac) => (ac.alt === "GND" ? 0 : figure(ac.alt)) }),
  numberColumn("VS", "V/S FPM", "vs"),
  numberColumn("GS", "GS KT", "gs"),
  numberColumn("TRK", "TRK", "trk", three),
  numberColumn("DIST", "DIST NM", "dist", fixed(1)),
  numberColumn("BRG", "BRG", "brg", three),
  // A squawk is four figures and set as one, but it is a code: matched as text.
  textColumn("SQWK", "SQWK", "sq", { num: true }),
  textColumn("HEX", "HEX", "hex", { text: (ac) => plain(ac.hex).toUpperCase(), sort: (ac) => plain(ac.hex) }),
  textColumn("DESC", "DESC", "desc"),
  textColumn("OPER", "OPER", "oper"),
  textColumn("CAT", "CAT", "cat"),
  numberColumn("AGE", "AGE S", "age", fixed(0)),
  numberColumn("LAT", "LAT", "lat", fixed(4)),
  numberColumn("LON", "LON", "lon", fixed(4)),
];

// The same columns by name: COLUMN.ALT.
export const COLUMN = Object.fromEntries(COLUMNS.map((column) => [column.key, column]));
