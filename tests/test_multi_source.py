"""Several independent data sources in one book (decisions/083): spec.split, the datasources and the references of
each sheet, card and action to its own source, expected numbers by source, the gate's check_sources."""
import copy
import csv
import json
import unittest
import zipfile

from lxml import etree

from tbuilder import expected, gate, spec as spec_mod
from tbuilder.build import build
from test_gate import repack
from test_roundtrip import OUT, SPECS

SPEC = json.loads((SPECS / "multi_source.json").read_text(encoding="utf-8"))
PLAN = ["Plan KPI · Plan", "Plan KPI · Attainment", "Sales by Manager"]
ORDERS = ["Orders KPI · Sales", "Orders KPI · Margin", "Orders by Region"]


def mutate(fn, base=SPEC):
    spec = copy.deepcopy(base)
    fn(spec)
    return spec


def built(spec=SPEC, name="multi_source"):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return out, etree.fromstring(z.read(out.stem + ".twb")), set(z.namelist())


def sources(root):
    """{caption: datasource name} of the data sources (not Parameters)."""
    return {d.get("caption"): d.get("name") for d in root.find("datasources") if d.get("name") != "Parameters"}


def sheet_source(root, name):
    ws = next(w for w in root.iter("worksheet") if w.get("name") == name)
    return [d.get("name") for d in ws.findall("table/view/datasources/datasource") if d.get("name") != "Parameters"]


class Split(unittest.TestCase):
    COLS = {"orders": ["Order Date", "Region", "Category", "Sales", "Profit", "Quantity"],
            "plan": ["Month", "Region", "Manager", "Sales", "Plan"]}

    def split(self, spec=SPEC):
        return spec_mod.split(spec, lambda d: self.COLS[d["name"]])

    def test_parts(self):
        (orders, a), (plan, b) = self.split()
        self.assertEqual((orders["name"], plan["name"]), ("orders", "plan"))
        self.assertEqual(a["datasource"], {"type": "csv", "path": "../data/sample/sales.csv"})  # without its name
        self.assertNotIn("datasources", a)
        self.assertEqual([s["name"] for s in a["sheets"]], ["Orders KPI", "Orders by Region"])
        self.assertEqual([s["name"] for s in b["sheets"]], ["Plan KPI", "Sales by Manager"])
        self.assertEqual([c["name"] for c in a["calcs"]], ["Margin"])
        self.assertEqual([c["name"] for c in b["calcs"]], ["Attainment"])
        self.assertEqual([f["field"] for f in a["filters"]], ["Category"])
        self.assertEqual([f["field"] for f in b["filters"]], ["Region"])  # a column of both: the show_on's source
        self.assertEqual(list(a["fields"]), ["Region"])
        self.assertEqual(list(b["fields"]), ["Region", "Manager"])  # Region: a column of both sources
        self.assertIs(a["sheets"][0], SPEC["sheets"][0])  # the spec's own sheet objects
        self.assertEqual(a["dashboard"], SPEC["dashboard"])
        self.assertEqual(a["parameters"], b["parameters"])

    def test_one_source_is_the_spec(self):
        one = {k: v for k, v in SPEC.items() if k != "datasources"}
        one["datasource"] = {"type": "csv", "path": "x.csv"}
        self.assertEqual(spec_mod.split(one, lambda d: []), [(one["datasource"], one)])

    def test_field_of_two_sources_and_of_none(self):
        def f(s):
            s["fields"] = {"Shared": {"caption": "S"}, "Nowhere": {"caption": "N"}}
        self.COLS = {"orders": ["Shared"], "plan": ["Shared"]}
        (_, a), (_, b) = self.split(mutate(f))
        self.assertEqual(list(a["fields"]), ["Shared", "Nowhere"])  # unknown: the first source's builder names it
        self.assertEqual(list(b["fields"]), ["Shared"])

    def test_refusals(self):
        cases = [
            (lambda s: s["sheets"][2].update(datasource="crm"), "datasource 'crm' is not one of"),
            (lambda s: s["calcs"][0].update(datasource="crm"), "Calc 'Margin'"),
            (lambda s: s["filters"][0].update(sheets=["Orders by Region", "Sales by Manager"]),
             "take another datasource"),
            (lambda s: s["datasources"][1].update(name="orders"), "duplicate names"),
            (lambda s: s["datasources"][1].update(path=s["datasources"][0]["path"]), "the same file"),
        ]
        for fn, text in cases:
            with self.subTest(text), self.assertRaisesRegex(spec_mod.SpecError, text):
                self.split(mutate(fn))


