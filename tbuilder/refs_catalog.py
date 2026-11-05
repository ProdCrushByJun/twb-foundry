"""A catalog of the blocks of workbooks (decisions/196).

`tb book-catalog <book...> --out profiles/<name>/` reads the XML of each book: book -> dashboard -> zone -> sheet, with
each sheet's form, marks, shelves, colors, preview and whether the generator can draw it (covered / partial / not
covered), and each dashboard's layout as rows and columns in proportion. No data of a book is read and nothing of it is
copied to a new book: a form or a layout is only a choice for /to-tableau. `pick-charts` turns numbers of the gallery into
refs.md, prefer and requests; `pick-layout` puts a layout's grid in a spec.
"""
import base64
import collections
import datetime
import json
import re
import shutil
from pathlib import Path

import yaml

from . import profile_from, rebuild, spec as spec_mod, user_profile
from .profile_from import SourceError

VERSION = 1
UNITS = 100000  # a zone's x, y, w, h are shares of the dashboard
AUTO_SIZE = profile_from.AUTO_SIZE
CARD_MAX = 0.25  # a colored container up to this share of the dashboard is one block whatever it holds; a larger one, if it holds one chart
PANEL_MAX = 0.6  # over this share it is a page's background: its children are the blocks
ALIGNED = 2000  # zones this close (in units) are at the same place
FLOATING_DECOR = 0.05  # sheets floating over at most this share of all sheets' area are helpers: the tiled tree stays
GRID_MAX, DEPTH_MAX, WEIGHT_MAX = rebuild.GRID_MAX, 3, 12  # spec.schema.json, build.MAX_GRID_DEPTH
ERROR_NOTE = 5  # percent: a block moved farther than this is said in the gallery
REGISTRY_MIN = 3  # so many sheets side by side at the same height are the columns of one table (as in the reference)
KNOWN_MARKS = {"Automatic", "Bar", "Line", "Area", "Square", "Circle", "Shape", "Text", "Map", "Pie", "GanttBar",
               "Polygon", "Multipolygon", "Density"}
TRIG = re.compile(r"\b(SIN|COS|TAN|ATAN2?|ACOS|ASIN|PI|RADIANS|DEGREES)\s*\(", re.I)
RUNNING = re.compile(r"\bRUNNING_(SUM|AVG|COUNT|MIN|MAX)\s*\(", re.I)
RANKED = re.compile(r"\bRANK(_DENSE|_UNIQUE|_MODIFIED|_PERCENTILE)?\s*\(", re.I)
INDEX = re.compile(r"\b(INDEX|LAST|FIRST)\s*\(\s*\)", re.I)
JITTER = re.compile(r"\b(RANDOM|RAWSQL)\b", re.I)
AXIS_MEASURE = re.compile(r"\[(sum|avg|cnt|ctd|min|max|usr|attr|median|pcto|win|rank|cum|pct|stdev|var)[^\]]*:qk\]")
DATE_AXIS = re.compile(r"\[(tyr|tqr|tmn|twk|tdy|yr|qr|mn|dy|wk|md|tmdy):[^\]]*:qk\]")
DATE_PART = re.compile(r"\[(yr|qr|mn|dy|wk|wd|tyr|tqr|tmn|twk|tdy):[^\]]*:(ok|nk)\]")
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
CONSTANT = re.compile(r"^\s*(?:(?:MIN|MAX|AVG|SUM|ATTR)\s*\(\s*)?-?[\d.]*\s*\)?\s*$|^\s*\"[^\"]*\"\s*$", re.I)  # MIN(1), 0, ""
SHELF_FIELD = re.compile(r"\[(?:[^\]]|\]\])+\]\.\[((?:[^\]]|\]\])+)\]")
# What a kind of block answers: a key of prefer by the spec's type
QUESTION = {"kpi": "kpi", "bar": "comparison", "lollipop": "comparison", "dumbbell": "comparison", "pareto": "comparison",
            "line": "trend", "area": "trend", "combo": "trend", "bump": "trend", "slope": "trend", "calendar": "trend",
            "donut": "part_to_whole", "treemap": "part_to_whole", "waffle": "part_to_whole",
            "table": "table", "registry": "table", "heatmap": "table", "histogram": "distribution", "strip": "distribution",
            "beeswarm": "distribution", "boxplot": "distribution", "scatter": "relationship", "bubbles": "relationship",
            "map": "geography", "tilegrid": "geography", "gantt": "flow", "waterfall": "flow", "funnel": "flow"}
# A form whose prefer value is not the spec's type (the variants of prefer)
PREFER_VALUE = {"KPI": "cards", "bar + target": "bullet", "bar in bar": "bar_in_bar", "100% stacked bar": "stacked_100"}


def _slug(text):
    return re.sub(r"[^\w-]+", "_", str(text)).strip("_")[:60] or "sheet"


def _source(path):
    return profile_from.read(path)


# ---- a sheet --------------------------------------------------------------------------------------------------------
def _captions(root):
    """A field's name -> (its caption, its formula) over all sources of the book."""
    out = {}
    for c in root.iter("column"):
        name = (c.get("name") or "").strip("[]")
        if not name:
            continue
        calc = c.find("calculation")
        old = out.get(name, (None, None))
        out[name] = (c.get("caption") or old[0], calc.get("formula") if calc is not None and calc.get("formula") else old[1])
    return out


def _bare(field):
    """[sum:Calculation_1:qk] -> Calculation_1; a quick table calc [rank:sum:X:qk:2] -> X."""
    parts = field.split(":")
    if parts[-1].isdigit():
        parts = parts[:-1]
    return parts[-2] if len(parts) >= 3 else field


def _shelf(text, captions):
    """A shelf for people: its fields with captions and their aggregation."""
    if not text:
        return []
    out = []
    for field in SHELF_FIELD.findall(text):
        parts = field.split(":")
        name = _bare(field)
        name = (captions.get(name) or (None,))[0] or name
        out.append(f"{parts[0]}({name})" if len(parts) >= 3 and parts[0] not in ("none", "") else name)
    return out


def _sheet_calcs(ws, captions):
    """The calcs a sheet uses: {caption: formula}."""
    out = {}
    for field in SHELF_FIELD.findall("".join(filter(None, (ws.findtext("table/rows"), ws.findtext("table/cols"))))):
        out[_bare(field)] = 1
    for tag in ws.iter("column", "column-instance"):
        out[_bare((tag.get("name") or "").strip("[]"))] = 1
        if tag.get("column"):
            out[tag.get("column").strip("[]")] = 1
    calcs = {}
    for name in out:
        caption, formula = captions.get(name, (None, None))
        if formula:
            calcs[caption or name] = formula
    return calcs


