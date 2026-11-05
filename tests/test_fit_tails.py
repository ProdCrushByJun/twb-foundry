"""The tails of the fit rule (decisions/093): a few fat bars in a tall cell, a long donut legend, a table without the
width for its columns. Each: the builder's refusal, a clean build, the gate's check by mutation, lint D10."""
import copy
import shutil
import tempfile
import unittest
from pathlib import Path

from tbuilder import design_lint, fit, gate

from test_fit import LAB, built, lab, repack

TABLE = {"name": "Table", "type": "table", "title": "**Table** team x region", "rows": "Team", "cols": "Region",
         "measure": {"field": "Sales"}}
BARS = {"name": "Bars", "type": "bar", "title": "**Bars**", "dimension": "Group", "measure": {"field": "Sales"},
        "sort": "desc"}
DONUT = {"name": "Mix", "type": "donut", "title": "**Mix**", "dimension": "Item", "measure": {"field": "Sales"}}


def one(sheet, **dash):
    """The lab's data with one sheet alone on the dashboard."""
    spec = lab("lists")
    spec["sheets"] = [sheet]
    spec["dashboard"].update(grid=[[sheet["name"]]], **dash)
    spec["dashboard"].pop("row_heights", None)
    return spec


def resized(width=None, height=None):
    """A mutation: the dashboard drawn at another size, its zones as they are."""
    def fn(root):
        size = next(root.iter("dashboard")).find("size")
        for key, val in (("width", width), ("height", height)):
            if val:
                for pre in ("min", "max"):
                    size.set(pre + key, str(val))
    return fn


def crowded(path):
    return [i for i in gate.run(path) if i.check == "fit-crowded"]


class Tails(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.bars = built(one(BARS, height=500), name="tails_bars", crowded=True)[0]
        cls.donut = built(one(DONUT, height=560), name="tails_donut", crowded=True)[0]
        cls.table = built(one(TABLE, width=450, height=700), name="tails_table", crowded=True)[0]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def refused(self, spec, pattern, name):
        with self.assertRaisesRegex(ValueError, pattern):
            built(spec, name=name, crowded=True)

    def test_clean_books_pass(self):
        for book in (self.bars, self.donut, self.table):
            self.assertEqual(gate.run(book), [], book.name)

    # -- fat bars ---------------------------------------------------------------------------------------------------
    def test_few_bars_in_a_tall_cell_are_refused(self):
        spec = one(dict(BARS, top={"n": 2}), height=1000)
        self.refused(spec, r"Sheet 'Bars': its bars would stretch to \d+px a row .*over 250px", "tails_fat")

    def test_more_bars_fill_the_same_cell(self):
        built(one(BARS, height=500), name="tails_fat_ok", crowded=True)  # 5 bars in 500px
        with self.assertRaisesRegex(ValueError, "stretch"):
            built(one(BARS, height=1600), name="tails_fat", crowded=True)

    def test_gate_catches_fat_bars(self):
        got = crowded(repack(self.bars, self.tmp / "fat.twbx", resized(height=2000)))
        self.assertEqual(len(got), 1, got)
        self.assertIn("'Bars'", str(got[0]))
        self.assertIn("stretch", str(got[0]))

    # -- donut legend -----------------------------------------------------------------------------------------------
    def test_long_legend_is_refused(self):
        self.refused(one(DONUT, height=420), r"Sheet 'Mix': the legend rows would be \d+px each .*under 16px",
                     "tails_legend")

    def test_gate_catches_a_squeezed_legend(self):
        got = crowded(repack(self.donut, self.tmp / "legend.twbx", resized(height=420)))
        self.assertEqual(len(got), 2, got)  # the dots and the text
        self.assertTrue(all("legend" in str(i) for i in got), got)

    # -- narrow table -----------------------------------------------------------------------------------------------
    def test_table_without_the_width_is_refused(self):
        spec = one(TABLE, width=700, height=700)  # half of 700: the whole 400 (the schema's minimum) is wide enough
        spec["sheets"].append({**TABLE, "name": "Twin"})  # since the outer margins shrank (decision 187)
        spec["dashboard"]["grid"] = [["Table", "Twin"]]
        self.refused(spec, r"Sheet 'Table': its columns need \d+px, the cell leaves \d+px .*scroll it sideways",
                     "tails_narrow")

    def test_gate_does_not_judge_a_table_width_it_cannot_know(self):
        """The packed book keeps no column px of a text sheet (the builder estimates it), so the gate stays silent."""
        got = crowded(repack(self.table, self.tmp / "narrow.twbx", resized(width=400)))
        self.assertEqual(got, [])

    def test_a_matrix_far_wider_than_its_cell_is_left_to_scroll(self):
        """Over NARROW_FAR the table is a scroll by design (a public book's 3761px month matrix), not a miss."""
        far = repack(self.table, self.tmp / "far.twbx", resized(width=140))  # ~3x short of the columns
        self.assertEqual(crowded(far), [])
        near = repack(self.table, self.tmp / "near.twbx", resized(width=460))  # within the estimate's slack
        self.assertEqual(crowded(near), [])

    # -- lint -------------------------------------------------------------------------------------------------------
    def d10(self, spec):
        return [f for f in design_lint.lint(copy.deepcopy(spec), str(LAB)) if f.rule == "D10"]

    def test_lint_d10(self):
        self.assertEqual([f.where for f in self.d10(one(DONUT, height=420))], ["sheet 'Mix'"])
        self.assertEqual(self.d10(one(DONUT, height=560)), [])
        self.assertEqual([f.where for f in self.d10(one(dict(BARS, top={"n": 2}), height=1000))], ["sheet 'Bars'"])
        self.assertEqual(self.d10(one(BARS, height=500)), [])


if __name__ == "__main__":
    unittest.main()
