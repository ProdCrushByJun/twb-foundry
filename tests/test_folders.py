"""Field folders in the Data pane (decisions/146): calcs[].folder and fields.<name>.folder -> <folders-common> in each
datasource that has the field; no folders, no change; build errors; the gate's check_folders."""
import copy
import json
import unittest
import zipfile

from lxml import etree

from tbuilder import gate
from tbuilder.build import build
from tbuilder.spec import SpecError, validate
from test_roundtrip import OUT, SPECS

SPEC = json.loads((SPECS / "folders.json").read_text(encoding="utf-8"))
MULTI = json.loads((SPECS / "multi_source.json").read_text(encoding="utf-8"))


def built(spec, name):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return etree.fromstring(z.read(out.stem + ".twb"))


def folders(root):
    """{datasource caption: {folder: [items]}}."""
    return {d.get("caption"): {f.get("name"): [i.get("name") for i in f.findall("folder-item")]
                               for f in d.findall("folders-common/folder")}
            for d in root.find("datasources") if d.get("name") != "Parameters"}


def calc_col(root, ds_caption, caption):
    ds = next(d for d in root.find("datasources") if d.get("caption") == ds_caption)
    return next(c.get("name") for c in ds.findall("column") if c.get("caption") == caption)


class TestFolders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(SPEC, "folders")

    def test_by_source(self):
        r = self.root
        self.assertEqual(folders(r), {
            "sales": {"Dates": ["[Order Date]"], "Geography": ["[Region]"],
                      "KPIs": sorted([calc_col(r, "sales", "Margin"), "[Sales]"])},
            "sales_plan": {"Geography": ["[Region]"], "People": ["[Manager]"],
                           "KPIs": sorted([calc_col(r, "sales_plan", "Attainment"), "[Plan]", "[Sales]"])}})

    def test_place_and_layout(self):
        for ds in self.root.find("datasources"):
            if ds.get("name") == "Parameters":
                continue
            tags = [c.tag for c in ds]
            self.assertEqual(tags[tags.index("folders-common") + 1], "layout")
            self.assertNotIn("column-instance", tags[tags.index("folders-common"):])
            self.assertEqual(ds.find("layout").get("show-structure"), "false")
            names = [f.get("name") for f in ds.findall("folders-common/folder")]
            self.assertEqual(names, sorted(names))

    def test_none_without_folders(self):
        root = built(MULTI, "folders_none")
        self.assertEqual(list(root.iter("folders-common")), [])
        self.assertTrue(all(l.get("show-structure") == "true" for l in root.iter("layout")))

    def test_gate_clean(self):
        self.assertEqual(gate.check_folders(self.root, SPEC), [])

    def test_schema(self):
        spec = copy.deepcopy(SPEC)
        spec["fields"]["Region"]["folder"] = "Bad [name]"
        with self.assertRaises(SpecError):
            validate(spec)

    def test_build_errors(self):
        def case(fn):
            spec = copy.deepcopy(SPEC)
            fn(spec)
            return spec
        for text, spec in [
            ("unknown field", case(lambda s: s["fields"].update({"Nope": {"folder": "X"}}))),
            ("a field is in one folder", case(lambda s: s["fields"].update({"Margin": {"folder": "Other"}}))),
            ("leading or trailing", case(lambda s: s["fields"]["Region"].update({"folder": "Geo "}))),
        ]:
            with self.subTest(text), self.assertRaisesRegex(ValueError, text):
                build(spec, OUT / "folders_bad.twbx", SPECS)

    def mutated(self, fn):
        root = copy.deepcopy(self.root)
        fn(root.find("datasources/datasource/folders-common"))
        return [i.message for i in gate.check_folders(root, SPEC)]

    def test_gate_broken_reference(self):
        def fn(fc):
            fc.find("folder/folder-item").set("name", "[Gone]")
        msgs = self.mutated(fn)
        self.assertTrue(any("[Gone], not a column" in m for m in msgs), msgs)
        self.assertTrue(any("belongs in folder" in m for m in msgs), msgs)  # [Order Date] dropped out

    def test_gate_duplicate(self):
        def fn(fc):
            etree.SubElement(fc.find("folder[@name='Geography']"), "folder-item", name="[Sales]", type="field")
        msgs = self.mutated(fn)
        self.assertTrue(any("[Sales] is in folder" in m for m in msgs), msgs)

    def test_gate_dropped(self):
        def fn(fc):
            fc.remove(fc.find("folder[@name='Dates']"))
        msgs = self.mutated(fn)
        self.assertEqual(msgs, ["'Order Date' belongs in folder 'Dates' by the spec, the workbook has it in None"])

    def test_gate_twice_named(self):
        def fn(fc):
            etree.SubElement(fc, "folder", name="Dates")
        self.assertTrue(any("named twice" in m for m in self.mutated(fn)))


if __name__ == "__main__":
    unittest.main()
