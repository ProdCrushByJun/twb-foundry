"""Comparison blocks (decisions/141): slope chart, box plot, waffle, small multiples (facet of a line / bar).

Spec:
- slope {dimension, period, measure, color?: {highlight}, good?: up | down, labels?: cull | spread}: a line per
  member of dimension between the two values of period kept by the sheet's filter on it (the first is 'before'), the
  member and its value at both ends; the line good / bad by the change, or the highlighted members accent and the
  rest muted; labels spread: every member's labels, moved apart where values are close;
- boxplot {dimension, measure, detail, points?}: a row per member, a dot per detail member (a row id) at its measure,
  Tableau's box (quartiles, median, whiskers 1.5 IQR); points false -> only the outliers are drawn;
- waffle {cells, measure, part: {field, values}, value?}: 100 squares (10 x 10), the share of part in the measure
  filled in the accent, the rest light grey; cells: a numeric row id that has 1..100 (a square per id, the sheet
  keeps them); value: the share as a big % over the squares;
- facet {field} on a line / bar: a panel per member of field side by side, its name over the panel, one shared axis.

XML (forms from Desktop books, data/refs/<type>):
- box: <reference-line ... boxplot-mark-exclusion boxplot-whisker-type='standard' formula='average' scope='per-cell'>
  on the measure's axis, Circle by the row id on Detail, a 'refboxplot' style rule (Higher Education Admissions 'Box
  Plot - Time');
- waffle: Square marks at continuous Column x Row positions, hidden axes (reference 'Waffle chart Index': no
  discrete headers, so Entire View, never a scrollbar), Color by a 'Box to Color' flag (id <= share), a white stroke
  (reference 'How to Create Waffle Charts'; there the grid is a 100-row helper table, here the row id itself, the share
  a FIXED LOD so the cells filter does not change it). The square's size and the axes' fixed ranges come from the
  zone (as a donut's ring, decisions/069): the grid a square of the zone's shorter side, its cells square whatever
  the zone's shape (a 2.6 size on 16px discrete cells scrolled, decisions/142). The ranges are of the grid, not the
  data: a filter does not move them; Desktop keeps a fixed range of an integer field in integers (re-save: -0.5 ->
  0), so a cell is UNIT wide, its square at the middle. value: the share in the sheet's title, a field reference to
  an aggregate on Detail (the reference's annotation text '<[...].[usr:Profit Ratio:qk]>', Enterprise Risk / GoodtoGo
  titles);
- slope: Line on a discrete period on Columns, the member on Detail, labels at the line ends (bump, decisions/140).
  labels spread (polish-26b): Tableau culls an overlapping label and never moves one, so the labels go on a second
  layer of a dual axis (Fastcampus 'Slope Chart': '(A + B)' on Rows, the fold synchronized, the second axis hidden;
  as dualaxis.py writes it), an invisible line (opacity 0, its labels stay) at label positions: per period, members
  ranked by value, each at least GAP above the one under it (p = max over j under it of v_j + (rank_i - rank_j) *
  GAP, the cascade 'max(v, previous + GAP)' unrolled). One table calc along the member and its color flag (the
  flag is a dimension of the view too: along the member alone it split the members by color, snapshot): RANK and
  LOOKUP at every offset (no calc references another table calc, decisions/034), so up to SPREAD_MAX members. GAP is
  LABEL_GAP of the axis's span (zero to the largest value of both periods, FIXED per member, the window over the
  members shown). The label one line, 'member value' (a customized label; two lines overlapped at GAP).
"""
import copy
import xml.etree.ElementTree as ET

from .design import COLOR

