"""Small multiples in rows (decisions/144): facet {field, cols: N} on a line / area lays the panels out N to a row,
the member's name at its line's end; the date axis of every facet shows a few ticks, not one.

Spec: facet {field, cols?} (compareviz.facet, decisions/141); cols N: a grid of N panels a row, panel i at row i // N,
column i % N, the members in their alphabetic order (a sheet filter on the field: the members it keeps).

XML (forms from Desktop books, Tableau Public: 'Consumer Confidence Index', 'Small Multiple Line Chart'):
- (row * measure) on Rows, (column * date) on Columns, the row / column fields' headers hidden ('label' display
  false), the member on Detail and as the label at the line's end (CCI: the country's code at its line's end);
- the books number the panels with INDEX() (a table calc at the member's level); here a CASE over the members from
  the data: no table calc addressing to get wrong when a member lacks a period;
- the date axis: <encoding attr='space' ... major-origin major-spacing major-units scope='cols' type='space'/> (CCI):
  a tick every span / 2 periods, so each narrow panel names its start, middle and end; the origin with its time, as
  Desktop re-saves it over a truncated date ('#2010-01-01 00:00:00#').
"""
import math
import xml.etree.ElementTree as ET

from .compareviz import facet

UNITS = {"year": "years", "quarter": "quarters", "month": "months", "week": "weeks", "day": "days"}
MAX_SIDE = 9  # rows and columns of the grid: '1'..'9' sort as numbers


def cols(s):
    f = facet(s)
    return f.get("cols") if f and s["type"] in ("line", "area") else None


def row_calc(s):
    return f"{s['name']} · Panel row"


def col_calc(s):
    return f"{s['name']} · Panel column"


def members(s, prof):
    """The panels' members: those the sheet's own filter on the field keeps, else every member, alphabetic."""
    field = s["facet"]["field"]
    kept = next((f["default"] for f in s.get("filters", []) if f["field"] == field and not f.get("exclude")
                 and isinstance(f.get("default"), list)), None)
    return sorted(kept if kept is not None else [v for v in prof.col(field).distinct if v not in (None, "")])


def check(spec, prof):
    for s in spec["sheets"]:
        n = cols(s)
        if n is None:
            continue
        if isinstance(s.get("color"), str):
            raise ValueError(f"Sheet '{s['name']}': facet cols names each panel at its line's end; a color field "
                             f"would label every line: drop color or the cols")
        rows = math.ceil(len(members(s, prof)) / n)
        if n > MAX_SIDE or rows > MAX_SIDE:
            raise ValueError(f"Sheet '{s['name']}': facet cols {n} gives {rows} rows; at most {MAX_SIDE} each way")


def calcs(spec, prof=None):
    """The panel's row and column: a CASE over the members (strings, discrete: '1', '2', ...)."""
    out = []
    for s in spec["sheets"]:
        n = cols(s)
        if n is None or prof is None:
            continue
        field, ms = s["facet"]["field"], members(s, prof)
        for name, at in ((row_calc(s), lambda i: i // n), (col_calc(s), lambda i: i % n)):
            whens = " ".join(f'WHEN "{m}" THEN "{at(i) + 1}"' for i, m in enumerate(ms))
            out.append({"name": name, "formula": f"CASE [{field}] {whens} END"})
    return out


def encode(b, s, fields, enc):
    """The row and column fields after the facet's; the member as the label at its line's end."""
    if cols(s) is None:
        return False
    member = fields[-1]  # compareviz.facet_field's, just before
    fields += [b._dim(row_calc(s)), b._dim(col_calc(s))]
    enc.append(("text", b.q(member.name)))
    return True


def _grid(b, s):
    return b.q(b._dim(row_calc(s)).name), b.q(b._dim(col_calc(s)).name)


def shelves(b, s, fields, rows_el, cols_el):
    """(row * measure) on Rows, (column * date) on Columns, as CCI saves them (after compareviz.shelves)."""
    if cols(s) is None:
        return
    r, c = _grid(b, s)
    rows_el.text = f"({r} * {b.q(fields[1].name)})"
    cols_el.text = f"({c} * {b.q(fields[0].name)})"


def style(b, style_el, s, fields):
    """The grid's row / column headers hidden; every facet's date axis with ticks at its start, middle and end."""
    from .colors import _rule
    if not facet(s) or s["type"] not in ("line", "area"):
        return
    if cols(s) is not None:
        lab = _rule(style_el, "label", before=("pane", "table", "worksheet", "gridline", "zeroline", "table-div"))
        for ref in _grid(b, s):
            ET.SubElement(lab, "format", attr="display", field=ref, value="false")
        ws = _rule(style_el, "worksheet", before=("gridline", "zeroline", "table-div"))
        if ws.find("format[@attr='display-field-labels'][@scope='rows']") is None:
            ET.SubElement(ws, "format", attr="display-field-labels", scope="rows", value="false")
    level = s["date"].get("level", "month")
    first, last = _span(b, s["date"]["field"], level)
    if first is None:
        return
    span = _periods(first, last, level)
    axis = style_el.find("style-rule[@element='axis']")
    if axis is None:
        axis = ET.Element("style-rule", element="axis")
        style_el.insert(0, axis)
    ET.SubElement(axis, "encoding", {"attr": "space", "class": "0", "field": b.q(fields[0].name),
                                     "field-type": "quantitative", "major-origin": f"#{first.isoformat()} 00:00:00#",
                                     "major-spacing": f"{max(1, math.ceil(span / 2))}.0",
                                     "major-units": UNITS[level], "scope": "cols", "type": "space"})


def pane_style(pane, s):
    """The member's name at the line's last point (CCI); build shows the labels, culled (encode returned True)."""
    if cols(s) is None:
        return
    st = pane.find("style")
    st = ET.SubElement(pane, "style") if st is None else st
    rule = st.find("style-rule[@element='mark']")
    rule = ET.SubElement(st, "style-rule", element="mark") if rule is None else rule
    for attr, value in (("mark-labels-mode", "line-ends"), ("mark-labels-line-first", "false")):
        ET.SubElement(rule, "format", attr=attr, value=value)


def _span(b, field, level):
    from . import dates
    ds = [dates.to_date(r[field]) for r in b.prof.rows if r[field] not in (None, "")]
    if not ds:
        return None, None
    day = lambda d: d.date() if hasattr(d, "date") else d  # noqa: E731  a datetime's day
    return dates.trunc(day(min(ds)), level), dates.trunc(day(max(ds)), level)


def _periods(first, last, level):
    months, days = (last.year - first.year) * 12 + last.month - first.month, (last - first).days
    return {"year": last.year - first.year, "quarter": months // 3, "month": months, "week": days // 7}.get(level, days)
