"""Grand totals and subtotals of a text table and a registry (todo 3.10, decisions/036).

spec: "totals": {"grand": "rows" | "cols" | "both", "sub": [outer row dimension], "label": "Total"}
- grand "rows": a total row under the rows (Tableau's 'Column Grand Totals'): <rows total='true'>;
  "cols": a total column right of the columns ('Row Grand Totals'): <cols total='true'> (CustomerSupportCaseDemo,
  Demo wealth and banking); "both": the two and their corner.
- sub: a total row after each member of the registry's outer row dimension: <subtotals><column> (XSD 2026.1).
A total is the measure aggregated over the rows of its partition, not the sum of the cells: for AVG, COUNTD and an
aggregate calc it is another number (Tableau's 'Automatic' total). expected.py computes it so through rows().

Look (Loan Retention, Demo wealth and banking): total text bold (cell / header font-weight, data-class total), the
label from the spec (header total-label), the total cells on a COLOR["rule"] background (pane background-color).
Not supported (refused): a heatmap or a chart (the total mark would rescale the color / the axis), a table calc
measure (Tableau totals a table calc over the total marks), a registry spark or pill column (a glyph string, a level of
one row), subtotals of a table (one dimension per shelf). A registry bar / bar_inside column takes a total: its bar is a
row-guarded calc, 0 on the total row (registry.bar_formula, decisions/081). A delta, share and text column take a total
(the change and the share of the total itself: 100 % on the grand total, decisions/109). A rank is blank on a total, a
track its share of the source, a dot keeps its number without a color, a tick its bar 0 and no line, a highlight's
flag is never set on a total (decisions/134).
"""
import xml.etree.ElementTree as ET

from .design import COLOR
from .registry import TOTAL_BARS, TOTAL_MARKS, TOTAL_TEXT

LABEL = "Total"  # the grand total label unless the spec gives one; a subtotal keeps Tableau's own 'Total'
SUB_LABEL = "Total"
TYPES = ("table", "registry")
CELL_BEFORE = ("header", "label", "mark", "pane", "worksheet", "gridline", "zeroline", "table-div")
HEADER_BEFORE = ("label", "mark", "pane", "worksheet", "gridline", "zeroline", "table-div")
PANE_BEFORE = ("worksheet", "gridline", "zeroline", "table-div")


def of(s):
    return s.get("totals")


def label(s):
    return of(s).get("label", LABEL)


def grand(s):
    """(total row, total column) of a sheet."""
    g = (of(s) or {}).get("grand")
    return g in ("rows", "both"), g in ("cols", "both")


def subs(s):
    return (of(s) or {}).get("sub", [])


def check(spec):
    for s in spec["sheets"]:
        t = of(s)
        if t is None:
            continue
        where = f"Sheet '{s['name']}'"
        if s["type"] not in TYPES:
            raise ValueError(f"{where}: totals apply to a table or a registry, not a {s['type']} (a total mark "
                             f"would rescale its axis or color)")
        if not t.get("grand") and not t.get("sub"):
            raise ValueError(f"{where}: totals need 'grand' or 'sub'")
        measures = [s["measure"]] if s["type"] == "table" else [c["measure"] for c in s["columns"]]
        if any("table_calc" in m for m in measures):
            raise ValueError(f"{where}: totals of a table calculation are not supported (Tableau totals it over the "
                             f"total marks)")
        if s["type"] == "table" and t.get("sub"):
            raise ValueError(f"{where}: subtotals need two row dimensions: use a registry with 'rows' [outer, inner]")
        if s["type"] == "registry":
            if t.get("grand") in ("cols", "both"):
                raise ValueError(f"{where}: a registry's columns are measures; grand totals 'rows' only")
            for sub in t.get("sub", []):
                if len(s["rows"]) != 2 or sub != s["rows"][0]:
                    raise ValueError(f"{where}: subtotals of '{sub}': only the outer of two row dimensions "
                                     f"({s['rows'][0] if len(s['rows']) == 2 else 'a registry with one row'})")
            for c in s["columns"]:
                if c.get("style", "bar") not in ("text",) + TOTAL_BARS + TOTAL_TEXT + TOTAL_MARKS:  # 039, 081, 134
                    raise ValueError(f"{where}: totals need text, bar, bar_inside, delta, share, rank, track, dot or "
                                     f"tick columns (column '{c.get('label', c['measure']['field'])}' is "
                                     f"{c.get('style', 'bar')}: a glyph string or a level of one row has no total; "
                                     f"drop the totals or show that column on a sheet without them)")


