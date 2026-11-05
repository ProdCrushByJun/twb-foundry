"""Dual axis (todo 7.2, decisions/044): two measures on one shelf, folded onto one axis, a pane (layer) each with its
own mark class.

Spec:
- combo {dimension, bar, line, sort?}: bars of one measure by a dimension, a line of another on the second axis (ER
  Operation 'Patients vs Waiting Time'). Bars muted, 70% of a member's slot, their values at their ends (cell
  vertical-align top, decisions/165; 084 had them inside at the base), the line in the accent.
- donut {dimension, measure}: a pie of the measure's shares and a white circle on top with the total in its centre
  (SuperMart, E-Commerce, Help Desk); a legend sheet next to it lists 'member value (share)' (NovaCart, Admissions).
- lollipop {dimension, measure, sort?}: a thin bar and a circle at its end; the value a discrete header right of the
  member (reference 'Lollipop', Admissions 'Bar - Locations': rows Dim / SUM(M):ok). The circle's own label stood on
  it at the pane's edge (decisions/084).

XML (forms from the reference books, not guessed):
- the shelf holds both measures as a concatenation: '(A + B)' on Rows (combo, donut) or Columns (lollipop); the
  same measure twice for a donut and a lollipop ('(MIN(0) + MIN(0))', E-Commerce Channel '(M + M)').
- the fold is an axis encoding in the worksheet style: <encoding attr='space' class=<0 | 1> field=<B> fold='true'
  scope=<rows | cols> [synchronized='true'] type='space'/>; class '1' when B is A again (its second occurrence:
  SuperMart donut, E-Commerce Channel), '0' for another measure (ER weekday, Admissions Bar - Locations).
- one pane per layer after the default pane: id 1 with y-axis-name (x-axis-name) = A, id 2 with B and, when B is A,
  y-index (x-index) = '1'; each has its own <mark class> and mark-sizing marks-scaling-off, the size in its style.
- the hidden axis: <format attr='display' class=.. field=.. scope=.. value='false'/> (data-ink; the values are
  labels). Desktop needs no manifest flag for any of it (the four reference books carry none of their own).
- a dumbbell's zero: false (polish-26b): Edit Axis 'Include zero' off is domain-expand='false' on the axis encoding
  (WebsiteTraffic sparklines, Enterprise Risk): on the first measure's class 0 encoding and on the fold; the range
  stays automatic, so a filter moves it (a fixed range kept the old one, decisions/142).
"""
import copy
import math
import xml.etree.ElementTree as ET

from . import design, formats, pareto
from .design import COLOR, FONT, KPI_VALUE_DENSE, PIE_PX_PER_SIZE

TYPES = ("combo", "donut", "lollipop", "dumbbell", pareto.TYPE)
LEGEND = "donut_legend"  # the donut's legend text: a part of the donut (build._expand)
DOTS = "donut_dots"  # its dots, a sheet of their own left of the text (decisions/069)
LEGEND_PARTS = (DOTS, LEGEND)
FILLS = ("donut",) + LEGEND_PARTS  # fit their zones (window zoom entire-view, as SuperMart's donut)
# Mark sizes (pane style 'size'): a thin stick under a circle for the lollipop. The donut's ring and hole are sized
# from its zone (fit, decisions/069); 2.6 / 1.6 stay for a donut on no dashboard. A combo's Bar is size / 2 of a
# member's slot whatever the slot's px (lab dual_bars: 0.6 -> 18 of 61px, 1.8 -> 55 of 61 and 133 of 147): 1.4 is
# 70%, wide enough for its value (0.6 left '85,565' twice as wide as its 27px bar, decisions/165).
SIZE = {"pie": "2.6", "hole": "1.6", "stick": "0.05", "dot": "0.7", "bar": "1.4", "span": "0.15"}
SELECTION = "selection-relaxation-allow"
# A combo's bar values (decisions/165, the user's choice of 2026-10-31): at the bar's end, above it (084's 'bottom',
# inside at the base as ER weekday, read as the axis' labels). The line may run through the top ones (lab
# dual_labels C3); its axis is the data's own, not fixed.
BAR_LABEL_ALIGN = "top"
# The legend's dot (decisions/069): a Circle, marks-scaling-off (as the KPI status dot, 062), ~9.5px per unit of size
# (lab legend4: 1.2 -> 11px, 2.0 -> 19, 3.0 -> 28), centred in a DOT_PX pane
DOT_SIZE = "1.2"
DOT_PX = 12
# The ring in its panel (decisions/069): its diameter is RING_FILL of the panel's shorter side (the references size
# it to their zones: RWFD NYC 0.93 in 70 x 82, Enterprise Risk 1.9 in 135 x 190, Bootcamp 1.66 in 297 x 316; Desktop
# draws the pane exactly as the zone less its margins, lab size2); the hole in the proportion it had (1.6 / 2.6,
# between SuperMart's 1.33 / 2.6 and E-Commerce's 1.7 / 2.0). The hole holds the total and its caption with
# HOLE_PAD_PX each side; RING_MIN_PX is the smallest ring of the references (RWFD NYC 0.93).
RING_FILL = 0.95
HOLE = 1.6 / 2.6
HOLE_PAD_PX = 4
RING_MIN_PX = 74