def _colors(ws):
    found = collections.Counter(c.lower() for el in ws.iter("format", "map", "color-palette", "color") for c in
                                HEX.findall(" ".join([el.get("value") or "", el.get("to") or "", el.text or ""])))
    return [c for c, _ in found.most_common(6)]


def _result(form, spec_type, status="covered", *missing, role="block"):
    return {"form": form, "spec_type": spec_type, "status": status, "missing": list(missing), "role": role}


def _axis_measures(shelf):
    return [m.group(0) for m in AXIS_MEASURE.finditer(shelf)]


def _is_constant(field, formula_of):
    """An axis of no data: SUM(0), a calc that is MIN(1): a place for a label or an icon, not a chart's measure."""
    name = _bare(field.strip("[]"))
    return bool(CONSTANT.match(name)) or (name in formula_of and bool(CONSTANT.match(formula_of[name])))


def classify(ws, calcs=None, formula_of=None):
    """What a worksheet draws and what the generator has of it: {form, spec_type, status, missing, role}, or None for a
    sheet with no table. By its marks, shelves and calcs; a sheet can look alike and be built otherwise, so the gallery
    shows its preview too."""
    t = ws.find("table")
    if t is None:
        return None
    formulas = " ".join((calcs or {}).values())
    formula_of = formula_of or {}
    ranked = bool(RANKED.search(formulas)) or "[rank" in (t.findtext("rows") or "")
    rows, cols = t.findtext("rows") or "", t.findtext("cols") or ""
    panes = t.findall("panes/pane")
    # the pane of no axis only holds what the axes' panes share when the sheet has both
    layers = [p for p in panes if p.get("x-axis-name") or p.get("y-axis-name")] or panes
    marks = {p.find("mark").get("class") for p in layers if p.find("mark") is not None and p.find("mark").get("class")} or {"Automatic"}
    enc = {e.tag for e in t.findall("panes/pane/encodings/*")}
    no_shelves = not rows.strip() and not cols.strip()
    m_rows, m_cols = len(AXIS_MEASURE.findall(rows)), len(AXIS_MEASURE.findall(cols))
    # (a + b) on a shelf are axes side by side; a fold puts them on one axis 
    folds = sum(1 for e in t.iter("encoding") if e.get("fold") == "true")
    dual = folds > 0 and len(panes) > 1
    panels = max(m_rows, m_cols) - folds
    date_axis = bool(DATE_AXIS.search(rows + cols))
    if date_axis and marks == {"Automatic"} and not no_shelves:  # what Automatic draws along a date
        marks = {"Line"}
    if dual and not no_shelves and "Automatic" in marks:  # beside another mark on an axis
        marks = (marks - {"Automatic"}) | {"Line" if date_axis else "Bar"}
    measures = _axis_measures(rows) + _axis_measures(cols)
    constant = bool(measures) and all(_is_constant(m, formula_of) for m in measures)
    dims = len(SHELF_FIELD.findall(rows + cols)) - len(measures)
    text_measure = any(":qk]" in (e.get("column") or "") for e in t.findall("panes/pane/encodings/text"))
    shapes = "shape" in enc and "Shape" in marks

    if ws.find(".//viz-extension") is not None or marks - KNOWN_MARKS:
        return _result("viz extension", None, "not supported yet", "a viz extension or a mark the generator does not know: " + ", ".join(sorted(marks - KNOWN_MARKS)))
    if "Density" in marks:
        return _result("density", None, "not supported yet", "density marks")
    if no_shelves and "Polygon" in marks:  # draws nothing, a holder of a tooltip or an action
        return _result("text or icon", None, "helper", role="helper")
    if "Polygon" in marks or TRIG.search(formulas):
        return _result("custom geometry", None, "not supported yet", "polygon or trigonometry: a shape computed from the data (radial, sankey, arc)")
    if "path" in enc:
        return _result("custom path", None, "not supported yet", "a line drawn along a path field (sankey, slope with densified points)")
    if "geometry" in enc or "Latitude" in rows + cols or "Multipolygon" in marks or "Map" in marks:
        if "Latitude (generated)" in rows + cols or "geometry" in enc or "generated" in rows + cols:
            return _result("map", "map", "partial", "two map layers") if dual else _result("map", "map")
        return _result("map", "map", "partial", "points by the book's own coordinates: the generator takes a geographic role")
    if "Pie" in marks:
        return _result("donut", "donut") if dual else _result("pie", "donut", "partial", "a whole pie: the generator draws a donut")
    if constant or (not measures and not no_shelves and "text" in enc and all(_is_constant(f, formula_of) for f in SHELF_FIELD.findall(rows + cols))):
        if dims >= 2:
            return _result("table with drawn columns", "registry", "partial", "columns drawn on constant axes: the generator has a registry's own column styles")
        return _result("labels on constant axes", None, "helper", role="helper")
    if panels >= 3 and dims:
        return _result("table of measures", "registry")
    if no_shelves:
        if "size" in enc and marks & {"Square", "Automatic"}:
            return _result("treemap", "treemap")
        if "size" in enc and "Circle" in marks:
            return _result("bubbles", "bubbles")
        if text_measure:
            return _result("KPI", "kpi")
        return _result("text or icon", None, "helper", role="helper")
    if "GanttBar" in marks:
        if "Bar" in marks:
            names = [_bare(m.strip("[]")) for m in measures]
            if len(set(names)) < len(names):  # the same measure again: a gantt of no length holds the total's label
                return _result("stacked bar with totals", "bar")
            return _result("bar + target", "bar")
        if RUNNING.search(formulas) or "cum:" in rows + cols:
            return _result("waterfall", "waterfall")
        if date_axis:
            return _result("gantt", "gantt")
        return _result("tick on an axis", "bar", "partial", "a tick mark: the generator draws a target on a bar or a tick in a registry")
    if "Area" in marks:
        return _result("area + line", "area", "partial", "a line on top of the area") if "Line" in marks else _result("area", "area")
    if dual:
        if "Line" in marks and marks <= {"Line", "Circle", "Shape"} and ranked:
            return _result("bump", "bump")
        if marks == {"Line"}:
            return _result("line, two layers", "line", "partial", "a second layer over the line (the last point, a band)")
        if marks <= {"Circle", "Shape"}:
            return _result("dots, two layers", "strip", "partial", "a second layer of dots or shapes")
        if "Bar" in marks and "Shape" in marks:
            return _result("bar with shapes", "bar", "partial", "a layer of shapes over the bars")
        if marks == {"Bar", "Line"} or marks == {"Bar", "Automatic", "Line"}:
            if RUNNING.search(formulas) and "TOTAL(" in formulas.upper():
                return _result("pareto", "pareto")
            return _result("combo bar + line", "combo")
        if marks == {"Bar", "Circle"}:
            return _result("lollipop", "lollipop")
        if "Line" in marks and "Circle" in marks:
            return (_result("line with dots", "line") if date_axis else _result("dumbbell", "dumbbell"))
        if marks == {"Bar"}:
            if re.search(r"(^|[(\s])-\s*(SUM|AVG|\[)", formulas):
                return _result("mirror bars", "bar", "partial", "bars up and down from zero: a calc with a minus and two colors, by hand in the spec")
            if m_rows >= 2:
                return _result("bar in bar", "bar")
            return _result("bar in bar", "bar", "partial", "the generator keeps parts inside a total, vertical only")
        if "Bar" in marks and marks <= {"Bar", "Text", "Automatic"}:
            return _result("bar", "bar", "partial", "a second axis for labels: the generator labels the bar itself")
        return _result("dual axis: " + " + ".join(sorted(marks)), None, "not supported yet", "this pair of marks on two axes")
    if "boxplot" in " ".join(r.get("distribution-type") or "" for r in t.iter("reference-line")) or t.find(".//reference-distribution") is not None:
        return _result("box plot", "boxplot")
    if m_rows and m_cols and not date_axis:
        if "Bar" in marks:
            return _result("bars on two measures", None, "not supported yet", "bar width from a measure (Marimekko)")
        if JITTER.search(formulas):
            return _result("beeswarm", "beeswarm")
        return _result("scatter", "scatter", "partial", "custom shapes") if shapes else _result("scatter", "scatter")
    if panels == 2 and marks & {"Bar", "Line", "Automatic"}:
        return _result("two panels of measures", "line" if date_axis else "bar", "partial", "two measures as panels: a facet of the generator takes a dimension")
    if "Line" in marks or (marks == {"Automatic"} and date_axis):
        if ranked:
            return _result("bump", "bump")
        return _result("line", "line") if date_axis else _result("slope or category line", "slope", "partial", "the generator's slope takes two periods")
    if "Square" in marks or ("text" in enc and "color" in enc and not m_rows and not m_cols):
        if re.search(r"\bwd:|weekday", rows + cols + formulas, re.I) and re.search(r"\bwk:|\btwk:|week", rows + cols + formulas, re.I):
            return _result("calendar", "calendar")
        if INDEX.search(formulas):
            return _result("tile grid or waffle", "tilegrid")
        return _result("heatmap", "heatmap")
    if "Text" in marks or (not m_rows and not m_cols and "text" in enc):
        many = "Measure Names" in rows + cols or ":Measure Names" in rows + cols
        return _result("table of measures", "registry") if many else _result("text table", "table")
    if "Bar" in marks or marks == {"Automatic"}:
        if not m_rows and not m_cols:
            return _result("text or icon", None, "helper", role="helper")
        if "size" in enc and "Bar" in marks:
            return _result("bar with sized width", "bar", "partial", "bar width by a measure")
        if ":bin" in rows + cols or "(bin)" in rows + cols.lower():
            return _result("histogram", "histogram")
        if "pcto:" in rows + cols:
            return _result("100% stacked bar", "bar")
        if "color" in enc:
            return _result("stacked bar", "bar")
        return _result("bar", "bar")
    if marks & {"Circle", "Shape"}:
        if m_rows or m_cols:
            return _result("dots with shapes", "strip", "partial", "custom shapes") if shapes else _result("dot plot", "strip")
        return _result("text or icon", None, "helper", role="helper") if shapes else _result("dots on a grid", "heatmap", "partial", "dots instead of squares")
    return _result("other: " + "+".join(sorted(marks)), None, "not supported yet", "this mark and shelf combination")


