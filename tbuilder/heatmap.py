"""Heatmap v2 (todo 8.6, decisions/041): a continuous color scale from the design tokens and marginal totals.

Spec:
- color {scale: sequential | diverging, palette?, good?, steps?, min?, max?, center?} on a heatmap (and on a bar,
  colored by its own measure). sequential: scale_low -> accent; diverging: bad <- scale_mid -> good around center
  (good: down swaps the ends). steps: stepped color (num-steps); min / max: a fixed range instead of the data's;
  center: the value at the neutral middle, required for diverging (lint C11).
- margins {rows: bar, cols: bar} on a heatmap: the total of each row as a bar at the right, of each column as a bar
  above it (ER Operation: weekday totals above the 'hour x weekday' heatmap, hour totals at its right), with the
  average line of decisions/028. A total is the measure aggregated over the row's (column's) data rows, as
  Tableau's grand totals (decisions/036): the margin is a bar sheet of its own over the same dimension.

XML (forms from the reference books, not guessed):
- the scale: worksheet style-rule 'mark' <encoding attr='color' field=<measure> type='custom-interpolated'
  [center max min num-steps]> <color-palette custom='true' name='' type='ordered-sequential|ordered-diverging'>
  with 11 / 13 colors (ER heatmap, BonusProject, Customer Support, Demo wealth and banking, European Superstore).
- the alignment of the margins: fixed cell sizes in px (style-rule 'cell' height / width by the row / column
  field, 121 + 5 sheets in the references), the heatmap's row header width ('header' width) and column header
  height ('header' height, BonusProject heatmap), the margin's own header hidden ('label' display false, ER), its
  axis hidden ('axis' display false). The zones are offset by the header the other sheet does not have, the gaps
  are empty zones (a tiled layout-basic is covered). The heatmap and its margins fill their zones (Entire View,
  decisions/068): the cells of both stretch alike, so they stay lined up.

Two row fields and outlier labels (decisions/171, the logistics mock's 'when' heatmap):
- rows [outer, inner]: nested on Rows (outer / inner) as a table's (decisions/045), each header as wide as its
  longest value, the outer one bold (style-rule 'label' font-weight by the field: Bar Chart Menu's Region). The
  outer member shows once over its inner rows, as Desktop draws nested dimensions.
- the groups apart (decisions/186): style-rule 'table-div' scope rows, div-level 1, a 5px line of the card's color
  between the members of the outer field (Desktop's form: golden_bullet_2025_1's Regions, as reflines' bullet).
- margins with them (decisions/186): the row totals nest (outer / inner) as the heatmap, one bar per inner row, their
  headers hidden, the fixed height on the inner field and the same group gap, so the bars stay level with the cells.
- label {min}: a hidden calc '<sheet> · Label' = IF <measure> >= min THEN <measure> END on Text instead of the
  measure (annotate's form); a cell below min shows its color alone.
"""
import math
import xml.etree.ElementTree as ET

from . import fit
from .design import (COLOR, HEADER_TEXT_PAD_PX, HEATMAP_CELL_MIN_PX, HEATMAP_HEADER_PX, MARGIN_BAR_PX, SCALE_DIV_SIDE,
                     SCALE_SEQ_COLORS, SPACE, field_label_px, row_header_fit_px)

SCALES = {"sequential": "accent", "diverging": "good_bad"}  # scale -> its palette (the default and the only one)
MARGIN_SUFFIX = {"rows": "Row Totals", "cols": "Column Totals"}
HEAT_HEAD_PAD_PX = 4  # a column header's text + this stays whole (37px for '2010' at 8pt: whole; 31px: '20..')
GROUP_GAP_PX = 5  # between the outer groups of two row fields, as the bullet's rows (reflines.BULLET_GAP_PX)


# ---- the scale ---------------------------------------------------------------------------------------------------
def scale(s):
    """The color scale spec of a heatmap or a bar, or None."""
    c = s.get("color")
    return c if isinstance(c, dict) and "scale" in c else None


