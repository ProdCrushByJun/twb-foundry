"""Reference lines and color against the average (todo 8.1, decisions/028).

The reference authors draw a dashed muted line with its label where it ends ('Average 76', ER Operation, Call Center,
NovaCart 'Avg: 17.8') and color the bars above it (ER Patients vs Waiting Time) or the history bars that got better
(Call Center). Spec:
- bar / line / area: reference {type: avg | median | const | param, value?, parameter?, measure?, label?} or a list
  of up to three. avg / median are taken over the marks in the view; a stacked bar or area over the stack totals
  (Desktop 2025.1 averages the bars, not their segments: lab 94.71 for 7 day totals, not 31.6 for 21 segments).
  measure: average another measure over the same marks (a calc that is null on weekends -> 'weekday avg').
- bar: color {vs: avg}: bars at or above the average of the bars in the accent color, the others muted; no legend
  (decision 016: the meaning in the subtitle, {accent:above average}).
- KPI cards: history_reference {type: avg | median, label?} over each card's history bars; history_color "change":
  a bar better than the period before in the good color, worse in the bad color, the rest muted.

XML (decisions/028; forms from ER, SOC, E-Commerce, Loan Retention and a Desktop 2025.1 lab):
<reference-line formula=average|median|constant scope=per-table label-type=custom label='Average <Value>'> in the pane
after its encodings, a parameter line as formula=average over value-column=[Parameters].[Parameter N]; its look in the
worksheet style-rule 'refline' by line id. Scope per-table: a sheet here has at most one dimension per shelf, so
the table is its only pane, and Color does not make panes. The two color flags are table calculations generated
here (WINDOW_AVG, LOOKUP along the sheet's dimension / date), not spec calcs: formula.py does not evaluate table
calcs, and the colors change no number. expected.py takes the line values from values().
"""
import re
import statistics
import xml.etree.ElementTree as ET

from . import colors, formats
from .design import COLOR, FONT, REF_STROKE_PX
from .formula import Calc, calc_id

# A line's reference label beside the end labels (decisions/184; Desktop 2025.1 lab out/l184, one 8pt line ~12px)
END_LABEL_ABOVE_PX = 13  # an end label's middle above its point
REF_LABEL_OFF_PX = 10  # a reference label's middle above (vertical-align top, the default) or below its line
LABEL_CLEAR_PX = 14  # the distance of two label middles at which they do not touch (12.5 still touched in the lab)
AXIS_DATA_SHARE = 0.9  # Desktop's axis leaves a margin: the data took 89% of the plot in the lab
SHEET_PLOT_PX = 300  # a sheet on no dashboard
LABEL_SLOTS = [("right", "top"), ("right", "bottom"), ("left", "top"), ("left", "bottom")]


class TableCalc(Calc):
    """A generated color flag: a table calculation, which formula.py neither parses nor evaluates."""

TYPES = ("avg", "median", "const", "param", "date", "band", "target")
# param: Desktop's form; target: a line per bar at its own target (reference 'Color vs. Target', decisions/095)
FORMULA = {"avg": "average", "median": "median", "const": "constant", "param": "average", "target": "total"}
# param: the parameter's name; date: the day ('Jun 1')
DEFAULT_LABEL = {"avg": "Average", "median": "Median", "const": "Target", "band": "Band", "target": "Target"}
GOAL = "Goal"  # a card measure's goal line (decisions/178): its record key
BELOW = "below target"  # the reference record's count of the bars below their target line (decisions/095)
MAX_BANDS = 3  # bullet graph: zones under each bar at percents of its target (reference 'Bullet Graph', decisions/152)
BULLET_BAR_SIZE = "0.7"  # the bar narrower than its zones, which fill the row
BULLET_GAP_PX = "5"  # reference: white row dividers, or the zones of next rows run into one wall
CHANGE = ("better", "worse", "same")  # history_color change: the flag's values
DATE_SHEETS = ("line", "area")  # a date line stands on a date axis (decisions/043)
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def zone_key(p):
    """The reference record's count of the bars below p % of their target: 'below 80% of target'."""
    return f"below {p:g}% of target"


def date_of(r):
    """A date line's day: 'value' as an ISO date."""
    import datetime as dt
    return dt.date.fromisoformat(r["value"])


def edges(r):
    """A band's two edges as line specs: (from, to), each a const (number) or a param (parameter name)."""
    def edge(v):
        return {"type": "param", "parameter": v} if isinstance(v, str) else {"type": "const", "value": v}
    return edge(r["from"]), edge(r["to"])