def _sheet(ws, captions):
    calcs = _sheet_calcs(ws, captions)
    found = classify(ws, calcs, {k: v[1] for k, v in captions.items() if v[1]})
    if found is None:
        return None
    t = ws.find("table")
    panes = [{"mark": (p.find("mark").get("class") if p.find("mark") is not None else None),
              "encodings": sorted({e.tag for e in p.findall("encodings/*")})} for p in t.findall("panes/pane")]
    return {"name": ws.get("name"), **found, "marks": sorted({p["mark"] for p in panes if p["mark"]}),
            "encodings": sorted({e for p in panes for e in p["encodings"]}), "panes": panes,
            "shelves": {"rows": _shelf(t.findtext("rows"), captions), "cols": _shelf(t.findtext("cols"), captions)},
            "calcs": calcs, "colors": _colors(ws), "reference_lines": len(t.findall(".//reference-line")),
            "dashboards": [], "preview": None}


# ---- a dashboard ----------------------------------------------------------------------------------------------------
def _kind(z):
    return profile_from._kind(z)


def _box(z):
    return tuple(int(float(z.get(k) or 0)) for k in ("x", "y", "w", "h"))


def _is_sheet(z, sheets):
    return not _kind(z) and z.get("name") in sheets


def _is_hidden(z):
    return (z.get("hidden-by-user") or "").lower() == "true"


def _roots(d):
    """A dashboard's tiled root and its floating zones: what lies beside the one layout-basic under <zones> floats."""
    top = d.find("zones")
    zones = top.findall("zone") if top is not None else []
    if zones and _kind(zones[0]) == "layout-basic":
        return zones[0], zones[1:]
    return None, zones


def _leaf_zones(z, sheets, floating, out):
    kids = z.findall("zone")
    if not kids:
        out.append({"kind": "sheet" if _is_sheet(z, sheets) else (_kind(z) or "other"), "name": z.get("name"),
                    "text": re.sub(r"\s+", " ", "".join(r.text or "" for r in z.iter("run")).replace("Æ", " ")).strip()[:60] or None,
                    "box": _box(z), "floating": floating, "hidden": _is_hidden(z)})
    for k in kids:
        _leaf_zones(k, sheets, floating, out)


def _sheets_in(z, sheets):
    if _is_hidden(z):
        return []
    if _is_sheet(z, sheets):
        return [z]
    return [s for k in z.findall("zone") for s in _sheets_in(k, sheets)]


def _is_card(z, under):
    fill = profile_from._style(z).get("background-color")
    solid = profile_from._solid(fill)
    return bool(solid) and solid != under


def _canvas(d):
    for r in d.findall("style/style-rule"):
        if r.get("element") == "table":
            for f in r.findall("format"):
                if f.get("attr") == "background-color":
                    return profile_from._solid(f.get("value")) or "#ffffff"
    return "#ffffff"


def _side_by_side(zones):
    boxes = sorted((_box(z) for z in zones), key=lambda b: b[0])
    return (len(boxes) >= REGISTRY_MIN and all(abs(b[1] - boxes[0][1]) <= ALIGNED and abs(b[3] - boxes[0][3]) <= ALIGNED for b in boxes)
            and all(boxes[i + 1][0] - (boxes[i][0] + boxes[i][2]) <= ALIGNED for i in range(len(boxes) - 1)))


