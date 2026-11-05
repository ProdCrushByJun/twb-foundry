"""Registry v2 (todo 8.5, decisions/039): rank, share "**21 %** (230)", bar with the value inside, track to 100 %,
dot on a scale, tick at the base, change with an arrow, two-line cell."""
import copy
import json
import unittest
from lxml import etree as ET  # gate walks getparent()
import zipfile
from pathlib import Path

from tbuilder import design, gate, registry
from tbuilder.build import build
from tbuilder.expected import compute
from test_roundtrip import SPECS

SPEC = json.loads((SPECS / "registry_v2.json").read_text(encoding="utf-8"))
OUT = Path(__file__).resolve().parent.parent / "out" / "registry_v2_test.twbx"
TIES = {  # COUNT(Sales) of sales.csv: South 135, North 123, West 123, East 119 (decisions/034)
    "version": 1, "datasource": {"type": "csv", "path": "../data/sample/sales.csv"},
    "sheets": [{"name": "Orders", "type": "registry", "rows": ["Region"], "columns": [
        {"measure": {"field": "Sales", "agg": "count"}, "style": "rank", "label": "#"},
        {"measure": {"field": "Sales", "agg": "count"}, "style": "text", "label": "Orders"}]}],
    "dashboard": {"name": "D", "width": 800, "height": 400, "grid": [["Orders"]]}}