SLOPE, BOX, WAFFLE = "slope", "boxplot", "waffle"
SPREAD_MAX = 12  # a slope's members with labels spread: the label calc looks at every other one (2 * 11 offsets)
LABEL_GAP = 0.09  # a label's height in the axis's span: one 9pt line (~16px) apart on a plot of ~200px
TYPES = (SLOPE, BOX, WAFFLE)
MARK = {SLOPE: "Line", BOX: "Circle", WAFFLE: "Square"}
EMPTY = "#e8e8e8"  # a waffle's empty squares: lighter than mark_muted, as the reference's grey
SIDE = 10  # a waffle is SIDE x SIDE squares
SQUARE_PX_PER_SIZE = 9.5  # a marks-scaling-off mark is ~9.5px across per unit of size (the legend dot, decisions/069)
SQUARE_FILL = 0.8  # the square in its cell; the white stroke between squares
GRID_FILL = 0.95  # the grid in the zone's shorter side
CELL_PX = 16  # a cell off a dashboard (reference 25)
UNIT = 10  # a cell's width on the axes: the grid is 0..SIDE * UNIT, a square at UNIT * column + UNIT / 2


def kind(s):
    return s["type"] if s["type"] in TYPES else None


def name(s, part):
    return f"{s['name']} · {part}"


def spread(s):
    return kind(s) == SLOPE and s.get("labels") == "spread"


def label_calc(s):
    return name(s, "Label")


def _period_filter(s):
    return next((f for f in s.get("filters", []) if f["field"] == s["period"] and not f.get("exclude")), None)


def _q(types, field, v):
    """A value in a formula: quoted unless its CSV column is numeric (a calc's period is text: STR(YEAR(...)))."""
    return str(v) if (types or {}).get(field) in ("integer", "real") else f'"{v}"'


def check(spec, prof):
    """A slope's period keeps two values; highlighted members are in their field; a waffle's cells have 1..100 (the
    grid's squares; the sheet keeps them with its own filter)."""
    for s in spec["sheets"]:
        k = kind(s)
        if k == SLOPE:
            f = _period_filter(s)
            if f is None or len(f.get("default", [])) != 2:
                raise ValueError(f"Sheet '{s['name']}': a slope needs a sheet filter on '{s['period']}' that keeps "
                                 f"its two periods (default: [before, after])")
            hl = (s.get("color") or {}).get("highlight", [])
            missing = [v for v in hl if v not in prof.col(s["dimension"]).distinct]
            if missing:
                raise ValueError(f"Sheet '{s['name']}': highlight values {missing} are not in '{s['dimension']}'")
            n = len(prof.col(s["dimension"]).distinct)
            if spread(s) and n > SPREAD_MAX:
                raise ValueError(f"Sheet '{s['name']}': labels spread takes up to {SPREAD_MAX} members of "
                                 f"'{s['dimension']}', it has {n}; use labels cull")
        elif k == BOX:
            if prof.col(s["measure"]["field"]).datatype not in ("integer", "real"):
                raise ValueError(f"Sheet '{s['name']}': '{s['measure']['field']}' must be a numeric column")
        elif k == WAFFLE:
            col = prof.col(s["cells"])
            got = ({float(r[s["cells"]]) for r in prof.rows if r[s["cells"]] not in (None, "")}
                   if col.datatype in ("integer", "real") else set())
            if not set(map(float, range(1, SIDE * SIDE + 1))) <= got:
                raise ValueError(f"Sheet '{s['name']}': cells '{s['cells']}' must be a numeric id with every value "
                                 f"1..{SIDE * SIDE} (a square each)")
            missing = [v for v in s["part"]["values"] if v not in prof.col(s["part"]["field"]).distinct]
            if missing:
                raise ValueError(f"Sheet '{s['name']}': part values {missing} are not in '{s['part']['field']}'")
            cell = name(s, "Cell")
            if not any(f["field"] == cell for f in s.get("filters", [])):  # the 100 squares, as the helper table
                s.setdefault("filters", []).append({"field": cell, "default": [True]})


