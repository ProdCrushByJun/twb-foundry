"""Color with meaning (todo 3.5): a muted base with an accent, good/bad by sign, the plan grey behind the fact,
and the legend as colored words in the block subtitle (reference dashboards).

bar / line / area sheets:
- color {highlight: [values], field?}: those values of the field in the accent color, the others muted. A bar
  highlights its own dimension by default; another field (line series, bar segments) also goes on Detail so
  that its marks stay apart.
- color {good: up|down} (bar): the sign of the measure, in the good or the bad color.
- plan: <measure> (bar): Measure Values with stacking off; the plan wide and muted, the fact narrow in the accent.
Subtitle words written {accent:East} / {good:above plan} / {bad:below plan} are drawn bold in that color, and no
legend is placed for these colors. Data-ink: on every bar/line/area an axis title or field label that only repeats
the block header is hidden (repeats(), todo 3.7; widths in tbuilder/ink.py). Every color comes from design.COLOR. The
builder takes the generated calcs, fields, encodings, style rules and palette maps from here; expected.py takes the
same calcs.
"""
import re
import xml.etree.ElementTree as ET

from . import benchmark, registry
from .design import COLOR, PLAN_FACT_SIZE

KINDS = ("bar", "line", "area")
WORD = re.compile(r"\{([a-z_]+):([^{}]+)\}")
ROLES = ("accent", "good", "bad")  # design.COLOR keys a colored word can take
MEASURE_NAMES = "[:Measure Names]"


def kind(s):
    """'highlight' | 'good' | 'plan' | None: what the colors of a bar/line/area sheet mean."""
    if s["type"] not in KINDS:
        return None
    if "plan" in s:
        return "plan"
    if benchmark.is_bench(s):  # selected accent vs the benchmark muted (decisions/043)
        return "benchmark"
    c = s.get("color")
    if isinstance(c, dict):  # vs, below: tbuilder/reflines.py, scale: tbuilder/heatmap.py
        return ("highlight" if "highlight" in c else "vs" if "vs" in c else "below" if "below" in c else
                "scale" if "scale" in c else "good")
    return None  # no color, or a dimension with Tableau's palette and a legend


def roles(s):
    """design.COLOR keys a sheet draws, so the colored words of its subtitle can name them."""
    if s["type"] == "kpi" and s.get("style") == "cards":
        return {"accent", "good", "bad"}
    if s["type"] in ("combo", "lollipop", "dumbbell", "bump", "pareto"):  # the line, the circles, highlighted ranks, the vital few (044, 139, 140, 157)
        return {"accent"}
    if s["type"] == "waterfall" or (s["type"] == "registry" and any("shape" in c for c in s["columns"])):
        return {"good", "bad"}  # the steps, the status marks by their sign (decisions/139)
    if s["type"] == "funnel":  # one accent (decisions/159)
        return {"accent"}
    if s["type"] == "gantt":  # plain accent, or a status in the colors its fields entry gives (polish-26)
        return {"accent", "good", "bad"} if "color" in s else {"accent"}
    if s["type"] in ("slope", "boxplot", "waffle"):  # decisions/141
        from . import compareviz
        return compareviz.roles(s)
    if s["type"] in ("treemap", "bubbles"):  # highlighted rectangles / circles, or the scale (decisions/138, 141)
        return {"accent"} if "highlight" in (s.get("color") or {}) else set()
    if s["type"] == "scatter":  # one accent color, or highlighted points (decisions/047)
        return {"accent"} if s.get("color") is None or "highlight" in s["color"] else set()
    return {"highlight": {"accent"}, "good": {"good", "bad"}, "plan": {"accent"}, "vs": {"accent"},
            "below": {"bad"}, "benchmark": {"accent"}, "scale": set(), None: set()}[kind(s)]


def highlight_field(s):
    return s["color"].get("field", s.get("dimension"))


def series_field(s):
    """The field besides a sheet's dimension/date that splits its marks: a color dimension or a highlighted field."""
    c = s.get("color")
    f = c if isinstance(c, str) else c.get("field") if isinstance(c, dict) else None
    return None if f == s.get("dimension") else f


def highlight_calc(s):
    return f"{s['name']} · Highlight"


def good_calc(s):
    return f"{s['name']} · Good"


def below_calc(s):
    return f"{s['name']} · Below Target"


