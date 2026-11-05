"""Dashboard filter actions (todo 3.6): spec checks, the XML Desktop 2025.1 writes, hints, gate mutations."""
import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from urllib.parse import unquote

from lxml import etree

from tbuilder import gate
from tbuilder.build import build
from tbuilder.spec import SpecError, validate
from test_roundtrip import ROOT, SPECS

SPEC = json.loads((SPECS / "actions.json").read_text(encoding="utf-8"))
OUT = ROOT / "out" / "actions_test.twbx"
GOLDEN_TWBX = ROOT / "golden" / "golden_actions_2025_1.twbx"


def built(spec, out=OUT):
    out = build(spec, out, SPECS)
    with zipfile.ZipFile(out) as z:
        return etree.fromstring(z.read(out.stem + ".twb"))


def mutate(fn):
    spec = copy.deepcopy(SPEC)
    fn(spec)
    return spec


def acts(spec):
    return spec["dashboard"]["actions"]


def params(action):
    return {p.get("name"): p.get("value") for p in action.findall("command/param")}


class Schema(unittest.TestCase):
    def test_valid(self):
        validate(SPEC)

    def test_rejected(self):
        for bad in [{"source": "Trend", "on": "menu"}, {"source": "Trend", "clear": "keep"},
                    {"source": "Trend", "targets": "some"}, {"source": "Trend", "targets": []},
                    {"source": "Trend", "fields": []}, {"source": "Trend", "hint": "<b>"},
                    {"source": "Trend", "url": "x"}, {"targets": "all"}]:
            with self.subTest(bad=bad), self.assertRaises(SpecError):
                validate(mutate(lambda s: acts(s).append(bad)))


class Checks(unittest.TestCase):
    def assertRejected(self, fn, text):
        with self.assertRaises(ValueError) as cm:
            built(mutate(fn))
        self.assertIn(text, str(cm.exception))

    def test_source_not_on_dashboard(self):
        def m(s):
            s["sheets"].append({"name": "Spare", "type": "bar", "dimension": "Region", "measure": {"field": "Sales"}})
            acts(s).append({"source": "Spare"})
        self.assertRejected(m, "source sheet is not on the dashboard")

    def test_target_not_on_dashboard(self):
        self.assertRejected(lambda s: acts(s)[1].update(targets=["Nope"]), "target 'Nope' is not on the dashboard")

    def test_source_is_not_its_own_target(self):
        self.assertRejected(lambda s: acts(s)[1].update(targets=["By Category"]), "not filtered by its own action")

    def test_kpi_is_not_a_source(self):
        self.assertRejected(lambda s: acts(s).append({"source": "KPI"}), "a kpi sheet has no dimension marks")

    def test_field_must_be_a_source_dimension(self):
        self.assertRejected(lambda s: acts(s)[1].update(fields=["Region"]),
                            "'Region' is not a dimension of the source sheet (dimensions: ['Category'])")

    def test_calc_field_not_supported(self):
        def m(s):
            s["calcs"] = [{"name": "Big", "formula": "IF [Sales] > 100 THEN \"big\" ELSE \"small\" END"}]
            s["sheets"][2]["color"] = "Big"
            acts(s)[1]["fields"] = ["Big"]
        self.assertRejected(m, "'Big' is a calculated field")

    def test_needs_block_headers(self):
        def m(s):
            s["block_headers"] = False
            s["dashboard"]["theme"] = "flat"
            for sh in s["sheets"]:
                sh.pop("subtitle", None)
        self.assertRejected(m, "need block_headers")

    def test_nothing_to_filter(self):
        def m(s):
            s["dashboard"]["grid"] = [["By Region"]]
            s["dashboard"].pop("row_heights")
            s["dashboard"]["actions"] = [{"source": "By Region"}]
        self.assertRejected(m, "nothing to filter")

    def test_comma_in_excluded_sheet(self):
        def m(s):
            s["sheets"][1]["name"] = "Regions, all"
            s["dashboard"]["grid"][1][0] = "Regions, all"
            acts(s)[0]["source"] = "Regions, all"
        self.assertRejected(m, "sheet 'Regions, all' contains ','")

    def test_hint_too_long_for_the_block(self):
        def m(s):
            s["dashboard"]["width"] = 400  # ~27 characters per 9pt line in a half-width block
            acts(s)[1]["hint"] = "Click a bar to see " * 4
        self.assertRejected(m, "needs ~5 lines")


class Workbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(copy.deepcopy(SPEC))
        cls.acts = cls.root.findall("actions/action")
        cls.ds = cls.root.find("datasources/datasource").get("name")

    def test_order_in_workbook(self):
        tags = [c.tag for c in self.root]
        self.assertEqual(tags.index("actions"), tags.index("worksheets") - 1)

    def test_all_targets_all_fields(self):
        a = self.acts[0]
        self.assertEqual(a.get("caption"), "By Region → All")
        self.assertEqual(a.find("activation").attrib, {"auto-clear": "true", "type": "on-select"})
        self.assertEqual(a.find("source").attrib, {"dashboard": "Actions", "type": "sheet", "worksheet": "By Region"})
        self.assertIsNone(a.find("link"))
        self.assertEqual(params(a), {"special-fields": "all", "target": "Actions"})  # no exclude: every sheet

    def test_selected_field_and_exclude_on_clear(self):
        a = self.acts[1]
        self.assertEqual(params(a), {"exclude": "KPI · Sales,KPI · Profit,By Region,By Category", "on-empty": "none",
                                     "target": "Actions"})  # physical sheets in reading order, source included
        ref = f"[{self.ds}].[Category]"
        self.assertEqual(unquote(a.find("link").get("expression")), f"tsl:Actions?{ref}~s0=<{ref}~na>")
        deps = self.root.find("actions/datasource-dependencies")
        self.assertEqual(deps.get("datasource"), self.ds)
        self.assertEqual([c.get("name") for c in deps.findall("column")], ["[Category]"])

    def test_hover(self):
        a = self.acts[2]
        self.assertEqual(a.find("activation").get("type"), "on-hover")
        self.assertEqual(params(a)["exclude"], "By Region,By Category,Trend")  # targets: the KPI tiles

    def test_insight_line_goes_with_its_sheet(self):
        spec = copy.deepcopy(SPEC)
        for s in spec["sheets"]:
            if s["name"] in ("By Region", "Trend"):
                s["insight"] = "Total **[Total Sales]**"
        spec.setdefault("calcs", []).append({"name": "Total Sales", "formula": "SUM([Sales])"})
        spec["dashboard"]["actions"] = [{"source": "By Category", "type": "filter", "targets": ["Trend"]}]
        spec["dashboard"]["height"] = 1400  # room for the two insight lines
        excluded = params(built(spec).find("actions/action"))["exclude"].split(",")
        self.assertIn("By Region · Insight", excluded)
        self.assertNotIn("Trend · Insight", excluded)

    def test_ids_are_stable_and_unique(self):
        names = [a.get("name") for a in self.acts]
        self.assertEqual(len(set(names)), 3)
        again = built(copy.deepcopy(SPEC), ROOT / "out" / "actions_test_again.twbx")
        self.assertEqual(names, [a.get("name") for a in again.findall("actions/action")])

    def test_signed_in_the_source_block(self):
        texts = ["".join(r.text or "" for r in z.iter("run")) for z in self.root.iter("zone")
                 if z.get("type-v2") == "text"]
        self.assertIn("RegionsÆ\nSales and profit | Click to filter", texts)
        self.assertIn("CategoriesÆ\nSum of sales | Click a bar to see its trend", texts)
        self.assertIn("Monthly SalesÆ\nHover to filter", texts)  # no subtitle: the hint becomes it

    def test_no_actions_no_element(self):
        root = built(mutate(lambda s: s["dashboard"].pop("actions")))
        self.assertIsNone(root.find("actions"))


def repack(src, fn):
    """Copy a .twbx with its workbook XML mutated by fn(root); return the new path."""
    with zipfile.ZipFile(src) as z:
        members = {n: z.read(n) for n in z.namelist()}
    twb = next(n for n in members if n.endswith(".twb"))
    root = etree.fromstring(members[twb])
    fn(root)
    members[twb] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
    path = Path(tempfile.mkdtemp()) / "mutant.twbx"
    with zipfile.ZipFile(path, "w") as z:
        for n, b in members.items():
            z.writestr(n, b)
    return path


class Gate(unittest.TestCase):
    """Break the actions of the Desktop-saved golden one way at a time; the gate must name the break."""

    def assertCaught(self, fn, text):
        issues = [str(i) for i in gate.run(repack(GOLDEN_TWBX, fn))]
        self.assertTrue(any(i.startswith("[actions]") and text in i for i in issues), issues)

    @staticmethod
    def action(root, i):
        return root.findall("actions/action")[i]

    def test_golden_passes(self):
        self.assertEqual(gate.run(GOLDEN_TWBX), [])

    def test_unknown_source_sheet(self):
        self.assertCaught(lambda r: self.action(r, 0).find("source").set("worksheet", "Gone"),
                          "source sheet 'Gone' is not on Actions")

    def test_unknown_source_dashboard(self):
        self.assertCaught(lambda r: self.action(r, 0).find("source").set("dashboard", "Other"),
                          "source dashboard 'Other' does not exist")

    def test_unknown_target(self):
        def m(r):
            next(p for p in self.action(r, 0).iter("param") if p.get("name") == "target").set("value", "Other")
        self.assertCaught(m, "target 'Other' is neither a dashboard nor a worksheet")

    def test_excluded_sheet_not_on_dashboard(self):
        def m(r):
            p = next(p for p in self.action(r, 1).iter("param") if p.get("name") == "exclude")
            p.set("value", p.get("value") + ",Gone")
        self.assertCaught(m, "excluded sheet 'Gone' is not on dashboard 'Actions'")

    def test_everything_excluded(self):
        def m(r):
            p = next(p for p in self.action(r, 1).iter("param") if p.get("name") == "exclude")
            p.set("value", p.get("value") + ",Trend")
        self.assertCaught(m, "filters no sheet")

    def test_link_field_not_in_datasource(self):
        def m(r):
            link = self.action(r, 1).find("link")
            link.set("expression", link.get("expression").replace("Category", "Segment"))
        self.assertCaught(m, "field [Segment] is not in datasource")

    def test_link_field_not_declared(self):
        def m(r):
            link = self.action(r, 1).find("link")
            link.set("expression", link.get("expression").replace("Category", "Region"))
        self.assertCaught(m, "field [Region] is not declared")

    def test_target_without_the_field_datasource(self):
        def m(r):
            trend = next(w for w in r.iter("worksheet") if w.get("name") == "Trend")
            trend.find("table/view/datasources/datasource").set("name", "federated.other")
        self.assertCaught(m, "target sheet 'Trend' does not use datasource")


if __name__ == "__main__":
    unittest.main()
