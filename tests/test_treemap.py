"""Treemap (decisions/138): the type in the schema, the Square marks and encodings of the reference books, the
sequential scale by the size, highlight, expected numbers, refusals."""
import csv
import unittest
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict

from tbuilder import expected, spec as spec_mod
from tbuilder.build import build
from tbuilder.design import COLOR
from test_gate import ws
from test_roundtrip import OUT, ROOT

CSV = ROOT / "data" / "sample" / "sales_products.csv"


def spec():
    return {"version": 1, "datasource": {"type": "csv", "path": "data/sample/sales_products.csv"},
            "sheets": [{"name": "Scale", "type": "treemap", "group": "Region", "label": "Product",
                        "size": {"field": "Sales"}, "value": True},
                       {"name": "Marked", "type": "treemap", "label": "Product", "size": {"field": "Sales"},
                        "color": {"highlight": ["Ember"]}}],
            "dashboard": {"name": "D", "width": 1000, "height": 600, "accent": "#0d6b4f",
                          "grid": [["Scale", "Marked"]]}}


def twb(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


class Treemap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = twb(build(spec(), OUT / "treemap.twbx", base_dir=ROOT))  # passes the gate

    def test_schema(self):
        spec_mod.validate(spec())
        for key, value in (("size", None), ("rows", "Region")):  # size required, no shelves
            bad = spec()
            bad["sheets"][0].pop(key, None) if value is None else bad["sheets"][0].update({key: value})
            with self.assertRaises(ValueError):
                spec_mod.validate(bad)

    def test_square_encodings_scale(self):
        """Keyword Research / Citizen: Square, no shelves, measure on size and color, group on Detail before the
        label; the scale scale_low -> accent of the book; labels culled, white lines between rectangles."""
        w = ws(self.root, "Scale")
        pane = w.find("table/panes/pane")
        self.assertEqual("Square", pane.find("mark").get("class"))
        self.assertIsNone(w.find("table/rows").text)
        self.assertIsNone(w.find("table/cols").text)
        enc = [(e.tag, e.get("column").split("].[")[-1]) for e in pane.find("encodings")]
        self.assertEqual([("color", "sum:Sales:qk]"), ("size", "sum:Sales:qk]"), ("lod", "none:Region:nk]"),
                          ("text", "none:Product:nk]"), ("text", "sum:Sales:qk]")], enc)
        e = w.find("table/style/style-rule[@element='mark']/encoding[@attr='color']")
        self.assertEqual("custom-interpolated", e.get("type"))
        colors = [c.text for c in e.find("color-palette")]
        self.assertEqual((COLOR["scale_low"], "#0d6b4f"), (colors[0], colors[-1]))
        fmt = {f.get("attr"): f.get("value") for f in pane.findall("style/style-rule[@element='mark']/format")}
        self.assertEqual({"mark-labels-show": "true", "mark-labels-cull": "true", "has-stroke": "true",
                          "stroke-color": "#ffffff"}, fmt)

    def test_highlight(self):
        w = ws(self.root, "Marked")
        tags = [e.tag for e in w.find("table/panes/pane/encodings")]
        self.assertEqual(["color", "size", "text"], tags)
        col = w.find("table/panes/pane/encodings/color").get("column").split("].[")[-1].split(":")[1]
        captions = {c.get("name"): c.get("caption") for c in self.root.iter("column")}
        self.assertEqual("Marked · Highlight", captions[f"[{col}]"])
        self.assertIsNone(w.find("table/style/style-rule[@element='mark']/encoding"))

    def test_expected(self):
        sums = defaultdict(float)
        for r in csv.DictReader(CSV.open(encoding="utf-8")):
            sums[(r["Region"], r["Product"])] += float(r["Sales"])
        got = expected.compute(spec(), CSV)["Scale"]
        self.assertEqual(len(sums), len(got))
        self.assertAlmostEqual(sum(sums.values()), sum(got.values()), places=2)

    def test_unknown_highlight_refused(self):
        bad = spec()
        bad["sheets"][1]["color"] = {"highlight": ["Nope"]}
        with self.assertRaisesRegex(ValueError, "not in 'Product'"):
            build(bad, OUT / "treemap_bad.twbx", base_dir=ROOT)


if __name__ == "__main__":
    unittest.main()
