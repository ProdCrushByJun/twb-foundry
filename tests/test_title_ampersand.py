"""'&' in a dashboard / sheet title and subtitle (decisions/132): the schema accepts it and the .twb carries it
escaped (&amp; in the file, '&' after parsing)."""
import copy
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile

from tbuilder.build import build
from test_roundtrip import OUT, ROOT

CASE = ROOT / "acceptance" / "plotly"


class TitleAmpersand(unittest.TestCase):
    def test_ampersand_in_titles(self):
        spec = copy.deepcopy(json.loads((CASE / "spec.json").read_text(encoding="utf-8")))
        spec["dashboard"]["title"] = "**People & Hiring** · Overview 2025"
        spec["dashboard"]["subtitle"] = "January – December 2025 · R&D and all departments"
        sheet = next(s for s in spec["sheets"] if s["name"] == "Exits by Dept")
        sheet["title"] = "Exits **by department** & team"
        sheet["subtitle"] = "number of people, hires & exits"
        out = build(spec, OUT / "title_ampersand.twbx", CASE)
        with zipfile.ZipFile(out) as z:
            raw = z.read(out.stem + ".twb").decode("utf-8")
        root = ET.fromstring(raw)  # well-formed
        text = " ".join(r.text or "" for r in root.iter("run"))
        self.assertIn("R&D", text)
        self.assertIn("hires & exits", text)
        self.assertIn("by department", text)
        self.assertIn("&amp;", raw)

    def test_plotly_case(self):
        """acceptance/plotly: the page's '&' title, and no 'Count of Event ID' axis title (measure.label 'people' is
        in the block header, colors.repeats hides the title)."""
        spec = json.loads((CASE / "spec.json").read_text(encoding="utf-8"))
        self.assertIn("&", spec["dashboard"]["title"])
        out = build(spec, OUT / "title_ampersand_plotly.twbx", CASE)
        with zipfile.ZipFile(out) as z:
            root = ET.fromstring(z.read(out.stem + ".twb"))
        ws = next(w for w in root.iter("worksheet") if w.get("name") == "By Quarter")
        titles = [f for f in ws.iter("format") if f.get("attr") == "title" and f.get("scope") == "rows"]
        self.assertEqual([f.get("value") for f in titles], [""])


if __name__ == "__main__":
    unittest.main()
