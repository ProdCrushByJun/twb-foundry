"""A registry with one column (decisions/099): one axis on Columns, so Desktop 2025.1 keeps one pane - it drops the
default pane, the layer pane's x-axis-name and its width on save (a public book Region Wise Figure / State Wise: resave DIFF,
6 differences). The builder writes Desktop's form: pane id 1 alone, no x-axis-name, no width; the reference line of a
tick in it."""
import copy
import json
import unittest
import zipfile

from lxml import etree

from tbuilder import gate
from tbuilder.build import build
from test_roundtrip import OUT, SPECS

SINGLE = json.loads((SPECS / "registry_single.json").read_text(encoding="utf-8"))
V2 = json.loads((SPECS / "registry_v2.json").read_text(encoding="utf-8"))


def built(spec, name):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return etree.fromstring(z.read(out.stem + ".twb"))


def sheet(root, name):
    return next(w for w in root.iter("worksheet") if w.get("name") == name)


def issues(root, check):
    return [str(i) for i in check(root)]


class Form(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(SINGLE, "registry_single_form")

    def test_one_pane_id_1_no_axis_no_width(self):
        for s in SINGLE["sheets"]:
            panes = sheet(self.root, s["name"]).findall("table/panes/pane")
            if s["columns"][0]["style"] == "bar_inside":  # two layers on one axis (077): the old form
                self.assertEqual([p.get("id") for p in panes], [None, "1", "2"], s["name"])
                continue
            self.assertEqual([(p.get("id"), p.get("x-axis-name")) for p in panes], [("1", None)], s["name"])
            self.assertIsNone(panes[0].find("style/style-rule[@element='pane']"), s["name"])

    def test_tick_line_in_the_only_pane(self):
        pane = sheet(self.root, "One Tick").find("table/panes/pane")
        self.assertEqual([e.tag for e in pane][:4], ["view", "mark", "encodings", "reference-line"])

    def test_still_a_registry_for_the_gate(self):
        for s in SINGLE["sheets"]:
            self.assertEqual(gate.registry_columns(sheet(self.root, s["name"]).find("table")), 1, s["name"])
        self.assertEqual(issues(self.root, gate.check_single_axis_pane), [])

    def test_several_columns_keep_their_panes(self):
        root = built(V2, "registry_single_v2")
        panes = sheet(root, "Categories").findall("table/panes/pane")
        self.assertEqual(panes[0].get("id"), None)
        self.assertTrue(all(p.get("x-axis-name") for p in panes[1:]))
        self.assertEqual(issues(root, gate.check_single_axis_pane), [])


class Mutations(unittest.TestCase):
    def setUp(self):
        self.root = built(SINGLE, "registry_single_mut")
        self.table = sheet(self.root, "One Text").find("table")
        self.pane = self.table.find("panes/pane")

    def test_default_pane_and_axis_name_back(self):
        self.pane.set("x-axis-name", self.table.findtext("cols"))
        default = etree.Element("pane", {"selection-relaxation-option": "selection-relaxation-allow"})
        self.table.find("panes").insert(0, default)
        got = issues(self.root, gate.check_single_axis_pane)
        self.assertEqual(len(got), 1)
        self.assertIn("drops the default pane", got[0])

    def test_width_on_the_only_pane(self):
        rule = etree.SubElement(self.pane.find("style"), "style-rule", element="pane")
        etree.SubElement(rule, "format", attr="maxwidth", value="200")
        got = issues(self.root, gate.check_single_axis_pane)
        self.assertEqual(len(got), 1)
        self.assertIn("has a width", got[0])

    def test_title_too_long_still_caught(self):
        """A one-column registry has no pane width, its column titles are still checked (064)."""
        spec = copy.deepcopy(SINGLE)
        spec["sheets"][0]["columns"][0]["label"] = "A very long column title " * 4
        spec["dashboard"]["grid"] = [["One Text", "One Text Top", "One Text Nested", "One Bar"]]
        spec["sheets"] = spec["sheets"][:4]
        with self.assertRaises(Exception) as e:
            built(spec, "registry_single_title")
        self.assertIn("column title", str(e.exception))


if __name__ == "__main__":
    unittest.main()
