"""Pareto (decisions/157): bars largest first, the running share on a second axis, the threshold line, the vital few
in the accent; expected (running shares from the CSV), refusals, gate mutations."""
import csv
import json
import unittest
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict

from tbuilder import expected, gate, spec as spec_mod
from tbuilder.build import build, build_file
from tbuilder.design import COLOR
from test_gate import repack, ws
from test_roundtrip import OUT, ROOT

SPEC = ROOT / "specs" / "pareto.json"
CSV = ROOT / "data" / "sample" / "complaints.csv"
ROWS = list(csv.DictReader(CSV.open(encoding="utf-8")))


def spec():
    s = json.loads(SPEC.read_text(encoding="utf-8"))
    s["datasource"]["path"] = "data/sample/complaints.csv"
    return s


def twb(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


def layers(w):
    return [p for p in w.findall("table/panes/pane") if p.get("id")]


def pareto(amounts):
    """[(member, amount, running share)] largest first, written apart from pareto.expected."""
    total = sum(amounts.values())
    out, run = [], 0
    for k in sorted(amounts, key=lambda k: (-amounts[k], k)):
        run += amounts[k]
        out.append((k, amounts[k], run / total))
    return out


def by_cause(count=False):
    out = defaultdict(float)
    for r in ROWS:
        out[r["Cause"]] += 1 if count else float(r["Cost"])
    return out


class Workbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = twb(build(spec(), OUT / "pareto.twbx", base_dir=ROOT))  # passes the gate
        cls.cols = {c.get("caption"): c for c in cls.root.iter("column") if c.get("caption")}

    def test_schema(self):
        spec_mod.validate(spec())
        for edit in ({"threshold": 1.2}, {"threshold": 0}, {"sort": "asc"}, {"measure": None}):
            bad = spec()
            s = bad["sheets"][0]
            for k, v in edit.items():
                s.pop(k) if v is None else s.update({k: v})
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                spec_mod.validate(bad)

    def test_dual_axis_bars_and_the_running_share(self):
        w = ws(self.root, "Cost Pareto")
        bar, line = layers(w)
        self.assertEqual([p.find("mark").get("class") for p in (bar, line)], ["Bar", "Line"])
        self.assertIn("[sum:Cost:qk]", bar.get("y-axis-name"))
        run = self.cols["Cost Pareto · Cumulative"]
        self.assertEqual(run.find("calculation").get("formula"), "RUNNING_SUM(SUM([Cost])) / TOTAL(SUM([Cost]))")
        self.assertEqual(run.get("default-format"), "p0%")
        self.assertIn(run.get("name")[1:-1], line.get("y-axis-name"))
        self.assertIn("[none:Cause:nk]", w.findtext("table/cols"))
        fold = w.find("table/style/style-rule[@element='axis']/encoding[@fold='true']")
        self.assertIsNone(fold.get("synchronized"))  # an amount and a share
        # both axes stay (display false on the first measure does not hide it in Desktop), without titles
        self.assertIsNone(w.find("table/style/style-rule[@element='axis']/format[@attr='display']"))
        titles = w.findall("table/style/style-rule[@element='axis']/format[@attr='title']")
        self.assertEqual([(t.get("value"), t.get("field").split(".")[-1]) for t in titles],
                         [("", "[sum:Cost:qk]"), ("", fold.get("field").split(".")[-1])])
        self.assertEqual(bar.find("style/style-rule[@element='mark']/format[@attr='mark-labels-show']").get("value"),
                         "false")  # the amounts read on the axis
        sort = w.find("table/view/computed-sort")
        self.assertEqual((sort.get("direction"), sort.get("using").split(".")[-1]), ("DESC", "[sum:Cost:qk]"))
        tc = next(ci for ci in w.iter("column-instance") if ci.get("column") == run.get("name")).find("table-calc")
        self.assertEqual(tc.get("ordering-type"), "Field")
        self.assertIn("[none:Cause:nk]", tc.get("ordering-field"))
        self.assertIsNotNone(self.root.find("document-format-change-manifest/SortTagCleanup"))

    def test_threshold_line(self):
        w = ws(self.root, "Cost Pareto")
        rl = w.find("table/panes/pane/reference-line")
        self.assertEqual((rl.get("formula"), rl.get("value"), rl.get("scope")), ("constant", "0.80000000000000004", "per-pane"))
        self.assertIn(self.cols["Cost Pareto · Cumulative"].get("name")[1:-1], rl.get("axis-column"))
        look = {f.get("attr"): f.get("value") for f in w.iterfind("table/style/style-rule[@element='refline']/format")}
        self.assertEqual((look["line-pattern-only"], look["text-format"]), ("dashed", "p0%"))

    def test_vital_few_in_the_accent(self):
        w = ws(self.root, "Cost Pareto")
        bar, line = layers(w)
        vital = self.cols["Cost Pareto · Vital"]
        self.assertEqual(vital.find("calculation").get("formula"),
                         "RUNNING_SUM(SUM([Cost])) - SUM([Cost]) < 0.8 * TOTAL(SUM([Cost]))")
        self.assertIn(vital.get("name")[1:-1], bar.find("encodings/color").get("column"))
        self.assertEqual(line.find("style/style-rule/format[@attr='mark-color']").get("value"), COLOR["muted"])
        pal = next(e for e in self.root.iter("encoding") if e.get("attr") == "color"
                   and vital.get("name")[1:-1] in (e.get("field") or ""))
        self.assertEqual({m.findtext("bucket"): m.get("to") for m in pal.iter("map")},
                         {"true": COLOR["accent"], "false": COLOR["mark_muted"]})

    def test_without_highlight_muted_bars_accent_line(self):
        w = ws(self.root, "Count Pareto")
        bar, line = layers(w)
        self.assertIsNone(bar.find("encodings"))
        self.assertEqual(bar.find("style/style-rule[@element='mark']/format[@attr='mark-color']").get("value"),
                         COLOR["mark_muted"])
        self.assertEqual(line.find("style/style-rule/format[@attr='mark-color']").get("value"), COLOR["accent"])
        self.assertNotIn("Count Pareto · Vital", self.cols)

    def test_refusals(self):
        bad = spec()
        bad["sheets"][0]["measure"]["table_calc"] = {"type": "running_total"}
        with self.assertRaises(ValueError):
            build(bad, OUT / "pareto_bad.twbx", base_dir=ROOT)


class Expected(unittest.TestCase):
    def test_running_shares_from_the_csv(self):
        got = expected.compute(spec(), CSV)
        for sheet, label, count in (("Cost Pareto", "SUM(Cost)", False), ("Count Pareto", "COUNT(Ticket)", True)):
            want = pareto(by_cause(count))
            self.assertEqual(list(got[sheet]), [k for k, *_ in want])  # largest first
            for k, amount, share in want:
                self.assertAlmostEqual(got[sheet][k][label], amount, places=6)
                self.assertAlmostEqual(got[sheet][k]["Cumulative"], share, places=9)
            self.assertAlmostEqual(want[-1][2], 1.0)
        self.assertEqual(got["Cost Pareto · Vital"]["count"], 5)  # Late delivery .. Billing error: 0.776 -> 0.850
        self.assertAlmostEqual(got["Cost Pareto · Vital"]["share"], pareto(by_cause())[4][2])
        self.assertNotIn("Count Pareto · Vital", got)

    def test_threshold_moves_the_vital_few(self):
        s = spec()
        s["sheets"][0]["threshold"] = 0.5
        got = expected.compute(s, CSV)
        self.assertEqual(got["Cost Pareto · Vital"]["count"], 2)  # 0 and 0.317 are under 0.5


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build_file(SPEC, OUT / "pareto_gate.twbx")

    def assertCaught(self, fn, text):
        issues = [str(i) for i in gate.run(repack(fn, source=self.path))]
        self.assertTrue(any(i.startswith("[pareto]") and text in i for i in issues), issues)

    def test_clean(self):
        self.assertEqual(gate.run(self.path), [])

    def test_sort_ascending(self):
        self.assertCaught(lambda r: ws(r, "Cost Pareto").find("table/view/computed-sort").set("direction", "ASC"),
                          "not sorted")

    def test_no_sort(self):
        def f(r):
            view = ws(r, "Cost Pareto").find("table/view")
            view.remove(view.find("computed-sort"))
        self.assertCaught(f, "not sorted")

    def test_sorted_by_another_measure(self):
        def f(r):
            w = ws(r, "Cost Pareto")
            s = w.find("table/view/computed-sort")
            s.set("using", w.find("table/style/style-rule[@element='axis']/encoding[@fold='true']").get("field"))
        self.assertCaught(f, "not sorted")

    def test_line_of_another_measure(self):
        def f(r):
            for c in r.iter("column"):
                if c.get("caption") == "Cost Pareto · Cumulative":
                    c.find("calculation").set("formula", "RUNNING_SUM(COUNT([Ticket])) / TOTAL(COUNT([Ticket]))")
        self.assertCaught(f, "does not add up the bars")

    def test_threshold_not_a_share(self):
        self.assertCaught(lambda r: ws(r, "Cost Pareto").find("table/panes/pane/reference-line").set("value", "80.0"),
                          "runs 0..1")

    def test_vital_at_another_threshold(self):
        def f(r):
            for c in r.iter("column"):
                if c.get("caption") == "Cost Pareto · Vital":
                    calc = c.find("calculation")
                    calc.set("formula", calc.get("formula").replace("0.8 *", "0.7 *"))
        self.assertCaught(f, "colored at 0.7")

    def test_running_along_nothing(self):
        def f(r):
            w = ws(r, "Cost Pareto")
            run = next(c for c in r.iter("column") if c.get("caption") == "Cost Pareto · Cumulative").get("name")
            ci = next(ci for ci in w.iter("column-instance") if ci.get("column") == run)
            ci.find("table-calc").set("ordering-field", "[x].[none:Region:nk]")
        self.assertCaught(f, "not along the members")


if __name__ == "__main__":
    unittest.main()
