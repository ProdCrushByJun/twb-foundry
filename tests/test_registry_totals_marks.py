"""decisions/134: a registry total takes rank, track, dot, tick and highlight columns. A rank is blank on a total, a
track its FIXED share of the source (100 % on the grand total), a dot its number without a color, a tick its bar 0 and
no line, a highlight never flags a total. Each column alone under a grand total and subtotals: builds, the gate passes,
the total's numbers are the source's; gate mutations; a spark / pill stays refused with a hint."""
import copy
import csv
import json
import re
import unittest
from collections import defaultdict
from pathlib import Path

from tbuilder import gate, registry
from tbuilder.build import build
from tbuilder.expected import compute, data_path
from test_gate import repack
from test_roundtrip import ROOT, SPECS

SPEC = json.loads((SPECS / "registry_totals_marks.json").read_text(encoding="utf-8"))
OUT = ROOT / "out" / "registry_totals_marks_test"
ROWS = list(csv.DictReader((ROOT / "data" / "sample" / "sales_plan.csv").open(encoding="utf-8")))
GUARD1 = "COUNTD([Region]) <= 1"
GUARD2 = "COUNTD([Region]) <= 1 AND COUNTD([Manager]) <= 1"

COLUMNS = {
    "rank": {"measure": {"field": "Sales"}, "style": "rank", "label": "#"},
    "track": {"measure": {"field": "Sales"}, "style": "track", "label": "Of total"},
    "dot": {"measure": {"field": "Plan", "agg": "avg"}, "style": "dot", "label": "Avg plan"},
    "tick": {"measure": {"field": "Sales"}, "style": "tick", "label": "Vs plan", "base": {"field": "Plan"}},
    "highlight": {"measure": {"field": "Plan"}, "style": "text", "label": "Plan", "highlight": {"above": 18000}},
}


def variant(name):
    """Both sheets: a Sales text column and the column under test (Regions: a grand total, Managers: subtotals too)."""
    spec = copy.deepcopy(SPEC)
    for s in spec["sheets"]:
        s["columns"] = [{"measure": {"field": "Sales"}, "style": "text", "label": "Sales"}, copy.deepcopy(COLUMNS[name])]
    return spec


def total(field, agg=sum, region=None):
    vals = [float(r[field]) for r in ROWS if region in (None, r["Region"])]
    return agg(vals) if agg is sum else agg(vals)


def mean(v):
    return sum(v) / len(v)


def by_region(field):
    out = defaultdict(float)
    for r in ROWS:
        out[r["Region"]] += float(r[field])
    return out


class EachColumnUnderTotals(unittest.TestCase):
    """The acceptance of 103 'table + KPI': each column builds, passes the gate and its total row is the source's."""

    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True, exist_ok=True)
        cls.books, cls.got = {}, {}
        for name in COLUMNS:
            spec = variant(name)
            cls.books[name] = build(spec, OUT / f"{name}.twbx", SPECS)
            cls.got[name] = compute(spec, data_path(spec, SPECS))

    def test_gate_passes(self):
        for name, path in self.books.items():
            with self.subTest(column=name):
                self.assertEqual([str(i) for i in gate.run(path)], [])

    def test_sales_total(self):
        for name, got in self.got.items():
            with self.subTest(column=name):
                self.assertAlmostEqual(got["Regions"]["TOTAL"]["Sales"], total("Sales"), 2)
                self.assertAlmostEqual(got["Managers"]["Total"]["Sales"], total("Sales"), 2)
                self.assertAlmostEqual(got["Managers"]["East | Total"]["Sales"], total("Sales", region="East"), 2)

    def test_rank_blank_on_totals(self):
        reg, man = self.got["rank"]["Regions"], self.got["rank"]["Managers"]
        self.assertIsNone(reg["TOTAL"]["#"])
        self.assertIsNone(man["Total"]["#"])
        self.assertIsNone(man["West | Total"]["#"])
        self.assertEqual(sorted(reg[r]["#"] for r in by_region("Sales")), [1, 2, 3, 4])
        self.assertEqual(man["West | Igor"]["#"], 1)  # within its region

    def test_track_total_is_its_share_of_the_source(self):
        whole, parts = total("Sales"), by_region("Sales")
        reg, man = self.got["track"]["Regions"], self.got["track"]["Managers"]
        self.assertAlmostEqual(reg["TOTAL"]["Of total"], 1.0)
        self.assertAlmostEqual(man["Total"]["Of total"], 1.0)
        for r, v in parts.items():
            self.assertAlmostEqual(reg[r]["Of total"], v / whole)
            self.assertAlmostEqual(man[f"{r} | Total"]["Of total"], v / whole)

    def test_dot_total_is_the_measure(self):
        reg = self.got["dot"]["Regions"]
        self.assertAlmostEqual(reg["TOTAL"]["Avg plan"], mean([float(r["Plan"]) for r in ROWS]))
        self.assertAlmostEqual(self.got["dot"]["Managers"]["North | Total"]["Avg plan"],
                               mean([float(r["Plan"]) for r in ROWS if r["Region"] == "North"]))

    def test_tick_line_none_on_totals(self):
        man = self.got["tick"]["Managers"]
        self.assertIsNone(man["Total"]["Vs plan · Plan"])
        self.assertIsNone(man["South | Total"]["Vs plan · Plan"])
        self.assertAlmostEqual(man["South | Elena"]["Vs plan · Plan"],
                               sum(float(r["Plan"]) for r in ROWS if r["Manager"] == "Elena"))
        self.assertAlmostEqual(man["Total"]["Vs plan"], total("Sales"), 2)

    def test_highlight_total_is_the_measure(self):
        man = self.got["highlight"]["Managers"]
        self.assertAlmostEqual(man["Total"]["Plan"], total("Plan"), 2)
        self.assertAlmostEqual(man["East | Total"]["Plan"], total("Plan", region="East"), 2)


