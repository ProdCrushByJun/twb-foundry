"""Parameters (todo 2.3, decisions/020): metric switch, Top N, period level - formulas, spec checks, XML, expected,
gate mutations."""
import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import design_lint, expected, gate, params
from tbuilder.build import build
from tbuilder.formula import CalcSet, FormulaError, calc_id
from tbuilder.spec import SpecError, validate
from test_roundtrip import ROOT, SPECS

SPEC = json.loads((SPECS / "params.json").read_text(encoding="utf-8"))
CSV = ROOT / "data" / "sample" / "sales_products.csv"
COLUMNS = {"Order Date": "date", "Region": "string", "Product": "string", "Sales": "real", "Profit": "real",
           "Quantity": "integer"}
METRIC = ('CASE [Metric] WHEN "Sales" THEN SUM([Sales]) WHEN "Profit" THEN SUM([Profit]) '
          'WHEN "Quantity" THEN SUM([Quantity]) END')


def mutate(fn, base=SPEC):
    spec = copy.deepcopy(base)
    fn(spec)
    return spec


def built(spec, name="params_test"):
    out = build(spec, ROOT / "out" / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return etree.fromstring(z.read(out.stem + ".twb")), out


def calcset(calcs, values=None, rows=None):
    pars = params.load(SPEC, set(COLUMNS), values)
    return CalcSet(calcs, COLUMNS, rows, pars)


class Formulas(unittest.TestCase):
    ROWS = [{"Order Date": "2025-03-14", "Region": "East", "Product": "Atlas", "Sales": "10", "Profit": "2",
             "Quantity": "3"},
            {"Order Date": "2025-05-02", "Region": "West", "Product": "Nova", "Sales": "5", "Profit": "-1",
             "Quantity": "4"}]

    def test_case_switch_over_a_parameter(self):
        for metric, want in (("Sales", 15), ("Profit", 1), ("Quantity", 7)):
            cs = calcset([{"name": "M", "formula": METRIC}], {"Metric": metric})
            c = cs["M"]
            self.assertTrue(c.is_agg)
            self.assertEqual(c.datatype, "real")
            self.assertEqual(c.params, ["Metric"])
            self.assertEqual(cs.agg_value("M", self.ROWS), want)

    def test_both_reference_forms_become_the_internal_name(self):
        cs = calcset([{"name": "A", "formula": "[Parameters].[Top N] * 2"}, {"name": "B", "formula": "[Top N] + 1"}])
        self.assertEqual(cs["A"].xml_formula, "[Parameters].[Parameter 2] * 2")
        self.assertEqual(cs["B"].xml_formula, "[Parameters].[Parameter 2] + 1")
        self.assertEqual(cs.row_value("A", self.ROWS[0]), 16)

    def test_parameters_are_constants_for_both_levels(self):
        cs = calcset([{"name": "Row", "formula": "[Sales] * [Top N]"},
                      {"name": "Agg", "formula": "SUM([Sales]) / [Top N]"}])
        self.assertFalse(cs["Row"].is_agg)
        self.assertTrue(cs["Agg"].is_agg)
        self.assertEqual(cs.agg_value("Agg", self.ROWS), 15 / 8)

    def test_params_are_transitive(self):
        cs = calcset([{"name": "M", "formula": METRIC}, {"name": "Twice", "formula": "[M] * 2"}])
        self.assertEqual(cs["Twice"].params, ["Metric"])

    def test_datetrunc_by_a_period_parameter(self):
        for period, want in (("week", "2025-03-10"), ("month", "2025-03-01"), ("quarter", "2025-01-01")):
            cs = calcset([{"name": "P", "formula": "DATETRUNC([Period], [Order Date])"}], {"Period": period})
            self.assertEqual(cs["P"].datatype, "date")
            self.assertEqual(cs.row_value("P", self.ROWS[0]).isoformat(), want)

    def test_case_with_else_and_numbers(self):
        cs = calcset([{"name": "X", "formula": 'CASE [Top N] WHEN 4 THEN "few" WHEN -1 THEN "?" ELSE "many" END'}])
        self.assertEqual(cs.row_value("X", self.ROWS[0]), "many")

    def test_rejected(self):
        for formula, msg in [
            ("[Parameters].[Nope] + 1", "unknown parameter [Parameters].[Nope]"),
            ('CASE [Metric] WHEN "Sale" THEN SUM([Sales]) ELSE 0 END', "WHEN ['Sale'] is not a value"),
            ('CASE [Metric] WHEN "Sales" THEN SUM([Sales]) END', "no WHEN for ['Profit', 'Quantity'] and no ELSE"),
            ('CASE [Metric] WHEN 1 THEN 2 END', "CASE compares a string with the integer WHEN value"),
            ('CASE [Metric] WHEN [Region] THEN 1 END', "WHEN takes a literal value"),
            ("CASE [Metric] END", "at least one WHEN"),
            ("DATETRUNC([Metric], [Order Date])", "or a string parameter whose values are all levels"),
            ("DATETRUNC([Top N], [Order Date])", "level must be a string literal"),
            ('[Metric] + 1', "'+' needs numbers"),
        ]:
            with self.subTest(formula=formula), self.assertRaises(FormulaError) as cm:
                calcset([{"name": "Bad", "formula": formula}])
            self.assertIn(msg, str(cm.exception))


class Schema(unittest.TestCase):
    def test_valid(self):
        validate(SPEC)

    def test_rejected(self):
        bad = [
            {"name": "X", "type": "string", "values": ["a", "b"]},  # no default
            {"name": "X", "type": "string", "range": {"min": 1, "max": 5}, "default": "a"},
            {"name": "X", "type": "integer", "values": ["1", "2"], "default": 1},
            {"name": "X", "type": "integer", "range": {"min": 1, "max": 5}, "default": "1"},
            {"name": "X", "type": "string", "values": ['a"b', "c"], "default": "c"},
            {"name": "X", "type": "string", "values": ["a"], "default": "a"},
            {"name": "X", "type": "real", "range": {"min": 1, "max": 5}, "default": "1"},  # real since 057
            {"name": "X[1]", "type": "string", "values": ["a", "b"], "default": "a"},
        ]
        for p in bad:
            with self.subTest(p=p), self.assertRaises(SpecError):
                validate(mutate(lambda s: s["parameters"].append(p)))
        for top in ({"n": 0}, {"n": 2.5}, {}, {"n": 5, "by": "Sales"}):
            with self.subTest(top=top), self.assertRaises(SpecError):
                validate(mutate(lambda s: s["sheets"][1].update(top=top)))
        with self.assertRaises(SpecError):  # top is not a KPI option (a line takes it since 148)
            validate(mutate(lambda s: s["sheets"][0].update(top={"n": 3})))


class Checks(unittest.TestCase):
    def assertRejected(self, fn, text):
        with self.assertRaises(ValueError) as cm:
            built(mutate(fn))
        self.assertIn(text, str(cm.exception))

    def test_default_must_be_in_the_domain(self):
        self.assertRejected(lambda s: s["parameters"][0].update(default="Margin"),
                            "default 'Margin' is not one of its values")
        self.assertRejected(lambda s: s["parameters"][1].update(default=7), "default 7 is not one of its range steps")
        self.assertRejected(lambda s: s["parameters"][1].update(default=16), "range steps")

    def test_range_is_whole_steps(self):
        self.assertRejected(lambda s: s["parameters"][1]["range"].update(max=14), "not a whole number of steps")
        self.assertRejected(lambda s: s["parameters"][1]["range"].update(min=15), "must be below max")

    def test_unique_and_unambiguous_names(self):
        self.assertRejected(lambda s: s["parameters"].append(dict(s["parameters"][0])), "duplicate parameter name")
        self.assertRejected(lambda s: s["parameters"][0].update(name="Region"), "a CSV column has the same name")
        self.assertRejected(lambda s: s["parameters"][0].update(name="Metric value"),
                            "a calculated field has the same name")

    def test_every_parameter_is_used(self):
        self.assertRejected(lambda s: s["parameters"].append({"name": "Spare", "type": "string",
                                                              "values": ["a", "b"], "default": "a"}),
                            "Parameters ['Spare'] are not used")

    def test_top_n_checks(self):
        self.assertRejected(lambda s: s["sheets"][1].update(top={"n": "Nope"}), "top n 'Nope' is not a parameter")
        self.assertRejected(lambda s: s["sheets"][1].update(top={"n": "Metric"}),
                            "top n 'Metric' is a string parameter; it must be integer")
        self.assertRejected(lambda s: s["sheets"][2]["measure"].update(table_calc={"type": "percent_of_total"}),
                            "Top N by a table calculation is not supported")
        self.assertRejected(lambda s: s["filters"][0].update(field="Product"),
                            "'Product' also has a dashboard filter; Tableau keeps one filter per field")

    def test_controls_need_the_header_row(self):
        self.assertRejected(lambda s: (s["dashboard"].pop("title"), s["dashboard"].pop("subtitle")),
                            "the dashboard needs a title or a subtitle")
        self.assertRejected(lambda s: s["dashboard"].update(sidebar=True), "with a sidebar they are not supported")

    def test_header_has_room_for_the_cards(self):
        self.assertRejected(lambda s: s["dashboard"].update(width=1000), "header cards (filters, parameters)")


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.path = built(SPEC)

    def sheet(self, name):
        return next(w for w in self.root.iter("worksheet") if w.get("name") == name)

    def test_parameters_datasource_comes_first(self):
        dss = self.root.find("datasources")
        self.assertEqual(dss[0].get("name"), "Parameters")
        cols = dss[0].findall("column")
        self.assertEqual([c.get("caption") for c in cols], ["Metric", "Top N", "Period"])
        self.assertEqual([c.get("name") for c in cols], ["[Parameter 1]", "[Parameter 2]", "[Parameter 3]"])
        self.assertEqual([m.get("value") for m in cols[0].findall("members/member")],
                         ['"Sales"', '"Profit"', '"Quantity"'])
        self.assertEqual(cols[1].find("range").attrib, {"granularity": "4", "max": "12", "min": "4"})
        self.assertEqual(cols[1].get("value"), "8")

    def test_sheet_dependencies(self):
        for name, used in (("Top Products", ["[Parameter 1]", "[Parameter 2]"]), ("KPI · All products", ["[Parameter 1]"]),
                           ("Trend", ["[Parameter 1]", "[Parameter 3]"])):
            view = self.sheet(name).find("table/view")
            self.assertIn("Parameters", [d.get("name") for d in view.findall("datasources/datasource")])
            deps = view.findall("datasource-dependencies")
            self.assertEqual(deps[0].get("datasource"), "Parameters")
            self.assertEqual([c.get("name") for c in deps[0].findall("column")], used)
            self.assertIsNone(deps[0].find("column/members"))  # members only in the datasource
        fixed = self.sheet("Most Profitable").find("table/view")  # no parameter: no Parameters datasource
        self.assertEqual([d.get("name") for d in fixed.findall("datasources/datasource")][1:], [])

    def test_csv_datasource_depends_on_its_calcs_parameters(self):
        ds = self.root.find("datasources")[1]
        deps = ds.find("datasource-dependencies")
        self.assertEqual(deps.get("datasource"), "Parameters")
        self.assertEqual([c.get("name") for c in deps.findall("column")], ["[Parameter 1]", "[Parameter 3]"])
        self.assertEqual([ch.tag for ch in ds][-3:], ["date-options", "datasource-dependencies", "object-graph"])

    def test_top_n_filter(self):
        view = self.sheet("Top Products").find("table/view")
        f = view.find("filter")
        self.assertTrue(f.get("column").endswith("[none:Product:nk]"))
        end = f.find("groupfilter")
        self.assertEqual((end.get("function"), end.get("end"), end.get("count")),
                         ("end", "top", "[Parameters].[Parameter 2]"))
        order = end.find("groupfilter")
        self.assertEqual(order.get("expression"), f"[{calc_id('Metric value')}]")  # an aggregate calc by its name
        self.assertEqual([c.text.split("].")[-1] for c in view.findall("slices/column")],
                         ["[none:Region:nk]", "[none:Product:nk]"])  # Desktop: after the dashboard filters
        fixed = self.sheet("Most Profitable").find("table/view/filter/groupfilter")
        self.assertEqual(fixed.get("count"), "3")
        self.assertEqual(fixed.find("groupfilter").get("expression"), "SUM([Profit])")

    def test_header_cards(self):
        zones = [z for z in self.root.iter("zone") if z.get("type-v2") == "paramctrl"]
        self.assertEqual([(z.get("param"), z.get("mode")) for z in zones],
                         [("[Parameters].[Parameter 1]", "compact"), ("[Parameters].[Parameter 2]", "slider"),
                          ("[Parameters].[Parameter 3]", "compact")])
        filt = next(z for z in self.root.iter("zone") if z.get("type-v2") == "filter")
        self.assertLess(int(filt.get("x")), int(zones[0].get("x")))  # filters first, then parameters

    def test_dashboard_dependencies(self):
        db = self.root.find("dashboards/dashboard")
        self.assertEqual([d.get("name") for d in db.findall("datasources/datasource")][0], "Parameters")
        deps = db.find("datasource-dependencies")
        self.assertEqual(deps.get("datasource"), "Parameters")
        self.assertEqual(len(deps.findall("column/members/member")), 6)  # Desktop keeps the members here

    def test_titles_show_the_current_value(self):
        runs = [r.text for z in self.root.iter("zone") if z.get("type-v2") == "text"
                for r in z.findall("formatted-text/run")]
        # one run with the text around the parameter: Desktop drops a run that is only a space ('Top 8products')
        self.assertIn("Top <[Parameters].[Parameter 2]> ", runs)
        self.assertIn("by <[Parameters].[Parameter 3]>", runs)
        self.assertNotIn("[Metric]", " ".join(runs))
        self.assertFalse([r for r in runs if not r.strip()])

    def test_title_width_uses_the_longest_value(self):
        pars = params.load(SPEC, set(COLUMNS))
        self.assertEqual(params.shown("Top [Top N] by [Metric] [x]", pars), "Top 12 by Quantity [x]")
        self.assertEqual(params.text("[x] [Metric]", pars), "[x] <[Parameters].[Parameter 1]>")


class Expected(unittest.TestCase):
    def test_defaults(self):
        e = expected.compute(SPEC, CSV)
        self.assertAlmostEqual(e["KPI"]["AGG(Metric value)"], 170547.57, places=2)
        self.assertEqual(len(e["Top Products"]), 8)
        self.assertAlmostEqual(e["Top Products"]["Beacon"], 17414.43, places=2)
        self.assertNotIn("Lumen", e["Top Products"])
        self.assertEqual(sorted(e["Most Profitable"]), ["Ember", "Iris", "Orbit"])
        self.assertEqual(len(e["Trend"]), 12)

    def test_other_values(self):
        e = expected.compute(SPEC, CSV, {"Metric": "Profit", "Top N": 4, "Period": "quarter"})
        self.assertEqual(sorted(e["Top Products"]), ["Ember", "Granite", "Iris", "Orbit"])
        self.assertAlmostEqual(e["Top Products"]["Iris"], 5517.39, places=2)
        self.assertEqual(list(e["Trend"]), ["2025-01-01", "2025-04-01", "2025-07-01", "2025-10-01"])
        e = expected.compute(SPEC, CSV, {"Metric": "Quantity", "Top N": 12, "Period": "week"})
        self.assertEqual(e["KPI"]["AGG(Metric value)"], 3285)
        self.assertEqual(list(e["Trend"])[0], "2024-12-30")  # weeks start on Monday

    def test_desktop_seen(self):
        """golden_params_2025_1 in Desktop 2025.1 (2026-10-20): defaults, then Metric Profit, Top N 4, Period
        quarter (tile, bars, the first quarter's tooltip)."""
        e = expected.compute(SPEC, CSV)
        self.assertEqual(round(e["KPI"]["AGG(Metric value)"]), 170548)
        self.assertEqual(list(e["Top Products"]), sorted(["Beacon", "Iris", "Cobalt", "Ember", "Juniper", "Meridian",
                                                          "Pioneer", "Atlas"]))
        e = expected.compute(SPEC, CSV, {"Metric": "Profit", "Top N": 4, "Period": "quarter"})
        self.assertEqual(round(e["KPI"]["AGG(Metric value)"]), 24592)
        self.assertEqual(round(e["Trend"]["2025-01-01"]), 5087)

    def test_unknown_or_bad_value(self):
        with self.assertRaises(ValueError):
            expected.compute(SPEC, CSV, {"Top N": 7})
        with self.assertRaises(ValueError):
            expected.compute(SPEC, CSV, {"Nope": 1})

    def test_top_is_ranked_before_the_dimension_filters(self):
        rows = [{"P": p, "R": r, "V": v} for p, r, v in
                [("a", "x", 10), ("b", "y", 9), ("b", "y", 3), ("c", "x", 8)]]
        key = lambda r: r["P"]  # noqa: E731
        total = lambda rs: sum(r["V"] for r in rs)  # noqa: E731
        self.assertEqual(params.top_members(rows, key, total, 2, "t"), {"a", "b"})
        # a tie at the 2nd place is broken A-Z as Desktop does (decisions/148)
        self.assertEqual(params.top_members(rows[:2] + [{"P": "c", "R": "x", "V": 9}], key, total, 2, "t"), {"a", "b"})

    def test_lint_counts_bars_after_top_n(self):
        rules = [f.rule for f in design_lint.lint(SPEC, SPECS)]
        self.assertNotIn("I4", rules)
        no_top = mutate(lambda s: s["sheets"][1].pop("top"))
        self.assertIn("I4", [f.rule for f in design_lint.lint(no_top, SPECS)])


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.path = built(SPEC, "params_gate")

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

    def assertCaught(self, fn, text):
        issues = [str(i) for i in gate.run(self.mutant(fn)) if i.check == "params"]
        self.assertTrue(any(text in i for i in issues), f"expected [params] ~ '{text}', got {issues}")

    @staticmethod
    def param(root, n):
        pds = next(d for d in root.find("datasources") if d.get("name") == "Parameters")
        return pds.findall("column")[n - 1]

    @staticmethod
    def view(root, sheet):
        return next(w for w in root.iter("worksheet") if w.get("name") == sheet).find("table/view")

    def test_generated_passes(self):
        self.assertEqual(gate.run(self.path), [])

    def test_default_not_a_member(self):
        def m(root):
            c = self.param(root, 1)
            c.set("value", '"Margin"')
            c.find("calculation").set("formula", '"Margin"')
        self.assertCaught(m, "is not one of its members")

    def test_value_differs_from_formula(self):
        self.assertCaught(lambda root: self.param(root, 1).find("calculation").set("formula", '"Profit"'),
                          "differs from its calculation formula")

    def test_value_off_the_range_steps(self):
        def m(root):
            c = self.param(root, 2)
            c.set("value", "7")
            c.find("calculation").set("formula", "7")
        self.assertCaught(m, "is not a step of the range 4..12 by 4")

    def test_value_of_the_wrong_type(self):
        def m(root):
            c = self.param(root, 2)
            c.set("value", '"ten"')
            c.find("calculation").set("formula", '"ten"')
        self.assertCaught(m, "is not a integer literal")

    def test_reference_to_an_undeclared_parameter(self):
        def m(root):
            calc = next(c for c in root.iter("calculation") if "CASE" in c.get("formula", ""))
            calc.set("formula", calc.get("formula").replace("[Parameter 1]", "[Parameter 9]"))
        self.assertCaught(m, "reference to parameter [Parameter 9], which is not declared")

    def test_sheet_without_the_dependency(self):
        def m(root):
            view = self.view(root, "Trend")
            view.remove(next(d for d in view.findall("datasource-dependencies")
                             if d.get("datasource") == "Parameters"))
        self.assertCaught(m, "uses parameter [Parameter 1] without declaring it")

    def test_sheet_without_the_datasource(self):
        def m(root):
            dss = self.view(root, "Top Products").find("datasources")
            dss.remove(next(d for d in dss if d.get("name") == "Parameters"))
        self.assertCaught(m, "does not list the Parameters datasource")

    def test_card_without_the_dependency(self):
        def m(root):
            db = root.find("dashboards/dashboard")
            db.remove(next(d for d in db.findall("datasource-dependencies") if d.get("datasource") == "Parameters"))
        self.assertCaught(m, "dashboard 'Explorer': uses parameter [Parameter 1] without declaring it")

    def test_top_count_by_a_string_parameter(self):
        self.assertCaught(lambda root: self.view(root, "Top Products").find("filter/groupfilter").set(
            "count", "[Parameters].[Parameter 1]"), "is a string parameter, not an integer")

    def test_top_count_not_positive(self):
        self.assertCaught(lambda root: self.view(root, "Most Profitable").find("filter/groupfilter").set("count", "0"),
                          "neither a positive integer nor a parameter")


if __name__ == "__main__":
    unittest.main()
