"""Selected vs benchmark, line-end labels, date line, reference band, small multiples by measure (decisions/043).

Run: python -m unittest discover -s tests
"""
import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import benchmark, expected, gate, reconcile, reflines, registry
from tbuilder.build import build
from tbuilder.spec import SpecError, validate
from test_roundtrip import ROOT, SPECS

SPEC = json.loads((SPECS / "benchmark.json").read_text(encoding="utf-8"))
FILTER_SPEC = json.loads((SPECS / "benchmark_filter.json").read_text(encoding="utf-8"))
CSV = ROOT / "data" / "sample" / "sales_2y.csv"


def rows():
    import csv
    with open(CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def mutate(fn, base=SPEC):
    spec = copy.deepcopy(base)
    fn(spec)
    return spec


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def built(spec, name="benchmark_test"):
    out = build(spec, ROOT / "out" / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return etree.fromstring(z.read(out.stem + ".twb")), out


def ws(root, name):
    return next(w for w in root.iter("worksheet") if w.get("name") == name)


class Expected(unittest.TestCase):
    """The benchmark is the average member per period over all rows; the selected line the member's own."""

    @classmethod
    def setUpClass(cls):
        cls.got = expected.compute(SPEC, CSV)
        cls.rows = rows()

    def by_hand(self, month, region=None, field="Sales"):
        vals = [float(r[field]) for r in self.rows if r["Order Date"].startswith(month)
                and (region is None or r["Region"] == region)]
        return vals

    def test_selected_is_the_parameter_member(self):
        jan = self.got["Compare · Sales"]["2024-01"]
        self.assertAlmostEqual(jan["West"], sum(self.by_hand("2024-01", "West")), 6)

    def test_benchmark_is_the_average_region(self):
        jan = self.got["Compare · Sales"]["2024-01"]
        regions = {r["Region"] for r in self.rows if r["Order Date"].startswith("2024-01")}
        self.assertAlmostEqual(jan["All regions avg"], sum(self.by_hand("2024-01")) / len(regions), 6)

    def test_avg_benchmark_is_the_average_row(self):
        jan = self.got["Compare · Avg sale"]["2024-01"]
        allrows, west = self.by_hand("2024-01"), self.by_hand("2024-01", "West")
        self.assertAlmostEqual(jan["All regions avg"], sum(allrows) / len(allrows), 6)
        self.assertAlmostEqual(jan["West"], sum(west) / len(west), 6)

    def test_parameter_moves_the_selected_line_only(self):
        other = expected.compute(SPEC, CSV, {"Select Region": "East"})
        a, b = self.got["Compare · Sales"]["2024-01"], other["Compare · Sales"]["2024-01"]
        self.assertEqual(a["All regions avg"], b["All regions avg"])
        self.assertAlmostEqual(b["East"], sum(self.by_hand("2024-01", "East")), 6)

    def test_filter_selects_and_the_benchmark_ignores_it(self):
        north = expected.compute(FILTER_SPEC, CSV)["Selected"]
        south = expected.compute(FILTER_SPEC, CSV, where={"Region": ["South"]})["Selected"]
        self.assertIn("North", north["2024-Q1"])
        self.assertAlmostEqual(north["2024-Q1"]["Organization"], south["2024-Q1"]["Organization"], 6)
        self.assertNotEqual(north["2024-Q1"]["North"], south["2024-Q1"]["South"])

    def test_line_ends(self):
        ends = self.got[benchmark.ends_record("Compare · Sales")]
        marks = self.got["Compare · Sales"]
        self.assertEqual(ends["West"], {"last": marks["2025-12"]["West"]})
        both = self.got[benchmark.ends_record("Total")]["Sales"]
        self.assertEqual(both, {"first": self.got["Total"]["2024-01"], "last": self.got["Total"]["2025-12"]})

    def test_band_edges_are_numbers(self):
        self.assertEqual(self.got[reflines.record("East")], {"Target range from": 3000, "Target range to": 5000})
        moved = expected.compute(SPEC, CSV, {"Target Low": 4000})
        self.assertEqual(moved[reflines.record("East")]["Target range from"], 4000)

    def test_date_line_has_no_number_record(self):
        self.assertNotIn(reflines.record("Compare · Sales"), self.got)

    def test_reconcile_entries(self):
        es = reconcile.entries(SPEC, self.got)
        parts = {(e["sheet"], e.get("part")) for e in es}
        self.assertIn(("Compare · Sales", "West"), parts)
        self.assertIn(("Compare · Sales", "All regions avg"), parts)
        self.assertIn(("Total", "line first"), parts)
        self.assertIn(("East", "reference line"), parts)


class Repeat(unittest.TestCase):
    def test_copies_per_measure_in_a_2x2_group(self):
        out = registry.expand(SPEC)
        names = [s["name"] for s in out["sheets"]]
        self.assertEqual(names[:4], ["Compare · Sales", "Compare · Profit", "Compare · Quantity", "Compare · Avg sale"])
        self.assertEqual(out["dashboard"]["grid"][0], [{"rows": [["Compare · Sales", "Compare · Profit"],
                                                                 ["Compare · Quantity", "Compare · Avg sale"]]}])

    def test_titles_and_one_legend(self):
        out = registry.expand(SPEC)
        a, b = sheet(out, "Compare · Sales"), sheet(out, "Compare · Profit")
        self.assertEqual(a["title"], "[Select Region] vs all regions: **Sales**")
        self.assertIn("subtitle", a)
        self.assertNotIn("subtitle", b)

    def test_without_columns_side_by_side(self):
        spec = mutate(lambda s: sheet(s, "Compare").pop("columns"))
        self.assertEqual(len(registry.expand(spec)["dashboard"]["grid"][0]), 4)

    def test_repeat_with_measure_is_refused(self):
        spec = mutate(lambda s: sheet(s, "Compare").update(measure={"field": "Sales"}))
        with self.assertRaises(SpecError):
            validate(spec)

    def test_repeat_twice_the_same_label(self):
        spec = mutate(lambda s: sheet(s, "Compare").update(repeat=[{"field": "Sales"}, {"field": "Sales"}]))
        with self.assertRaisesRegex(ValueError, "names a measure twice"):
            registry.expand(spec)


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.path = built(SPEC)

    def test_measure_values_colored_by_measure_names(self):
        w = ws(self.root, "Compare · Sales")
        self.assertTrue(w.findtext("table/rows").endswith("[Multiple Values]"))
        self.assertTrue(w.find("table/panes/pane/encodings/color").get("column").endswith("[:Measure Names]"))
        members = [g.get("member") for g in w.iterfind("table/view/filter/groupfilter/groupfilter")]
        self.assertEqual(len(members), 2)
        sort = [b.text for b in w.iterfind("table/view/manual-sort/dictionary/bucket")]
        self.assertEqual(sort, members)  # the selected line first: drawn on top

    def test_benchmark_is_fixed_on_the_period(self):
        cols = {c.get("caption"): c for c in self.root.find("datasources")[1].findall("column")}
        f = cols["Compare · Sales · Benchmark"].find("calculation").get("formula")
        self.assertTrue(f.startswith("{FIXED [Calculation_") and "COUNTD([Region])" in f)
        self.assertEqual(cols["Compare · Sales · Period"].find("calculation").get("formula"),
                         "DATETRUNC('month', [Order Date])")
        self.assertIn("[Parameters].[Parameter 1]", cols["Compare · Sales · Selected"].find("calculation").get("formula"))

    def test_palette_accent_and_muted(self):
        enc = self.root.find("datasources")[1].find("style/style-rule/encoding[@field='[:Measure Names]']")
        colors_ = {m.find("bucket").text: m.get("to") for m in enc.findall("map")}
        w = ws(self.root, "Compare · Sales")
        sel, bench = [b.text for b in w.iterfind("table/view/manual-sort/dictionary/bucket")]
        self.assertEqual((colors_[sel], colors_[bench]), ("#4e79a7", "#898989"))

    def test_line_end_labels(self):
        def fmt(name):
            rule = ws(self.root, name).find("table/panes/pane/style/style-rule[@element='mark']")
            return {f.get("attr"): f.get("value") for f in rule.findall("format")}
        self.assertEqual(fmt("Compare · Sales")["mark-labels-line-first"], "false")
        self.assertEqual(fmt("Total")["mark-labels-line-first"], "true")
        self.assertEqual(fmt("Total")["mark-labels-mode"], "line-ends")

    def test_date_line_on_the_date_axis(self):
        rl = ws(self.root, "Compare · Sales").find("table/panes/pane/reference-line")
        self.assertEqual(rl.get("value"), "#2025-07-01 00:00:00#")
        self.assertTrue(rl.get("axis-column").endswith("[tmn:Order Date:qk]"))
        self.assertIsNone(rl.get("tooltip-type"))  # Desktop 2025.1 rejects SOC's attribute

    def test_band_is_two_edges_with_fills(self):
        w = ws(self.root, "Total")
        lines = w.findall("table/panes/pane/reference-line")
        self.assertEqual([(rl.get("id"), rl.get("value")) for rl in lines][:2],
                         [("refline0", "13000.0"), ("refline1", "16000.0")])
        fills = {f.get("id"): f.get("value") for f in w.iterfind(
            "table/style/style-rule[@element='refline']/format[@attr='fill-above']")}
        self.assertEqual((fills["refline0"], fills["refline1"]), ("#edeff4", "#ffffff"))

    def test_constant_on_measure_values_names_the_axis(self):
        """Desktop 2025.1 Save As rewrites a constant's value-column on [Multiple Values] to the axis (061)."""
        rl = ws(self.root, "East").findall("table/panes/pane/reference-line")[1]
        self.assertEqual((rl.get("formula"), rl.get("value")), ("constant", "5000.0"))
        self.assertTrue(rl.get("axis-column").endswith("[Multiple Values]"))
        self.assertEqual(rl.get("value-column"), rl.get("axis-column"))

    def test_manual_sort_comes_with_its_manifest_flag(self):
        self.assertIsNotNone(self.root.find("document-format-change-manifest/SortTagCleanup"))


class Refusals(unittest.TestCase):
    def assertRefused(self, spec, text, base=None):
        with self.assertRaisesRegex(ValueError, text):
            build(spec, ROOT / "out" / "benchmark_refused.twbx", SPECS)

    def test_benchmark_with_color(self):
        self.assertRefused(mutate(lambda s: sheet(s, "East").update(color="Category")), "remove 'color'")

    def test_unknown_select_value(self):
        self.assertRefused(mutate(lambda s: sheet(s, "East")["benchmark"].update(select="Mars")),
                           "not a value of 'Region'")

    def test_select_parameter_must_be_a_string_list(self):
        self.assertRefused(mutate(lambda s: sheet(s, "East")["benchmark"].update(select={"parameter": "Target Low"})),
                           "must be a string parameter")

    def test_agg_max(self):
        self.assertRefused(mutate(lambda s: sheet(s, "East")["measure"].update(agg="max")), "agg sum or avg")

    def test_other_filter_must_be_context(self):
        spec = mutate(lambda s: s["filters"][1].pop("context"), FILTER_SPEC)
        self.assertRefused(spec, "make that filter")

    def test_filter_on_field_with_a_value_select(self):
        spec = mutate(lambda s: s["sheets"][0]["benchmark"].update(select="North"), FILTER_SPEC)
        self.assertRefused(spec, "would cut the selected line")

    def test_select_filter_needs_one_value(self):
        spec = mutate(lambda s: s["filters"][0].update(default=["North", "South"]), FILTER_SPEC)
        self.assertRefused(spec, "one default value")

    def test_avg_line_on_a_benchmark(self):
        self.assertRefused(mutate(lambda s: sheet(s, "East").update(reference={"type": "avg"})),
                           "avg / median line over a benchmark")

    def test_band_from_above_to(self):
        self.assertRefused(mutate(lambda s: sheet(s, "Total")["reference"][0].update({"from": 17000})),
                           "must be below 'to'")

    def test_band_parameter_above_to(self):
        self.assertRefused(mutate(lambda s: sheet(s, "East")["reference"].update(to=2500)), "must be below 'to'")

    def test_date_line_on_a_bar(self):
        spec = mutate(lambda s: s["sheets"].append(
            {"name": "Bars", "type": "bar", "dimension": "Region", "measure": {"field": "Sales"},
             "reference": {"type": "date", "value": "2025-01-01"}}) or s["dashboard"]["grid"].append(["Bars"]))
        self.assertRefused(spec, "date line stands on a date axis")

    def test_bad_date(self):
        spec = mutate(lambda s: sheet(s, "Compare").update(reference={"type": "date", "value": "2025-13-01"}))
        self.assertRefused(spec, "not a YYYY-MM-DD date")


class GateCatchesBenchmarks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.path = built(SPEC, "benchmark_gate")

    def mutant(self, fn):
        with zipfile.ZipFile(self.path) as src:
            members = {n: src.read(n) for n in src.namelist()}
        name = next(n for n in members if n.endswith(".twb"))
        root = etree.fromstring(members[name])
        fn(root)
        members[name] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
        path = Path(tempfile.mkdtemp()) / "mutant.twbx"
        with zipfile.ZipFile(path, "w") as z:
            for n, b in members.items():
                z.writestr(n, b)
        return path

    def assertCaught(self, fn, check, text):
        issues = [str(i) for i in gate.run(self.mutant(fn)) if i.check == check]
        self.assertTrue(any(text in i for i in issues), f"expected [{check}] ~ '{text}', got {issues}")

    def test_generated_passes(self):
        self.assertEqual(gate.run(self.path), [])

    def test_benchmark_without_lod(self):
        def m(root):
            for c in root.iter("column"):
                if c.get("caption") == "East · Benchmark":
                    c.find("calculation").set("formula", "[Sales] / 4")
        self.assertCaught(m, "benchmark", "no FIXED LOD")

    def test_benchmark_exclude_is_not_enough(self):
        def m(root):
            for c in root.iter("column"):
                if c.get("caption") == "East · Benchmark":
                    c.find("calculation").set("formula", "{EXCLUDE [Region] : SUM([Sales])}")
        self.assertCaught(m, "benchmark", "no FIXED LOD")

    def test_band_from_above_to(self):
        def m(root):
            rl = ws(root, "Total").find("table/panes/pane/reference-line")
            rl.set("value", "17000.0")
        self.assertCaught(m, "reflines", "'from' 17000 is not below 'to' 16000")

    def test_band_parameter_above_to(self):
        def m(root):
            for c in root.find("datasources")[0].findall("column"):
                if c.get("caption") == "Target Low":
                    c.set("value", "5500")
        self.assertCaught(m, "reflines", "'from' 5500 is not below 'to' 5000")

    def test_band_without_its_top_edge(self):
        def m(root):
            pane = ws(root, "Total").find("table/panes/pane")
            pane.remove(pane.findall("reference-line")[1])
            rule = ws(root, "Total").find("table/style/style-rule[@element='refline']")
            for f in rule.findall("format[@id='refline1']"):
                rule.remove(f)
        self.assertCaught(m, "reflines", "has no 'to' edge")

    def test_date_line_not_on_a_date_axis(self):
        def m(root):
            rl = ws(root, "Compare · Sales").find("table/panes/pane/reference-line")
            rl.set("axis-column", rl.get("axis-column").replace("[tmn:Order Date:qk]", "[Multiple Values]"))
        self.assertCaught(m, "reflines", "not on a continuous date axis")

    def test_tooltip_type_on_a_line(self):
        self.assertCaught(lambda root: ws(root, "Compare · Sales").find("table/panes/pane/reference-line").set(
            "tooltip-type", "none"), "reflines", "tooltip-type")

    def test_manual_sort_without_flag(self):
        def m(root):
            man = root.find("document-format-change-manifest")
            man.remove(man.find("SortTagCleanup"))
        self.assertCaught(m, "manifest", "<manual-sort> without the manifest flag SortTagCleanup")


if __name__ == "__main__":
    unittest.main()