def lines(s):
    """Reference specs of a sheet as a list; a card history part takes its card's history_reference."""
    if s["type"] == "card_history":
        r = s["card"].get("history_reference")
        goal = s["measure"].get("goal")  # the measure's goal: a dashed line without a label (decisions/178)
        return ([r] if r else []) + ([{"type": "const", "value": goal, "label": GOAL, "silent": True}]
                                     if goal is not None else [])
    r = s.get("reference")
    return [] if r is None else r if isinstance(r, list) else [r]


def label(r):
    if r.get("label"):
        return r["label"]
    if r["type"] == "date":
        d = date_of(r)
        return f"{MONTHS[d.month - 1]} {d.day}"
    return r["parameter"] if r["type"] == "param" else DEFAULT_LABEL[r["type"]]


def vs_avg(s):
    c = s.get("color")
    return s["type"] == "bar" and isinstance(c, dict) and c.get("vs") == "avg"


def changes(s):
    """A KPI cards sheet (or one of its history parts) whose history is colored by the change."""
    card = s.get("card", s)
    return card.get("history_color") == "change"


def vs_calc(s):
    return f"{s['name']} · Above Average"


def change_calc(p):
    return f"{p['name']} · Change Color"


def record(name):
    """expected.py key of a sheet's reference values ({label: value}), next to its marks."""
    return f"{name} · Reference"


def total_end(s):
    """A stacked horizontal bar with its total at the bar end (reference 'Stacked with End Labels', decisions/095)."""
    return s["type"] == "bar" and s.get("total") == "end"


def stacked(s):
    """Marks stack (bar, area with segments): avg / median are taken over the stack totals."""
    return s["type"] in ("bar", "area") and colors.series_field(s) is not None


# ---- spec checks (before the calcs are compiled) ----------------------------------------------------------------
def check(spec, prof, params):
    calc_names = {c["name"] for c in spec.get("calcs", [])}
    for s in spec["sheets"]:
        where = f"Sheet '{s['name']}'"
        if s["type"] == "kpi":
            extra = [k for k in ("history_reference", "history_color") if k in s]
            if extra and s.get("style") != "cards":
                raise ValueError(f"KPI '{s['name']}': {extra} only apply to style 'cards'")
        refs = lines(s) if s["type"] != "kpi" else [s["history_reference"]] if "history_reference" in s else []
        for r in refs:
            _check_line(r, where, prof, params, calc_names, s)
        labels = [label(r) for r in refs]
        if len(set(labels)) != len(labels):
            raise ValueError(f"{where}: reference line labels must be unique, got {labels}")
        if refs and "plan" in s:
            raise ValueError(f"{where}: a reference line next to a plan is not supported yet (the plan is a bar)")
        if (refs or vs_avg(s)) and "table_calc" in s.get("measure", {}):
            raise ValueError(f"{where}: reference lines and color vs avg on a table calculation are not supported yet")
        if s.get("total") == "end":
            from . import barlabels
            if not (barlabels.horizontal(s) and stacked(s)):
                raise ValueError(f"{where}: total 'end' is the stack total of a stacked horizontal bar (color by a "
                                 f"field); remove 'total'")
            if refs or "table_calc" in s["measure"] or s.get("labels") == "end":
                raise ValueError(f"{where}: total 'end' does not go with a reference line, a table calculation or "
                                 f"labels 'end' (decisions/095)")


def _param(p, where, params):
    if p not in params:
        raise ValueError(f"{where}: reference line parameter '{p}' is not a parameter "
                         f"(parameters: {sorted(params) or 'none'})")
    if params[p].datatype != "integer":
        raise ValueError(f"{where}: reference line parameter '{p}' is a {params[p].datatype} parameter; it must "
                         f"be a number")
    return params[p]


