"""Values at the bar ends instead of the axis (decisions/087; reference 'Labels on the End' in 14 of its 15 bars, another
'labels on the bar instead of the axis').

Spec: bar.labels: end | none.
- end (the default of a horizontal bar of members, not stacked, without a plan or a target line): each bar's value
  at its end (pane mark-labels-show, culled), the measure's axis hidden (axis display false). Desktop shortens the
  longest bar so that its label fits the pane (decisions/077: 11-14px beyond the label); the pane must hold the
  widest label, LABEL_ROOM_PX and BAR_MIN_PX of bar, else the build fails naming the sheet ('too narrow'). The row
  headers get a width set, so the gate knows the pane.
- none: the axis as before (a spec where the axis is needed: many bars, a scale to read).
Not by default (decisions/087): a stacked bar (a label per segment, the total nowhere), a vertical bar (labels over
the columns crowd), a bar along a date (090), a plan (two labels per row), a target (095: a line across each bar,
where its label would stand). end is refused on the first four; with a target it may be asked for. A line across
all the bars (avg, median, const, param, band) has its own label: the bars keep theirs and lose the axis
(decisions/165, the user's choice of 2026-10-31; 087 kept the axis there).
bar.value_column: left (decisions/095, reference 'Labels on the Left'): the value as a second row header, discrete
([sum:Sales:ok], VALUE_PX wide, right-aligned), the bar without a label and its axis hidden. A stacked bar's
total 'end' (reflines.py) hides the axis the same way.
Every horizontal bar's row headers: 10pt (FONT bar_header) in the text color (reference: 10pt #333333).
A bar with a sign (negative values in its expected numbers, color good / a diverging scale): the zero line solid, the
rest of the declutter as it was (design rule I1, reference Lollipop / Variance).
"""
import xml.etree.ElementTree as ET

from . import colors, formats
from .design import COLOR, FONT, row_header_fit_px, text_px
from .registry import LABEL_ROOM_PX

MODES = ("end", "none")
VALUE_PX = 52  # value_column left: the reference's width of the value header
BAR_MIN_PX = 40  # the longest bar beside its label at the least: shorter, the bars no longer compare
LABEL_PT = 9  # Desktop's mark label font (the registry's measured widths: '52%' 32px)
FLOOR_PX = LABEL_ROOM_PX + BAR_MIN_PX + text_px("0", LABEL_PT)  # the gate's floor: the shortest label possible


def horizontal(s):
    return s["type"] == "bar" and s.get("orientation", "horizontal") == "horizontal" and "margin" not in s


def eligible(s):
    """A horizontal bar of members, one bar per row: a label at its end says its value."""
    return (horizontal(s) and colors.series_field(s) is None and colors.kind(s) != "plan"
            and not s.get("date_level"))


def per_bar(s):
    """A reference line drawn across each bar (target, bullet zones): a label at the bar's end would stand on it."""
    from .reflines import lines
    return any(r["type"] == "target" for r in lines(s))


def mode(s):
    """'end' | 'none' of a bar; None for another sheet."""
    if s["type"] != "bar":
        return None
    return s.get("labels") or ("end" if eligible(s) and not per_bar(s) and "value_column" not in s else "none")


def value_left(s):
    return s["type"] == "bar" and s.get("value_column") == "left"


def value_field(b, s):
    """The value header of value_column left: the measure discrete, [sum:Sales:ok] (as in the reference)."""
    f = b._measure(s["measure"])
    f.type, f.name = "ordinal", f.name[:-3] + "ok]"
    return f


def no_axis(s):
    """The bar's numbers are on the marks or beside them: its measure axis hidden."""
    return mode(s) == "end" or value_left(s) or (s["type"] == "bar" and s.get("total") == "end")


def check(spec):
    for s in spec["sheets"]:
        if s["type"] == "bar" and s.get("labels") == "end" and not eligible(s):
            why = ("a vertical bar" if s.get("orientation") == "vertical" else "a bar along a date" if
                   s.get("date_level") else "a plan" if colors.kind(s) == "plan" else "a stacked bar")
            raise ValueError(f"Sheet '{s['name']}': labels 'end' is for a horizontal bar of members, not {why} "
                             f"(decisions/087); remove 'labels'")
        if value_left(s) and (not eligible(s) or s.get("labels") == "end" or "table_calc" in s["measure"]):
            raise ValueError(f"Sheet '{s['name']}': value_column 'left' is for a horizontal bar of members (not "
                             f"stacked, no plan, no date, no table calculation) without labels 'end' "
                             f"(decisions/095)")