def is_dual(s):
    return s["type"] in TYPES


def change_calc(s):
    """A dumbbell's span: to - from, the Gantt bar's size (SOC 'Line - Uptime': size = the difference)."""
    return f"{s['name']} · Change"


def axis_calc(s):
    """MIN(0): the one-mark axis both pies of a donut stand on."""
    return f"{s['name']} · Axis"


def share_calc(s):
    return f"{s['name']} · Share"


def legend_name(s):
    return f"{s['name']} · Legend"


def total_record(s):
    """expected.py record of a donut's centre."""
    return f"{s['name']} · Total"


def label(m):
    return m.get("label", m["field"])


def dots_name(s):
    return f"{s['name']} · Dots"


def parts(s):
    """A donut, its legend's dots and its legend's text, side by side in its cell."""
    return [s, {"name": dots_name(s), "type": DOTS, "donut": s}, {"name": legend_name(s), "type": LEGEND, "donut": s}]


def measures(s):
    """The measure objects of a dual-axis sheet (formats.measures)."""
    return [s[k] for k in ("bar", "line", "from", "to") if isinstance(s.get(k), dict)]


def value_header(m):
    """A lollipop's value as a discrete header: its measure's instance as Desktop writes a discrete measure,
    [sum:M:ok] ordinal (reference 'Lollipop' [usr:..:ok], Admissions [ctd:Applicant Id:ok]; decisions/084)."""
    v = copy.copy(m)
    v.name, v.type = m.name.replace(":qk]", ":ok]"), "ordinal"
    return v


def value_header_style(b, s):
    """(px, text-format) of a lollipop's value header: its number format (the measure's, else the one Tableau's
    automatic label shows, registry.automatic) written on the header, whose own automatic one shows every decimal
    ('8 38..' for a SUM of Profit in lab lolli_formats); the width its widest value takes at the header font plus a
    header's insets (decisions/064, 084)."""
    from . import registry
    values = list(b.expected[s["name"]].values())
    fmt = registry._fmt(b, s["measure"], values)
    px = max(design.text_px(formats.render(v, fmt), FONT["table_header"]) for v in values) + design.HEADER_TEXT_PAD_PX
    return px, formats.tableau(fmt)