def calcs(spec, types=None):
    """slope: the change (FIXED per member, the sheet's period filter does not touch it) and its good flag, or the
    highlight flag; waffle: share, filled flag, row, column, the cells kept."""
    out = []
    for s in spec["sheets"]:
        k = kind(s)
        if k == SLOPE:
            a, z = _period_filter(s)["default"]
            m, d, p = s["measure"], s["dimension"], s["period"]
            agg = m.get("agg", "sum").upper()
            at = lambda v: f"{{FIXED [{d}] : {agg}(IF [{p}] = {_q(types, p, v)} THEN [{m["field"]}] END)}}"  # noqa: E731
            out.append({"name": name(s, "Change"), "formula": f"{at(z)} - {at(a)}"})
            hl = (s.get("color") or {}).get("highlight")
            if hl:
                out.append({"name": name(s, "Highlight"), "formula": " OR ".join(f'[{d}] = "{v}"' for v in hl)})
            else:
                op = ">=" if s.get("good", "up") == "up" else "<="
                out.append({"name": name(s, "Good"), "formula": f"[{name(s, 'Change')}] {op} 0"})
            if spread(s):  # both ends' values of a member: the span of the axis
                out += [{"name": name(s, "Hi"), "formula": f"MAX({at(a)}, {at(z)})"},
                        {"name": name(s, "Lo"), "formula": f"MIN({at(a)}, {at(z)})"},
                        {"name": label_calc(s), "formula": _label_formula(s),
                         "compute_using": [d, _flag(s)[0]]}]
        elif k == WAFFLE:
            m, part, c = s["measure"]["field"], s["part"], s["cells"]
            cond = " OR ".join(f"[{part['field']}] = {_q(types, part['field'], v)}" for v in part["values"])
            out += [{"name": name(s, "Share"),
                     "formula": f"{{FIXED : SUM(IIF({cond}, [{m}], 0))}} / {{FIXED : SUM([{m}])}}"},
                    {"name": name(s, "Filled"), "formula": f"[{c}] <= ROUND([{name(s, 'Share')}] * {SIDE * SIDE})"},
                    {"name": name(s, "Row"), "formula": f"-{UNIT} * INT(([{c}] - 1) / {SIDE}) - {UNIT // 2}"},  # top
                    {"name": name(s, "Column"),
                     "formula": f"{UNIT} * ([{c}] - 1 - {SIDE} * INT(([{c}] - 1) / {SIDE})) + {UNIT // 2}"},
                    {"name": name(s, "Square"), "formula": f"STR([{c}])"},  # a mark per id
                    {"name": name(s, "Cell"), "formula": f"[{c}] >= 1 AND [{c}] <= {SIDE * SIDE}"}]
            if s.get("value"):  # one value for the title: the same on every mark
                out.append({"name": name(s, "Value"), "formula": f"MIN([{name(s, 'Share')}])", "format": "pct0"})
    return out


def _label_formula(s):
    """The label's position: its value, raised to GAP over each member ranked under it (a tie: the one before it
    along the member counts as under)."""
    m = s["measure"]
    v = f"{m.get('agg', 'sum').upper()}([{m['field']}])"
    r = f"RANK({v}, 'asc')"
    gap = f"{LABEL_GAP} * (WINDOW_MAX(MAX([{name(s, 'Hi')}])) - MIN(WINDOW_MIN(MIN([{name(s, 'Lo')}])), 0))"
    out = v
    for k in reversed([k for k in range(-(SPREAD_MAX - 1), SPREAD_MAX) if k]):
        under, steps = ("<=", f"MAX({r} - LOOKUP({r}, {k}), 1)") if k < 0 else ("<", f"({r} - LOOKUP({r}, {k}))")
        term = f"IFNULL(IIF(LOOKUP({r}, {k}) {under} {r}, LOOKUP({v}, {k}) + {steps} * {gap}, {v}), {v})"
        out = f"MAX({term}, {out})"
    return out


