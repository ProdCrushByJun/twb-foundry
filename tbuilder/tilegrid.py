"""Tile grid (decisions/154): a square tile per member, colored by its measure, its code and value on it.

Spec: tilegrid {dimension, measure, label?, color?, layout, group?}:
- layout {row, col}: a tile map, each tile at the row / column two numeric columns of the data give it (1 at the top
  left), empty places left empty;
- layout {cols: N}: a wall, the members by the measure descending, N to a row; group: a block of N columns per
  member of group, side by side;
- color: the measure's scale (heatmap.scale, decisions/041), sequential by default; label: the tile's short name,
  default the member.

XML (forms from Desktop books):
- tile map: 'Line Chart Tile Map' (Row, Column integers as discrete dimensions on Rows / Columns, their headers
  hidden, no dividers). An integer as a discrete dimension here is a bin of size 1 ('[none:X (bin):ok]', the
  histogram's form of decisions/140): numbers sort as numbers, '10' after '9';
- wall: reference 'Countries' (Internet Access), rebuilt in out/wtc_tile_wall (decisions/145): COL = (INDEX()-1) % N,
  ROW = INT((INDEX()-1) / N) as discrete table calcs '[usr:...:ok]' along the member, Columns '(group / COL)', the
  order a computed-sort of the member by the measure DESC. The formula has no '%': (i - N * INT(i / N));
- the tile: a Square on the discrete cell (as a heatmap's), a white stroke between tiles (treemap, decisions/138),
  the label '<code>' bold over '<value>' in the middle.
"""
import xml.etree.ElementTree as ET

from . import formats, heatmap
from .design import COLOR, text_px

KIND = "tilegrid"
SEQUENTIAL = {"scale": "sequential"}
def stroke():
    return ("has-stroke", "true"), ("stroke-color", COLOR["card_bg"])


LABEL_PT = 9  # Tableau's mark label
LABEL_PAD_PX = 8  # the label's room inside the tile


def is_tilegrid(s):
    return s["type"] == KIND


def wall(s):
    return is_tilegrid(s) and "cols" in s["layout"]


def scale(s):
    return s.get("color") or SEQUENTIAL


def row_calc(s):
    return f"{s['name']} · Row"


def col_calc(s):
    return f"{s['name']} · Column"


def tiles_record(name):
    return f"{name} · Tiles"


def check(spec, prof):
    """A layout is {row, col} or {cols}; a tile map's places are numbers, one per member, one member per place."""
    for s in spec["sheets"]:
        if not is_tilegrid(s):
            continue
        where, lay = f"Sheet '{s['name']}'", s["layout"]
        if ("cols" in lay) == ("row" in lay or "col" in lay) or ("cols" not in lay and not {"row", "col"} <= set(lay)):
            raise ValueError(f"{where}: layout is {{row, col}} (a tile map) or {{cols}} (a wall), not {sorted(lay)}")
        if "group" in s and "cols" not in lay:
            raise ValueError(f"{where}: group splits a wall into blocks; a tile map's places come from the data")
        if "cols" in lay:
            continue
        for k in ("row", "col"):
            if prof.col(lay[k]).datatype != "integer":
                raise ValueError(f"{where}: layout {k} '{lay[k]}' must be an integer column (the tile's {k})")
        places, members = {}, {}
        for r in prof.rows:
            m, p = r[s["dimension"]], (r[lay["row"]], r[lay["col"]])
            if m in (None, "") or "" in p or None in p:
                continue
            if members.setdefault(m, p) != p:
                raise ValueError(f"{where}: '{m}' has two places ({members[m]} and {p}); one tile per member")
            if places.setdefault(p, m) != m:
                raise ValueError(f"{where}: '{places[p]}' and '{m}' share the place row {p[0]}, col {p[1]}")