class Schema(unittest.TestCase):
    def invalid(self, fn, text):
        with self.assertRaisesRegex(spec_mod.SpecError, text):
            spec_mod.validate(mutate(fn))

    def test_valid(self):
        spec_mod.validate(SPEC)

    def test_datasource_or_datasources(self):
        self.invalid(lambda s: s.update(datasource={"type": "csv", "path": "x.csv"}), "valid under each")
        self.invalid(lambda s: s.pop("datasources"), "is not valid under any")

    def test_items(self):
        self.invalid(lambda s: s["datasources"].pop(), "should be non-empty|too short")
        self.invalid(lambda s: s["datasources"][0].pop("name"), "'name' is a required property")
        self.invalid(lambda s: s["datasources"][0].update(colour="red"), "Unevaluated properties")
        self.invalid(lambda s: s["datasources"][0].update(path="x.xlsx"), "datasources/0/path")


class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out, cls.root, cls.names = built()
        cls.ds = sources(cls.root)

    def test_two_datasources_and_their_data(self):
        self.assertEqual(set(self.ds), {"sales", "sales_plan"})
        self.assertLessEqual({"Data/sample/sales.csv", "Data/sample/sales_plan.csv"}, self.names)
        names = [d.get("name") for d in self.root.find("datasources")]
        self.assertEqual(names, ["Parameters", self.ds["sales"], self.ds["sales_plan"]])  # Parameters, then spec order
        self.assertEqual(self.root.find("windows").get("source-height"), "58")  # the Data pane lists two

    def test_each_sheet_on_its_source(self):
        for n in ORDERS:
            self.assertEqual(sheet_source(self.root, n), [self.ds["sales"]], n)
        for n in PLAN:
            self.assertEqual(sheet_source(self.root, n), [self.ds["sales_plan"]], n)

    def test_calcs_in_their_datasource(self):
        def calcs(ds):
            el = next(d for d in self.root.find("datasources") if d.get("name") == ds)
            return {c.get("caption") for c in el.findall("column") if c.find("calculation") is not None}
        self.assertIn("Margin", calcs(self.ds["sales"]))
        self.assertNotIn("Attainment", calcs(self.ds["sales"]))
        self.assertIn("Attainment", calcs(self.ds["sales_plan"]))
        self.assertNotIn("Margin", calcs(self.ds["sales_plan"]))

    def test_shared_view_per_source(self):
        svs = self.root.findall("shared-views/shared-view")
        self.assertEqual([sv.get("name") for sv in svs], sorted(self.ds.values()))  # by name, as Desktop saves
        self.assertEqual(len(self.root.findall("shared-views")), 1)

    def test_dashboard_cards_of_both_sources(self):
        db = self.root.find("dashboards/dashboard")
        listed = [d.get("name") for d in db.findall("datasources/datasource")]
        self.assertEqual(listed, ["Parameters"] + sorted(self.ds.values()))  # by name, as Desktop saves
        self.assertEqual([d.get("datasource") for d in db.findall("datasource-dependencies")],
                         ["Parameters"] + sorted(self.ds.values()))
        cards = {z.get("name"): z.get("param") for z in db.iter("zone") if z.get("type-v2") == "filter"}
        self.assertEqual(cards, {"Orders by Region": f"[{self.ds['sales']}].[none:Category:nk]",
                                 "Sales by Manager": f"[{self.ds['sales_plan']}].[none:Region:nk]"})

    def test_action_filters_its_source_only(self):
        a = self.root.find("actions/action")
        excl = a.find("command/param[@name='exclude']").get("value").split(",")
        self.assertEqual(excl, PLAN)
        self.assertEqual([d.get("name") for d in self.root.findall("actions/datasources/datasource")],
                         [self.ds["sales"]])

    def test_top_n_by_parameter_on_the_second_source(self):
        flt = next(f for f in next(w for w in self.root.iter("worksheet") if w.get("name") == "Sales by Manager")
                   .iter("filter") if f.find("groupfilter[@function='end']") is not None)
        self.assertEqual(flt.get("column"), f"[{self.ds['sales_plan']}].[none:Manager:nk]")

    def test_gate_passes(self):
        self.assertEqual(gate.run(self.out, SPEC), [])

    def test_refusals(self):
        cases = [
            (lambda s: s["dashboard"]["actions"][0].update(targets=["Plan KPI"]), "take another datasource"),
            (lambda s: (s["sheets"][3].pop("top"), s["sheets"][3].update(title="Managers")),
             "Parameters \\['Top Managers'\\] are not used"),
            (lambda s: s["dashboard"].update(data_as_of="Order Date"), "not supported yet"),
        ]
        for fn, text in cases:
            with self.subTest(text), self.assertRaisesRegex(ValueError, text):
                build(mutate(fn), OUT / "multi_source_bad.twbx", SPECS)


