"""Axis ticks are skipped whatever the subpixel layout of the browser (decisions/116)."""
import unittest

from tbuilder import reconcile


def tick(v, x, y, w, svg=0):
    return {"text": str(v), "box": [x, y, w, 16], "up": [str(v)], "svg": svg}


def skipped(items):
    fs = reconcile.facts({"texts": items})
    return [f["status"] == "skipped" and f.get("reason") == "axis tick" for f in fs]


class AxisTicks(unittest.TestCase):
    def test_right_edges_split_by_a_grid_boundary(self):
        # right edges 214, 215, 215, 214, 214: a fixed grid of 3 px put them in two buckets (Chrome 156)
        items = [tick(0, 207, 539, 7), tick(25, 201, 483, 14), tick(50, 201, 427, 14), tick(75, 201, 372, 13),
                 tick(100, 194, 316, 20)]
        self.assertEqual(skipped(items), [True] * 5)

    def test_same_ticks_shifted_by_a_subpixel(self):
        for shift in (0, 1, 2):
            items = [tick(v, 200 - len(str(v)) * 7 + shift, y, len(str(v)) * 7)
                     for v, y in ((0, 539), (25, 483), (50, 427), (75, 372), (100, 316))]
            self.assertEqual(skipped(items), [True] * 5, shift)

    def test_data_labels_are_not_a_progression(self):
        items = [tick(72, 268, 368, 14), tick(72, 376, 368, 14), tick(80, 484, 351, 14), tick(82, 592, 346, 14)]
        self.assertEqual(skipped(items), [False] * 4)

    def test_labels_in_one_column_without_equal_steps_stay(self):
        items = [tick(v, 100, 20 * i, 14) for i, v in enumerate((72, 80, 91))]
        self.assertEqual(skipped(items), [False] * 3)


if __name__ == "__main__":
    unittest.main()
