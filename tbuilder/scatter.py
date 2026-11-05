"""Scatter plot with the averages of both axes (todo 7.3, decisions/047; NovaCart 'Revenue vs. Customers').

Spec: {type: scatter, detail, x, y, color?, size?, axis_lines?, trend?}
- detail: the dimension a point stands for (on Detail: one mark per member);
- x, y: measures aggregated per point, x on Columns, y on Rows;
- color: a dimension (Tableau's palette and legend; a point per detail x color member), a measure {field, agg?}
  (the house sequential scale, as a filled map) or {highlight: [members of detail]} (those points accent, the rest
  muted, no legend: the meaning in the subtitle, decisions/016);
- size: a measure on Size;
- axis_lines {type: avg | median, label?}: a dashed muted line across each axis at the average (median) of the
  points, labelled '<label> <value>' ('Avg: 17.8', 'Avg: $11,899'; default label Average / Median);
- trend: a linear trend line over all points (one line, also with a color: exclude-color).

XML (form from NovaCart 'Revenue vs. Customers', Desktop-saved, 2025.x):
- Rows = the y measure, Columns = the x measure, <mark class='Circle'/> with mark-sizing marks-scaling-off, the
  detail on <lod>;
- one <reference-line> per axis in the pane, the x line first: axis-column = value-column = the axis measure,
  formula average | median, scope per-table, label 'Avg: <Value>'; without NovaCart's tooltip-type (Desktop 2025.1
  does not declare it, decisions/043). Their look in the worksheet style-rule 'refline' by id, as reflines.py;
- the trend line: <trendline enabled fit='linear' .../> between the encodings and the reference lines (XSD order,
  PaneSpecification-Trendline-G); its form is from the XSD, not from a reference book (none of them has one): the
  hybrid golden is its check.
"""
import statistics
import xml.etree.ElementTree as ET

from . import reflines
from .design import COLOR, FONT, REF_STROKE_PX

TYPE = "scatter"
DEFAULT_LABEL = {"avg": "Average", "median": "Median"}
# NovaCart: accent circles, partly transparent, a rim; ours: 75% opaque (as the symbol map) with a white rim so that
# overlapping points stay apart
POINT = {"size": "1.3", "mark-transparency": "191", "has-stroke": "true"}


def is_scatter(s):
    return s["type"] == TYPE


def color_kind(s):
    """'dimension' | 'measure' | 'highlight' | None."""
    c = s.get("color")
    if c is None:
        return None
    if isinstance(c, str):
        return "dimension"
    return "highlight" if "highlight" in c else "measure"


def highlight_calc(s):
    return f"{s['name']} · Highlight"


def label(s):
    a = s["axis_lines"]
    return a.get("label") or DEFAULT_LABEL[a.get("type", "avg")]


def record(name):
    """expected.py record of the axis lines: {axis measure label: value}."""
    return f"{name} · Axis Lines"


def measures(s):
    """The measure objects of a scatter (formats.measures)."""
    out = [s["x"], s["y"]] + ([s["size"]] if "size" in s else [])
    return out + ([s["color"]] if color_kind(s) == "measure" else [])


def roles(s):
    """design.COLOR keys the subtitle's colored words can name (colors.roles)."""
    return {"accent"} if color_kind(s) in ("highlight", None) else set()


# ---- spec checks ------------------------------------------------------------------------------------------------
def check(spec, prof):
    calc_names = {c["name"] for c in spec.get("calcs", [])}
    for s in spec["sheets"]:
        if not is_scatter(s):
            continue
        where = f"Scatter '{s['name']}'"
        ms = measures(s)
        if any("table_calc" in m for m in ms):
            raise ValueError(f"{where}: table calculations on a scatter are not supported yet")
        key = lambda m: (m["field"], m.get("agg", "sum"))  # noqa: E731
        if key(s["x"]) == key(s["y"]):
            raise ValueError(f"{where}: x and y are the same measure; a scatter compares two")
        for m in ms:
            if m["field"] not in calc_names:
                prof.col(m["field"])  # unknown field -> the profiler's error with the column list
        if s["detail"] in calc_names:
            raise ValueError(f"{where}: detail '{s['detail']}' is a calculated field; CSV columns only for now")
        detail = prof.col(s["detail"])
        if detail.datatype != "string":
            raise ValueError(f"{where}: detail '{s['detail']}' is {detail.datatype}; a point stands for a member of "
                             f"a text dimension")
        k = color_kind(s)
        if k == "dimension":
            if s["color"] == s["detail"]:
                raise ValueError(f"{where}: color is the detail field; use color.highlight to mark some points")
            prof.col(s["color"])
        if k == "highlight":
            values = s["color"]["highlight"]
            missing = [v for v in values if v not in detail.distinct]
            if missing:
                raise ValueError(f"{where}: highlight values {missing} are not in '{s['detail']}' "
                                 f"(values: {detail.distinct[:12]})")
            if any('"' in v for v in values):
                raise ValueError(f"{where}: highlight values containing '\"' are not verified against Tableau yet")


