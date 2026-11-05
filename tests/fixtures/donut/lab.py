"""Donut labs (decisions/069): what Desktop 2025.1 draws for a Pie of a given size and for the legend forms.

  python tests/fixtures/donut/lab.py size|size2|legend|legend2|legend3|legend4|labels <out_dir>
  python tests/fixtures/donut/lab.py measure <dashboard.png> <book.twbx>

labels:  decisions/084, the combo's and the lollipop's labels (lab/dual_labels.png): the combo's bar values with
         cell vertical-align bottom / center / top (C1-C3; the line crosses the top ones), the lollipop's value as a
         discrete header (L1, reference 'Lollipop'), inside a big circle in white (L2), its circle's label with cell
         text-align right (L3: still on the circle at the pane's edge). Built with the generator of a6bf14a.
         lab/lolli_formats.png: the value header of 084 on Sales (currency_k) and on Profit by category with its
         text-format; without it (the first run, not kept) Desktop's automatic header showed every decimal of the
         real SUM and cut it to '8 38..' in the width measured for '8 389'.

size:    six donuts by Category (sales_2y.csv), the pie at P = 0.6 .. 2.6 and its hole at P * 1.6 / 2.6, each in a
         cell of a 1400 x 700 dashboard (no headers): px per unit of size, linear or not.
size2:   the same size (1.6) in cells of three heights: is the px of a size absolute.
legend:  four donuts whose legend sheets take the forms to compare:
         L1 Text mark, a '●' run without fontcolor (the mark's color) and the value and share in runs of their own
            color (per-run fontcolor against the color encoding), text left;
         L2 Circle (marks-scaling-off, small) with its label right of it (cell text-align right);
         L3 Bootcamp 'By Device': (Axis + Axis) on Columns, not folded: a Circle pane and a Text pane, text left;
         L4 L1 in two lines ('● member' over 'value (share)'), the row headers hidden (Citizen: label display false).
legend2: Enterprise Risk 'Risk level numbers': a colored Circle with its label in datalabel color-mode 'user' (M1 text
         left, M2 right), and the Text mark of L4 with color-mode user (M3) / auto (M4).
legend3: the dot on an axis (the donut's MIN(0), fixed -0.15..1, hidden), text-align right / left / none (N1-N3),
         the range from 0 (N4).
legend4: as legend3 N2 (text left) with dots of size 0.7 / 1.2 / 2.0 / 3.0 (Q1-Q4).
measure: the bounding box of the colored pixels of each donut zone -> outer and hole diameter in px.
The labs bypass the builder's own size and legend: the XML is patched after the build, the gate is not run. size,
size2 and legend were built with the generator of 897b852 (the 044 legend: a Circle labelled 'value (share)', equal
halves of the cell), legend2-4 with the work in progress of 069 (a Text legend, the ring check off); the patches
start from those forms. Snapshots: lab/*.png (PrintWindow, Desktop 2025.1).
"""
import json
import sys
import zipfile
from pathlib import Path

from lxml import etree

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from tbuilder import build as build_mod  # noqa: E402

SIZES = ["0.6", "1.0", "1.4", "1.8", "2.2", "2.6"]
HOLE = 1.6 / 2.6
DOT = "●"


def spec(names, grid, height=700, theme=None):
    sheets = [{"name": n, "type": "donut", "dimension": "Category", "measure": {"field": "Sales"}} for n in names]
    dash = {"name": "Lab", "title": "Donut lab", "width": 1400, "height": height, "grid": grid}
    if theme:
        dash["theme"] = theme
    return {"version": 1, "datasource": {"type": "csv", "path": "../../../data/sample/sales_2y.csv"},
            "sheets": sheets, "dashboard": dash}


def patch(path, fn):
    with zipfile.ZipFile(path) as z:
        members = {n: z.read(n) for n in z.namelist()}
    twb = next(n for n in members if n.endswith(".twb"))
    root = etree.fromstring(members[twb])
    fn(root)
    members[twb] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in members.items():
            z.writestr(n, b)


def ws(root, name):
    return next(w for w in root.iter("worksheet") if w.get("name") == name)


