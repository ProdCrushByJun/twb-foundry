"""Reference lines, color vs avg, KPI history change colors (decisions/028).

Run: python -m unittest discover -s tests
"""
import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import design_lint, expected, gate, reflines
from tbuilder.build import build
from tbuilder.spec import SpecError, validate
from test_roundtrip import ROOT, SPECS

SPEC = json.loads((SPECS / "reflines.json").read_text(encoding="utf-8"))
CSV = ROOT / "data" / "sample" / "sales_2y.csv"


def mutate(fn, base=SPEC):
    spec = copy.deepcopy(base)
    fn(spec)
    return spec


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def built(spec, name="reflines_test"):
    out = build(spec, ROOT / "out" / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return etree.fromstring(z.read(out.stem + ".twb")), out


class Expected(unittest.TestCase):
    """Line values as Desktop 2025.1 drew them in golden_reflines_2025_1 and the lab (decisions/028)."""

    @classmethod
    def setUpClass(cls):
        cls.got = expected.compute(SPEC, CSV)

    def line(self, name):
        return self.got[reflines.record(name)]

    def test_average_of_the_bars(self):
        self.assertAlmostEqual(self.line("Regions")["Average"], 79333.235, 3)  # Desktop: 79 333

    def test_median_of_stacked_bars_is_over_their_totals(self):
        # 4 region totals: (78 646 + 82 909) / 2, the middle two averaged; Desktop: 80 778 (not a segment value)
        self.assertAlmostEqual(self.line("Stack")["Median"], 80777.555, 3)

    def test_constant_and_parameter(self):
        self.assertEqual(self.line("Categories"), {"Target": 105000})
        self.assertEqual(self.line("Total"), {"Target": 15000})
        got = expected.compute(SPEC, CSV, {"Target": 12000})
        self.assertEqual(got[reflines.record("Total")], {"Target": 12000})

    def test_line_with_series_averages_every_mark(self):
        # 24 months x 4 regions; Desktop: 3 305 (the monthly total average would be 13 222)
        self.assertAlmostEqual(self.line("Trend")["Average"], 3305.5515, 3)

    def test_card_history_average(self):
        self.assertAlmostEqual(self.line("Monthly · Sales · History")["Average"], 13222.2058, 3)
        self.assertAlmostEqual(self.line("Monthly · Profit · History")["Average"], 1022.7271, 3)

    def test_marks_unchanged(self):
        self.assertAlmostEqual(self.got["Regions"]["West"], 85565.19, 2)



class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.path = built(SPEC, "reflines_xml")

    def ws(self, name):
        return next(w for w in self.root.iter("worksheet") if w.get("name") == name)

    def lines(self, name):
        return self.ws(name).findall(".//pane/reference-line")

    def test_average_line(self):
        (rl,) = self.lines("Regions")
        self.assertEqual((rl.get("formula"), rl.get("scope"), rl.get("label"), rl.get("label-type")),
                         ("average", "per-table", "Average <Value>", "custom"))
        self.assertEqual(rl.get("axis-column"), rl.get("value-column"))

    def test_parameter_line(self):
        (rl,) = self.lines("Total")
        self.assertEqual((rl.get("formula"), rl.get("value-column")), ("average", "[Parameters].[Parameter 1]"))
        self.assertIn("Parameters", [d.get("name") for d in self.ws("Total").findall("table/view/datasources/"
                                                                                       "datasource")])

    def test_constant_on_a_real_axis(self):
        (rl,) = self.lines("Categories")
        self.assertEqual((rl.get("formula"), rl.get("value"), rl.get("probability")), ("constant", "105000.0", None))

    def test_line_after_the_pane_encodings(self):
        pane = self.ws("Monthly · Sales · History").find(".//pane")
        tags = [c.tag for c in pane]
        self.assertLess(tags.index("label-data"), tags.index("reference-line"))
        self.assertLess(tags.index("reference-line"), tags.index("customized-tooltip"))

    def test_look(self):
        rule = self.ws("Regions").find("table/style/style-rule[@element='refline']")
        got = {f.get("attr"): f.get("value") for f in rule}
        self.assertEqual((got["line-pattern-only"], got["stroke-color"], got["color"], got["text-format"]),
                         ("dashed", "#898989", "#898989", "n#,##0;-#,##0"))
        names = [r.get("element") for r in self.ws("Regions").find("table/style")]
        self.assertLess(names.index("refline"), names.index("gridline"))

    def test_text_format(self):
        self.assertEqual(reflines.text_format(2.6), "n#,##0.0;-#,##0.0")
        self.assertEqual(reflines.text_format(76.0), "n#,##0;-#,##0")

    def test_color_vs_avg_is_a_table_calc_with_a_palette(self):
        ds = next(d for d in self.root.find("datasources") if d.get("name") != "Parameters")
        col = next(c for c in ds.findall("column") if c.get("caption") == "Regions · Above Average")
        self.assertEqual(col.find("calculation").get("formula"), "SUM([Sales]) >= WINDOW_AVG(SUM([Sales]))")
        self.assertEqual(col.find("calculation/table-calc").get("ordering-type"), "Rows")
        inst = f"[usr:{col.get('name')[1:-1]}:nk]"
        ci = next(c for c in ds.findall("column-instance") if c.get("name") == inst)
        self.assertTrue(ci.find("table-calc").get("ordering-field").endswith("[none:Region:nk]"))
        enc = ds.find(f"style/style-rule/encoding[@field='{inst}']")
        self.assertEqual({m.find("bucket").text: m.get("to") for m in enc}, {"true": "#4e79a7", "false": "#d4d4d4"})

    def test_history_change_colors_replace_the_current_flag(self):
        enc = self.ws("Monthly · Sales · History").find(".//pane/encodings/color").get("column")
        self.assertIn("usr:Calculation_", enc)
        ds = next(d for d in self.root.find("datasources") if d.get("name") != "Parameters")
        col = next(c for c in ds.findall("column") if c.get("caption") == "Monthly · Sales · History · Change Color")
        self.assertIn("LOOKUP(SUM([Sales]), -1)", col.find("calculation").get("formula"))

    def test_no_reference_no_change(self):
        def m(s):
            s.pop("parameters")  # used by a line only
            for x in s["sheets"]:
                for k in ("reference", "history_reference", "history_color"):
                    x.pop(k, None)
        root, _ = built(mutate(m), "reflines_none")
        self.assertIsNone(root.find(".//reference-line"))
        self.assertIsNone(root.find(".//style-rule[@element='refline']"))


class SpecChecks(unittest.TestCase):
    def assertRejected(self, fn, text):
        with self.assertRaises((ValueError, SpecError)) as cm:
            built(mutate(fn))
        self.assertIn(text, str(cm.exception))

    def test_constant_without_value(self):
        self.assertRejected(lambda s: sheet(s, "Categories")["reference"].pop("value"), "has no 'value'")

    def test_unknown_parameter(self):
        self.assertRejected(lambda s: sheet(s, "Total")["reference"].update(parameter="Goal"), "is not a parameter")

    def test_string_parameter(self):
        def m(s):
            s["parameters"].append({"name": "Mode", "type": "string", "values": ["a", "b"], "default": "a"})
            sheet(s, "Total")["reference"]["parameter"] = "Mode"
        self.assertRejected(m, "it must be a number")

    def test_unknown_measure(self):
        self.assertRejected(lambda s: sheet(s, "Regions")["reference"].update(measure={"field": "Margin"}), "Margin")

    def test_value_on_an_average(self):
        self.assertRejected(lambda s: sheet(s, "Regions")["reference"].update(value=1), "does not take ['value']")

    def test_duplicate_labels(self):
        self.assertRejected(lambda s: sheet(s, "Regions").update(reference=[{"type": "avg"}, {"type": "avg"}]),
                            "labels must be unique")

    def test_history_options_need_cards(self):
        def m(s):
            s["sheets"].append({"name": "Tiles", "type": "kpi", "style": "tiles", "measures": [{"field": "Sales"}],
                                "history_color": "change"})
        self.assertRejected(m, "only apply to style 'cards'")

    def test_reference_with_a_plan(self):
        def m(s):
            r = sheet(s, "Regions")
            r.pop("color")
            r["plan"] = {"field": "Profit"}
        self.assertRejected(m, "next to a plan")

    def test_schema(self):
        with self.assertRaises(SpecError):
            validate(mutate(lambda s: sheet(s, "Regions").update(reference={"type": "mean"})))
        with self.assertRaises(SpecError):
            validate(mutate(lambda s: sheet(s, "Regions").update(color={"vs": "median"})))

    def test_parameter_used_only_by_a_line_counts_as_used(self):
        built(SPEC, "reflines_param_used")  # Target is used by the line alone: no 'not used' error


class Lint(unittest.TestCase):
    def test_one_line_per_sheet(self):
        spec = mutate(lambda s: sheet(s, "Regions").update(reference=[{"type": "avg"}, {"type": "median"}]))
        found = [f for f in design_lint.lint(spec, SPECS) if f.rule == "I7"]
        self.assertEqual([(f.level, f.where) for f in found], [("warn", "sheet 'Regions'")])
        self.assertEqual([f for f in design_lint.lint(SPEC, SPECS) if f.rule == "I7"], [])


class GateCatchesReferenceLines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.path = built(SPEC, "reflines_gate")

    def mutant(self, fn):
        with zipfile.ZipFile(self.path) as src:
            members = {n: src.read(n) for n in src.namelist()}
        name = next(n for n in members if n.endswith(".twb"))
        root = etree.fromstring(members[name])
        fn(root)
        members[name] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
        path = Path(tempfile.mkdtemp()) / "mutant.twbx"
        with zipfile.ZipFile(path, "w") as z:
            for n, b in members.items():
                z.writestr(n, b)
        return path

    def assertCaught(self, fn, check, text):
        issues = [str(i) for i in gate.run(self.mutant(fn)) if i.check == check]
        self.assertTrue(any(text in i for i in issues), f"expected [{check}] ~ '{text}', got {issues}")

    @staticmethod
    def line(root, sheet_name):
        ws = next(w for w in root.iter("worksheet") if w.get("name") == sheet_name)
        return ws.find(".//pane/reference-line")

    def test_generated_passes(self):
        self.assertEqual(gate.run(self.path), [])

    def test_line_on_a_field_not_in_the_sheet(self):
        def m(root):
            rl = self.line(root, "Regions")
            rl.set("value-column", rl.get("value-column").replace("[sum:Sales:qk]", "[sum:Margin:qk]"))
        self.assertCaught(m, "refs", "[sum:Margin:qk] is not declared")

    def test_line_at_an_undeclared_parameter(self):
        self.assertCaught(lambda root: self.line(root, "Total").set("value-column", "[Parameters].[Parameter 9]"),
                          "params", "[Parameter 9], which is not declared")

    def test_parameter_line_without_the_sheet_dependency(self):
        def m(root):
            ws = next(w for w in root.iter("worksheet") if w.get("name") == "Total")
            view = ws.find("table/view")
            view.remove(next(d for d in view.findall("datasource-dependencies")
                             if d.get("datasource") == "Parameters"))
        self.assertCaught(m, "params", "without declaring it in its dependencies")

    def test_constant_line_without_value(self):
        def m(root):
            del self.line(root, "Categories").attrib["value"]
        self.assertCaught(m, "reflines", "constant line refline0 has no value")

    def test_constant_line_with_a_word(self):
        self.assertCaught(lambda root: self.line(root, "Categories").set("value", "target"), "reflines",
                          "has no value (got 'target')")

    def test_custom_label_without_text(self):
        self.assertCaught(lambda root: self.line(root, "Regions").set("label", " "), "reflines",
                          "custom label without text")

    def test_look_of_a_missing_line(self):
        def m(root):
            rl = self.line(root, "Regions")
            rl.getparent().remove(rl)
        self.assertCaught(m, "reflines", "refline format for refline0, which is no line here")


if __name__ == "__main__":
    unittest.main()