def _block_kind(zones, info):
    """How the sheets of a container read as one block: 'registry', 'kpi', a chart's name, or None for several blocks."""
    forms = [info[z.get("name")] for z in zones if z.get("name") in info and info[z.get("name")]["role"] == "block"]
    kpis = [f for f in forms if f["spec_type"] == "kpi"]
    tables = [f for f in forms if f["spec_type"] in ("table", "registry")]
    charts = [f for f in forms if f not in kpis and f not in tables]
    if len(charts) > 1 or (charts and len(kpis) > 1) or (charts and tables):
        return None
    if charts:
        return charts[0]["spec_type"] or charts[0]["form"]
    if kpis and not tables:
        return "kpi"
    return "registry" if tables else "helper"


def _main_kind(zones, info):
    """A small card of several charts: the kind of its largest chart."""
    charts = [z for z in zones if info[z.get("name")]["role"] == "block" and info[z.get("name")]["spec_type"] not in ("kpi", "table", "registry")]
    largest = max(charts or zones, key=lambda z: _area(_box(z)))
    return info[largest.get("name")]["spec_type"] or info[largest.get("name")]["form"]


def _slot(zones, kind):
    xs = [_box(z) for z in zones]
    x0, y0 = min(b[0] for b in xs), min(b[1] for b in xs)
    x1, y1 = max(b[0] + b[2] for b in xs), max(b[1] + b[3] for b in xs)
    return {"sheets": [z.get("name") for z in zones], "kind": kind, "box": (x0, y0, x1 - x0, y1 - y0)}


def _slots(z, sheets, info, under):
    """A zone's blocks: one for a sheet; one for a card or a row of table columns with one block's sheets; else its
    children's. This is what a new sheet takes the place of, and a block of a book is often several sheets."""
    if _is_sheet(z, sheets) and not _is_hidden(z):
        return [_slot([z], _block_kind([z], info) or "helper")]
    inner = _sheets_in(z, sheets)
    if not inner:
        return []
    b = _box(z)
    area = b[2] * b[3] / (UNITS * UNITS)
    if len(inner) == 1 and area < PANEL_MAX and _is_card(z, under):  # the card with its header texts, not only the sheet
        return [{**_slot(inner, _block_kind(inner, info) or "helper"), "box": b}]
    if len(inner) > 1 and area < PANEL_MAX:
        kind = _block_kind(inner, info)
        if _side_by_side(inner) and all(info[s.get("name")]["spec_type"] in ("registry", "table", "bar", "heatmap", None) for s in inner):
            return [_slot(inner, "registry")]
        if _is_card(z, under) and (kind or area < CARD_MAX):
            return [{**_slot(inner, kind or _main_kind(inner, info)), "box": b}]
    under = profile_from._solid(profile_from._style(z).get("background-color")) or under
    return [s for k in z.findall("zone") for s in _slots(k, sheets, info, under)]


def _join_kpis(slots):
    """KPI cards in a row (or a column) are one sheet of the spec, with one measure a card."""
    out = []
    for axis in (1, 0):  # 1: same y and height, side by side; 0: same x and width, one under another
        kpis = sorted((s for s in slots if s["kind"] == "kpi"), key=lambda s: (s["box"][axis], s["box"][1 - axis]))
        others = [s for s in slots if s["kind"] != "kpi"]
        out, run = [], []
        for s in kpis:
            r = run[-1] if run else None
            if r and abs(r["box"][axis] - s["box"][axis]) <= ALIGNED and abs(r["box"][axis + 2] - s["box"][axis + 2]) <= ALIGNED \
                    and not any(_between(o["box"], r["box"], s["box"], axis) for o in others):
                run.append(s)
            else:
                if run:
                    out.append(run)
                run = [s]
        if run:
            out.append(run)
        joined = []
        for run in out:
            if len(run) == 1:
                joined.append(run[0])
                continue
            x0, y0 = min(s["box"][0] for s in run), min(s["box"][1] for s in run)
            x1, y1 = max(s["box"][0] + s["box"][2] for s in run), max(s["box"][1] + s["box"][3] for s in run)
            joined.append({"sheets": [n for s in run for n in s["sheets"]], "kind": "kpi", "box": (x0, y0, x1 - x0, y1 - y0),
                           "kpi_cards": sum(s.get("kpi_cards", 1) for s in run)})
        slots = others + joined
    return slots


def _between(o, a, b, axis):
    along = 1 - axis
    return min(a[along], b[along]) < o[along] < max(a[along], b[along]) and o[axis] < a[axis] + a[axis + 2] and a[axis] < o[axis] + o[axis + 2]


def _cuts(items):
    """Slots -> a sheet name or ('rows' | 'cols', [(subtree, extent)]); None for zones no straight line divides."""
    if len(items) == 1:
        return items[0][0]
    for axis, kind in ((1, "rows"), (0, "cols")):
        bands = rebuild._bands(items, axis)
        if len(bands) > 1:
            kids = [(_cuts(b), extent) for (b, _), extent in zip(bands, _extents(bands, axis))]
            return None if any(k is None for k, _ in kids) else (kind, kids)
    return None


def _extents(bands, axis):
    """Bands' extents with the gaps between them halved between neighbours: the place each takes, as the grid has no gaps."""
    spans = [(min(i[1][axis] for i in b), max(i[1][axis] + i[1][axis + 2] for i in b)) for b, _ in bands]
    out = []
    for n, (s, e) in enumerate(spans):
        lo = (spans[n - 1][1] + s) / 2 if n else s
        hi = (e + spans[n + 1][0]) / 2 if n + 1 < len(spans) else e
        out.append(hi - lo)
    return out


def _weights(extents):
    """Integer weights 1-12 nearest in proportion to the extents."""
    total = sum(extents) or 1
    best, best_err = [1] * len(extents), None
    for top in range(1, WEIGHT_MAX + 1):
        most = max(extents) or 1
        w = [max(1, round(e / most * top)) for e in extents]
        err = max(abs(a / sum(w) - e / total) for a, e in zip(w, extents))
        if best_err is None or err < best_err - 0.002:  # the smaller weights unless the larger are visibly closer
            best, best_err = w, err
    return best


