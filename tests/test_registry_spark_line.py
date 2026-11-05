"""Registry line spark (roadmap 153, decisions/153): the measure per period as a line in each row on a sheet of its own
right of the registry, an independent axis per row, the last period a dot (as in the references)."""
import copy
import csv
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from pathlib import Path

from tbuilder import gate, registry, sparkline
from tbuilder.build import build
from tbuilder.expected import compute
from test_roundtrip import SPECS

SPEC = json.loads((SPECS / "registry_spark_line.json").read_text(encoding="utf-8"))
CSV = SPECS / SPEC["datasource"]["path"]
OUT = Path(__file__).resolve().parent.parent / "out" / "registry_spark_line_test.twbx"
PART = "Regions · Monthly sales"


def built(spec):
    out = build(spec, OUT, SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def mutate(fn, spec=SPEC):
    spec = copy.deepcopy(spec)
    fn(spec)
    return spec


def reg(spec):
    return spec["sheets"][0]


def spark(spec):
    return reg(spec)["columns"][-1]


def monthly():
    """An independent sum per region and month from the CSV."""
    by = defaultdict(float)
    with open(CSV, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            by[(r["Region"], r["Order Date"][:7])] += float(r["Sales"])
    return by


class Numbers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = compute(SPEC, CSV)
        cls.by = monthly()

    def test_line_is_the_monthly_sums(self):
        line = self.got[PART]
        months = [f"{2024 + i // 12}-{i % 12 + 1:02d}" for i in range(24)]
        self.assertEqual(len(line), 4 * 24)
        for key, v in line.items():
            region, month = key.split(" | ")
            self.assertIn(month, months)
            self.assertAlmostEqual(v, self.by[(region, month)], places=2)

    def test_last_period_is_the_dot(self):
        for region, row in self.got["Regions"].items():
            self.assertAlmostEqual(row["Monthly sales"], self.by[(region, "2025-12")], places=2)

    def test_periods_bound_the_line(self):
        spec = mutate(lambda s: spark(s)["spark"].update({"from": "2025-07-01", "count": 3}))
        line = compute(spec, CSV)[PART]
        self.assertEqual({k.split(" | ")[1] for k in line}, {"2025-07", "2025-08", "2025-09"})
        for region, row in compute(spec, CSV)["Regions"].items():
            self.assertAlmostEqual(row["Monthly sales"], self.by[(region, "2025-09")], places=2)


class Calcs(unittest.TestCase):
    def test_generated(self):
        got = {c["name"]: c["formula"] for c in registry.calcs(SPEC, set())}
        self.assertEqual(got[f"{PART} · In Periods"], "DATETRUNC('month', [Order Date]) >= #2024-01-01# AND "
                                                       "DATETRUNC('month', [Order Date]) <= #2025-12-01#")
        self.assertEqual(got[f"{PART} · Last"], "IF DATETRUNC('month', [Order Date]) = #2025-12-01# THEN [Sales] END")
        self.assertNotIn(f"{PART} · Cell", got)  # not a cell of the registry's sheet
        self.assertNotIn(f"{PART} · Spark", got)

    def test_glyphs_on_request(self):
        spec = mutate(lambda s: spark(s)["spark"].update({"count": 8, "form": "glyphs"}))
        self.assertFalse(sparkline.is_line(spark(spec)))
        self.assertIn(f"{PART} · Spark", {c["name"] for c in registry.calcs(spec, set())})

    def test_line_is_the_default(self):
        """decisions/164: a spark without 'form' is a line where the registry takes one, else glyphs (the fallback)."""
        def form(fn):
            spec = registry.expand(mutate(lambda s: (spark(s)["spark"].pop("form"), spark(s)["spark"].update(count=8),
                                                     fn(s))))
            return next(c for c in reg(spec)["columns"] if c["style"] == "spark")["spark"]["form"]
        self.assertEqual(form(lambda s: None), "line")
        self.assertEqual(form(lambda s: reg(s)["columns"].reverse()), "glyphs")  # not the last column
        self.assertEqual(form(lambda s: reg(s).update(rows=["Region", "Category"])), "glyphs")
        self.assertEqual(form(lambda s: reg(s).update(totals={"grand": "rows"})), "glyphs")
        self.assertEqual(form(lambda s: reg(s).update(top={"n": 2})), "glyphs")
        spec = mutate(lambda s: spark(s)["spark"].pop("form"))
        registry.expand(spec)
        self.assertNotIn("form", spark(spec)["spark"])


class Workbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(copy.deepcopy(SPEC))
        cls.sheets = {w.get("name"): w for w in cls.root.iter("worksheet")}
        cls.zones = {z.get("name"): z for z in cls.root.iter("zone") if z.get("name")}

    def test_registry_draws_the_other_columns(self):
        cols = self.sheets["Regions"].findtext("table/cols")
        self.assertEqual(cols.count(" + "), 2)  # Sales (and its outside layer) + Profit; no spark cell

    def test_line_sheet_form(self):
        t = self.sheets[PART].find("table")
        self.assertTrue(t.findtext("rows").startswith("([") and " * ([" in t.findtext("rows"))
        self.assertIn("[tmn:Order Date:qk]", t.findtext("cols"))
        marks = [p.find("mark").get("class") for p in t.iterfind("panes/pane[@id]")]
        self.assertEqual(marks, ["Line", "Circle"])
        dot = t.find("panes/pane[@id='2']/style/style-rule[@element='mark']/format[@attr='mark-color']")
        self.assertEqual(dot.get("value"), registry.bar_color(reg(SPEC)))

    def test_zones_side_by_side(self):
        r, p = self.zones["Regions"], self.zones[PART]
        self.assertEqual(int(r.get("x")) + int(r.get("w")), int(p.get("x")))
        self.assertEqual((r.get("y"), r.get("h")), (p.get("y"), p.get("h")))

    def test_title_over_the_line(self):
        texts = ["".join(z.itertext()).strip() for z in self.root.iter("zone") if z.get("type-v2") == "text"]
        self.assertIn("Monthly sales", texts)

    def test_gate_clean(self):
        from lxml import etree  # the gate walks up to parents
        root = etree.fromstring(ET.tostring(self.root))
        self.assertEqual([i for c in gate.CHECKS if c is not gate.check_xsd for i in c(root)], [])


class Errors(unittest.TestCase):
    def check(self, fn, pattern):
        with self.assertRaisesRegex(ValueError, pattern):
            build(mutate(fn), OUT, SPECS)

    def test_line_is_the_last_column(self):
        self.check(lambda s: reg(s)["columns"].reverse(), "last column")

    def test_one_row_dimension(self):
        self.check(lambda s: reg(s).update(rows=["Region", "Category"]), "one row dimension")

    def test_no_totals_or_top(self):
        self.check(lambda s: reg(s).update(totals={"grand": "rows"}), "no totals")
        self.check(lambda s: reg(s).update(top={"n": 2}), "(no totals|Top N)")

    def test_periods(self):
        self.check(lambda s: spark(s)["spark"].update(count=61), "maximum of 60")  # the schema
        self.check(lambda s: spark(s)["spark"].update({"form": "glyphs"}), "outside 2..12")

    def test_spark_date_is_a_date(self):  # decisions/096 tail: glyphs too
        self.check(lambda s: spark(s)["spark"].update(date="Region"), "spark.date 'Region' is not a date")
        self.check(lambda s: spark(s)["spark"].update(date="Ship Date"), "spark.date 'Ship Date' is not a date")
        self.check(lambda s: spark(s)["spark"].update(date="Region", form="glyphs", count=8), "is not a date")


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(copy.deepcopy(SPEC))

    def issues(self, fn):
        root = copy.deepcopy(self.root)
        fn(root)
        return [i.message for i in gate.check_registry_spark_line(root)]

    @staticmethod
    def part(root):
        return next(w for w in root.iter("worksheet") if w.get("name") == PART).find("table")

    def test_clean(self):
        self.assertEqual(self.issues(lambda r: None), [])

    def test_dot_off_the_line_axis(self):
        def f(root):
            self.part(root).find("style/style-rule[@element='axis']/encoding[@fold='true']").set("synchronized", "false")
        self.assertTrue(any("floats" in m for m in self.issues(f)))

    def test_no_periods_filter(self):
        def f(root):
            v = self.part(root).find("view")
            v.remove(v.find("filter"))
        self.assertTrue(any("periods filter" in m for m in self.issues(f)))

    def test_sort_differs(self):
        def f(root):
            self.part(root).find("view/computed-sort").set("direction", "ASC")
        self.assertTrue(any("not the registry's" in m for m in self.issues(f)))

    def test_axis_shown(self):
        def f(root):
            fmt = self.part(root).find("style/style-rule[@element='axis']/format[@attr='display']")
            fmt.set("value", "true")
        self.assertTrue(any("a spark has no axes" in m for m in self.issues(f)))

    def test_row_names_shown(self):
        def f(root):
            rule = self.part(root).find("style/style-rule[@element='label']")
            rule.remove(rule.find("format"))
        self.assertTrue(any("row names" in m for m in self.issues(f)))

    def test_pane_height(self):
        def f(root):
            self.part(root).find("panes/pane[@id='1']/style/style-rule[@element='pane']/format[@attr='maxheight']") \
                .set("value", "24")
        self.assertTrue(any("drift apart" in m for m in self.issues(f)))

    def test_other_rows(self):
        def f(root):
            t = self.part(root)
            t.find("rows").text = t.findtext("rows").replace("[none:Region:nk]", "[none:Category:nk]", 1)
        self.assertTrue(any("row dimension" in m for m in self.issues(f)))


if __name__ == "__main__":
    unittest.main()