def _check_line(r, where, prof, params, calc_names, s=None):
    t = r["type"]
    if t == "const" and "value" not in r:
        raise ValueError(f"{where}: reference line 'const' has no 'value'")
    if t == "const" and not isinstance(r["value"], (int, float)):
        raise ValueError(f"{where}: reference line 'const' value {r['value']!r} is not a number")
    if t == "param":
        p = r.get("parameter")
        if p is None:
            raise ValueError(f"{where}: reference line 'param' has no 'parameter'")
        _param(p, where, params)
    if t == "date":  # a vertical line on the date axis (SOC 'Jun 1st', decisions/043)
        if s is not None and s["type"] not in DATE_SHEETS:
            raise ValueError(f"{where}: a date line stands on a date axis: line or area sheets only")
        if not isinstance(r.get("value"), str):
            raise ValueError(f"{where}: reference line 'date' needs 'value', a day as YYYY-MM-DD")
        try:
            date_of(r)
        except ValueError:
            raise ValueError(f"{where}: reference line 'date' value {r['value']!r} is not a YYYY-MM-DD date") from None
    if t == "target":  # a line per bar at its own target, no label (decisions/095)
        if "measure" not in r:
            raise ValueError(f"{where}: reference line 'target' needs 'measure', the target of each bar")
        if s is not None and not (s["type"] == "bar" and not stacked(s) and "plan" not in s):
            raise ValueError(f"{where}: reference line 'target' is for a bar, one bar per member (not stacked)")
        if "label" in r:
            raise ValueError(f"{where}: reference line 'target' has no label: say the line in the subtitle")
        bands = r.get("bands")
        if bands is not None and not (1 <= len(bands) <= MAX_BANDS and all(0 < p < 100 for p in bands)
                                      and bands == sorted(set(bands))):
            raise ValueError(f"{where}: target 'bands' are 1 to {MAX_BANDS} percents of the target, rising, each "
                             f"above 0 and below 100 (the line is 100), got {bands}")
    if t == "band":  # a pale band between two values (decisions/043)
        if "from" not in r or "to" not in r:
            raise ValueError(f"{where}: reference band needs 'from' and 'to' (numbers or integer parameters)")
        ends = [_param(v, where, params).value if isinstance(v, str) else v for v in (r["from"], r["to"])]
        if not ends[0] < ends[1]:
            raise ValueError(f"{where}: reference band 'from' {ends[0]} must be below 'to' {ends[1]}")
    extra = [k for k, ok in (("value", t in ("const", "date")), ("parameter", t == "param"),
                             ("measure", t in ("avg", "median", "target")), ("from", t == "band"), ("to", t == "band"),
                             ("bands", t == "target"))
             if k in r and not ok]
    if extra:
        raise ValueError(f"{where}: reference line '{t}' does not take {extra}")
    if "measure" in r:
        if "table_calc" in r["measure"]:
            raise ValueError(f"{where}: a reference line over a table calculation is not supported yet")
        if r["measure"]["field"] not in calc_names:
            prof.col(r["measure"]["field"])  # unknown field -> the profiler's error with the column list


def params_used(spec):
    """Parameters that a reference line uses (their control moves it)."""
    out = {r["parameter"] for s in spec["sheets"] for r in lines(s) if r["type"] == "param"}
    return out | {v for s in spec["sheets"] for r in lines(s) if r["type"] == "band"
                  for v in (r["from"], r["to"]) if isinstance(v, str)}


# ---- generated table calcs --------------------------------------------------------------------------------------
def _value(b, m):
    """SUM([Sales]) / [Calculation_...] of a measure, as a table calc's XML formula: (formula, raw deps, calc deps)."""
    col = b.col(m["field"])
    calc = getattr(col, "calc", None)
    if calc is not None and calc.is_agg:
        return f"[{col.name}]", calc.raw_deps, [calc.name] + calc.calc_deps
    agg = m.get("agg", "sum").upper()
    if calc is not None:
        return f"{agg}([{col.name}])", calc.raw_deps, [calc.name] + calc.calc_deps
    return f"{agg}([{col.name}])", [col.name], []


def table_calcs(b):
    """{caption: Calc} of the color flags: WINDOW_AVG (color vs avg) and LOOKUP (history change)."""
    out = {}

    def add(name, formula, datatype, raw, deps):
        out[name] = TableCalc(name, formula, None, datatype, True, calc_id(name), formula, None, sorted(raw), deps)

    for s in b.spec["sheets"]:
        if vs_avg(s):
            v, raw, deps = _value(b, s["measure"])
            add(vs_calc(s), f"{v} >= WINDOW_AVG({v})", "boolean", raw, deps)
    for p in b.worksheets:
        if p["type"] == "card_history" and changes(p):
            v, raw, deps = _value(b, p["measure"])
            prev = f"LOOKUP({v}, -1)"
            up, down = ">", "<"
            if p["measure"].get("good", "up") == "down":
                up, down = down, up
            add(change_calc(p), f'IF {v} {up} {prev} THEN "better" ELSEIF {v} {down} {prev} THEN "worse" '
                                f'ELSE "same" END', "string", raw, deps)
    return out


