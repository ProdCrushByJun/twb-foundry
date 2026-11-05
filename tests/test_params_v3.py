"""Parameters v3 (decisions/057): integer list (a public book's Year Parameter), real, date (a public book's Order Date Cutoff),
boolean. Spec checks, the XML Desktop 2025.1 saves (golden_params_filters_v3), the values formulas see, gate
mutations."""
import copy
import datetime as dt
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import expected, gate, params
from tbuilder.build import build
from tbuilder.spec import SpecError, validate
from test_roundtrip import OUT, ROOT, SPECS

CSV = ROOT / "data" / "sample" / "sales_products.csv"


def load():
    return json.loads((SPECS / "params_filters_v3.json").read_text(encoding="utf-8"))


def param_columns(root):
    ds = next(d for d in root.find("datasources") if d.get("name") == "Parameters")
    return {c.get("caption"): c for c in ds.findall("column")}


class Load(unittest.TestCase):
    def pars(self, *ps, values=None):
        return params.load({"sheets": [], "parameters": list(ps)}, set(), values)

    def test_typed_values(self):
        p = self.pars({"name": "Cut", "type": "date", "range": {"min": "2025-01-01", "max": "2025-12-31"},
                       "default": "2025-09-30"},
                      {"name": "Y", "type": "integer", "values": [2023, 2024], "default": 2024},
                      {"name": "W", "type": "real", "range": {"min": 0, "max": 1, "step": 0.25}, "default": 0.5},
                      {"name": "B", "type": "boolean", "default": False})
        self.assertEqual(p["Cut"].value, dt.date(2025, 9, 30))
        self.assertEqual((p["Y"].value, p["W"].value, p["B"].value), (2024, 0.5, False))
        self.assertEqual([p[n].literal(p[n].value) for n in ("Cut", "Y", "W", "B")],
                         ["#2025-09-30#", "2024", "0.5", "false"])
        self.assertEqual([p[n].mode for n in ("Cut", "Y", "W", "B")], ["datetime", "compact", "slider", "compact"])
        self.assertEqual(p["B"].values, [True, False])

    def test_another_value(self):
        p = self.pars({"name": "Cut", "type": "date", "range": {"min": "2025-01-01", "max": "2025-12-31"},
                       "default": "2025-09-30"}, values={"Cut": "2025-03-31"})
        self.assertEqual(p["Cut"].value, dt.date(2025, 3, 31))
        with self.assertRaises(ValueError):
            self.pars({"name": "Cut", "type": "date", "range": {"min": "2025-01-01", "max": "2025-12-31"},
                       "default": "2025-09-30"}, values={"Cut": "2026-01-01"})

    def test_real_literal_as_desktop_saves_it(self):
        self.assertEqual([params.real_literal(v) for v in (0.25, 1, 2025, 0.14, 0.08)],
                         ["0.25", "1.0", "2025.0", "0.14000000000000001", "0.080000000000000002"])

    def test_refused(self):
        bad = [
            ({"name": "Y", "type": "integer", "values": [2023, 2024], "default": 2022}, "not one of its values"),
            ({"name": "W", "type": "real", "range": {"min": 0, "max": 1, "step": 0.3}, "default": 0.3},
             "whole number of steps"),
            ({"name": "W", "type": "real", "range": {"min": 0, "max": 1, "step": 0.25}, "default": 0.3},
             "range steps"),
            ({"name": "Cut", "type": "date", "range": {"min": "2025-01-01", "max": "2025-12-31", "step": 1},
              "default": "2025-09-30"}, "no step"),
            ({"name": "Cut", "type": "date", "range": {"min": "2025-01-01", "max": "2025-12-31"},
              "default": "2026-09-30"}, "not one of its range"),
            ({"name": "Cut", "type": "date", "values": ["2025-01-01", "31.12.2025"], "default": "2025-01-01"},
             "not an ISO date"),
            ({"name": "B", "type": "boolean", "values": [True, False], "default": True}, "leave out values"),
            ({"name": "Y", "type": "integer", "values": [1, 1], "default": 1}, "listed twice"),
        ]
        for p, text in bad:
            with self.subTest(p=p), self.assertRaisesRegex(ValueError, text):
                self.pars(p)

    def test_schema(self):
        spec = load()
        validate(spec)
        for p in ({"name": "B", "type": "boolean", "default": "true"},
                  {"name": "Cut", "type": "date", "range": {"min": "2025-01-01", "max": "2025-12-31"},
                   "default": "30.09.2025"},
                  {"name": "Y", "type": "integer", "values": [2023, 2024], "range": {"min": 1, "max": 2},
                   "default": 2023},
                  {"name": "W", "type": "real", "default": 0.5}):
            s = copy.deepcopy(spec)
            s["parameters"].append(p)
            with self.subTest(p=p), self.assertRaises(SpecError):
                validate(s)

    def test_buttons_take_a_string_parameter(self):
        spec = load()
        spec["sheets"].append({"name": "Pick", "type": "buttons", "parameter": "Top count"})
        spec["dashboard"]["grid"].append(["Pick"])
        with self.assertRaises(ValueError):
            build(spec, OUT / "params_v3_buttons.twbx", SPECS)


