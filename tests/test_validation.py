"""Data-dependent spec errors (schema-valid but wrong for this CSV) must fail loudly at build time."""
import copy
import json
import unittest
from pathlib import Path

from tbuilder.build import build
from test_roundtrip import SPECS

GOLDEN_SPEC = json.loads((SPECS / "golden.json").read_text(encoding="utf-8"))

OUT = Path(__file__).resolve().parent.parent / "out" / "invalid.twbx"


def mutate(fn):
    spec = copy.deepcopy(GOLDEN_SPEC)
    fn(spec)
    return spec


class InvalidSpecs(unittest.TestCase):
    def assertRejects(self, spec, msg):
        with self.assertRaisesRegex((ValueError, KeyError), msg):
            build(spec, OUT, SPECS)

    def test_unknown_field(self):
        self.assertRejects(mutate(lambda s: s["sheets"][1].update(dimension="Country")), "not found")

    def test_sum_of_string(self):
        self.assertRejects(mutate(lambda s: s["sheets"][1].update(measure={"field": "Region"})), "non-numeric")

    def test_date_as_plain_dimension(self):
        self.assertRejects(mutate(lambda s: s["sheets"][1].update(dimension="Order Date")), "is a date")

    def test_numeric_field_as_dimension(self):
        self.assertRejects(mutate(lambda s: s["sheets"][1].update(dimension="Quantity")), "numeric")

    def test_line_on_non_date(self):
        self.assertRejects(mutate(lambda s: s["sheets"][2].update(date={"field": "Region"})), "not a date")

    def test_dashboard_unknown_sheet(self):
        self.assertRejects(mutate(lambda s: s["dashboard"]["grid"][0].append("Ghost")), "unknown sheet")

    def test_duplicate_sheet_names(self):
        self.assertRejects(mutate(lambda s: s["sheets"][1].update(name="KPI")), "Duplicate sheet")

    def test_filter_card_off_dashboard(self):
        self.assertRejects(mutate(lambda s: s["filters"][0].update(show_on="Nowhere")), "not on the dashboard")

    def test_aggregate_calc_with_agg(self):
        def f(s):
            s["calcs"] = [{"name": "PR", "formula": "SUM([Profit]) / SUM([Sales])"}]
            s["sheets"][1]["measure"] = {"field": "PR", "agg": "sum"}
        self.assertRejects(mutate(f), "remove 'agg'")

    def test_aggregate_calc_as_dimension(self):
        def f(s):
            s["calcs"] = [{"name": "PR", "formula": "SUM([Profit]) / SUM([Sales])"}]
            s["sheets"][1]["dimension"] = "PR"
        self.assertRejects(mutate(f), "only be a measure")

    def test_filter_on_calc(self):
        def f(s):
            s["calcs"] = [{"name": "Big", "formula": 'IF SUM([Sales]) > 500 THEN "Y" ELSE "N" END'}]
            s["filters"][0]["field"] = "Big"
        self.assertRejects(mutate(f), "is an aggregate")  # a row-level calc is a filter field since 057

    def test_bad_formula_names_the_calc(self):
        def f(s):
            s["calcs"] = [{"name": "PR", "formula": "SUM([Profit]) / [Sales]"}]
        self.assertRejects(mutate(f), "'PR'.*cannot mix aggregate")

    def test_include_calc_as_dimension(self):
        def f(s):
            s["calcs"] = [{"name": "Per Cat", "formula": "{INCLUDE [Category] : SUM([Sales])}"}]
            s["sheets"][1]["color"] = "Per Cat"
        self.assertRejects(mutate(f), "INCLUDE/EXCLUDE: it can only be a measure")

    def test_table_calc_along_must_be_sheet_dimension(self):
        self.assertRejects(mutate(lambda s: s["sheets"][1]["measure"].update(
            table_calc={"type": "percent_of_total", "along": ["Category"]}) or s["sheets"][1].pop("color")),
            "not a dimension of this sheet")

    def test_table_calc_needs_dimensions(self):
        self.assertRejects(mutate(lambda s: s["sheets"][0]["measures"][0].update(
            table_calc={"type": "running_total"})), "needs dimensions")

    def test_table_calc_with_sort(self):
        def f(s):
            s["sheets"][1]["measure"]["table_calc"] = {"type": "percent_of_total"}
            s["sheets"][1]["sort"] = "desc"
        self.assertRejects(mutate(f), "sorting by a table calculation")

    def test_row_heights_count(self):
        self.assertRejects(mutate(lambda s: s["dashboard"].update(row_heights=[1, 2, 3])), "row_heights")

    def test_duplicate_tile_labels(self):
        self.assertRejects(mutate(lambda s: s["sheets"][0].update(
            style="tiles", measures=[{"field": "Sales"}, {"field": "Profit", "label": "Sales"}])), "unique")

    def test_tile_name_collides_with_sheet(self):
        def f(s):
            s["sheets"][0].update(style="tiles")
            s["sheets"][1]["name"] = "KPI · Sales"
            s["dashboard"]["grid"][0][1] = "KPI · Sales"
        self.assertRejects(mutate(f), "collide")


class Legends(unittest.TestCase):
    def test_one_legend_per_color_field(self):
        import zipfile
        from lxml import etree
        spec = copy.deepcopy(GOLDEN_SPEC)
        spec["sheets"].append({"name": "Bar 2", "type": "bar", "dimension": "Region",
                               "measure": {"field": "Profit"}, "color": "Category"})
        spec["dashboard"]["grid"].append(["Bar 2"])
        out = build(spec, OUT.with_name("legends.twbx"), SPECS)
        root = etree.fromstring(zipfile.ZipFile(out).read("legends.twb"))
        legends = [z for z in root.iter("zone") if z.get("type-v2") == "color"]
        self.assertEqual(len(legends), 1)


if __name__ == "__main__":
    unittest.main()
