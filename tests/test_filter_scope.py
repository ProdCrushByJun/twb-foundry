"""A filter of one dashboard in a book with several dashboards (decisions/071): Desktop's 'Apply to selected
worksheets' - a copy of the filter in each sheet's view tied by `filter-group`, no shared-view."""
import copy
import json
import unittest
import zipfile

from lxml import etree

from tbuilder import expected, filters, gate
from tbuilder.build import build
from test_gate import repack
from test_roundtrip import OUT, SPECS

CSV = SPECS / "../data/sample/sales.csv"
SPEC = {
    "$schema": "../tbuilder/spec.schema.json", "version": 1,
    "datasource": {"type": "csv", "path": "../data/sample/sales.csv"},
    "sheets": [
        {"name": "KPI", "type": "kpi", "style": "tiles", "measures": [{"field": "Sales"}, {"field": "Profit"}]},
        {"name": "By Category", "type": "bar", "dimension": "Category", "measure": {"field": "Sales"}, "sort": "desc"},
        {"name": "Trend", "type": "line", "date": {"field": "Order Date", "level": "month"},
         "measure": {"field": "Sales"}},
        {"name": "Matrix", "type": "table", "rows": "Region", "cols": "Category", "measure": {"field": "Sales"}}
    ],
    "filters": [{"field": "Region", "show_on": "By Category", "mode": "single_dropdown"}],
    "dashboards": [
        {"name": "Overview", "title": "Overview", "width": 1000, "height": 800, "row_heights": [1, 3],
         "grid": [["KPI"], ["By Category"]]},
        {"name": "Details", "title": "Details", "width": 1000, "height": 800, "grid": [["Trend"], ["Matrix"]]}
    ],
    "nav": {"style": "tabs"}
}
REGION = "[federated.{}].[none:Region:nk]"


def mutate(fn, base=SPEC):
    spec = copy.deepcopy(base)
    fn(spec)
    return spec


def built(spec, name="filter_scope"):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return out, etree.fromstring(z.read(out.stem + ".twb"))


def region_filters(root):
    """{worksheet: its view's filter on Region}."""
    out = {}
    for ws in root.iter("worksheet"):
        for f in ws.findall("table/view/filter"):
            if f.get("column", "").endswith("[none:Region:nk]"):
                out[ws.get("name")] = f
    return out


def cards(root, dashboard):
    db = next(d for d in root.iter("dashboard") if d.get("name") == dashboard)
    return [z for z in db.iter("zone") if z.get("type-v2") == "filter"]


class Scope(unittest.TestCase):
    def test_scope_is_the_card_dashboard(self):
        self.assertEqual(filters.scope(SPEC, SPEC["filters"][0]), {"KPI", "By Category"})

    def test_shared_sheet_pulls_its_dashboard_in(self):
        three = mutate(lambda s: s["dashboards"][1].update(grid=[["Trend"]])
                       or s["dashboards"].append({"name": "Third", "grid": [["Matrix"]]}))
        self.assertEqual(filters.scope(three, three["filters"][0]), {"KPI", "By Category"})
        three["dashboards"][1]["grid"].append(["By Category"])  # Details shares By Category: Details joins
        self.assertEqual(filters.scope(three, three["filters"][0]), {"KPI", "By Category", "Trend"})

    def test_every_dashboard_is_the_shared_view(self):
        spec = mutate(lambda s: s["dashboards"][1]["grid"].append(["By Category"]))
        self.assertIsNone(filters.scope(spec, spec["filters"][0]))

    def test_workbook_scope_and_one_dashboard(self):
        self.assertIsNone(filters.scope(SPEC, {**SPEC["filters"][0], "scope": "workbook"}))
        one = mutate(lambda s: s.update(dashboard=s.pop("dashboards")[0]) or s.pop("nav"))
        self.assertIsNone(filters.scope(one, one["filters"][0]))


class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out, cls.root = built(SPEC)

    def test_no_shared_view(self):
        self.assertEqual(list(self.root.iter("shared-view")), [])

    def test_only_the_dashboards_sheets_carry_it(self):
        got = region_filters(self.root)
        self.assertEqual(set(got), {"KPI · Sales", "KPI · Profit", "By Category"})
        self.assertEqual({f.get("filter-group") for f in got.values()}, {"3"})  # Desktop rewrites 1 and 2 on save
        for ws in self.root.iter("worksheet"):
            slices = [c.text for c in ws.findall("table/view/slices/column")]
            self.assertEqual(any(c.endswith("[none:Region:nk]") for c in slices), ws.get("name") in got, ws.get("name"))

    def test_card_only_on_its_dashboard(self):
        self.assertEqual([z.get("name") for z in cards(self.root, "Overview")], ["By Category"])
        self.assertEqual(cards(self.root, "Details"), [])

    def test_gate_passes(self):
        self.assertEqual(gate.run(self.out, SPEC), [])

    def test_workbook_scope_keeps_the_shared_view(self):
        out, root = built(mutate(lambda s: s["filters"][0].update(scope="workbook")), "filter_scope_wb")
        self.assertEqual(len(list(root.iter("shared-view"))), 1)
        self.assertEqual(region_filters(root), {})
        self.assertEqual(len(cards(root, "Details")), 1)

    def test_refusals(self):
        with self.assertRaisesRegex(ValueError, "scope 'workbook'"):
            built(mutate(lambda s: s["filters"].append({"field": "Order Date", "show_on": "By Category",
                                                        "mode": "range"})), "filter_scope_bad")
        with self.assertRaisesRegex(ValueError, "scope 'workbook'"):
            built(mutate(lambda s: s["filters"][0].update(context=True)), "filter_scope_bad")


