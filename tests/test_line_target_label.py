"""A line's reference label apart from the series' end labels (decisions/184): 'target 95' does not cover 'City 95'
at equal or close values, a far line stays where Desktop puts it by default.

Run: python -m unittest discover -s tests
"""
import csv
import tempfile
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import gate, reflines
from tbuilder.build import build
from tbuilder.reflines import label_slots

TOP, BOTTOM = ("right", "top"), ("right", "bottom")
LEFT, LEFT_BOTTOM = ("left", "top"), ("left", "bottom")
SERIES = {"City": [92, 93, 91, 94, 93, 95, 94, 96, 94, 95, 94, 95.0],
          "Suburb": [85, 86, 84, 88, 86, 85, 87, 86, 89, 87, 88, 88.0],
          "Region": [90, 91, 92, 90, 93, 92, 93, 94, 92, 93, 94, 93.5]}
# the lab's plot: 260px, 90% of it over 84..96: 19.5px a unit
PLOT = dict(plot_px=260, lo=84, hi=96)


def slot(target, last, first=()):
    return label_slots(refs=[target], ends={"right": list(last), "left": list(first)}, **PLOT)[0]


class Slots(unittest.TestCase):
    def test_equal_value_goes_below_its_line(self):
        self.assertEqual(slot(95, [95]), BOTTOM)

    def test_close_below_the_end_label_goes_below(self):
        self.assertEqual(slot(94.7, [95]), BOTTOM)

    def test_close_above_within_both_slots_goes_left(self):
        """0.6 of a unit (12px) above the point: its default slot touches the end label, the slot under its
        line touches it too."""
        self.assertEqual(slot(95.6, [95]), LEFT)

    def test_just_clear_stays(self):
        self.assertEqual(slot(95.9, [95]), TOP)

    def test_far_stays_at_the_default(self):
        self.assertEqual(slot(90, [95]), TOP)
        self.assertEqual(slot(95, [88]), TOP)

    def test_another_series_under_the_line_goes_left(self):
        """One series ends on the line, another just under it: neither slot on the right is free."""
        self.assertEqual(slot(95, [95, 94.3]), LEFT)

    def test_first_values_block_the_left(self):
        self.assertEqual(slot(95, [95, 94.3], first=[95]), LEFT_BOTTOM)

    def test_two_lines_do_not_share_a_slot(self):
        ends = {"right": [90], "left": []}
        self.assertEqual(label_slots(refs=[95, 95], ends=ends, **PLOT), [TOP, BOTTOM])

    def test_nothing_clear_takes_the_farthest(self):
        ends = {"right": [95, 94.3, 95.6], "left": [95, 94.3, 95.6]}
        got = label_slots(refs=[95], ends=ends, **PLOT)[0]
        self.assertIn(got, reflines.LABEL_SLOTS)

    def test_flat_series_has_a_scale(self):
        self.assertEqual(label_slots(100, 5, 5, {"right": [5]}, [5]), [BOTTOM])


def spec(target, **sheet):
    base = dict(name="Lab", type="line", title="On time", date={"field": "Month", "level": "month"},
                measure={"field": "OnTime", "agg": "avg"}, color="Zone", labels="last",
                reference={"type": "const", "value": target, "label": "target"})
    base.update(sheet)
    base = {k: v for k, v in base.items() if v is not None}
    return {"version": 1, "datasource": {"type": "csv", "path": "ontime.csv"}, "sheets": [base],
            "dashboard": {"name": "Board", "title": "Board", "width": 1000, "height": 700, "grid": [["Lab"]]}}


class Built(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        with open(cls.dir / "ontime.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Month", "Zone", "OnTime"])
            for zone, vals in SERIES.items():
                w.writerows((f"2025-{i + 1:02d}-01", zone, v) for i, v in enumerate(vals))

    def twbx(self, target, **sheet):
        return build(spec(target, **sheet), self.dir / f"t{target}.twbx", self.dir)

    def forms(self, target, **sheet):
        with zipfile.ZipFile(self.twbx(target, **sheet)) as z:
            root = etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))
        rule = next(root.iter("worksheet")).find("table/style/style-rule[@element='refline']")
        return {f.get("attr"): f.get("value") for f in rule if f.get("attr") in ("text-align", "vertical-align")}

    def test_equal_value_writes_below(self):
        self.assertEqual(self.forms(95), {"text-align": "right", "vertical-align": "bottom"})

    def test_far_writes_nothing_new(self):
        self.assertEqual(self.forms(90.5), {"text-align": "right"})

    def test_no_end_labels_writes_nothing_new(self):
        self.assertEqual(self.forms(95, labels=None), {"text-align": "right"})

    def test_gate_catches_a_bad_value(self):
        for attr in ("vertical-align", "text-align"):
            with zipfile.ZipFile(self.twbx(95)) as z:
                root = etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))
            rule = next(root.iter("worksheet")).find("table/style/style-rule[@element='refline']")
            rule.find(f"format[@attr='{attr}']").set("value", "middle")
            issues = gate.check_reference_lines(root)
            self.assertTrue(any(attr in i.message and "middle" in i.message for i in issues), issues)

    def test_gate_passes_the_generator(self):
        with zipfile.ZipFile(self.twbx(95)) as z:
            root = etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))
        self.assertEqual(gate.check_reference_lines(root), [])


if __name__ == "__main__":
    unittest.main()
