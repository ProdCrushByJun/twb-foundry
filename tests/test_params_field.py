"""Parameters from a field when the workbook opens (decisions/163): values_from (Desktop's source-field) and
default_from (default-value-field), the default's alias on the column; refusals of the spec, the XML forms, the gate's
checks with their mutations, the golden round trip and its numbers."""
import copy
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from tbuilder import excel, expected, gate, params
from tbuilder.build import build
from tbuilder.spec import SpecError, validate
from test_bar_labels import repack
from test_roundtrip import SPECS, canon, normalize, read_twbx

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "golden" / "golden_params_field_2025_1"
OUT = ROOT / "out"


def load():
    return json.loads((SPECS / "params_field.json").read_text(encoding="utf-8"))


def par(spec, name):
    return next(p for p in spec["parameters"] if p["name"] == name)


def pcol(root, caption):
    pds = next(d for d in root.find("datasources") if d.get("name") == "Parameters")
    return next(c for c in pds.findall("column") if c.get("caption") == caption)


class Spec(unittest.TestCase):
    def test_values_and_defaults_from_the_data(self):
        spec = load()
        ps = params.load(spec, {"Order Date", "Region", "Product", "Sales", "Profit", "Quantity"},
                         prof=excel.load(expected.data_path(spec, SPECS), spec["datasource"]))
        self.assertEqual(ps["Region pick"].values, ["East", "North", "South", "West"])
        self.assertEqual(ps["As of"].default.isoformat(), "2025-03-15")  # {MAX([Order Date])}
        self.assertEqual(ps["Min sale"].values, [20, 30, 40, 50])
        self.assertEqual(ps["Min sale"].default, 20)  # {FIXED : MIN([Sales])}
        self.assertEqual(ps["Top count"].default, 4)  # {COUNTD([Region])}

    def test_schema_takes_values_from_instead_of_values(self):
        validate(load())
        spec = load()
        par(spec, "Region pick")["values"] = ["East", "West"]
        with self.assertRaises(SpecError):
            validate(spec)

    def test_expected_at_other_values(self):
        spec = load()
        got = expected.compute(spec, expected.data_path(spec, SPECS),
                               {"As of": "2025-02-15", "Min sale": 30, "Top count": 2})
        self.assertEqual(got["KPI"]["AGG(Sales to date)"], 760)
        self.assertEqual(got["KPI"]["AGG(Big sales)"], 1080)
        self.assertEqual(set(got["Top Bar"]), {"A", "B"})