def built(spec, out=OUT):
    out = build(spec, out, SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def mutate(fn, spec=SPEC):
    spec = copy.deepcopy(spec)
    fn(spec)
    return spec


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def column(spec, sheet_name, label):
    return next(c for c in sheet(spec, sheet_name)["columns"] if registry.label(c) == label)


class Calcs(unittest.TestCase):
    def test_generated(self):
        got = {c["name"]: c for c in registry.calcs(SPEC, {"Sales 2025", "Sales 2024"})}
        rank = got["Categories · # · Rank"]
        self.assertEqual((rank["formula"], rank["compute_using"]), ("RANK([Sales 2025])", ["Category"]))
        share = got["Regions · Share · Share"]
        self.assertEqual(share["formula"], "[Sales 2025] / MAX({FIXED : [Sales 2025]})")  # decisions/109
        self.assertNotIn("compute_using", share)
        self.assertEqual(got["Regions · Of total · Track"]["formula"], "1 - [Sales 2025] / TOTAL([Sales 2025])")
        self.assertEqual(got["Categories · Change · Change"]["formula"],
                         "([Sales 2025] - [Sales 2024]) / ABS([Sales 2024])")
        self.assertEqual(got["Categories · Change · Change Good"]["formula"],
                         "IF [Categories · Change · Change] >= 0 THEN [Categories · Change · Change] END")
        self.assertNotIn("Regions · Sales · Cell", got)  # a bar is its measure
        self.assertIn("Regions · Avg profit · Cell", got)  # a dot sits on a dummy axis

    def test_bar_inside_splits_its_values(self):
        """decisions/077: inside from a share of the column's longest bar up (all rows), the rest outside."""
        got = {c["name"]: c for c in registry.calcs(SPEC, {"Sales 2025", "Sales 2024"})}
        fit = f"[Sales 2025] > 0 AND [Sales 2025] >= {registry.INSIDE_K0} * WINDOW_MAX([Sales 2025])"
        inside, outside = got["Regions · Sales · Inside"], got["Regions · Sales · Outside"]
        self.assertEqual(inside["formula"], f"IF {fit} THEN [Sales 2025] END")
        self.assertEqual(outside["formula"], f"IF NOT ({fit}) THEN [Sales 2025] END")
        self.assertEqual((inside["compute_using"], inside["format"], outside["format"]), (["Region"], "number", "number"))

    def test_longest_bar_estimate_is_never_longer_than_drawn(self):
        """The lab of decisions/077 (Desktop 2025.1, a registry): (pane px, widest label) -> the longest
        bar Desktop drew next to labels outside. The estimate under it: a value counted inside fits its bar."""
        from tbuilder.design import text_px
        for pane, label, drawn in [(171, "52%", 125), (171, "52,0%", 113), (250, "52%", 207)]:
            with self.subTest(pane=pane, label=label):
                est = pane - text_px(label, 9, True) - registry.LABEL_ROOM_PX
                self.assertLessEqual(est, drawn)
                self.assertGreater(est, drawn - 15)  # not much shorter: few values pushed outside for nothing

    def test_csv_measure_is_aggregated(self):
        got = {c["name"]: c["formula"] for c in registry.calcs(TIES)}
        self.assertEqual(got["Orders · # · Rank"], "RANK(COUNT([Sales]))")


class Expected(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = compute(SPEC, SPECS / SPEC["datasource"]["path"])

    def test_rank_share_delta(self):
        reg, cat = self.got["Regions"], self.got["Categories"]
        sales = {k: v["Sales"] for k, v in reg.items()}
        self.assertEqual([reg[k]["#"] for k in sorted(sales, key=sales.get, reverse=True)], [1, 2, 3, 4])
        self.assertAlmostEqual(sum(v["Share"] for v in reg.values()), 1)
        self.assertAlmostEqual(reg["North"]["Share"], sales["North"] / sum(sales.values()))
        self.assertEqual(reg["North"]["Of total"], reg["North"]["Share"])
        self.assertEqual(reg["North"]["Share · value"], sales["North"])
        c = cat["North | Tech"]
        self.assertAlmostEqual(c["Change"], (c["Sales vs PY"] - c["Sales vs PY · Sales 2024"])
                               / abs(c["Sales vs PY · Sales 2024"]))
        self.assertLess(c["Change"], 0)
        for region in ("East", "North", "South", "West"):  # a rank within each region (nested like the sort)
            self.assertEqual(sorted(v["#"] for k, v in cat.items() if k.startswith(region)), [1, 2, 3])

    def test_rank_ties_are_competition(self):
        got = compute(TIES, SPECS / TIES["datasource"]["path"])["Orders"]
        self.assertEqual({k: v["#"] for k, v in got.items()}, {"South": 1, "North": 2, "West": 2, "East": 4})

    def test_reconcile_sees_rank_share_change(self):
        from tbuilder.reconcile import entries
        ents = entries(SPEC, self.got)
        share = next(e for e in ents if e["sheet"] == "Regions" and e["key"] == "North" and "share" in e["tags"]
                     and e["tags"][0] == "Share")
        self.assertTrue(share["pct"])
        change = next(e for e in ents if e["key"] == "North | Tech" and "change" in e["tags"])
        self.assertTrue(change["pct"])
        self.assertTrue(any(e["key"] == "East | Office" and e["tags"][:1] == ["Sales 2024"] for e in ents))


class Workbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(copy.deepcopy(SPEC))
        cls.ws = {w.get("name"): w for w in cls.root.iter("worksheet")}
        cls.ds = cls.root.find("datasources/datasource")

    def panes(self, name):
        """The column panes (a bar_inside's second layer, x-index 1, left out)."""
        return [p for p in self.ws[name].findall("table/panes/pane")[1:] if p.get("x-index") is None]

    def test_bar_inside_value_inside_or_outside(self):
        """decisions/077: the white label shows the values from a share of the longest bar up; a second layer of the
        same axis (a transparent bar) labels the rest outside, in the text color."""
        table = self.ws["Regions"].find("table")
        bar = self.panes("Regions")[1]
        f = bar.get("x-axis-name")
        layer = next(p for p in table.iterfind("panes/pane") if p.get("x-index") == "1")
        self.assertEqual(layer.get("x-axis-name"), f)
        self.assertEqual(table.findtext("cols").count(f), 2)
        fold = table.find("style/style-rule[@element='axis']/encoding[@fold='true']")
        self.assertEqual((fold.get("field"), fold.get("class"), fold.get("synchronized")), (f, "1", "true"))
        inside = bar.find("customized-label/formatted-text/run")
        outside = layer.find("customized-label/formatted-text/run")
        self.assertEqual((inside.get("fontcolor"), outside.get("fontcolor")),
                         (design.COLOR["cell_text"], design.COLOR["text"]))
        mark = {x.get("attr"): x.get("value") for x in layer.iterfind("style/style-rule[@element='mark']/format")}
        self.assertEqual((mark["mark-color"], mark["mark-transparency"]), (design.COLOR["cell_text"], "0"))
        self.assertIsNone(layer.find("style/style-rule[@element='pane']"))  # one width per column (064)
        formulas = {c.get("caption"): c.find("calculation").get("formula") for c in self.ds.iter("column")
                    if c.find("calculation") is not None}
        k = formulas["Regions · Sales · Inside"].split(">= ")[1].split(" *")[0]
        self.assertNotEqual(k, registry.INSIDE_K0)  # set from the pane's width
        self.assertIn(f"NOT (", formulas["Regions · Sales · Outside"])
        self.assertIn(f">= {k} * WINDOW_MAX(", formulas["Regions · Sales · Outside"])
        fmts = {c.get("caption"): c.get("default-format") for c in self.ds.iter("column")}
        self.assertEqual(fmts["Regions · Sales · Inside"], fmts["Sales 2025"])  # the measure's own format

    def test_marks_and_widths(self):
        panes = self.panes("Regions")
        self.assertEqual([p.find("mark").get("class") for p in panes], ["Bar"] * 4 + ["Circle"])
        self.assertEqual(len(self.ws["Regions"].findall("table/panes/pane")), 1 + 5 + 1)  # + bar_inside's layer
        widths = [int(p.find("style/style-rule[@element='pane']/format[@attr='minwidth']").get("value"))
                  for p in panes]
        self.assertEqual(len(set(widths)), 1)  # a rank column as wide as the rest: Desktop draws them so (064)

    def test_rank_is_along_the_inner_row(self):
        ci = [c for c in self.ws["Categories"].iter("column-instance") if c.find("table-calc") is not None]
        self.assertTrue(ci)
        self.assertTrue(all(c.find("table-calc").get("ordering-field").endswith("[none:Category:nk]") for c in ci))

    def test_share_label_bold_with_the_value_in_brackets(self):
        runs = self.panes("Regions")[3].findall("customized-label/formatted-text/run")
        self.assertEqual(runs[0].get("bold"), "true")
        self.assertTrue(runs[0].text.endswith("> "))
        self.assertTrue(runs[1].text.startswith("(<") and runs[1].text.endswith(">)"))
        self.assertEqual(runs[1].get("fontcolor"), design.COLOR["muted"])

    def test_track_is_measure_values_stacked_on_a_fixed_axis(self):
        table = self.ws["Regions"].find("table")
        self.assertIn("[Multiple Values]", table.findtext("cols"))
        sort = table.find("view/manual-sort")
        names = [b.text for b in sort.iter("bucket")]
        self.assertEqual(len(names), 2)
        enc = table.find("style/style-rule[@element='axis']/encoding")
        self.assertEqual((enc.get("field").split(".")[-1], enc.get("min"), enc.get("max"), enc.get("range-type")),
                         ("[Multiple Values]", "0.0", "1.0", "fixed"))  # real shares: Desktop's '0.0' (065)
        maps = {m.findtext("bucket"): m.get("to") for m in self.ds.iter("map")}
        # the rest first, the share last: Desktop stacks the first member at the far end (decisions/065)
        # the share in the registry's bar_color (decisions/079), the accent without one
        self.assertEqual([maps[n] for n in names], [design.COLOR["track"], "#0d3a6b"])

    def test_track_palette_instances_carry_the_sheets_compute_using(self):
        """decisions/065: a datasource instance without it is Desktop's default (Rows) one; the sheet's would become
        [...:qk:1], unmapped (red / orange)."""
        deps = {c.get("name"): c for c in self.ws["Regions"].iterfind("table/view/datasource-dependencies/"
                                                                     "column-instance")}
        names = [b.text.strip('"').split("].", 1)[1] for b in self.ws["Regions"].iter("bucket")]
        for n in names:
            ds_ci = self.ds.find(f"column-instance[@name='{n}']")
            self.assertEqual(ds_ci.find("table-calc").attrib, deps[n].find("table-calc").attrib)
            self.assertTrue(ds_ci.find("table-calc").get("ordering-field").endswith("[none:Region:nk]"))
        self.assertIsNotNone(self.ds.find("column[@name='[Region]']"))
        self.assertIsNotNone(self.ds.find("column-instance[@name='[none:Region:nk]']"))

    def test_dot_scale(self):
        enc = self.ws["Regions"].find("table/style/style-rule[@element='mark']/encoding")
        colors = [c.text for c in enc.iter("color")]
        self.assertEqual((colors[0], colors[-1], len(colors)), (design.COLOR["dot_low"], design.COLOR["good"], 11))

    def test_tick_is_a_per_cell_line_at_the_base(self):
        rl = self.ws["Categories"].find(".//reference-line")
        self.assertEqual((rl.get("scope"), rl.get("formula"), rl.get("label-type")), ("per-cell", "average", "none"))
        self.assertNotEqual(rl.get("value-column"), rl.get("axis-column"))
        # decisions/065: in the default pane (Desktop moves it there), its base on Detail of the tick's pane (on no
        # shelf Desktop drops the base and the line)
        default = self.ws["Categories"].find("table/panes/pane")
        self.assertIsNone(default.get("id"))
        self.assertIs(default.find("reference-line"), rl)
        tick = self.panes("Categories")[1]
        self.assertEqual(tick.get("x-axis-name"), rl.get("axis-column"))
        self.assertEqual(tick.find("encodings/lod").get("column"), rl.get("value-column"))
        rule = self.ws["Categories"].find("table/style/style-rule[@element='refline']")
        self.assertEqual(rule.find("format[@attr='stroke-size']").get("value"), str(design.TICK_STROKE_PX))

    def test_delta_runs_good_and_bad(self):
        runs = self.panes("Categories")[2].findall("customized-label/formatted-text/run")
        self.assertEqual([r.get("fontcolor") for r in runs], [design.COLOR["good_text"], design.COLOR["bad_text"]])
        fmts = {c.get("caption"): c.get("default-format") for c in self.ds.iter("column")}
        self.assertEqual(fmts["Categories · Change · Change Good"], "*▲ 0.0%;▼ 0.0%")

    def test_two_line_cell(self):
        runs = self.panes("Categories")[3].findall("customized-label/formatted-text/run")
        self.assertEqual(runs[1].text, "Æ\n")
        self.assertEqual(runs[2].get("fontsize"), str(design.FONT["cell_second"]))
        h = self.ws["Categories"].find("table/style/style-rule[@element='cell']/format[@attr='height']")
        self.assertEqual(h.get("value"), str(design.REGISTRY_ROW_TWO_LINE_PX))


class Errors(unittest.TestCase):
    def assertRejects(self, spec, msg):
        with self.assertRaisesRegex(ValueError, msg):
            build(spec, OUT, SPECS)

    def test_options_of_other_styles(self):
        cases = [(lambda s: column(s, "Regions", "#").update(highlight={"above": 1}), "highlight applies"),
                 (lambda s: column(s, "Categories", "Change").pop("base"), "needs 'base'"),
                 (lambda s: column(s, "Regions", "Sales").update(base={"field": "Sales 2024"}), "'base' applies"),
                 (lambda s: column(s, "Regions", "#").update(with_value=True), "with_value"),
                 (lambda s: column(s, "Regions", "Sales").update(second={"field": "Profit"}), "second"),
                 (lambda s: column(s, "Regions", "Share").update(style="track"), "one track")]
        for fn, msg in cases:
            with self.subTest(msg=msg):
                self.assertRejects(mutate(fn), msg)


class Repeat(unittest.TestCase):
    def test_expand(self):
        got = registry.expand(SPEC)
        names = [s["name"] for s in got["sheets"]]
        self.assertEqual(names[-2:], ["Top · Region", "Top · Category"])
        top = sheet(got, "Top · Category")
        self.assertEqual((top["rows"], top["title"], top["top"]), (["Category"], "Top 2 by **Category**", {"n": 2}))
        self.assertNotIn("repeat", top)
        self.assertEqual(got["dashboard"]["grid"][-1], ["Top · Region", "Top · Category"])
        self.assertIs(registry.expand(TIES), TIES)  # nothing repeats: the spec itself

    def test_top_n_rows_and_their_rank(self):
        got = compute(SPEC, SPECS / SPEC["datasource"]["path"])
        self.assertEqual({k: v["#"] for k, v in got["Top · Region"].items()}, {"North": 1, "West": 2})
        self.assertEqual(len(got["Top · Category"]), 2)

    def test_top_filter_in_the_workbook(self):
        root = built(copy.deepcopy(SPEC))
        ws = next(w for w in root.iter("worksheet") if w.get("name") == "Top · Region")
        end = ws.find("table/view/filter/groupfilter[@function='end']")
        self.assertEqual((end.get("count"), end.get("end")), ("2", "top"))
        self.assertIn("Calculation_", end.find("groupfilter").get("expression"))  # by the first column's calc

    def test_errors(self):
        def two_rows(s):
            t = sheet(s, "Top")
            t.pop("repeat")
            t["rows"] = ["Region", "Category"]
            s["dashboard"]["grid"][-1] = ["Top"]
        with self.assertRaisesRegex(ValueError, "one row dimension"):
            build(mutate(two_rows), OUT, SPECS)
        with self.assertRaisesRegex(ValueError, "twice"):
            build(mutate(lambda s: sheet(s, "Top").update(repeat=["Region", "Region"])), OUT, SPECS)


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(copy.deepcopy(SPEC))

    def issues(self, fn):
        root = copy.deepcopy(self.root)
        fn(root)
        return [i for c in gate.CHECKS if c is not gate.check_xsd for i in c(root)]

    def ws(self, root, name):
        return next(w for w in root.iter("worksheet") if w.get("name") == name)

    def test_clean(self):
        self.assertEqual(self.issues(lambda r: None), [])

    def test_share_label_field_not_on_its_pane(self):
        def f(root):
            enc = self.ws(root, "Regions").findall("table/panes/pane")[5].find("encodings")  # after bar_inside's 2
            enc.remove(enc.findall("text")[0])
        self.assertTrue(any(i.check == "labels" for i in self.issues(f)))

    def test_track_without_measure_names_filter(self):
        def f(root):
            view = self.ws(root, "Regions").find("table/view")
            view.remove(next(x for x in view.findall("filter") if x.get("column").endswith("[:Measure Names]")))
        self.assertTrue(any(i.check == "measures" for i in self.issues(f)))

    def test_rank_without_compute_using(self):
        def f(root):
            for ci in self.ws(root, "Categories").iter("column-instance"):
                for tc in ci.findall("table-calc"):
                    ci.remove(tc)
        self.assertTrue(any(i.check == "tablecalc" for i in self.issues(f)))

    def test_tick_base_not_on_the_sheet(self):
        def f(root):
            ws = self.ws(root, "Categories")
            line = ws.find(".//reference-line")
            deps = ws.find("table/view/datasource-dependencies")
            deps.remove(next(c for c in deps.findall("column-instance")
                             if line.get("value-column").endswith(c.get("name"))))
        self.assertTrue(self.issues(f))

    def test_tick_base_on_no_shelf(self):
        """decisions/065: the base only in the dependencies (039's form) - Desktop drops it and the line."""
        def f(root):
            for p in self.ws(root, "Categories").iter("pane"):
                for enc in p.findall("encodings"):
                    if enc.find("lod") is not None:
                        p.remove(enc)
        self.assertTrue(any(i.check == "reflines" and "per-cell" in i.message for i in self.issues(f)))

    def test_bar_inside_without_its_outside_layer(self):
        """decisions/077: 039's form, one layer: short bars clip their white value."""
        def f(root):
            panes = self.ws(root, "Regions").find("table/panes")
            panes.remove(next(p for p in panes if p.get("x-index") == "1"))
        self.assertTrue(any(i.check == "registry" and "second layer" in i.message for i in self.issues(f)))

    def test_bar_inside_white_label_of_every_value(self):
        """decisions/077: the white label shows the measure itself (039's form), not the calc of the values that
        fit."""
        def f(root):
            panes = self.ws(root, "Regions").findall("table/panes/pane")
            bar = panes[2]
            run = bar.find("customized-label/formatted-text/run")
            run.text = f"<{bar.get('x-axis-name')}>"
            bar.find("encodings/text").set("column", bar.get("x-axis-name"))
        self.assertTrue(any(i.check == "registry" and "clips" in i.message for i in self.issues(f)))

    def test_track_palette_instance_without_compute_using(self):
        """decisions/065: the datasource instance of a track measure without the sheet's compute-using (039's form):
        Desktop renames the sheet's to :qk:1 and paints it red / orange."""
        def f(root):
            ds = root.find("datasources/datasource")
            for ci in ds.findall("column-instance"):
                for tc in ci.findall("table-calc"):
                    ci.remove(tc)
        self.assertTrue(any(i.check == "measures" and ":qk:1" in i.message for i in self.issues(f)))


if __name__ == "__main__":
    unittest.main()
