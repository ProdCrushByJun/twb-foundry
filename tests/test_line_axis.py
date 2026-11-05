"""A line's value axis and its end labels (decisions/170): Include zero off by default for a share, a mean or a ratio,
a fixed range from axis {min, max}, the axis wide enough for its top tick, 'series value' at the line's end, a
reference line's label at the right.

Run: python -m unittest discover -s tests
"""
import copy
import unittest
import zipfile

from lxml import etree

from tbuilder import design, ink
from tbuilder.build import build
from tbuilder.spec import SpecError, validate
from test_roundtrip import ROOT, SPECS

MONTH = {"field": "Order Date", "level": "month"}
SPEC = {
    "version": 1,
    "datasource": {"type": "csv", "path": "../data/sample/sales_2y.csv"},
    "calcs": [{"name": "Margin", "formula": "SUM([Profit]) / SUM([Sales]) * 100",
               "format": {"type": "number", "decimals": 1}}],
    "sheets": [
        {"name": "Sum", "type": "line", "title": "Sales", "date": MONTH, "measure": {"field": "Sales"}},
        {"name": "Avg", "type": "line", "title": "Average sale", "date": MONTH,
         "measure": {"field": "Sales", "agg": "avg"}, "color": "Region", "labels": "last"},
        {"name": "Ratio", "type": "line", "title": "Margin", "date": MONTH, "measure": {"field": "Margin"},
         "color": {"highlight": ["West"], "field": "Region"}, "labels": "last",
         "reference": {"type": "const", "value": 12, "label": "target"}},
        {"name": "Fixed", "type": "line", "title": "Margin, fixed", "date": MONTH, "measure": {"field": "Margin"},
         "axis": {"min": -100, "max": 100}},
        {"name": "Zero", "type": "line", "title": "Average sale from zero", "date": MONTH,
         "measure": {"field": "Sales", "agg": "avg"}, "axis": {"zero": True}},
    ],
    "dashboard": {"name": "Line axis", "title": "Line axis", "width": 1400, "height": 1000,
                  "grid": [["Sum", "Avg", "Ratio"], ["Fixed", "Zero"]]},
}


def built(spec, name="line_axis_test"):
    out = build(spec, ROOT / "out" / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return etree.fromstring(z.read(out.stem + ".twb"))


def axis_encoding(root, name):
    w = next(w for w in root.iter("worksheet") if w.get("name") == name)
    return w.find("table/style/style-rule[@element='axis']/encoding"), w


class LineAxis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(copy.deepcopy(SPEC))

    def test_sum_keeps_zero(self):
        enc, _ = axis_encoding(self.root, "Sum")
        self.assertIsNone(enc)

    def test_mean_and_ratio_drop_zero(self):
        for name in ("Avg", "Ratio"):
            enc, _ = axis_encoding(self.root, name)
            self.assertEqual(enc.get("domain-expand"), "false", name)
            self.assertEqual(enc.get("scope"), "rows")
            self.assertIsNone(enc.get("range-type"))

    def test_zero_override(self):
        enc, _ = axis_encoding(self.root, "Zero")
        self.assertIsNone(enc)

    def test_fixed_range(self):
        enc, _ = axis_encoding(self.root, "Fixed")
        self.assertEqual((enc.get("range-type"), enc.get("min"), enc.get("max")), ("fixed", "-100", "100"))
        self.assertIsNone(enc.get("domain-expand"))

    def test_fixed_range_must_hold_the_values(self):
        spec = copy.deepcopy(SPEC)
        spec["sheets"][3]["axis"] = {"min": 50, "max": 100}
        with self.assertRaisesRegex(ValueError, "cuts the values"):
            built(spec, "line_axis_cut")

    def test_schema(self):
        for axis in ({"min": 0}, {"max": 1}, {"zero": "no"}, {"step": 5}):
            spec = copy.deepcopy(SPEC)
            spec["sheets"][3]["axis"] = axis
            with self.assertRaises(SpecError, msg=axis):
                validate(spec)

    def test_end_labels_name_the_series(self):
        for name in ("Avg", "Ratio"):
            _, w = axis_encoding(self.root, name)
            pane = w.find("table/panes/pane")
            texts = [t.get("column") for t in pane.findall("encodings/text")]
            self.assertTrue(texts[0].endswith("[none:Region:nk]"), name)
            runs = [r.text for r in pane.findall("customized-label/formatted-text/run")]
            self.assertEqual(runs, [f"<{texts[0]}>", f" <{texts[1]}>"])
            kids = [k.tag for k in pane]
            self.assertEqual(kids.index("customized-label") + 1, kids.index("style"))
            cull = pane.find("style/style-rule[@element='mark']/format[@attr='mark-labels-cull']")
            self.assertEqual(cull.get("value"), "true")  # a muted label that would overlap is not drawn

    def test_reference_label_right(self):
        _, w = axis_encoding(self.root, "Ratio")
        rule = w.find("table/style/style-rule[@element='refline']")
        self.assertEqual(rule.find("format[@attr='text-align']").get("value"), "right")

    def test_axis_holds_the_top_tick(self):
        # '100.0' is 5 characters (36px by count) but 40px at 9pt: Desktop clipped it to '10..' (gaps #17)
        need = design.text_px("100.0", ink.AXIS_TICK_PT) + ink.AXIS_TICK_PAD_PX
        _, w = axis_encoding(self.root, "Fixed")  # axis to 100, one decimal: the top tick reads '100.0'
        width =w.find("table/style/style-rule[@element='axis']/format[@attr='width']")
        self.assertGreaterEqual(int(width.get("value")), need)


if __name__ == "__main__":
    unittest.main()