def check(spec):
    """Spec checks of the scales and the margins (the schema checks the shapes)."""
    for s in spec["sheets"]:
        where = f"Sheet '{s['name']}'"
        c = scale(s)
        if c is not None:
            kind = c["scale"]
            if c.get("palette", SCALES[kind]) != SCALES[kind]:
                raise ValueError(f"{where}: a {kind} scale takes palette '{SCALES[kind]}', not '{c['palette']}'")
            if kind == "sequential" and ("center" in c or "good" in c):
                raise ValueError(f"{where}: 'center' and 'good' belong to a diverging scale")
            if kind == "diverging" and "center" not in c:
                raise ValueError(f"{where}: a diverging scale needs 'center' (the value at the neutral middle, "
                                 f"e.g. 0 for a change); without it Tableau puts the middle at the data's midpoint")
            lo, hi = c.get("min"), c.get("max")
            if lo is not None and hi is not None and lo >= hi:
                raise ValueError(f"{where}: color scale min {lo} is not below max {hi}")
            ctr = c.get("center")
            if ctr is not None and ((lo is not None and ctr <= lo) or (hi is not None and ctr >= hi)):
                raise ValueError(f"{where}: color scale center {ctr} is outside min..max ({lo}..{hi})")
            if s["type"] == "bar" and "plan" in s:
                raise ValueError(f"{where}: plan colors the bars itself: no color scale with it")
        if s["type"] == "heatmap":
            _check_rows(s, where)
        if margins(s) and "table_calc" in s["measure"]:
            raise ValueError(f"{where}: marginal totals of a table calculation are not supported (Tableau would "
                             f"compute the table calc over the totals)")


def _check_rows(s, where):
    from .tables import rows
    rs = rows(s)
    if len(rs) == 2 and (len(set(rs)) != 2 or s["cols"] in rs):  # one row field: dates.check_heat says it better
        raise ValueError(f"{where}: rows {rs} and cols '{s['cols']}' must be different fields")
    if "label" in s and "table_calc" in s["measure"]:
        raise ValueError(f"{where}: label min of a table calculation is not supported")


# ---- outlier labels (decisions/171) ------------------------------------------------------------------------------
def label_name(s):
    return f"{s['name']} · Label"


def calcs(spec):
    """The label calc of each heatmap with label {min}: the measure where it is >= min, else Null (no text)."""
    from .annotate import _is_agg
    defs = {c["name"]: c for c in spec.get("calcs", [])}
    out = []
    for s in spec["sheets"]:
        if s["type"] != "heatmap" or "label" not in s:
            continue
        m, c = s["measure"], defs.get(s["measure"]["field"])
        expr = (f"[{m['field']}]" if c and _is_agg(c["formula"])
                else f"{m.get('agg', 'sum').upper()}([{m['field']}])")
        fmt = m.get("format") or (c or {}).get("format")  # the label reads as the cell's number
        out.append({"name": label_name(s), "formula": f"IF {expr} >= {s['label']['min']} THEN {expr} END",
                    **({"format": fmt} if fmt else {})})
    return out


def text_field(b, s, fields, m):
    """The field on Text: the label calc (added to the fields) with label {min}, else the measure."""
    if "label" not in s:
        return m
    t = b._measure({"field": label_name(s)})
    fields.append(t)
    return t


def _mix(a, b, k):
    a, b = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (a, b))
    return "#" + "".join(f"{round(x + (y - x) * k):02x}" for x, y in zip(a, b))


def palette(c):
    """(palette type, [colors low -> high]) of a scale spec, all from design.COLOR."""
    if c["scale"] == "sequential":
        n = SCALE_SEQ_COLORS
        return "ordered-sequential", [_mix(COLOR["scale_low"], COLOR["accent"], k / (n - 1)) for k in range(n)]
    low, high = (COLOR["bad"], COLOR["good"]) if c.get("good", "up") == "up" else (COLOR["good"], COLOR["bad"])
    n = SCALE_DIV_SIDE
    side = [_mix(low, COLOR["scale_mid"], k / n) for k in range(n)]
    return "ordered-diverging", side + [COLOR["scale_mid"]] + [_mix(COLOR["scale_mid"], high, (k + 1) / n)
                                                               for k in range(n)]


def _num(v):
    """A range value as Desktop writes it ('0.0', '-1.0': Customer Support, European Superstore)."""
    return repr(float(v))


