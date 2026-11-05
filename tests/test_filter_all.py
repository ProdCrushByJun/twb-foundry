"""Shared dimension filters in the state "(All)" (decisions/021): no list of members, so values added to the data
after the build are not filtered out; gate mutations."""
import csv
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import gate
from tbuilder.build import build
from test_roundtrip import OUT, ROOT, SPECS

USER = "{http://www.tableausoftware.com/xml/user}"


def load(name):
    return json.loads((SPECS / name).read_text(encoding="utf-8"))


def built(spec, name, base=SPECS):
    out = build(spec, OUT / f"{name}.twbx", base)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb")), out


def shared_filters(root):
    return {f.get("column").split("].")[1]: f for f in root.find("shared-views/shared-view").findall("filter")}


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sidebar, _ = built(load("layout_sidebar.json"), "filter_all_sidebar")  # Category + Region
        cls.golden, _ = built(load("golden.json"), "filter_all_golden")  # Region + a KPI with Measure Names

    def test_all_state_as_desktop_writes_it(self):
        """One level-members groupfilter on the filter's own instance, ui-enumeration all, nothing inside."""
        filters = shared_filters(self.sidebar)
        self.assertEqual(list(filters), ["[none:Category:nk]", "[none:Region:nk]"])
        for inst, f in filters.items():
            with self.subTest(field=inst):
                self.assertEqual(f.get("class"), "categorical")
                (g,) = list(f)
                self.assertEqual(dict(g.attrib), {"function": "level-members", "level": inst,
                                                  f"{USER}ui-enumeration": "all", f"{USER}ui-marker": "enumerate"})
                self.assertEqual(len(g), 0)

    def test_no_members_listed(self):
        """A list of members is what cut off new values: none in the shared filters."""
        sv = self.golden.find("shared-views/shared-view")
        self.assertEqual([g for g in sv.iter("groupfilter") if g.get("function") == "member"], [])

    def test_measure_names_filter_unchanged(self):
        """The KPI's Measure Names filter keeps its manual list (the measures are fixed by the spec)."""
        kpi = next(w for w in self.golden.iter("worksheet") if w.get("name") == "KPI")
        g = kpi.find("table/view/filter/groupfilter")
        self.assertEqual((g.get("function"), g.get(f"{USER}op")), ("union", "manual"))
        self.assertEqual(len(g.findall("groupfilter[@function='member']")), 3)

    def test_filter_does_not_depend_on_the_values(self):
        """A CSV with one more region builds the same filter: nothing in it knows which values existed."""
        spec = load("golden.json")
        tmp = Path(tempfile.mkdtemp())
        src = ROOT / "data" / "sample" / "sales.csv"
        with src.open(encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        new = dict(zip(rows[0], rows[1]), Region="Central")
        with (tmp / "sales.csv").open("w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(rows + [[new[c] for c in rows[0]]])
        spec["datasource"]["path"] = "sales.csv"
        more, _ = built(spec, "filter_all_more_values", tmp)

        def canon(root):
            f = shared_filters(root)["[none:Region:nk]"]
            return ET.tostring(f).replace(root.find("datasources/datasource").get("name").encode(), b"DS")
        self.assertEqual(canon(more), canon(self.golden))


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.path = built(load("layout_sidebar.json"), "filter_all_gate")

    def mutant(self, fn):
        with zipfile.ZipFile(self.path) as src:
            members = {n: src.read(n) for n in src.namelist()}
        name = next(n for n in members if n.endswith(".twb"))
        root = etree.fromstring(members[name])
        sv = next(root.iter("shared-view"))
        fn(next(f for f in sv.findall("filter") if "[none:Region:nk]" in f.get("column")))
        members[name] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
        path = Path(tempfile.mkdtemp()) / "mutant.twbx"
        with zipfile.ZipFile(path, "w") as z:
            for n, b in members.items():
                z.writestr(n, b)
        return path

    def assertCaught(self, fn, text):
        issues = [str(i) for i in gate.run(self.mutant(fn)) if i.check == "filters"]
        self.assertTrue(any(text in i for i in issues), f"expected [filters] ~ '{text}', got {issues}")

    def test_generated_passes(self):
        self.assertEqual(gate.run(self.path), [])

    def test_listed_members(self):
        """The shape before decisions/021: every value at build time, enumerated."""
        def m(f):
            f.remove(f[0])
            g = etree.SubElement(f, "groupfilter", {"function": "union", f"{USER}ui-domain": "database",
                                                    f"{USER}ui-enumeration": "inclusive",
                                                    f"{USER}ui-marker": "enumerate"})
            for v in ("East", "North", "South", "West"):
                etree.SubElement(g, "groupfilter", function="member", level="[none:Region:nk]", member=f'"{v}"')
        self.assertCaught(m, "lists members: values added to the data later are filtered out")

    def test_level_of_another_field(self):
        self.assertCaught(lambda f: f[0].set("level", "[none:Category:nk]"), "is not the filter's own")

    def test_level_not_declared(self):
        def m(f):
            f.set("column", f.get("column").replace("[none:Region:nk]", "[none:Segment:nk]"))
            f[0].set("level", "[none:Segment:nk]")
        self.assertCaught(m, "is not the filter's own declared instance")

    def test_not_enumerated_as_all(self):
        self.assertCaught(lambda f: f[0].set(f"{USER}ui-enumeration", "inclusive"), "without user:ui-enumeration='all'")

    def test_not_level_members(self):
        self.assertCaught(lambda f: f[0].set("function", "union"), "expected one level-members groupfilter")


if __name__ == "__main__":
    unittest.main()