def runs(text, where):
    """'{accent:East} vs the rest' -> [('East', 'accent'), (' vs the rest', None)]."""
    out, pos = [], 0
    for m in WORD.finditer(text):
        if m.group(1) not in ROLES:
            raise ValueError(f"{where}: unknown color '{m.group(1)}' in '{m.group()}' (use accent, good or bad)")
        out += [(text[pos:m.start()], None), (m.group(2), m.group(1))]
        pos = m.end()
    out.append((text[pos:], None))
    out = [(t, r) for t, r in out if t]
    if any("{" in t or "}" in t for t, r in out if r is None):
        raise ValueError(f"{where}: '{text}' has a brace outside a colored word ({{accent:word}})")
    return out


def plain(text):
    """The text as shown, without the colored-word markup (for size estimates)."""
    return WORD.sub(lambda m: m.group(2), text)


def calcs(spec):
    """Calc specs for highlight and good/bad sheets."""
    spec_calcs = {c["name"] for c in spec.get("calcs", [])}  # one used without 'agg' is an aggregate calc
    out = []
    for s in spec["sheets"]:
        k = kind(s)
        if k == "highlight":
            f = highlight_field(s)
            out.append({"name": highlight_calc(s),
                        "formula": " OR ".join(f'[{f}] = "{v}"' for v in s["color"]["highlight"])})
        elif k == "good":
            op = ">=" if s["color"]["good"] == "up" else "<="
            out.append({"name": good_calc(s), "formula": f"{_agg(s['measure'], spec_calcs)} {op} 0"})
        elif k == "below":  # a bar below its target line (reflines.py, decisions/095)
            target = next(r["measure"] for r in _refs(s) if r.get("type") == "target")
            out.append({"name": below_calc(s), "formula": f"{_agg(s['measure'], spec_calcs)} < "
                                                         f"{_agg(target, spec_calcs)}"})
    return out


def _agg(m, spec_calcs):
    """SUM([Sales]) of a measure spec in a calc formula; [Calc] of a spec calc used without 'agg' (an aggregate)."""
    if m["field"] in spec_calcs and "agg" not in m:
        return f"[{m['field']}]"
    return f"{m.get('agg', 'sum').upper()}([{m['field']}])"


def _refs(s):
    r = s.get("reference")
    return [] if r is None else r if isinstance(r, list) else [r]


def _words(text, drawn, where):
    """Colored words may only name colors that are drawn (a legend for a color nobody sees misleads)."""
    used = {r for _, r in runs(text, where) if r}
    if used - drawn:
        raise ValueError(f"{where}: colored words {sorted(used - drawn)} name a color that is not drawn (drawn: "
                         f"{sorted(drawn) or 'none'}); color the marks with color.highlight, color.good or plan")


def check(spec, prof):
    """Spec checks that need the CSV, before the calcs are generated (a bad field fails here, not in a calc)."""
    calc_names = {c["name"] for c in spec.get("calcs", [])}
    d = spec["dashboard"]
    if d.get("subtitle"):  # a dashboard-wide legend: any color a sheet draws
        _words(d["subtitle"], set().union(*(roles(s) for s in spec["sheets"])), f"Dashboard '{d['name']}'")
    for s in spec["sheets"]:
        where = f"Sheet '{s['name']}'"
        if s.get("subtitle"):
            _words(s["subtitle"], roles(s), where)
        k = kind(s)
        if k == "plan":
            if "color" in s:
                raise ValueError(f"{where}: plan colors the bars itself (fact accent, plan muted): remove 'color'")
            if any("table_calc" in s[x] for x in ("measure", "plan")):
                raise ValueError(f"{where}: table calculations with a plan are not supported yet")
            if len({(s[x]["field"], s[x].get("agg", "sum")) for x in ("measure", "plan")}) == 1:
                raise ValueError(f"{where}: plan and measure are the same field")
        elif k == "highlight":
            f, values = highlight_field(s), s["color"]["highlight"]
            if f in calc_names:
                raise ValueError(f"{where}: highlight field '{f}' is a calculated field; CSV columns only for now")
            col = prof.col(f)
            if col.datatype != "string":
                raise ValueError(f"{where}: highlight field '{f}' is {col.datatype}; it must be a text dimension")
            missing = [v for v in values if v not in col.distinct]
            if missing:
                raise ValueError(f"{where}: highlight values {missing} are not in '{f}' (values: {col.distinct[:12]})")
            if any('"' in v for v in values):
                raise ValueError(f"{where}: highlight values containing '\"' are not verified against Tableau yet")
        elif k == "below":
            if s["type"] != "bar" or not any(r.get("type") == "target" for r in _refs(s)):
                raise ValueError(f"{where}: color.below 'target' needs a bar with reference {{type: target, measure}}")
            if "table_calc" in s["measure"]:
                raise ValueError(f"{where}: color.below on a table calculation is not supported yet")
        elif k == "good":
            m = s["measure"]
            if "table_calc" in m:
                raise ValueError(f"{where}: color.good on a table calculation is not supported yet")
            if m["field"] not in calc_names:
                prof.col(m["field"])