def calcs(spec):
    """A wall's column and row of the tile: INDEX() along the member (and its label)."""
    out = []
    for s in spec["sheets"]:
        if not wall(s):
            continue
        n, i = s["layout"]["cols"], "(INDEX() - 1)"
        # the label is a dimension of the view too: along it as well, or each code is a partition (snapshot)
        along = [s["dimension"]] + ([s["label"]] if s.get("label", s["dimension"]) != s["dimension"] else [])
        out += [{"name": col_calc(s), "formula": f"{i} - {n} * INT({i} / {n})", "compute_using": along},
                {"name": row_calc(s), "formula": f"INT({i} / {n})", "compute_using": along}]
    return out


def bin_columns(spec, prof):
    """A tile map's row and column: bins of size 1 (discrete integers)."""
    from .distviz import BinColumn, bin_name
    return {bin_name(s["layout"][k]): BinColumn(s["layout"][k], 1)
            for s in spec["sheets"] if is_tilegrid(s) and not wall(s) for k in ("row", "col")}


def bin_sources(b):
    """The columns a tile map bins: Desktop declares them in the source (re-save adds them, as measures)."""
    return [b.prof.col(s["layout"][k]) for s in b.worksheets if is_tilegrid(s) and not wall(s) for k in ("row", "col")]


def _ok(f):
    """A discrete instance of a number: '[none:X (bin):ok]', '[usr:Calculation_...:ok]' (references)."""
    prefix = f.name[1:-1].rsplit(":", 1)[0]
    f.name, f.type = f"[{prefix}:ok]", "ordinal"
    return f


def shape(b, s):
    """-> fields, rows, cols, encodings, labels, measure names (build.sheet_shape): the row and column first, then
    the measure, the member, its label, a wall's group."""
    from .distviz import bin_name
    lay = s["layout"]
    if wall(s):
        r, c = (_ok(b._measure({"field": n(s)})) for n in (row_calc, col_calc))
    else:
        r, c = (_ok(b._dim(bin_name(lay[k]))) for k in ("row", "col"))
    m, d = b._measure(s["measure"]), b._dim(s["dimension"])
    fields = [r, c, m, d]
    lab = d
    if s.get("label", s["dimension"]) != s["dimension"]:
        lab = b._dim(s["label"])
        fields.append(lab)
    if wall(s) and "group" in s:
        fields.append(b._dim(s["group"]))
    enc = [("color", b.q(m.name)), ("lod", b.q(d.name)), ("text", b.q(lab.name)), ("text", b.q(m.name))]
    return fields, r.name, c.name, enc, True, None


def _group(b, s, fields):
    return next(f for f in fields if f.kind == "dim" and getattr(f.col, "name", None) == s["group"]) \
        if wall(s) and "group" in s else None


def sort(b, view, s, fields):
    """A wall: the members by the measure descending, the order INDEX() walks (the reference's computed-sort)."""
    if wall(s):
        ET.SubElement(view, "computed-sort", column=b.q(fields[3].name), direction="DESC", using=b.q(fields[2].name))


def shelves(b, s, fields, rows_el, cols_el):
    """A wall's blocks: (group / COL) on Columns."""
    g = _group(b, s, fields)
    if g is not None:
        cols_el.text = f"({b.q(g.name)} / {b.q(fields[1].name)})"


def style(b, style_el, s, fields):
    """The row and column headers hidden (a group's names stay), no field labels; the measure's color scale."""
    if not is_tilegrid(s):
        return
    from .colors import _rule
    lab = _rule(style_el, "label", before=("pane", "table", "worksheet", "gridline", "zeroline", "table-div"))
    for f in fields[:2]:
        ET.SubElement(lab, "format", attr="display", field=b.q(f.name), value="false")
    ws = _rule(style_el, "worksheet", before=("gridline", "zeroline", "table-div"))
    for scope in ("rows", "cols"):
        if ws.find(f"format[@attr='display-field-labels'][@scope='{scope}']") is None:
            ET.SubElement(ws, "format", attr="display-field-labels", scope=scope, value="false")
    c = scale(s)
    heatmap.encoding(style_el, c, b.q(fields[2].name), *heatmap.palette(c))


