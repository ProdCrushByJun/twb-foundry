"""Table calculation functions in calc formulas (decisions/034): formula.py, the sheet checks, expected, the gate."""
import copy
import json
import unittest

from tbuilder import expected, gate
from tbuilder.build import build, build_file
from tbuilder.formula import CalcSet, FormulaError
from test_gate import repack, ws
from test_roundtrip import OUT, ROOT, read_twbx

SPEC = ROOT / "specs" / "tablecalc_funcs.json"
TYPES = {"R": "string", "C": "string", "S": "integer", "X": "real"}
ROWS = [{"R": r, "C": c, "S": s, "X": x} for r, c, s, x in
        [("a", "p", "10", "1"), ("b", "p", "30", ""), ("c", "q", "20", "2"), ("d", "q", "30", "4"), ("a", "q", "5", "")]]
MARKS = [[r for r in ROWS if r["R"] == k] for k in "abcd"]  # SUM(S): a 15, b 30, c 20, d 30


def values(formula, marks=MARKS, cu=("R",)):
    cs = CalcSet([{"name": "T", "formula": formula, "compute_using": list(cu)}], TYPES, ROWS)
    return cs.table_values("T", marks)


def error(formula, cu=("R",), extra=()):
    specs = list(extra) + [{"name": "T", "formula": formula, **({"compute_using": list(cu)} if cu else {})}]
    with unittest.TestCase().assertRaises(FormulaError) as e:
        CalcSet(specs, TYPES, ROWS)
    return str(e.exception)


class Evaluate(unittest.TestCase):
    def test_rank_competition_and_dense(self):
        self.assertEqual(values("RANK(SUM([S]))"), [4, 1, 3, 1])  # ties share the rank, the next one skips
        self.assertEqual(values("RANK(SUM([S]), 'asc')"), [1, 3, 2, 3])
        self.assertEqual(values("RANK_DENSE(SUM([S]))"), [3, 1, 2, 1])
        self.assertEqual(values("RANK_DENSE(SUM([S]), 'asc')"), [1, 3, 2, 3])

    def test_rank_ignores_nulls(self):
        self.assertEqual(values("RANK(SUM([X]))"), [3, None, 2, 1])  # b has no X: not ranked, does not count

    def test_windows(self):
        self.assertEqual(values("WINDOW_SUM(SUM([S]))"), [95] * 4)
        self.assertEqual(values("WINDOW_AVG(SUM([S]))"), [23.75] * 4)
        self.assertEqual(values("WINDOW_MAX(SUM([S]))"), [30] * 4)
        self.assertEqual(values("WINDOW_MIN(SUM([S]))"), [15] * 4)
        self.assertEqual(values("WINDOW_AVG(SUM([S]), -1, 0)"), [15, 22.5, 25, 25])  # clipped at the first mark
        self.assertEqual(values("WINDOW_SUM(SUM([S]), FIRST(), 0)"), [15, 45, 65, 95])
        self.assertEqual(values("WINDOW_SUM(SUM([S]), 0, LAST())"), [95, 80, 50, 30])
        self.assertEqual(values("WINDOW_AVG(SUM([X]))"), [7 / 3] * 4)  # nulls left out of the average

    def test_lookup_running_index(self):
        self.assertEqual(values("LOOKUP(SUM([S]), -1)"), [None, 15, 30, 20])
        self.assertEqual(values("LOOKUP(SUM([S]), 2)"), [20, 30, None, None])
        self.assertEqual(values("RUNNING_SUM(SUM([S]))"), [15, 45, 65, 95])
        self.assertEqual(values("INDEX()"), [1, 2, 3, 4])
        self.assertEqual(values("FIRST()"), [0, -1, -2, -3])
        self.assertEqual(values("LAST()"), [3, 2, 1, 0])
        self.assertEqual(values("SUM([S]) - LOOKUP(SUM([S]), -1)"), [None, 15, -10, 10])

    def test_total_reaggregates_rows(self):
        self.assertEqual(values("SUM([S]) / TOTAL(SUM([S]))"), [15 / 95, 30 / 95, 20 / 95, 30 / 95])
        # TOTAL(AVG) is the average of the partition's rows (19), not of the marks' averages (21.875)
        self.assertEqual(values("TOTAL(AVG([S]))"), [19] * 4)

    def test_partitions_are_separate(self):
        self.assertEqual(values("INDEX()", marks=MARKS[:2]), [1, 2])
        self.assertEqual(values("RANK(SUM([S]))", marks=MARKS[2:]), [2, 1])

    def test_types(self):
        cs = CalcSet([{"name": "A1", "formula": "RANK(SUM([X]))", "compute_using": ["R"]},
                      {"name": "B1", "formula": "WINDOW_AVG(SUM([S]))", "compute_using": ["R"]},
                      {"name": "C1", "formula": "LOOKUP(SUM([S]), -1) > 1", "compute_using": ["R"]},
                      {"name": "D1", "formula": "SUM([S])"}], TYPES, ROWS)
        self.assertEqual([cs[n].datatype for n in ("A1", "B1", "C1")], ["integer", "real", "boolean"])
        self.assertTrue(cs["A1"].table_calc and cs["A1"].is_agg)
        self.assertEqual(cs["A1"].compute_using, ["R"])
        self.assertFalse(cs["D1"].table_calc)
        with self.assertRaises(ValueError):
            cs.agg_value("A1", ROWS)  # no partition: no value


