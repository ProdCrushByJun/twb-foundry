"""Table calculation functions in calc formulas: the sheet side (decisions/034).

formula.py parses, types and evaluates RANK / WINDOW_* / LOOKUP / RUNNING_SUM / TOTAL / INDEX / FIRST / LAST; the
calc's spec names its compute_using (the sheet dimensions it runs along). Here: where such a calc may be shown, its
direction on each sheet and the XML Desktop writes for it.

XML (forms from Desktop-saved workbooks: golden_reflines_2025_1 flags, Customer Support Case, Data Quality Testing,
Broker Portfolio): the calc's <calculation> carries Desktop's default <table-calc ordering-type='Rows'/>; on the sheet
its column-instance [usr:Calculation_...:qk] carries the direction as Specific Dimensions, as the quick table calcs of
decisions/011: one dimension -> ordering-field, several -> <order field> children in compute_using order.
"""
import re
import xml.etree.ElementTree as ET

from . import barinbar, reflines

SHEETS = ("bar", "line", "area", "table", "heatmap")  # sheets with dimensions and one measure per mark
AXIS_SHEETS = ("bar", "line", "area")  # a measure axis: Desktop counts its nulls in the corner ("1 null")
EDGE_NULL_QUICK = ("difference", "percent_difference")  # no value at the partition's first row
LOOKUP = re.compile(r"\bLOOKUP\s*\(", re.I)  # LOOKUP(expr, -1): no row before the first one


def is_table_calc(col):
    calc = getattr(col, "calc", None)
    return calc is not None and calc.table_calc


def resolve(b, s, fields, dims):
    """Check where a table calc calc is shown and map its compute_using to this sheet's dimension instances.

    dims: {caption: Field} of the sheet's dimensions (as for the quick table calcs)."""
    for f in fields:
        if not is_table_calc(f.col):
            continue
        name, where = f.col.calc.name, f"Sheet '{s['name']}'"
        # registry: its rank / share / track calcs (decisions/039); a donut and its legend: the share (044)
        if s["type"] not in SHEETS + ("registry", "donut", "donut_legend", "waterfall", "funnel", "strip", "beeswarm", "bump",
                                      "slope", "tilegrid", "pareto"):  # 139, 140, polish-26b, 154, 157
            raise ValueError(f"{where}: '{name}' is a table calculation; it needs a sheet with dimensions "
                             f"({', '.join(SHEETS)})")
        if f.tc:
            raise ValueError(f"{where}: a quick table_calc on the table calculation '{name}' is not supported")
        if s["type"] == "bar" and (s.get("sort", "none") != "none" or "top" in s or "plan" in s) \
                and name != barinbar.pos_calc(s):  # the parts' position; the sort is by the measure (156)
            raise ValueError(f"{where}: sorting, Top N or a plan with the table calculation '{name}' is not supported "
                             f"yet")
        if reflines.lines(s) or reflines.vs_avg(s):
            raise ValueError(f"{where}: reference lines and color vs avg on the table calculation '{name}' are not "
                             f"supported yet")
        for a in f.col.calc.compute_using:
            if a not in dims:
                raise ValueError(f"{where}: '{name}' compute_using '{a}' is not a dimension of this sheet "
                                 f"(dimensions: {sorted(dims)})")
        f.tc_order = [b.q(dims[a].name) for a in f.col.calc.compute_using]


def write(ci, f):
    """<table-calc> of a table calc calc's column-instance on a sheet: its compute_using (Specific Dimensions)."""
    if not is_table_calc(f.col):
        return
    attrs = {"ordering-field": f.tc_order[0]} if len(f.tc_order) == 1 else {}
    tc = ET.SubElement(ci, "table-calc", {**attrs, "ordering-type": "Field"})
    if len(f.tc_order) > 1:
        for ref in f.tc_order:
            ET.SubElement(tc, "order", {"field": ref})


def edge_null(f):
    """The measure has no value at an edge of its partition by design (the first month of a previous-month calc)."""
    if f.tc:
        return f.tc["type"] in EDGE_NULL_QUICK
    return is_table_calc(f.col) and bool(LOOKUP.search(f.col.calc.formula))


def style(style_el, s, fields):
    """No 'N nulls' indicator on an axis sheet whose table calc is null at the edge (decisions/167): the null is the
    calc's, not missing data. Desktop's form: <format show-null-value-warning='false'/> in the table rule (ER)."""
    from .colors import _rule
    if s["type"] not in AXIS_SHEETS or not any(edge_null(f) for f in fields if f.kind == "agg"):
        return
    rule = _rule(style_el, "table", before=("worksheet", "refline", "gridline", "zeroline", "table-div"))
    if rule.find("format[@attr='show-null-value-warning']") is None:
        ET.SubElement(rule, "format", attr="show-null-value-warning", value="false")


def calculation(el, calc):
    """Desktop's default compute-using inside the calc's <calculation> (it adds it on save)."""
    if calc.table_calc:
        ET.SubElement(el, "table-calc", {"ordering-type": "Rows"})


def expected(calcs, m):
    """The table calc of a measure for expected.py: a calc with table calc functions, or None."""
    c = calcs.calcs.get(m["field"])
    if c is None or not c.table_calc:
        return None
    return {"type": "formula", "along": c.compute_using,
            "values": lambda marks, view, name=c.name: calcs.table_values(name, marks, view)}