def set_size(root, name, pie, hole):
    panes = [p for p in ws(root, name).iterfind("table/panes/pane") if p.get("id")]
    for p, v in zip(panes, (pie, hole)):
        p.find("style/style-rule[@element='mark']/format[@attr='size']").set("value", v)


def sub(parent, tag, **attrs):
    return etree.SubElement(parent, tag, {k.replace("_", "-"): v for k, v in attrs.items()})


def runs(pane, items):
    lab = pane.find("customized-label")
    if lab is not None:
        pane.remove(lab)
    lab = etree.Element("customized-label")
    pane.find("mark").addnext(lab) if pane.find("encodings") is None else pane.find("encodings").addnext(lab)
    ft = sub(lab, "formatted-text")
    for text, attrs in items:
        sub(ft, "run", **attrs).text = text


def legend_l1(root, name):
    """Text mark: '●' (no fontcolor) + value (own color, bold) + share (muted), text left."""
    pane = ws(root, name).find("table/panes/pane")
    enc = pane.find("encodings")
    value, share = [e.get("column") for e in enc.iterfind("text")]
    pane.find("mark").set("class", "Text")
    runs(pane, [(DOT, {}), (f" <{value}>", {"bold": "true", "fontcolor": "#333333"}),
                (f" (<{share}>)", {"fontcolor": "#898989"})])
    style = pane.find("style")
    rule = style.find("style-rule[@element='mark']")
    rule.remove(rule.find("format[@attr='size']"))
    cell = etree.Element("style-rule", element="cell")
    sub(cell, "format", attr="text-align", value="left")
    style.insert(0, cell)


def legend_l4(root, name):
    """L1 in two lines and without the row header: '● member' over 'value (share)'; the header hidden by a label
    format (Citizen Service Requests: style-rule label, display false)."""
    w = ws(root, name)
    pane = w.find("table/panes/pane")
    enc = pane.find("encodings")
    dim = enc.find("color").get("column")
    value, share = [e.get("column") for e in enc.iterfind("text")]
    sub(enc, "text", column=dim)
    pane.find("mark").set("class", "Text")
    runs(pane, [(DOT, {}), (f" <{dim}>", {"fontcolor": "#333333"}), ("Æ\n", {}),
                (f"<{value}>", {"bold": "true", "fontcolor": "#333333"}), (f" (<{share}>)", {"fontcolor": "#898989"})])
    style = pane.find("style")
    rule = style.find("style-rule[@element='mark']")
    rule.remove(rule.find("format[@attr='size']"))
    cell = etree.Element("style-rule", element="cell")
    sub(cell, "format", attr="text-align", value="left")
    style.insert(0, cell)
    tstyle = w.find("table/style")
    label = etree.Element("style-rule", element="label")
    sub(label, "format", attr="display", field=dim, value="false")
    after = tstyle.find("style-rule[@element='pane']")
    after.addnext(label) if after is not None else tstyle.append(label)


def legend_l2(root, name):
    """Circle, fixed small size, label right of it."""
    pane = ws(root, name).find("table/panes/pane")
    pane.find("mark").addnext(etree.Element("mark-sizing", {"mark-sizing-setting": "marks-scaling-off"}))
    style = pane.find("style")
    style.find("style-rule[@element='mark']/format[@attr='size']").set("value", "0.12")
    cell = etree.Element("style-rule", element="cell")
    sub(cell, "format", attr="text-align", value="right")
    style.insert(0, cell)