def encode(b, s, fields, enc):
    """Add the fields and encodings of a meaning color to a sheet's shape; -> the measures of a plan sheet
    (fact, plan: Measure Values on the axis) or None. b is the Builder."""
    from .build import Field  # build imports this module
    k = kind(s)
    if k == "highlight":
        flag = b._dim(highlight_calc(s))
        fields.append(flag)
        enc.append(("color", b.q(flag.name)))
        if series_field(s):  # series / segments stay apart on Detail
            d = b._dim(series_field(s))
            fields.append(d)
            enc.append(("lod", b.q(d.name)))
    elif k in ("good", "below"):
        name = good_calc(s) if k == "good" else below_calc(s)
        if not b.calcs[name].is_agg:
            raise ValueError(f"Sheet '{s['name']}': '{s['measure']['field']}' is a row-level calculation; give the "
                             f"measure an 'agg' for color.{k}")
        flag = Field(b.col(name), "agg", "user", discrete=True)
        fields.append(flag)
        enc.append(("color", b.q(flag.name)))
    elif k == "scale":  # the bar's own measure on Color, a continuous scale (decisions/041)
        enc.append(("color", b.q(fields[1].name)))
    elif k == "plan":
        fact, plan = fields[1], b._measure(s["plan"])
        fields.append(plan)
        enc += [("color", b.q(MEASURE_NAMES)), ("size", b.q(MEASURE_NAMES))]
        return [fact, plan]
    return None


PLAIN = ("bar", "line", "area", "histogram", "strip", "beeswarm", "gantt", "funnel")
HOUSE_ACCENT = "#4e79a7"  # Tableau 10 blue: what Desktop draws without a mark color


def plain_mark(pane, s, enc):
    """A sheet without a color field draws Tableau's blue; with a book accent (decisions/137) that is not the
    house's color: its marks the accent, written as Desktop does (mark-color in the pane's 'mark' rule). The house
    accent is that blue already, so books without one (and their goldens) stay as they are (decisions/141)."""
    if s["type"] not in PLAIN or any(tag == "color" for tag, _ in enc) or COLOR["accent"] == HOUSE_ACCENT:
        return
    st = pane.find("style")
    if st is None:
        st = ET.SubElement(pane, "style")
    rule = st.find("style-rule[@element='mark']")
    if rule is None:
        rule = ET.SubElement(st, "style-rule", element="mark")
    ET.SubElement(rule, "format", attr="mark-color", value=COLOR["accent"])


def breakdown(s):
    """Stack marks: off for a plan sheet, so the plan and the fact bars overlap from zero."""
    return "off" if kind(s) == "plan" else "auto"


def measure_order(b, view, s, names):
    """Plan sheet: Measure Names sorted by hand, fact first. Tableau sorts Measure Names alphabetically by
    default; the first value gets the smallest size and is drawn on top (Desktop 2025.1)."""
    if kind(s) != "plan":
        return
    sort = ET.SubElement(view, "manual-sort", column=b.q(MEASURE_NAMES), direction="ASC")
    d = ET.SubElement(sort, "dictionary")
    for m in names:
        ET.SubElement(d, "bucket").text = f'"{b.q(m.name)}"'


