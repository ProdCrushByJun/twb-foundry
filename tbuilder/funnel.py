"""Funnel (decisions/159): a stage per row, a level bar centered on zero as long as the stage's value, the
conversion from the stage before it beside the value.

Spec: {type: funnel, dimension, measure, sort?: desc | none, conversion?: previous | first | none}
- dimension: the stages, top to bottom; sort desc (default) by the value, none in the field's manual order
  (fields.<dim>.order, required: stages by name are not a process);
- measure: the stage's value (users, deals);
- conversion: previous (default) the value over the stage before it (the first stage has none; 0 %), first over the
  first stage (0.0 %: late stages keep a few % of the first), none only the value.

XML (reference Funnel Chart Catalogue 'Funnel with Gantt bars'; the Gantt bar of waterfall / gantt):
<mark class='GanttBar'/>, the start -value / 2 on Columns (an aggregate calc), the value on <size> (a Gantt bar runs
from its start by its size: to +value / 2), the stages on Rows, sorted by the value (computed-sort,
'Traditional Funnel Chart', 'Funnel I') or in their manual order. The conversion is
a table calc along the stages (LOOKUP(.., -1) / WINDOW_SUM(.., FIRST(), FIRST())), as the % labels of the references
(pcto, pcva quick table calcs); the axis has no meaning (its zero is the funnel's middle), so it is hidden.
The labels (value, conversion) sit left of each bar's start; the widest bar would leave them no room and Desktop puts
them inside it (grey on the accent, snapshot): an invisible line at LEFT_ROOM % of the smallest start widens the axis
to the left (reference 'funnel': formula min, percentage-bands, reference-line-value percentage 130;
'Progress Bars Variations' 2024.3 for the form without tooltip-type).
"""
import xml.etree.ElementTree as ET

TYPE = "funnel"
LEFT_ROOM = 140  # % of the smallest start (-max / 2): 0.2 max left of the widest bar for its labels
REFLINE = "refline0"


def is_funnel(s):
    return s["type"] == TYPE


def sort(s):
    return s.get("sort", "desc") if is_funnel(s) else None


def conversion(s):
    return s.get("conversion", "previous")


def start_calc(s):
    return f"{s['name']} · Start"


def conv_calc(s):
    return f"{s['name']} · Conversion"


def _agg(m, calc_names):
    return (f"[{m['field']}]" if m["field"] in calc_names and "agg" not in m
            else f"{m.get('agg', 'sum').upper()}([{m['field']}])")


def check(spec):
    for s in spec["sheets"]:
        if not is_funnel(s):
            continue
        if "table_calc" in s["measure"]:
            raise ValueError(f"Sheet '{s['name']}': a funnel computes its own conversion; give it the plain measure")
        if sort(s) == "none" and "order" not in spec.get("fields", {}).get(s["dimension"], {}):
            raise ValueError(f"Sheet '{s['name']}': sort none keeps the stages in their process order: give "
                             f"fields.{s['dimension']}.order (or sort desc, by the value)")


def calcs(spec):
    """The bar's start (half the value left of zero) and the conversion (a table calc along the stages)."""
    names = {c["name"] for c in spec.get("calcs", [])}
    out = []
    for s in spec["sheets"]:
        if not is_funnel(s):
            continue
        a, d = _agg(s["measure"], names), s["dimension"]
        out.append({"name": start_calc(s), "formula": f"-{a} / 2"})
        conv = conversion(s)
        if conv != "none":
            base = f"LOOKUP({a}, -1)" if conv == "previous" else f"WINDOW_SUM({a}, FIRST(), FIRST())"
            out.append({"name": conv_calc(s), "formula": f"{a} / {base}", "compute_using": [d],
                        "format": "pct0" if conv == "previous" else "pct1"})
    return out


def shape(b, s):
    """-> fields, rows, cols, encodings, labels, measure names (build.sheet_shape): the stages on Rows, the start on
    Columns, the value on Size and Text, the conversion on Text."""
    d, m = b._dim(s["dimension"]), b._measure(s["measure"])
    start = b._measure({"field": start_calc(s)})
    fields, enc = [d, start, m], [("size", b.q(m.name)), ("text", b.q(m.name))]
    if conversion(s) != "none":
        c = b._measure({"field": conv_calc(s)})
        fields.append(c)
        enc.append(("text", b.q(c.name)))
    return fields, d.name, start.name, enc, True, None


def expected(s, rows, dim, value, grouped, order=None):
    """stage -> {value, conversion} in the order Desktop draws them (the conversion's LOOKUP follows that order):
    by the value (desc), else the field's manual order, else by name. order: fields.<dim>.order."""
    vals = grouped(rows, [dim(s["dimension"])], value(s["measure"]))
    if sort(s) == "desc":
        keys = sorted(vals, key=lambda k: (-(vals[k] or 0), k))
    else:
        rank = {v: i for i, v in enumerate(order or [])}
        keys = sorted(vals, key=lambda k: (rank.get(k, len(rank)), k))
    conv, out = conversion(s), {}
    for i, k in enumerate(keys):
        base = None if conv == "none" else (vals[keys[i - 1]] if i else None) if conv == "previous" else vals[keys[0]]
        out[k] = {"value": vals[k], "conversion": None if conv == "none" or not base or vals[k] is None
                  else vals[k] / base}
    return out


def pane(b, pane_el, s, fields):
    """The invisible line that leaves room for the widest bar's labels (after the encodings, XSD order)."""
    if not is_funnel(s):
        return
    start = b.q(fields[1].name)
    line = ET.SubElement(pane_el, "reference-line", {
        "axis-column": start, "enable-instant-analytics": "true", "fill-above": "false", "fill-below": "false",
        "formula": "min", "id": REFLINE, "label-type": "none", "percentage-bands": "true", "scope": "per-table",
        "symmetric": "false", "value-column": start, "z-order": "1"})
    ET.SubElement(line, "reference-line-value", percentage=str(LEFT_ROOM))


def style(b, style_el, s, fields):
    """The start's axis hidden: its zero is the funnel's middle, its ticks would read as negative users. The room
    line drawn as nothing (reference: refline off, refband transparent)."""
    if not is_funnel(s):
        return
    from .colors import _rule
    axis = _rule(style_el, "axis", before=())
    at = len([f for f in axis if f.get("field")])  # after the field formats (title), before the declutter
    axis.insert(at, ET.Element("format", {"attr": "display", "class": "0", "field": b.q(fields[1].name),
                                          "scope": "cols", "value": "false"}))
    rule = _rule(style_el, "refline", before=("gridline", "zeroline", "table-div"))
    for attr, value in [("stroke-size", "0"), ("line-visibility", "off")]:
        ET.SubElement(rule, "format", attr=attr, id=REFLINE, value=value)
    band = _rule(style_el, "refband", before=("gridline", "zeroline", "table-div"))
    ET.SubElement(band, "format", attr="fill-color", id=REFLINE, value="#00000000")
