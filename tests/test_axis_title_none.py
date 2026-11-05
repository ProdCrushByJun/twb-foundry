"""measure.axis_title "none" (decisions/136): the measure axis has no title, said in the spec and not through a word of
the header in measure.label."""
import copy
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile

from tbuilder import spec as spec_mod
from tbuilder.build import build
from test_roundtrip import OUT, ROOT

CASE = ROOT / "acceptance" / "plotly"


def _row_titles(spec, name):
    out = build(spec, OUT / "axis_title_none.twbx", CASE)
    with zipfile.ZipFile(out) as z:
        root = ET.fromstring(z.read(out.stem + ".twb"))
    ws = next(w for w in root.iter("worksheet") if w.get("name") == "By Quarter")
    return [f.get("value") for f in ws.iter("format") if f.get("attr") == "title" and f.get("scope") == "rows"]


class AxisTitleNone(unittest.TestCase):
    def setUp(self):
        self.spec = copy.deepcopy(json.loads((CASE / "spec.json").read_text(encoding="utf-8")))
        self.sheet = next(s for s in self.spec["sheets"] if s["name"] == "By Quarter")
        del self.sheet["measure"]["label"]  # the old way out

    def test_without_it_the_title_stays(self):
        self.assertNotEqual(_row_titles(self.spec, "By Quarter"), [""])

    def test_none_hides_it(self):
        self.sheet["measure"]["axis_title"] = "none"
        self.assertEqual(_row_titles(self.spec, "By Quarter"), [""])

    def test_none_hides_it_without_a_header(self):
        self.sheet["measure"]["axis_title"] = "none"
        self.sheet.pop("title", None)
        self.sheet.pop("subtitle", None)
        self.assertEqual(_row_titles(self.spec, "By Quarter"), [""])

    def test_only_none_is_allowed(self):
        self.sheet["measure"]["axis_title"] = "Count"
        with self.assertRaises(spec_mod.SpecError):
            spec_mod.validate(self.spec)


if __name__ == "__main__":
    unittest.main()
