"""Interactivity (todo 8.7, decisions/042): buttons that set a parameter (parameter actions), a period switch, radio
parameter cards, a view switch (dynamic zone visibility) - spec checks, XML, expected, gate mutations."""
import copy
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import design_lint, expected, gate, interact
from tbuilder.build import build
from tbuilder.spec import SpecError, validate
from test_roundtrip import ROOT, SPECS

sys.path.insert(0, str(ROOT / "tools"))
from param_variant import variant  # noqa: E402

SPEC = json.loads((SPECS / "interactive.json").read_text(encoding="utf-8"))
CSV = ROOT / "data" / "sample" / "sales_products.csv"
USER = "{http://www.tableausoftware.com/xml/user}"


def mutate(fn, base=SPEC):
    spec = copy.deepcopy(base)
    fn(spec)
    return spec


def built(spec, name="interact_test"):
    out = build(spec, ROOT / "out" / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return etree.fromstring(z.read(out.stem + ".twb")), out


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


def views(root, prefix):
    """The switch's view containers: the zones holding a sheet zone whose name starts with prefix, with the card
    around it when there is one (decisions/168: container > card > inner zone > sheet)."""
    out = []
    for z in root.iter("zone"):
        if z.get("type-v2", "").startswith("layout") and any(
                k.get("name", "").startswith(prefix) and not k.get("type-v2") for k in z):
            while len(z.getparent().findall("zone")) == 1:
                z = z.getparent()
            out.append(z)
    return out


class Schema(unittest.TestCase):
    def test_valid(self):
        validate(SPEC)

    def test_rejected(self):
        cases = [
            lambda s: sheet(s, "Periods").pop("parameter"),
            lambda s: sheet(s, "Periods").update(arrange="grid"),
            lambda s: sheet(s, "Products").pop("views"),
            lambda s: sheet(s, "Products").update(views={"Chart": "Products Chart"}),
            lambda s: s["parameters"][2].update(control="slider"),
            lambda s: s["parameters"][1].update(period={"field": "Order Date", "anchor": "2025-12-31"}),
        ]
        for fn in cases:
            with self.assertRaises(SpecError):
                validate(mutate(fn))


class Checks(unittest.TestCase):
    def assertRejected(self, fn, text):
        with self.assertRaises(ValueError) as cm:
            build(mutate(fn), ROOT / "out" / "interact_reject.twbx", SPECS)
        self.assertIn(text, str(cm.exception))

    def test_buttons_need_a_list_parameter(self):
        self.assertRejected(lambda s: sheet(s, "Periods").update(parameter="Nope"), "is not declared")
        self.assertRejected(lambda s: (s["parameters"].append(
            {"name": "N", "type": "integer", "range": {"min": 1, "max": 3}, "default": 1}),
            s["sheets"].append({"name": "Ns", "type": "buttons", "parameter": "N"})), "is a range")
        self.assertRejected(lambda s: (s["sheets"].append({"name": "Again", "type": "buttons", "parameter": "Period"}),
                                       s["dashboard"]["grid"].append(["Again"])), "two buttons sheets")

    def test_radio_takes_a_string_parameter(self):
        self.assertRejected(lambda s: (s["parameters"].append(
            {"name": "N", "type": "integer", "range": {"min": 1, "max": 3}, "default": 1, "control": "radio"}),
            s["calcs"].append({"name": "N twice", "formula": "[N] * 2"})), "radio buttons list the values")

    def test_period_values_and_field(self):
        self.assertRejected(lambda s: s["parameters"][1].update(values=["L6M", "YTD", "All"]), "are not periods")
        self.assertRejected(lambda s: s["parameters"][1].update(period={"field": "Region"}), "must be a date column")

    def test_switch_views(self):
        self.assertRejected(lambda s: sheet(s, "Products").update(views={"Chart": "Products Chart",
                                                                         "Map": "Products Table"}),
                            "must be the values")
        self.assertRejected(lambda s: sheet(s, "Products")["views"].update(Table="Periods"), "a switch shows")
        self.assertRejected(lambda s: sheet(s, "Products")["views"].update(Table="Products Chart"),
                            "already a view")
        self.assertRejected(lambda s: s["dashboard"]["grid"].append(["Products Table"]), "place the switch")

    def test_buttons_need_room(self):
        self.assertRejected(lambda s: s["dashboard"].update(row_heights=[1, 12, 12]), "too short for its buttons")


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.out = built(SPEC)
        cls.ds = next(d.get("name") for d in cls.root.find("datasources") if d.get("name") != "Parameters")
        cls.calc = {c.get("caption"): c.get("name")[1:-1] for c in cls.root.find("datasources")[1].findall("column")
                    if c.find("calculation") is not None}

    def test_one_worksheet_per_button(self):
        names = [w.get("name") for w in self.root.iter("worksheet")]
        self.assertEqual(names[:7], ["Periods · L3M", "Periods · L6M", "Periods · L9M", "Periods · All",
                                     "Metrics · Sales", "Metrics · Profit", "Metrics · Quantity"])
        self.assertNotIn("Products", names)  # a switch is no worksheet
        ws = self.root.find("worksheets/worksheet[@name='Periods · L6M']")
        enc = ws.find("table/panes/pane/encodings")
        self.assertEqual(enc.find("text").get("column"), f"[{self.ds}].[none:{self.calc['Period · L6M']}:nk]")
        self.assertEqual(enc.find("color").get("column"), f"[{self.ds}].[none:{self.calc['Period · L6M · on']}:nk]")

    def test_parameter_actions(self):
        acts = self.root.findall("actions/edit-parameter-action")
        self.assertEqual(len(acts), 7)
        self.assertEqual([a.get("name") for a in acts], sorted(a.get("name") for a in acts))  # Desktop's order
        a = next(a for a in acts if a.get("caption") == "Metrics · Profit")
        self.assertEqual(a.find("activation").get("type"), "on-select")
        self.assertEqual(a.find("source").attrib, {"dashboard": "Explorer", "type": "sheet",
                                                   "worksheet": "Metrics · Profit"})
        self.assertEqual(a.find("clear-option").attrib, {"type": "do-nothing", "value": "s:LROOT:"})
        ps = {p.get("name"): p.get("value") for p in a.iter("param")}
        self.assertEqual(ps, {"source-field": f"[{self.ds}].[none:{self.calc['Metric · Profit']}:nk]",
                              "target-parameter": "[Parameters].[Parameter 1]"})
        self.assertIsNone(self.root.find("actions/action"))  # no filter actions in this spec

    def test_manifest_flags(self):
        flags = [e.tag for e in self.root.find("document-format-change-manifest")]
        for f in interact.ACTION_FLAGS + interact.DZV_FLAGS:
            self.assertIn(f, flags)
        self.assertEqual(flags, sorted(flags))

    def test_period_filter_is_a_shared_filter_without_card(self):
        col = f"[{self.ds}].[none:{self.calc['Period filter']}:nk]"
        flt = self.root.find(f"shared-views/shared-view/filter[@column='{col}']")
        g = flt.find("groupfilter")
        self.assertEqual((g.get("function"), g.get("member"), g.get(f"{USER}ui-enumeration")),
                         ("member", "true", "inclusive"))
        self.assertEqual(flt.find("target").get("field"), col)
        for ws in self.root.iter("worksheet"):
            self.assertIn(col, [c.text for c in ws.findall("table/view/slices/column")], ws.get("name"))
        self.assertFalse([z for z in self.root.iter("zone") if z.get("type-v2") == "filter"])
        formula = self.root.find(f".//column[@name='[{self.calc['Period filter']}]']/calculation").get("formula")
        self.assertIn("WHEN \"L6M\" THEN DATEDIFF('month', [Order Date], {FIXED : MAX([Order Date])}) < 6", formula)
        self.assertIn('WHEN "All" THEN TRUE END', formula)
        # declared without the CSV columns of its formula: Desktop 2025.1 drops [Order Date] there on Save As (061)
        deps = self.root.find("shared-views/shared-view/datasource-dependencies")
        self.assertNotIn("[Order Date]", [c.get("name") for c in deps.findall("column")])

    def test_header_cards(self):
        cards = [z for z in self.root.iter("zone") if z.get("type-v2") == "paramctrl"]
        self.assertEqual([(z.get("param"), z.get("mode")) for z in cards], [("[Parameters].[Parameter 3]", "list")])
        db = self.root.find("dashboards/dashboard")
        deps = db.find("datasource-dependencies[@datasource='Parameters']")
        self.assertEqual([c.get("name") for c in deps.findall("column")], ["[Parameter 3]"])  # only the carded one

    def test_switch_zones_and_datagraph(self):
        db = self.root.find("dashboards/dashboard")
        flows = views(db, "Products ")
        self.assertEqual([z.get("hidden-by-user") for z in flows], [None, "true"])  # Chart shown, Table hidden
        self.assertEqual(flows[0].getparent(), flows[1].getparent())
        self.assertEqual({z.get("type-v2") for z in flows}, {"layout-basic"})  # decisions/082
        self.assertEqual({z.get("hidden-by-user") for z in flows[1].iter("zone")}, {"true"})  # as Desktop saves it
        self.assertEqual({z.get("hidden-by-user") for z in flows[0].iter("zone")}, {None})
        nodes = self.root.findall("datagraph/graph/nodes/dashboard-zone-visibility-node")
        self.assertEqual([n.get("zone-id") for n in nodes], [z.get("id") for z in flows])
        self.assertEqual({n.get("dashboard-identifier") for n in nodes}, {db.find("simple-id").get("uuid")})
        fields = self.root.findall("datagraph/graph/nodes/single-value-field-node")
        self.assertEqual([f.get("fieldname") for f in fields],
                         [f"[{self.ds}].[{self.calc['Products · Chart']}]", f"[{self.ds}].[{self.calc['Products · Table']}]"])
        self.assertEqual(len(self.root.findall("datagraph/graph/edges/edge")), 2)

    def test_variant_passes_the_gate(self):
        with tempfile.TemporaryDirectory() as d:
            out = variant(self.out, Path(d) / "v.twbx", {"View": "Table", "Period": "All"})
            self.assertEqual(gate.run(out), [])
            with zipfile.ZipFile(out) as z:
                root = etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))
        flows = views(root, "Products ")
        self.assertEqual([z.get("hidden-by-user") for z in flows], ["true", None])
        self.assertEqual({z.get("hidden-by-user") for z in flows[0].iter("zone")}, {"true"})
        self.assertEqual({z.get("hidden-by-user") for z in flows[1].iter("zone")}, {None})

    def test_lint_clean(self):
        self.assertFalse([f for f in design_lint.lint(SPEC) if f.level == "error"])


