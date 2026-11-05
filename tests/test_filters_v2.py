"""Filters v2 (decisions/035): the selection at open (default), single-value dropdown, only relevant values, exclude,
context filters and Tableau's order of operations (context -> Top N / FIXED -> dimension filters); gate mutations."""
import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import expected, gate, reconcile
from tbuilder.build import build
from test_roundtrip import OUT, ROOT, SPECS

USER = "{http://www.tableausoftware.com/xml/user}"
CSV = ROOT / "data" / "sample" / "sales_stores.csv"


def load(name="filters_v2.json"):
    return json.loads((SPECS / name).read_text(encoding="utf-8"))


def built(spec, name):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return etree.fromstring(z.read(out.stem + ".twb")), out


def shared(root):
    return {f.get("column").split("].")[1]: f for f in next(root.iter("shared-view")).findall("filter")}


def card(root, inst):
    return next(z for z in root.iter("zone") if z.get("type-v2") == "filter" and z.get("param", "").endswith(inst))


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.path = built(load(), "filters_v2_xml")

    def test_gate_passes(self):
        self.assertEqual(gate.run(self.path, load()), [])

    def test_single_default_is_one_member(self):
        """Region: one member as Desktop writes a single selection (SuperMart, TableauReportsUsage)."""
        f = shared(self.root)["[none:Region:nk]"]
        (g,) = list(f)
        self.assertEqual(dict(g.attrib), {"function": "member", "level": "[none:Region:nk]", "member": '"North"',
                                          f"{USER}ui-domain": "database", f"{USER}ui-enumeration": "inclusive",
                                          f"{USER}ui-marker": "enumerate"})

    def test_context_attribute_after_column(self):
        f = shared(self.root)["[none:Region:nk]"]
        self.assertEqual(list(f.attrib), ["class", "column", "context"])
        self.assertEqual(f.get("context"), "true")
        self.assertIsNone(shared(self.root)["[none:Channel:nk]"].get("context"))

    def test_several_defaults_are_a_union(self):
        (g,) = list(shared(self.root)["[none:Channel:nk]"])
        self.assertEqual((g.get("function"), g.get(f"{USER}ui-enumeration")), ("union", "inclusive"))
        self.assertEqual([m.get("member") for m in g], ['"Online"', '"Retail"'])

    def test_no_default_stays_all(self):
        (g,) = list(shared(self.root)["[none:City:nk]"])
        self.assertEqual((g.get("function"), g.get(f"{USER}ui-enumeration")), ("level-members", "all"))

    def test_cards(self):
        self.assertEqual(card(self.root, "[none:Region:nk]").get("mode"), "dropdown")
        city = card(self.root, "[none:City:nk]")
        self.assertEqual((city.get("mode"), city.get("values")), ("checkdropdown", "relevant"))
        self.assertIsNone(card(self.root, "[none:Channel:nk]").get("values"))

    def test_exclude_is_except(self):
        spec = load()
        spec["filters"][2] = {"field": "Channel", "show_on": "Top Products", "default": ["Partner"], "exclude": True}
        root, path = built(spec, "filters_v2_exclude")
        (g,) = list(shared(root)["[none:Channel:nk]"])
        self.assertEqual((g.get("function"), g.get(f"{USER}ui-enumeration")), ("except", "exclusive"))
        self.assertEqual([(k.get("function"), k.get("member")) for k in g],
                         [("level-members", None), ("member", '"Partner"')])
        self.assertEqual(gate.run(path, spec), [])
        rows = expected.compute(spec, CSV)["By City"]
        self.assertEqual(rows, expected.compute(load(), CSV)["By City"])  # Online + Retail = all but Partner


class BuilderRefuses(unittest.TestCase):
    def refused(self, fn, text):
        spec = load()
        fn(spec)
        with self.assertRaises(ValueError) as e:
            build(spec, OUT / "filters_v2_bad.twbx", SPECS)
        self.assertIn(text, str(e.exception))

    def test_default_not_in_data(self):
        self.refused(lambda s: s["filters"][0].update(default=["Central"]), "is not in the data")

    def test_single_with_two_defaults(self):
        self.refused(lambda s: s["filters"][0].update(default=["North", "East"]), "selects one value")

    def test_default_of_every_value(self):
        self.refused(lambda s: s["filters"][2].update(default=["Online", "Partner", "Retail"]), "leave it out")

    def test_exclude_without_default(self):
        self.refused(lambda s: s["filters"][1].update(exclude=True), "exclude needs default")

    def test_default_on_a_date_filter(self):
        self.refused(lambda s: s["filters"].append({"field": "Order Date", "show_on": "KPI", "mode": "range",
                                                    "default": ["x"]}), "applies to a filter of values")

    def test_list_card_in_the_header(self):
        """single_list became a card (decisions/162), a line per value: the right panel only."""
        self.refused(lambda s: s["filters"][1].update(mode="single_list"), "needs a line per value")