def _to_grid(node, depth=1):
    """A tree -> (rows of cells, row heights), or raises why the spec's grid cannot hold it."""
    kids = node[1] if isinstance(node, tuple) and node[0] == "rows" else [(node, 1)]
    if len(kids) > GRID_MAX:
        raise OverflowError(f"{len(kids)} rows in one column: a grid holds {GRID_MAX}")
    rows = []
    for kid, _ in kids:
        cells = kid[1] if isinstance(kid, tuple) and kid[0] == "cols" else [(kid, 1)]
        if len(cells) > GRID_MAX:
            raise OverflowError(f"{len(cells)} blocks in one row: a grid holds {GRID_MAX}")
        row = []
        for (cell, _), width in zip(cells, _weights([e for _, e in cells])):
            if isinstance(cell, str):
                row.append({"sheet": cell, "width": width})
                continue
            if depth >= DEPTH_MAX:
                raise OverflowError(f"nested deeper than the {DEPTH_MAX} levels of a grid")
            inner, heights = _to_grid(cell, depth + 1)
            row.append({"rows": inner, "row_heights": heights, "width": width})
        rows.append(row)
    return rows, _weights([e for _, e in kids])


def _shape(rows):
    """'2 rows: 4 / 3' or 'rows: 1 / 2 (1 + 3 under)': what a person checks against the picture."""
    def row(r):
        return " + ".join(f"[{' / '.join(row(x) for x in c['rows'])}]" if "rows" in c else "1" for c in r)
    return " / ".join(row(r) for r in rows)


def _area(box):
    return box[2] * box[3]


def layout(d, info, size):
    """A dashboard as rows and columns in proportion, each block a slot S1, S2.. A floating dashboard has no such tree."""
    root, floats = _roots(d)
    sheets = set(info)
    floating = [z for f in floats for z in _sheets_in(f, sheets)]
    tiled = _sheets_in(root, sheets) if root is not None else []
    tiled_area = sum(_area(_box(z)) for z in tiled)
    floating_area = sum(_area(_box(z)) for z in floating)
    all_area = tiled_area + floating_area
    out = {"status": "covered", "why": [], "floating_share": round(floating_area / all_area, 3) if all_area else 0}
    if not all_area:
        return {**out, "status": "not supported yet", "why": ["no sheets on it"]}
    if not tiled or floating_area / all_area > FLOATING_DECOR:
        return {**out, "status": "not supported yet",
                "why": [f"{round(100 * floating_area / all_area)}% of the sheets' area floats: floating is not carried over"]}
    if floats:
        out["status"] = "partial"
        out["why"].append(f"{len(floats)} floating zones are left out: " + ", ".join(sorted({z.get('name') or _kind(z) or 'object' for z in floats}))[:160])
    slots = _join_kpis(_slots(root, sheets, info, _canvas(d)))
    helpers = [s for s in slots if s["kind"] == "helper"]
    if helpers and len(helpers) < len(slots):
        slots = [s for s in slots if s["kind"] != "helper"]
        out["why"].append(f"helper sheets without data left out: {', '.join(n for s in helpers for n in s['sheets'])}"[:160])
    slots.sort(key=lambda s: (s["box"][1], s["box"][0]))
    for i, s in enumerate(slots, 1):
        s["slot"] = f"S{i}"
    tree = _cuts([(s["slot"], s["box"]) for s in slots])
    if tree is None:
        return {**out, "status": "not supported yet", "why": out["why"] + ["blocks overlap: no straight line divides them"]}
    try:
        rows, heights = _to_grid(tree if isinstance(tree, tuple) else ("rows", [(tree, 1)]))
    except OverflowError as e:
        return {**out, "status": "not supported yet", "why": out["why"] + [str(e)]}
    x0, y0 = min(s["box"][0] for s in slots), min(s["box"][1] for s in slots)
    body = (x0, y0, max(s["box"][0] + s["box"][2] for s in slots) - x0, max(s["box"][1] + s["box"][3] for s in slots) - y0)
    error = _error(rows, heights, slots, body)
    if error > ERROR_NOTE:
        out["why"].append(f"the grid moves a block by up to {error}% (empty space in a column, weights 1-12)")
    return {**out, "width": size[0], "height": size[1], "row_heights": heights, "grid": rows, "shape": _shape(rows), "body": body,
            "error_pct": error,
            "slots": [{"slot": s["slot"], "kind": s["kind"], "sheets": s["sheets"], "kpi_cards": s.get("kpi_cards", 1),
                       "share": [round(s["box"][2] / body[2], 3), round(s["box"][3] / body[3], 3)]} for s in slots],
            "left_out": _left_out(d)}


def _place(rows, heights, box, out):
    x, y, w, h = box
    total = sum(heights)
    for row, ht in zip(rows, heights):
        rh = h * ht / total
        cw = sum(c.get("width", 1) for c in row)
        cx = x
        for c in row:
            wide = w * c.get("width", 1) / cw
            if "rows" in c:
                _place(c["rows"], c["row_heights"], (cx, y, wide, rh), out)
            else:
                out[c["sheet"]] = (cx, y, wide, rh)
            cx += wide
        y += rh


def _error(rows, heights, slots, body):
    """How far the weights move a block, in percent of the body: at most what 1-12 can round."""
    placed = {}
    _place(rows, heights, (0, 0, 1, 1), placed)
    worst = 0
    for s in slots:
        have = placed[s["slot"]]
        want = ((s["box"][0] - body[0]) / body[2], (s["box"][1] - body[1]) / body[3], s["box"][2] / body[2], s["box"][3] / body[3])
        worst = max(worst, max(abs(a - b) for a, b in zip(have, want)))
    return round(worst * 100, 1)


def _left_out(d):
    """What of the dashboard's tiled zones a grid has no cell for: the spec's header and filter panel take these."""
    root, _ = _roots(d)
    kinds = collections.Counter()
    for z in root.iter("zone") if root is not None else ():
        if not z.findall("zone") and _kind(z) and _kind(z) != "layout-basic":
            kinds[_kind(z)] += 1
    return dict(kinds)


def _size(d):
    size = d.find("size")
    w, h = (profile_from._px(size.get("maxwidth")), profile_from._px(size.get("maxheight"))) if size is not None else (0, 0)
    return (w, h) if w and h else AUTO_SIZE


def _dashboard(d, info):
    size = _size(d)
    root, floats = _roots(d)
    zones = []
    sheets = set(info)
    if root is not None:
        _leaf_zones(root, sheets, False, zones)
    for f in floats:
        _leaf_zones(f, sheets, True, zones)
    for z in zones:
        z["px"] = [round(z["box"][0] * size[0] / UNITS), round(z["box"][1] * size[1] / UNITS),
                   round(z["box"][2] * size[0] / UNITS), round(z["box"][3] * size[1] / UNITS)]
        if z["kind"] == "sheet":
            z["status"] = "not supported yet" if z["floating"] else info[z["name"]]["status"]
    return {"name": d.get("name"), "size": list(size), "fixed": size != AUTO_SIZE or d.find("size") is not None,
            "sheets": sorted({z["name"] for z in zones if z["kind"] == "sheet"}), "zones": zones, "layout": layout(d, info, size)}