def legend_l3(root, name, donut):
    """Bootcamp 'By Device': (Axis + Axis) on Columns without a fold: a Circle pane, a Text pane."""
    w, d = ws(root, name), ws(root, donut)
    deps, ddeps = w.find("table/view/datasource-dependencies"), d.find("table/view/datasource-dependencies")
    axis_col = next(c for c in ddeps.iterfind("column") if (c.get("caption") or "").endswith("· Axis"))
    axis_inst = next(c for c in ddeps.iterfind("column-instance") if c.get("column") == axis_col.get("name"))
    deps.insert(0, etree.fromstring(etree.tostring(axis_col)))
    deps.append(etree.fromstring(etree.tostring(axis_inst)))
    ds = deps.get("datasource")
    a = f"[{ds}].{axis_inst.get('name')}"
    table = w.find("table")
    old = table.find("panes/pane")
    enc = old.find("encodings")
    color = enc.find("color").get("column")
    value, share = [e.get("column") for e in enc.iterfind("text")]
    panes = table.find("panes")
    panes.remove(old)
    axis = table.find("style/style-rule[@element='axis']")
    if axis is None:
        axis = etree.Element("style-rule", element="axis")
        table.find("style").insert(0, axis)
    for i, cls in enumerate(("0", "1")):
        axis.insert(i, etree.Element("format", {"attr": "display", "class": cls, "field": a, "scope": "cols",
                                                "value": "false"}))
    default = sub(panes, "pane", selection_relaxation_option="selection-relaxation-allow")
    sub(sub(default, "view"), "breakdown", value="auto")
    sub(default, "mark", **{"class": "Circle"})
    for i, (mark, idx) in enumerate((("Circle", None), ("Text", "1")), 1):
        attrs = {"id": str(i), "selection-relaxation-option": "selection-relaxation-allow", "x-axis-name": a}
        if idx:
            attrs["x-index"] = idx
        p = sub(panes, "pane", **{k.replace("-", "_"): v for k, v in attrs.items()})
        sub(sub(p, "view"), "breakdown", value="auto")
        sub(p, "mark", **{"class": mark})
        sub(p, "mark-sizing", mark_sizing_setting="marks-scaling-off")
        e = sub(p, "encodings")
        if mark == "Circle":
            sub(e, "color", column=color)
        else:
            sub(e, "text", column=value)
            sub(e, "text", column=share)
            runs(p, [(f"<{value}>", {"bold": "true", "fontcolor": "#333333"}),
                     (f" (<{share}>)", {"fontcolor": "#898989"})])
        st = sub(p, "style")
        if mark == "Text":
            sub(sub(st, "style-rule", element="cell"), "format", attr="text-align", value="left")
        rule = sub(st, "style-rule", element="mark")
        sub(rule, "format", attr="mark-labels-show", value="true" if mark == "Text" else "false")
        if mark == "Circle":
            sub(rule, "format", attr="size", value="0.12")
    table.find("cols").text = f"({a} + {a})"


def legend_circle(root, name, align, mode="user", mark="Circle"):
    """legend2 (after legend: per-run colors lost to the color encoding): Enterprise Risk 'Risk level numbers' - a
    colored Circle (marks-scaling-off), its label in the datalabel color-mode 'user' (not the mark's color), leading
    spaces past the dot; cell text-align = align. mark='Text' + mode 'user': does the '●' run keep the mark's color?"""
    w = ws(root, name)
    pane = w.find("table/panes/pane")
    enc = pane.find("encodings")
    dim = enc.find("color").get("column")
    texts = [e.get("column") for e in enc.iterfind("text")]
    value, share = texts[0], texts[1]
    if dim not in texts:
        sub(enc, "text", column=dim)
    pane.find("mark").set("class", mark)
    if pane.find("mark-sizing") is None:
        pane.find("mark").addnext(etree.Element("mark-sizing", {"mark-sizing-setting": "marks-scaling-off"}))
    pad = "    " if mark == "Circle" else ""
    first = [(DOT, {})] if mark == "Text" else []
    runs(pane, first + [(f"{pad}<{dim}>", {"fontcolor": "#333333"}), ("Æ\n", {}),
                        (f"{pad}<{value}>", {"bold": "true", "fontcolor": "#333333"}),
                        (f" (<{share}>)", {"fontcolor": "#898989"})])
    style = pane.find("style")
    for r in list(style):
        if r.get("element") in ("cell", "datalabel"):
            style.remove(r)
    rule = style.find("style-rule[@element='mark']")
    for f in rule.findall("format[@attr='size']"):
        rule.remove(f)
    if mark == "Circle":
        sub(rule, "format", attr="size", value="0.12")
    cell = etree.Element("style-rule", element="cell")
    sub(cell, "format", attr="text-align", value=align)
    dl = etree.Element("style-rule", element="datalabel")
    sub(dl, "format", attr="color-mode", value=mode)
    sub(dl, "format", attr="color", value="#333333")
    style.insert(0, dl)
    style.insert(0, cell)