class Expected(unittest.TestCase):
    def test_selection_filters_only_its_dashboard(self):
        spec = json.loads(json.dumps(SPEC))
        spec["datasource"]["path"] = str(CSV.resolve())
        all_ = expected.compute(spec, CSV)
        east = expected.compute(spec, CSV, where={"Region": ["East"]})
        self.assertEqual(east["Trend"], all_["Trend"])  # Details: not filtered
        self.assertEqual(east["Matrix"], all_["Matrix"])
        self.assertLess(sum(east["By Category"].values()), sum(all_["By Category"].values()))


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out, _ = built(SPEC, "filter_scope_src")

    def caught(self, fn, text):
        issues = gate.run(repack(fn, source=self.out))
        self.assertTrue(any(text in i.message for i in issues), issues)

    def test_card_missing(self):
        def drop(root):
            for z in [z for z in root.iter("zone") if z.get("type-v2") == "filter"]:
                z.getparent().remove(z)
        self.caught(drop, "no card")

    def test_copies_differ(self):
        def change(root):
            f = region_filters(root)["KPI · Sales"]
            g = f.find("groupfilter")
            g.set("function", "member")
            g.set("member", '"East"')
        self.caught(change, "differs")

    def test_group_on_a_dashboard_without_card(self):
        def add(root):
            src = region_filters(root)["By Category"]
            view = next(w for w in root.iter("worksheet") if w.get("name") == "Trend").find("table/view")
            slices = view.find("slices")
            if slices is None:
                slices = etree.Element("slices")
                view.insert(list(view).index(view.find("aggregation")), slices)
            view.insert(list(view).index(slices), copy.deepcopy(src))
            etree.SubElement(slices, "column").text = src.get("column")
        self.caught(add, "no card")


ONE = {k: v for k, v in SPEC.items() if k not in ("dashboards", "nav")}
ONE["dashboard"] = {"name": "Overview", "title": "Overview", "width": 1000, "height": 900, "row_heights": [1, 2, 2],
                    "grid": [["KPI"], ["By Category", "Matrix"], ["Trend"]]}


class Sheets(unittest.TestCase):
    """`sheets` on a filter (decisions/074): Tableau's 'Apply to selected worksheets' - only the listed sheets."""

    def test_only_the_listed_sheets_carry_it(self):
        spec = mutate(lambda s: s["filters"][0].update(sheets=["By Category"]), ONE)
        out, root = built(spec, "filter_sheets")
        self.assertEqual(list(root.iter("shared-view")), [])
        self.assertEqual(set(region_filters(root)), {"By Category"})
        self.assertEqual([z.get("name") for z in cards(root, "Overview")], ["By Category"])
        self.assertEqual(gate.run(out, spec), [])

    def test_a_kpi_listed_carries_it_on_every_tile(self):
        spec = mutate(lambda s: s["filters"][0].update(sheets=["By Category", "KPI"]), ONE)
        _, root = built(spec, "filter_sheets_kpi")
        self.assertEqual(set(region_filters(root)), {"By Category", "KPI · Sales", "KPI · Profit"})

    def test_card_on_each_dashboard_of_a_listed_sheet(self):
        spec = mutate(lambda s: s["filters"][0].update(sheets=["By Category"])
                      or s["dashboards"][1]["grid"].append(["By Category"]))
        out, root = built(spec, "filter_sheets_two")
        self.assertEqual(set(region_filters(root)), {"By Category"})
        self.assertEqual([z.get("name") for z in cards(root, "Details")], ["By Category"])  # not Trend / Matrix
        self.assertEqual(gate.run(out, spec), [])

    def test_every_sheet_listed_is_the_shared_view(self):
        spec = mutate(lambda s: s["filters"][0].update(sheets=["KPI", "By Category", "Trend", "Matrix"]), ONE)
        _, root = built(spec, "filter_sheets_all")
        self.assertEqual(len(list(root.iter("shared-view"))), 1)

    def test_refusals(self):
        for fn, text, base in [(lambda f: f.update(sheets=["By Category"], show_on="Matrix"), "show_on", ONE),
                               (lambda f: f.update(sheets=["Nope"]), "no sheet", ONE),
                               (lambda f: f.update(sheets=["By Category"], scope="workbook"), "'workbook'", SPEC)]:
            with self.assertRaisesRegex(ValueError, text):
                built(mutate(lambda s: fn(s["filters"][0]), base), "filter_sheets_bad")

    def test_expected_filters_only_the_listed(self):
        spec = mutate(lambda s: s["filters"][0].update(sheets=["By Category"]), ONE)
        spec["datasource"]["path"] = str(CSV.resolve())
        plain = copy.deepcopy(spec)
        all_ = expected.compute(plain, CSV)
        east = expected.compute(spec, CSV, where={"Region": ["East"]})
        self.assertEqual(east["Matrix"], all_["Matrix"])  # on the dashboard, not listed
        self.assertEqual(east["KPI"], all_["KPI"])
        self.assertLess(sum(east["By Category"].values()), sum(all_["By Category"].values()))
