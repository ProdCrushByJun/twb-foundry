"""A heatmap drawn in divs: a number counts as checked only if its value and its place both agree (decisions/200)."""
import tempfile
import unittest
from pathlib import Path

from tbuilder import html_outline, insight, reconcile, reconcile_grid

ROWS = ["Groups", "Direct", "Other"]
COLS = ["0-7", "8-30", "181+"]
GRID = [[17, 34, 71], [8, 19, 26], [14, 18, 0]]
ROW_TOTALS = [61, 15, 16]
COL_TOTALS = [10, 28, 57]
X0, Y0, DX, DY = 100, 60, 100, 36
HEAT = "Heat"
SPEC = {"datasource": {"csv": "x.csv"}, "sheets": [{"name": HEAT, "type": "heatmap"}]}


def outline(grid=GRID, row_totals=ROW_TOTALS, col_totals=COL_TOTALS):
    """Cells as wide as their column; totals are small and off the lines of the grid, as bars push them."""
    texts, labels = [], []
    for r, row in enumerate(grid):
        for c, v in enumerate(row):
            texts.append({"text": f"{v}%", "box": [X0 + c * DX, Y0 + r * DY, 96, 32], "grid": 0})
        texts.append({"text": f"{row_totals[r]}%", "box": [X0 + 3 * DX + 20 + 15 * r, Y0 + r * DY + 9, 24, 14],
                      "grid": 0})
        labels.append({"grid": 0, "text": ROWS[r], "box": [0, Y0 + r * DY, 96, 32]})
    for c, name in enumerate(COLS):
        texts.append({"text": f"{col_totals[c]}%", "box": [X0 + c * DX + 36, Y0 - 40 - 11 * c, 24, 14], "grid": 0})
        labels.append({"grid": 0, "text": name, "box": [X0 + c * DX, Y0 - 18, 96, 14]})
    return {"texts": texts, "grid_labels": labels}


def entries(grid=GRID):
    out = [reconcile._entry(HEAT, f"{r} | {c}", ["Cancelled"], grid[i][j] / 100, fmt="pct0")
           for i, r in enumerate(ROWS) for j, c in enumerate(COLS)]
    out += [reconcile._entry(f"{HEAT} · Row Totals", r, ["Cancelled"], ROW_TOTALS[i] / 100, fmt="pct0")
            for i, r in enumerate(ROWS)]
    out += [reconcile._entry(f"{HEAT} · Column Totals", c, ["Cancelled"], COL_TOTALS[i] / 100, fmt="pct0")
            for i, c in enumerate(COLS)]
    return out


def run(out):
    es = entries()
    fs = reconcile.facts(out)
    reconcile._match(fs, es, reconcile._Names(SPEC, es), [])
    return fs


def statuses(fs):
    return sorted({f["status"] for f in fs})


class Place(unittest.TestCase):
    def test_cells_and_totals_get_their_place(self):
        out = reconcile_grid.annotate(outline())
        by = {t["text"]: t.get("cell") for t in out["texts"]}
        self.assertEqual(by["34%"], {"row": "Groups", "col": "8-30"})
        self.assertEqual(by["61%"], {"row": "Groups", "col": ""})
        self.assertEqual(by["57%"], {"row": "", "col": "181+"})

    def test_all_match(self):
        self.assertEqual(statuses(run(outline())), ["matched"])

    def test_swapped_cells_do_not_pass(self):
        """The same values, each one in the other's cell: without the place both would still be found in the book."""
        swapped = [[34, 17, 71]] + GRID[1:]
        fs = run(outline(grid=swapped))
        self.assertEqual(sorted(f["number"] for f in fs if f["status"] == "mismatch"), ["17%", "34%"])

    def test_wrong_row_total_does_not_pass(self):
        fs = run(outline(row_totals=[62, 15, 16]))
        self.assertEqual([f["number"] for f in fs if f["status"] == "mismatch"], ["62%"])

    def test_wrong_column_total_does_not_pass(self):
        fs = run(outline(col_totals=[11, 28, 57]))
        self.assertEqual([f["number"] for f in fs if f["status"] == "mismatch"], ["11%"])

    def test_a_row_without_a_label_binds_nothing(self):
        out = outline()
        out["grid_labels"] = [lb for lb in out["grid_labels"] if lb["text"] != "Direct"]
        reconcile_grid.annotate(out)
        self.assertFalse([t for t in out["texts"] if "cell" in t])
        self.assertNotIn("matched", statuses(run(out)))

    def test_numbers_of_other_scopes_are_not_cells(self):
        out = outline()
        for t in out["texts"]:
            t["grid"] = None
        self.assertFalse([t for t in reconcile_grid.annotate(out)["texts"] if "cell" in t])

    def test_a_scattered_scope_is_no_grid(self):
        out = {"texts": [{"text": str(i), "box": [i * 37, i * 53, 20, 14], "grid": 0} for i in range(1, 10)],
               "grid_labels": [{"grid": 0, "text": "Name", "box": [0, 0, 20, 14]}]}
        self.assertFalse([t for t in reconcile_grid.annotate(out)["texts"] if "cell" in t])