def style(b, style_el, s, fields):
    """The scale in the worksheet's 'mark' rule: the measure on Color, a custom interpolated palette (a map writes
    its own: maps.table)."""
    c = scale(s)
    if c is None or s["type"] == "map":
        return
    encoding(style_el, c, b.q(fields[1].name if s["type"] == "bar" else fields[2].name), *palette(c))


def encoding(style_el, c, field, kind, colors):
    """<encoding attr='color' ... type='custom-interpolated'> of the field with the palette, in the 'mark' rule."""
    from .colors import _rule
    rule = _rule(style_el, "mark", before=("pane", "worksheet", "refline", "gridline", "zeroline", "table-div"))
    attrs = {"attr": "color"}
    if "center" in c:
        attrs["center"] = _num(c["center"])
    attrs["field"] = field
    for k in ("max", "min"):
        if k in c:
            attrs[k] = _num(c[k])
    if "steps" in c:
        attrs["num-steps"] = str(c["steps"])
    attrs["type"] = "custom-interpolated"
    enc = ET.SubElement(rule, "encoding", attrs)
    pal = ET.SubElement(enc, "color-palette", custom="true", name="", type=kind)
    for color in colors:
        ET.SubElement(pal, "color").text = color


def ranged(spec):
    """A sheet whose scale has a fixed range or a center: the gate checks it against the expected numbers."""
    return any((c := scale(s)) and any(k in c for k in ("min", "max", "center")) for s in spec["sheets"])


# ---- marginal totals ---------------------------------------------------------------------------------------------
def margins(s):
    """{'rows': 'bar', 'cols': 'bar'} (either) of a heatmap, else {}."""
    return s.get("margins", {}) if s["type"] == "heatmap" else {}


def part_name(s, side):
    return f"{s['name']} · {MARGIN_SUFFIX[side]}"


def parts(s):
    """The physical sheets of a heatmap: itself, then a bar sheet per margin (the builder and expected.py draw and
    compute them as bars with an average line)."""
    from .tables import rows
    out = [s]
    for side in ("rows", "cols"):
        if side in margins(s):
            p = {"name": part_name(s, side), "type": "bar", "dimension": rows(s)[0] if side == "rows" else s[side],
                 "measure": s["measure"], "orientation": "horizontal" if side == "rows" else "vertical",
                 "reference": {"type": "avg"}, "margin": side, "heatmap": s}
            if side == "rows" and len(rows(s)) == 2:
                p["inner"] = rows(s)[1]
            out.append(p)
    return out


def is_margin(s):
    return "margin" in s


def margin_inner(b, s, fields):
    """The row totals of a heatmap with two row fields: the inner field among the bar's fields (decisions/186)."""
    if "inner" in s:
        fields.append(b._dim(s["inner"]))


def margin_shelf(b, s, fields, rows_el):
    """(outer / inner) on the Rows of those row totals, as the heatmap's."""
    if "inner" in s:
        rows_el.text = f"({b.q(fields[0].name)} / {b.q(fields[-1].name)})"


def _group_gaps(style_el):
    """The groups of the outer row field apart (decisions/186): a line of the card's color between them."""
    from .colors import _rule
    div = _rule(style_el, "table-div", before=())
    for f in div.findall("format[@scope='rows']"):
        div.remove(f)
    for attr, value in (("line-visibility", "on"), ("stroke-size", str(GROUP_GAP_PX)),
                        ("stroke-color", COLOR["card_bg"]), ("line-pattern-only", "solid"), ("div-level", "1")):
        ET.SubElement(div, "format", attr=attr, scope="rows", value=value)


