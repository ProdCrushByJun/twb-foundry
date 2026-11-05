"""Points of an svg line without labels are read against the value axis and checked (decisions/123)."""
import unittest

from tbuilder import reconcile

# value axis 0..40K: gridlines at y = 200, 150, 100, 50 (10K = 50 px, 200 px/ 40K), tick texts 16 px high
HLINES = [200.0, 150.0, 100.0, 50.0, 0.0]
VALUES = [0, 10, 20, 30, 40]


def ticks(svg=0, hlines=True):
    return [{"text": f"${v}K", "box": [20, round(h - 8), 24, 16], "up": [f"${v}K"], "svg": svg}
            for v, h in zip(VALUES, HLINES)]


def outline(points, hlines=HLINES, items=None):
    return {"texts": items if items is not None else ticks(),
            "lines": [{"svg": 0, "polylines": [[[60 + 20 * i, y] for i, y in enumerate(points)]],
                       "hlines": hlines}]}


def y_of(v):
    return 200 - v / 200.0  # px for a value: 200 px per 40000


SPEC = {"datasource": {"csv": "x.csv"}, "sheets": [{"name": "By Month", "type": "line"}]}


def ents(values, sheet="By Month"):
    return [reconcile._entry(sheet, f"2024-{i + 1:02d}", ["Cost"], v) for i, v in enumerate(values)]


def run(out, es):
    fs = reconcile.facts(out)
    reconcile._match(fs, es, reconcile._Names(SPEC, es), [])
    return [f for f in fs if f.get("line")]


class UnlabeledLine(unittest.TestCase):
    VALS = [12000, 25000, 18000, 31000]

    def test_points_match_the_series(self):
        got = run(outline([y_of(v) for v in self.VALS]), ents(self.VALS))
        self.assertEqual([f["status"] for f in got], ["matched"] * 4)
        self.assertIn("By Month [2024-01]", got[0]["workbook"])

    def test_a_wrong_point_is_a_mismatch(self):
        shown = [12000, 25000, 24000, 31000]  # the page draws 24000 where the workbook has 18000
        got = run(outline([y_of(v) for v in shown]), ents(self.VALS))
        self.assertEqual([f["status"] for f in got], ["matched", "matched", "mismatch", "matched"])

    def test_axis_ticks_stay_skipped(self):
        fs = reconcile.facts(outline([y_of(v) for v in self.VALS]))
        self.assertEqual([f["reason"] for f in fs if f.get("svg") == 0], ["axis tick"] * 5)

    def test_no_sheet_of_that_length_is_skipped_with_the_reason(self):
        got = run(outline([y_of(v) for v in self.VALS]), ents(self.VALS + [1000]))
        self.assertEqual({f["status"] for f in got}, {"skipped"})
        self.assertIn("no sheet of the workbook has 4 dated points", got[0]["reason"])

    def test_without_gridlines_the_tick_texts_give_the_scale(self):
        got = run(outline([y_of(v) for v in self.VALS], hlines=[]), ents(self.VALS))
        self.assertEqual([f["status"] for f in got], ["matched"] * 4)

    def test_no_axis_is_one_skipped_fact(self):
        got = run(outline([20, 40, 30, 50], items=[]), ents(self.VALS))
        self.assertEqual([(f["status"], "no value axis" in f["reason"]) for f in got], [("skipped", True)])

    def test_a_labelled_line_is_left_to_its_labels(self):
        label = {"text": "12,000", "box": [60, 140, 30, 12], "up": ["12,000"], "svg": 0}
        fs = reconcile.facts(outline([y_of(v) for v in self.VALS], items=ticks() + [label]))
        self.assertEqual([f for f in fs if f.get("line")], [])

    def test_uneven_ticks_are_not_read(self):
        odd = ticks()
        odd[2]["box"][1] += 30
        got = run(outline([y_of(v) for v in self.VALS], hlines=[], items=odd), ents(self.VALS))
        self.assertEqual([f["status"] for f in got], ["skipped"])


if __name__ == "__main__":
    unittest.main()
