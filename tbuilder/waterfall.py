"""Waterfall (decisions/139): a step per member of the dimension, each from the running total before it to the one
after it, good / bad by the sign of the step.

Spec: {type: waterfall, dimension, measure, good?: up | down, total?: true}
- dimension: the steps along Columns, in the dimension's order (fields.<dim>.order for a manual one);
- measure: the step's value; its running sum is where the step ends;
- good: up (default) -> a rise in the good color, a fall bad; down -> the other way round;
- total: a last bar 'Total' from 0 to the sum, in the muted ink (decisions/144).

XML (forms from Desktop books, data/refs/waterfall: Higher Education Admissions 'Bar 1', SOC 'Line - Uptime'):
<mark class='GanttBar'/>, the running sum on the axis shelf (RUNNING_SUM along the dimension, a table calc), the
negative step on <size> (a Gantt bar runs from its position by its size: back to the total before it), the sign flag
on Color (an aggregate boolean, as color.good, decisions/016), the step's value as the label.
The total (reference 'How to Create Waterfall Charts', 'Simple Waterfall Chart'): <cols total='true'>, the total
column's pane without its border (pane border-style data-class total none); the running sum over the one total mark is
the sum, its size takes it back to 0. The total's color: the sign flag is a string then, 'total' where the mark spans
more than one member (MIN <> MAX).
"""
import xml.etree.ElementTree as ET

from .design import COLOR

TYPE = "waterfall"
TOTAL = "Total"  # the total bar's header


def is_waterfall(s):
    return s["type"] == TYPE


def run_calc(s):
    return f"{s['name']} · Running"


def step_calc(s):
    return f"{s['name']} · Step"


def good_calc(s):
    return f"{s['name']} · Good"


def _agg(m, calc_names):
    return (f"[{m['field']}]" if m["field"] in calc_names and "agg" not in m
            else f"{m.get('agg', 'sum').upper()}([{m['field']}])")


def check(spec):
    for s in spec["sheets"]:
        if is_waterfall(s) and "table_calc" in s["measure"]:
            raise ValueError(f"Sheet '{s['name']}': a waterfall runs its own running sum; give it the plain measure")


def calcs(spec):
    """The running total (a table calc along the dimension), the negative step (the Gantt bar's size), the sign."""
    names = {c["name"] for c in spec.get("calcs", [])}
    out = []
    for s in spec["sheets"]:
        if not is_waterfall(s):
            continue
        a, fmt = _agg(s["measure"], names), s["measure"].get("format")
        f = {"format": fmt} if fmt else {}
        cmp = ">=" if s.get("good", "up") == "up" else "<="
        d = s["dimension"]
        good = (f'IF MIN([{d}]) <> MAX([{d}]) THEN "total" ELSEIF {a} {cmp} 0 THEN "good" ELSE "bad" END'
                if s.get("total") else f"{a} {cmp} 0")
        out += [{"name": run_calc(s), "formula": f"RUNNING_SUM({a})", "compute_using": [d], **f},
                {"name": step_calc(s), "formula": f"-{a}", **f},
                {"name": good_calc(s), "formula": good}]
    return out


def palettes(b):
    """The sign flag: good / bad (as color.good, colors.palettes)."""
    out = {}
    for s in b.worksheets:
        if is_waterfall(s):
            col = b.calc_cols[good_calc(s)].name
            out[f"[usr:{col}:nk]"] = (col, "User", [('"good"', COLOR["good"]), ('"bad"', COLOR["bad"]),
                                                    ('"total"', COLOR["muted"])] if s.get("total")
                                      else [("true", COLOR["good"]), ("false", COLOR["bad"])])
    return out


def shape(b, s):
    """-> fields, rows, cols, encodings, labels, measure names (build.sheet_shape): the running total on Rows, the
    dimension on Columns."""
    from .build import Field
    d, m = b._dim(s["dimension"]), b._measure(s["measure"])
    run = b._measure({"field": run_calc(s)})
    step = b._measure({"field": step_calc(s)})
    good = Field(b.col(good_calc(s)), "agg", "user", discrete=True)
    enc = [("color", b.q(good.name)), ("size", b.q(step.name)), ("text", b.q(m.name))]
    return [d, run, m, step, good], run.name, d.name, enc, True, None


def shelves(s, cols_el):
    if is_waterfall(s) and s.get("total"):
        cols_el.set("total", "true")


def style(b, style_el, s, fields):
    """The total bar's header 'Total' and its pane without the border Desktop draws around a total."""
    if not (is_waterfall(s) and s.get("total")):
        return
    from .colors import _rule
    from .totals import HEADER_BEFORE, PANE_BEFORE
    ET.SubElement(_rule(style_el, "header", before=HEADER_BEFORE), "format", {
        "attr": "total-label", "data-class": "total", "field": b.q(fields[0].name), "value": TOTAL})
    ET.SubElement(_rule(style_el, "pane", before=PANE_BEFORE), "format", {
        "attr": "border-style", "data-class": "total", "value": "none"})


def expected(s, rows, dim, value, grouped):
    """member -> the step (the label each bar shows); 'Total' -> the sum (the total bar's label)."""
    out = grouped(rows, [dim(s["dimension"])], value(s["measure"]))
    if s.get("total"):
        from .formula import View
        out[TOTAL] = value(s["measure"])(rows, View([], rows))  # the measure over all the rows, as donut's total
    return out