def sheet_style(b, style_el, s, fields):
    """Static rules of a heatmap and of its margin sheets: without margins its row header width, with them the
    labels; the cell sizes come with the layout (cell)."""
    from .colors import _rule
    if is_margin(s):
        b.heat_styles[s["name"]] = (style_el, fields)
        side = s["margin"]
        axis = _rule(style_el, "axis", before=())
        axis.insert(0, ET.Element("format", {"attr": "display", "class": "0", "field": b.q(fields[1].name),
                                             "scope": "cols" if side == "rows" else "rows", "value": "false"}))
        if side == "rows":  # the heatmap's row headers name the rows
            _label(style_el, b.q(fields[0].name))
            if "inner" in s:
                _label(style_el, b.q(fields[-1].name))
                _group_gaps(style_el)
        _field_labels_off(style_el)
        return
    if s["type"] != "heatmap":
        return
    if len(row_fields(s, fields)) == 2:  # the outer member bold, once over its inner rows (decisions/171)
        _bold(style_el, b.q(fields[0].name))
        _group_gaps(style_el)
    if not margins(s):  # the row headers as wide as their text and the field label over them (decisions/066)
        b.heat_columns.append((style_el, s, fields))  # column widths from the numbers: column_widths
        for f in reversed(row_fields(s, fields)):  # the outer width first, as the registry writes them
            _header_size(style_el, b.q(f.name), "width", row_header_w(b, s, fields, f=f))
        return
    b.heat_styles[s["name"]] = (style_el, fields)
    if "cols" in margins(s):  # the column margin above shows the column names
        _label(style_el, b.q(fields[1].name))
    _field_labels_off(style_el)  # a field label row would push the cells off the margins' rows


def column_widths(b):
    """A heatmap without margins: its columns as wide as their header when it is wider than the numbers, or Desktop
    sizes them by the numbers and cuts 'Furnit..' (as a text table's, decisions/066, 094). Run after every sheet is
    built: the numbers are the expected ones, and computing them earlier changes which sheet error comes first; before
    the windows, whose fit reads the width."""
    from .ink import table_cell
    for style_el, s, fields in b.heat_columns:
        with b._source_of(s["name"]):  # its source's fields (decisions/083)
            cw = table_cell(b, s, fields)
            if cw:
                _cell_size(style_el, b.q(fields[1].name), "width", cw)


