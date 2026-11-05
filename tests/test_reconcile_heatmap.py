"""Cells of a heatmap drawn as svg texts are named by their axis labels and checked (decisions/127)."""
import unittest

from tbuilder import reconcile

DEPTS = ["Engineering", "Sales", "Support"]
MONTHS = ["Jan", "Feb", "Mar"]
GRID = [[3, 5, 8], [4, 6, 9], [2, 7, 10]]  # rows = departments, cols = months
X0, Y0, DX, DY = 100, 40, 60, 30


def outline(grid=GRID, labels=True, svg=0):
    texts, names = [], []
    for r, row in enumerate(grid):
        for c, v in enumerate(row):
            texts.append({"text": str(v), "box": [X0 + c * DX - 6, Y0 + r * DY - 8, 12, 16], "svg": svg})
    for c, m in enumerate(MONTHS):
        names.append({"svg": svg, "text": m, "box": [X0 + c * DX - 10, Y0 + 3 * DY, 20, 16]})
    for r, d in enumerate(DEPTS):
        names.append({"svg": svg, "text": d, "box": [X0 - 100, Y0 + r * DY - 8, 70, 16]})
    return {"texts": texts, "svg_labels": names if labels else []}


SPEC = {"datasource": {"csv": "x.csv"}, "sheets": [{"name": "Exit Heatmap", "type": "heatmap"}]}


def entries(grid=GRID):
    return [reconcile._entry("Exit Heatmap", f"{d} | 2025-{c + 1:02d}", ["Exits"], grid[r][c])
            for r, d in enumerate(DEPTS) for c in range(3)]


def run(out, es):
    fs = reconcile.facts(out)
    reconcile._match(fs, es, reconcile._Names(SPEC, es), [])
    return fs


class Heatmap(unittest.TestCase):
    def test_cells_get_row_and_column(self):
        out = outline()
        reconcile.facts(out)
        self.assertEqual(out["texts"][0]["cell"], {"row": "Engineering", "col": "Jan"})
        self.assertEqual(out["texts"][8]["cell"], {"row": "Support", "col": "Mar"})

    def test_cells_match_the_workbook(self):
        fs = run(outline(), entries())
        self.assertEqual([f["status"] for f in fs], ["matched"] * 9)

    def test_a_wrong_cell_is_a_mismatch(self):
        shown = [[3, 5, 8], [4, 6, 9], [2, 7, 12]]
        fs = run(outline(shown), entries())
        self.assertEqual([f["status"] for f in fs].count("mismatch"), 1)
        self.assertEqual(fs[8]["status"], "mismatch")

    def test_a_zero_cell_without_a_mark_is_not_a_mismatch(self):
        shown = [[3, 5, 8], [4, 0, 9], [2, 7, 10]]  # the workbook has no mark for Sales | Feb (no events)
        es = [e for e in entries() if e["key"] != "Sales | 2025-02"]
        fs = run(outline(shown), es)
        self.assertEqual(fs[4]["status"], "unverified")
        self.assertEqual([f["status"] for f in fs].count("matched"), 8)

    def test_a_zero_cell_against_a_nonzero_mark_is_a_mismatch(self):
        shown = [[3, 5, 8], [4, 0, 9], [2, 7, 10]]
        self.assertEqual(run(outline(shown), entries())[4]["status"], "mismatch")

    def test_cells_are_not_axis_ticks(self):
        fs = run(outline([[1, 2, 3], [4, 5, 6], [7, 8, 9]]), entries([[1, 2, 3], [4, 5, 6], [7, 8, 9]]))
        self.assertNotIn("axis tick", [f.get("reason") for f in fs])

    def test_without_labels_nothing_is_guessed(self):
        out = outline(labels=False)
        reconcile.facts(out)
        self.assertTrue(all("cell" not in t for t in out["texts"]))

    def test_a_column_of_ticks_is_no_grid(self):
        out = {"texts": [{"text": str(v), "box": [20, 100 - v * 5, 12, 16], "svg": 0} for v in (0, 10, 20, 30)],
               "svg_labels": [{"svg": 0, "text": "Jan", "box": [20, 140, 20, 16]}]}
        fs = reconcile.facts(out)
        self.assertEqual({f["reason"] for f in fs}, {"axis tick"})


if __name__ == "__main__":
    unittest.main()