def legend_axis(root, name, donut, align, lo="-0.15", size="0.12"):
    """legend3: the dot on an axis (the donut's MIN(0) on Columns, fixed lo..1, hidden): a mark on an axis gets its
    label beside it, not centred on it (the lollipop's '685' left of its dot); align = cell text-align or None."""
    w, d = ws(root, name), ws(root, donut)
    deps, ddeps = w.find("table/view/datasource-dependencies"), d.find("table/view/datasource-dependencies")
    axis_col = next(c for c in ddeps.iterfind("column") if (c.get("caption") or "").endswith("· Axis"))
    axis_inst = next(c for c in ddeps.iterfind("column-instance") if c.get("column") == axis_col.get("name"))
    deps.insert(0, etree.fromstring(etree.tostring(axis_col)))
    deps.append(etree.fromstring(etree.tostring(axis_inst)))
    a = f"[{deps.get('datasource')}].{axis_inst.get('name')}"
    table = w.find("table")
    axis = table.find("style/style-rule[@element='axis']")
    axis.insert(0, etree.Element("encoding", {"attr": "space", "class": "0", "field": a, "field-type": "quantitative",
                                              "max": "1", "min": lo, "range-type": "fixed", "scope": "cols",
                                              "type": "space"}))
    axis.insert(1, etree.Element("format", {"attr": "display", "class": "0", "field": a, "scope": "cols",
                                            "value": "false"}))
    table.find("cols").text = a
    pane = table.find("panes/pane")
    enc = pane.find("encodings")
    dim = enc.find("color").get("column")
    texts = [e.get("column") for e in enc.iterfind("text")]
    value, share = texts[0], texts[1]
    if dim not in texts:
        sub(enc, "text", column=dim)
    pane.find("mark").set("class", "Circle")
    if pane.find("mark-sizing") is None:
        pane.find("mark").addnext(etree.Element("mark-sizing", {"mark-sizing-setting": "marks-scaling-off"}))
    runs(pane, [(f"<{dim}>", {"fontcolor": "#333333"}), ("Æ\n", {}),
                (f"<{value}>", {"bold": "true", "fontcolor": "#333333"}), (f" (<{share}>)", {"fontcolor": "#898989"})])
    style = pane.find("style")
    for r in list(style):
        if r.get("element") in ("cell", "datalabel"):
            style.remove(r)
    rule = style.find("style-rule[@element='mark']")
    for f in rule.findall("format[@attr='size']"):
        rule.remove(f)
    sub(rule, "format", attr="size", value=size)
    dl = etree.Element("style-rule", element="datalabel")
    sub(dl, "format", attr="color-mode", value="user")
    sub(dl, "format", attr="color", value="#333333")
    style.insert(0, dl)
    if align:
        cell = etree.Element("style-rule", element="cell")
        sub(cell, "format", attr="text-align", value=align)
        style.insert(0, cell)


def labels_spec(combos, lollipops):
    """decisions/084: the combo and the lollipop of specs/dual_axis.json, one sheet per label form."""
    sheets = [{"name": n, "type": "combo", "dimension": "Region", "bar": {"field": "Sales"},
               "line": {"field": "Profit"}, "sort": "desc"} for n in combos]
    sheets += [{"name": n, "type": "lollipop", "dimension": "Region", "measure": {"field": "Quantity"}, "sort": "desc"}
               for n in lollipops]
    dash = {"name": "Lab", "title": "Label lab", "width": 1400, "height": 900, "grid": [combos, lollipops]}
    return {"version": 1, "datasource": {"type": "csv", "path": "../../../data/sample/sales_2y.csv"},
            "sheets": sheets, "dashboard": dash}


def layer(root, name, i):
    return next(p for p in ws(root, name).iterfind("table/panes/pane") if p.get("id") == str(i))


def cell_align(pane, **attrs):
    """A pane's cell style (ER weekday: vertical-align bottom on the bar layer), before its mark rule."""
    style = pane.find("style")
    cell = etree.Element("style-rule", element="cell")
    for k, v in attrs.items():
        sub(cell, "format", attr=k.replace("_", "-"), value=v)
    style.insert(0, cell)


