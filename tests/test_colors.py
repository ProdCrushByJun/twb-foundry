"""Color with meaning (todo 3.5): highlight with a muted base, good/bad by sign, plan behind the fact, colored words."""
import copy
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tbuilder import colors, design
from tbuilder.build import build
from tbuilder.expected import compute
from tbuilder.spec import SpecError, validate
from test_roundtrip import SPECS

SPEC = json.loads((SPECS / "colors.json").read_text(encoding="utf-8"))
SPEC["dashboard"]["theme"] = "flat"  # the view without cards (decisions/168)
OUT = Path(__file__).resolve().parent.parent / "out" / "colors_test.twbx"
C = design.COLOR


def built(spec):
    out = build(spec, OUT, SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def mutate(fn):
    spec = copy.deepcopy(SPEC)
    fn(spec)
    return spec


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


class Words(unittest.TestCase):
    def test_runs(self):
        self.assertEqual(colors.runs("{good:Above plan} and {bad:below}", "x"),
                         [("Above plan", "good"), (" and ", None), ("below", "bad")])
        self.assertEqual(colors.runs("no colors", "x"), [("no colors", None)])
        self.assertEqual(colors.plain("{accent:East} vs the rest"), "East vs the rest")

    def test_bad_markup(self):
        with self.assertRaisesRegex(ValueError, "unknown color 'red'"):
            colors.runs("{red:East}", "x")
        with self.assertRaisesRegex(ValueError, "brace outside"):
            colors.runs("{accent East}", "x")


class Calcs(unittest.TestCase):
    def test_generated(self):
        got = {c["name"]: c["formula"] for c in colors.calcs(SPEC)}
        self.assertEqual(got["Regions · Highlight"], '[Region] = "East"')
        self.assertEqual(got["Managers · Highlight"], '[Manager] = "Denis" OR [Manager] = "Galina"')
        self.assertEqual(got["Gap · Good"], "[Sales vs Plan] >= 0")  # an aggregate calc as it is
        self.assertNotIn("Plan · Highlight", got)

    def test_good_formula_variants(self):
        s = mutate(lambda s: sheet(s, "Gap").update(measure={"field": "Sales", "agg": "avg"}, color={"good": "down"}))
        self.assertEqual({c["name"]: c["formula"] for c in colors.calcs(s)}["Gap · Good"], "AVG([Sales]) <= 0")

    def test_expected(self):
        """Hand-checked on data/sample/sales_plan.csv (make_sales_plan.py, seed 2025)."""
        got = compute(SPEC, SPECS / SPEC["datasource"]["path"])
        self.assertEqual(round(got["Regions"]["East"]), 35353)
        self.assertEqual(round(got["Managers"]["North | Denis"]), 18760)
        self.assertEqual({k: round(v) for k, v in got["Plan"]["Denis"].items()}, {"SUM(Sales)": 18760,
                                                                                   "SUM(Plan)": 16709})
        self.assertEqual(round(got["Gap"]["Denis"]), 2051)
        self.assertEqual(sum(v >= 0 for v in got["Gap"].values()), 4)  # four managers above plan, four below
        self.assertEqual(len(got["Trend"]), 48)  # 12 months x 4 regions: highlighting keeps one line per region


class Workbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(copy.deepcopy(SPEC))
        cls.ws = {w.get("name"): w for w in cls.root.iter("worksheet")}

    def pane(self, name):
        return self.ws[name].find("table/panes/pane")

    def encodings(self, name):
        return [(e.tag, e.get("column").split("].[", 1)[1]) for e in self.pane(name).find("encodings")]

    def test_highlight_on_own_dimension(self):
        (tag, col), = self.encodings("Regions")
        self.assertEqual(tag, "color")
        self.assertTrue(col.startswith("none:Calculation_") and col.endswith(":nk]"))

    def test_highlight_other_field_on_detail(self):
        for name in ("Managers", "Trend", "Stack"):
            enc = self.encodings(name)
            self.assertEqual([t for t, _ in enc], ["color", "lod"], name)
            self.assertIn(":Manager:" if name == "Managers" else ":Region:", enc[1][1])

    def test_good_flag(self):
        (tag, col), = self.encodings("Gap")
        self.assertEqual(tag, "color")
        self.assertTrue(col.startswith("usr:Calculation_") and col.endswith(":nk]"))  # discrete aggregate flag

    def test_plan(self):
        ws = self.ws["Plan"]
        self.assertEqual(self.encodings("Plan"), [("color", ":Measure Names]"), ("size", ":Measure Names]")])
        self.assertEqual(self.pane("Plan").find("view/breakdown").get("value"), "off")  # stack marks off
        self.assertTrue(ws.findtext("table/cols").endswith("[Multiple Values]"))
        members = [g.get("member") for g in ws.iter("groupfilter") if g.get("function") == "member"]
        self.assertEqual([m.split("].[")[1] for m in members], ["sum:Sales:qk]\"", "sum:Plan:qk]\""])
        self.assertEqual(self.pane("Regions").find("view/breakdown").get("value"), "auto")

    def test_palettes(self):
        ds = self.root.find("datasources/datasource")
        maps = {e.get("field"): [(m.get("to"), m.findtext("bucket")) for m in e] for e in ds.iter("encoding")}
        names = maps.pop("[:Measure Names]")
        self.assertEqual([c for c, _ in names], [C["accent"], C["mark_muted"]])
        self.assertTrue(names[0][1].endswith('.[sum:Sales:qk]"') and names[1][1].endswith('.[sum:Plan:qk]"'))
        self.assertEqual(sorted(map(tuple, maps.values())).count(((C["accent"], "true"), (C["mark_muted"], "false"))),
                         4)
        self.assertIn([(C["good"], "true"), (C["bad"], "false")], maps.values())
        instances = {ci.get("name") for ci in ds.findall("column-instance")}
        # the flags' instances, and the measures the Measure Names map refers to (Desktop declares them)
        self.assertEqual(instances, set(maps) | {"[sum:Sales:qk]", "[sum:Plan:qk]"})
        self.assertEqual({c.get("name") for c in ds.findall("column") if "caption" not in c.attrib},
                         {"[Sales]", "[Plan]"})

    def test_plan_order_and_sizes(self):
        view = self.ws["Plan"].find("table/view")
        sort = view.find("manual-sort")
        self.assertEqual([b.text.split("].[")[1] for b in sort.iter("bucket")], ['sum:Sales:qk]"', 'sum:Plan:qk]"'])
        self.assertLess(list(view).index(view.find("filter")), list(view).index(sort))
        self.assertLess(list(view).index(sort), list(view).index(view.find("computed-sort")))
        rules = [r.get("element") for r in self.ws["Plan"].find("table/style")]
        self.assertEqual(rules.index("mark"), rules.index("pane") - 1)
        size = self.ws["Plan"].find("table/style/style-rule[@element='mark']/encoding")
        self.assertEqual((size.get("type"), size.get("min-size")), ("catsize", str(design.PLAN_FACT_SIZE)))
        self.assertIsNone(self.ws["Regions"].find("table/view/manual-sort"))

    def hidden(self, name):
        """(axis titles hidden [(instance, scope)], field-label scopes hidden) of a worksheet."""
        style = self.ws[name].find("table/style")
        titles = [(f.get("field").split("].", 1)[1], f.get("scope")) for f in style.iter("format")
                  if f.get("attr") == "title"]
        labels = [f.get("scope") for f in style.iter("format") if f.get("attr") == "display-field-labels"]
        return titles, labels

    def test_data_ink_repeats_hidden(self):
        """An axis title / field label that only repeats the block header goes (data-ink)."""
        self.assertEqual(self.hidden("Regions"), ([("[sum:Sales:qk]", "cols")], ["rows"]))  # 'Sales by region'
        self.assertEqual(self.hidden("Managers"), ([("[sum:Sales:qk]", "cols")], ["rows"]))  # '... their regions'
        self.assertEqual(self.hidden("Plan"), ([("[Multiple Values]", "cols")], ["rows"]))  # 'Value' says nothing
        self.assertEqual(self.hidden("Trend"), ([("[tmn:Month:qk]", "cols"), ("[sum:Sales:qk]", "rows")], []))
        self.assertEqual(self.hidden("Gap"), ([("[usr:Calculation_4730773905612032612:qk]", "cols")], ["rows"]))
        rules = [r.get("element") for r in self.ws["Plan"].find("table/style")]
        self.assertEqual(rules[:6], ["axis", "header", "label", "mark", "pane", "worksheet"])  # Desktop's order

    def test_data_ink_keeps_what_the_header_does_not_say(self):
        """decisions/183: a horizontal bar loses its row label even if the header does not name the field."""
        root = built(mutate(lambda s: sheet(s, "Regions").update(title="Overview", subtitle="{accent:East}")))
        ws = next(w for w in root.iter("worksheet") if w.get("name") == "Regions")
        self.assertFalse([f for f in ws.iter("format") if f.get("attr") == "title"])
        self.assertTrue([f for f in ws.iter("format") if f.get("attr") == "display-field-labels"
                         and f.get("scope") == "rows" and f.get("value") == "false"])

    def test_data_ink_switch_for_all_sheets(self):
        """3.7 switch, on: a plain bar loses the labels its header repeats too; off (3.5), it keeps them."""
        spec = mutate(lambda s: sheet(s, "Regions").pop("color") and sheet(s, "Regions").update(subtitle="By sales"))
        ws = lambda root: next(w for w in root.iter("worksheet") if w.get("name") == "Regions")  # noqa: E731
        self.assertTrue([f for f in ws(built(spec)).iter("format") if f.get("attr") == "title"])
        colors.REPEATS_ALL_SHEETS = False
        try:
            self.assertFalse([f for f in ws(built(spec)).iter("format") if f.get("attr") == "title"])
        finally:
            colors.REPEATS_ALL_SHEETS = True

    def test_no_legends(self):
        self.assertFalse([z for z in self.root.iter("zone") if z.get("type-v2") == "color"])

    def test_colored_words(self):
        runs = [(r.text, r.get("fontcolor"), r.get("bold")) for z in self.root.iter("zone")
                if z.get("type-v2") == "text" for r in z.iter("run")]
        self.assertIn(("Above plan", C["good"], "true"), runs)
        self.assertIn((" and ", C["muted"], None), runs)
        self.assertIn(("below plan", C["bad"], "true"), runs)
        self.assertIn(("East", C["accent"], "true"), runs)
        self.assertFalse([t for t, _, _ in runs if t and "{" in t])

    def test_plain_color_keeps_its_legend(self):
        root = built(mutate(lambda s: sheet(s, "Regions").update(color="Manager", subtitle="By manager")))
        legends = [z for z in root.iter("zone") if z.get("type-v2") == "color"]
        self.assertEqual(len(legends), 1)


class Errors(unittest.TestCase):
    def assertRejects(self, spec, msg):
        with self.assertRaisesRegex(ValueError, msg):
            build(spec, OUT, SPECS)

    def test_unknown_value(self):
        self.assertRejects(mutate(lambda s: sheet(s, "Regions")["color"].update(highlight=["Esat"])),
                           r"highlight values \['Esat'\] are not in 'Region'")

    def test_numeric_highlight_field(self):
        self.assertRejects(mutate(lambda s: sheet(s, "Trend")["color"].update(field="Sales", highlight=["1"])),
                           "must be a text dimension")

    def test_word_color_not_drawn(self):
        self.assertRejects(mutate(lambda s: sheet(s, "Regions").update(subtitle="{good:East}")),
                           r"colored words \['good'\]")
        def no_bad_anywhere(s):  # the dashboard subtitle may name any color a sheet draws, and no other
            del sheet(s, "Gap")["color"]
            sheet(s, "Gap")["subtitle"] = "Gap to plan"
            s["dashboard"]["subtitle"] = "{bad:Below plan}"
        self.assertRejects(mutate(no_bad_anywhere), r"Dashboard 'Colors': colored words \['bad'\]")
        build(mutate(lambda s: s["dashboard"].update(subtitle="{bad:Below plan} in 2025")), OUT, SPECS)

    def test_plan_with_color(self):
        self.assertRejects(mutate(lambda s: sheet(s, "Plan").update(color="Region")), "remove 'color'")

    def test_plan_same_field(self):
        self.assertRejects(mutate(lambda s: sheet(s, "Plan").update(plan={"field": "Sales"})), "same field")

    def test_fact_and_plan_swapped_between_sheets(self):
        def f(s):
            other = copy.deepcopy(sheet(s, "Plan"))
            other.update(name="Plan 2", measure={"field": "Plan"}, plan={"field": "Sales"}, subtitle="x")
            s["sheets"].append(other)
        self.assertRejects(mutate(f), "fact in one plan sheet and the plan in another")

    def test_good_on_table_calc(self):
        self.assertRejects(mutate(lambda s: sheet(s, "Gap").update(
            measure={"field": "Sales", "table_calc": {"type": "difference"}})), "table calculation")

    def test_good_on_row_level_calc(self):
        def f(s):
            s["calcs"].append({"name": "Gap Row", "formula": "[Sales] - [Plan]"})
            sheet(s, "Gap")["measure"] = {"field": "Gap Row"}
        self.assertRejects(mutate(f), "row-level calculation")

    def test_schema(self):
        validate(SPEC)
        for bad in [lambda s: sheet(s, "Trend")["color"].pop("field"),  # a series needs its field
                    lambda s: sheet(s, "Trend").update(color={"good": "up"}),  # good/bad is for bars
                    lambda s: sheet(s, "Regions").update(color={"highlight": []}),
                    lambda s: sheet(s, "Trend").update(plan={"field": "Plan"})]:
            with self.assertRaises(SpecError):
                validate(mutate(bad))


if __name__ == "__main__":
    unittest.main()