def calcs(spec):
    """The highlight flag: [detail] = "A" OR ... (a row-level boolean dimension, as colors.highlight)."""
    return [{"name": highlight_calc(s),
             "formula": " OR ".join(f'[{s["detail"]}] = "{v}"' for v in s["color"]["highlight"])}
            for s in spec["sheets"] if is_scatter(s) and color_kind(s) == "highlight"]


def palettes(b):
    """The highlight flag's palette map: accent / muted (build._palettes)."""
    out = {}
    for s in b.worksheets:
        if is_scatter(s) and color_kind(s) == "highlight":
            col = b.calc_cols[highlight_calc(s)].name
            out[f"[none:{col}:nk]"] = (col, "None", [("true", COLOR["accent"]), ("false", COLOR["mark_muted"])])
    return out


# ---- workbook (build.py) ----------------------------------------------------------------------------------------
def shape(b, s):
    """-> fields, rows, cols, encodings, labels, measure names (build.sheet_shape); table() writes the pane.
    fields: detail, x, y, then the color field, the size measure."""
    d, x, y = b._dim(s["detail"]), b._measure(s["x"]), b._measure(s["y"])
    fields, enc = [d, x, y], []
    k = color_kind(s)
    if k == "dimension":
        c = b._dim(s["color"])
    elif k == "highlight":
        c = b._dim(highlight_calc(s))
    elif k == "measure":
        c = b._measure(s["color"])
    if k:
        fields.append(c)
        enc.append(("color", b.q(c.name)))
    if "size" in s:
        z = b._measure(s["size"])
        fields.append(z)
        enc.append(("size", b.q(z.name)))
    enc.append(("lod", b.q(d.name)))
    return fields, y.name, x.name, enc, False, None


def _caption(f, m=None):
    return (m or {}).get("label") or getattr(f.col, "caption", f.col.name)


def _runs(parent, runs):
    ft = ET.SubElement(parent, "formatted-text")
    for text, attrs in runs:
        ET.SubElement(ft, "run", attrs).text = text


def _lines(b, s, fields):
    """[(id, axis field)] of the axis lines: x first, as NovaCart."""
    return [(f"refline{i}", f) for i, f in enumerate(fields[1:3])] if "axis_lines" in s else []


def table(b, table_el, style_el, s, fields):
    """The color scale (a measure), the pane (marks, trend line, axis lines, tooltip, look), the shelves."""
    from .colors import _rule
    from .maps import filled_palette
    d, x, y = fields[:3]
    k = color_kind(s)
    if k == "measure":  # the house sequential scale, light end off the white card (as a filled map)
        rule = _rule(style_el, "mark", before=("pane", "worksheet", "refline", "gridline", "zeroline", "table-div"))
        enc = ET.SubElement(rule, "encoding", {"attr": "color", "field": b.q(fields[3].name),
                                               "type": "custom-interpolated"})
        pal = ET.SubElement(enc, "color-palette", custom="true", name="", type="ordered-sequential")
        for c in filled_palette():
            ET.SubElement(pal, "color").text = c
    _line_style(b, style_el, s, fields)
    pane = ET.SubElement(ET.SubElement(table_el, "panes"), "pane",
                         {"selection-relaxation-option": "selection-relaxation-allow"})
    ET.SubElement(ET.SubElement(pane, "view"), "breakdown", value="auto")
    ET.SubElement(pane, "mark", {"class": "Circle"})
    ET.SubElement(pane, "mark-sizing", {"mark-sizing-setting": "marks-scaling-off"})
    e = ET.SubElement(pane, "encodings")
    for tag, ref in b.shapes[s["name"]][1]:
        ET.SubElement(e, tag, column=ref)
    if s.get("trend"):  # one linear line over all points (exclude-color: not one per color)
        ET.SubElement(pane, "trendline", {"enable-confidence-bands": "false", "enable-instant-analytics": "true",
                                          "enabled": "true", "exclude-color": "true", "exclude-intercept": "false",
                                          "fit": "linear"})
    formula = reflines.FORMULA[s["axis_lines"].get("type", "avg")] if "axis_lines" in s else None
    for i, (rid, f) in enumerate(_lines(b, s, fields)):
        ref = b.q(f.name)
        ET.SubElement(pane, "reference-line", {
            "axis-column": ref, "enable-instant-analytics": "true", "formula": formula, "id": rid,
            "label": f"{label(s)} <Value>", "label-type": "custom", "probability": "95", "scope": "per-table",
            "value-column": ref, "z-order": str(i + 1)})
    runs = [(f"<{b.q(d.name)}>", {"bold": "true"})]
    shown = [(x, s["x"]), (y, s["y"])] + [(f, None) for f in fields[3:] if not (k == "highlight" and f is fields[3])]
    for f, m in shown:
        runs += [("Æ\n", {}), (f"{_caption(f, m)}:\t", {"fontcolor": COLOR["muted"]}), (f"<{b.q(f.name)}>",
                                                                                         {"bold": "true"})]
    _runs(ET.SubElement(pane, "customized-tooltip", {"show-buttons": "false"}), runs)
    pane_style = ET.SubElement(pane, "style")
    rule = ET.SubElement(pane_style, "style-rule", element="mark")
    ET.SubElement(rule, "format", attr="size", value=POINT["size"])
    if k is None:  # one color: the accent
        ET.SubElement(rule, "format", attr="mark-color", value=COLOR["accent"])
    for attr, value in (("mark-transparency", POINT["mark-transparency"]), ("has-stroke", POINT["has-stroke"]),
                        ("stroke-color", COLOR["card_bg"])):
        ET.SubElement(rule, "format", attr=attr, value=value)
    if s.get("trend"):  # muted and thin, as the axis lines
        tr = ET.SubElement(pane_style, "style-rule", element="trendline")
        ET.SubElement(tr, "format", attr="stroke-size", value=str(REF_STROKE_PX))
        ET.SubElement(tr, "format", attr="stroke-color", value=COLOR["muted"])
    ET.SubElement(table_el, "rows").text = b.q(y.name)
    ET.SubElement(table_el, "cols").text = b.q(x.name)


