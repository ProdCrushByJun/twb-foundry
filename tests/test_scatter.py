"""Scatter (decisions/047): points by a detail dimension, axis lines at the average / median, highlight, color, size,
trend line; round-trip, workbook, expected numbers vs the CSV and Desktop, reconcile, refusals, gate mutations."""
import copy
import csv
import json
import statistics
import unittest
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict

from tbuilder import expected, gate, reconcile, scatter, spec as spec_mod
from tbuilder.build import build, build_file
from tbuilder.design_lint import lint
from test_gate import repack, ws
from test_roundtrip import OUT, ROOT, canon, normalize, read_twbx

SPEC = ROOT / "specs" / "scatter.json"
CSV = ROOT / "data" / "sample" / "sales_products.csv"
GOLDEN = ROOT / "golden" / "golden_scatter_2025_1.twb"
ROWS = list(csv.DictReader(CSV.open(encoding="utf-8")))


def spec():
    return json.loads(SPEC.read_text(encoding="utf-8"))


def sheet(s, name):
    return next(x for x in s["sheets"] if x["name"] == name)


def twb(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


def sums(field, *by):
    out = defaultdict(float)
    for r in ROWS:
        out[" | ".join(r[b] for b in by)] += float(r[field])
    return out


class RoundTrip(unittest.TestCase):
    def test_golden_rebuilds_identically(self):
        """Highlight + averages, size + medians + trend, color by dimension, color by measure: re-saved by Desktop
        2025.1 (Save As from a fresh open) without a change."""
        out = build_file(SPEC, OUT / "roundtrip_scatter.twbx")
        got, names = read_twbx(out)
        self.assertIn("Data/sample/sales_products.csv", names)
        self.assertEqual(canon(normalize(ET.parse(GOLDEN).getroot())), canon(normalize(got)))


class Workbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = twb(build_file(SPEC, OUT / "scatter.twbx"))

    def test_shelves_marks_detail(self):
        w = ws(self.root, "Products")
        self.assertTrue(w.findtext("table/rows").endswith("[sum:Sales:qk]"))
        self.assertTrue(w.findtext("table/cols").endswith("[sum:Quantity:qk]"))
        pane = w.find("table/panes/pane")
        self.assertEqual(pane.find("mark").get("class"), "Circle")
        self.assertEqual(pane.find("mark-sizing").get("mark-sizing-setting"), "marks-scaling-off")
        self.assertEqual([e.tag for e in pane.find("encodings")], ["color", "lod"])
        self.assertTrue(pane.find("encodings/lod").get("column").endswith("[none:Product:nk]"))

    def test_axis_lines_x_first_as_novacart(self):
        lines = ws(self.root, "Products").findall("table/panes/pane/reference-line")
        self.assertEqual([(l.get("id"), l.get("formula"), l.get("label")) for l in lines],
                         [("refline0", "average", "Avg: <Value>"), ("refline1", "average", "Avg: <Value>")])
        self.assertTrue(lines[0].get("axis-column").endswith("[sum:Quantity:qk]"))
        self.assertTrue(lines[1].get("axis-column").endswith("[sum:Sales:qk]"))
        self.assertTrue(all(l.get("axis-column") == l.get("value-column") for l in lines))
        self.assertTrue(all(l.get("tooltip-type") is None for l in lines))  # Desktop 2025.1 does not declare it
        fmt = {f.get("id"): f.get("value") for f in ws(self.root, "Products").iterfind(
            "table/style/style-rule[@element='refline']/format[@attr='text-format']")}
        self.assertEqual(fmt, {"refline0": "n#,##0;-#,##0", "refline1": 'c"$"#,##0;-"$"#,##0'})  # the axis format

    def test_medians_size_trend(self):
        pane = ws(self.root, "Profitability").find("table/panes/pane")
        self.assertEqual([e.tag for e in pane.find("encodings")], ["size", "lod"])
        self.assertEqual({l.get("formula") for l in pane.findall("reference-line")}, {"median"})
        self.assertEqual([c.tag for c in pane][3:6], ["encodings", "trendline", "reference-line"])  # XSD order
        t = pane.find("trendline")
        self.assertEqual((t.get("fit"), t.get("enabled"), t.get("exclude-color")), ("linear", "true", "true"))
        self.assertIsNotNone(pane.find("style/style-rule[@element='trendline']"))

    def test_highlight_palette_and_no_legend(self):
        maps = {m.get("to"): m.findtext("bucket") for m in
                self.root.find("datasources/datasource").iterfind("style/style-rule/encoding/map")}
        self.assertEqual(maps, {"#4e79a7": "true", "#d4d4d4": "false"})
        legends = [z for z in self.root.iter("zone") if z.get("type-v2") == "color"]
        self.assertEqual([z.get("name") for z in legends], ["Regions"])  # the color dimension only
        mark = ws(self.root, "Products").find("table/panes/pane/style/style-rule[@element='mark']")
        self.assertIsNone(mark.find("format[@attr='mark-color']"))  # the palette colors it

    def test_one_color_accent(self):
        mark = ws(self.root, "Profitability").find("table/panes/pane/style/style-rule[@element='mark']")
        self.assertEqual(mark.find("format[@attr='mark-color']").get("value"), "#4e79a7")

    def test_color_measure_sequential(self):
        w = ws(self.root, "Margin")
        enc = w.find("table/style/style-rule[@element='mark']/encoding")
        self.assertEqual(enc.get("type"), "custom-interpolated")
        self.assertTrue(enc.get("field").endswith("[sum:Sales:qk]"))

    def test_fills_its_zone(self):
        zooms = {vp.get("name") for vp in self.root.iter("viewpoint") if vp.find("zoom") is not None}
        self.assertLessEqual({"Products", "Profitability", "Regions", "Margin"}, zooms)


class Expected(unittest.TestCase):
    """The numbers, computed from the CSV here independently, and the values Desktop 2025.1 drew (golden_scatter)."""

    @classmethod
    def setUpClass(cls):
        cls.exp = expected.compute(spec(), CSV)

    def test_points(self):
        q, s = sums("Quantity", "Product"), sums("Sales", "Product")
        got = self.exp["Products"]
        self.assertEqual(sorted(got), sorted(q))
        for p in q:
            self.assertAlmostEqual(got[p]["SUM(Quantity)"], q[p], 6)
            self.assertAlmostEqual(got[p]["SUM(Sales)"], s[p], 6)

    def test_color_dimension_splits_the_points(self):
        got = self.exp["Regions"]
        s = sums("Sales", "Product", "Region")
        self.assertEqual(len(got), 64)
        self.assertAlmostEqual(got["Atlas | East"]["SUM(Sales)"], s["Atlas | East"], 6)

    def test_axis_lines_as_desktop(self):
        q, s, p = sums("Quantity", "Product"), sums("Sales", "Product"), sums("Profit", "Product")
        avg = self.exp[scatter.record("Products")]
        self.assertAlmostEqual(avg["SUM(Quantity)"], sum(q.values()) / len(q), 9)
        self.assertAlmostEqual(avg["SUM(Sales)"], sum(s.values()) / len(s), 9)
        med = self.exp[scatter.record("Profitability")]
        self.assertAlmostEqual(med["SUM(Sales)"], statistics.median(s.values()), 6)
        self.assertAlmostEqual(med["SUM(Profit)"], statistics.median(p.values()), 6)
        # Desktop 2025.1 labels: Avg: 205, Avg: $10 659, Median $10 729, Median 1 314 (pandas: 205.3125, 10659.22,
        # 10729.26, 1313.52)
        self.assertEqual([round(v) for v in avg.values()], [205, 10659])
        self.assertEqual([round(v) for v in med.values()], [10729, 1314])


class Reconcile(unittest.TestCase):
    def test_entries(self):
        s = spec()
        ents = [e for e in reconcile.entries(s, expected.compute(s, CSV)) if e["sheet"] == "Products"]
        self.assertEqual(len(ents), 16 * 2 + 2)
        lines = [e for e in ents if e.get("part", "").startswith("reference line")]
        self.assertEqual([(e["tags"], e.get("fmt")) for e in lines],
                         [(["Avg:", "Quantity"], None), (["Avg:", "Sales"], "currency")])
        iris = [e for e in ents if e["key"] == "Iris"]
        self.assertEqual(sorted(e["tags"][0] for e in iris), ["Quantity", "Sales"])


class Refusals(unittest.TestCase):
    def build(self, change):
        s = spec()
        change(sheet(s, "Products"))
        return build(s, OUT / "scatter_bad.twbx", SPEC.parent)

    def refused(self, change, text):
        with self.assertRaises(ValueError) as e:
            self.build(change)
        self.assertIn(text, str(e.exception))

    def test_same_measure_on_both_axes(self):
        self.refused(lambda p: p.update(y={"field": "Quantity"}), "same measure")

    def test_unknown_highlight(self):
        self.refused(lambda p: p.update(color={"highlight": ["Zeta"]}), "are not in 'Product'")

    def test_numeric_detail(self):
        self.refused(lambda p: p.update(detail="Profit"), "text dimension")

    def test_color_is_the_detail(self):
        self.refused(lambda p: p.update(color="Product", subtitle="by product"), "color is the detail field")

    def test_table_calc(self):
        self.refused(lambda p: p["x"].update(table_calc={"type": "running_total"}), "not supported yet")

    def test_accent_word_without_accent(self):
        def f(p):
            p["color"] = "Region"
        self.refused(f, "name a color that is not drawn")

    def test_schema_rejects_foreign_keys(self):
        s = spec()
        sheet(s, "Products")["measure"] = {"field": "Sales"}
        with self.assertRaises(spec_mod.SpecError):
            spec_mod.validate(s)
        s = spec()
        sheet(s, "Products")["axis_lines"] = {"type": "const"}
        with self.assertRaises(spec_mod.SpecError):
            spec_mod.validate(s)


class Lint(unittest.TestCase):
    def test_spec_is_clean(self):
        self.assertEqual([f for f in lint(spec()) if f.level == "error"], [])


class GateCatchesScatter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build_file(SPEC, OUT / "scatter_gate.twbx")

    def assertCaught(self, fn, text):
        issues = [str(i) for i in gate.run(repack(fn, source=self.path))]
        self.assertTrue(any(i.startswith("[scatter]") and text in i for i in issues), issues)

    def test_clean(self):
        self.assertEqual(gate.run(self.path), [])

    def test_line_on_a_field_off_the_axes(self):
        def f(r):
            pane = ws(r, "Profitability").find("table/panes/pane")
            size = pane.find("encodings/size").get("column")
            pane.find("reference-line").set("axis-column", size)
        self.assertCaught(f, "on neither Rows nor Columns")

    def test_trend_line_on_a_discrete_axis(self):
        def f(r):
            t = ws(r, "Profitability").find("table")
            t.find("cols").text = t.find("panes/pane/encodings/lod").get("column")
        self.assertCaught(f, "trend line without a continuous axis")

    def test_scatter_without_a_dimension(self):
        def f(r):
            enc = ws(r, "Profitability").find("table/panes/pane/encodings")
            enc.remove(enc.find("lod"))
        self.assertCaught(f, "one aggregate point")

    def test_novacart_form_passes(self):
        """The reference's own sheet shape (lines on both axes of a scatter) is not flagged."""
        root = twb(self.path)
        self.assertEqual([i for i in gate.check_scatter(root)], [])


if __name__ == "__main__":
    unittest.main()
