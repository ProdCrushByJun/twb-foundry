"""D11 (decisions/107): the rows of a heatmap / registry need more px than its cell leaves."""
import copy
import tempfile
import unittest
from pathlib import Path

from tbuilder.design_lint import lint
from tests.test_design_lint import BASE, CSV

HEAT = {"name": "Heat", "type": "heatmap", "rows": "Region", "cols": "Month", "measure": {"field": "Sales"}}
REG = {"name": "Reg", "type": "registry", "rows": ["Region"], "sort": "none",
       "columns": [{"measure": {"field": "Sales"}, "style": "text", "label": "Sales"}]}


class CellShortTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        (cls.dir / "data.csv").write_text(CSV, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def found(self, sheet, weights, **extra):
        s = copy.deepcopy(BASE)
        s["sheets"].append({**copy.deepcopy(sheet), **extra})
        s["dashboard"].update(grid=[["KPI"], [sheet["name"]]], row_heights=weights)
        return [f for f in lint(s, self.dir) if f.rule == "D11"]

    def test_short_heatmap_is_flagged_with_the_needed_px(self):
        f = self.found(HEAT, [5, 1])  # 50px for 6 rows of 20px and a 24px header
        self.assertEqual([x.level for x in f], ["warn"])
        self.assertIn("144px", f[0].text)

    def test_short_registry_is_flagged(self):
        self.assertEqual(len(self.found(REG, [3, 1])), 1)  # 110px for 6 rows of 20px

    def test_cell_that_fits_is_clean(self):
        self.assertEqual(self.found(HEAT, [1, 1]), [])
        self.assertEqual(self.found(REG, [1, 1]), [])

    def test_top_n_counts_only_the_shown_rows(self):
        self.assertEqual(self.found(REG, [3, 1], top={"n": 3}), [])  # 3 rows of 20px fit in 110px