class Expected(unittest.TestCase):
    def test_period_switch_filters_the_rows(self):
        e = expected.compute(SPEC, CSV)
        self.assertEqual(list(e["Trend"]), [f"2025-{m:02d}" for m in range(7, 13)])  # L6M of Dec 2025
        self.assertAlmostEqual(sum(e["Trend"].values()), 85679.67, places=2)
        totals = {v: sum(x for x in out["Trend"].values()) for v, out in expected.by_value(SPEC, CSV, "Period").items()}
        self.assertAlmostEqual(totals["L3M"], 41915.11, places=2)
        self.assertAlmostEqual(totals["All"], 170547.57, places=2)  # decisions/020: 170 548

    def test_every_metric(self):
        by = expected.by_value(SPEC, CSV, "Metric")
        self.assertEqual(sorted(by), ["Profit", "Quantity", "Sales"])
        self.assertEqual(by["Quantity"]["Trend"]["2025-12"], 336)
        self.assertAlmostEqual(by["Profit"]["Trend"]["2025-07"], 2332.14, places=2)
        with self.assertRaises(ValueError):
            expected.by_value(SPEC, CSV, "Nope")


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.out = built(SPEC, "interact_gate")

    def mutant(self, fn):
        root = copy.deepcopy(self.root)
        fn(root)
        tmp = Path(tempfile.mkdtemp()) / "m.twbx"
        with zipfile.ZipFile(self.out) as src, zipfile.ZipFile(tmp, "w") as z:
            for n in src.namelist():
                z.writestr(n, etree.tostring(root) if n.endswith(".twb") else src.read(n))
        return gate.run(tmp)

    def assertCaught(self, fn, text):
        issues = self.mutant(fn)
        self.assertTrue(any(text in str(i) for i in issues), [str(i) for i in issues])

    def action(self, root, caption):
        return next(a for a in root.iter("edit-parameter-action") if a.get("caption") == caption)

    def test_generated_passes(self):
        self.assertEqual(gate.run(self.out), [])

    def test_action_on_an_undeclared_parameter(self):
        def m(root):
            p = next(p for p in self.action(root, "Metrics · Sales").iter("param")
                     if p.get("name") == "target-parameter")
            p.set("value", "[Parameters].[Parameter 9]")
        self.assertCaught(m, "target parameter [Parameters].[Parameter 9] is not declared")

    def test_action_field_not_on_the_source_sheet(self):
        def m(root):  # the Sales button's action reads the Profit button's field
            src = next(p for p in self.action(root, "Metrics · Profit").iter("param") if p.get("name") == "source-field")
            dst = next(p for p in self.action(root, "Metrics · Sales").iter("param") if p.get("name") == "source-field")
            dst.set("value", src.get("value"))
        self.assertCaught(m, "is not on the marks of sheet 'Metrics · Sales'")

    def test_action_source_not_on_the_dashboard(self):
        self.assertCaught(lambda r: self.action(r, "Periods · L3M").find("source").set("worksheet", "Trend2"),
                          "source sheet 'Trend2' is not on dashboard")

    def test_button_value_not_in_the_list(self):
        def m(root):
            p = next(c for ds in root.find("datasources") if ds.get("name") == "Parameters" for c in ds
                     if c.get("caption") == "Period")
            p.find("members").remove(next(x for x in p.find("members") if x.get("value") == '"L9M"'))
        self.assertCaught(m, "to \"L9M\", which is not one of its values")

    def test_zone_shown_for_a_value_the_parameter_lacks(self):
        def m(root):
            p = next(c for ds in root.find("datasources") if ds.get("name") == "Parameters" for c in ds
                     if c.get("caption") == "View")
            p.find("members").remove(next(x for x in p.find("members") if x.get("value") == '"Table"'))
        self.assertCaught(m, "which is not one of its values")
        self.assertCaught(m, "the zone never shows")

    def test_zone_of_no_dashboard(self):
        self.assertCaught(lambda r: next(r.iter("dashboard-zone-visibility-node")).set("dashboard-identifier", "{X}"),
                          "is no dashboard's simple-id")
        self.assertCaught(lambda r: next(r.iter("dashboard-zone-visibility-node")).set("zone-id", "9999"),
                          "has no zone 9999")

    def test_hidden_by_user_disagrees_with_the_default(self):
        def m(root):
            for z in root.iter("zone"):
                z.attrib.pop("hidden-by-user", None)
        self.assertCaught(m, "hidden-by-user is unset but the field is false")

    def test_zone_without_a_driving_field(self):
        edges = "datagraph/graph/edges"
        self.assertCaught(lambda r: r.find(edges).remove(r.find(edges)[0]), "no field drives")

    def test_missing_manifest_flags(self):
        def m(root):
            man = root.find("document-format-change-manifest")
            for f in ("ParameterAction", "ZoneVisibilityControl"):
                man.remove(man.find(f))
        self.assertCaught(m, "without the ParameterAction flag")
        self.assertCaught(m, "without the ZoneVisibilityControl flag")

    def test_period_filter_member(self):
        def m(root):
            for g in root.iter("groupfilter"):
                if g.get("member") == "true":
                    g.set("member", "false")
        self.assertCaught(m, "a parameter switch keeps the rows where it is true")

    def test_period_filter_without_its_control(self):
        def m(root):  # no button sets Period any more: the filter hides data nobody can change
            acts = root.find("actions")
            for a in list(acts):
                if a.get("caption", "").startswith("Periods"):
                    acts.remove(a)
        self.assertCaught(m, "has no card on a dashboard")

    def test_unknown_card_mode(self):
        self.assertCaught(lambda r: next(z for z in r.iter("zone") if z.get("type-v2") == "paramctrl").set(
            "mode", "radio"), "parameter card mode 'radio'")

    def test_overlap_outside_a_switch_still_caught(self):
        def m(root):
            for n in list(root.iter("dashboard-zone-visibility-node")):
                n.getparent().remove(n)
        self.assertCaught(m, "overlap")