def _line_style(b, style_el, s, fields):
    """The axis lines' look, as reflines.style: dashed muted 1px, the label muted, its number in the axis's format."""
    lines = _lines(b, s, fields)
    if not lines:
        return
    from .colors import _rule
    rule = _rule(style_el, "refline", before=("gridline", "zeroline", "table-div"))
    got = b.expected.get(record(s["name"]), {})
    for (rid, f), m in zip(lines, (s["x"], s["y"])):
        fmt = b.number_format(f.col)
        for attr, value in [("fill-above", "#00000000"), ("fill-below", "#00000000"),
                            ("stroke-size", str(REF_STROKE_PX)), ("line-visibility", "on"),
                            ("line-pattern-only", "dashed"), ("stroke-color", COLOR["muted"]),
                            ("font-size", str(FONT["ref_label"])), ("color", COLOR["muted"]),
                            ("text-format", reflines.text_format(got.get(_key(m)), fmt))]:
            ET.SubElement(rule, "format", attr=attr, id=rid, value=value)


# ---- expected numbers -------------------------------------------------------------------------------------------
def _key(m):
    """A measure's label in the expected records, as expected._label for a CSV column: SUM(Sales)."""
    return f"{m.get('agg', 'sum').upper()}({m['field']})"


def expected(s, rows, dim, value, grouped, key=_key):
    """{sheet: {point: {x label: v, y label: v}}, record: {x label: line, y label: line}}. A point is a detail member
    ('Atlas'), with a color dimension 'Atlas | West' (the color splits the marks). The axis lines are the average
    (median) of the points' values, as Desktop's per-table line over the marks (decisions/028)."""
    keys = [dim(s["detail"])] + ([dim(s["color"])] if color_kind(s) == "dimension" else [])
    xs, ys = (grouped(rows, keys, value(s[a])) for a in ("x", "y"))
    out = {s["name"]: {p: {key(s["x"]): xs[p], key(s["y"]): ys[p]} for p in xs}}
    if "axis_lines" in s:
        how = s["axis_lines"].get("type", "avg")
        line = {}
        for a, got in (("x", xs), ("y", ys)):
            vals = [v for v in got.values() if v is not None]
            line[key(s[a])] = None if not vals else sum(vals) / len(vals) if how == "avg" else statistics.median(vals)
        out[record(s["name"])] = line
    return out


def entries(s, exp, fmt, entry, tags):
    """reconcile entries: each point's x and y, the two axis lines (their label and the axis measure name them)."""
    out, name = [], s["name"]
    for point, vals in exp.get(name, {}).items():
        for a in ("x", "y"):
            out.append(entry(name, point, tags(s[a]), vals[_key(s[a])], fmt=fmt(s[a])))
    for a in ("x", "y"):
        v = exp.get(record(name), {}).get(_key(s[a]))
        if v is not None:
            out.append(entry(name, "", [label(s)] + tags(s[a]), v, part=f"reference line {a}", fmt=fmt(s[a])))
    return out
