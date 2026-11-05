"""Pareto (decisions/157): bars of a measure by a dimension, largest first, and the running share of the total as a
line on a second axis (0-100 % on the right), a dashed line at the threshold (80 %); the 'vital few' bars, those
before which the running share is still under the threshold, in the accent, the rest muted.

Spec: {type: pareto, dimension, measure, threshold?: 0.8, highlight?: true}
- the members always sorted by the measure, descending (a Pareto is that order);
- highlight false: every bar muted, the line in the accent (a combo's look).

XML (reference 'How To: Create an Advanced Pareto Chart', sheet '12. Final Cleanup'; data/refs/pareto):
rows '(SUM(M) + Running)', a dual axis as dualaxis.py writes it (Bar + Line layers, not synchronized: an amount and
a share); the running share RUNNING_SUM(SUM(M)) / TOTAL(SUM(M)) a table calc along the dimension, in percent; the
dimension sorted by SUM(M) descending (the running sum follows the sort); the threshold a constant reference line on
the share's axis (reference: a parameter, scope per-pane, in the default pane, dotted). The vital flag is a boolean table
calc on the bars' Color (reference: a string of threshold zones). The bars' axis stays on the left, the bars without
labels: a format display false on the first measure of a fold does not hide its axis in Desktop 2025.1 (snapshot, two
placements), and an axis plus labels says the amount twice.
"""
import xml.etree.ElementTree as ET

from . import formats
from .design import COLOR, FONT, REF_STROKE_PX

TYPE = "pareto"
THRESHOLD = 0.8
SHARE_FORMAT = "pct0"


def is_pareto(s):
    return s["type"] == TYPE


def threshold(s):
    return s.get("threshold", THRESHOLD)


def highlight(s):
    return s.get("highlight", True)


def run_calc(s):
    return f"{s['name']} · Cumulative"


def vital_calc(s):
    return f"{s['name']} · Vital"


def vital_record(name):
    """expected: the vital few, {count: how many bars, share: the running share at the last of them}."""
    return f"{name} · Vital"


def _agg(m, calc_names):
    return (f"[{m['field']}]" if m["field"] in calc_names and "agg" not in m
            else f"{m.get('agg', 'sum').upper()}([{m['field']}])")


def check(spec):
    for s in spec["sheets"]:
        if not is_pareto(s):
            continue
        if "table_calc" in s["measure"]:
            raise ValueError(f"Sheet '{s['name']}': a Pareto runs its own running share; give it the plain measure")
        if not 0 < threshold(s) < 1:
            raise ValueError(f"Sheet '{s['name']}': threshold {threshold(s)} is a share of the total, between 0 and 1")


def calcs(spec):
    """The running share (the line) and the vital flag (the bars' color), table calcs along the dimension."""
    names = {c["name"] for c in spec.get("calcs", [])}
    out = []
    for s in spec["sheets"]:
        if not is_pareto(s):
            continue
        a, d = _agg(s["measure"], names), s["dimension"]
        out.append({"name": run_calc(s), "formula": f"RUNNING_SUM({a}) / TOTAL({a})", "compute_using": [d],
                    "format": SHARE_FORMAT})
        if highlight(s):  # the share before this member is still under the threshold
            out.append({"name": vital_calc(s), "formula": f"RUNNING_SUM({a}) - {a} < {threshold(s)!r} * TOTAL({a})",
                        "compute_using": [d]})
    return out


def palettes(b):
    """The vital few in the accent, the rest muted (as color.highlight, decisions/016)."""
    out = {}
    for s in b.worksheets:
        if is_pareto(s) and highlight(s):
            col = b.calc_cols[vital_calc(s)].name
            out[f"[usr:{col}:nk]"] = (col, "User", [("true", COLOR["accent"]), ("false", COLOR["mark_muted"])])
    return out


def along_fields(b):
    """The dimensions the vital flags run along: Desktop declares them in the datasource next to the flags' palette
    maps (reflines.along_fields)."""
    out = {}
    for s in b.worksheets:
        if is_pareto(s) and highlight(s):
            d = b._dim(s["dimension"])
            out.setdefault(d.name, d)
    return [out[k] for k in sorted(out)]