# ---- sheet shape ------------------------------------------------------------------------------------------------
def encode(b, s, fields, enc):
    """bar / line / area: the color flag of color vs avg, and the measures a reference line averages instead of the
    sheet's own (on Detail: a reference line can only use a field of the view)."""
    from .build import Field  # build imports this module
    if vs_avg(s):
        flag = Field(b.col(vs_calc(s)), "agg", "user", discrete=True)
        flag.along = fields[0]  # WINDOW_AVG over the bars: computed along the bar dimension
        fields.append(flag)
        enc.append(("color", b.q(flag.name)))
    for r in lines(s):
        if "measure" in r:
            m = b._measure(r["measure"])
            if m.name not in {f.name for f in fields}:
                fields.append(m)
                enc.append(("lod", b.q(m.name)))


def history(b, p, fields, enc):
    """card_history with history_color change: the change flag replaces the current-period flag on Color."""
    from .build import Field
    if not changes(p):
        return
    flag = Field(b.col(change_calc(p)), "agg", "user", discrete=True)
    flag.along = fields[0]  # LOOKUP(-1): the period before, along the date axis
    fields[2] = flag
    enc[0] = ("color", b.q(flag.name))


def table_calc(b, ci, f):
    """The compute-using of a generated table calc flag (Specific Dimensions, as decisions/011)."""
    along = getattr(f, "along", None)
    if along is not None:
        ET.SubElement(ci, "table-calc", {"ordering-field": b.q(along.name), "ordering-type": "Field"})


def calculation(el, calc):
    """<calculation> of a generated table calc: Desktop adds its default compute-using inside it on save
    (golden_reflines_2025_1); the sheet's own compute-using is on its column-instance."""
    if isinstance(calc, TableCalc):
        ET.SubElement(el, "table-calc", {"ordering-type": "Rows"})


def _along(b, s):
    """The field a sheet's color flag is computed along (and the flag's caption), or None."""
    from .build import Field
    if vs_avg(s):
        return b._dim(s["dimension"]), vs_calc(s)
    if s["type"] == "card_history" and changes(s):
        return Field(b.col(s["card"]["date"]["field"]), "date", s["card"]["date"].get("level", "month")), change_calc(s)
    return None


def along_fields(b):
    """Fields the color flags are computed along: Desktop declares them in the datasource, next to the flags'
    palette maps (golden_reflines_2025_1)."""
    out = {}
    for s in b.worksheets:
        a = _along(b, s)
        if a:
            out.setdefault(a[0].name, a[0])
    return [out[k] for k in sorted(out)]


def instance_table_calc(b, ci):
    """A color flag's column-instance in the datasource (its palette map refers to it) carries the same
    compute-using as on the sheet, as Desktop writes it (reference Ads Campaigns); without it Desktop drops the map."""
    for s in b.worksheets:
        a = _along(b, s)
        if a and ci.get("column") == f"[{b.calc_cols[a[1]].name}]":
            ET.SubElement(ci, "table-calc", {"ordering-field": b.q(a[0].name), "ordering-type": "Field"})


def helpers(s, fields):
    """Fields that only drive the look: the color flags and the measures behind a reference line."""
    names = {vs_calc(s)} | ({change_calc(s)} if s["type"] == "card_history" else set())
    own = {f.name for f in fields[:2]}
    extra = {m["field"] for r in lines(s) if "measure" in r for m in [r["measure"]]}
    return [f for f in fields[2:] if getattr(f.col, "caption", None) in names
            or (f.name not in own and getattr(f.col, "caption", f.col.name) in extra)]


def palettes(b):
    """Palette maps of the color flags, as colors.palettes: {instance: (column, derivation, [(bucket, color)])}."""
    out = {}
    for s in b.worksheets:
        if vs_avg(s):
            col = b.calc_cols[vs_calc(s)].name
            out[f"[usr:{col}:nk]"] = (col, "User", [("true", COLOR["accent"]), ("false", COLOR["mark_muted"])])
        if s["type"] == "card_history" and changes(s):
            col = b.calc_cols[change_calc(s)].name
            out[f"[usr:{col}:nk]"] = (col, "User", [('"better"', COLOR["good"]), ('"worse"', COLOR["bad"]),
                                                    ('"same"', COLOR["mark_muted"])])
    return out