def label_positions(vals, span):
    """period | member -> the label's position, as _label_formula: vals {period | member: value} (the members in
    the addressing order: sorted), span: the axis's (the largest of both ends less zero or the smallest)."""
    gap, out = LABEL_GAP * span, {}
    for period in sorted({k.split(" | ")[0] for k in vals}):
        ks = sorted(k for k in vals if k.split(" | ")[0] == period and vals[k] is not None)
        vs = [vals[k] for k in ks]
        rank = [1 + sum(w < v for w in vs) for v in vs]
        for i, k in enumerate(ks):
            p = vs[i]
            for j in range(len(ks)):
                if j < i and rank[j] <= rank[i]:
                    p = max(p, vs[j] + max(rank[i] - rank[j], 1) * gap)
                elif j > i and rank[j] < rank[i]:
                    p = max(p, vs[j] + (rank[i] - rank[j]) * gap)
            out[k] = p
    return out


def label_record(name_):
    return f"{name_} · Labels"


def value_record(name_):
    return f"{name_} · Value"


def _flag(s):
    if kind(s) == WAFFLE:
        return name(s, "Filled"), [("true", COLOR["accent"]), ("false", EMPTY)]
    if (s.get("color") or {}).get("highlight"):
        return name(s, "Highlight"), [("true", COLOR["accent"]), ("false", COLOR["mark_muted"])]
    return name(s, "Good"), [("true", COLOR["good"]), ("false", COLOR["bad"])]


def palettes(b):
    """The flag on Color: accent / muted, good / bad, filled / empty (build._palettes)."""
    out = {}
    for s in b.worksheets:
        if kind(s) in (SLOPE, WAFFLE):
            calc, colors = _flag(s)
            col = b.calc_cols[calc].name
            out[f"[none:{col}:nk]"] = (col, "None", colors)
    return out


def roles(s):
    """design.COLOR keys the sheet draws (the subtitle's colored words)."""
    if kind(s) == SLOPE:
        return {"accent"} if (s.get("color") or {}).get("highlight") else {"good", "bad"}
    return {"accent"} if kind(s) == WAFFLE else set()


def shape(b, s):
    """-> fields, rows, cols, encodings, labels, measure names (build.sheet_shape)."""
    k = kind(s)
    if k == SLOPE:
        p, m, d = b._dim(s["period"]), b._measure(s["measure"]), b._dim(s["dimension"])
        f = b._dim(_flag(s)[0])
        enc = [("color", b.q(f.name)), ("lod", b.q(d.name)), ("text", b.q(d.name)), ("text", b.q(m.name))]
        extra = [b._measure({"field": label_calc(s)})] if spread(s) else []  # the labels' layer (layers)
        return [p, m, d, f] + extra, m.name, p.name, enc, False, None
    if k == BOX:
        d, m, det = b._dim(s["dimension"]), b._measure(s["measure"]), b._dim(s["detail"])
        return [d, m, det], d.name, m.name, [("lod", b.q(det.name))], False, None
    r, c = (b._measure({"field": name(s, x), "agg": "min"}) for x in ("Row", "Column"))
    sq, f = b._dim(name(s, "Square")), b._dim(name(s, "Filled"))
    fields, enc = [r, c, sq, f], [("color", b.q(f.name)), ("lod", b.q(sq.name))]
    if s.get("value"):
        v = b._measure({"field": name(s, "Value")})
        fields.append(v)
        enc.append(("lod", b.q(v.name)))
    return fields, r.name, c.name, enc, False, None


def _rule(el, element, before=()):
    from .colors import _rule
    return _rule(el, element, before=before)


