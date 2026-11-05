"""A registry's spark column as a line (decisions/153): spark {form: "line"} draws the measure per period as a line in
each row, its last period a dot, on a sheet of its own right of the registry in the same cell.

A registry is one worksheet whose columns share Rows and Columns (decisions/015): a line needs a date on Columns and
the measure on Rows, which would multiply every other column. So the line is a part of the registry (as a heatmap's
margins, decisions/041): the same row dimension, sort and filters, its row headers hidden, its panes as tall as the
registry's rows, its title in the registry's title strip.

XML (Tableau Public: 'Sparklines & KPIs', 'Client WoW KPI Sparklines',
'Sparkline'; all three the same form):
- Rows (dimension * (SUM(m) + SUM(last))), Columns the truncated date, continuous;
- the measure axis 'range-type=independent' (each row its own min..max) with 'domain-expand=false', the last value
  folded onto it (fold, synchronized): the dot sits on the line's end; every axis hidden;
- the periods: a boolean calc on Filters kept 'true' (the reference's 'Last 30 Days'); the last value a row-level calc
  IF <period> = <last> THEN [m] END (the reference's 'Last Day Volume'), a Circle.
"""
import datetime
import xml.etree.ElementTree as ET

from . import registry
from .design import COLOR

KIND = "registry_spark"
FORMS = ("glyphs", "line")
LINE_PX = "0.3"  # the reference's line size (0.296): a hairline that keeps a row's shape readable at 20px
DOT_SIZE = "0.6"


def is_line(c):
    return registry.style(c) == "spark" and c["spark"].get("form", "glyphs") == "line"


def line_column(s):
    return next((c for c in s.get("columns", []) if is_line(c)), None) if registry.is_registry(s) else None


def drawn(s):
    """The columns the registry's own sheet draws: all but a line spark."""
    return [c for c in s["columns"] if not is_line(c)]


def is_part(s):
    return s["type"] == KIND


def part_name(s, c):
    return f"{s['name']} · {registry.label(c)}"


def parts(s):
    """The physical sheets of a registry: itself, then its line spark's sheet."""
    c = line_column(s)
    if c is None:
        return [s]
    return [s, {"name": part_name(s, c), "type": KIND, "registry": s, "column": c, "rows": s["rows"],
                "sort": s.get("sort", "none")}]


def window_calc(s, c):
    return registry._name(s, c, "In Periods")


def last_calc(s, c):
    return registry._name(s, c, "Last")


def _cut(c):
    sp = c["spark"]
    return f"DATETRUNC('{sp['level']}', [{sp['date']}])"


def calcs(s, c):
    """The periods' flag (Filters) and the last period's value (the dot)."""
    ps = registry.spark_periods(c)
    first, last = (f"#{d.isoformat()}#" for d in (ps[0], ps[-1]))
    return [{"name": window_calc(s, c), "formula": f"{_cut(c)} >= {first} AND {_cut(c)} <= {last}"},
            {"name": last_calc(s, c), "formula": f"IF {_cut(c)} = {last} THEN [{c['measure']['field']}] END"}]


def can_line(s, j):
    """Column j of registry s can be a line (check's rules): the last of two or more, one row dimension, no totals or
    Top N."""
    cols = s.get("columns", [])
    return (j == len(cols) - 1 and len(cols) >= 2 and len(s.get("rows", [])) == 1 and not registry.totalled(s)
            and "top" not in s)


def check(s, where):
    """A line spark: the registry's last column (its sheet stands at the cell's right edge), one per registry, one
    row dimension, no totals and no Top N (the part repeats neither)."""
    lines = [registry.label(c) for c in s["columns"] if is_line(c)]
    if not lines:
        return
    if len(lines) > 1:
        raise ValueError(f"{where}: one line spark per registry, got {lines}")
    if not is_line(s["columns"][-1]):
        raise ValueError(f"{where}: a line spark is the last column (its sheet stands right of the registry)")
    if len(s["columns"]) < 2:
        raise ValueError(f"{where}: a line spark needs another column (the registry's sheet draws the others)")
    if len(s["rows"]) != 1:
        raise ValueError(f"{where}: a line spark takes one row dimension, got {s['rows']}")
    if registry.totalled(s) or "top" in s:
        raise ValueError(f"{where}: a line spark takes no totals and no Top N yet")


def check_date(b, s):
    """spark.date is a date of the data (decisions/096 tail: a missing one failed only inside the formula)."""
    for c in s["columns"]:
        if registry.style(c) != "spark":
            continue
        name = c["spark"]["date"]
        try:
            col = b.prof.col(name)
        except ValueError:
            col = None
        if col is None or col.datatype not in ("date", "datetime"):
            raise ValueError(f"Registry '{s['name']}', column '{registry.label(c)}': spark.date '{name}' is not a "
                             f"date field of the data")


# ---- workbook (build.py) -------------------------------------------------------------------------------------------
def shape(b, p):
    """-> fields [row dimension, date, measure, last value, periods flag, sort measure]."""
    from .build import Field
    s, c = p["registry"], p["column"]
    sp, m = c["spark"], c["measure"]
    fields = [b._dim(s["rows"][0]), Field(b.col(sp["date"]), "date", sp["level"]), b._measure(m),
              Field(b.col(last_calc(s, c)), "agg", m.get("agg", "sum")), b._dim(window_calc(s, c))]
    if p["sort"] != "none":
        fields.append(b._measure(s["columns"][0]["measure"]))
    return fields