# ---- XML --------------------------------------------------------------------------------------------------------
def physical(s):
    """[(id, line spec, band)] of a sheet's lines as drawn: a band is two lines, its 'from' and 'to' edges (band =
    (edge, band spec), else None); a target's zones one distribution under its line (band = ('zones', target spec)).
    Bands come first: the white fill above a band's top would cover a line drawn under it (z-order)."""
    out, rest = [], []
    for r in lines(s):
        if r["type"] == "band":
            lo, hi = edges(r)
            out += [(lo, ("from", r)), (hi, ("to", r))]
        else:
            if r.get("bands"):
                rest.append((r, ("zones", r)))
            rest.append((r, None))
    return [(f"refline{i}", r, band) for i, (r, band) in enumerate(out + rest)]


def pane(b, pane_el, s, fields):
    """<reference-line> per line, in the pane after its encodings and label data (XSD order)."""
    from . import benchmark
    if total_end(s):  # the stack total as a line's value at the bar end: the reference's form, the line itself off
        axis = b.q(fields[1].name)
        ET.SubElement(pane_el, "reference-line", {
            "axis-column": axis, "enable-instant-analytics": "true", "formula": "total", "id": "refline0",
            "label-type": "value", "scope": "per-cell", "value-column": axis, "z-order": "1"})
    if not lines(s):
        return
    bench = benchmark.is_bench(s)  # Measure Values on the axis (SOC: axis-column [Multiple Values])
    axis = b.q("[Multiple Values]") if bench else b.q(fields[1].name)
    for i, (rid, r, band) in enumerate(physical(s)):
        t = r["type"]
        if band and band[0] == "zones":  # reference 'Bullet Graph' (Show Me's bullet): percents of each bar's target
            zones = ET.SubElement(pane_el, "reference-line", {
                "axis-column": axis, "enable-instant-analytics": "false", "fill-above": "true",
                "fill-below": "true", "formula": "min", "id": rid, "label-type": "none", "percentage-bands": "true",
                "scope": "per-cell", "symmetric": "false", "value-column": b.q(b._measure(r["measure"]).name),
                "z-order": str(i + 1)})
            for p in r["bands"]:
                ET.SubElement(zones, "reference-line-value", percentage=_literal(p, False))
            continue
        if t == "date":  # SOC 'Jun 1st': a constant on the date axis, the label its text only. Without SOC's
            # tooltip-type: Desktop 2025.1 rejects it ("attribute 'tooltip-type' is not declared", check-desktop)
            day = b.q(fields[0].name)
            ET.SubElement(pane_el, "reference-line", {
                "axis-column": day, "enable-instant-analytics": "true", "formula": "constant", "id": rid,
                "label": label(r), "label-type": "custom", "scope": "per-pane",
                "value": f"#{date_of(r).isoformat()} 00:00:00#", "value-column": day, "z-order": str(i + 1)})
            continue
        if t == "param":
            value_col = b.params[r["parameter"]].ref
        elif "measure" in r:
            value_col = b.q(b._measure(r["measure"]).name)
        else:  # a constant: its axis. On Measure Values too: SOC's lines there name a measure of the view, but
            # Desktop 2025.1 rewrites that to [Multiple Values] on Save As (decisions/061, golden_benchmark)
            value_col = axis
        attrs = {"axis-column": axis, "enable-instant-analytics": "true", "formula": FORMULA[t], "id": rid}
        text = band_label(band) if band else None if t == "target" or r.get("silent") else f"{label(r)} <Value>"
        if text:
            attrs.update({"label": text, "label-type": "custom"})
        else:
            attrs["label-type"] = "none"
        if t not in ("const", "target"):
            attrs["probability"] = "95"
        attrs["scope"] = "per-cell" if t == "target" else "per-table"
        if t == "const":
            attrs["value"] = _literal(r["value"], _real(fields[1]))
        attrs.update({"value-column": value_col, "z-order": str(i + 1)})
        ET.SubElement(pane_el, "reference-line", attrs)


def band_label(band):
    """A band's text: at its top edge, only when the spec names it ('Target range'); the edges have none."""
    edge, r = band
    return r["label"] if edge == "to" and r.get("label") else None


def zones(s):
    """Ids of a sheet's target zones (a distribution per bar)."""
    return [rid for rid, _, band in physical(s) if band and band[0] == "zones"]


def bullet(s):
    """A bar with zones under its target: a bullet graph (decisions/152)."""
    return any(r.get("bands") for r in lines(s))


def mark_style(pane, s):
    """A bullet's bar: thinner than the row its zones fill."""
    if not bullet(s):
        return
    st = pane.find("style")
    st = ET.SubElement(pane, "style") if st is None else st
    rule = st.find("style-rule[@element='mark']")
    rule = ET.SubElement(st, "style-rule", element="mark") if rule is None else rule
    ET.SubElement(rule, "format", attr="size", value=BULLET_BAR_SIZE)