def check(spec):
    """Spec checks the schema cannot make."""
    calc_names = {c["name"] for c in spec.get("calcs", [])}
    for s in spec["sheets"]:
        if not is_dual(s):
            continue
        where = f"Sheet '{s['name']}'"
        if pareto.is_pareto(s):  # its own checks (decisions/157)
            continue
        ms = ([s["bar"], s["line"]] if s["type"] == "combo" else [s["from"], s["to"]] if s["type"] == "dumbbell"
              else [s["measure"]])
        if any("table_calc" in m for m in ms):
            raise ValueError(f"{where}: table calculations on a {s['type']} are not supported yet")
        if s["type"] == "combo" and (s["bar"]["field"], s["bar"].get("agg", "sum")) == \
                (s["line"]["field"], s["line"].get("agg", "sum")):
            raise ValueError(f"{where}: bar and line are the same measure; a combo shows two")
        if s["type"] == "dumbbell" and (s["from"]["field"], s["from"].get("agg", "sum")) == \
                (s["to"]["field"], s["to"].get("agg", "sum")):
            raise ValueError(f"{where}: from and to are the same measure; a dumbbell shows two")
        if s["type"] == "donut" and s["measure"]["field"] in calc_names:
            raise ValueError(f"{where}: a donut takes a CSV column for now (its share is generated from it)")


def _agg(m, calc_names):
    return (f"[{m['field']}]" if m["field"] in calc_names and "agg" not in m
            else f"{m.get('agg', 'sum').upper()}([{m['field']}])")


def calcs(spec):
    """A donut's axis MIN(0) and its share of the total along its dimension (registry share, decisions/039)."""
    names = {c["name"] for c in spec.get("calcs", [])}
    out = []
    for s in spec["sheets"]:
        if s["type"] == "dumbbell":
            fmt = s["to"].get("format") or s["from"].get("format")
            out.append({"name": change_calc(s), "formula": f"{_agg(s['to'], names)} - {_agg(s['from'], names)}",
                        **({"format": fmt} if fmt else {})})
        if s["type"] == "donut":
            a = _agg(s["measure"], names)
            out += [{"name": axis_calc(s), "formula": "MIN(0)"},
                    {"name": share_calc(s), "formula": f"{a} / TOTAL({a})", "compute_using": [s["dimension"]],
                     "format": "pct0"}]
    return out


def same_unit(b, s, f1, f2):
    """Both layers measure one thing: the same field, or two measures in the same explicit number format (dollars
    and dollars). Their axes are then synchronized: one scale, the line or circle reads against the bar."""
    if f1.col.name == f2.col.name:
        return True
    a, c = b.number_format(f1.col), b.number_format(f2.col)
    return a is not None and a == c


# ---- the ring in its zone (decisions/069) ----------------------------------------------------------------------------
def _number(b, s, value):
    """A value of the donut's measure as the workbook shows it: its format, else Tableau's automatic one."""
    from . import registry
    return formats.render(value, registry._fmt(b, s["measure"], [value]))


def hole_need_px(b, s):
    """(px, what) the hole's diameter that holds the total (bold, KPI_VALUE_DENSE) and its caption whole."""
    total = _number(b, s, b.expected[total_record(s)])
    cap = label(s["measure"])
    t, c = design.text_px(total, KPI_VALUE_DENSE, bold=True), design.text_px(cap, FONT["block_subtitle"])
    return max(t, c) + 2 * HOLE_PAD_PX, f"the total '{total}'" if t >= c else f"the caption '{cap}'"


def ring_need_px(b, s):
    """(px, why) the smallest ring of a donut: its hole holds the total and the caption, and RING_MIN_PX."""
    hole, what = hole_need_px(b, s)
    need = math.ceil(hole / HOLE)
    return (need, f"{what} in its {hole}px hole") if need > RING_MIN_PX else (RING_MIN_PX, "the smallest ring")


def _size(px):
    return f"{px / PIE_PX_PER_SIZE:.3f}"


def axis_record(name):
    """expected: the span a dumbbell's axis without zero covers (polish-26b)."""
    return f"{name} · Axis"