class Reject(unittest.TestCase):
    def test_compute_using_required(self):
        self.assertIn("set compute_using", error("RANK(SUM([S]))", cu=None))
        self.assertIn("applies only to table calculations", error("SUM([S])"))
        self.assertIn("repeats", error("INDEX()", cu=("R", "R")))

    def test_levels(self):
        self.assertIn("needs an aggregate", error("RANK([S])"))
        self.assertIn("needs an aggregate", error("WINDOW_SUM(1)"))
        self.assertIn("cannot be inside an aggregate", error("SUM(RANK(SUM([S])))"))
        self.assertIn("cannot mix aggregate", error("RANK(SUM([S])) + [S]"))

    def test_not_in_lod(self):
        self.assertIn("inside a LOD", error("{FIXED : WINDOW_SUM(SUM([S]))}"))
        self.assertIn("inside a LOD", error("SUM({FIXED [R] : INDEX()})"))

    def test_arguments(self):
        self.assertIn("integer literal", error("LOOKUP(SUM([S]), [S])"))
        self.assertIn("1 or 3", error("WINDOW_AVG(SUM([S]), -2)"))
        self.assertIn("FIRST() / LAST()", error("WINDOW_AVG(SUM([S]), INDEX(), 0)"))
        self.assertIn("'asc' or 'desc'", error("RANK(SUM([S]), 'up')"))
        self.assertIn("needs a number", error("RANK(MAX([R]))"))
        self.assertIn("not another table calculation", error("TOTAL(SUM([S]) - LOOKUP(SUM([S]), -1))"))
        self.assertIn("INDEX takes 0", error("INDEX(1)"))

    def test_no_reference_to_another_table_calc(self):
        other = [{"name": "Rk", "formula": "RANK(SUM([S]))", "compute_using": ["R"]}]
        self.assertIn("[Rk] is a table calculation", error("[Rk] + 1", extra=other))


def _spec(**change):
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    spec["datasource"]["path"] = str(ROOT / "data" / "sample" / "sales.csv")
    spec.update(change)
    return spec


class Sheets(unittest.TestCase):
    def build_error(self, spec):
        with self.assertRaises(ValueError) as e:
            build(spec, OUT / "tcf_neg.twbx")
        return str(e.exception)

    def test_compute_using_not_on_the_sheet(self):
        spec = _spec()
        spec["calcs"][0]["compute_using"] = ["Category"]  # Sales Rank on a bar by Region
        self.assertIn("compute_using 'Category' is not a dimension of this sheet", self.build_error(spec))

    def test_not_on_a_kpi(self):
        spec = _spec()
        spec["sheets"].append({"name": "K", "type": "kpi", "measures": [{"field": "Sales Rank"}]})
        spec["dashboard"]["grid"].append(["K"])
        self.assertIn("needs a sheet with dimensions", self.build_error(spec))

    def test_not_with_a_sort_or_a_quick_table_calc(self):
        spec = _spec()
        spec["sheets"][0]["sort"] = "desc"
        self.assertIn("sorting, Top N or a plan", self.build_error(spec))
        spec = _spec()
        spec["sheets"][0]["measure"]["table_calc"] = {"type": "running_total"}
        self.assertIn("quick table_calc on the table calculation", self.build_error(spec))

    def test_missing_compute_using_fails_the_build(self):
        spec = _spec()
        del spec["calcs"][0]["compute_using"]
        self.assertIn("set compute_using", self.build_error(spec))


