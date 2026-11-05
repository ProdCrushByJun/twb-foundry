"""Regression for case 102 (acceptance/plotly): a bar along a date with color and the HTML palette (decisions/111, 121)."""
import copy
import json
import unittest
import zipfile
import xml.etree.ElementTree as ET

from tbuilder.build import build
from test_gate import ws
from test_roundtrip import OUT, ROOT

PLOTLY = ROOT / "acceptance" / "plotly"
SPEC = json.loads((PLOTLY / "spec.json").read_text(encoding="utf-8"))
SHEET = "By Quarter"


def twb(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


def encodings(root):
    return [e for r in root.iter("style-rule") if r.get("element") == "mark"
            for e in r.findall("encoding") if e.get("type") == "palette"]


class PlotlyDateBar(unittest.TestCase):
    def test_palette_is_the_pages(self):
        path = OUT / "plotly_date_bar_palette.twbx"
        build(SPEC, path, PLOTLY)
        root = twb(path)
        maps = {m.findtext("bucket").strip('"'): m.get("to") for e in encodings(root)
                if e.get("field", "").endswith("[none:Event Type:nk]") for m in e.findall("map")}
        self.assertEqual(maps, {"Hire": "#2f6fb5", "Exit": "#e07b39"})

    def test_highlight_on_the_date_bar_is_accepted(self):
        spec = copy.deepcopy(SPEC)
        next(s for s in spec["sheets"] if s["name"] == SHEET)["color"] = {"field": "Event Type", "highlight": ["Exit"]}
        path = OUT / "plotly_date_bar_highlight.twbx"
        build(spec, path, PLOTLY)
        enc = ws(twb(path), SHEET).find("table/panes/pane/encodings")
        self.assertTrue(enc.find("color").get("column").split(".[")[-1].startswith("none:Calculation_"))
        self.assertTrue(enc.find("lod").get("column").endswith(".[none:Event Type:nk]"))


if __name__ == "__main__":
    unittest.main()