def fit(b, p, w_px, h_px):
    """A donut's ring from its dashboard zone, w_px x h_px inside the zone's margins (decisions/069): RING_FILL of the
    shorter side, the hole in proportion; a ring too small for its total refuses the build. On several dashboards
    the smallest zone sizes it."""
    if p["type"] != "donut":
        return
    ring = int(min(w_px, h_px) * RING_FILL)
    need, why = ring_need_px(b, p)
    if ring < need:
        raise ValueError(f"Donut '{p['name']}': its zone leaves {w_px}x{h_px}px, a ring of {ring}px; it needs {need}px "
                         f"({why}): give the cell more width or height")
    if ring >= b.ring_px.get(p["name"], ring + 1):
        return
    b.ring_px[p["name"]] = ring
    pie, hole = b.rings[p["name"]]
    pie.set("value", _size(ring))
    hole.set("value", _size(ring * HOLE))


def legend_lines(b, s):
    """The legend's text per member, as its label draws it: [[(text, bold)] per line]: the member over
    '**value** (share)'."""
    return [[[(k, False)], [(_number(b, s, v["value"]), True), (f" ({formats.render(v['share'], 'pct0')})", False)]]
            for k, v in b.expected[legend_name(s)].items()]


def legend_need_px(b, s):
    """Width of the legend's text: its longest line at the label font (FONT table_header, 9pt) and a text cell's
    insets (TABLE_CELL_PAD_PX: golden_dual_axis wrapped '105 263 (33%)', ~100px drawn, in a 107px pane)."""
    pt = FONT["table_header"]
    return max(sum(design.text_px(t, pt, bold) for t, bold in line) for lines in legend_lines(b, s)
               for line in lines) + design.TABLE_CELL_PAD_PX


def split(b, s, x, w, width):
    """[(x, w)] in zone units of the donut, the dots and the legend text in their cell: the dots DOT_PX, the text as
    wide as it is, each with its zone's margins (zone_margin between parts, the block's edge outside), the ring the
    rest (decisions/069; an equal split cut both the legend and the ring of ITSM)."""
    inner = design.SPACE["zone_margin"]
    tw = b._units(legend_need_px(b, s) + inner + b._edge(), width)
    dw = b._units(DOT_PX + 2 * inner, width)
    rw = max(0, w - dw - tw)
    return [(x, rw), (x + rw, dw), (x + rw + dw, w - rw - dw)]


# ---- workbook (build.py) -------------------------------------------------------------------------------------------
def shape(b, s):
    """-> fields, rows, cols, encodings, labels, measure names (build.sheet_shape); the shelves of a dual-axis sheet
    are written by table()."""
    from .build import Field
    t = s["type"]
    if t == DOTS:  # rows = the dimension (headers hidden), a dot in the member's color
        dim = b._dim(s["donut"]["dimension"])
        return [dim], dim.name, None, [("color", b.q(dim.name))], False, None
    if t == LEGEND:  # rows = the dimension (headers hidden), its text: the member over value (share)
        d = s["donut"]
        dim, m = b._dim(d["dimension"]), b._measure(d["measure"])
        share = Field(b.col(share_calc(d)), "agg", "user")
        enc = [("text", b.q(m.name)), ("text", b.q(share.name)), ("text", b.q(dim.name))]
        return [dim, m, share], dim.name, None, enc, True, None
    if pareto.is_pareto(s):  # bars, the running share, the vital flag (decisions/157)
        return pareto.shape(b, s)
    if t == "combo":
        d = b._bar_dim(s)  # a date with date_level: a bar per period (decisions/140)
        return [d, b._measure(s["bar"]), b._measure(s["line"])], None, None, [], False, None
    if t == "dumbbell":
        return [b._dim(s["dimension"]), b._measure(s["from"]), b._measure(s["to"]),
                b._measure({"field": change_calc(s)})], None, None, [], False, None
    if t == "lollipop":
        m = b._measure(s["measure"])
        return [b._dim(s["dimension"]), m, value_header(m)], None, None, [], False, None
    d, m = b._dim(s["dimension"]), b._measure(s["measure"])
    axis = Field(b.col(axis_calc(s)), "agg", "user")
    share = Field(b.col(share_calc(s)), "agg", "user")
    return [d, m, axis, share], None, None, [], False, None


