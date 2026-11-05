"""A chart's min height on a dashboard (decisions/101): the rule (fit.chart_need / short_charts) on the Desktop lab
(tests/fixtures/min_height), the builder's refusal, the gate's check by mutation, lint D9, rebuild's reading."""
import copy
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tbuilder import build as build_mod
from tbuilder import design_lint, fit, gate, rebuild

from test_fit import read, repack

ROOT = Path(__file__).resolve().parent.parent
FIT = ROOT / "tests" / "fixtures" / "fit"
_spec = importlib.util.spec_from_file_location("min_height_lab", ROOT / "tests" / "fixtures" / "min_height" /
                                               "build_lab.py")
LAB = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(LAB)
# (dashboard height, control row weight) of the lab books: 'Line' 60 / 75px inside its margins (build_lab.py)
H60, H75 = (992, 5), (955, 4)


def lab_book(dims, out, check=False):
    """The lab book; check False: built as the lab is, without the min-height check of the builder and the gate."""
    if check:
        return build_mod.build(LAB.spec(*dims), out, base_dir=str(FIT))
    with mock.patch.object(build_mod, "MIN_CHECK", False), mock.patch.object(gate, "check_chart_height",
                                                                             lambda root: []):
        return build_mod.build(LAB.spec(*dims), out, base_dir=str(FIT))


class Rule(unittest.TestCase):
    """The sheets the rule flags are the ones Desktop drew blank or without marks (h60: BarH, Scatter, their 55px
    of axis and title leave 5px; Line / Area / AreaD / BarV / Combo drawn with 30-36px of plot); at 75px none."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.h60 = lab_book(H60, cls.tmp / "h60.twbx")
        cls.h75 = lab_book(H75, cls.tmp / "h75.twbx")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_h60(self):
        short = {name: (have, need) for _, name, have, need in fit.short_charts(read(self.h60))}
        self.assertEqual(short, {"BarH": (60, 75), "Scatter": (60, 75)})

    def test_h75(self):
        self.assertEqual(fit.short_charts(read(self.h75)), [])

    def test_not_charts(self):
        """A heatmap (no axis) and a text table have no chart height; a map neither (its generated lat / long)."""
        root = read(self.h60)
        ws = {w.get("name"): w for w in root.iter("worksheet")}
        zone = next(z for z in root.iter("zone") if z.get("name") == "Heat")
        self.assertIsNone(fit.chart_need(ws["Heat"], zone, (1600, 992)))

    def test_builder_refuses(self):
        with self.assertRaises(ValueError) as e:
            lab_book(H60, self.tmp / "refused.twbx", check=True)
        self.assertRegex(str(e.exception), r"Sheet '(BarH|Scatter)': the cell is too short for a chart \(60px .*"
                                           r"75px needed")
        self.assertFalse((self.tmp / "refused.twbx").exists())

    def test_builder_message_read_by_rebuild(self):
        """rebuild's fit (decisions/066) gives the sheet's row more height on 'too short' (a public book Weekly Sales Trend)."""
        try:
            lab_book(H60, self.tmp / "refused.twbx", check=True)
        except ValueError as e:
            m = rebuild._CELL_ERROR.match(str(e))
        self.assertEqual((m.group(1) in ("BarH", "Scatter"), m.group(2)), (True, "short"))


class GateCatchesShortChart(unittest.TestCase):
    """The 75px lab book passes; its Scatter zone 10px shorter (65px, the axes drawn without marks) is refused."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.book = lab_book(H75, cls.tmp / "h75.twbx", check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_clean(self):
        self.assertEqual(gate.run(self.book), [])

    def test_shorter_zone(self):
        def fn(root):
            z = next(z for z in root.iter("zone") if z.get("name") == "Scatter")
            z.set("h", str(int(z.get("h")) - 10 * fit.FULL // H75[0] - 1))
        got = [str(i) for i in gate.run(repack(self.book, self.tmp / "m.twbx", fn)) if i.check == "chart-height"]
        self.assertEqual(len(got), 1, got)
        self.assertIn("sheet 'Scatter': 65px high inside its margins, 75px needed", got[0])


class Lint(unittest.TestCase):
    def test_d9(self):
        spec = LAB.spec(*H60)
        found = {f.where for f in design_lint.lint(copy.deepcopy(spec), str(FIT)) if f.rule == "D9"}
        self.assertIn("sheet 'Scatter'", found)
        self.assertNotIn("sheet 'Line ctl'", found)  # the tall control row
        self.assertNotIn("sheet 'Heat'", found)  # no axis
        spec["dashboard"]["row_heights"] = [3, 3, 3]
        spec["dashboard"]["height"] = 960
        self.assertEqual([f for f in design_lint.lint(spec, str(FIT)) if f.rule == "D9"], [])


if __name__ == "__main__":
    unittest.main()
