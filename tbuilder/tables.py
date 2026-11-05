"""A text table's row fields and its sort (decisions/045).

- rows: one field or two ["Analyst", "Owner Team"] (the a case's detail table: the analyst and the team beside it).
  Two fields nest on the Rows shelf as Desktop writes it: ([ds].[none:Analyst:nk] / [ds].[none:Owner Team:nk])
  (reference Reports Usage, the registry of decisions/015).
- sort {by: "total", order: "asc" | "desc"}: the rows by their row total, i.e. the outer row field sorted by the
  measure summed over the columns (Desktop's 'Sort by field', <computed-sort> as a bar's); the inner field rides
  along. Its rows keep the outer field's order.
expected keys: '<outer> | <inner> | <column>'; reconcile reads a page row by its first cell, so the inner member
is not required next to the number (each outer member has its own inner one: the analyst's team).
"""
SORTS = ("asc", "desc")


def rows(s):
    """The row fields of a table or heatmap: a list."""
    r = s["rows"]
    return [r] if isinstance(r, str) else list(r)


def sort(s):
    v = s.get("sort") if s["type"] == "table" else None
    return v if isinstance(v, dict) else None


def check(spec):
    for s in spec["sheets"]:
        if s["type"] != "table":
            continue
        where = f"Sheet '{s['name']}'"
        rs = rows(s)
        if len(set(rs)) != len(rs) or s["cols"] in rs:
            raise ValueError(f"{where}: rows {rs} and cols '{s['cols']}' must be different fields")
        if len(rs) == 2 and (s.get("totals") or {}).get("sub"):
            raise ValueError(f"{where}: subtotals of a table are not supported; a registry with two rows has them")


def extra(b, s):
    """The inner row field (a second one) of a table or heatmap (decisions/171), as a field after [row, col,
    measure]."""
    return [b._dim(n) for n in rows(s)[1:]] if s["type"] in ("table", "heatmap") else []


def rows_shelf(b, s, fields, rows_el):
    """Two row fields: (outer / inner) on Rows."""
    if s["type"] in ("table", "heatmap") and len(rows(s)) == 2:
        rows_el.text = f"({b.q(fields[0].name)} / {b.q(fields[3].name)})"


def style(b, st, s, fields):
    """Two row fields: each row header as wide as its longest label (9pt + padding), the registry's header width form
    (reference: header format width per field). Desktop sized them by default and clipped 'Analyst ..', 'North – Ha..'
    (a case's Detail, 2026-10-21). Wider where the text metric says the label would still be cut (decisions/064)."""
    if s["type"] != "table":
        return
    from .colors import _rule, repeats
    from .design import FONT, field_label_px, row_header_fit_px, text_px
    from .totals import HEADER_BEFORE
    if len(rows(s)) == 1:  # one row field: its header as wide as the field label over it (decisions/094)
        if "rows" in repeats(b, s, fields)[1]:
            return
        caption = b.shown(fields[0].col)
        # Desktop sizes the header by the values and cut 'Paid Mon..' (ink 85 over values '2024-01' that need 68,
        # golden_dates_v2); a label whose ink fits that width it draws whole ('Region' 53 in 60: totals, tablecalcs)
        if text_px(caption, FONT["table_header"], bold=True) > row_header_fit_px(b.fields.labels(fields[0].col), ""):
            _rule(st, "header", before=HEADER_BEFORE).insert(0, _format(fields[0], b, field_label_px(caption)))
        return
    header = _rule(st, "header", before=HEADER_BEFORE)
    for i, f in enumerate((fields[0], fields[3])):  # the widths first in the rule, as the registry writes them
        px = row_header_fit_px(b.fields.labels(f.col), b.shown(f.col))  # its title: the caption (073)
        header.insert(i, _format(f, b, px))


def _format(f, b, px):
    import xml.etree.ElementTree as ET
    return ET.Element("format", attr="width", field=b.q(f.name), value=str(px))


def write_sort(b, view, s, fields):
    """<computed-sort> of the outer row field by the measure: the rows by their total."""
    so = sort(s)
    if so:
        from .build import _sub
        _sub(view, "computed-sort", column=b.q(fields[0].name), direction=so.get("order", "desc").upper(),
             using=b.q(fields[2].name))


def members(s, e):
    """reconcile: a two-row table names a mark by its outer member (the page's row header) and its column."""
    if s["type"] == "table" and len(rows(s)) == 2 and len(e["key"].split(" | ")) == 3:
        parts = e["key"].split(" | ")
        e["members"] = [m for m in (parts[0], parts[2]) if m in e["members"]]
    return e