# ---- controls and clicks ---------------------------------------------------------------------------------------------
CONTROL_MODE = {"compact": "dropdown", "checkdropdown": "dropdown", "checklist": "list", "radiolist": "radio", "typein": "type in"}
ACTION_COMMAND = {"tsc:tsl-filter": "filter", "tsc:brush": "highlight"}
ACTION_TAG = {"edit-parameter-action": "parameter", "nav-action": "navigation", "edit-group-action": "group"}
ACTION_ON = {"on-select": "click", "on-hover": "hover", "on-menu": "menu"}


def _action(a):
    """(kind, trigger) of one action, or None when it is not one (<actions> also holds its datasources)."""
    if not a.tag.endswith("action"):
        return None
    command, link = a.find("command"), a.find("link")
    kind = ACTION_TAG.get(a.tag) or (ACTION_COMMAND.get(command.get("command")) if command is not None else None)
    kind = kind or ("url" if link is not None else "other")
    on = a.find("activation")
    return kind, ACTION_ON.get(on.get("type"), on.get("type")) if on is not None else "menu"


def _controls(d, root, captions):
    """What on a dashboard the sheets' statuses do not say. For reading only: pick-charts carries none of it, the spec sets it."""
    caption = lambda field: (captions.get(field) or (None,))[0] or field
    top, floats = _roots(d)
    params, filters = [], []
    for start in [top, *floats]:
        for z in start.iter("zone") if start is not None else ():
            field = SHELF_FIELD.findall(z.get("param") or "")
            if field and _kind(z) in ("paramctrl", "filter"):
                name = caption(_bare(field[0]) if _kind(z) == "filter" else field[0])
                (params if _kind(z) == "paramctrl" else filters).append(
                    {"name": name, "control": CONTROL_MODE.get(z.get("mode"), z.get("mode"))})
    actions = collections.Counter()
    all_actions = root.find("actions")
    for a in all_actions if all_actions is not None else ():
        source = a.find("source")
        found = _action(a)
        if found and source is not None and source.get("dashboard") == d.get("name"):
            actions[found] += 1
    return {"parameters": params, "filters": filters,
            "actions": [{"kind": k, "on": on, "count": n} for (k, on), n in sorted(actions.items())]}


# ---- a book ---------------------------------------------------------------------------------------------------------
def preview_path(book_slug, name):
    return f"previews/{book_slug}/{_slug(name)}.png"


def _thumbnails(root, folder, book_slug):
    """The pictures Desktop saved in the book, to refs/previews/."""
    for t in root.iter("thumbnail"):
        name, data = t.get("name"), (t.text or "").strip()
        if not name or not data:
            continue
        try:
            raw = base64.b64decode(data)
        except ValueError:
            continue
        target = folder / preview_path(book_slug, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)


def read_book(path, meta=None, refs_dir=None):
    root = _source(path)
    captions = _captions(root)
    sheets = {}
    for ws in root.iter("worksheet"):
        s = _sheet(ws, captions)
        if s:
            sheets[s["name"]] = s
    dashes = [{**_dashboard(d, sheets), "controls": _controls(d, root, captions)} for d in profile_from.dashboards(root)]
    for d in dashes:
        for n in d["sheets"]:
            sheets[n]["dashboards"].append(d["name"])
    if refs_dir:
        folder, book_slug = Path(refs_dir), _slug(Path(path).stem)
        _thumbnails(root, folder, book_slug)
        for it in [*sheets.values(), *dashes]:  # the book's own picture, or one /pick-charts fetched (Public strips them)
            rel = preview_path(book_slug, it["name"])
            it["preview"] = rel if (folder / rel).is_file() else None
    stories = [d.get("name") for d in root.iter("dashboard") if d.get("type") == "storyboard"]
    return {"file": Path(path).name, "name": Path(path).stem, "source_build": root.get("source-build"), **(meta or {}),
            "dashboards": dashes, "stories": stories, "sheets": list(sheets.values())}


def _meta_of(book):
    return {k: book[k] for k in ("url", "site", "workbook_id") if k in book}


def number(cat):
    """Gallery numbers: B1.. books, L1.. dashboards (a layout), 1.. sheets. A book added later never moves the others."""
    sheet_n = layout_n = 0
    for b_n, b in enumerate(cat["books"], 1):
        b["id"] = f"B{b_n}"
        for d in b["dashboards"]:
            layout_n += 1
            d["id"] = f"L{layout_n}"
        for s in b["sheets"]:
            sheet_n += 1
            s["id"] = sheet_n
    return cat


def make(books, out_dir, meta=None):
    """refs/catalog.json and refs/gallery.md in out_dir: the books there, in their first order, then the new ones."""
    out_dir = Path(out_dir)
    refs = out_dir / "refs"
    path = refs / "catalog.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"books": []}
    known = {b["file"]: _meta_of(b) for b in old["books"]}
    meta = {k: v for k, v in (meta or {}).items() if v}
    if meta and len(books) != 1:
        raise SourceError("--url, --site and --workbook-id describe one book")
    refs.mkdir(parents=True, exist_ok=True)
    for book in books:
        if Path(book).suffix.lower() not in (".twbx", ".twb"):
            raise SourceError(f"{book}: not a workbook (.twbx, .twb)")
        profile_from.read(book)
        target = refs / Path(book).name
        if Path(book).resolve() != target.resolve():
            shutil.copyfile(book, target)
        if meta:
            known[Path(book).name] = meta
        else:
            known.setdefault(Path(book).name, {})
    missing = [f for f in known if not (refs / f).is_file()]
    if missing:
        raise SourceError(f"The catalog names books no longer in {refs}: {', '.join(missing)}")
    if not known:
        raise SourceError("nothing to do: give a workbook")
    cat = number({"version": VERSION, "books": [read_book(refs / f, m, refs) for f, m in known.items()]})
    path.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    (refs / "gallery.md").write_text(gallery(cat), encoding="utf-8")
    return cat


def summary(cat):
    status = collections.Counter(s["status"] for b in cat["books"] for s in b["sheets"])
    layouts = collections.Counter(d["layout"]["status"] for b in cat["books"] for d in b["dashboards"])
    return {"books": len(cat["books"]), "dashboards": sum(len(b["dashboards"]) for b in cat["books"]),
            "sheets": sum(len(b["sheets"]) for b in cat["books"]), "sheet_status": dict(status), "layout_status": dict(layouts)}


def _cell(text):
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def _named(controls):
    return ", ".join(f"{c['name']} ({c['control']})" if c["control"] else c["name"] for c in controls)


def _acted(actions):
    return ", ".join(f"{a['count']} {a['kind']} on {a['on']}" for a in actions)