class OrderOfOperations(unittest.TestCase):
    """Tableau: context filters -> Top N and FIXED -> dimension filters."""

    def test_top_n_within_the_context(self):
        got = expected.compute(load(), CSV)["Top Products"]
        spec = load()
        spec["filters"][0].pop("context")  # Region a dimension filter: Top N over all regions, then North
        flat = expected.compute(spec, CSV)["Top Products"]
        self.assertEqual(sorted(got), ["Cobalt", "Harbor", "Juniper", "Meridian", "Orbit"])
        self.assertNotEqual(sorted(got), sorted(flat))

    def test_top_n_ranks_before_the_dimension_filters(self):
        """Channel is not in the context: the top 5 of North are ranked over all channels, then Partner drops out."""
        spec = load()
        spec["filters"][2].pop("default")
        all_channels = expected.compute(spec, CSV)["Top Products"]
        self.assertEqual(sorted(all_channels), sorted(expected.compute(load(), CSV)["Top Products"]))
        self.assertTrue(all(all_channels[k] > v for k, v in expected.compute(load(), CSV)["Top Products"].items()))

    def test_fixed_after_the_context(self):
        """{FIXED : SUM(Sales)} = the total of North (the context), not of the data: share = Online+Retail / North."""
        import csv
        with CSV.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        north = sum(float(r["Sales"]) for r in rows if r["Region"] == "North")
        shown = sum(float(r["Sales"]) for r in rows if r["Region"] == "North" and r["Channel"] != "Partner")
        kpi = expected.compute(load(), CSV)["KPI"]
        self.assertAlmostEqual(kpi["SUM(Sales)"], shown, places=6)
        self.assertAlmostEqual(kpi["AGG(Share of region)"], shown / north, places=9)

    def test_where_replaces_the_default(self):
        """The workbook user's choice in a card (reconcile state) replaces the default of that card."""
        east = expected.compute(load(), CSV, where={"Region": {"East"}})["By City"]
        self.assertEqual(sorted(east), ["Albany", "Boston", "Newark"])


class Reconcile(unittest.TestCase):
    def test_state_must_match_the_default(self):
        with self.assertRaises(ValueError) as e:
            reconcile._check_state(load(), CSV, {"Region": ["East"]})
        self.assertIn("opens with default", str(e.exception))
        reconcile._check_state(load(), CSV, {"Region": ["North"]})  # the same selection: fine


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.path = built(load(), "filters_v2_gate")

    def mutant(self, fn):
        with zipfile.ZipFile(self.path) as src:
            members = {n: src.read(n) for n in src.namelist()}
        name = next(n for n in members if n.endswith(".twb"))
        root = etree.fromstring(members[name])
        fn(root, shared(root))
        members[name] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
        path = Path(tempfile.mkdtemp()) / "mutant.twbx"
        with zipfile.ZipFile(path, "w") as z:
            for n, b in members.items():
                z.writestr(n, b)
        return path

    def assertCaught(self, fn, text, spec=None):
        issues = [str(i) for i in gate.run(self.mutant(fn), spec) if i.check == "filters"]
        self.assertTrue(any(text in i for i in issues), f"expected [filters] ~ '{text}', got {issues}")

    def test_default_value_not_in_data(self):
        self.assertCaught(lambda r, f: f["[none:Region:nk]"][0].set("member", '"Central"'),
                          "values the data does not have")

    def test_single_card_with_two_values(self):
        def m(root, f):
            region = f["[none:Region:nk]"]
            g = region[0]
            region.remove(g)
            u = etree.SubElement(region, "groupfilter", {"function": "union", f"{USER}ui-domain": "database",
                                                         f"{USER}ui-enumeration": "inclusive",
                                                         f"{USER}ui-marker": "enumerate"})
            for v in ("North", "East"):
                etree.SubElement(u, "groupfilter", function="member", level="[none:Region:nk]", member=f'"{v}"')
        self.assertCaught(m, "single-value card (dropdown) shows one value, the filter selects 2")

    def test_context_without_card(self):
        def m(root, f):
            z = card(root, "[none:Region:nk]")
            z.getparent().remove(z)
        self.assertCaught(m, "context filter on [none:Region:nk] has no card")

    def test_default_lost(self):
        """The shared-view in (All) where the spec asks for Channel = Online, Retail: a valid file, the wrong state."""
        def m(root, f):
            ch = f["[none:Channel:nk]"]
            ch.remove(ch[0])
            etree.SubElement(ch, "groupfilter", {"function": "level-members", "level": "[none:Channel:nk]",
                                                 f"{USER}ui-enumeration": "all", f"{USER}ui-marker": "enumerate"})
        self.assertEqual([i for i in gate.run(self.mutant(m)) if i.check == "filters"], [])  # valid alone
        self.assertCaught(m, "the workbook opens with all [], the spec asks for in", load())

    def test_context_lost(self):
        self.assertCaught(lambda r, f: f["[none:Region:nk]"].attrib.pop("context"), "context is False", load())

    def test_exclude_without_its_level(self):
        def m(root, f):
            ch = f["[none:Channel:nk]"]
            ch.remove(ch[0])
            e = etree.SubElement(ch, "groupfilter", {"function": "except", f"{USER}ui-enumeration": "exclusive"})
            etree.SubElement(e, "groupfilter", function="member", level="[none:Channel:nk]", member='"Partner"')
        self.assertCaught(m, "except: expected level-members")


if __name__ == "__main__":
    unittest.main()