class Xml(unittest.TestCase):
    """The parameter columns as Desktop 2025.1 saved them (golden round-trip 1:1, decisions/057)."""

    @classmethod
    def setUpClass(cls):
        out = build(load(), OUT / "params_v3_xml.twbx", SPECS)
        with zipfile.ZipFile(out) as z:
            cls.root = etree.fromstring(z.read(out.stem + ".twb"))
        cls.path = out

    def test_columns(self):
        c = param_columns(self.root)
        cut, top, w, b = c["Cutoff"], c["Top count"], c["Target margin"], c["With West"]
        self.assertEqual((cut.get("datatype"), cut.get("param-domain-type"), cut.get("type"), cut.get("value")),
                         ("date", "range", "quantitative", "#2025-09-30#"))
        self.assertEqual(dict(cut.find("range").attrib), {"max": "#2025-12-31#", "min": "#2025-01-01#"})
        self.assertEqual([m.get("value") for m in top.findall("members/member")], ["3", "5", "8"])
        self.assertEqual(top.get("param-domain-type"), "list")
        self.assertEqual(dict(w.find("range").attrib), {"granularity": "0.125", "max": "0.5", "min": "0.0"})
        self.assertEqual((b.get("type"), b.get("value"), [m.get("value") for m in b.findall("members/member")]),
                         ("nominal", "true", ["true", "false"]))

    def test_cards(self):
        modes = {z.get("param"): z.get("mode") for z in self.root.iter("zone") if z.get("type-v2") == "paramctrl"}
        self.assertEqual(sorted(modes.values()), ["compact", "compact", "datetime", "slider"])

    def test_sheet_declares_the_parameter_of_a_filter_calc(self):
        """Every sheet shows the context filter [Order Date] <= [Cutoff]: it depends on the Cutoff parameter (a public book's
        sheets do so)."""
        for ws in self.root.iter("worksheet"):
            deps = [d for d in ws.iter("datasource-dependencies") if d.get("datasource") == "Parameters"]
            with self.subTest(ws.get("name")):
                self.assertIn("[Parameter 1]", [c.get("name") for d in deps for c in d.findall("column")])

    def test_gate_passes(self):
        self.assertEqual(gate.run(self.path, load()), [])


class Numbers(unittest.TestCase):
    def test_parameter_values(self):
        """The defaults (golden/expected), then each new kind of parameter moved."""
        spec = load()
        base = expected.compute(spec, CSV)
        want = json.loads((ROOT / "golden" / "expected" / "golden_params_filters_v3_2025_1.json").read_text("utf-8"))
        self.assertAlmostEqual(base["KPI"]["AGG(Shown sales)"], want["KPI"]["AGG(Shown sales)"], 2)
        early = expected.compute(spec, CSV, {"Cutoff": "2025-03-31"})
        self.assertEqual(sorted(early["Trend"]), ["2025-01", "2025-02", "2025-03"])
        top3 = expected.compute(spec, CSV, {"Top count": 3})
        self.assertEqual(len(top3["Top Products"]), 3)
        self.assertLess(set(top3["Top Products"]), set(base["Top Products"]))
        gap = expected.compute(spec, CSV, {"Target margin": 0.125})
        self.assertAlmostEqual(gap["KPI"]["AGG(Margin gap)"] - base["KPI"]["AGG(Margin gap)"], 0.125, 9)
        no_west = expected.compute(spec, CSV, {"With West": False})
        self.assertLess(no_west["KPI"]["AGG(Shown sales)"], base["KPI"]["AGG(Shown sales)"])


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build(load(), OUT / "params_v3_gate.twbx", SPECS)

    def mutant(self, fn):
        with zipfile.ZipFile(self.path) as src:
            members = {n: src.read(n) for n in src.namelist()}
        name = next(n for n in members if n.endswith(".twb"))
        root = etree.fromstring(members[name])
        fn(param_columns(root))
        members[name] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
        path = Path(tempfile.mkdtemp()) / "mutant.twbx"
        with zipfile.ZipFile(path, "w") as z:
            for n, b in members.items():
                z.writestr(n, b)
        return path

    def assertCaught(self, fn, text):
        issues = [str(i) for i in gate.run(self.mutant(fn)) if i.check == "params"]
        self.assertTrue(any(text in i for i in issues), f"expected [params] ~ '{text}', got {issues}")

    def _value(self, c, v):
        c.set("value", v)
        c.find("calculation").set("formula", v)

    def test_date_not_a_literal(self):
        self.assertCaught(lambda c: self._value(c["Cutoff"], "2025-09-30"), "is not a date literal")

    def test_date_out_of_range(self):
        self.assertCaught(lambda c: self._value(c["Cutoff"], "#2026-01-31#"), "not within the range")

    def test_date_range_with_granularity(self):
        self.assertCaught(lambda c: c["Cutoff"].find("range").set("granularity", "1"), "no granularity")

    def test_integer_list_value_not_a_member(self):
        self.assertCaught(lambda c: self._value(c["Top count"], "4"), "is not one of its members")

    def test_real_without_its_point(self):
        self.assertCaught(lambda c: self._value(c["Target margin"], "1"), "is not a real literal")

    def test_real_off_the_steps(self):
        self.assertCaught(lambda c: self._value(c["Target margin"], "0.3"), "is not a step of the range")

    def test_boolean_quoted(self):
        self.assertCaught(lambda c: self._value(c["With West"], '"true"'), "is not a boolean literal")

    def test_boolean_members(self):
        self.assertCaught(lambda c: c["With West"].find("members").remove(c["With West"].find("members")[1]),
                          "members are true and false")

    def test_date_parameter_nominal(self):
        self.assertCaught(lambda c: c["Cutoff"].set("type", "nominal"), "a date parameter is quantitative")


if __name__ == "__main__":
    unittest.main()