def pane(b, pane_el, s, fields):
    """The tooltip 'member: value' (not the row / column helpers) and the label: the code bold over the value."""
    if not is_tilegrid(s):
        return
    d, m = b.q(fields[3].name), b.q(fields[2].name)
    lab = next((t.get("column") for t in pane_el.iterfind("encodings/text")), d)
    if pane_el.find("customized-tooltip") is None:
        ft = ET.SubElement(ET.SubElement(pane_el, "customized-tooltip", {"show-buttons": "false"}), "formatted-text")
        ET.SubElement(ft, "run", bold="true").text = f"<{d}>"
        ET.SubElement(ft, "run").text = "Æ\n"
        ET.SubElement(ft, "run").text = f"<{m}>"
    ft = ET.SubElement(ET.SubElement(pane_el, "customized-label"), "formatted-text")
    ET.SubElement(ft, "run", bold="true").text = f"<{lab}>"
    value = [ET.SubElement(ft, "run"), ET.SubElement(ft, "run")]
    value[0].text, value[1].text = "Æ\n", f"<{m}>"
    b.tile_values[s["name"]] = (ft, value)


def fit(b, p, w_px):
    """The tile's width from its zone (w_px inside the margins over its columns): a value wider than the tile shows
    '###' (snapshot: $24.0K on 37px), so the label keeps the code alone, the value in the tooltip. A code wider than
    the tile: refused."""
    if not is_tilegrid(p) or p["name"] not in b.tile_values:
        return
    tiles = b.expected.get(tiles_record(p["name"])) or {}
    if not tiles:
        return
    tile_px = w_px / len({(t.get("group"), t["col"]) for t in tiles.values()})
    lab = p.get("label", p["dimension"])
    codes = {r[lab] for r in b.prof.rows if r[p["dimension"]] in tiles}
    widest = max(text_px(c, LABEL_PT, bold=True) for c in codes)
    if widest + LABEL_PAD_PX > tile_px:
        raise ValueError(f"Tile grid '{p['name']}': its tiles are {int(tile_px)}px wide, the label '{lab}' needs "
                         f"{widest + LABEL_PAD_PX}px: a shorter label, fewer columns or a wider zone")
    fmt = p["measure"].get("format") or b.number_format(b.col(p["measure"]["field"])) or "number"
    values = (b.expected.get(p["name"]) or {}).values()
    if max((text_px(formats.render(v, fmt), LABEL_PT) for v in values if v is not None), default=0) \
            + LABEL_PAD_PX > tile_px:
        ft, runs = b.tile_values[p["name"]]
        for r in runs:
            if r in list(ft):
                ft.remove(r)


def mark_style(rule, s):
    """The pane's 'mark' rule after the labels: every label shown, white lines between the tiles."""
    if not is_tilegrid(s):
        return
    for el in rule.findall("format[@attr='mark-labels-cull']"):
        el.set("value", "false")
    for attr, value in stroke():
        ET.SubElement(rule, "format", attr=attr, value=value)


def expected(s, rows, dim, value, grouped):
    """member -> measure."""
    return grouped(rows, [dim(s["dimension"])], value(s["measure"]))


def tiles(s, rows, values):
    """member -> {row, col (, group)}: 1-based places; a wall's by the measure descending (a tie by the member), in
    its group. values: member -> measure."""
    lay = s["layout"]
    if not wall(s):
        out = {}
        for r in rows:
            m = r[s["dimension"]]
            if m in values and m not in out:
                out[m] = {"row": int(float(r[lay["row"]])), "col": int(float(r[lay["col"]]))}
        return out
    group = {r[s["dimension"]]: r[s["group"]] for r in rows} if "group" in s else {}
    n, out, at = lay["cols"], {}, {}
    for m in sorted((m for m in values if values[m] is not None), key=lambda m: (-values[m], m)):
        g = group.get(m)
        i = at.get(g, 0)
        at[g] = i + 1
        out[m] = {"row": i // n + 1, "col": i % n + 1, **({"group": g} if "group" in s else {})}
    return out