# ---- workbook ------------------------------------------------------------------------------------------------------
def shelves(b, s, rows_el, cols_el):
    row, col = grand(s)
    if row:
        rows_el.set("total", "true")
    if col:
        cols_el.set("total", "true")


def subtotals(b, table, s, dims):
    """<subtotals> after <cols> (XSD 2026.1 order: rows, cols, ..., subtotals)."""
    if not subs(s):
        return
    el = ET.SubElement(table, "subtotals")
    for name in subs(s):
        d = next(d for d in dims if d.col.name == name)
        ET.SubElement(el, "column").text = b.q(d.name)


def style(b, st, s, row_dim, col_dim=None):
    """Bold total text, its label, the shaded total cells (forms of Loan Retention and Demo wealth and banking)."""
    if of(s) is None:
        return
    from .colors import _rule
    row, col = grand(s)
    cell = _rule(st, "cell", before=CELL_BEFORE)
    if row or col:
        ET.SubElement(cell, "format", {"attr": "font-weight", "data-class": "total", "value": "bold"})
    if subs(s):
        ET.SubElement(cell, "format", {"attr": "font-weight", "data-class": "subtotal", "value": "bold"})
    if row or col:
        header = _rule(st, "header", before=HEADER_BEFORE)
        for on, d in ((row, row_dim), (col, col_dim)):
            if on:
                ET.SubElement(header, "format", {"attr": "total-label", "data-class": "total",
                                                 "field": b.q(d.name), "value": label(s)})
                ET.SubElement(header, "format", {"attr": "font-weight", "data-class": "total",
                                                 "field": b.q(d.name), "value": "bold"})
        pane = _rule(st, "pane", before=PANE_BEFORE)
        ET.SubElement(pane, "format", {"attr": "background-color", "data-class": "total", "value": COLOR["rule"]})


# ---- expected numbers ----------------------------------------------------------------------------------------------
def _kept(rows, keys):
    """The rows that make marks, as in expected._grouped: a Null member is a mark too (decisions/056)."""
    from .expected import is_mark
    return [r for r in rows if is_mark(r, keys)]


def table(s, rows, keys, value, grouped):
    """{key: total} of a table: 'Total | <col>' (total row), '<row> | Total' (total column), 'Total | Total'.
    value(rows, view): the measure over a partition's rows; grouped(rows, keys, value) as expected._grouped."""
    from .formula import View
    row, col = grand(s)
    if not (row or col):
        return {}
    kept, out, lab = _kept(rows, keys), {}, label(s)
    if row:  # keys: the row fields (one or two, decisions/045), then the column field
        out.update({f"{lab} | {k}": v for k, v in grouped(kept, keys[-1:], value).items()})
    if col:
        out.update({f"{k} | {lab}": v for k, v in grouped(kept, keys[:-1], value).items()})
    if row and col:
        out[f"{lab} | {lab}"] = value(kept, View([], kept))
    return out


def registry(s, rows, keys, value, grouped):
    """{key: total} of a registry column: 'Total' (grand total row), '<outer> | Total' (subtotals)."""
    from .formula import View
    kept, out = _kept(rows, keys), {}
    if subs(s):
        out.update({f"{k} | {SUB_LABEL}": v for k, v in grouped(kept, keys[:1], value).items()})
    if grand(s)[0]:
        out[label(s)] = value(kept, View([], kept))
    return out