class Refused(unittest.TestCase):
    def refused(self, edit, why):
        spec = load()
        edit(spec)
        with self.assertRaisesRegex((ValueError, SpecError), why):
            build(spec, OUT / "params_field_refused.twbx", SPECS)

    def test_unknown_column(self):
        self.refused(lambda s: par(s, "Region pick").update(values_from="Area"), "not a column of the data")

    def test_column_of_another_type(self):
        self.refused(lambda s: par(s, "Min sale").update(values_from="Region"), "is a string column")

    def test_aliases_with_values_from(self):
        self.refused(lambda s: par(s, "Region pick").update(aliases={"East": "Eastern"}), "no aliases")

    def test_default_not_in_the_field(self):
        self.refused(lambda s: par(s, "Region pick").update(default="Mars"), "not one of its values from 'Region'")

    def test_default_and_default_from(self):
        def edit(s):
            p = par(s, "Top count")
            p["default"] = 3
        self.refused(edit, "default")

    def test_default_from_row_level(self):
        def edit(s):
            next(c for c in s["calcs"] if c["name"] == "Regions")["formula"] = "LEN([Region])"
        self.refused(edit, "one value over the whole data")

    def test_default_from_by_dimension(self):
        def edit(s):
            next(c for c in s["calcs"] if c["name"] == "Regions")["formula"] = "{FIXED [Product] : COUNTD([Region])}"
        self.refused(edit, "one value over the whole data")

    def test_default_from_with_a_parameter(self):
        def edit(s):
            next(c for c in s["calcs"] if c["name"] == "Regions")["formula"] = "{MAX([Sales])} - [Min sale]"
        self.refused(edit, "refers to a parameter")

    def test_default_from_of_another_type(self):
        self.refused(lambda s: par(s, "Top count").update(default_from="Last date"), "is date")

    def test_default_from_outside_the_list(self):
        def edit(s):
            next(c for c in s["calcs"] if c["name"] == "Regions")["formula"] = "{COUNTD([Product])}"  # 6
        self.refused(edit, "gives 6, which is not one of its values")


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = read_twbx(build(load(), OUT / "params_field_xml.twbx", SPECS))[0]

    def test_source_field_has_no_members(self):
        c = pcol(self.root, "Region pick")
        self.assertTrue(c.get("source-field").endswith("].[Region]"))
        self.assertIsNone(c.find("members"))
        self.assertIsNone(c.get("default-value-field"))

    def test_default_value_field_is_the_calc(self):
        c = pcol(self.root, "As of")
        self.assertRegex(c.get("default-value-field"), r"^\[federated\.\w+\]\.\[Calculation_\d+\]$")
        self.assertEqual(c.get("value"), "#2025-03-15#")

    def test_default_alias_on_the_column(self):
        self.assertEqual(pcol(self.root, "Top count").get("alias"), "four")

    def test_manifest_flag(self):
        self.assertIsNotNone(self.root.find("document-format-change-manifest/ParameterDefaultValues"))

    def test_sheet_declares_the_fields(self):
        w = next(w for w in self.root.iter("worksheet") if w.get("name") == "To Date")
        deps = next(d for d in w.findall("table/view/datasource-dependencies") if d.get("datasource") != "Parameters")
        names = {c.get("name") for c in deps.findall("column")}
        self.assertIn("[Order Date]", names)
        self.assertTrue(any(n.startswith("[Calculation_") for n in names))


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = build(load(), OUT / "params_field_gate.twbx", SPECS)

    def test_clean(self):
        self.assertEqual(gate.run(self.book), [])

    def caught(self, fn, text):
        got = [str(i) for i in gate.run(repack(self.book, fn)) if i.check in ("params", "manifest")]
        self.assertTrue(got, "not caught")
        self.assertTrue(any(text in g for g in got), got)

    def test_source_field_to_an_unknown_column(self):
        self.caught(lambda r: pcol(r, "Region pick").set("source-field", pcol(r, "Region pick").get("source-field")
                                                         .replace("[Region]", "[Area]")), "is no column")

    def test_source_field_of_another_type(self):
        self.caught(lambda r: pcol(r, "Min sale").set("source-field", pcol(r, "Region pick").get("source-field")),
                    "is string; the parameter is integer")

    def test_source_field_on_a_range(self):
        self.caught(lambda r: pcol(r, "Min sale").set("param-domain-type", "range"), "source-field gives a list")

    def test_members_with_source_field(self):
        def fn(r):
            c = pcol(r, "Region pick")
            m = c.makeelement("members", {})
            m.append(c.makeelement("member", {"value": '"East"'}))
            c.append(m)
        self.caught(fn, "keeps no members")

    def test_default_value_field_not_a_calc(self):
        self.caught(lambda r: pcol(r, "Min sale").set("default-value-field", pcol(r, "Min sale").get("source-field")),
                    "is not a calculated field")

    def test_default_value_field_of_another_type(self):
        self.caught(lambda r: pcol(r, "Min sale").set("default-value-field", pcol(r, "As of").get("default-value-field")),
                    "is date; the parameter is integer")

    def test_default_value_field_with_a_parameter(self):
        def fn(r):
            ref = pcol(r, "As of").get("default-value-field").split("].[")[1].rstrip("]")
            for c in r.iter("column"):
                if c.get("name") == f"[{ref}]" and c.find("calculation") is not None:
                    c.find("calculation").set("formula", "{MAX([Order Date])} + [Parameters].[Parameter 3]")
        self.caught(fn, "refers to a parameter")

    def test_no_manifest_flag(self):
        def fn(r):
            m = r.find("document-format-change-manifest")
            m.remove(m.find("ParameterDefaultValues"))
        self.caught(fn, "ParameterDefaultValues")

    def test_sheet_without_the_field(self):
        def fn(r):
            w = next(w for w in r.iter("worksheet") if w.get("name") == "To Date")
            for d in w.findall("table/view/datasource-dependencies"):
                for c in d.findall("column"):
                    if c.get("name", "").startswith("[Calculation_") and "MAX([Order Date])" in (
                            c.find("calculation").get("formula") if c.find("calculation") is not None else ""):
                        d.remove(c)
        self.caught(fn, "without declaring its field")

    def test_default_alias_missing(self):  # Desktop's card would show the first alias, 'two' (decisions/163)
        def fn(r):
            for c in r.iter("column"):
                if c.get("caption") == "Top count":
                    c.attrib.pop("alias", None)
        self.caught(fn, "shows as 'four'")


class Golden(unittest.TestCase):
    def test_golden_rebuilds_identically(self):
        out = build(load(), OUT / "params_field_roundtrip.twbx", SPECS)
        golden = normalize(ET.parse(GOLDEN.with_suffix(".twb")).getroot())
        self.assertEqual(canon(golden), canon(normalize(read_twbx(out)[0])))

    def test_expected_equals_golden_json(self):
        spec = load()
        want = json.loads((ROOT / "golden" / "expected" / f"{GOLDEN.name}.json").read_text(encoding="utf-8"))
        want = {k: v for k, v in want.items() if not k.startswith("_")}
        got = expected.compute(spec, expected.data_path(spec, SPECS))
        self.assertEqual(json.loads(json.dumps(got, default=str)), want)


if __name__ == "__main__":
    unittest.main()