def style(b, style_el, s, fields):
    """No field labels over the headers; a waffle without headers; the box's look (Higher Education)."""
    k = kind(s)
    if not k and not facet(s):
        return
    if facet(s) or k in (SLOPE, BOX):
        for scope in ("rows",) if k == BOX else ("cols",):
            ws = _rule(style_el, "worksheet", before=("gridline", "zeroline", "table-div"))
            if ws.find(f"format[@attr='display-field-labels'][@scope='{scope}']") is None:
                ET.SubElement(ws, "format", attr="display-field-labels", scope=scope, value="false")
    if k == WAFFLE:  # fixed ranges of the grid (sized from the zone by fit), the axes hidden (as in the reference)
        axis = _rule(style_el, "axis", before=("cell", "header", "label", "mark", "pane", "table", "worksheet",
                                               "gridline", "zeroline", "table-div"))
        encs = []
        grid = ((fields[1], "cols", 0, SIDE * UNIT), (fields[0], "rows", -SIDE * UNIT, 0))
        for i, (f, scope, lo, hi) in enumerate(grid):
            encs.append(ET.Element("encoding", {"attr": "space", "class": "0", "field": b.q(f.name),
                                                "field-type": "quantitative", "max": str(hi), "min": str(lo),
                                                "range-type": "fixed", "scope": scope, "type": "space"}))
            axis.insert(i, encs[-1])
            ET.SubElement(axis, "format", {"attr": "display", "class": "0", "field": b.q(f.name), "scope": scope,
                                           "value": "false"})
        b.waffles[s["name"]] = {"axes": encs}
    elif k == BOX:
        rule = _rule(style_el, "refboxplot", before=("gridline", "zeroline", "table-div"))
        for attr, value in (("fill-color", "#f0f0f0d9"), ("whisker-end", "large"),
                            ("whisker-stroke-color", COLOR["muted"]), ("whisker-stroke-size", "1"),
                            ("stroke-color", COLOR["muted"])):
            ET.SubElement(rule, "format", attr=attr, id="refline1", value=value)


def pane(b, pane_el, s, fields):
    """The box: a per-cell box plot on the measure's axis (Higher Education 'Box Plot - Time')."""
    if kind(s) != BOX:
        return
    m = b.q(fields[1].name)
    ET.SubElement(pane_el, "reference-line", {
        "axis-column": m, "boxplot-mark-exclusion": "false" if s.get("points") else "true",
        "boxplot-whisker-type": "standard", "enable-instant-analytics": "true", "formula": "average", "id": "refline1",
        "label-type": "none", "probability": "95", "scope": "per-cell", "symmetric": "false", "value-column": m,
        "z-order": "1"})


def mark(pane_el, s):
    """After the <mark>: no scaling, the size its own (the reference's waffle, Higher Education's box dots)."""
    if kind(s) in (BOX, WAFFLE):
        ET.SubElement(pane_el, "mark-sizing", {"mark-sizing-setting": "marks-scaling-off"})


def pane_style(b, pane_el, s):
    """slope: labels at both line ends, a dot on each; box: small muted dots; waffle: white lines between squares."""
    k = kind(s)
    if not k:
        return
    st = pane_el.find("style")
    if st is None:
        st = ET.SubElement(pane_el, "style")
    rule = st.find("style-rule[@element='mark']")
    if rule is None:
        rule = ET.SubElement(st, "style-rule", element="mark")
    formats = {SLOPE: [("mark-labels-show", "true"), ("mark-labels-mode", "line-ends"),
                       ("mark-labels-line-first", "true"), ("mark-labels-line-last", "true"),
                       ("mark-labels-cull", "false" if spread(s) else "true"), ("mark-markers-mode", "all")],
               BOX: [("size", "0.4"), ("mark-color", COLOR["muted"]), ("mark-transparency", "160")],
               WAFFLE: [("size", _square_size(CELL_PX)), ("has-stroke", "true"),
                        ("stroke-color", COLOR["card_bg"])]}[k]
    for attr, value in formats:
        el = ET.SubElement(rule, "format", attr=attr, value=value)
        if k == WAFFLE and attr == "size":  # sized by fit from the zone
            b.waffles[s["name"]]["size"] = el


def _square_size(cell_px):
    return f"{cell_px * SQUARE_FILL / SQUARE_PX_PER_SIZE:.3f}"