def combo_bar_align(root, name, value):
    cell_align(layer(root, name, 1), vertical_align=value)


def lollipop_value_column(root, name, width="40"):
    """Reference 'Lollipop' / Admissions 'Bar - Locations': the value as a discrete header right of the member
    (rows Dim / SUM(M):ok, header width 40, text right), the circle unlabelled."""
    w = ws(root, name)
    deps = w.find("table/view/datasource-dependencies")
    ds = deps.get("datasource")
    qk = next(c for c in deps.iterfind("column-instance") if c.get("name").endswith(":qk]"))
    ok = etree.fromstring(etree.tostring(qk))
    ok.set("name", qk.get("name").replace(":qk]", ":ok]"))
    ok.set("type", "ordinal")
    qk.addprevious(ok)
    ok_ref = f"[{ds}].{ok.get('name')}"
    rows = w.find("table/rows")
    rows.text = f"({rows.text} / {ok_ref})"
    tstyle = w.find("table/style")
    header = tstyle.find("style-rule[@element='header']")
    sub(header, "format", attr="width", field=ok_ref, value=width)
    label = etree.Element("style-rule", element="label")
    sub(label, "format", attr="text-align", field=ok_ref, value="right")
    tstyle.find("style-rule[@element='pane']").addprevious(label)
    circle = layer(root, name, 2)
    circle.remove(circle.find("encodings"))
    circle.find("style/style-rule[@element='mark']/format[@attr='mark-labels-show']").set("value", "false")


def lollipop_inside(root, name, size="3.0"):
    """A caption 'In bigger charts, put labels inside the circles' / Help Desk 'ADO Status': a big circle, its
    label centred on it in white (datalabel color-mode user, Admissions)."""
    circle = layer(root, name, 2)
    circle.find("style/style-rule[@element='mark']/format[@attr='size']").set("value", size)
    cell_align(circle, text_align="center", vertical_align="center")
    style = circle.find("style")
    dl = etree.Element("style-rule", element="datalabel")
    sub(dl, "format", attr="color-mode", value="user")
    sub(dl, "format", attr="color", value="#ffffff")
    style.find("style-rule[@element='mark']").addprevious(dl)


def lollipop_right(root, name):
    """The circle's label with cell text-align right: does Desktop keep it right of the circle at the pane's edge?"""
    cell_align(layer(root, name, 2), text_align="right")