def _layers(b, s, fields):
    """[(axis Field, mark class, encodings [(tag, Field)], mark formats [(attr, value)], label runs | None,
    tooltip runs | None | 'empty')] of the two layers."""
    t = s["type"]
    if t == "card_history":  # a KPI sparkline and its max / min / last points (decisions/059)
        from . import kpi2
        return kpi2.point_layers(b, s, fields)
    if t == "combo":
        d, bar, line = fields
        dense = s.get("date_level") in ("week", "day")  # a value over each of many bars: none (polish-26)
        return [(bar, "Bar", [], [("size", SIZE["bar"]), ("mark-labels-show", "false" if dense else "true"),
                                  ("mark-labels-cull", "true"),
                                  ("mark-color", COLOR["mark_muted"])], None, None),
                (line, "Line", [], [("mark-labels-show", "false"), ("mark-color", COLOR["accent"])], None, None)]
    if pareto.is_pareto(s):  # the bars by the vital flag, the running share's line (decisions/157)
        return pareto.layers(b, s, fields)
    if t == "dumbbell":  # a muted span from 'from' by the change, the 'to' circle in accent with its value
        d, a, z, ch = fields
        return [(a, "GanttBar", [("size", ch)], [("size", SIZE["span"]), ("mark-labels-show", "false"),
                                                  ("mark-color", COLOR["mark_muted"])], None, None),
                (z, "Circle", [], [("size", SIZE["dot"]), ("mark-labels-show", "true"),
                                   ("mark-color", COLOR["accent"])], None, None)]
    if t == "lollipop":  # the value in its header, not on the circle (decisions/084)
        d, m, _ = fields
        return [(m, "Bar", [], [("size", SIZE["stick"]), ("mark-labels-show", "false"),
                                ("mark-color", COLOR["mark_muted"])], None, "empty"),
                (m, "Circle", [], [("size", SIZE["dot"]), ("mark-labels-show", "false"),
                                   ("mark-color", COLOR["accent"])], None, None)]
    d, m, axis, share = fields
    tip = [(f"<{b.q(d.name)}>", {"bold": "true"}), ("Æ\n", {}), (f"{label(s['measure'])}:\t", {"fontcolor": COLOR["muted"]}),
           (f"<{b.q(m.name)}>", {"bold": "true"}), ("Æ\n", {}), ("Share:\t", {"fontcolor": COLOR["muted"]}),
           (f"<{b.q(share.name)}>", {"bold": "true"})]
    total = [(f"<{b.q(m.name)}>", {"bold": "true", "fontcolor": COLOR["text"], "fontsize": str(KPI_VALUE_DENSE)}),
             ("Æ\n", {}), (label(s["measure"]), {"fontcolor": COLOR["muted"], "fontsize": str(FONT["block_subtitle"])})]
    return [(axis, "Pie", [("color", d), ("wedge-size", m), ("tooltip", share)],
             [("size", SIZE["pie"]), ("mark-labels-show", "false"), ("has-stroke", "true"),
              ("stroke-color", COLOR["card_bg"])], None, tip),
            (axis, "Pie", [("text", m)], [("size", SIZE["hole"]), ("mark-labels-show", "true"),
                                          ("mark-color", COLOR["card_bg"])], total, "empty")]


def _hidden(s, a, b2, same):
    """[(class, Field)] of the axes not drawn: the line's (its values in the tooltip), both of a lollipop (its value
    is in its header) and of a donut (a dummy axis)."""
    if pareto.is_pareto(s):  # both axes stay: the amounts left, the share right (decisions/157)
        return []
    if s["type"] in ("combo", "card_history", "dumbbell"):  # a card history hides its line's axis itself (build.worksheet)
        return [("0", b2)]
    return [("0", a), ("1" if same else "0", b2)]


def _runs(parent, runs):
    ft = ET.SubElement(parent, "formatted-text")
    for text, attrs in runs:
        ET.SubElement(ft, "run", attrs).text = text