def _real(m):
    """The axis measure holds real numbers: a real column or calc, or an average."""
    return m.derivation == "Avg" or m.col.datatype == "real"


def _literal(v, real):
    """A constant as Desktop writes it for the axis type: '105000.0' on a real axis (golden_reflines_2025_1), '100'
    on an integer one (lab), a fraction in 17 digits: '0.14999999999999999' for 0.15 (178, like pareto)."""
    if not float(v).is_integer():
        return f"{float(v):.17g}"
    return repr(float(v)) if real else str(int(v))


def style(b, style_el, s, fields):
    """The look of each line (worksheet style-rule 'refline', Desktop's place: after pane and worksheet, before the
    gridline rules): dashed muted 1px, the label muted at FONT ref_label, its number format from the value."""
    refs = lines(s)
    if not refs and not total_end(s):
        return
    rule = colors._rule(style_el, "refline", before=("gridline", "zeroline", "table-div"))
    got = b.expected.get(record(s["name"]), {})
    fmt = b.number_format(fields[1].col)
    text = [("font-size", str(FONT["ref_label"])), ("color", COLOR["muted"])]
    if total_end(s):  # reference: no line, the total right of the bar end as a bar label (barlabels: 9pt text color)
        from .barlabels import LABEL_PT  # in the row's middle: without vertical-align at the cell's foot (165)
        for attr, value in [("fill-above", "#00000000"), ("fill-below", "#00000000"), ("stroke-size", "0"),
                            ("line-visibility", "off"), ("font-size", str(LABEL_PT)), ("color", COLOR["text"]),
                            ("text-align", "right"), ("vertical-align", "center"),
                            ("text-format", text_format(None, fmt))]:
            ET.SubElement(rule, "format", attr=attr, id="refline0", value=value)
    for rid, r, band in physical(s):
        if band and band[0] == "zones":  # their fill: the refband rule below
            continue
        if band:  # SOC's shading: an edge without a line, the area above the 'from' edge pale, above 'to' white
            fill = COLOR["band"] if band[0] == "from" else COLOR["card_bg"]
            formats_ = [("fill-above", fill), ("fill-below", "#00000000"), ("stroke-size", "0"),
                        ("line-visibility", "off")] + (text if band_label(band) else [])
        elif r["type"] == "target":  # reference 'Color vs. Target': a solid line across each bar, no label
            formats_ = [("fill-above", "#00000000"), ("fill-below", "#00000000"), ("stroke-size", str(REF_STROKE_PX)),
                        ("line-visibility", "on"), ("line-pattern-only", "solid"), ("stroke-color", COLOR["text"])]
        elif r["type"] == "date":  # SOC 'Jun 1st': solid, no number in its label
            formats_ = [("fill-above", "#00000000"), ("fill-below", "#00000000"), ("stroke-size", str(REF_STROKE_PX)),
                        ("line-visibility", "on"), ("line-pattern-only", "solid"), ("stroke-color", COLOR["muted"])
                        ] + text
        else:
            formats_ = [("fill-above", "#00000000"), ("fill-below", "#00000000"), ("stroke-size", str(REF_STROKE_PX)),
                        ("line-visibility", "on"), ("line-pattern-only", "dashed"), ("stroke-color", COLOR["muted"])
                        ] + ([] if r.get("silent") else text + [("text-format", text_format(got.get(label(r)), fmt))])
            if s["type"] in ("line", "area"):  # 'goal 95' where the line ends, by the latest values (170)
                formats_.append(("text-align", "right"))
        for attr, value in formats_:
            ET.SubElement(rule, "format", attr=attr, id=rid, value=value)
    if zones(s):  # the darkest zone lowest, no edges (reference: the default palette, not reversed)
        band_rule = colors._rule(style_el, "refband", before=("gridline", "zeroline", "table-div"))
        for rid in zones(s):
            for attr, value in [("reverse-palette", "false"), ("stroke-size", "0"), ("line-visibility", "off")]:
                ET.SubElement(band_rule, "format", attr=attr, id=rid, value=value)
        div = colors._rule(style_el, "table-div", before=())
        for f in div.findall("format[@scope='rows']"):
            div.remove(f)
        for attr, value in [("line-visibility", "on"), ("stroke-size", BULLET_GAP_PX),
                            ("stroke-color", COLOR["card_bg"]), ("line-pattern-only", "solid"), ("div-level", "1")]:
            ET.SubElement(div, "format", attr=attr, scope="rows", value=value)