class Calcs(unittest.TestCase):
    def setUp(self):
        self.calcs = {c["name"]: c for c in registry.calcs(SPEC)}

    def test_rank_guarded(self):
        self.assertEqual(self.calcs["Regions · # · Rank"]["formula"], f"IF {GUARD1} THEN RANK(SUM([Sales])) END")
        self.assertEqual(self.calcs["Managers · # · Rank"]["formula"], f"IF {GUARD2} THEN RANK(SUM([Sales])) END")

    def test_track_fixed_share(self):
        share = self.calcs["Regions · Of total · Share"]
        self.assertEqual(share["formula"], "SUM([Sales]) / MAX({FIXED : SUM([Sales])})")
        self.assertNotIn("compute_using", share)
        self.assertEqual(self.calcs["Regions · Of total · Track"]["formula"],
                         "1 - SUM([Sales]) / MAX({FIXED : SUM([Sales])})")

    def test_dot_color_and_tick_line_guarded(self):
        self.assertEqual(self.calcs["Regions · Avg plan · Color"]["formula"], f"IF {GUARD1} THEN AVG([Plan]) END")
        self.assertEqual(self.calcs["Managers · Sales vs plan · Base"]["formula"], f"IF {GUARD2} THEN SUM([Plan]) END")
        self.assertEqual(self.calcs["Managers · Sales vs plan · Bar"]["formula"],
                         f"IF {GUARD2} THEN SUM([Sales]) ELSE 0 END")

    def test_flag_never_on_a_total(self):
        self.assertEqual(self.calcs["Managers · Plan · Flag"]["formula"],
                         f'IF NOT ({GUARD2}) THEN "Total" ELSEIF SUM([Plan]) > 18000 THEN "Flagged" ELSE "Row" END')

    def test_without_totals_unchanged(self):
        spec = copy.deepcopy(SPEC)
        for s in spec["sheets"]:
            s.pop("totals")
        calcs = {c["name"]: c for c in registry.calcs(spec)}
        self.assertEqual(calcs["Regions · # · Rank"]["formula"], "RANK(SUM([Sales]))")
        self.assertEqual(calcs["Regions · Of total · Share"]["formula"], "SUM([Sales]) / TOTAL(SUM([Sales]))")
        self.assertEqual(calcs["Managers · Plan · Flag"]["formula"], "SUM([Plan]) > 18000")
        self.assertFalse({"Regions · Avg plan · Color", "Managers · Sales vs plan · Base"} & set(calcs))


class Refusal(unittest.TestCase):
    def test_pill_under_totals_refused_with_a_hint(self):
        spec = variant("rank")
        spec["sheets"][0]["columns"][1] = {"measure": {"field": "Sales"}, "style": "pill", "label": "Level",
                                           "levels": [{"label": "Low", "color": "bad"},
                                                      {"from": 33000, "label": "High", "color": "good"}]}
        with self.assertRaisesRegex(ValueError, "is pill: .*drop the totals"):
            build(spec, OUT / "neg.twbx", SPECS)


class GateMutations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True, exist_ok=True)
        cls.path = build(SPEC, OUT / "marks.twbx", SPECS)

    def issues(self, fn):
        return [str(i) for i in gate.run(repack(fn, source=self.path)) if i.check == "totals"]

    def formulas(self, root, pred, change):
        hit = [c for c in root.iter("calculation") if pred(c.get("formula") or "")]
        self.assertTrue(hit)
        for c in hit:
            c.set("formula", change(c.get("formula")))

    def test_clean(self):
        self.assertEqual(self.issues(lambda r: None), [])

    def test_track_of_the_visible_rows_refused(self):
        fn = lambda r: self.formulas(r, lambda f: "FIXED :" in f,  # noqa: E731
                                     lambda f: re.sub(r"MAX\(\{FIXED : (.+?)\}\)", r"TOTAL(\1)", f))
        self.assertTrue(any("[Multiple Values]" in i for i in self.issues(fn)))

    def test_track_axis_not_fixed_refused(self):
        def fn(root):
            for e in root.iter("encoding"):
                if e.get("field", "").endswith("[Multiple Values]") and e.get("range-type") == "fixed":
                    e.set("max", "2.0")
        self.assertTrue(any("[Multiple Values]" in i for i in self.issues(fn)))

    def test_dot_color_with_a_total_value_refused(self):
        fn = lambda r: self.formulas(r, lambda f: f.endswith("THEN AVG([Plan]) END"),  # noqa: E731
                                     lambda f: f[:-len(" END")] + " ELSE 0 END")
        self.assertTrue(any("colored by" in i for i in self.issues(fn)))

    def test_dot_color_unguarded_refused(self):
        fn = lambda r: self.formulas(r, lambda f: f.endswith("THEN AVG([Plan]) END"),  # noqa: E731
                                     lambda f: "AVG([Plan])")
        self.assertTrue(any("colored by" in i for i in self.issues(fn)))


if __name__ == "__main__":
    unittest.main()