def gallery(cat):
    lines = ["# Blocks of your workbooks", "", "Pick by number: `3 7` sheets, `B1` a whole book, `L2` a dashboard's layout:",
             "", "```", "python -m tbuilder pick-charts profiles/<name>/ --pick \"3 7 L2\"", "```", ""]
    for b in cat["books"]:
        where = b.get("url") or (f"{b.get('site')}, workbook {b.get('workbook_id')}" if b.get("workbook_id") else b["file"])
        lines += [f"## {b['id']}. {b['name']}", "", f"{where} · saved in {b.get('source_build') or 'unknown version'}", ""]
        if b.get("stories"):
            lines += [f"Stories, not read: {', '.join(b['stories'])}", ""]
        lines += ["### Layouts", "", "| # | Dashboard | Size | Layout | Rows / columns | Why |", "|---|---|---|---|---|---|"]
        for d in b["dashboards"]:
            lt = d["layout"]
            image = f"![]({d['preview']}) " if d.get("preview") else ""
            lines.append(f"| {d['id']} | {image}{_cell(d['name'])} | {d['size'][0]}x{d['size'][1]} | {lt['status']} | "
                         f"{_cell(lt.get('shape', ''))} | {_cell('; '.join(lt['why']))} |")
        controls = [d for d in b["dashboards"] if any(d.get("controls", {}).values())]
        if controls:
            lines += ["", "### Controls and clicks", "", "Not picked by number: the spec sets these.", "",
                      "| Dashboard | Parameters | Filters | Actions |", "|---|---|---|---|"]
            for d in controls:
                c = d["controls"]
                lines.append(f"| {_cell(d['name'])} | {_cell(_named(c['parameters']))} | {_cell(_named(c['filters']))} | {_cell(_acted(c['actions']))} |")
        blocks = [s for s in b["sheets"] if s["role"] == "block"]
        lines += ["", "### Sheets", "", "| # | Preview | Sheet | What it is | Generator | Status | Missing | On |", "|---|---|---|---|---|---|---|---|"]
        for s in blocks:
            image = f"![]({s['preview']})" if s.get("preview") else ""
            lines.append(f"| {s['id']} | {image} | {_cell(s['name'])} | {_cell(s['form'])} | {_cell(s['spec_type'] or '-')} | {s['status']} | "
                         f"{_cell('; '.join(s['missing']))} | {_cell(', '.join(s['dashboards']))} |")
        helpers = [s["name"] for s in b["sheets"] if s["role"] == "helper"]
        if helpers:
            lines += ["", f"Helpers without data, no number to pick by: {_cell(', '.join(helpers))}"[:600]]
        lines.append("")
    return "\n".join(lines)


# ---- picking --------------------------------------------------------------------------------------------------------
def _find(cat, ref):
    for b in cat["books"]:
        if ref == b["id"]:
            return "book", b, None
        for d in b["dashboards"]:
            if ref == d["id"]:
                return "layout", b, d
        for s in b["sheets"]:
            if ref == str(s["id"]):
                return "sheet", b, s
    raise SourceError(f"'{ref}': no such number in the gallery")


def _book_where(b):
    return b.get("url") or b["file"]


def mechanics(b, s):
    """refs/<sheet>.md: what /pick-charts starts the reading of a sheet from: the trick, the mechanics, what is decoration."""
    shelves = s["shelves"]
    lines = [f"# {s['name']}: {s['form']}", "", f"Source: {b['name']} ({_book_where(b)}), source-build {b.get('source_build')}.",
             f"Local: `refs/{b['file']}`. Generator: {s['spec_type'] or 'none'}, {s['status']}.", "",
             "## Mechanics", f"- **Shelves**: Columns `{' + '.join(shelves['cols']) or 'empty'}`; Rows `{' + '.join(shelves['rows']) or 'empty'}`"]
    for i, p in enumerate(s["panes"], 1):
        lines.append(f"- **Layer {i}**: {p['mark']}; on the marks card: {', '.join(p['encodings']) or 'nothing'}")
    if s["reference_lines"]:
        lines.append(f"- **Reference lines**: {s['reference_lines']}")
    if s["colors"]:
        lines.append(f"- **Colors (not taken: the profile's are)**: {', '.join(s['colors'])}")
    if s["calcs"]:
        lines += ["", "## Calcs"] + [f"- `{k}` = `{re.sub(r'\s+', ' ', v)[:300]}`" for k, v in s["calcs"].items()]
    lines += ["", "## What the generator has", f"Status: **{s['status']}**." + (f" Missing: {'; '.join(s['missing'])}." if s["missing"] else ""), "",
              "## What to take", "(the /pick-charts reading: the trick in a line, what is decoration, which variant fits the design rules)", ""]
    return "\n".join(lines)


def _request(b, s, today):
    return f"- [ ] **{s['form']}** (request from /pick-charts, {today}) — {b['name']}, sheet `{s['name']}`: {_book_where(b)} ; {'; '.join(s['missing'])}"


def add_requests(path, requests):
    """Requests into the profile's requests.md (forms the generator lacks); a request already there stays once."""
    text = path.read_text(encoding="utf-8") if path.is_file() else "# Forms the generator lacks\n"
    new = [r for r in requests if r.split(" — ", 1)[1] not in text]
    if new:
        path.write_text(text.rstrip("\n") + "\n" + "\n".join(new) + "\n", encoding="utf-8")
    return new


def _read_profile(out_dir):
    path = Path(out_dir) / "profile.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {"profile_version": 1, "based_on": user_profile.HOUSE}


def _picked_line(kind, b, item):
    if kind == "book":
        return f"| {b['id']} | {_cell(b['name'])} | whole book | {_book_where(b)} | {len(b['sheets'])} sheets |  |"
    if kind == "layout":
        lt = item["layout"]
        return f"| {item['id']} | {_cell(b['name'])} | layout `{_cell(item['name'])}`: {_cell(lt.get('shape', ''))} | {_book_where(b)} | {lt['status']} | {_cell('; '.join(lt['why']))} |"
    return f"| {item['id']} | {_cell(b['name'])} | `{_cell(item['name'])}`: {_cell(item['form'])} | {_book_where(b)} | {item['status']} | {_cell('; '.join(item['missing']))} |"


def _write_refs_md(out_dir, rows):
    path = Path(out_dir) / "refs.md"
    head = ["# Workbooks you like", "", "| # | Book | What | Where | Status | Missing |", "|---|---|---|---|---|---|"]
    old = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    kept = [r for r in old if re.match(r"\| (L|B)?\d+ \|", r)]
    other = [r for r in old if r not in kept and not r.startswith("|---") and not r.startswith("| # |") and r.strip() and not r.startswith("# Workbooks you like")
             and not r.startswith("One line each:")]
    keys = {r.split("|")[1] for r in rows}
    merged = [r for r in kept if r.split("|")[1] not in keys] + rows
    path.write_text("\n".join(head + merged + ([""] + other if other else []) + [""]), encoding="utf-8")


