"""Registry alignment (decisions/126, 164): a pill and its title centred, every other column and title at the left;
no title at the right (the user's rule)."""
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tbuilder import registry
from tbuilder.build import build
from test_roundtrip import SPECS

OUT = Path(__file__).resolve().parent.parent / "out" / "registry_align_test.twbx"


def built(name):
    spec = json.loads((SPECS / name).read_text(encoding="utf-8"))
    out = build(spec, OUT, SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


class Align(unittest.TestCase):
    def test_per_style(self):
        for st, want in (("text", "left"), ("rank", "left"), ("share", "left"), ("delta", "left"),
                         ("pill", "center"), ("spark", "left"), ("bar", "left"), ("bar_inside", "left"),
                         ("dot", "left"), ("tick", "left"), ("track", "left")):
            self.assertEqual(registry.align({"style": st}), want, st)

    def test_built_cells(self):
        root = built("registry_v2.json")
        seen = set()
        for pane in root.iter("pane"):
            for f in pane.iterfind("style/style-rule[@element='cell']/format[@attr='text-align']"):
                seen.add(f.get("value"))
        self.assertEqual(seen, {"left"})

    def test_titles_follow_cells(self):
        root = built("registry_spark_pill.json")
        runs = {r.text: r.get("fontalignment") for r in root.iter("run") if r.get("bold") == "true"}
        self.assertEqual(runs["Profit"], "1")  # a pill, centred
        self.assertIsNone(runs["Quarterly sales"])  # left
        root = built("registry_v2.json")
        runs = {r.text: r.get("fontalignment") for r in root.iter("run") if r.get("bold") == "true"}
        for t in ("Share", "Change", "Units", "Sales"):
            self.assertIsNone(runs[t], t)

    def test_no_title_at_the_right(self):
        """No registry spec gives a column title fontalignment 2 (right)."""
        for name in ("registry.json", "registry_v2.json", "registry_totals.json", "theme_cards.json",
                     "switch_registry.json", "registry_spark_pill.json"):
            root = built(name)
            right = [r.text for r in root.iter("run") if r.get("fontalignment") == "2"]
            self.assertEqual(right, [], name)


if __name__ == "__main__":
    unittest.main()