def sort(b, p, fields):
    """(dimension, measure) of the registry's sort: its row dimension by its first column."""
    return fields[0], fields[5]


def periods_filter(b, view, fields):
    """The periods flag kept true, as the reference's 'Last 30 Days' (a boolean member unquoted). -> its slice."""
    from .build import USER_NS
    ref = b.q(fields[4].name)
    flt = ET.SubElement(view, "filter", {"class": "categorical", "column": ref})
    ET.SubElement(flt, "groupfilter", {"function": "member", "level": fields[4].name, "member": "true",
                                       f"{{{USER_NS}}}ui-domain": "database",
                                       f"{{{USER_NS}}}ui-enumeration": "inclusive",
                                       f"{{{USER_NS}}}ui-marker": "enumerate"})
    return ref


def table(b, table_el, p, fields):
    """Style, panes and shelves of the part (the reference's 'Stocks' form)."""
    s = p["registry"]
    dim, date, m, last = (b.q(f.name) for f in fields[:4])
    style = ET.SubElement(table_el, "style")
    axis = ET.SubElement(style, "style-rule", element="axis")
    ET.SubElement(axis, "encoding", {"attr": "space", "class": "0", "domain-expand": "false", "field": m,
                                     "field-type": "quantitative", "range-type": "independent", "scope": "rows",
                                     "type": "space"})
    ET.SubElement(axis, "format", {"attr": "display", "class": "0", "field": m, "scope": "rows", "value": "false"})
    ET.SubElement(axis, "format", {"attr": "display", "class": "0", "field": date, "scope": "cols", "value": "false"})
    ET.SubElement(axis, "encoding", {"attr": "space", "class": "0", "field": last, "field-type": "quantitative",
                                     "fold": "true", "scope": "rows", "synchronized": "true", "type": "space"})
    ET.SubElement(axis, "format", {"attr": "display", "class": "0", "field": last, "scope": "rows", "value": "false"})
    label = ET.SubElement(style, "style-rule", element="label")  # the registry names the rows
    ET.SubElement(label, "format", attr="display", field=dim, value="false")
    tbl = ET.SubElement(style, "style-rule", element="table")
    ET.SubElement(tbl, "format", attr="show-null-value-warning", value="false")  # the dot is null but at the end
    ws = ET.SubElement(style, "style-rule", element="worksheet")
    ET.SubElement(ws, "format", attr="display-field-labels", scope="rows", value="false")
    for element, attrs in (("gridline", {}), ("zeroline", {})):
        ET.SubElement(ET.SubElement(style, "style-rule", element=element), "format", attr="line-visibility",
                      value="off")
    div = ET.SubElement(style, "style-rule", element="table-div")
    for scope in ("rows", "cols"):
        ET.SubElement(div, "format", attr="line-visibility", scope=scope, value="off")
    panes = ET.SubElement(table_el, "panes")
    default = ET.SubElement(panes, "pane", {"selection-relaxation-option": "selection-relaxation-allow"})
    ET.SubElement(ET.SubElement(default, "view"), "breakdown", value="auto")
    ET.SubElement(default, "mark", {"class": "Automatic"})
    for i, (ref, mark, color, size) in enumerate(((m, "Line", COLOR["muted"], LINE_PX),
                                                  (last, "Circle", registry.bar_color(s), DOT_SIZE)), 1):
        pane = ET.SubElement(panes, "pane", {"id": str(i), "selection-relaxation-option":
                                             "selection-relaxation-allow", "y-axis-name": ref})
        ET.SubElement(ET.SubElement(pane, "view"), "breakdown", value="auto")
        ET.SubElement(pane, "mark", {"class": mark})
        rule = ET.SubElement(ET.SubElement(pane, "style"), "style-rule", element="mark")
        ET.SubElement(rule, "format", attr="size", value=size)
        ET.SubElement(rule, "format", attr="mark-color", value=color)
    b.registry_els[p["name"]] = (style, [pane for pane in panes.findall("pane[@id]")])
    ET.SubElement(table_el, "rows").text = f"({dim} * ({m} + {last}))"
    ET.SubElement(table_el, "cols").text = date


def size(b, p, row_px, w_px):
    """Each row's panes as tall as a registry row and as wide as the part's column (the reference's pane rule)."""
    _, panes = b.registry_els[p["name"]]
    for pane in panes:
        rule = ET.SubElement(pane.find("style"), "style-rule", element="pane")
        for attr, v in (("minwidth", w_px), ("maxwidth", w_px), ("minheight", row_px), ("maxheight", row_px)):
            ET.SubElement(rule, "format", attr=attr, value=str(v))


# ---- expected.py ---------------------------------------------------------------------------------------------------
def in_periods(c, day):
    """The period start a date falls in, if it is one of the spark's periods, else None."""
    sp = c["spark"]
    day = day if type(day) is datetime.date else day.date()
    if sp["level"] == "day":
        start = day
    elif sp["level"] == "month":
        start = day.replace(day=1)
    elif sp["level"] == "quarter":
        start = datetime.date(day.year, (day.month - 1) // 3 * 3 + 1, 1)
    else:
        start = datetime.date(day.year, 1, 1)
    return start if start in registry.spark_periods(c) else None
