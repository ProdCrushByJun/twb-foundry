"""Table calculation functions v2 (decisions/147): SIZE, RANK_UNIQUE, RUNNING_AVG / MIN / MAX / COUNT, WINDOW_COUNT /
MEDIAN, PREVIOUS_VALUE; NULL marks and ties; the expected numbers of specs/tablecalc_v2.json; the gate."""
import json
import unittest

from tbuilder import expected, gate
from tbuilder.build import build_file
from test_gate import repack, ws
from test_roundtrip import OUT, ROOT
from tbuilder.formula import CalcSet
from test_tablecalc_funcs import ROWS, TYPES, error, values

SPEC = ROOT / "specs" / "tablecalc_v2.json"


class Evaluate(unittest.TestCase):  # SUM(S) = 15, 30, 20, 30; SUM(X) = 1, NULL, 2, 4
    def test_size_counts_every_mark(self):
        self.assertEqual(values("SIZE()"), [4, 4, 4, 4])
        self.assertEqual(values("SIZE() - INDEX()"), [3, 2, 1, 0])

    def test_rank_unique_breaks_ties_by_position(self):
        self.assertEqual(values("RANK_UNIQUE(SUM([S]))"), [4, 1, 3, 2])
        self.assertEqual(values("RANK_UNIQUE(SUM([S]), 'asc')"), [1, 3, 2, 4])
        self.assertEqual(values("RANK_UNIQUE(SUM([X]))"), [3, None, 2, 1])  # NULL is not ranked

    def test_running_folds_skip_null(self):
        self.assertEqual(values("RUNNING_SUM(SUM([X]))"), [1, 1, 3, 7])
        self.assertEqual(values("RUNNING_AVG(SUM([X]))"), [1, 1, 1.5, 7 / 3])
        self.assertEqual(values("RUNNING_MIN(SUM([X]))"), [1, 1, 1, 1])
        self.assertEqual(values("RUNNING_MAX(SUM([X]))"), [1, 1, 2, 4])
        self.assertEqual(values("RUNNING_COUNT(SUM([X]))"), [1, 1, 2, 3])

    def test_running_over_no_value_is_null(self):
        self.assertEqual(values("RUNNING_COUNT(SUM([X]))", marks=[[ROW] for ROW in
                                                                  [{"R": "a", "C": "p", "S": "1", "X": ""},
                                                                   {"R": "b", "C": "p", "S": "1", "X": "5"}]]),
                         [None, 1])

    def test_window_count_and_median(self):
        self.assertEqual(values("WINDOW_COUNT(SUM([X]))"), [3, 3, 3, 3])
        self.assertEqual(values("WINDOW_COUNT(SUM([X]), -1, 0)"), [1, 1, 1, 2])
        self.assertEqual(values("WINDOW_MEDIAN(SUM([S]), -1, 0)"), [15, 22.5, 25, 25])

    def test_previous_value(self):
        self.assertEqual(values("PREVIOUS_VALUE(0) + SUM([S])"), [15, 45, 65, 95])
        self.assertEqual(values("PREVIOUS_VALUE(0) + SUM([X])"), [1, None, None, None])  # NULL propagates

    def test_types(self):
        for f, t in (("SIZE()", "integer"), ("RANK_UNIQUE(SUM([S]))", "integer"), ("RUNNING_AVG(SUM([S]))", "real"),
                     ("RUNNING_COUNT(SUM([S]))", "integer"), ("WINDOW_MEDIAN(SUM([S]))", "real"),
                     ("WINDOW_COUNT(SUM([S]))", "integer"), ("RUNNING_MAX(SUM([S]))", "integer"),
                     ("PREVIOUS_VALUE(0) + SUM([S])", "integer"), ("PREVIOUS_VALUE(0.5) + SUM([S])", "real")):
            cs = CalcSet([{"name": "T", "formula": f, "compute_using": ["R"]}], TYPES, ROWS)
            self.assertEqual(cs.calcs["T"].datatype, t, f)


class Errors(unittest.TestCase):
    def test_previous_value_needs_aggregate_or_constant(self):
        self.assertIn("row-level", error("PREVIOUS_VALUE([S])"))
        self.assertIn("another table calculation", error("PREVIOUS_VALUE(RANK(SUM([S])))"))
        self.assertIn("number", error("PREVIOUS_VALUE('a')"))

    def test_argument_counts(self):
        for f in ("SIZE(1)", "RANK_UNIQUE()", "RUNNING_AVG()", "RUNNING_COUNT(SUM([S]), 1)", "WINDOW_MEDIAN()",
                  "PREVIOUS_VALUE()"):
            error(f)

    def test_compute_using_is_required(self):
        error("SIZE()", cu=None)


class Numbers(unittest.TestCase):
    def test_expected_matches_the_golden_json(self):
        got = expected.compute(json.loads(SPEC.read_text(encoding="utf-8")), ROOT / "data" / "sample" / "tablecalc_v2.csv")
        want = json.loads((ROOT / "golden" / "expected" / "golden_tablecalc_v2_2025_1.json").read_text(encoding="utf-8"))
        for sheet, marks in got.items():
            for k, v in marks.items():
                w = want[sheet][k]
                self.assertTrue((v is None) == (w is None) and (v is None or abs(v - w) < 1e-3), (sheet, k, v, w))


class GateCatchesTableCalcsV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = build_file(SPEC, OUT / "gate_tablecalc_v2.twbx")

    def test_passes(self):
        self.assertEqual(gate.run(self.src), [])

    def test_calc_without_compute_using(self):
        def m(r):
            for ci in ws(r, "Previous Value").iter("column-instance"):
                for t in ci.findall("table-calc"):
                    ci.remove(t)
        issues = gate.run(repack(m, source=self.src))
        self.assertTrue([i for i in issues if i.check == "tablecalc" and "has no compute-using" in str(i)],
                        [str(i) for i in issues])

    def test_wrong_calc_type(self):
        def m(r):
            for c in r.iter("column"):
                if c.get("caption") == "Running Avg" and c.find("calculation") is not None:
                    c.set("datatype", "integer")  # RUNNING_AVG is real
        issues = gate.run(repack(m, source=self.src))
        self.assertTrue([i for i in issues if i.check == "tablecalc" and "returns real" in str(i)],
                        [str(i) for i in issues])


if __name__ == "__main__":
    unittest.main()