def value_px():
    """The title's line over the grid: the share at the KPI value's size."""
    from .design import FONT, line_px
    return line_px(FONT["kpi_value"])


def shows_title(s):
    """A waffle with its value shows its sheet title (the %) in its zone."""
    return kind(s) == WAFFLE and bool(s.get("value"))


def title(b, ws, s):
    """The share as a big % in the sheet's title: a reference to the Value aggregate on Detail."""
    if not shows_title(s):
        return
    from .design import FONT
    lo = ws.find("layout-options")
    if lo is None:
        lo = ET.SubElement(ws, "layout-options")
    ft = lo.find("title/formatted-text")
    if ft is None:
        ft = ET.SubElement(ET.SubElement(lo, "title"), "formatted-text")
    else:  # after the sheet's own title (a dashboard without block headers)
        ET.SubElement(ft, "run").text = "  "
    run = ET.SubElement(ft, "run", bold="true", fontcolor=COLOR["accent"], fontsize=str(FONT["kpi_value"]))
    run.text = f"<{b.q(b._measure({'field': name(s, 'Value')}).name)}>"  # on Detail (shape)


def fit(b, p, w_px, h_px):
    """A waffle from its dashboard zone, w_px x h_px inside the zone's margins: the grid a square of GRID_FILL of the
    shorter side (under the value's title), at the top left; the axes' ranges keep its cells square, the square
    SQUARE_FILL of its cell. On several dashboards the smallest zone sizes it."""
    if kind(p) != WAFFLE:
        return
    h = h_px - (value_px() if p.get("value") else 0)
    side = min(w_px, h) * GRID_FILL
    if side < SIDE * 6:
        raise ValueError(f"Waffle '{p['name']}': its zone leaves {w_px}x{h_px}px, a grid of {int(side)}px; 10 squares "
                         f"need {SIDE * 6}px: give the cell more width or height")
    if side >= b.waffle_px.get(p["name"], side + 1):
        return
    b.waffle_px[p["name"]] = side
    x, y = b.waffles[p["name"]]["axes"]
    x.set("max", str(round(SIDE * UNIT * w_px / side)))
    y.set("min", str(-round(SIDE * UNIT * h / side)))
    b.waffles[p["name"]]["size"].set("value", _square_size(side / SIDE))


def layers(b, table, s, fields):
    """labels spread: '(measure + label position)' on Rows, the second axis folded and hidden; the line's layer
    without labels, the labels' layer an invisible line at the positions (dualaxis.table's panes)."""
    if not spread(s):
        return
    a, lab = b.q(fields[1].name), b.q(fields[-1].name)
    table.find("rows").text = f"({a} + {lab})"
    axis = _rule(table.find("style"), "axis", before=("cell", "header", "label", "mark", "pane", "table", "worksheet",
                                                      "gridline", "zeroline", "table-div"))
    axis.insert(0, ET.Element("encoding", {"attr": "space", "class": "0", "field": lab, "field-type": "quantitative",
                                           "fold": "true", "scope": "rows", "synchronized": "true", "type": "space"}))
    ET.SubElement(axis, "format", {"attr": "display", "class": "0", "field": lab, "scope": "rows", "value": "false"})
    panes = table.find("panes")
    default = panes.find("pane")
    line, text = copy.deepcopy(default), copy.deepcopy(default)
    for el in [el for el in default if el.tag not in ("view", "mark", "encodings")]:
        default.remove(el)
    for el in default.findall("encodings/text"):  # the layers' shared encodings stay (Desktop re-save)
        default.find("encodings").remove(el)
    for i, (pane, ref) in enumerate(((line, a), (text, lab)), 1):
        sel = pane.get("selection-relaxation-option")
        pane.attrib.clear()
        pane.attrib.update({"id": str(i), "selection-relaxation-option": sel, "y-axis-name": ref})
        panes.append(pane)
    enc = line.find("encodings")
    for el in enc.findall("text"):
        enc.remove(el)
    rule = line.find("style/style-rule[@element='mark']")
    for el in [el for el in rule if el.get("attr", "").startswith("mark-labels")]:
        rule.remove(el)
    label = ET.Element("customized-label")  # one line, 'member value': GAP holds one line (two overlapped, snapshot)
    ft = ET.SubElement(label, "formatted-text")
    for i, ref in enumerate(e.get("column") for e in text.findall("encodings/text")):  # a run of a lone space
        ET.SubElement(ft, "run").text = f"{' ' if i else ''}<{ref}>"  # Desktop drops (re-save): with the value
    text.insert(list(text).index(text.find("style")), label)  # before its style, as Desktop writes it
    rule = text.find("style/style-rule[@element='mark']")
    for el in [el for el in rule if el.get("attr") == "mark-markers-mode"]:
        rule.remove(el)
    ET.SubElement(rule, "format", attr="mark-transparency", value="0")  # the line hidden, its labels shown


