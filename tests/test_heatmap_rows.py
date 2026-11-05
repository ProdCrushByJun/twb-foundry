"""Heatmap with two row fields and outlier labels (decisions/171): the shelf, the header widths, the bold outer
header, the label calc on Text, the refusals, the expected keys and the gate mutations. The gap between the groups and
the margins beside two row fields (decisions/186)."""
import csv
import json
import unittest
from collections import defaultdict

from tbuilder import expected, gate, heatmap
from tbuilder.build import build, build_file
from tbuilder.design import COLOR, FONT, HEADER_TEXT_PAD_PX, text_px
from test_gate import repack, ws
from test_heatmap_v2 import fmt, twb
from test_roundtrip import OUT, ROOT

SPEC = ROOT / "specs" / "heatmap_rows.json"
CSV = ROOT / "data" / "sample" / "sales_2y.csv"
NAME = "Margin Map"
LABEL = heatmap.label_name({"name": NAME})
TOTALS = heatmap.part_name({"name": NAME}, "rows")
ROWS = list(csv.DictReader(CSV.open(encoding="utf-8")))


def spec():
    return json.loads(SPEC.read_text(encoding="utf-8"))


def sheet(s):
    return next(x for x in s["sheets"] if x["name"] == NAME)


def label_col(root):
    return next(c for c in root.iter("column") if c.get("caption") == LABEL)