def fit_zone(b, s, zone_w, zone_h):
    """A heatmap without margins in its zone: Desktop fits the columns to the zone's width, and a column narrower than
    its header cuts it ('20..' at 31px, roadmap26; whole at 37px, srb_renewables). When the row headers and the
    columns' headers do not fit side by side, the row headers give way first, down to their longest word, the names
    wrapping onto lines the rows still hold; else the build fails naming the sheet (decisions/144). A heatmap needing
    more than fit.NARROW_FAR x its zone scrolls on purpose (a public book's 48 months), as fit's 'narrow' leaves it."""
    from .design import LINE_HEIGHT, text_px
    if s["type"] != "heatmap" or margins(s):
        return
    style_el, _, fields = next(e for e in b.heat_columns if e[1] is s)
    widths = [style_el.find(f"style-rule[@element='header']/format[@attr='width'][@field='{b.q(f.name)}']")
              for f in row_fields(s, fields)]
    head = widths[0]
    from . import dates
    level = dates.heat_level(s)
    cols = set(dates.period_labels(level, [r[s["cols"]] for r in b.prof.rows]) if level
               else b.fields.labels(fields[1].col))
    pt = b.font["table_header"]
    need = len(cols) * (max(text_px(v, pt) for v in cols) + HEAT_HEAD_PAD_PX)
    row_w, labels = sum(int(h.get("value")) for h in widths), b.fields.labels(fields[0].col)
    if row_w + need <= zone_w or row_w + need > zone_w * fit.NARROW_FAR:  # far wider: a table that scrolls on purpose
        return
    if len(widths) == 2:  # two row fields keep their widths: a wrapped outer name would not read as one group
        raise ValueError(f"Sheet '{s['name']}': its {len(cols)} columns need {need}px for their headers beside "
                         f"{row_w}px of two row headers, the cell leaves {zone_w}px (Desktop would cut them to '..'); "
                         f"give the cell more width")
    from .colors import repeats
    floor = max(text_px(w, pt) for v in labels for w in v.split()) + HEADER_TEXT_PAD_PX  # the longest word
    if "rows" not in repeats(b, s, fields)[1]:  # the field label over the headers stays whole (decisions/073)
        floor = max(floor, field_label_px(b.shown(fields[0].col)))
    new = zone_w - need
    lines = max(-(-(text_px(v, pt) + HEADER_TEXT_PAD_PX) // max(new, 1)) for v in labels)
    if new >= floor and len(labels) * lines * pt * 4 / 3 * LINE_HEIGHT + HEATMAP_HEADER_PX <= zone_h:
        head.set("value", str(int(new)))
        return
    raise ValueError(f"Sheet '{s['name']}': its {len(cols)} columns need {need}px for their headers beside {row_w}px "
                     f"of row headers, the cell leaves {zone_w}px (Desktop would cut them to '..'); give the cell more "
                     f"width or the rows more height (the row names wrap)")


def row_fields(s, fields):
    """The row fields of a heatmap's fields: [outer] or [outer, inner] (fields[3], decisions/171)."""
    from .tables import rows
    return [fields[0], fields[3]] if len(rows(s)) == 2 else [fields[0]]


def row_header_w(b, s, fields, label=True, f=None):
    """px of a heatmap's row headers (of the row field f, the outer by default): the longest row value whole and,
    when it shows, the field label over them (Desktop sized them itself and cut 'Accessor..', 'Sub-Cate..': a public book,
    decisions/066); the outer of two in bold."""
    from .colors import repeats
    f = f or fields[0]
    labels = b.fields.labels(f.col)
    px = row_header_fit_px(labels, "")
    if f is fields[0] and len(row_fields(s, fields)) == 2:
        from .design import FONT, text_px
        px = max(px, max(text_px(v, FONT["table_header"], bold=True) for v in labels) + HEADER_TEXT_PAD_PX)
    if label and "rows" not in repeats(b, s, fields)[1]:
        px = max(px, field_label_px(b.shown(f.col)))  # the field label Desktop shows (decisions/073)
    return px


def _bold(style_el, ref):
    """The header of a row field in bold: style-rule 'label' font-weight by the field (Bar Chart Menu: Region)."""
    from .colors import _rule
    rule = _rule(style_el, "label", before=("mark", "pane", "worksheet", "refline", "gridline", "zeroline",
                                            "table-div"))
    ET.SubElement(rule, "format", attr="font-weight", field=ref, value="bold")


def _label(style_el, ref):
    from .colors import _rule
    rule = _rule(style_el, "label", before=("mark", "pane", "worksheet", "refline", "gridline", "zeroline",
                                            "table-div"))
    ET.SubElement(rule, "format", attr="display", field=ref, value="false")


def _field_labels_off(style_el):
    from .colors import _rule
    rule = _rule(style_el, "worksheet", before=("refline", "gridline", "zeroline", "table-div"))
    for scope in ("cols", "rows"):
        if rule.find(f"format[@attr='display-field-labels'][@scope='{scope}']") is None:
            ET.SubElement(rule, "format", attr="display-field-labels", scope=scope, value="false")


def pane_style(pane, s):
    """A margin's bars: muted, labelled with the total (the heatmap keeps the color)."""
    if not is_margin(s):
        return
    rule = ET.SubElement(ET.SubElement(pane, "style"), "style-rule", element="mark")
    for attr, value in (("mark-labels-show", "true"), ("mark-labels-cull", "true"),
                        ("mark-color", COLOR["mark_muted"])):
        ET.SubElement(rule, "format", attr=attr, value=value)


def _cell_size(style_el, ref, attr, px):
    from .colors import _rule
    rule = _rule(style_el, "cell", before=("header", "label", "mark", "pane", "worksheet", "refline", "gridline",
                                           "zeroline", "table-div"))
    rule.insert(0, ET.Element("format", attr=attr, field=ref, value=str(px)))


def _header_size(style_el, ref, attr, px):
    from .colors import _rule
    rule = _rule(style_el, "header", before=("label", "mark", "pane", "worksheet", "refline", "gridline",
                                             "zeroline", "table-div"))
    rule.insert(0, ET.Element("format", attr=attr, field=ref, value=str(px)))


def cell(b, parent, s, box, size, head):
    """A heatmap with margins in its block: zones and the fixed cell sizes that line the margins up with the cells.

        [ empty: row headers ] [ column totals ] [ empty ]
        [ heatmap: row headers + cells          ] [ row totals ]

    Sizes in px: the row header W (longest row value), cell width / height filling the heatmap's zone, the
    margins MARGIN_BAR_PX long. The heatmap's cells start at its zone's margin + W (left) and + its column header
    (top, only without the column margin); each margin's zone is offset by the same amount."""
    from . import spacing
    x, y, w, h = box
    width, height = size
    m = margins(s)
    heat_style, heat_fields = b.heat_styles[s["name"]]
    rs, c = row_fields(s, heat_fields), heat_fields[1]
    count = fit.builder_counter(b)  # the Null member too: it is a row / column of its own (decisions/056, 068)
    from . import dates
    level = dates.heat_level(s)  # date columns: one per period, not per date in the data
    n_c = (len(set(dates.period_labels(level, [r[s["cols"]] for r in b.prof.rows]))) if level
           else count(None, [(f"[{c.col.name}]", "None")], [None]) or len(b.fields.labels(c.col)))
    n_r = (count(None, [(f"[{f.col.name}]", "None") for f in rs], [None] * len(rs))  # the existing outer + inner pairs
           or math.prod(len(b.fields.labels(f.col)) for f in rs))
    row_ws = [row_header_w(b, s, heat_fields, label=False, f=f) for f in rs]  # field labels off (_field_labels_off)
    row_w = sum(row_ws)
    col_h = 0 if "cols" in m else HEATMAP_HEADER_PX  # the heatmap's own column header (no column margin)
    inner = SPACE["zone_margin"]
    cell_box = (x, y, w, h)

    def ux(px):
        return round(px * 100000 / width)

    def uy(px):
        return round(px * 100000 / height)

    def margin_of(zb):
        return spacing.margins(zb, cell_box, b.block_headers, head, b._edge())

    right_w = ux(MARGIN_BAR_PX + inner + b._edge()) if "rows" in m else 0
    # the column margin: its bars and, under them, the column names (the heatmap's own header is hidden)
    top_h = uy(MARGIN_BAR_PX + HEATMAP_HEADER_PX + (0 if head else b._edge()) + inner) if "cols" in m else 0
    heat = (x, y + top_h, w - right_w, h - top_h)
    hm = margin_of(heat)
    content_w = heat[2] * width // 100000 - hm["left"] - hm["right"] - row_w
    content_h = heat[3] * height // 100000 - hm["top"] - hm["bottom"] - col_h
    cw, rh = content_w // n_c, content_h // n_r
    if min(cw, rh) < HEATMAP_CELL_MIN_PX:
        raise ValueError(f"Sheet '{s['name']}': heatmap cells of {cw}x{rh}px with its margins (min "
                         f"{HEATMAP_CELL_MIN_PX}px); give the block more room or drop a margin")
    r_ref, c_ref = b.q(rs[-1].name), b.q(c.name)  # a row's height is the inner field's (as the registry's)
    _cell_size(heat_style, c_ref, "width", cw)
    _cell_size(heat_style, r_ref, "height", rh)
    if col_h:
        _header_size(heat_style, c_ref, "height", col_h)
    for f, px in zip(reversed(rs), reversed(row_ws)):
        _header_size(heat_style, b.q(f.name), "width", px)
    zones = [(s["name"], heat, hm)]
    if "rows" in m:
        ry = heat[1] + uy(col_h)
        rbox = (x + w - right_w, ry, right_w, y + h - ry)
        rm = dict(margin_of(rbox), top=hm["top"])  # its first bar level with the first row of cells
        style_el, _ = b.heat_styles[part_name(s, "rows")]
        _cell_size(style_el, r_ref, "height", rh)
        zones.append((part_name(s, "rows"), rbox, rm))
        if ry > y:
            zones.append((None, (x + w - right_w, y, right_w, ry - y), None))
    if "cols" in m:
        left_w = ux(hm["left"] + row_w - inner)  # the column totals start where the cells do
        tbox = (x + left_w, y, w - right_w - left_w, top_h)
        style_el, _ = b.heat_styles[part_name(s, "cols")]
        _cell_size(style_el, c_ref, "width", cw)
        zones += [(part_name(s, "cols"), tbox, margin_of(tbox)), (None, (x, y, left_w, top_h), None)]
    for name, (zx, zy, zw, zh), zm in zones:
        if name is None:  # a gap of the tiled layout: an empty zone
            b._zone_style(ET.SubElement(parent, "zone", {"h": str(zh), "id": b._zid(), "type-v2": "empty",
                                                         "w": str(zw), "x": str(zx), "y": str(zy)}),
                          margin_of((zx, zy, zw, zh)))
            continue
        attrs = {"h": str(zh), "id": b._zid(), "name": name, "show-title": "false", "w": str(zw), "x": str(zx),
                 "y": str(zy)}
        b._zone_style(ET.SubElement(parent, "zone", attrs), zm)