# ---- small multiples ----------------------------------------------------------------------------------------------

def facet(s):
    return s.get("facet") if s["type"] in ("line", "bar", "area") else None


def facet_field(b, s, fields):
    """The facet's dimension, last among the sheet's fields."""
    if facet(s):
        fields.append(b._dim(s["facet"]["field"]))


def shelves(b, s, fields, rows_el, cols_el):
    """(facet * date), (facet * measure) or (facet / dimension) on Columns: a panel per member, its name as the header over it."""
    if facet(s):
        f = next(x for x in fields if getattr(x.col, "name", None) == s["facet"]["field"]
                 or getattr(x.col, "caption", None) == s["facet"]["field"])
        op = "*" if cols_el.text.endswith(":qk]") else "/"  # Desktop saves a crossing with an axis as '*' (as strip)
        cols_el.text = f"({b.q(f.name)} {op} {cols_el.text})" if cols_el.text else b.q(f.name)


def expected(s, rows, dim, value, grouped):
    """slope: period | member -> measure; box: member | id -> measure; waffle: filled squares -> {filled, share}."""
    k = kind(s)
    if k == SLOPE:
        return grouped(rows, [dim(s["period"]), dim(s["dimension"])], value(s["measure"]))
    if k == BOX:
        return grouped(rows, [dim(s["dimension"]), dim(s["detail"])], value(s["measure"]))
    m, part = s["measure"]["field"], s["part"]
    num = lambda v: float(v) if v not in (None, "") else 0.0  # noqa: E731
    total = sum(num(r[m]) for r in rows)
    share = sum(num(r[m]) for r in rows if r[part["field"]] in part["values"]) / total if total else None
    return {"share": share, "filled": None if share is None else int(_round(share * SIDE * SIDE))}


def box_record(name):
    return f"{name} · Box"


def box_stats(s, rows, dim, value, grouped):
    """member -> {q1, median, q3}: the quartiles Tableau's box draws over the member's dots (linear interpolation,
    as PERCENTILE; polish-26)."""
    by = {}
    for key, v in grouped(rows, [dim(s["dimension"]), dim(s["detail"])], value(s["measure"])).items():
        if v is not None:
            by.setdefault(key.split(" | ")[0], []).append(v)
    return {m: {"q1": percentile(vs, 0.25), "median": percentile(vs, 0.5), "q3": percentile(vs, 0.75)}
            for m, vs in by.items()}


def percentile(values, p):
    """Tableau's PERCENTILE / MEDIAN: linear between the closest ranks."""
    vs = sorted(values)
    if not vs:
        return None
    i = (len(vs) - 1) * p
    lo = int(i)
    return vs[lo] + (vs[min(lo + 1, len(vs) - 1)] - vs[lo]) * (i - lo)


def _round(x):
    """Tableau's ROUND: half away from zero."""
    import math
    return math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)