def label_slots(plot_px, lo, hi, ends, refs):
    """[(text-align, vertical-align)] for each labelled line of refs (values, in order), so its label covers neither
    a series' end label nor another line's label (decisions/184). plot_px: the plot's height; lo, hi: the axis;
    ends: {'right': [last values], 'left': [first values]}. The first slot of LABEL_SLOTS that stands clear wins, so
    a line far from the labels keeps Desktop's default place; with none clear, the one farthest from its neighbours."""
    px = plot_px * AXIS_DATA_SHARE / ((hi - lo) or abs(hi) or 1)
    y = lambda v: (hi - v) * px
    taken = {side: [y(v) - END_LABEL_ABOVE_PX for v in vals] for side, vals in ends.items()}
    out = []
    for v in refs:
        def centre(slot):
            return y(v) + (REF_LABEL_OFF_PX if slot[1] == "bottom" else -REF_LABEL_OFF_PX)

        def clearance(slot):
            return min((abs(centre(slot) - c) for c in taken.get(slot[0], [])), default=float("inf"))
        slot = next((sl for sl in LABEL_SLOTS if clearance(sl) >= LABEL_CLEAR_PX), None) or max(LABEL_SLOTS, key=clearance)
        taken.setdefault(slot[0], []).append(centre(slot))
        out.append(slot)
    return out


def place_labels(b, wb):
    """A line's labelled reference lines apart from its end labels ('target 95' over 'City 95', decisions/184). After
    the dashboards: the px per unit come from the zone, the smallest one when a sheet sits on several."""
    from . import benchmark, compareviz, fit
    plots = {}
    for _, z, ws, size in fit._zones(wb):
        need = fit.chart_need(ws, z, size)
        if need:
            plot = max(need[0] - need[1] + fit.PLOT_MIN_PX, fit.PLOT_MIN_PX)
            plots[ws.get("name")] = min(plot, plots.get(ws.get("name"), plot))
    rules = {w.get("name"): w.find("table/style/style-rule[@element='refline']") for w in wb.iter("worksheet")}
    for s in b.worksheets:
        if not benchmark.ends(s) or stacked(s) or compareviz.facet(s) or benchmark.is_bench(s):  # see the decision
            continue
        with b._source_of(s["name"]):
            got = b.expected.get(record(s["name"]), {})
            shown = [(rid, got[label(r)]) for rid, r, band in physical(s)
                     if not band and r["type"] in ("avg", "median", "const", "param") and not r.get("silent")
                     and got.get(label(r)) is not None]
            if not shown:
                continue
            last = b.expected.get(benchmark.ends_record(s["name"]), {}).values()
            ends = {"right": [e["last"] for e in last], "left": [e["first"] for e in last if "first" in e]}
            marks = [x for v in b.expected.get(s["name"], {}).values()
                     for x in (v.values() if isinstance(v, dict) else [v]) if x is not None]
            vals = marks + [v for _, v in shown]
            lo, hi = axis_range(s) or (min(vals), max(vals))
            if not axis_range(s) and (s["type"] == "area" or (s.get("axis") or {}).get(
                    "zero", zero_default(b, b.axis_fields[s["name"]][1]))):
                lo, hi = min(lo, 0), max(hi, 0)
        slots = label_slots(plots.get(s["name"], SHEET_PLOT_PX), lo, hi, ends, [v for _, v in shown])
        for (rid, _), (align, valign) in zip(shown, slots):
            rule = rules[s["name"]]
            if align != "right":
                rule.find(f"format[@attr='text-align'][@id='{rid}']").set("value", align)
            if valign != "top":  # Desktop's default, not written
                ET.SubElement(rule, "format", attr="vertical-align", id=rid, value=valign)


def text_format(v, fmt=None):
    """Number format of a line's label: the measure's own format (decisions/032), else whole numbers ('Average 76'),
    one decimal below 10 ('Average 2.6'). Without it Desktop writes all digits: 'Average 94.714285714' (lab)."""
    if fmt is not None:
        return formats.tableau(fmt)
    if v is not None and abs(v) < 10 and not float(v).is_integer():
        return "n#,##0.0;-#,##0.0"
    return "n#,##0;-#,##0"


