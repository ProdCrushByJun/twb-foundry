"""Filters v3 (decisions/057): a filter on a calc (text, boolean: a public book's [Order Date] <= [Cutoff] as a shared context
filter), a sheet's own filter of values, a filter on an aggregate (SUM(Sales) >= 9000, an aggregate calc), Tableau's
order of operations for them; the XML Desktop 2025.1 saves (golden_params_filters_v3); gate mutations; rebuild."""
import copy
import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import expected, filters, gate, rebuild
from tbuilder.build import build
from tbuilder.spec import SpecError, validate
from test_roundtrip import OUT, ROOT, SPECS

USER = "{http://www.tableausoftware.com/xml/user}"
CSV = ROOT / "data" / "sample" / "sales_products.csv"


def load():
    return json.loads((SPECS / "params_filters_v3.json").read_text(encoding="utf-8"))


def rows():
    with open(CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def view(root, name):
    return next(ws for ws in root.iter("worksheet") if ws.get("name") == name).find("table/view")


def built(spec, name):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return etree.fromstring(z.read(out.stem + ".twb")), out


class Numbers(unittest.TestCase):
    """expected.py against plain Python over the CSV, at the parameter defaults (cutoff 2025-09-30)."""

    @classmethod
    def setUpClass(cls):
        cls.got = expected.compute(load(), CSV)
        cls.ctx = [r for r in rows() if r["Order Date"] <= "2025-09-30"]

    def sums(self, rs, key):
        out = {}
        for r in rs:
            out[r[key]] = out.get(r[key], 0) + float(r["Sales"])
        return out

    def test_context_filter_on_a_boolean_calc(self):
        self.assertAlmostEqual(self.got["KPI"]["AGG(Shown sales)"], sum(float(r["Sales"]) for r in self.ctx), 6)
        self.assertEqual(max(self.got["Trend"]), "2025-09")

    def test_sheet_filters_of_values(self):
        """Region in North / East and Profit > 0 on this sheet only; the other sheets keep every region."""
        keep = [r for r in self.ctx if r["Region"] in ("North", "East") and float(r["Profit"]) > 0]
        want = self.sums(keep, "Product")
        self.assertEqual(set(self.got["North East"]), set(want))
        for k, v in want.items():
            self.assertAlmostEqual(self.got["North East"][k], v, 6)

    def test_measure_filter_after_the_aggregation(self):
        """A mark stays when its own SUM(Sales) passes: the products' totals, not the orders."""
        totals = self.sums(self.ctx, "Product")
        self.assertEqual(set(self.got["Big Products"]), {k for k, v in totals.items() if v >= 9000})
        self.assertTrue(all(float(r["Sales"]) < 9000 for r in self.ctx))  # no single order passes by itself

    def test_measure_filter_on_an_aggregate_calc_after_a_text_calc_filter(self):
        large = [r for r in self.ctx if int(r["Quantity"]) >= 3]
        by = {}
        for r in large:
            p, s = by.get(r["Region"], (0, 0))
            by[r["Region"]] = (p + float(r["Profit"]), s + float(r["Sales"]))
        want = {k: p / s for k, (p, s) in by.items() if p / s >= 0.14}
        self.assertEqual(set(self.got["Large Orders"]), set(want))
        for k, v in want.items():
            self.assertAlmostEqual(self.got["Large Orders"][k], v, 9)

    def test_top_n_ranks_before_the_sheet_filters(self):
        """Top N is a dimension filter computed before the other dimension filters (020); a sheet's own filter of
        values is one of those: the top members of the context rows, then the rows the sheet keeps."""
        spec = load()
        s = sheet(spec, "Top Products")
        s["filters"] = [{"field": "Region", "default": ["West"]}]
        got = expected.compute(spec, CSV)["Top Products"]
        self.assertEqual(set(got), set(self.got["Top Products"]))  # the same five products
        west = self.sums([r for r in self.ctx if r["Region"] == "West"], "Product")
        for k, v in got.items():
            self.assertAlmostEqual(v, west[k], 6)

    def test_where_does_not_touch_a_sheet_filter(self):
        got = expected.compute(load(), CSV, where={"Before cutoff": {True}})
        self.assertEqual(got["North East"], self.got["North East"])


class Checks(unittest.TestCase):
    def assertRefused(self, fn, text):
        spec = load()
        fn(spec)
        with self.assertRaisesRegex(ValueError, text):
            build(spec, OUT / "filters_v3_refused.twbx", SPECS)

    def test_aggregate_calc_as_a_filter_of_values(self):
        self.assertRefused(lambda s: sheet(s, "North East")["filters"].append({"field": "Margin", "default": ["x"]}),
                           "is an aggregate")

    def test_measure_filter_on_a_row_calc(self):
        self.assertRefused(lambda s: sheet(s, "Big Products")["filters"].append({"field": "Profitable", "min": 1}),
                           "row-level calc")

    def test_value_not_in_the_data(self):
        self.assertRefused(lambda s: sheet(s, "North East")["filters"][0].update(default=["Central"]),
                           "not in the data")

    def test_boolean_default_on_a_text_field(self):
        self.assertRefused(lambda s: sheet(s, "North East")["filters"][0].update(default=[True]), "not in the data")

    def test_same_field_as_a_dashboard_filter(self):
        self.assertRefused(lambda s: sheet(s, "Big Products")["filters"].append(
            {"field": "Before cutoff", "default": [True]}), "also has a dashboard filter")

    def test_two_filters_on_a_field(self):
        self.assertRefused(lambda s: sheet(s, "Big Products")["filters"].append({"field": "Sales", "max": 1}),
                           "two filters")

    def test_top_n_field(self):
        self.assertRefused(lambda s: sheet(s, "Top Products").update(filters=[{"field": "Product",
                                                                               "default": ["Iris"]}]),
                           "Top N is a filter on that field")

    def test_measure_filter_with_a_table_calc(self):
        def f(s):
            sheet(s, "Big Products")["measure"]["table_calc"] = {"type": "percent_of_total"}
            sheet(s, "Big Products")["sort"] = "none"
        self.assertRefused(f, "table calculations or totals")

    def test_fixed_calc_filter(self):
        def f(s):
            s["calcs"].append({"name": "Top region", "formula": 'IF {FIXED [Region] : SUM([Sales])} > 1 THEN "Y" '
                                                                'ELSE "N" END'})
            sheet(s, "North East")["filters"].append({"field": "Top region", "default": ["Y"]})
        self.assertRefused(f, "uses FIXED")

    def test_unverified_sheet_type(self):
        def f(s):
            s["sheets"].append({"name": "Pie", "type": "donut", "dimension": "Region", "measure": {"field": "Sales"},
                                "filters": [{"field": "Region", "default": ["West"]}]})
        with self.assertRaises((ValueError, SpecError)):
            spec = load()
            f(spec)
            validate(spec)
            build(spec, OUT / "filters_v3_refused.twbx", SPECS)

    def test_schema(self):
        for f in ({"field": "Sales", "min": 1, "default": ["x"]}, {"field": "Sales"},
                  {"field": "Sales", "agg": "median", "min": 1}, {"field": "Region", "default": ["West"], "agg": "sum"}):
            spec = load()
            sheet(spec, "Big Products")["filters"] = [f]
            with self.subTest(f=f), self.assertRaises(SpecError):
                validate(spec)


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.path = built(load(), "filters_v3_xml")

    def test_shared_boolean_context_filter(self):
        """a public book's form: member true, unquoted, context; the shared view lists the calc, not its CSV columns."""
        sv = next(self.root.iter("shared-view"))
        (f,) = sv.findall("filter")
        self.assertEqual(f.get("context"), "true")
        self.assertEqual(f[0].get("member"), "true")
        self.assertEqual([c.get("caption") for c in sv.iter("column")], ["Before cutoff"])

    def test_sheet_filters_in_the_view_by_column(self):
        v = view(self.root, "North East")
        kids = [(ch.tag, ch.get("column").split("].")[1]) for ch in v if ch.tag in ("filter", "computed-sort")]
        self.assertEqual([t for t, _ in kids], ["filter", "computed-sort", "filter"])  # Desktop: by column
        self.assertEqual([c for _, c in kids], sorted(c for _, c in kids))
        slices = [c.text.split("].")[1] for c in v.find("slices")]
        self.assertEqual(slices[1:], ["[none:Region:nk]", kids[0][1]])  # after the shared filter, in spec order

    def test_measure_filter_bounds_as_desktop_saves_them(self):
        f = next(x for x in view(self.root, "Big Products").findall("filter") if x.get("class") == "quantitative")
        self.assertEqual((f.get("included-values"), f.findtext("min"), f.find("max")), ("in-range", "9000.0", None))
        f = next(x for x in view(self.root, "Large Orders").findall("filter") if x.get("class") == "quantitative")
        self.assertTrue(f.get("column").endswith(":qk]") and "[usr:" in f.get("column"))
        self.assertEqual(f.findtext("min"), "0.14000000000000001")

    def test_no_card_for_a_sheet_filter(self):
        params = {z.get("param") for z in self.root.iter("zone") if z.get("type-v2") == "filter"}
        self.assertEqual(len(params), 1)  # the shared context filter only

    def test_kpi_tiles_carry_the_kpi_filters(self):
        spec = load()
        sheet(spec, "KPI")["filters"] = [{"field": "Region", "default": ["West"]}]
        root, path = built(spec, "filters_v3_tiles")
        for ws in root.iter("worksheet"):
            if ws.get("name").startswith("KPI · "):
                self.assertIn("[none:Region:nk]", [f.get("column").split("].")[1] for f in ws.iter("filter")])
        self.assertEqual(gate.run(path, spec), [])

    def test_gate_passes(self):
        self.assertEqual(gate.run(self.path, load()), [])


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.path = built(load(), "filters_v3_gate")

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

    def assertCaught(self, fn, text, spec=None):
        issues = [str(i) for i in gate.run(self.mutant(fn), spec) if i.check == "filters"]
        self.assertTrue(any(text in i for i in issues), f"expected [filters] ~ '{text}', got {issues}")

    @staticmethod
    def flt(root, name, cls):
        return next(f for f in view(root, name).findall("filter") if f.get("class") == cls)

    def test_quoted_boolean_member(self):
        self.assertCaught(lambda r: next(r.iter("shared-view")).find("filter")[0].set("member", '"true"'),
                          "keeps the rows where it is true")  # a boolean calc of parameters: the switch check

    def test_quoted_boolean_member_of_a_sheet_filter(self):
        def m(r):
            f = next(x for x in view(r, "North East").findall("filter") if "Calculation_" in x.get("column"))
            f[0].set("member", '"true"')
        self.assertCaught(m, "of a boolean field are not true / false")

    def test_sheet_filter_member_not_in_the_data(self):
        def m(r):
            f = next(x for x in view(r, "North East").findall("filter") if "Region" in x.get("column"))
            f[0][0].set("member", '"Central"')
        self.assertCaught(m, "values the data does not have")

    def test_sheet_filter_not_in_the_slices(self):
        def m(r):
            sl = view(r, "Big Products").find("slices")
            sl.remove(next(c for c in sl if "sum:Sales" in c.text))
        self.assertCaught(m, "not in the sheet's slices")

    def test_measure_filter_without_bounds(self):
        def m(r):
            f = self.flt(r, "Big Products", "quantitative")
            f.remove(f.find("min"))
        self.assertCaught(m, "with min and / or max")

    def test_measure_filter_bound_not_a_number(self):
        self.assertCaught(lambda r: setattr(self.flt(r, "Big Products", "quantitative").find("min"), "text", "9k"),
                          "are not numbers")

    def test_measure_filter_min_above_max(self):
        def m(r):
            f = self.flt(r, "Big Products", "quantitative")
            etree.SubElement(f, "max").text = "100.0"
        self.assertCaught(m, "is above max")

    def test_lost_sheet_filter_by_spec(self):
        def m(r):
            v = view(r, "North East")
            v.remove(next(x for x in v.findall("filter") if "Region" in x.get("column")))
        self.assertCaught(m, "no filter on the field in the sheet", load())

    def test_other_bound_by_spec(self):
        self.assertCaught(lambda r: setattr(self.flt(r, "Big Products", "quantitative").find("min"), "text", "100.0"),
                          "the sheet filters", load())

    def test_shared_calc_filter_in_all_by_spec(self):
        def m(r):
            f = next(r.iter("shared-view")).find("filter")
            g = f[0]
            f.remove(g)
            etree.SubElement(f, "groupfilter", {"function": "level-members", "level": g.get("level"),
                                                f"{USER}ui-enumeration": "all", f"{USER}ui-marker": "enumerate"})
        self.assertCaught(m, "the workbook opens with all", load())


class Rebuild(unittest.TestCase):
    """rebuild reads a sheet's own filters into the spec (decisions/057)."""

    def filt(self, kind, item, **kw):
        return rebuild.Filt(item, kind, text="filter", **kw)

    def test_values_of_a_boolean_calc(self):
        f = rebuild.Fld("[Calculation_1]", "Profitable", "boolean", calc_class="tableau", formula="[Profit] > 0")
        got = rebuild._sheet_filter(self.filt("categorical", rebuild.Item("dim", f), members=["true"]))
        self.assertEqual(got, {"field": "Profitable", "default": [True]})

    def test_exclude_of_a_column(self):
        f = rebuild.Fld("[Region]", "Region")
        got = rebuild._sheet_filter(self.filt("categorical", rebuild.Item("dim", f), members=["West"], exclude=True))
        self.assertEqual(got, {"field": "Region", "default": ["West"], "exclude": True})

    def test_range_of_an_aggregate(self):
        f = rebuild.Fld("[Sales]", "Sales", "real", "measure")
        got = rebuild._sheet_filter(self.filt("range", rebuild.Item("measure", f, "sum"),
                                              detail={"min": "1000", "max": "2500.5"}))
        self.assertEqual(got, {"field": "Sales", "min": 1000, "max": 2500.5})
        got = rebuild._sheet_filter(self.filt("range", rebuild.Item("measure", f, "avg"), detail={"min": "10.",
                                                                                                    "max": None}))
        self.assertEqual(got, {"field": "Sales", "agg": "avg", "min": 10.0})

    def test_context_filter_of_one_sheet(self):
        f = rebuild.Fld("[Region]", "Region")
        with self.assertRaisesRegex(rebuild.Skip, "context filter of one sheet"):
            rebuild._sheet_filter(self.filt("categorical", rebuild.Item("dim", f), members=["West"], context=True))

    def test_set_filter(self):
        with self.assertRaisesRegex(rebuild.Skip, "cannot take"):
            rebuild._sheet_filter(self.filt("categorical", rebuild.Item("other", ref="Top 5 States")))


if __name__ == "__main__":
    unittest.main()
