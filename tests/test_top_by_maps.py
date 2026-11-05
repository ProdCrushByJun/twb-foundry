"""Top N by another measure than the sheet's (top.by) and maps checked after the filters (decisions/067)."""
import copy
import csv
import json
import unittest
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict

from lxml import etree

from tbuilder import expected, gate, maps
from tbuilder.build import build, build_file
from test_gate import repack, ws
from test_roundtrip import OUT, ROOT, SPECS

SPEC = json.loads((SPECS / "top_by.json").read_text(encoding="utf-8"))
CSV = ROOT / "data" / "sample" / "sales_products.csv"
ROWS = list(csv.DictReader(CSV.open(encoding="utf-8")))


def sums(field, rows=ROWS):
    out = defaultdict(float)
    for r in rows:
        out[r["Product"]] += float(r[field])
    return out


def top(values, n):
    return set(sorted(values, key=lambda k: -values[k])[:n])


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def mutate(fn, spec=SPEC):
    spec = copy.deepcopy(spec)
    fn(spec)
    return spec


def twb(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


class Expected(unittest.TestCase):
    """The Top N ranks by top.by, the marks show the sheet's measure (pandas-like sums over the CSV)."""

    @classmethod
    def setUpClass(cls):
        cls.got = expected.compute(SPEC, SPECS / SPEC["datasource"]["path"])

    def test_bar_ranked_by_another_column(self):
        sales, profit = sums("Sales"), sums("Profit")
        want = {k: round(profit[k], 2) for k in top(sales, 5)}
        self.assertEqual({k: round(v, 2) for k, v in self.got["Profit of Top Sellers"].items()}, want)
        self.assertNotEqual(set(want), top(profit, 5))  # by its own measure it would be another list

    def test_bar_ranked_by_an_aggregate_calc(self):
        sales, profit = sums("Sales"), sums("Profit")
        margin = {k: profit[k] / sales[k] for k in sales}
        self.assertEqual(set(self.got["Sales of Top Margins"]), top(margin, 4))
        self.assertNotEqual(top(margin, 4), top(sales, 4))

    def test_registry_ranked_by_an_average(self):
        q, n = sums("Quantity"), defaultdict(int)
        for r in ROWS:
            n[r["Product"]] += 1
        avg = {k: q[k] / n[k] for k in q}
        got = self.got["Busiest Products"]
        self.assertEqual(set(got), top(avg, 6))
        sales = sums("Sales")
        self.assertEqual({k: round(v["Sales"], 2) for k, v in got.items()}, {k: round(sales[k], 2) for k in got})
        self.assertNotEqual(top(avg, 6), top(sales, 6))


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = twb(build_file(SPECS / "top_by.json", OUT / "top_by.twbx"))

    def deps(self, name):
        return ws(self.root, name).find("table/view/datasource-dependencies")

    def order(self, name):
        return ws(self.root, name).find("table/view/filter/groupfilter[@function='end']/groupfilter")

    def test_by_column_declared_without_an_instance(self):
        """As Desktop wrote a public book's State Wise (%): <column name='[Sales]'/> in the sheet, no [sum:Sales:qk]."""
        self.assertEqual(self.order("Profit of Top Sellers").get("expression"), "SUM([Sales])")
        deps = self.deps("Profit of Top Sellers")
        self.assertEqual([c.get("name") for c in deps.findall("column")], ["[Product]", "[Profit]", "[Sales]"])
        self.assertEqual([c.get("name") for c in deps.findall("column-instance")],
                         ["[none:Product:nk]", "[sum:Profit:qk]"])
        self.assertEqual([c.tag for c in deps][:3], ["column"] * 3)  # the columns before the instances

    def test_by_calc_declares_its_columns(self):
        order = self.order("Sales of Top Margins")
        calc = order.get("expression")
        self.assertRegex(calc, r"^\[Calculation_\d+\]$")
        names = [c.get("name") for c in self.deps("Sales of Top Margins").findall("column")]
        self.assertEqual(names, sorted(names, key=lambda n: n))
        self.assertTrue({calc, "[Profit]", "[Sales]"} <= set(names))

    def test_registry_by_an_average(self):
        self.assertEqual(self.order("Busiest Products").get("expression"), "AVG([Quantity])")
        self.assertIn("[Quantity]", [c.get("name") for c in self.deps("Busiest Products").findall("column")])

    def test_without_by_unchanged(self):
        root = twb(build(mutate(lambda s: sheet(s, "Profit of Top Sellers")["top"].pop("by")), OUT / "top_by_plain.twbx",
                         SPECS))
        deps = ws(root, "Profit of Top Sellers").find("table/view/datasource-dependencies")
        self.assertEqual([c.get("name") for c in deps.findall("column")], ["[Product]", "[Profit]"])
        end = ws(root, "Profit of Top Sellers").find("table/view/filter/groupfilter[@function='end']")
        self.assertEqual(end.find("groupfilter").get("expression"), "SUM([Profit])")


class Golden(unittest.TestCase):
    def test_golden_rebuilds_identically(self):
        """golden_top_by_2025_1: specs/top_by.json re-saved by Desktop 2025.1 (resave CLEAN, 3/3 sheets) = the
        generator's output; Desktop kept the by field's bare column and the expressions."""
        import difflib
        from test_roundtrip import canon, normalize, read_twbx
        got, names = read_twbx(build_file(SPECS / "top_by.json", OUT / "roundtrip_top_by.twbx"))
        self.assertIn("Data/sample/sales_products.csv", names)
        want, _ = read_twbx(ROOT / "golden" / "golden_top_by_2025_1.twbx")
        a, b = canon(normalize(want)), canon(normalize(got))
        self.assertEqual(a, b, "\n" + "\n".join(difflib.unified_diff(a, b, "golden", "generated", lineterm="", n=2)))

    def test_rebuild_reads_top_by(self):
        """The golden read as a foreign book: rebuild carries top.by (decisions/067)."""
        import tempfile
        from pathlib import Path
        from tbuilder import rebuild
        with tempfile.TemporaryDirectory() as tmp:
            r = rebuild.rebuild(ROOT / "golden" / "golden_top_by_2025_1.twbx", Path(tmp) / "spec.json")
            got = json.loads((Path(tmp) / "spec.json").read_text(encoding="utf-8"))
        # our registry draws its columns on MIN(1) axes joined with +: rebuild reads no registry of ours (053)
        self.assertEqual([s for s, _ in r.skipped], ["Busiest Products"])
        tops = {s["name"]: s["top"] for s in got["sheets"]}
        self.assertEqual(tops, {"Profit of Top Sellers": {"n": 5, "by": {"field": "Sales"}},
                                "Sales of Top Margins": {"n": 4, "by": {"field": "Margin"}}})


class Refusals(unittest.TestCase):
    def build(self, spec):
        return build(spec, OUT / "top_by_refused.twbx", SPECS)

    def test_by_text_column(self):
        with self.assertRaisesRegex(ValueError, "Product"):
            self.build(mutate(lambda s: sheet(s, "Profit of Top Sellers")["top"].update(by={"field": "Product"})))

    def test_by_table_calc(self):
        def tc(s):
            sheet(s, "Profit of Top Sellers")["top"]["by"] = {"field": "Sales", "table_calc": {"type": "running_total"}}
        with self.assertRaisesRegex(ValueError, "table calculation"):
            self.build(mutate(tc))

    def test_agg_on_an_aggregate_calc(self):
        with self.assertRaisesRegex(ValueError, "aggregate calculation: remove 'agg'"):
            self.build(mutate(lambda s: sheet(s, "Sales of Top Margins")["top"].update(
                by={"field": "Margin", "agg": "avg"})))

    def test_unknown_field(self):
        with self.assertRaisesRegex(ValueError, "Nope"):
            self.build(mutate(lambda s: sheet(s, "Profit of Top Sellers")["top"].update(by={"field": "Nope"})))


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build_file(SPECS / "top_by.json", OUT / "top_by_gate.twbx")

    def caught(self, fn):
        return [str(i) for i in gate.run(repack(fn, source=self.path))]

    def assertCaught(self, fn, text):
        issues = self.caught(fn)
        self.assertTrue(any(i.startswith("[params]") and text in i for i in issues), issues)

    @staticmethod
    def order(r, name):
        return ws(r, name).find("table/view/filter/groupfilter[@function='end']/groupfilter")

    @staticmethod
    def drop_column(r, name, col):
        deps = ws(r, name).find("table/view/datasource-dependencies")
        deps.remove(deps.find(f"column[@name='{col}']"))

    def test_clean(self):
        self.assertEqual(gate.run(self.path), [])

    def test_by_column_not_declared(self):
        self.assertCaught(lambda r: self.drop_column(r, "Profit of Top Sellers", "[Sales]"),
                          "[Sales] is not declared in the sheet's dependencies")

    def test_by_calc_not_declared(self):
        def f(r):
            calc = self.order(r, "Sales of Top Margins").get("expression")
            self.drop_column(r, "Sales of Top Margins", calc)
        self.assertCaught(f, "is not declared in the sheet's dependencies")

    def test_sum_of_text(self):
        self.assertCaught(lambda r: self.order(r, "Profit of Top Sellers").set("expression", "SUM([Product])"),
                          "SUM of a string")

    def test_column_without_aggregation(self):
        self.assertCaught(lambda r: self.order(r, "Profit of Top Sellers").set("expression", "[Sales]"),
                          "a column without an aggregation")

    def test_not_an_expression(self):
        self.assertCaught(lambda r: self.order(r, "Profit of Top Sellers").set("expression", "SUM(Sales)"),
                          "neither AGG([column]) nor [calc]")


GEO = ROOT / "data" / "sample" / "sales_geo.csv"
GEO_ROWS = list(csv.DictReader(GEO.open(encoding="utf-8")))
MAP = {  # Canada's rows carry a province: unknown as a state of the United States, filtered out by Ship Country
    "version": 1, "datasource": {"type": "csv", "path": "PATH"},
    "sheets": [{"name": "States", "type": "map", "style": "filled",
                "geo": {"field": "State", "role": "state", "country": "United States"}, "measure": {"field": "Sales"}}],
    "filters": [{"field": "Ship Country", "default": ["United States"], "show_on": "States"}],
    "dashboard": {"name": "D", "title": "Map", "width": 900, "height": 600, "grid": [["States"]]}}


def map_spec(filters=True):
    path = OUT / "maps_after_filters" / "sales_geo.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(GEO_ROWS[0]))
        w.writeheader()
        w.writerows(dict(r, State="Ontario") if r["Ship Country"] == "Canada" else r for r in GEO_ROWS)
    s = copy.deepcopy(MAP)
    s["datasource"]["path"] = str(path)
    if not filters:
        s.pop("filters")
    return s


class MapsAfterFilters(unittest.TestCase):
    """a public book's Sales by State: the map draws the states left after Country/Region = United States."""

    def test_provinces_filtered_out_build(self):
        s = map_spec()
        self.assertIn("Canada", {r["Ship Country"] for r in GEO_ROWS})
        out = build(s, OUT / "maps_after_filters.twbx", OUT)
        self.assertEqual(gate.run(out), [])
        got = expected.compute(s, s["datasource"]["path"])["States"]
        want = defaultdict(float)
        for r in GEO_ROWS:
            if r["Ship Country"] == "United States":
                want[r["State"]] += float(r["Sales"])
        self.assertEqual({k: round(v, 2) for k, v in got.items()}, {k: round(v, 2) for k, v in want.items()})
        self.assertNotIn("Ontario", got)

    def test_without_the_filter_refused(self):
        with self.assertRaisesRegex(ValueError, r"does not know 1 value\(s\) of 'State'.*'Ontario'"):
            build(map_spec(filters=False), OUT / "maps_after_filters.twbx", OUT)

    def test_shown_values(self):
        s = map_spec()
        from tbuilder.profile import profile_csv as profile
        prof = profile(s["datasource"]["path"])
        self.assertNotIn("Ontario", maps.shown(s, prof, s["sheets"][0], "State"))
        self.assertIn("Ontario", prof.col("State").distinct)

    def test_gate_filter_opened_to_all(self):
        """The gate reads the filter from the XML: at (All) the province reaches the map."""
        out = build(map_spec(), OUT / "maps_after_filters_gate.twbx", OUT)

        def to_all(r):
            flt = next(r.iter("shared-view")).find("filter")
            level = flt.get("column").split("].", 1)[1]
            for g in list(flt):
                flt.remove(g)
            g = etree.SubElement(flt, "groupfilter", {"function": "level-members", "level": level})
            g.set("{http://www.tableausoftware.com/xml/user}ui-enumeration", "all")
            g.set("{http://www.tableausoftware.com/xml/user}ui-marker", "enumerate")
        issues = [str(i) for i in gate.run(repack(to_all, source=out))]
        self.assertTrue(any(i.startswith("[maps]") and "Ontario" in i for i in issues), issues)

    def test_gate_filter_excluding_the_country(self):
        out = build(map_spec(), OUT / "maps_after_filters_gate2.twbx", OUT)

        def other(r):
            for g in next(r.iter("shared-view")).iter("groupfilter"):
                if g.get("member") == '"United States"':
                    g.set("member", '"Canada"')
        issues = [str(i) for i in gate.run(repack(other, source=out))]
        self.assertTrue(any(i.startswith("[maps]") and "Ontario" in i for i in issues), issues)


if __name__ == "__main__":
    unittest.main()