# ---- a switch of registries, in a book with several sources (decisions/082) ----------------------------------
REG = json.loads((SPECS / "switch_registry.json").read_text(encoding="utf-8"))


def reg_built(spec=REG, name="switch_registry_test"):
    out = build(spec, ROOT / "out" / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return etree.fromstring(z.read(out.stem + ".twb")), out


def titles(container, sheet_zone):
    """The column titles standing right on a registry's sheet zone inside container."""
    x, y, w = (int(sheet_zone.get(k)) for k in ("x", "y", "w"))
    return [t for t in container.iter("zone") if t.get("type-v2") == "text"
            and int(t.get("y")) + int(t.get("h")) == y and x <= int(t.get("x")) < x + w]


class SwitchRegistryChecks(unittest.TestCase):
    def assertRejected(self, fn, text):
        with self.assertRaises(ValueError) as cm:
            build(mutate(fn, REG), ROOT / "out" / "switch_registry_reject.twbx", SPECS)
        self.assertIn(text, str(cm.exception))

    def test_switch_takes_its_views_source(self):
        self.assertRejected(lambda s: sheet(s, "Plan").pop("datasource"),
                            "give the switch \"datasource\": \"plan\"")

    def test_views_of_one_source(self):
        def m(s):
            s["sheets"].append({"name": "Orders Bars", "type": "bar", "dimension": "Region",
                                "measure": {"field": "Sales"}})
            sheet(s, "Plan")["views"]["Chart"] = "Orders Bars"
        self.assertRejected(m, "a switch shows views of one datasource")

    def test_buttons_still_refused_with_several_sources(self):
        self.assertRejected(lambda s: (s["sheets"].append({"name": "Pick", "type": "buttons", "datasource": "plan",
                                                           "parameter": "Breakdown"}),
                                       s["dashboard"]["grid"].insert(0, ["Pick"])), "are not supported yet")


class SwitchRegistryXml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.out = reg_built()
        cls.db = cls.root.find("dashboards/dashboard")

    def test_registries_with_their_titles_in_their_containers(self):
        conts = views(self.db, "Plan ")
        self.assertEqual([z.get("hidden-by-user") for z in conts], [None, "true", "true"])
        self.assertEqual({z.get("type-v2") for z in conts}, {"layout-basic"})
        for c, name, cols in zip(conts, ("Plan by Manager", "Plan by Region"),
                                 (["Manager", "Sales", "Plan", "Attainment"], ["Region", "Sales", "Plan"])):
            s = next(z for z in c.iter("zone") if z.get("name") == name)
            got = ["".join(r.text for r in t.iter("run")) for t in titles(c, s)]
            self.assertEqual(got, cols)
        for c in conts[1:]:  # every zone of a hidden view hidden, as Desktop saves it
            self.assertEqual({z.get("hidden-by-user") for z in c.iter("zone")}, {"true"})

    def test_flags_in_the_views_source(self):
        plan = next(d.get("name") for d in self.root.find("datasources")
                    if d.find(".//connection[@filename]") is not None
                    and d.find(".//connection[@filename]").get("filename").endswith("sales_plan.csv"))
        fields = [f.get("fieldname") for f in self.root.iter("single-value-field-node")]
        self.assertEqual(len(fields), 3)
        self.assertTrue(all(f.startswith(f"[{plan}].") for f in fields), fields)
        edges = [e.get("from") for e in self.root.iterfind("datagraph/graph/edges/edge")]
        self.assertEqual(len(edges), 3)
        self.assertEqual(edges, sorted(edges))  # as Desktop saves them

    def test_variant_shows_the_second_registry(self):
        with tempfile.TemporaryDirectory() as d:
            out = variant(self.out, Path(d) / "v.twbx", {"Breakdown": "By region"})
            self.assertEqual(gate.run(out), [])
            with zipfile.ZipFile(out) as z:
                root = etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))
        conts = views(root, "Plan ")
        self.assertEqual([{z.get("hidden-by-user") for z in c.iter("zone")} for c in conts],
                         [{"true"}, {None}, {"true"}])

    def test_resave_matches_pairs_by_guid(self):
        """Desktop writes the subgraph pairs in an order of its own (golden_switch_registry_2025_1): resave and the
        round-trip match them by node-guid."""
        import xml.etree.ElementTree as ET
        from tbuilder import resave
        a = ET.fromstring(etree.tostring(self.root))
        b = ET.fromstring(etree.tostring(self.root))
        pairs = b.find("datagraph/graph/node-execution-subgraphs")
        pairs[:] = list(pairs)[::-1]
        self.assertEqual(resave.diff(a, b), [])

    def test_lint_clean(self):
        self.assertFalse([f for f in design_lint.lint(REG, SPECS) if f.level == "error"])




class SwitchRegistryGateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.out = reg_built(name="switch_registry_gate")

    mutant = GateCatches.mutant
    assertCaught = GateCatches.assertCaught

    def test_generated_passes(self):
        self.assertEqual(gate.run(self.out), [])

    def test_title_outside_the_container(self):
        def m(root):  # the hidden registry's first title moved up into the switch's row
            c = views(root, "Plan by Region")[0]
            t = titles(c, next(z for z in c.iter("zone") if z.get("name") == "Plan by Region"))[0]
            t.getparent().remove(t)
            c.getparent().getparent().append(t)
            t.attrib.pop("hidden-by-user")
        self.assertCaught(m, "column title 'Region' of registry 'Plan by Region' is outside its switch container")

    def test_zone_shown_in_a_hidden_container(self):
        def m(root):
            c = views(root, "Plan by Region")[0]
            next(z for z in c.iter("zone") if z.get("name") == "Plan by Region").attrib.pop("hidden-by-user")
        self.assertCaught(m, "hidden-by-user is unset inside switch container")

    def test_zone_hidden_in_a_shown_container(self):
        def m(root):
            c = views(root, "Plan by Manager")[0]
            titles(c, next(z for z in c.iter("zone") if z.get("name") == "Plan by Manager"))[1].set("hidden-by-user", "true")
        self.assertCaught(m, "hidden-by-user is true inside switch container")


if __name__ == "__main__":
    unittest.main()