class Expected(unittest.TestCase):
    def test_numbers_by_source(self):
        got = expected.compute(SPEC, expected.data_path(SPEC, SPECS))
        with open(SPECS / "../data/sample/sales_plan.csv", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertAlmostEqual(got["Orders KPI"]["SUM(Sales)"], 224710, delta=1)  # Sales of sales.csv
        self.assertAlmostEqual(got["Plan KPI"]["SUM(Plan)"], sum(float(r["Plan"]) for r in rows), places=6)
        self.assertEqual(set(got["Sales by Manager"]), {"Igor", "Anna", "Denis", "Fedor"})  # Top 4 by sales_plan's Sales

    def test_selection_of_a_card_changes_its_source_only(self):
        base = expected.compute(SPEC, SPECS)
        east = expected.compute(SPEC, SPECS, where={"Region": ["East"]})  # the card on plan's Region
        self.assertEqual(east["Orders by Region"], base["Orders by Region"])  # orders' Region is another field
        self.assertLess(east["Plan KPI"]["SUM(Plan)"], base["Plan KPI"]["SUM(Plan)"])


class GateCatchesSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out, root, _ = built(name="multi_source_src")
        cls.ds = sources(root)

    def caught(self, fn, text, spec=None):
        issues = gate.run(repack(fn, source=self.out), spec)
        self.assertTrue(any(i.check == "sources" and text in i.message for i in issues), issues)

    def view(self, root, name):
        return next(w for w in root.iter("worksheet") if w.get("name") == name).find("table/view")

    def test_unknown_datasource_in_a_list(self):
        def f(root):
            self.view(root, "Orders by Region").find("datasources/datasource").set("name", "federated.nope")
        self.caught(f, "not in the workbook")

    def test_sheet_of_two_sources(self):
        def f(root):
            dss = self.view(root, "Orders by Region").find("datasources")
            etree.SubElement(dss, "datasource", caption="sales_plan", name=self.ds["sales_plan"])
        self.caught(f, "takes 2 data sources")

    def test_reference_to_another_source(self):
        def f(root):
            rows = next(w for w in root.iter("worksheet") if w.get("name") == "Orders by Region").find("table/rows")
            rows.text = rows.text.replace(self.ds["sales"], self.ds["sales_plan"])
        self.caught(f, "not to its data source")

    def test_shared_view_of_no_datasource(self):
        self.caught(lambda root: root.find("shared-views/shared-view").set("name", "federated.gone"), "shared view")

    def test_sheet_on_the_other_source_than_the_spec(self):
        def f(root):  # the worksheets swap their data sources, the datasources stay
            a, b = self.ds["sales"], self.ds["sales_plan"]
            wss = root.find("worksheets")
            raw = etree.tostring(wss).decode().replace(a, "@A@").replace(b, a).replace("@A@", b)
            root.replace(wss, etree.fromstring(raw))
        self.caught(f, "the spec gives it source", SPEC)

    def test_generated_passes(self):
        self.assertEqual([i for i in gate.run(self.out, SPEC) if i.check == "sources"], [])


if __name__ == "__main__":
    unittest.main()