class BandNames(unittest.TestCase):
    def test_the_numbers_of_a_band_are_its_name(self):
        es = entries()
        out = {"texts": [{"text": "0-7", "box": [0, 0, 20, 14]}, {"text": "181+", "box": [0, 20, 20, 14]}]}
        fs = reconcile.facts(out)
        reconcile._match(fs, es, reconcile._Names(SPEC, es), [])
        self.assertEqual({f["number"]: f["reason"] for f in fs if f["status"] == "skipped"},
                         {"0": "part of a name", "7": "part of a name", "181": "part of a name"})


class Sentence(unittest.TestCase):
    PHRASE = (insight._words("Within a week"), [])

    def fact(self, text="10%", up=("10%", "Within a week 10% ; 181+ days 57%"), inline=True):
        item = {"text": text, "box": [0, 0, 30, 14], "up": list(up)}
        if inline:
            item["inline"] = True
        return reconcile.facts({"texts": [item]})[0]

    def test_inline_number_reads_the_words_around_it(self):
        self.assertTrue(insight.next_to(self.fact(), self.PHRASE))

    def test_block_number_is_not_in_the_sentence(self):
        """A card's big number sits next to '33,102 of 79,330': no phrase of the note may claim it."""
        self.assertFalse(insight.next_to(self.fact(inline=False), self.PHRASE))

    def test_other_words_do_not_claim_it(self):
        self.assertFalse(insight.next_to(self.fact(), (["booked", "ahead"], [])))

    def test_same_number_twice_in_the_sentence_binds_nothing(self):
        f = self.fact(up=("10%", "Within a week 10% ; later 10%"))
        self.assertNotIn("around", f)


@unittest.skipUnless(Path(html_outline.CHROME_CANDIDATES[0]).is_file(), "Chrome not installed")
class Browser(unittest.TestCase):
    """outline.js on a real page: scope and labels of a css grid."""
    PAGE = """<!doctype html><html><head><style>
.h{display:grid;grid-template-columns:100px repeat(3,100px) 120px;gap:2px;width:520px}
.c{text-align:center;height:34px}.m{height:60px;display:flex;flex-direction:column-reverse;align-items:center}.m i{display:block;width:40px}
.s{display:flex;align-items:center;gap:4px}.s i{display:block;height:10px}
</style></head><body><div class="i">Within a week <b>10%</b> cancel</div><div class="h">
<div></div><div class="m"><i style="height:9px"></i><b>10%</b></div><div class="m"><i style="height:20px"></i><b>28%</b></div>
<div class="m"><i style="height:40px"></i><b>57%</b></div><div></div>
<div></div><div class="t">0-7</div><div class="t">8-30</div><div class="t">181+</div><div>All</div>
<div class="r">Groups</div><div class="c">17%</div><div class="c">34%</div><div class="c">71%</div>
<div class="s"><i style="width:50px"></i><b>61%</b></div>
<div class="r">Direct</div><div class="c">8%</div><div class="c">19%</div><div class="c">26%</div>
<div class="s"><i style="width:20px"></i><b>15%</b></div>
<div class="r">Other</div><div class="c">14%</div><div class="c">18%</div><div class="c">0%</div>
<div class="s"><i style="width:21px"></i><b>16%</b></div>
</div></body></html>"""

    def test_a_css_grid_is_named(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "page.html"
            p.write_text(self.PAGE, encoding="utf-8")
            out = html_outline.outline(p)
        reconcile_grid.annotate(out)
        by = {}
        for t in out["texts"]:
            by.setdefault(t["text"], t)
        self.assertEqual(by["34%"]["cell"], {"row": "Groups", "col": "8-30"})
        self.assertEqual(by["15%"]["cell"], {"row": "Direct", "col": ""})
        self.assertEqual(by["57%"]["cell"], {"row": "", "col": "181+"})
        phrase = next(t for t in out["texts"] if t["text"] == "10%" and "cell" not in t)
        self.assertTrue(phrase["inline"])


if __name__ == "__main__":
    unittest.main()