def style(b, style_el, s, fields):
    """The worksheet style of a horizontal bar: its row headers 10pt in the text color; with end labels the measure's
    axis hidden and the row header width set."""
    if not horizontal(s):
        return
    d, m = fields[0], fields[1]
    label = colors._rule(style_el, "label", before=("mark", "pane", "worksheet", "gridline", "zeroline", "table-div"))
    ET.SubElement(label, "format", attr="color", field=b.q(d.name), value=COLOR["text"])
    ET.SubElement(label, "format", attr="font-size", field=b.q(d.name), value=str(FONT["bar_header"]))
    if value_left(s):  # reference: the value header right-aligned; 10pt in the text color as the member headers
        v = b.q(value_field(b, s).name)
        for attr, value in [("color", COLOR["text"]), ("font-size", str(FONT["bar_header"])), ("text-align", "right")]:
            ET.SubElement(label, "format", attr=attr, field=v, value=value)
        if _values(b, s):  # the format value_px measured: Desktop draws a discrete real with all its decimals
            from .registry import _fmt  # ('36,571.62' cut to '36,57..' in a header sized for '36,572', 152)
            ET.SubElement(label, "format", attr="text-format", field=v,
                          value=formats.tableau(_fmt(b, s["measure"], _values(b, s))))
    if not no_axis(s):
        return
    axis = colors._rule(style_el, "axis", before=())
    at = len([f for f in axis if f.get("field")])  # after the field formats (title), before the declutter
    axis.insert(at, ET.Element("format", {"attr": "display", "class": "0", "field": b.q(m.name), "scope": "cols",
                                          "value": "false"}))
    header = colors._rule(style_el, "header", before=("label", "mark", "pane", "worksheet", "gridline", "zeroline",
                                                       "table-div"))
    if header.find(f"format[@attr='width'][@field='{b.q(d.name)}']") is None:  # the field label shown: ink.row_header
        ET.SubElement(header, "format", attr="width", field=b.q(d.name), value=str(header_px(b, d)))
    if value_left(s):
        ET.SubElement(header, "format", attr="width", field=b.q(value_field(b, s).name), value=str(value_px(b, s)))


def value_px(b, s):
    """px of the value header: the reference's VALUE_PX, wider when the widest value would be cut."""
    from .design import HEADER_TEXT_PAD_PX
    from .registry import _fmt
    values = _values(b, s)
    if not values:
        return VALUE_PX
    fmt = _fmt(b, s["measure"], values)
    return max([VALUE_PX] + [text_px(formats.render(x, fmt), FONT["bar_header"]) + HEADER_TEXT_PAD_PX for x in values])


def header_px(b, d):
    """px of a bar's row headers without the field label: its longest value at the bar header font."""
    return row_header_fit_px(b.fields.labels(d.col), "", pt=FONT["bar_header"])


def _values(b, s):
    return [x for v in b.expected.get(s["name"], {}).values()
            for x in (v.values() if isinstance(v, dict) else [v]) if isinstance(x, (int, float)) and x is not None]


def signed(b, s):
    """Does the bar have a sign: bars left (down) of zero?"""
    c = s.get("color")
    if colors.kind(s) == "good" or (isinstance(c, dict) and c.get("scale") == "diverging"):
        return True
    return any(x < 0 for x in _values(b, s))


def need_px(b, s):
    """px of pane the labelled bars need: the widest label on each side of zero with its room, and BAR_MIN_PX."""
    from .registry import _fmt
    values = _values(b, s)
    if not values:
        return FLOOR_PX
    fmt = _fmt(b, s["measure"], values)
    need = BAR_MIN_PX
    for side in ([x for x in values if x >= 0], [x for x in values if x < 0]):
        if side:
            need += max(text_px(formats.render(x, fmt), LABEL_PT) for x in side) + LABEL_ROOM_PX
    return need


def zero_line(b, ws, s):
    """The zero line of a bar with a sign: solid along the measure's axis (reference Lollipop: line-visibility on,
    line-pattern-only solid); the other direction stays off."""
    rule = ws.find("table/style/style-rule[@element='zeroline']")
    if rule is None:  # declutter off: Desktop draws its zero lines anyway
        return
    scope = "cols" if s.get("orientation", "horizontal") == "horizontal" else "rows"
    other = "rows" if scope == "cols" else "cols"
    for f in list(rule):
        rule.remove(f)
    for attrs in ({"attr": "line-visibility", "scope": scope, "value": "on"},
                  {"attr": "line-visibility", "scope": other, "value": "off"},
                  {"attr": "line-pattern-only", "scope": scope, "value": "solid"}):
        ET.SubElement(rule, "format", attrs)


def finish(b, wb):
    """After the dashboards: the zero lines (from the expected numbers) and the room for the end labels in each
    zone of a labelled bar ('too narrow' fails the build, as the other minimums: rebuild widens the cell)."""
    wss = {w.get("name"): w for w in wb.iter("worksheet")}
    bars = {s["name"]: s for s in b.worksheets if s["type"] == "bar"}
    for name, s in bars.items():
        if name in wss and signed(b, s):
            with b._source_of(name):
                zero_line(b, wss[name], s)
    for db in wb.iter("dashboard"):
        size = db.find("size")
        dims = (int(size.get("maxwidth") or size.get("minwidth")), int(size.get("maxheight") or size.get("minheight")))
        for z in db.find("zones").iter("zone"):
            s = bars.get(z.get("name"))
            if s is None or z.get("type-v2") or mode(s) != "end":
                continue
            with b._source_of(s["name"]):
                have = pane_px(wss[s["name"]], z, dims)
                need = need_px(b, s)
            if have < need:
                raise ValueError(f"Sheet '{s['name']}': the cell is too narrow for the values at the bar ends "
                                 f"({have}px of bars beside the row headers on dashboard '{db.get('name')}', {need}px "
                                 f"needed: the widest label, {LABEL_ROOM_PX}px of room and {BAR_MIN_PX}px of bar); "
                                 f"give the cell more width, or labels: none for the axis")


def pane_px(ws, zone, size):
    """px of a horizontal bar's pane: its zone inside the margins less its row header widths."""
    from . import fit
    w, _ = fit.zone_px(zone, size)
    heads = sum(int(f.get("value")) for f in ws.findall("table/style/style-rule[@element='header']/format")
                if f.get("attr") == "width")
    return w - heads