# ---- expected numbers -------------------------------------------------------------------------------------------
def values(s, marks, pars):
    """{label: value} of a sheet's lines. marks(measure spec) -> {mark key: value} as expected.py groups the sheet;
    a stacked sheet's keys 'position | segment' add up per position."""
    out = {}
    for r in lines(s):
        t = r["type"]
        if t == "const":
            out[label(r)] = r["value"]
            continue
        if t == "param":
            out[label(r)] = pars[r["parameter"]].value
            continue
        if t == "date":  # a day, not a number
            continue
        if t == "band":  # its two edges as numbers (decisions/043)
            for edge, v in zip(("from", "to"), (r["from"], r["to"])):
                out[f"{label(r)} {edge}"] = pars[v].value if isinstance(v, str) else v
            continue
        if t == "target":  # per bar, no number of its own: the count of the bars below it (color below target)
            have, target = marks(s["measure"]), marks(r["measure"])
            out[BELOW] = sum(1 for k, v in have.items() if v is not None and target.get(k) is not None
                             and v < target[k])
            for p in r.get("bands", []):  # the bars that end in a zone under p % of their target
                out[zone_key(p)] = sum(1 for k, v in have.items() if v is not None and target.get(k) is not None
                                       and v < target[k] * p / 100)
            continue
        got = marks(r.get("measure") or s["measure"])
        if stacked(s):
            totals = {}
            for k, v in got.items():
                if v is not None:
                    pos = k.split(" | ")[0]
                    totals[pos] = totals.get(pos, 0) + v
            got = totals
        vals = [v for v in got.values() if v is not None]
        out[label(r)] = None if not vals else (sum(vals) / len(vals) if t == "avg" else statistics.median(vals))
    return out


# ---- a line's value axis (decisions/170) ------------------------------------------------------------------------
RATIO = re.compile(r"/|\b(?:AVG|MEDIAN)\s*\(", re.I)  # an aggregate calc of a share, a mean or a ratio


def zero_default(b, m):
    """Include zero by default: off for a share, a percent, a mean or a ratio (their story is the span, 88-96, not
    0-100), on for a count or a sum that grows from nothing."""
    from .ink import PERCENT_CALCS  # ink imports this module
    if formats.is_percent(b.number_format(m.col)) or (m.tc or {}).get("type") in PERCENT_CALCS:
        return False
    if m.derivation in ("Avg", "Median"):
        return False
    calc = getattr(m.col, "calc", None)
    return not (m.derivation == "User" and calc is not None and bool(RATIO.search(calc.formula)))


def axis_range(s):
    """(min, max) of a line's fixed value axis from axis {min, max}, else None."""
    ax = (s.get("axis") or {}) if s["type"] == "line" else {}
    return (ax["min"], ax["max"]) if "min" in ax else None


def line_axis(b, style_el, s, fields):
    """A line's value axis: fixed from axis {min, max}, else Include zero from axis.zero or zero_default; nothing when
    zero stays (Desktop's default). Desktop's encodings, first in the axis rule: range-type fixed (the KPI bars'
    form), domain-expand false (the dumbbell of decisions/143)."""
    if s["type"] != "line":
        return
    if s.get("benchmark"):  # Measure Values on Rows (decisions/043): Desktop's own axis
        if s.get("axis"):
            raise ValueError(f"Sheet '{s['name']}': axis is not supported with benchmark")
        return
    m, ax, fixed = fields[1], s.get("axis") or {}, axis_range(s)
    if fixed:
        lo, hi = fixed
        if lo >= hi:
            raise ValueError(f"Sheet '{s['name']}': axis min {lo:g} must be below max {hi:g}")
        vals = [x for v in b.expected.get(s["name"], {}).values()
                for x in (v.values() if isinstance(v, dict) else [v]) if x is not None]
        if vals and (min(vals) < lo or max(vals) > hi):  # a mark off a fixed axis is not drawn
            raise ValueError(f"Sheet '{s['name']}': axis {lo:g}..{hi:g} cuts the values "
                             f"{min(vals):g}..{max(vals):g}; widen it")
        attrs = {"attr": "space", "class": "0", "field": b.q(m.name), "field-type": "quantitative",
                 "max": f"{hi:g}", "min": f"{lo:g}", "range-type": "fixed"}
    elif ax.get("zero", zero_default(b, m)):
        return
    else:
        attrs = {"attr": "space", "class": "0", "domain-expand": "false", "field": b.q(m.name),
                 "field-type": "quantitative"}
    attrs.update({"scope": "rows", "type": "space"})
    colors._rule(style_el, "axis", before=()).insert(0, ET.Element("encoding", attrs))