class Expected(unittest.TestCase):
    """The golden spec's numbers, checked by hand from the sales.csv totals (decisions/034)."""

    @classmethod
    def setUpClass(cls):
        cls.e = expected.compute(_spec(), ROOT / "data" / "sample" / "sales.csv")

    def test_ranks(self):
        self.assertEqual(self.e["Sales Rank"], {"East": 4, "North": 2, "South": 1, "West": 3})
        # orders: South 135, North 123, West 123, East 119 -> competition 1 2 2 4, dense ascending 3 2 2 1
        self.assertEqual(self.e["Orders Rank"], {"East": 4, "North": 2, "South": 1, "West": 2})
        self.assertEqual(self.e["Orders Dense Rank"], {"East": 1, "North": 2, "South": 3, "West": 2})

    def test_months(self):
        self.assertIsNone(self.e["Prev Month"]["2025-01"])
        self.assertAlmostEqual(self.e["Prev Month"]["2025-02"], 19090.65, 2)
        self.assertAlmostEqual(self.e["Running"]["2025-12"], 224709.68, 2)
        self.assertAlmostEqual(self.e["Remaining"]["2025-01"], 224709.68, 2)
        self.assertAlmostEqual(self.e["Remaining"]["2025-12"], 17753.87, 2)
        self.assertAlmostEqual(self.e["Moving Avg"]["2025-03"], (19090.65 + 24338.11 + 21982.65) / 3, 6)
        self.assertAlmostEqual(self.e["Cumulative"]["2025-12"], 224709.68 / 12, 6)

    def test_partitions(self):
        avg = (52353.59 + 58482.58 + 58862.46 + 55011.05) / 4
        self.assertAlmostEqual(self.e["Sales vs Avg"]["East"], 52353.59 - avg, 6)
        for cat in ("Furniture", "Office", "Tech"):  # the share partitions by Category: 100% per column
            self.assertAlmostEqual(sum(v for k, v in self.e["Share"].items() if k.endswith(cat)), 1, 9)
        self.assertEqual(self.e["Min-Max"]["North | Furniture"], 1)
        self.assertEqual(self.e["Min-Max"]["North | Office"], 0)
        self.assertEqual(list(self.e["Index"].values()), list(range(1, 13)))  # along Region, then Category


class NullIndicator(unittest.TestCase):
    """decisions/167: no '1 null' in the corner of an axis sheet whose calc is null at the partition's edge."""
    @classmethod
    def setUpClass(cls):
        cls.root = read_twbx(build_file(SPEC, OUT / "tcf_nulls.twbx"))[0]
        cls.quick = read_twbx(build_file(ROOT / "specs" / "tablecalcs.json", OUT / "tc_nulls.twbx"))[0]

    @staticmethod
    def hidden(root, name):
        return ws(root, name).find("table/style/style-rule[@element='table']/"
                                   "format[@attr='show-null-value-warning'][@value='false']") is not None

    def test_lookup_and_difference_hide_it(self):
        self.assertTrue(self.hidden(self.root, "Prev Month"))  # LOOKUP(SUM([Sales]), -1)
        self.assertTrue(self.hidden(self.quick, "MoM Change"))  # quick percent_difference

    def test_calcs_without_an_edge_null_keep_it(self):
        for name in ("Running", "Moving Avg", "Sales Rank", "Remaining"):
            self.assertFalse(self.hidden(self.root, name), name)
        self.assertFalse(self.hidden(self.quick, "Running Sales"))
        self.assertFalse(self.hidden(self.quick, "Region Difference"))  # a text table draws no indicator


class GateCatchesTableCalcs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = build_file(SPEC, OUT / "gate_tablecalc_funcs.twbx")

    def assertCaught(self, mutate, text):
        issues = gate.run(repack(mutate, source=self.src))
        hits = [i for i in issues if i.check == "tablecalc" and text in str(i)]
        self.assertTrue(hits, f"expected [tablecalc] ~ '{text}', got: {[str(i) for i in issues]}")

    def test_passes(self):
        self.assertEqual(gate.run(self.src), [])

    def test_calc_without_compute_using(self):
        def m(r):
            for ci in ws(r, "Sales Rank").iter("column-instance"):
                for t in ci.findall("table-calc"):
                    ci.remove(t)
        self.assertCaught(m, "has no compute-using")

    def test_compute_using_off_the_sheet(self):
        def m(r):  # Category declared on the bar's sheet, but not on its shelves: the rank runs along it
            deps = ws(r, "Sales Rank").find("table/view/datasource-dependencies")
            index = ws(r, "Index").find("table/view/datasource-dependencies")
            col = next(c for c in index.findall("column") if c.get("name") == "[Category]")
            ci = next(c for c in index.findall("column-instance") if c.get("column") == "[Category]")
            deps.insert(0, copy.deepcopy(col))
            deps.append(copy.deepcopy(ci))
            tc = next(t for t in deps.iter("table-calc") if t.get("ordering-field"))
            tc.set("ordering-field", tc.get("ordering-field").replace("[none:Region:nk]", "[none:Category:nk]"))
        self.assertCaught(m, "which is not on the sheet's rows, columns or marks")

    def test_table_calc_in_lod(self):
        def m(r):
            for c in r.iter("column"):
                if c.get("caption") == "Sales Rank" and c.find("calculation") is not None:
                    c.find("calculation").set("formula", "{FIXED [Region] : RANK(SUM([Sales]))}")
        self.assertCaught(m, "inside a LOD expression")


if __name__ == "__main__":
    unittest.main()
