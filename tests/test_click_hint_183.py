"""L24 (decisions/183): the default action hint ('Click to filter') only with dashboard.action_hints; a horizontal
bar has no row field label ('Warehouse' + the sort icon) over its rows."""
import copy
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile

from tbuilder import actions
from tbuilder.build import build
from test_roundtrip import OUT, SPECS

SPEC = json.loads((SPECS / "actions.json").read_text(encoding="utf-8"))


def twb(spec, name):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def texts(root):
    return ["".join(r.text or "" for r in z.iter("run")) for z in root.iter("zone") if z.get("type-v2") == "text"]


class Hints(unittest.TestCase):
    def spec(self, key):
        s = copy.deepcopy(SPEC)
        s["dashboard"].pop("action_hints", None)
        if key is not None:
            s["dashboard"]["action_hints"] = key
        return s

    def test_off_by_default(self):
        text = " ".join(texts(twb(self.spec(None), "hint183_off")))
        self.assertNotIn("Click to filter", text)
        self.assertNotIn("Hover to filter", text)
        self.assertIn("Click a bar to see its trend", text)  # an action's own hint is written
        self.assertEqual(actions.sign({"name": "By Region", "subtitle": "x"}, self.spec(None))["subtitle"], "x")

    def test_key_turns_them_on(self):
        text = " ".join(texts(twb(self.spec(True), "hint183_on")))
        self.assertIn("Sales and profit | Click to filter", text)
        self.assertIn("Hover to filter", text)

    def test_false_is_off(self):
        self.assertNotIn("Click to filter", " ".join(texts(twb(self.spec(False), "hint183_false"))))



class RowLabel(unittest.TestCase):
    def test_horizontal_bar_has_no_row_label(self):
        spec = copy.deepcopy(SPEC)
        for s in spec["sheets"]:
            if s["name"] == "By Region":  # the header does not name the field
                s["title"], s["subtitle"] = "**Totals**", "Sales and profit"
        root = twb(spec, "hint183_rows")
        bars = [w for w in root.iter("worksheet") if w.get("name") == "By Region"]
        self.assertTrue(bars)
        for w in bars:
            hidden = [f for f in w.iter("format") if f.get("attr") == "display-field-labels"
                      and f.get("scope") == "rows" and f.get("value") == "false"]
            self.assertTrue(hidden, w.get("name"))
            self.assertNotIn("⇅", ET.tostring(w, encoding="unicode"))


if __name__ == "__main__":
    unittest.main()
