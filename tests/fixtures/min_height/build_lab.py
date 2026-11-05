"""Chart min height lab (decisions/101): what Desktop 2025.1 draws for a line / area / bar / combo / scatter / heatmap
in a zone H px high (inside its margins), on a dashboard without a theme like a public book's (block headers, sheet titles
off).

  python tests/fixtures/min_height/build_lab.py <out_dir> [H ...] [--fit standard|fit-width|entire-view]

Per H: <out_dir>/h<H>[_<fit>].twbx. Rows 1 and 2 hold the sheets under test at H px; row 3 the same line, area and
bar as a control, tall. The dashboard's height and the control row's weight are searched so the zone of 'Line' is H
px inside its margins (fit.zone_px). Data: tests/fixtures/fit/lab.csv (seeded). --fit forces every viewpoint's zoom
of rows 1-2 (as the fit lab does, decisions/068): built without the gate. The builder's min-height check is lifted
(MIN_CHECK and gate.check_chart_height off) so the lab can build below it; --fit books are forced after the gate.
"""
import copy
import json
import sys
import zipfile
from pathlib import Path

from lxml import etree

HERE = Path(__file__).resolve().parent
FIT = HERE.parent / "fit"
sys.path.insert(0, str(HERE.parents[2]))

from tbuilder import build as build_mod  # noqa: E402
from tbuilder import fit  # noqa: E402

DATE = {"field": "Order Date", "level": "week"}


def sheets():
    s = [{"name": "Line", "type": "line", "title": "Line by week", "date": DATE, "measure": {"field": "Sales"}},
         {"name": "Area", "type": "area", "title": "Area by week", "date": DATE, "measure": {"field": "Sales"}},
         {"name": "BarH", "type": "bar", "title": "Bar 5 groups", "dimension": "Group", "measure": {"field": "Sales"},
          "sort": "desc", "labels": "none"},  # the axis the lab measured (decisions/101, before 087)
         {"name": "BarV", "type": "bar", "title": "Bar 5 groups, vertical", "dimension": "Group", "measure": {"field": "Sales"},
          "orientation": "vertical", "sort": "desc"},
         {"name": "Combo", "type": "combo", "title": "Combo by group", "dimension": "Group", "bar": {"field": "Sales"},
          "line": {"field": "Profit"}, "sort": "desc"},
         {"name": "Scatter", "type": "scatter", "title": "Scatter by item", "detail": "Item",
          "x": {"field": "Quantity"}, "y": {"field": "Sales"}},
         {"name": "Heat", "type": "heatmap", "title": "Heatmap team x region", "rows": "Team", "cols": "Region",
          "measure": {"field": "Sales"}, "color": {"scale": "sequential"}},
         {"name": "AreaD", "type": "area", "title": "Area by day", "date": {"field": "Order Date", "level": "day"},
          "measure": {"field": "Sales"}}]
    ctl = [dict(copy.deepcopy(x), name=x["name"] + " ctl", title=x["title"] + " (control)") for x in s[:3]]
    return s, ctl


def spec(height, weight):
    s, ctl = sheets()
    return {"version": 1, "datasource": {"type": "csv", "path": "lab.csv"}, "sheets": s + ctl,
            "dashboard": {"name": "Lab", "title": "Min height lab", "width": 1600, "height": height, "theme": "flat",
                          "grid": [["Line", "Area", "BarH", "BarV"], ["Combo", "Scatter", "Heat", "AreaD"],
                                   [x["name"] for x in ctl]],
                          "row_heights": [1, 1, weight]}}


def zone_h(book, name="Line"):
    with zipfile.ZipFile(book) as z:
        root = etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))
    db = next(root.iter("dashboard"))
    size = db.find("size")
    dims = (int(size.get("maxwidth")), int(size.get("maxheight")))
    return {z.get("name"): fit.zone_px(z, dims) for z in db.find("zones").iter("zone")
            if z.get("name") and not z.get("type-v2")}


def force(book, mode, names):
    with zipfile.ZipFile(book) as z:
        items = {n: z.read(n) for n in z.namelist()}
    twb = next(n for n in items if n.endswith(".twb"))
    root = etree.fromstring(items[twb])
    for win in root.iter("window"):
        if win.get("class") == "dashboard":
            for vp in win.iter("viewpoint"):
                if vp.get("name") in names:
                    for zm in vp.findall("zoom"):
                        vp.remove(zm)
                    if mode != "standard":
                        etree.SubElement(vp, "zoom", type=mode)
    items[twb] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
    with zipfile.ZipFile(book, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in items.items():
            z.writestr(n, data)


def build(target, out, mode=None):
    tmp = out / "_try.twbx"
    best = None
    for weight in [max(1, min(12, round(300 / target)))]:  # the control row ~300px
        lo, hi = 300, 4000
        while lo <= hi:  # the zone grows with the height
            mid = (lo + hi) // 2
            try:
                build_mod.build(spec(mid, weight), tmp, base_dir=str(FIT))
            except ValueError:  # a row too short for its block headers: taller
                lo = mid + 1
                continue
            h = zone_h(tmp)["Line"][1]
            if best is None or abs(h - target) < abs(best[0] - target):
                best = (h, mid, weight)
            if h == target:
                break
            lo, hi = (mid + 1, hi) if h < target else (lo, mid - 1)
        if best[0] == target:
            break
    h, height, weight = best
    dst = out / (f"h{target}" + (f"_{mode}" if mode else "") + ".twbx")
    sp = spec(height, weight)
    build_mod.build(copy.deepcopy(sp), dst, base_dir=str(FIT))
    (out / (dst.stem + ".json")).write_text(json.dumps(dict(sp, datasource={"type": "csv", "path": str(
        (FIT / "lab.csv").resolve())}), indent=1), encoding="utf-8")
    if mode:
        force(dst, mode, {x["name"] for x in sheets()[0]})
    zones = zone_h(dst)
    print(dst, {n: zones[n] for n in ("Line", "Combo", "Line ctl")}, "dashboard", height, "weight", weight)
    tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    mode = None
    if "--fit" in args:
        i = args.index("--fit")
        mode = args[i + 1]
        del args[i:i + 2]
    out = Path(args[0])
    out.mkdir(parents=True, exist_ok=True)
    build_mod.MIN_CHECK = False
    build_mod.gate.check_chart_height = lambda root: []  # the gate's check of it too
    for t in args[1:]:
        build(int(t), out, mode)