def instance_table_calc(b, ci):
    """The vital flag's datasource column-instance (its palette refers to it) carries the sheet's compute-using; without
    it Desktop renames the sheet's instance to [usr:..:nk:1], which the palette does not map (resave, decisions/065)."""
    for s in b.worksheets:
        if is_pareto(s) and highlight(s) and ci.get("column") == f"[{b.calc_cols[vital_calc(s)].name}]":
            ET.SubElement(ci, "table-calc", {"ordering-field": b.q(b._dim(s["dimension"]).name),
                                             "ordering-type": "Field"})


def shape(b, s):
    """-> fields (dimension, measure, running share[, vital flag]); the shelves are written by dualaxis.table."""
    from .build import Field
    fields = [b._dim(s["dimension"]), b._measure(s["measure"]), b._measure({"field": run_calc(s)})]
    if highlight(s):
        fields.append(Field(b.col(vital_calc(s)), "agg", "user", discrete=True))
    return fields, None, None, [], False, None


def layers(b, s, fields):
    """dualaxis._layers: the bars (labelled, by the vital flag or muted), the running share's line."""
    m, run = fields[1], fields[2]
    bar = [("size", "0.6"), ("mark-labels-show", "false")]  # the amounts read on the left axis (it stays)
    enc = []
    if highlight(s):
        enc = [("color", fields[3])]
    else:
        bar.append(("mark-color", COLOR["mark_muted"]))
    line = COLOR["muted"] if highlight(s) else COLOR["accent"]  # the accent is the vital bars'
    return [(m, "Bar", enc, bar, None, None),
            (run, "Line", [], [("mark-labels-show", "false"), ("mark-color", line)], None, None)]


def refline(b, pane, s, fields):
    """The threshold on the share's axis, in the default pane (reference: per-pane, the label its value)."""
    run = b.q(fields[2].name)
    ET.SubElement(pane, "reference-line", {
        "axis-column": run, "enable-instant-analytics": "true", "formula": "constant", "id": "refline0",
        "label-type": "value", "scope": "per-pane", "value": f"{float(threshold(s)):.17g}", "value-column": run,  # the value as Desktop writes it: 0.80000000000000004
        "z-order": "1"})


def style(b, style_el, s, fields):
    """Both axes without a title (reference: title ''; the block header names the measure, the calc's caption says
    nothing to a reader), the threshold's look (reflines.style): dashed muted, its label the percent."""
    from .colors import _rule
    axis = style_el.find("style-rule[@element='axis']")
    at = max(i for i, el in enumerate(axis) if el.tag in ("encoding", "format") and el.get("field")) + 1
    for i, f in enumerate((fields[1], fields[2])):
        axis.insert(at + i, ET.Element("format", {"attr": "title", "class": "0", "field": b.q(f.name),
                                                  "scope": "rows", "value": ""}))
    rule = _rule(style_el, "refline", before=("gridline", "zeroline", "table-div"))
    for attr, value in [("fill-above", "#00000000"), ("fill-below", "#00000000"), ("stroke-size", str(REF_STROKE_PX)),
                        ("line-visibility", "on"), ("line-pattern-only", "dashed"), ("stroke-color", COLOR["muted"]),
                        ("font-size", str(FONT["ref_label"])), ("color", COLOR["muted"]),
                        ("text-format", formats.tableau(SHARE_FORMAT))]:
        ET.SubElement(rule, "format", attr=attr, id="refline0", value=value)


def expected(s, rows, dim, value, grouped, label):
    """member -> {measure label: value, 'Cumulative': running share}, largest first (ties by name, as Desktop's
    sort), and the vital few in a record of their own."""
    amounts = grouped(rows, [dim(s["dimension"])], value(s["measure"]))
    order = sorted(amounts, key=lambda k: (-(amounts[k] or 0), str(k)))
    total = sum(amounts[k] or 0 for k in order)
    out, run, vital = {}, 0.0, {"count": 0, "share": None}
    for k in order:
        before, run = run, run + (amounts[k] or 0)
        out[k] = {label: amounts[k], "Cumulative": run / total if total else None}
        if total and before < threshold(s) * total:
            vital = {"count": vital["count"] + 1, "share": run / total}
    return out, vital
