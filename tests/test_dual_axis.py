"""Dual axis (decisions/044): combo, donut, lollipop; expected, reconcile, refusals, lint, gate mutations."""
import csv
import json
import unittest
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict

from tbuilder import dualaxis, expected, gate, reconcile
from tbuilder.build import build, build_file
from tbuilder.design import COLOR, PIE_PX_PER_SIZE
from tbuilder.design_lint import lint
from test_gate import repack, ws
from test_roundtrip import OUT, ROOT

SPEC = ROOT / "specs" / "dual_axis.json"
CSV = ROOT / "data" / "sample" / "sales_2y.csv"
ROWS = list(csv.DictReader(CSV.open(encoding="utf-8")))


def spec():
    return json.loads(SPEC.read_text(encoding="utf-8"))


def sheet(s, name):
    return next(x for x in s["sheets"] if x["name"] == name)


def twb(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


def total(field, by):
    out = defaultdict(float)
    for r in ROWS:
        out[r[by]] += float(r[field])
    return out


def fold(w):
    return w.find("table/style/style-rule[@element='axis']/encoding[@fold='true']")


def layers(w):
    return [p for p in w.findall("table/panes/pane") if p.get("id")]


class Workbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = twb(build_file(SPEC, OUT / "dual_axis.twbx"))

    def test_combo_bars_and_a_line_on_two_axes(self):
        w = ws(self.root, "Combo")
        bar, line = layers(w)
        self.assertEqual([p.find("mark").get("class") for p in layers(w)], ["Bar", "Line"])
        self.assertIn("[sum:Sales:qk]", bar.get("y-axis-name"))
        self.assertIn("[sum:Profit:qk]", line.get("y-axis-name"))
        rows = w.findtext("table/rows")
        self.assertRegex(rows, r"^\(\[federated\.\w+\]\.\[sum:Sales:qk\] \+ \[federated\.\w+\]\.\[sum:Profit:qk\]\)$")
        self.assertIn("[none:Region:nk]", w.findtext("table/cols"))
        f = fold(w)
        self.assertEqual((f.get("class"), f.get("scope")), ("0", "rows"))
        self.assertIn("[sum:Profit:qk]", f.get("field"))
        self.assertIsNone(f.get("synchronized"))  # sales and profit: no common unit given
        hidden = w.findall("table/style/style-rule[@element='axis']/format[@attr='display']")
        self.assertEqual([h.get("field").split(".")[-1] for h in hidden], ["[sum:Profit:qk]"])
        self.assertEqual(line.find("style/style-rule/format[@attr='mark-color']").get("value"), COLOR["accent"])
        self.assertIn("[sum:Sales:qk]", w.find("table/view/computed-sort").get("using"))  # by the bars
        # decisions/165: the bars' values at their ends (084 had them at the base), the bars 70% of a slot
        self.assertEqual(bar.find("style/style-rule[@element='cell']/format[@attr='vertical-align']").get("value"),
                         "top")
        self.assertEqual(bar.find("style/style-rule[@element='mark']/format[@attr='size']").get("value"), "1.4")
        self.assertEqual([r.get("element") for r in bar.find("style")], ["cell", "mark"])
        self.assertIsNone(line.find("style/style-rule[@element='cell']"))

    def test_donut_two_pies_on_one_axis_twice(self):
        w = ws(self.root, "Donut")
        outer, inner = layers(w)
        self.assertEqual([p.find("mark").get("class") for p in (outer, inner)], ["Pie", "Pie"])
        self.assertEqual(outer.get("y-axis-name"), inner.get("y-axis-name"))
        self.assertEqual((outer.get("y-index"), inner.get("y-index")), (None, "1"))
        f = fold(w)
        self.assertEqual((f.get("class"), f.get("synchronized")), ("1", "true"))
        self.assertEqual(len(w.findall("table/style/style-rule[@element='axis']/format[@attr='display']")), 2)
        self.assertEqual(sorted(e.tag for e in outer.find("encodings")), ["color", "tooltip", "wedge-size"])
        self.assertIn("[sum:Sales:qk]", inner.find("encodings/text").get("column"))
        self.assertEqual(inner.find("style/style-rule/format[@attr='mark-color']").get("value"), COLOR["card_bg"])
        self.assertIsNotNone(inner.find("customized-label"))
        self.assertFalse(w.findtext("table/cols"))  # <cols /> as SuperMart's donut

    def test_donut_legend_sheets_beside_it(self):
        """decisions/069: the legend's dots (a Circle per member in its color, fixed size) and its text (a Text mark
        without a color, 'member' over '**value** (share)' in their own colors, from the pane's left), each its own
        sheet with the row headers hidden; the zones: ring, dots, text."""
        dots = ws(self.root, dualaxis.dots_name({"name": "Donut"}))
        pane = dots.find("table/panes/pane")
        self.assertEqual(pane.find("mark").get("class"), "Circle")
        self.assertEqual(pane.find("mark-sizing").get("mark-sizing-setting"), "marks-scaling-off")
        self.assertEqual(pane.find("style/style-rule/format[@attr='size']").get("value"), dualaxis.DOT_SIZE)
        self.assertIn("[none:Category:nk]", pane.find("encodings/color").get("column"))
        text = ws(self.root, dualaxis.legend_name({"name": "Donut"}))
        pane = text.find("table/panes/pane")
        self.assertEqual(pane.find("mark").get("class"), "Text")
        self.assertIsNone(pane.find("encodings/color"))  # a color encoding draws every run in the member's color
        runs = pane.findall("customized-label/formatted-text/run")
        self.assertTrue(all(r.get("fontcolor") for r in runs if r.text != "Æ\n"))
        self.assertIn("(<", "".join(r.text for r in runs))
        self.assertEqual(pane.find("style/style-rule[@element='cell']/format[@attr='text-align']").get("value"), "left")
        for w in (dots, text):
            hidden = w.find("table/style/style-rule[@element='label']/format[@attr='display']")
            self.assertIn("[none:Category:nk]", hidden.get("field"))
        zones = {z.get("name"): z for z in self.root.iter("zone") if z.get("name")}
        donut, dz, tz = zones["Donut"], zones["Donut · Dots"], zones["Donut · Legend"]
        self.assertEqual(int(donut.get("x")) + int(donut.get("w")), int(dz.get("x")))
        self.assertEqual(int(dz.get("x")) + int(dz.get("w")), int(tz.get("x")))
        self.assertGreater(int(donut.get("w")), int(tz.get("w")))  # the legend as wide as its text
        self.assertNotIn("Donut", {c.get("name") for c in self.root.iter("zone") if c.get("type-v2") == "color"})

    def test_ring_sized_from_its_zone(self):
        """decisions/069: the ring is RING_FILL of the zone's shorter side inside its margins, the hole 1.6 / 2.6."""
        outer, inner = layers(ws(self.root, "Donut"))
        size = [float(p.find("style/style-rule/format[@attr='size']").get("value")) for p in (outer, inner)]
        z = next(z for z in self.root.iter("zone") if z.get("name") == "Donut")
        st = {f.get("attr"): int(f.get("value")) for f in z.findall("zone-style/format") if "margin" in f.get("attr")}
        m = {k: st.get(f"margin-{k}", st["margin"]) for k in ("top", "right", "bottom", "left")}
        w = int(z.get("w")) * 1400 // 100000 - m["left"] - m["right"]
        h = int(z.get("h")) * 700 // 100000 - m["top"] - m["bottom"]
        ring = int(min(w, h) * dualaxis.RING_FILL)
        self.assertAlmostEqual(size[0] * PIE_PX_PER_SIZE, ring, delta=0.5)
        self.assertAlmostEqual(size[1] / size[0], 1.6 / 2.6, delta=0.002)

    def test_a_ring_too_small_for_its_total_is_refused(self):
        s = spec()
        s["dashboard"]["grid"] = [["Combo", "Donut", "Lollipop", "Combo 2", "Combo 3"]]
        s["sheets"] += [dict(sheet(s, "Combo"), name=f"Combo {i}") for i in (2, 3)]
        with self.assertRaisesRegex(ValueError, r"Donut 'Donut': its zone leaves \d+x\d+px, a ring of \d+px; it "
                                                r"needs \d+px \(the total '317.333' in its \d+px hole\)"):
            build(s, OUT / "dual_axis_small.twbx", SPEC.parent)

    def test_lollipop_stick_and_circle_across(self):
        w = ws(self.root, "Lollipop")
        stick, dot = layers(w)
        self.assertEqual([p.find("mark").get("class") for p in (stick, dot)], ["Bar", "Circle"])
        self.assertEqual((stick.get("x-index"), dot.get("x-index")), (None, "1"))
        f = fold(w)
        self.assertEqual((f.get("class"), f.get("scope"), f.get("synchronized")), ("1", "cols", "true"))
        self.assertRegex(w.findtext("table/rows"), r"^\(\[federated\.\w+\]\.\[none:Region:nk\] / "
                                                   r"\[federated\.\w+\]\.\[sum:Quantity:ok\]\)$")

    def test_lollipop_value_in_its_header(self):
        """decisions/084 (reference 'Lollipop'): the value a discrete header after the member, as wide as '685' at 9pt
        plus a header's insets, right-aligned in the number format the width was measured in; the circle is not
        labelled (its label stood on it at the pane's edge)."""
        w = ws(self.root, "Lollipop")
        stick, dot = layers(w)
        ok = next(c for c in w.iter("column-instance") if c.get("name") == "[sum:Quantity:ok]")
        self.assertEqual((ok.get("derivation"), ok.get("type")), ("Sum", "ordinal"))
        self.assertIsNone(dot.find("encodings"))
        self.assertEqual(dot.find("style/style-rule/format[@attr='mark-labels-show']").get("value"), "false")
        width = next(f for f in w.iterfind("table/style/style-rule[@element='header']/format[@attr='width']"))
        self.assertTrue(width.get("field").endswith("[sum:Quantity:ok]"))
        from tbuilder.design import HEADER_TEXT_PAD_PX, text_px
        self.assertEqual(int(width.get("value")), text_px("685", 9) + HEADER_TEXT_PAD_PX)
        label = {f.get("attr"): f.get("value") for f in w.iterfind("table/style/style-rule[@element='label']/format")
                 if f.get("field", "").endswith("[sum:Quantity:ok]")}
        self.assertEqual(label, {"text-align": "right", "text-format": "n#,##0;-#,##0"})

    def test_entire_view_for_the_donut(self):
        win = next(w for w in self.root.iter("window") if w.get("class") == "dashboard")
        zoomed = {v.get("name") for v in win.iter("viewpoint") if v.find("zoom") is not None}
        self.assertTrue({"Donut", "Donut · Legend"} <= zoomed)


class SameUnit(unittest.TestCase):
    def test_one_number_format_synchronizes_the_combo(self):
        s = spec()
        c = sheet(s, "Combo")
        c["bar"]["format"] = c["line"]["format"] = "currency_k"
        s["sheets"] = [c]
        s["dashboard"]["grid"] = [["Combo"]]
        root = twb(build(s, OUT / "dual_axis_sync.twbx", SPEC.parent))
        self.assertEqual(fold(ws(root, "Combo")).get("synchronized"), "true")


class Expected(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exp = expected.compute(spec(), CSV)

    def test_both_layers_of_the_combo(self):
        sales, profit = total("Sales", "Region"), total("Profit", "Region")
        for k, v in self.exp["Combo"].items():
            self.assertAlmostEqual(v["SUM(Sales)"], sales[k], 2)
            self.assertAlmostEqual(v["SUM(Profit)"], profit[k], 2)

    def test_donut_total_and_shares(self):
        sales = total("Sales", "Category")
        self.assertAlmostEqual(self.exp["Donut · Total"], sum(sales.values()), 2)
        legend = self.exp["Donut · Legend"]
        self.assertAlmostEqual(sum(v["share"] for v in legend.values()), 1.0, 9)
        for k, v in legend.items():
            self.assertAlmostEqual(v["value"], sales[k], 2)
            self.assertAlmostEqual(v["share"], sales[k] / sum(sales.values()), 9)

    def test_lollipop(self):
        q = total("Quantity", "Region")
        self.assertEqual(self.exp["Lollipop"], {k: q[k] for k in sorted(q)})

    def test_reconcile_entries(self):
        ents = reconcile.entries(spec(), self.exp)
        donut = [e for e in ents if e["sheet"] == "Donut"]
        self.assertEqual(sorted({e.get("part", "") for e in donut}), ["", "share", "total"])
        self.assertTrue(all(e["pct"] for e in donut if e.get("part") == "share"))
        combo = [e for e in ents if e["sheet"] == "Combo"]
        self.assertEqual(len(combo), 8)


class ReconcileLabel(unittest.TestCase):
    """decisions/069: the donut's measure label is the caption under its total. As a tag of all its entries it named
    other blocks' numbers: ITSM 'Software Incidents Incidents by category 787' went to the donut's total, 'Email
    Incidents ... 253' to its [Email] slice (Email is a channel and a category)."""

    def spec(self):
        s = spec()
        s["sheets"] = [dict(sheet(s, "Donut"), measure={"field": "Sales", "label": "orders"}),
                       {"name": "By Category", "type": "bar", "dimension": "Category",
                        "measure": {"field": "Quantity"}},
                       {"name": "By Region", "type": "bar", "dimension": "Region", "measure": {"field": "Quantity"}}]
        s["dashboard"]["grid"] = [["Donut", "By Category", "By Region"]]
        return s

    def page(self):
        def chart(title, series, points):
            return {"lib": "chartjs", "canvas": 0, "title": title, "heading": None,
                    "points": [{"label": k, "series": series, "value": v} for k, v in points]}
        return {"texts": [{"text": "317,333", "box": [0, 0, 10, 10], "up": ["317,333", "317,333 orders"]}],
                "canvases": [{"box": [0, 0, 10, 10], "data": True}],
                "charts": [chart("Orders by category", "Orders", [("Furniture", "861"), ("Office", "783"),
                                                                    ("Tech", "900")]),
                           chart("Orders by region", "Orders", [("West", "636"), ("East", "685")]),
                           chart("Sales mix", "Sales", [("Furniture", "105263"), ("Tech", "103853")])]}

    def test_the_label_names_only_the_total(self):
        r = reconcile.check(self.spec(), SPEC.parent, self.page())
        got = {f["number"]: (f["status"], f.get("workbook", "")) for f in r["facts"]}
        self.assertTrue(r["ok"], got)
        self.assertTrue(got["317,333"][1].startswith("Donut total"), got)
        self.assertTrue(got["861"][1].startswith("By Category [Furniture]"), got)
        self.assertTrue(got["636"][1].startswith("By Region [West]"), got)
        self.assertTrue(got["105263"][1].startswith("Donut [Furniture]"), got)

    def test_a_mutated_slice_is_still_caught(self):
        page = self.page()
        page["charts"][2]["points"][0]["value"] = "105999"
        got = {f["number"]: f for f in reconcile.check(self.spec(), SPEC.parent, page)["facts"]}
        self.assertEqual(got["105999"]["status"], "mismatch")


class Refusals(unittest.TestCase):
    def build(self, s):
        return build(s, OUT / "dual_axis_bad.twbx", SPEC.parent)

    def test_combo_of_one_measure(self):
        s = spec()
        sheet(s, "Combo")["line"] = {"field": "Sales"}
        with self.assertRaisesRegex(ValueError, "same measure"):
            self.build(s)

    def test_table_calc(self):
        s = spec()
        sheet(s, "Lollipop")["measure"]["table_calc"] = {"type": "percent_of_total"}
        with self.assertRaisesRegex(ValueError, "table calculations on a lollipop"):
            self.build(s)

    def test_unknown_key(self):
        from tbuilder.spec import SpecError
        s = spec()
        sheet(s, "Donut")["color"] = "Region"
        with self.assertRaises(SpecError):
            self.build(s)


class Lint(unittest.TestCase):
    def test_donut_of_more_than_five_slices(self):
        s = spec()
        s["datasource"]["path"] = "../data/sample/sales_products.csv"
        sheet(s, "Donut")["dimension"] = "Product"
        found = [f for f in lint(s, SPEC.parent) if f.rule == "C2" and "Donut" in f.where]
        self.assertTrue(found and found[0].level == "warn", found)

    def test_clean(self):
        self.assertEqual([str(f) for f in lint(spec(), SPEC.parent) if f.level != "info"], [])


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build_file(SPEC, OUT / "dual_axis_gate.twbx")

    def assertCaught(self, fn, text):
        issues = [str(i) for i in gate.run(repack(fn, source=self.path))]
        self.assertTrue(any(i.startswith("[dual-axis]") and text in i for i in issues), issues)

    def test_clean(self):
        self.assertEqual(gate.run(self.path), [])

    def test_one_unit_not_synchronized(self):
        self.assertCaught(lambda r: fold(ws(r, "Lollipop")).attrib.pop("synchronized"), "not synchronized")

    def test_second_layer_without_mark_class(self):
        self.assertCaught(lambda r: layers(ws(r, "Combo"))[1].find("mark").set("class", "Automatic"),
                          "no mark class")

    def test_second_layer_without_mark(self):
        def f(r):
            p = layers(ws(r, "Lollipop"))[1]
            p.remove(p.find("mark"))
        self.assertCaught(f, "no mark class")

    def test_donut_without_total(self):
        def f(r):
            p = layers(ws(r, "Donut"))[1]
            p.remove(p.find("encodings"))
        self.assertCaught(f, "donut without its total")

    def test_missing_layer_pane(self):
        def f(r):
            panes = ws(r, "Combo").find("table/panes")
            panes.remove(layers(ws(r, "Combo"))[1])
        self.assertCaught(f, "no pane for the layer")

    def test_ring_larger_than_its_panel(self):
        """decisions/069: ITSM's 208px ring (size 2.6) in a 132px panel was cut at both edges."""
        def f(r):
            layers(ws(r, "Donut"))[0].find("style/style-rule/format[@attr='size']").set("value", "9")
        self.assertCaught(f, "cuts the ring")

    def test_combo_bar_values_at_the_base(self):
        """decisions/165: golden_dual_axis of 084, '85,565' inside its bar at the base."""
        def f(r):
            layers(ws(r, "Combo"))[0].find("style/style-rule/format[@attr='vertical-align']").set("value", "bottom")
        self.assertCaught(f, "off their ends")

    def test_combo_bar_values_mid_bar(self):
        def f(r):
            layers(ws(r, "Combo"))[0].find("style/style-rule/format[@attr='vertical-align']").set("value", "center")
        self.assertCaught(f, "off their ends")

    def test_lollipop_circle_labelled(self):
        """decisions/084: golden_dual_axis before 084, '685' on its circle at the pane's edge."""
        def f(r):
            layers(ws(r, "Lollipop"))[1].find("style/style-rule/format[@attr='mark-labels-show']").set("value", "true")
        self.assertCaught(f, "circle is labelled")

    def test_fold_without_a_measure_before_it(self):
        def f(r):
            w = ws(r, "Combo")
            w.find("table/rows").text = w.find("table/rows").text.split(" + ")[1].rstrip(")")
        self.assertCaught(f, "no measure before it")


if __name__ == "__main__":
    unittest.main()