def table(b, table_el, style, s, fields):
    """The axis fold and the hidden axes (worksheet style), the default pane and a pane per layer, the shelves."""
    layers = _layers(b, s, fields)
    (a, *_), (f2, *_) = layers
    same = a.name == f2.name
    across = s["type"] in ("lollipop", "dumbbell")  # the measures on Columns
    scope, xy = ("cols", "x") if across else ("rows", "y")
    axis = style.find("style-rule[@element='axis']")
    if axis is None:
        axis = ET.Element("style-rule", element="axis")
        style.insert(0, axis)
    no_zero = s["type"] == "dumbbell" and s.get("zero", True) is False  # the span, not zero (polish-26b)
    no_zero = no_zero or (s["type"] == "card_history" and bool(s["card"].get("separate_cards")))  # 178: the mock
    expand = {"domain-expand": "false"} if no_zero else {}
    enc = {"attr": "space", "class": "1" if same else "0", **expand, "field": b.q(f2.name),
           "field-type": "quantitative", "fold": "true", "scope": scope}
    if same or same_unit(b, s, a, f2) or s["type"] in ("card_history", "dumbbell"):  # a dumbbell: one scale  # points: values of the line (059)
        enc["synchronized"] = "true"
    enc["type"] = "space"
    axis.insert(0, ET.Element("encoding", enc))
    first = 1  # the hidden axes' formats go after the encodings
    if no_zero:  # the first measure's axis too (WebsiteTraffic: class 0 and the fold)
        axis.insert(0, ET.Element("encoding", {"attr": "space", "class": "0", **expand, "field": b.q(a.name),
                                               "field-type": "quantitative", "scope": scope, "type": "space"}))
        first = 2
    for i, (cls, f) in enumerate(_hidden(s, a, f2, same), first):
        axis.insert(i, ET.Element("format", {"attr": "display", "class": cls, "field": b.q(f.name), "scope": scope,
                                             "value": "false"}))
    panes = ET.SubElement(table_el, "panes")
    default = ET.SubElement(panes, "pane", {"selection-relaxation-option": SELECTION})
    ET.SubElement(ET.SubElement(default, "view"), "breakdown", value="auto")
    ET.SubElement(default, "mark", {"class": layers[0][1]})
    if s["type"] == "card_history":  # the history's average line, in the default pane as ER Operation's
        from . import reflines
        reflines.pane(b, default, s, fields)
    if pareto.is_pareto(s):  # the threshold on the share's axis (decisions/157)
        pareto.refline(b, default, s, fields)
        pareto.style(b, style, s, fields)
    for i, (f, mark, encs, fmts, lab, tip) in enumerate(layers, 1):
        attrs = {"id": str(i), "selection-relaxation-option": SELECTION, f"{xy}-axis-name": b.q(f.name)}
        if same and i == 2:
            attrs[f"{xy}-index"] = "1"
        pane = ET.SubElement(panes, "pane", attrs)
        ET.SubElement(ET.SubElement(pane, "view"), "breakdown", value="auto")
        ET.SubElement(pane, "mark", {"class": mark})
        ET.SubElement(pane, "mark-sizing", {"mark-sizing-setting": "marks-scaling-off"})
        if encs:
            e = ET.SubElement(pane, "encodings")
            for tag, ef in encs:
                ET.SubElement(e, tag, column=b.q(ef.name))
        if tip == "empty":
            ET.SubElement(ET.SubElement(pane, "customized-tooltip", {"show-buttons": "false"}), "formatted-text")
        elif tip:
            _runs(ET.SubElement(pane, "customized-tooltip", {"show-buttons": "false"}), tip)
        if lab:
            _runs(ET.SubElement(pane, "customized-label"), lab)
        pane_style = ET.SubElement(pane, "style")
        if s["type"] == "combo" and i == 1:  # the bars' values at their ends (decisions/165)
            ET.SubElement(ET.SubElement(pane_style, "style-rule", element="cell"), "format", attr="vertical-align",
                          value=BAR_LABEL_ALIGN)
        rule = ET.SubElement(pane_style, "style-rule", element="mark")
        for attr, value in fmts:
            el = ET.SubElement(rule, "format", attr=attr, value=value)
            if s["type"] == "donut" and attr == "size":  # the ring and the hole: set from its zone (fit)
                b.rings.setdefault(s["name"], []).append(el)
    d = fields[0]
    shelf = f"({b.q(a.name)} + {b.q(f2.name)})"
    member = f"({b.q(d.name)} / {b.q(fields[2].name)})" if s["type"] == "lollipop" else b.q(d.name)  # the member, its value
    rows, cols = ((member, shelf) if across else (shelf, None if s["type"] == "donut" else member))
    ET.SubElement(table_el, "rows").text = rows
    cols_el = ET.SubElement(table_el, "cols")
    if cols:
        cols_el.text = cols