class Built(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build_file(SPEC, OUT / "heatmap_rows_test.twbx")
        cls.root = twb(cls.path)
        cls.ws = ws(cls.root, NAME)

    def test_rows_nest_outer_over_inner(self):
        rows = self.ws.find("table/rows").text
        self.assertRegex(rows, r"^\(\[[^]]+\]\.\[none:Region:nk\] / \[[^]]+\]\.\[none:Category:nk\]\)$")

    def test_each_row_field_has_a_header_wide_enough(self):
        values = {f: {r[f] for r in ROWS} for f in ("Region", "Category")}
        for field, bold in (("Region", True), ("Category", False)):
            w = int(fmt(self.root, NAME, "header", "width", f":{field}:"))
            longest = max(text_px(v, FONT["table_header"], bold=bold) for v in values[field])
            self.assertGreaterEqual(w, longest + HEADER_TEXT_PAD_PX, field)

    def test_the_outer_header_is_bold_the_inner_is_not(self):
        self.assertEqual(fmt(self.root, NAME, "label", "font-weight", ":Region:"), "bold")
        self.assertIsNone(fmt(self.root, NAME, "label", "font-weight", ":Category:"))

    def test_the_label_calc_is_on_text_and_the_measure_on_color(self):
        enc = self.ws.find("table/panes/pane/encodings")
        col = label_col(self.root)
        name = col.get("name").strip("[]")
        self.assertIn(name, enc.find("text").get("column"))
        self.assertNotIn(name, enc.find("color").get("column"))
        m = next(c for c in self.root.iter("column") if c.get("caption") == "Margin").get("name")
        self.assertEqual(col.find("calculation").get("formula"), f"IF {m} >= 10 THEN {m} END")

    def test_the_label_reads_as_the_measure(self):
        margin = next(c for c in self.root.iter("column") if c.get("caption") == "Margin")
        self.assertEqual(label_col(self.root).get("default-format"), margin.get("default-format"))

    def test_a_gap_between_the_outer_groups(self):  # Desktop's form: golden_bullet_2025_1's Regions
        div = {f.get("attr"): f.get("value") for f in self.ws.findall("table/style/style-rule[@element='table-div']/format")
               if f.get("scope") == "rows"}
        self.assertEqual(div, {"line-visibility": "on", "stroke-size": str(heatmap.GROUP_GAP_PX),
                               "stroke-color": COLOR["card_bg"], "line-pattern-only": "solid", "div-level": "1"})

    def test_one_row_field_has_no_gap(self):
        s = spec()
        sheet(s).update(rows="Region")
        sheet(s).pop("color")  # its fixed range is for the finer grain
        root = twb(build(s, OUT / "heatmap_rows_one.twbx", SPEC.parent))
        self.assertIsNone(fmt(root, NAME, "table-div", "div-level", ""))


class Margins(unittest.TestCase):
    """The row totals beside two row fields, with date columns (a period each, not a date each)."""

    @classmethod
    def setUpClass(cls):
        cls.spec = spec()
        sheet(cls.spec)["margins"] = {"rows": "bar"}
        cls.path = build(cls.spec, OUT / "heatmap_rows_margins.twbx", SPEC.parent)
        cls.root = twb(cls.path)
        cls.heat, cls.bars = ws(cls.root, NAME), ws(cls.root, TOTALS)

    def test_the_bars_nest_as_the_heatmap(self):
        self.assertEqual(self.bars.find("table/rows").text, self.heat.find("table/rows").text)

    def test_their_row_headers_are_hidden(self):
        for field in (":Region:", ":Category:"):
            self.assertEqual(fmt(self.root, TOTALS, "label", "display", field), "false", field)

    def test_the_height_is_on_the_inner_field_and_the_same(self):
        h = fmt(self.root, NAME, "cell", "height", ":Category:")
        self.assertGreaterEqual(int(h), heatmap.HEATMAP_CELL_MIN_PX)
        self.assertEqual(fmt(self.root, TOTALS, "cell", "height", ":Category:"), h)

    def test_the_same_gap(self):
        self.assertEqual(fmt(self.root, TOTALS, "table-div", "div-level", ""), "1")

    def test_a_cell_is_as_wide_as_a_quarter_not_as_a_date(self):
        self.assertGreater(int(fmt(self.root, NAME, "cell", "width", ":Order Date:")), 50)

    def test_expected_keys_are_outer_inner(self):
        exp = expected.compute(self.spec, CSV)[TOTALS]
        self.assertEqual(set(exp), {f"{r['Region']} | {r['Category']}" for r in ROWS})
        for k, v in exp.items():
            rows = [r for r in ROWS if f"{r['Region']} | {r['Category']}" == k]
            self.assertAlmostEqual(v, sum(float(r["Profit"]) for r in rows) / sum(float(r["Sales"]) for r in rows) * 100,
                                   places=6, msg=k)

    def test_both_margins(self):
        s = spec()
        h = sheet(s)
        h.update(cols="Half", margins={"rows": "bar", "cols": "bar"})
        h.pop("date_level")
        h.pop("color")
        s.setdefault("calcs", []).append({"name": "Half", "formula": "IF MONTH([Order Date]) <= 6 THEN 'H1' ELSE 'H2' END"})
        path = build(s, OUT / "heatmap_rows_both.twbx", SPEC.parent)
        self.assertEqual(gate.run(path, spec=s), [])

    def _issues(self, fn):
        return [str(i) for i in gate.run(repack(fn, source=self.path))]

    def test_gate_clean(self):
        self.assertEqual(gate.run(self.path), [])

    def test_gate_the_bars_on_the_outer_field_only(self):
        def f(r):
            el = ws(r, TOTALS).find("table/rows")
            el.text = el.text.strip("()").split(" / ")[0]
        self.assertTrue(any("rows differ" in i for i in self._issues(f)))

    def test_gate_another_height(self):
        def f(r):
            el = next(x for x in ws(r, TOTALS).findall("table/style/style-rule[@element='cell']/format")
                      if x.get("attr") == "height")
            el.set("value", str(int(el.get("value")) + 2))
        self.assertTrue(any("row height" in i for i in self._issues(f)))

    def test_gate_no_gap_on_the_bars(self):
        def f(r):
            style = ws(r, TOTALS).find("table/style")
            style.remove(style.find("style-rule[@element='table-div']"))
        self.assertTrue(any("gap between groups" in i for i in self._issues(f)))


class Calcs(unittest.TestCase):
    def test_a_plain_field_is_aggregated(self):
        s = {"sheets": [{"name": "H", "type": "heatmap", "rows": "Region", "cols": "Segment",
                         "measure": {"field": "Sales", "agg": "avg"}, "label": {"min": 250}}]}
        self.assertEqual(heatmap.calcs(s)[0]["formula"], "IF AVG([Sales]) >= 250 THEN AVG([Sales]) END")

    def test_no_label_no_calc(self):
        s = spec()
        sheet(s).pop("label")
        self.assertEqual(heatmap.calcs(s), [])


class Expected(unittest.TestCase):
    def test_keys_are_outer_inner_col_and_labels_only_from_min(self):
        exp = expected.compute(spec(), CSV)
        sales, profit = defaultdict(float), defaultdict(float)
        for r in ROWS:
            k = f"{r['Region']} | {r['Category']} | {r['Order Date'][:4]}-Q{(int(r['Order Date'][5:7]) - 1) // 3 + 1}"
            sales[k] += float(r["Sales"])
            profit[k] += float(r["Profit"])
        cells = exp[NAME]
        self.assertEqual(len(cells), 4 * 3 * 8)  # two years of quarters
        for k, v in cells.items():
            self.assertAlmostEqual(v, profit[k] / sales[k] * 100, places=6, msg=k)
        labels = {k: v for k, v in cells.items() if v >= 10}
        self.assertTrue(labels and len(labels) < len(cells))


class Refusals(unittest.TestCase):
    def assertRefused(self, edit, text):
        s = spec()
        edit(sheet(s))
        with self.assertRaises(ValueError) as cm:
            build(s, OUT / "heatmap_rows_refused.twbx", SPEC.parent)
        self.assertIn(text, str(cm.exception))

    def test_the_same_field_twice(self):
        self.assertRefused(lambda h: h.update(rows=["Region", "Region"]), "must be different fields")

    def test_a_row_field_on_cols(self):
        self.assertRefused(lambda h: h.update(rows=["Region", "Order Date"]), "must be different fields")

    def test_label_of_a_table_calc(self):
        self.assertRefused(lambda h: h["measure"].update(table_calc={"type": "running_total"}), "label min")

    def test_too_narrow_a_cell(self):  # two row headers keep their widths: no wrapping, a refusal
        s = spec()
        s["dashboard"].update(width=700, theme="flat")  # in a card the cell is narrower still: a table that scrolls
        with self.assertRaises(ValueError) as cm:
            build(s, OUT / "heatmap_rows_refused.twbx", SPEC.parent)
        self.assertIn("give the cell more width", str(cm.exception))


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build_file(SPEC, OUT / "heatmap_rows_gate.twbx")
        cls.exp = expected.compute(spec(), CSV)

    def issues(self, fn):
        return [str(i) for i in gate.run(repack(fn, source=self.path), expected=self.exp)]

    def test_clean(self):
        self.assertEqual(gate.run(self.path, expected=self.exp), [])

    def test_bold_of_a_field_not_on_the_sheet(self):
        def f(r):
            el = ws(r, NAME).find("table/style/style-rule[@element='label']/format")
            el.set("field", el.get("field").replace("none:Region:nk", "none:Segment:nk"))
        self.assertTrue(self.issues(f))

    def test_label_calc_dropped_from_the_datasource(self):
        def f(r):
            for ds in r.iter("datasource"):
                for c in list(ds.findall("column")):
                    if c.get("caption") == LABEL:
                        ds.remove(c)
        self.assertTrue(self.issues(f))


if __name__ == "__main__":
    unittest.main()