def sheet_style(b, style, s, fields):
    """Worksheet style rules of a bar/line/area/table sheet: data-ink (labels that repeat the header, widths that
    keep the rest unclipped: tbuilder/ink.py) and the plan's sizes. Desktop's rule order: axis, cell, header, mark,
    pane, worksheet, gridline, zeroline, table-div."""
    from . import ink  # ink imports this module
    titles, labels = repeats(b, s, fields)
    if titles:
        axis, formats = _rule(style, "axis", before=()), []
        for ref, scope in titles:  # field formats first, as Desktop writes them
            formats.append({"attr": "title", "class": "0", "field": b.q(ref), "scope": scope, "value": ""})
            if scope == "rows":  # a vertical axis: its own width, or Desktop clips the longer ticks
                formats.append({"attr": "width", "field": b.q(ref), "value": str(ink.axis(b, s, fields[1]))})
        for i, attrs in enumerate(formats):
            axis.insert(i, ET.Element("format", attrs))
    if row_label_shown(b, s, labels):  # a header as wide as the label, or Desktop clips it to 'Man..'
        ET.SubElement(_rule(style, "header", before=("label", "mark", "pane", "worksheet", "gridline", "zeroline",
                                                     "table-div")),
                      "format", attr="width", field=b.q(fields[0].name), value=str(ink.row_header(b, s, fields[0])))
    cell = ink.table_cell(b, s, fields) if b.block_headers and s["type"] == "table" else None
    if cell:  # columns as wide as their header values, or Desktop clips them to 'Furnit..'
        ET.SubElement(_rule(style, "cell", before=("header", "label", "mark", "pane", "worksheet", "gridline",
                                                   "zeroline", "table-div")), "format", attr="width", value=str(cell))
    if kind(s) == "plan":  # Size by Measure Names: the fact PLAN_FACT_SIZE of the plan's width (Edit Sizes range)
        ET.SubElement(_rule(style, "mark", before=("pane", "worksheet", "gridline", "zeroline", "table-div")),
                      "encoding", {"attr": "size", "field": b.q(MEASURE_NAMES), "field-type": "nominal",
                                   "max-size": "1", "min-size": str(PLAN_FACT_SIZE), "type": "catsize"})
    for scope in labels:
        ET.SubElement(_rule(style, "worksheet", before=("gridline", "zeroline", "table-div")), "format",
                      attr="display-field-labels", scope=scope, value="false")


def _rule(style, element, before):
    """The style-rule for element, created in Desktop's order: ahead of the first rule named in before."""
    rule = style.find(f"style-rule[@element='{element}']")
    if rule is None:
        rule = ET.Element("style-rule", element=element)
        nxt = [i for i, r in enumerate(style) if r.get("element") in before]
        style.insert(nxt[0] if nxt else (0 if not before else len(style)), rule)
    return rule


# ---- data-ink: no label that only repeats the block header ---------------------------------------------------
# On for every bar/line/area with a block header (todo 3.7; 3.5 had it on the sheets of this module only).
REPEATS_ALL_SHEETS = True
TABLES = ("table", "heatmap")  # their field labels too
LEVEL_WORDS = {"year": ("year",), "quarter": ("quarter",), "month": ("month",), "week": ("week",),
               "day": ("day", "daily")}  # 'monthly' contains 'month'


def repeats(b, s, fields):
    """What only repeats the block header: (axis titles [(field ref, scope)], field-label scopes).

    An axis title or a field label goes when its field's caption is in the header text ('Sales **by region**':
    the Sales axis title and the Region label; a plural counts: 'Categories' names Category; a measure's own
    `label` counts too: 'Incidents by category' with label 'incidents' hides the Count of Number title); a date axis title
    when the header names its field or its level ('Monthly sales'). A plan sheet's Measure Values axis ('Value')
    never says anything: the subtitle names the fact and the plan.
    """
    if s["type"] == "gantt":  # 'Day of start [2026]' under dated ticks says nothing (polish-26)
        return [(fields[1].name, "cols")], []
    if s["type"] == "waterfall":  # the running total's title and the steps' field label say nothing (139)
        return [(fields[1].name, "rows")], ["cols"]
    if s["type"] == "funnel":  # the start's axis says nothing (hidden, decisions/159), the stages are the rows
        return [(fields[1].name, "cols")], ["rows"]
    if not ((s["type"] in KINDS and (kind(s) or REPEATS_ALL_SHEETS)) or (s["type"] in TABLES and REPEATS_ALL_SHEETS)):
        return [], []
    no_title = s.get("measure", {}).get("axis_title") == "none"  # said outright in the spec (decisions/136)
    outright = no_title or s.get("field_labels") == "none" or (
        isinstance(s.get("date"), dict) and s["date"].get("axis_title") == "none")  # polish-26
    if not outright and (not b.block_headers or not (s.get("title") or s.get("subtitle"))):
        return [], []
    text = plain(" ".join(s.get(k, "") for k in ("title", "subtitle"))).replace("**", "").lower()

    def said(f):
        word = getattr(f.col, "caption", f.col.name).lower()
        switched = getattr(getattr(f.col, "calc", None), "params", [])  # a header showing [Metric] names its measure
        return (word in text or (word.endswith("y") and word[:-1] + "ies" in text)  # 'region' is in 'regions'
                or any(f"[{p.lower()}]" in text for p in switched))

    if s["type"] in TABLES:  # the field labels over the row and the column headers ('Sales by region and category')
        if s.get("field_labels") == "none":  # said outright: the header names the cut (polish-26)
            return [], ["cols", "rows"]
        return [], [scope for f, scope in ((fields[0], "rows"), (fields[1], "cols")) if said(f)]
    d, m = fields[0], fields[1]
    across = s["type"] == "bar" and s.get("orientation", "horizontal") == "horizontal"  # measure on Columns
    m_scope, d_scope = ("cols", "rows") if across else ("rows", "cols")
    titles = []
    if s["type"] in ("line", "area"):
        level = s["date"].get("level", "month")
        if said(d) or any(w in text for w in LEVEL_WORDS[level]) or s["date"].get("axis_title") == "none":  # (polish-26)
            titles.append((d.name, "cols"))
    if kind(s) in ("plan", "benchmark"):  # Measure Values: its title 'Value' says nothing
        titles.append(("[Multiple Values]", m_scope))
    elif no_title or said(m) or (s["measure"].get("label") and s["measure"]["label"].lower() in text):  # the label names it (091)
        titles.append((m.name, m_scope))
    level = s.get("date_level") if s["type"] == "bar" else None  # a bar per period: 'by month' (decisions/090)
    # a horizontal bar's row label ('Warehouse' + the sort icon) goes always: the rows read as their own names
    # (decisions/183); a vertical bar's column label only when the header says it
    labels = [d_scope] if s["type"] == "bar" and (across or said(d) or (
        level and any(w in text for w in LEVEL_WORDS[level]))) else []
    return sorted(titles, key=lambda t: t[1]), labels