def pick(out_dir, refs, today=None):
    """Numbers of the gallery -> refs.md, prefer, requests in the plan, refs/<sheet>.md, the layout in profile.yaml."""
    out_dir = Path(out_dir)
    path = out_dir / "refs" / "catalog.json"
    if not path.is_file():
        raise SourceError(f"{path}: run book-catalog first")
    cat = json.loads(path.read_text(encoding="utf-8"))
    profile = _read_profile(out_dir)
    prefer, sources, rows, requests, read_them, whole, layouts = dict(profile.get("prefer") or {}), list(profile.get("sources") or []), [], [], [], [], []
    moved = []

    def source(b):
        for s in sources:
            if s.get("file") == f"refs/{b['file']}":
                return s
        s = {"kind": "public" if b.get("url") else "server" if b.get("workbook_id") else "file", "file": f"refs/{b['file']}", **_meta_of(b), "picked": []}
        sources.append(s)
        return s

    def want(question, value, why):
        if prefer.get(question) not in (None, value):
            moved.append(f"prefer.{question}: {prefer[question]} -> {value} ({why})")
        prefer[question] = value

    for ref in refs:
        kind, b, item = _find(cat, ref)
        rows.append(_picked_line(kind, b, item))
        src = source(b)
        picked = src.setdefault("picked", [])
        if kind == "book":
            picked.append("workbook")
            whole.append(b["file"])
            counts = collections.Counter((QUESTION[s["spec_type"]], PREFER_VALUE.get(s["form"], s["spec_type"])) for s in b["sheets"]
                                         if s["status"] == "covered" and s["spec_type"] in QUESTION and s["dashboards"])
            for (question, value), _ in reversed(counts.most_common()):
                want(question, value, b["name"])
        elif kind == "layout":
            picked.append(f"layout: {item['name']}")
            if item["layout"]["status"] == "not supported yet":
                raise SourceError(f"{ref} '{item['name']}': its layout is not supported yet: {'; '.join(item['layout']['why'])}")
            profile["layout"] = {"file": f"refs/{b['file']}", "dashboard": item["name"]}
            layouts.append(item["name"])
        else:
            picked.append(item["name"])
            if item["status"] in ("covered", "partial") and item["spec_type"] in QUESTION:
                want(QUESTION[item["spec_type"]], PREFER_VALUE.get(item["form"], item["spec_type"]), item["name"])
            if item["status"] == "not supported yet":
                requests.append(_request(b, item, today or _today()))
            target = out_dir / "refs" / f"{_slug(item['name'])}.md"
            target.write_text(mechanics(b, item), encoding="utf-8")
            read_them.append(str(target))
    src_list = [s if not s.get("picked") else {**s, "picked": list(dict.fromkeys(s["picked"]))} for s in sources]
    if prefer:
        profile["prefer"] = prefer
    if src_list:
        profile["sources"] = src_list
    found = user_profile.problems(profile)
    if found:
        raise SourceError("The profile would be invalid:\n" + "\n".join(f"  - {p}" for p in found))
    (out_dir / "profile.yaml").write_text(yaml.safe_dump(profile, sort_keys=False, allow_unicode=True), encoding="utf-8")
    _write_refs_md(out_dir, rows)
    added = add_requests(out_dir / "requests.md", requests) if requests else []
    return {"refs": str(out_dir / "refs.md"), "prefer": prefer, "moved": moved, "requests": added, "read": read_them,
            "whole_books": whole, "layout": profile.get("layout") if layouts else None}


def _today():
    return datetime.date.today().isoformat()


# ---- a layout in a spec ---------------------------------------------------------------------------------------------
def find_layout(cat, ref):
    for b in cat["books"]:
        for d in b["dashboards"]:
            if ref in (d.get("id"), d["name"]):
                return b, d
    raise SourceError(f"'{ref}': no such dashboard in the catalog")


def _fill(rows, names):
    out = []
    for row in rows:
        cells = []
        for c in row:
            if "rows" in c:
                cells.append({"rows": _fill(c["rows"], names), "row_heights": c["row_heights"], "width": c["width"]})
            else:
                cells.append({"sheet": names[c["sheet"]], "width": c["width"]})
        out.append(cells)
    return out


def apply_layout(lt, mapping, spec):
    """spec with the dashboard's size and grid, its slots holding the sheets of mapping {slot: sheet}. Text, filters,
    theme of the spec stay, and so do its sheets: only the arrangement comes from the book."""
    if lt["status"] == "not supported yet":
        raise SourceError(f"This layout is not supported yet: {'; '.join(lt['why'])}")
    slots = [s["slot"] for s in lt["slots"]]
    lost = [s for s in slots if s not in mapping]
    extra = [s for s in mapping if s not in slots]
    if lost or extra:
        raise SourceError(f"Slots to fill: {', '.join(slots)}." + (f" Not filled: {', '.join(lost)}." if lost else "") + (f" No such slot: {', '.join(extra)}." if extra else ""))
    names = {s["name"] for s in spec.get("sheets", [])}
    alien = [v for v in mapping.values() if v not in names]
    if alien:
        raise SourceError(f"Not sheets of the spec: {', '.join(alien)}")
    if "dashboards" in spec:
        raise SourceError("A spec with several dashboards: put the grid by hand in the one it is for")
    dash = dict(spec["dashboard"])
    dash.update(width=lt["width"], height=lt["height"], grid=_fill(lt["grid"], mapping), row_heights=lt["row_heights"])
    out = {**spec, "dashboard": dash}
    spec_mod.validate(out)
    return out


def layout_cli(out_dir, ref, maps, spec_path, out_path):
    """What `tb pick-layout` prints or writes."""
    path = Path(out_dir) / "refs" / "catalog.json"
    if not path.is_file():
        raise SourceError(f"{path}: run book-catalog first")
    cat = json.loads(path.read_text(encoding="utf-8"))
    if not ref:
        chosen = _read_profile(out_dir).get("layout")
        if not chosen:
            raise SourceError("No layout: give its number from the gallery, or pick one with pick-charts")
        ref = chosen["dashboard"]
    b, d = find_layout(cat, ref)
    lt = d["layout"]
    if not spec_path:
        return {"book": b["name"], "dashboard": d["name"], **{k: v for k, v in lt.items() if k != "body"}}
    mapping = dict(m.split("=", 1) for m in maps)
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    out = apply_layout(lt, mapping, spec)
    target = Path(out_path or spec_path)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"spec": str(target), "width": lt["width"], "height": lt["height"], "shape": lt["shape"], "error_pct": lt["error_pct"], "why": lt["why"]}