def main(mode, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if mode == "labels":  # decisions/084
        combos, lollipops = ["C1 bottom", "C2 center", "C3 top"], ["L1 column", "L2 inside", "L3 right"]
        sp = labels_spec(combos, lollipops)
        path = build_mod.build(sp, out / "dual_labels.twbx", base_dir=str(HERE))
        patch(path, lambda r: (combo_bar_align(r, combos[0], "bottom"), combo_bar_align(r, combos[1], "center"),
                               combo_bar_align(r, combos[2], "top"), lollipop_value_column(r, lollipops[0]),
                               lollipop_inside(r, lollipops[1]), lollipop_right(r, lollipops[2])))
    elif mode == "size":
        names = [f"P{s}" for s in SIZES]
        sp = spec(names, [names[:3], names[3:]])
        path = build_mod.build(sp, out / "donut_size.twbx", base_dir=str(HERE))
        patch(path, lambda r: [set_size(r, f"P{s}", s, f"{float(s) * HOLE:.4f}") for s in SIZES])
    elif mode == "size2":
        names = ["H1", "H2", "H3"]
        sp = spec(names, [["H1", "H2"], ["H3"]], height=700)
        sp["dashboard"]["row_heights"] = [3, 1]
        path = build_mod.build(sp, out / "donut_size2.twbx", base_dir=str(HERE))
        patch(path, lambda r: [set_size(r, n, "1.6", f"{1.6 * HOLE:.4f}") for n in names])
    elif mode == "legend":
        names = ["L1", "L2", "L3", "L4"]
        sp = spec(names, [names])
        path = build_mod.build(sp, out / "donut_legend.twbx", base_dir=str(HERE))
        patch(path, lambda r: (legend_l1(r, "L1 · Legend"), legend_l2(r, "L2 · Legend"),
                               legend_l3(r, "L3 · Legend", "L3"), legend_l4(r, "L4 · Legend")))
    elif mode == "legend2":
        names = ["M1", "M2", "M3", "M4"]
        sp = spec(names, [names])
        from tbuilder import dualaxis
        dualaxis.ring_need_px = lambda b, s: (0, "")  # the lab's legends, not its rings
        path = build_mod.build(sp, out / "donut_legend2.twbx", base_dir=str(HERE))
        patch(path, lambda r: (legend_circle(r, "M1 · Legend", "left"), legend_circle(r, "M2 · Legend", "right"),
                               legend_circle(r, "M3 · Legend", "left", "user", "Text"),
                               legend_circle(r, "M4 · Legend", "left", "auto", "Text")))
    elif mode == "legend3":
        names = ["N1", "N2", "N3", "N4"]
        sp = spec(names, [names])
        from tbuilder import dualaxis
        dualaxis.ring_need_px = lambda b, s: (0, "")  # the lab's legends, not its rings
        path = build_mod.build(sp, out / "donut_legend3.twbx", base_dir=str(HERE))
        patch(path, lambda r: (legend_axis(r, "N1 · Legend", "N1", "right"), legend_axis(r, "N2 · Legend", "N2", "left"),
                               legend_axis(r, "N3 · Legend", "N3", None),
                               legend_axis(r, "N4 · Legend", "N4", "right", lo="0")))
    elif mode == "legend4":  # the dot's size: does the label clear a bigger dot?
        sizes = {"Q1": "0.7", "Q2": "1.2", "Q3": "2.0", "Q4": "3.0"}
        sp = spec(list(sizes), [list(sizes)])
        from tbuilder import dualaxis
        dualaxis.ring_need_px = lambda b, s: (0, "")  # the lab's legends, not its rings
        path = build_mod.build(sp, out / "donut_legend4.twbx", base_dir=str(HERE))
        patch(path, lambda r: [legend_axis(r, f"{n} · Legend", n, "left", size=v) for n, v in sizes.items()])
    else:
        raise SystemExit(f"unknown mode {mode}")
    (HERE / f"{mode}.json").write_text(json.dumps(sp, indent=1), encoding="utf-8")
    print(path)


def measure(png, book):
    """Each donut zone of the dashboard picture: bbox of saturated pixels (the ring) and the white run across its
    centre row (the hole)."""
    from tbuilder import screenshot as sh
    img = sh.load_png(png)
    root = sh._twb_root(book)
    d = root.find("./dashboards/dashboard")
    W, H = int(d.find("size").get("maxwidth")), int(d.find("size").get("maxheight"))
    sheets = {w.get("name") for w in root.iter("worksheet")
              if any(m.get("class") == "Pie" for m in w.iter("mark"))}
    out = {}
    for z in d.iter("zone"):
        if z.get("name") not in sheets or z.get("type-v2"):
            continue
        x, y, w, h = (int(z.get(k)) for k in ("x", "y", "w", "h"))
        x0, y0, x1, y1 = x * W // 100000, y * H // 100000, (x + w) * W // 100000, (y + h) * H // 100000
        pts = [(xx, yy) for yy in range(y0, y1) for xx in range(x0, x1)
               if (lambda c: max(c) - min(c) > 40)(img.pixel(xx, yy))]
        if not pts:
            out[z.get("name")] = None
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        cx, cy = (min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2
        row = [xx for xx in range(min(xs), max(xs) + 1) if max(img.pixel(xx, cy)) - min(img.pixel(xx, cy)) > 40]
        gaps = [b - a - 1 for a, b in zip(row, row[1:]) if b - a > 1]
        out[z.get("name")] = {"zone_px": [x1 - x0, y1 - y0], "ring_w": max(xs) - min(xs) + 1,
                              "ring_h": max(ys) - min(ys) + 1, "hole": max(gaps, default=0),
                              "clipped": min(xs) <= x0 + 1 or max(xs) >= x1 - 2}
    return out


if __name__ == "__main__":
    if sys.argv[1] == "measure":
        print(json.dumps(measure(sys.argv[2], sys.argv[3]), indent=1))
    else:
        main(sys.argv[1], sys.argv[2])