def row_label_shown(b, s, labels):
    """A horizontal bar keeps its row field label (block style, the header does not name the field)."""
    return (b.block_headers and s["type"] == "bar" and s.get("orientation", "horizontal") == "horizontal"
            and "rows" not in labels and "margin" not in s)  # a heatmap's margin hides its rows (decisions/041)


def measures(b):
    """Fields of the fact and plan measures (the Measure Names palette maps them; Desktop declares them)."""
    out = {}
    for s in b.worksheets:
        if kind(s) == "plan":
            for m in (s["measure"], s["plan"]):
                f = b._measure(m)
                out.setdefault(f.name, f)
    for f in registry.measures(b) + benchmark.measures(b):  # a registry track (decisions/039), a benchmark (043)
        out.setdefault(f.name, f)
    return [out[k] for k in sorted(out)]


def palettes(b):
    """Palette maps of the meaning colors: {instance: (column | None, derivation, [(bucket, color)])}.

    Measure Names (plan sheets) is not a column: no column-instance of its own; its buckets are the measures
    (declared through measures()), and the map is shared by the workbook.
    """
    out, names = {}, {}
    for s in b.worksheets:
        k = kind(s)
        if k == "highlight":
            col = b.calc_cols[highlight_calc(s)].name
            out[f"[none:{col}:nk]"] = (col, "None", [("true", COLOR["accent"]), ("false", COLOR["mark_muted"])])
        elif k == "good":
            col = b.calc_cols[good_calc(s)].name
            out[f"[usr:{col}:nk]"] = (col, "User", [("true", COLOR["good"]), ("false", COLOR["bad"])])
        elif k == "below":  # reference 'Color vs. Target': the bars under their target stand out
            col = b.calc_cols[below_calc(s)].name
            from . import reflines  # it imports this module
            rest = COLOR["accent"] if reflines.bullet(s) else COLOR["mark_muted"]  # a gray bar on gray zones: lost
            out[f"[usr:{col}:nk]"] = (col, "User", [("true", COLOR["bad"]), ("false", rest)])
        elif k == "plan":
            for m, color in ((s["measure"], COLOR["accent"]), (s["plan"], COLOR["mark_muted"])):
                bucket = f'"{b.q(b._measure(m).name)}"'
                if names.setdefault(bucket, color) != color:
                    raise ValueError(f"Sheet '{s['name']}': '{m['field']}' is a fact in one plan sheet and the plan "
                                     f"in another; Measure Names colors are shared by the workbook")
    names.update(registry.palettes(b))  # a registry track: its own generated calcs (decisions/039)
    names.update(benchmark.palettes(b))  # selected vs benchmark lines (decisions/043)
    if names:
        out[MEASURE_NAMES] = (None, None, sorted(names.items()))
    return out
