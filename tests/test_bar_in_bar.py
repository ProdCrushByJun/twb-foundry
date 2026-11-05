"""Bar-in-bar (decisions/156, reference 'Ungrouped Stacked'): the member's total as a wide bar, the parts of its color
field side by side inside it. Refusals of the spec, the XML form, the gate's checks with their mutations, the totals
against a sum of the CSV."""
import csv
import json
import unittest
from collections import defaultdict
from pathlib import Path

from tbuilder import barinbar, expected, gate
from tbuilder.build import build
from test_bar_labels import built, repack, ws
from test_roundtrip import SPECS

ROOT = Path(__file__).resolve().parent.parent


def load():
    return json.loads((SPECS / "bar_in_bar.json").read_text(encoding="utf-8"))


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def layers(w):
    return w.findall("table/panes/pane[@id]")


class Refused(unittest.TestCase):
    def refused(self, change, why):
        spec = load()
        s = sheet(spec, "Inside")
        for k, v in change.items():
            if v is None:
                s.pop(k, None)
            else:
                s[k] = v
        with self.assertRaisesRegex(ValueError, why):
            build(spec, ROOT / "out" / "bar_in_bar_refused.twbx", SPECS)

    def test_needs_a_part_field(self):
        self.refused({"color": None, "legend": None}, "parts 'inside' needs 'color'")
        self.refused({"color": "Region", "legend": None}, "parts 'inside' needs 'color'")

    def test_not_with_other_bar_variants(self):
        self.refused({"total": "end"}, "does not go with total")
        self.refused({"reference": {"type": "avg"}}, "does not go with reference")
        self.refused({"labels": "none"}, "does not go with labels")
        self.refused({"top": {"n": 2}}, "does not go with top")

    def test_vertical_only(self):
        self.refused({"orientation": None}, "is a vertical bar")
        self.refused({"orientation": "horizontal"}, "is a vertical bar")


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(load(), ROOT / "out" / "bar_in_bar_test.twbx")  # its own file: modules run in parallel

    def test_shelves(self):
        w = ws(self.root, "Inside")
        self.assertRegex(w.find("table/cols").text, r"^\(\[.*none:Region:nk\] \* \[.*usr:Calculation_\d+:qk\]\)$")
        self.assertRegex(w.find("table/rows").text, r"^\(\[.*sum:Sales:qk\] \+ \[.*sum:Sales:qk\]\)$")
        v = ws(self.root, "Columns")
        self.assertIn("none:Region:nk", v.find("table/cols").text)
        self.assertIn("sum:Profit:qk", v.find("table/rows").text)

    def test_layers(self):
        total, parts = layers(ws(self.root, "Inside"))
        self.assertIsNone(total.find("encodings/color"))
        self.assertIn("none:Category:nk", parts.find("encodings/color").get("column"))
        self.assertEqual(parts.get("y-index"), "1")
        sizes = [float(p.find("mark-sizing").get("custom-mark-size-in-axis-units")) for p in (total, parts)]
        self.assertEqual(sizes, [3 + barinbar.TOTAL_PAD, barinbar.PART])  # 3 categories
        for p in (total, parts):
            self.assertEqual(p.find("mark-sizing").get("mark-sizing-setting"), "marks-scaling-on")
            self.assertIsNotNone(p.find("style/style-rule/format[@attr='mark-labels-show'][@value='true']"))
            self.assertIsNone(p.find("style/style-rule/format[@attr='mark-labels-cull']"))  # every value shown

    def test_position_and_axes(self):
        w = ws(self.root, "Inside")
        calc = next(c for c in w.iter("column") if c.get("caption") == "Inside · Position")
        self.assertEqual(calc.find("calculation").get("formula"), barinbar.FORMULA)
        ci = next(c for c in w.iter("column-instance") if c.get("column") == calc.get("name"))
        self.assertIn("none:Category:nk", ci.find("table-calc").get("ordering-field"))
        axis = w.find("table/style/style-rule[@element='axis']")
        rng = axis.find("encoding[@range-type='fixed']")
        self.assertEqual((rng.get("min"), rng.get("max"), rng.get("scope")), ("-2.25", "2.25", "cols"))
        self.assertEqual(axis.find("encoding[@fold='true']").get("synchronized"), "true")
        self.assertEqual(len(axis.findall("format[@attr='display'][@value='false']")), 3)  # both measure axes, position


class Numbers(unittest.TestCase):
    def test_totals_are_the_sums(self):
        spec = load()
        got = expected.compute(spec, expected.data_path(spec, SPECS))
        sums, parts = defaultdict(float), defaultdict(float)
        with open(ROOT / "data" / "sample" / "sales.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                sums[r["Region"]] += float(r["Sales"])
                parts[f"{r['Region']} | {r['Category']}"] += float(r["Sales"])
        self.assertEqual(set(got["Inside · Total"]), set(sums))
        for k, v in sums.items():
            self.assertAlmostEqual(got["Inside · Total"][k], v, places=2)
        for k, v in parts.items():
            self.assertAlmostEqual(got["Inside"][k], v, places=2)


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = build(load(), ROOT / "out" / "bar_in_bar_gate.twbx", SPECS)

    def test_clean(self):
        self.assertEqual(gate.run(self.book), [])

    def caught(self, fn, text):
        got = [str(i) for i in gate.run(repack(self.book, fn)) if i.check == "bar-in-bar"]
        self.assertEqual(len(got), 1, got)
        self.assertIn(text, got[0])

    def test_total_split_by_color(self):
        def fn(root):
            total, parts = layers(ws(root, "Inside"))
            enc = total.makeelement("encodings", {})
            enc.append(parts.find("encodings/color").__copy__())
            total.insert(3, enc)
        self.caught(fn, "one layer is the total")

    def test_position_formula(self):
        def fn(root):
            for c in ws(root, "Inside").iter("column"):
                if c.get("caption") == "Inside · Position":
                    c.find("calculation").set("formula", "INDEX()")
        self.caught(fn, "the position is not")

    def test_position_not_along_parts(self):
        def fn(root):
            for ci in ws(root, "Inside").iter("column-instance"):
                if ci.find("table-calc") is not None:
                    ci.find("table-calc").set("ordering-field", "[x].[none:Region:nk]")
        self.caught(fn, "does not run along the part field")

    def test_total_not_wider(self):
        def fn(root):
            layers(ws(root, "Inside"))[0].find("mark-sizing").set("custom-mark-size-in-axis-units", "0.5")
        self.caught(fn, "is not wider than a part")

    def test_axis_clips_the_total(self):
        def fn(root):
            ws(root, "Inside").find("table/style/style-rule[@element='axis']/encoding[@range-type='fixed']").set(
                "max", "1.75")
        self.caught(fn, "is not fixed wider than")

    def test_unsynchronized(self):
        def fn(root):
            del ws(root, "Inside").find("table/style/style-rule[@element='axis']/encoding[@fold='true']").attrib[
                "synchronized"]
        got = [str(i) for i in gate.run(repack(self.book, fn)) if i.check == "dual-axis"]
        self.assertEqual(len(got), 1, got)


if __name__ == "__main__":
    unittest.main()