def sheet_style(b, style, s, fields):
    """No field label over the dimension's headers (the block header names it; ER weekday: cols off). The legend
    hides its row headers: the member is in its label (Citizen Service Requests: style-rule label, display false).
    A lollipop's value header: its width and the number right-aligned (decisions/084)."""
    from .colors import _rule
    if not (is_dual(s) or s["type"] in LEGEND_PARTS) or s["type"] == "donut":
        return
    scope = "cols" if s["type"] in ("combo", pareto.TYPE) else "rows"
    ET.SubElement(_rule(style, "worksheet", before=("gridline", "zeroline", "table-div")), "format",
                  attr="display-field-labels", scope=scope, value="false")
    if s["type"] in LEGEND_PARTS:
        ET.SubElement(_rule(style, "label", before=("pane", "table", "worksheet", "gridline", "zeroline", "table-div")),
                      "format", attr="display", field=b.q(fields[0].name), value="false")
    if s["type"] == "lollipop":  # its value header as wide as its widest value, the number right (reference 'Lollipop')
        value, (px, fmt) = b.q(fields[2].name), value_header_style(b, s)
        ET.SubElement(_rule(style, "header", before=("label", "pane", "worksheet", "gridline", "zeroline", "table-div")),
                      "format", attr="width", field=value, value=str(px))
        label = _rule(style, "label", before=("pane", "table", "worksheet", "gridline", "zeroline", "table-div"))
        ET.SubElement(label, "format", attr="text-align", field=value, value="right")
        ET.SubElement(label, "format", attr="text-format", field=value, value=fmt)


def legend_pane(b, pane, s, fields):
    """The legend's label (decisions/069): the member over '**value** (share)'. A Text mark without a color: the
    color encoding would draw every run in the member's color, whatever its fontcolor (lab legend, legend2)."""
    dim, m, share = fields
    text, muted = {"fontcolor": COLOR["text"]}, {"fontcolor": COLOR["muted"]}
    _runs(ET.SubElement(pane, "customized-label"),
          [(f"<{b.q(dim.name)}>", text), ("Æ\n", {}), (f"<{b.q(m.name)}>", {"bold": "true", **text}),
           (" (", muted), (f"<{b.q(share.name)}>", muted), (")", muted)])


def legend_style(pane_style):
    """The legend's text from the left of its pane (Bootcamp 'By Device': cell text-align left)."""
    rule = ET.Element("style-rule", element="cell")
    ET.SubElement(rule, "format", attr="text-align", value="left")
    pane_style.insert(0, rule)


def dots_mark(pane, s):
    """After the <mark> of the legend's dots: no scaling (the KPI status dot, decisions/062)."""
    if s["type"] == DOTS:
        ET.SubElement(pane, "mark-sizing", {"mark-sizing-setting": "marks-scaling-off"})


def dots_style(pane, s):
    """The dot's size, the pane's style (as the KPI status dot's)."""
    if s["type"] != DOTS:
        return
    st = pane.find("style")
    st = ET.SubElement(pane, "style") if st is None else st
    ET.SubElement(ET.SubElement(st, "style-rule", element="mark"), "format", attr="size", value=DOT_SIZE)
