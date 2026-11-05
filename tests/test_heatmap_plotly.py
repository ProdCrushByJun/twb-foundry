"""Heatmap along a date (case 102, decisions/125): a column per period, 'Jan' headers, narrow columns, refusals."""
import copy
import json
import re
import unittest
import zipfile

from tbuilder import expected
from tbuilder.build import build
from test_roundtrip import OUT, ROOT

PLOTLY = ROOT / "acceptance" / "plotly"
SPEC = json.loads((PLOTLY / "spec.json").read_text(encoding="utf-8"))
NAME = "Exit Heatmap"


def sheet(spec):
    return next(s for s in spec["sheets"] if s["name"] == NAME)


def worksheet(path):
    with zipfile.ZipFile(path) as z:
        t = z.read(next(n for n in z.namelist() if n.endswith(".twb"))).decode("utf-8")
    i = t.rfind("<worksheet", 0, t.index(NAME))
    return t[i:t.index("</worksheet>", i)]


class HeatmapDate(unittest.TestCase):
    def test_spec_uses_the_date(self):
        s = sheet(SPEC)
        self.assertEqual((s["cols"], s["date_level"]), ("Event Date", "month"))

    def test_columns_narrow_and_header_is_month_name(self):
        path = OUT / "plotly_heatmap_date.twbx"
        build(SPEC, path, PLOTLY)
        w = worksheet(path)
        width = int(re.search(r'attr="width" field="[^"]*tmn:Event Date:ok\]" value="(\d+)"', w).group(1))
        self.assertLessEqual(width, 50)  # was 70: '01 Jan' of a calc string under the character floor
        self.assertIn('tmn:Event Date:ok]" value="*mmm"', w)

    def test_expected_keys_are_periods(self):
        got = expected.compute(SPEC, PLOTLY / "hr_events.csv")[NAME]
        self.assertIn("Engineering | 2025-01", got)
        ref = json.loads((PLOTLY / "expected.json").read_text(encoding="utf-8"))["spec.json"][NAME]
        for k, v in ref.items():
            self.assertEqual(got[k], v, k)

    def test_refusals(self):
        bad = copy.deepcopy(SPEC)
        sheet(bad)["cols"] = "Department"
        with self.assertRaisesRegex(ValueError, "date_level needs a date"):
            build(bad, OUT / "plotly_heatmap_text_col.twbx", PLOTLY)
        bad = copy.deepcopy(SPEC)
        sheet(bad)["margins"] = {"cols": "bar"}
        with self.assertRaisesRegex(ValueError, "column margin"):
            build(bad, OUT / "plotly_heatmap_margin.twbx", PLOTLY)


if __name__ == "__main__":
    unittest.main()
