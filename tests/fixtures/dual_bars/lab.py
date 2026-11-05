"""Combo bar lab (decisions/165): how wide Desktop 2025.1 draws a combo's Bar (marks-scaling-off) per unit of size,
and whether that px is absolute or follows the slot of a member; the bars' values at their end (no cell rule).

  python tests/fixtures/dual_bars/lab.py build <out_dir>         -> <out_dir>/combo_size.twbx
  py -3.14 tests/fixtures/dual_bars/lab.py measure tests/fixtures/dual_bars/lab/combo_size.png

Row 1: four combos (specs/dual_axis.json's) at bar size 0.6 / 1.0 / 1.4 / 1.8 in quarter-width cells; row 2: two at
1.0 / 1.8 in half-width cells (a slot of a member twice as wide). The XML is patched after the build (the cell rule of
084 removed, the size set), the gate is not run. Result (lab/combo_size.png, Desktop 2025.1): a Bar is size / 2 of
its slot whatever the slot's px: 61px slots 18 / 31 / 43 / 55px, 147px slots 74 / 133px; the values above the bars,
the line through the tallest one's.
"""
import sys
import zipfile
from pathlib import Path

from lxml import etree

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from tbuilder import build as build_mod  # noqa: E402

ROW1 = {"S0.6": "0.6", "S1.0": "1.0", "S1.4": "1.4", "S1.8": "1.8"}
ROW2 = {"W1.0": "1.0", "W1.8": "1.8"}


def spec():
    names = list(ROW1) + list(ROW2)
    sheets = [{"name": n, "type": "combo", "dimension": "Region", "bar": {"field": "Sales"},
               "line": {"field": "Profit"}, "sort": "desc"} for n in names]
    dash = {"name": "Lab", "title": "Combo bar lab", "width": 1400, "height": 900, "grid": [list(ROW1), list(ROW2)]}
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


def set_bar(root, name, size):
    w = next(x for x in root.iter("worksheet") if x.get("name") == name)
    pane = next(p for p in w.iterfind("table/panes/pane") if p.get("id") == "1")
    for cell in pane.findall("style/style-rule[@element='cell']"):
        cell.getparent().remove(cell)
    pane.find("style/style-rule[@element='mark']/format[@attr='size']").set("value", size)


def build(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = build_mod.build(spec(), out / "combo_size.twbx", base_dir=str(HERE))
    patch(path, lambda r: [set_bar(r, n, v) for n, v in {**ROW1, **ROW2}.items()])
    print(path)


def measure(png):
    """Runs of the bars' grey (#d3d3d3) across a row of each lab row (PIL: py -3.14) -> bar px, slot px."""
    from PIL import Image
    img = Image.open(png).convert("RGB")
    for name, y in (("row 1", 400), ("row 2", 800)):  # lab/combo_size.png, 1400 x 900
        runs, start = [], None
        for x in range(img.width):
            grey = all(abs(c - 211) < 8 for c in img.getpixel((x, y)))
            if grey and start is None:
                start = x
            if not grey and start is not None:
                runs.append((start, x - start))
                start = None
        print(name, "bars", [n for _, n in runs], "slots", [b[0] - a[0] for a, b in zip(runs, runs[1:])])


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build(sys.argv[2])
    else:
        measure(sys.argv[2])
