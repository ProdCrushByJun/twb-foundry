"""The regression runner itself (decisions/027): on a small copy of the repo, a clean case is OK, a broken one FAILs,
a new folder is picked up. The unit and mutation stages are not run here (they would run this file again)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tbuilder import desktop_check as dc
from tbuilder import regress
from test_roundtrip import ROOT



def rows_of(rows, case=None, stage=None):
    return [r for r in rows if (case is None or r.case == case) and (stage is None or r.stage == stage)]


def fails(rows):
    return [(r.case, r.stage, r.reason) for r in rows if r.status == regress.FAIL]




class Rows(unittest.TestCase):
    def test_mutation_that_slips_through_fails(self):
        outcomes = [("test_gate.GateCatches.test_a", "GateCatches", regress.OK, ""),
                    ("test_gate.GateCatches.test_b", "GateCatches", regress.FAIL, "failure: ...\nAssertionError: x"),
                    ("test_x.Other.test_c", "Other", regress.FAIL, "failure")]
        rows = regress.mutation_rows(outcomes)
        self.assertEqual([(r.case, r.status) for r in rows], [("mutation/test_gate.GateCatches.test_a", regress.OK),
                                                              ("mutation/test_gate.GateCatches.test_b", regress.FAIL)])
        self.assertEqual(rows[1].reason, "AssertionError: x")
        self.assertEqual(regress.mutation_rows(outcomes[2:])[0].status, regress.FAIL)  # no mutation tests at all
        unit = regress.unit_rows(outcomes)
        self.assertEqual([(r.case, r.status) for r in unit], [("unit", regress.FAIL),
                                                              ("unit/test_gate.GateCatches.test_b", regress.FAIL),
                                                              ("unit/test_x.Other.test_c", regress.FAIL)])

    def test_run_tests_collects_each_outcome(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        (d / "test_fake_regress_mutations.py").write_text(
            "import unittest\n"
            "class GateCatchesFake(unittest.TestCase):\n"
            "    def test_caught(self):\n        pass\n"
            "    def test_slips(self):\n        self.fail('not caught')\n"
            "    def test_sub(self):\n"
            "        for i in (1, 2):\n"
            "            with self.subTest(i=i):\n                self.assertEqual(i, 1)\n", encoding="utf-8")
        got = {(t.rsplit(".", 1)[-1], s) for t, _, s, _ in regress.run_tests(d)}
        self.assertEqual(got, {("test_caught", regress.OK), ("test_slips", regress.FAIL),
                               ("test_sub (i=2)", regress.FAIL)})

    def test_compare(self):
        got = {"KPI": {"SUM(Sales)": 224710.4}, "Bar": {"East | Tech": 10.0, "East | Office": 5.0},
               "Reg": {"East": {"Total": 47.0}}, "Pct": {"x": 7.74}}
        self.assertEqual(regress.compare({"_source": "README", "KPI": {"SUM(Sales)": 224710}, "Bar": {"East": 15},
                                          "Reg": {"East": {"Total": 47}}, "Pct": {"x": 7.7}}, got), [])
        self.assertEqual(regress.compare({"KPI": {"SUM(Sales)": 224712}, "Bar": {"West": 1}, "Pct": {"x": 7.8},
                                          "Nope": {"a": 1}}, got),
                         ["KPI / SUM(Sales): 224710.4 != 224712", "Bar / West: not in the computed numbers",
                          "Pct / x: 7.74 != 7.8", "Nope: not in the computed numbers"])


if __name__ == "__main__":
    unittest.main()
