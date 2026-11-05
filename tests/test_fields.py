"""Field properties (decisions/033): aliases, manual order, groups with Other, default colors."""
import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import gate
from tbuilder.build import build_file
from tbuilder.design_lint import lint
from tbuilder.expected import compute
from tbuilder.spec import SpecError, load, validate
from test_roundtrip import OUT, ROOT

SPEC = ROOT / "specs" / "fields.json"
CSV = ROOT / "data" / "sample" / "sales_products.csv"


def spec_with(change):
    s = load(SPEC)
    s["datasource"]["path"] = CSV.as_posix()
    change(s)
    return s


def build(spec, name):
    path = Path(tempfile.mkdtemp()) / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return build_file(path, OUT / f"fields_{name}.twbx")


def twb(path):
    with zipfile.ZipFile(path) as z:
        return etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


class Expected(unittest.TestCase):
    """expected names and orders the marks as Tableau shows them."""

    @classmethod
    def setUpClass(cls):
        cls.got = compute(load(SPEC), CSV)

    def test_aliases_in_the_manual_order(self):
        self.assertEqual(list(self.got["Regions"]), ["North side", "East coast", "South belt", "West coast"])
        self.assertAlmostEqual(self.got["Regions"]["East coast"], 35210.92, 2)

    def test_group_with_other(self):
        lines = self.got["Lines"]
        self.assertEqual(list(lines), ["Growth", "Core", "Other"])
        self.assertAlmostEqual(sum(lines.values()), sum(self.got["Regions"].values()), 6)  # nothing lost
        self.assertAlmostEqual(lines["Growth"], 32597.19, 2)

    def test_table_in_both_orders(self):
        keys = list(self.got["Matrix"])
        self.assertEqual(keys[:4], ["North side | Growth", "North side | Core", "North side | Other",
                                    "East coast | Growth"])

    def test_running_total_follows_the_manual_order(self):
        """A table calc runs along the field in its sort order (Tableau), not the alphabet of the values."""
        s = load(SPEC)
        s["sheets"][0]["measure"]["table_calc"] = {"type": "running_total"}
        got = compute(s, CSV)["Regions"]
        self.assertAlmostEqual(got["North side"], 44518.47, 2)
        self.assertAlmostEqual(got["East coast"], 44518.47 + 35210.92, 2)

    def test_without_fields_nothing_changes(self):
        s = load(SPEC)
        s.pop("fields")
        s["sheets"] = [s["sheets"][0]]
        s["sheets"][0].pop("color")
        s["filters"] = []
        self.assertEqual(list(compute(s, CSV)["Regions"]), ["East", "North", "South", "West"])


class Xml(unittest.TestCase):
    """The forms of Desktop's own books (reference workbooks, decisions/033)."""

    @classmethod
    def setUpClass(cls):
        cls.root = twb(build_file(SPEC, OUT / "fields_xml.twbx"))
        cls.ds = next(d for d in cls.root.find("datasources") if d.get("name").startswith("federated."))

    def test_aliases_in_the_column(self):
        col = self.ds.find("column[@name='[Region]']")
        self.assertEqual([(a.get("key"), a.get("value")) for a in col.findall("aliases/alias")],
                         [('"East"', "East coast"), ('"North"', "North side"), ('"South"', "South belt"),
                          ('"West"', "West coast")])
        deps = [c for c in self.root.iter("column") if c.get("name") == "[Region]" and c.getparent().tag ==
                "datasource-dependencies"]
        self.assertTrue(deps and all(c.find("aliases") is not None for c in deps))  # each sheet that shows it

    def test_default_sort_after_date_options(self):
        tags = [c.tag for c in self.ds]
        self.assertEqual(tags[tags.index("date-options") + 1], "default-sorts")
        sorts = {m.get("column"): [b.text for b in m.iter("bucket")] for m in self.ds.iter("manual-sort")}
        self.assertEqual(sorts, {"[Product Line]": ['"Growth"', '"Core"', '"Other"'],
                                 "[none:Region:nk]": ['"North"', '"East"', '"South"', '"West"']})
        self.assertIsNotNone(self.ds.find("column-instance[@name='[none:Region:nk]']"))

    def test_group_is_a_categorical_bin_used_as_its_column(self):
        calc = self.ds.find("column[@name='[Product Line]']/calculation")
        self.assertEqual((calc.get("class"), calc.get("column"), calc.get("default")),
                         ("categorical-bin", "[Product]", '"Other"'))
        self.assertEqual([(b.get("value"), len(b)) for b in calc], [('"Core"', 4), ('"Growth"', 3)])
        lines = next(w for w in self.root.iter("worksheet") if w.get("name") == "Lines")
        self.assertTrue(lines.findtext("table/rows").endswith(".[Product Line]"))
        self.assertFalse([ci for ci in self.root.iter("column-instance") if ci.get("column") == "[Product Line]"])
        # the group's source is declared too: Desktop 2025.1 adds it on Save As (decisions/061)
        src = self.ds.find("column[@name='[Product]']")
        self.assertEqual((src.get("datatype"), src.get("role"), src.get("type")), ("string", "dimension", "nominal"))
        # Desktop orders columns by the bracketed name: [Product Line] before [Product] (' ' < ']'), here and per sheet
        for deps in [self.ds, *self.root.iter("datasource-dependencies")]:
            names = [c.get("name") for c in deps.findall("column")]
            if "[Product]" in names:
                self.assertLess(names.index("[Product Line]"), names.index("[Product]"))

    def test_default_colors(self):
        maps = {e.get("field"): {m.findtext("bucket"): m.get("to") for m in e}
                for e in self.ds.findall("style/style-rule/encoding")}
        self.assertEqual(maps["[Product Line]"], {'"Core"': "#4e79a7", '"Growth"': "#3ea8a6", '"Other"': "#d4d4d4"})
        self.assertEqual(maps["[none:Region:nk]"]['"North"'], "#1f3a5f")

    def test_gate_passes(self):
        self.assertEqual(gate.run(OUT / "fields_xml.twbx"), [])


class SpecErrors(unittest.TestCase):
    """A property that does not fit the data stops the build with the reason."""

    def assertFails(self, change, text):
        with self.assertRaises((ValueError, SpecError)) as e:
            build(spec_with(change), "bad")
        self.assertIn(text, str(e.exception))

    def test_alias_of_a_value_not_in_the_data(self):
        self.assertFails(lambda s: s["fields"]["Region"]["aliases"].update(Central="Middle"),
                         "aliases names ['Central']")

    def test_two_values_one_label(self):
        self.assertFails(lambda s: s["fields"]["Region"]["aliases"].update(West="East coast"),
                         "show ['East coast'] for more than one value")

    def test_order_without_some_values(self):
        self.assertFails(lambda s: s["fields"]["Region"].update(order=["North", "East"]), "order leaves out")

    def test_order_twice_is_a_schema_error(self):
        with self.assertRaises(SpecError):
            validate(spec_with(lambda s: s["fields"]["Region"].update(order=["North", "North"])))

    def test_color_of_some_values(self):
        self.assertFails(lambda s: s["fields"]["Region"].update(color={"North": "#000000"}), "color leaves out")

    def test_member_in_two_bins(self):
        self.assertFails(lambda s: s["fields"]["Product Line"]["group"]["bins"]["Growth"].append("Atlas"),
                         "'Atlas' is in bins 'Core' and 'Growth'")

    def test_bin_of_unknown_member(self):
        self.assertFails(lambda s: s["fields"]["Product Line"]["group"]["bins"]["Growth"].append("Zeppelin"),
                         "names ['Zeppelin']")

    def test_bin_named_like_a_member_left_out(self):
        def change(s):
            g = s["fields"]["Product Line"]
            g["group"].pop("other")
            g["group"]["bins"]["Iris"] = g["group"]["bins"].pop("Growth")
            g.pop("order"), g.pop("color")
        self.assertFails(change, "bin names ['Iris'] are also members left out")

    def test_group_named_like_a_column(self):
        def change(s):
            s["fields"]["Product"] = s["fields"].pop("Product Line")
            for sh in s["sheets"]:
                for k in ("dimension", "color", "cols"):
                    if sh.get(k) == "Product Line":
                        sh[k] = "Product"
        self.assertFails(change, "already a column")

    def test_numeric_field(self):
        self.assertFails(lambda s: s["fields"].update(Quantity={"order": ["1", "2"]}), "is integer")


def mutant(path, fn):
    with zipfile.ZipFile(path) as src:
        members = {n: src.read(n) for n in src.namelist()}
    name = next(n for n in members if n.endswith(".twb"))
    root = etree.fromstring(members[name])
    fn(next(d for d in root.find("datasources") if d.get("name").startswith("federated.")))
    members[name] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
    out = Path(tempfile.mkdtemp()) / "mutant.twbx"
    with zipfile.ZipFile(out, "w") as z:
        for n, b in members.items():
            z.writestr(n, b)
    return out


class GateCatchesFields(unittest.TestCase):
    """The gate checks the properties against the packaged data, independently of the builder."""

    @classmethod
    def setUpClass(cls):
        cls.path = build_file(SPEC, OUT / "fields_gate.twbx")

    def assertCaught(self, fn, text):
        issues = [str(i) for i in gate.run(mutant(self.path, fn)) if i.check == "fields"]
        self.assertTrue(any(text in i for i in issues), f"expected [fields] ~ '{text}', got {issues}")

    def test_alias_of_a_missing_value(self):
        self.assertCaught(lambda ds: ds.find("column[@name='[Region]']/aliases/alias").set("key", '"Central"'),
                          "a value the data does not have")

    def test_alias_label_twice(self):
        self.assertCaught(lambda ds: ds.find("column[@name='[Region]']/aliases/alias").set("value", "North side"),
                          "labels ['North side'] show more than one value")

    def test_order_without_a_value(self):
        def drop(ds):
            d = ds.find("default-sorts/manual-sort[@column='[none:Region:nk]']/dictionary")
            d.remove(d[-1])
        self.assertCaught(drop, "leaves out ['West']")

    def test_group_order_without_other(self):
        def drop(ds):
            d = ds.find("default-sorts/manual-sort[@column='[Product Line]']/dictionary")
            d.remove(d[-1])
        self.assertCaught(drop, "leaves out ['Other']")

    def test_member_in_two_bins(self):
        def overlap(ds):
            bins = ds.findall("column[@name='[Product Line]']/calculation/bin")
            etree.SubElement(bins[1], "value").text = '"Atlas"'
        self.assertCaught(overlap, 'member "Atlas" is in bins')

    def test_bin_of_a_missing_member(self):
        self.assertCaught(lambda ds: ds.find("column[@name='[Product Line]']/calculation/bin/value")
                          .__setattr__("text", '"Zeppelin"'), "a value the data does not have")

    def test_group_through_an_instance(self):
        """The first build's form: Desktop 2025.1 opened it with 'Warnings occurred while loading' (check-desktop)."""
        self.assertCaught(lambda ds: etree.SubElement(ds, "column-instance", column="[Product Line]",
                                                      derivation="None", name="[none:Product Line:nk]",
                                                      pivot="key", type="nominal"),
                          "not through an instance")

    def test_sort_of_an_undeclared_instance(self):
        self.assertCaught(lambda ds: ds.find("default-sorts/manual-sort").set("column", "[none:Nowhere:nk]"),
                          "not a column-instance")


SPEC2 = ROOT / "specs" / "fields_v2.json"


def spec2_with(change):
    s = load(SPEC2)
    s["datasource"]["path"] = CSV.as_posix()
    change(s)
    return s


class V2(unittest.TestCase):
    """decisions/151: a calc dimension with properties, groups over a calc and over a number, a filter by group."""

    @classmethod
    def setUpClass(cls):
        cls.got = compute(load(SPEC2), CSV)
        cls.path = build_file(SPEC2, OUT / "fields_v2_xml.twbx")
        cls.root = twb(cls.path)

    def assertFails(self, change, text):
        with self.assertRaises((ValueError, SpecError)) as e:
            build(spec2_with(change), "bad2")
        self.assertIn(text, str(e.exception))

    def test_calc_aliases_and_order_in_expected(self):
        self.assertEqual(list(self.got["Sizes"]), ["Large order", "Medium order", "Small order"])

    def test_groups_are_labelled_by_their_bins(self):
        self.assertEqual(list(self.got["Tiers"]), ["Top orders", "The rest"])
        self.assertEqual(list(self.got["Bands"]), ["1-4 units", "5-8 units", "9+ units"])
        self.assertAlmostEqual(sum(self.got["Tiers"].values()), sum(self.got["Sizes"].values()), 6)
        self.assertAlmostEqual(sum(self.got["Bands"].values()), sum(self.got["Sizes"].values()), 6)

    def test_group_over_a_number_has_unquoted_members(self):
        c = self.root.find(".//column[@name='[Qty Band]']/calculation")
        self.assertEqual(c.get("column"), "[Quantity]")
        self.assertEqual([v.text for v in c.find("bin[@value='\"5-8 units\"']")], ["5", "6", "7", "8"])

    def test_bins_are_alphabetical_like_desktop(self):
        bins = [b.get("value") for b in self.root.find(".//column[@name='[Size Tier]']/calculation")]
        self.assertEqual(bins, sorted(bins))

    def test_group_over_a_calc_points_at_the_calc(self):
        c = self.root.find(".//column[@name='[Size Tier]']/calculation")
        self.assertTrue(c.get("column").startswith("[Calculation_"))

    def test_calc_keeps_its_aliases(self):
        col = self.root.find(".//datasource/column[@caption='Order Size']")
        self.assertEqual([a.get("value") for a in col.findall("aliases/alias")],
                         ["Large order", "Medium order", "Small order"])

    def test_group_has_no_aliases_element(self):
        self.assertIsNone(self.root.find(".//column[@name='[Size Tier]']/aliases"))

    def test_filter_by_group_uses_the_bare_column(self):
        f = self.root.find("shared-views/shared-view/filter")
        self.assertTrue(f.get("column").endswith("].[Size Tier]"))

    def test_gate_passes(self):
        self.assertEqual(gate.run(self.path), [])

    def test_group_aliases_are_refused(self):
        self.assertFails(lambda s: s["fields"]["Size Tier"].update(aliases={"Top orders": "Big"}),
                         "renamed through its bin names")

    def test_group_over_a_real_is_refused(self):
        self.assertFails(lambda s: s["fields"]["Qty Band"]["group"].update(field="Sales"),
                         "must be a text or integer column")

    def test_group_over_a_number_checks_its_members(self):
        self.assertFails(lambda s: s["fields"]["Qty Band"]["group"]["bins"]["9+ units"].append(99), "names ['99']")

    def test_calc_alias_of_a_missing_value(self):
        self.assertFails(lambda s: s["fields"]["Order Size"]["aliases"].update(Huge="Giant"), "aliases names ['Huge']")

    def test_calc_order_must_list_every_value(self):
        self.assertFails(lambda s: s["fields"]["Order Size"].update(order=["Large", "Small"]),
                         "order leaves out ['Medium']")


class GateCatchesFieldsV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build_file(SPEC2, OUT / "fields_v2_gate.twbx")

    def assertCaught(self, fn, text):
        issues = [str(i) for i in gate.run(mutant(self.path, fn)) if i.check == "fields"]
        self.assertTrue(any(text in i for i in issues), f"expected [fields] ~ '{text}', got {issues}")

    def test_number_quoted_in_a_numeric_group(self):
        self.assertCaught(lambda ds: ds.find("column[@name='[Qty Band]']/calculation/bin/value")
                          .__setattr__("text", '"1"'), "unquoted integers")

    def test_member_of_a_missing_number(self):
        self.assertCaught(lambda ds: ds.find("column[@name='[Qty Band]']/calculation/bin/value")
                          .__setattr__("text", "99"), "a value the data does not have")

    def test_aliases_on_a_group(self):
        def add(ds):
            col = ds.find("column[@name='[Size Tier]']")
            etree.SubElement(etree.SubElement(col, "aliases"), "alias", key='"The rest"', value="Others")
        self.assertCaught(add, "aliases on a group")



class SortFlag(unittest.TestCase):
    """<default-sorts><manual-sort> also needs SortTagCleanup: with `order` and no sorted bar Desktop 2025.1 did not
    open the book ("no declaration found for element 'manual-sort'", decisions/056)."""

    def test_order_without_a_sorted_sheet_sets_the_flag(self):
        def unsort(s):
            for sh in s["sheets"]:
                sh.pop("sort", None)
        root = twb(build(spec_with(unsort), "order_unsorted"))
        self.assertIsNotNone(root.find("document-format-change-manifest/SortTagCleanup"))

    def test_gate_catches_default_sorts_without_the_flag(self):
        root = twb(build_file(SPEC, OUT / "fields_flag.twbx"))
        root.find("document-format-change-manifest").remove(root.find("document-format-change-manifest/SortTagCleanup"))
        issues = [str(i) for i in gate.check_sort_flags(root)]
        self.assertTrue(any("default-sorts" in i for i in issues), issues)


class Lint(unittest.TestCase):
    def findings(self, spec, csv):
        d = Path(tempfile.mkdtemp())
        (d / "data.csv").write_text(csv, encoding="utf-8")
        spec = copy.deepcopy(spec)
        spec["datasource"]["path"] = "data.csv"
        return [(f.rule, f.text) for f in lint(spec, d)]

    BAR = {"version": 1, "datasource": {"type": "csv", "path": "data.csv"},
           "sheets": [{"name": "Bar", "type": "bar", "title": "Sales **by day**", "dimension": "Day",
                       "measure": {"field": "Sales"}}],
           "dashboard": {"name": "D", "title": "**Sales**", "subtitle": "x", "width": 1200, "height": 800,
                         "grid": [["Bar"]]}}

    def test_weekdays_out_of_calendar_order(self):
        csv = "Day,Sales\nMon,1\nTue,2\nWed,3\nFri,4\n"
        found = self.findings(self.BAR, csv)
        self.assertTrue(any(r == "I3" and "fields.Day.order" in t for r, t in found), found)
        ordered = copy.deepcopy(self.BAR)
        ordered["fields"] = {"Day": {"order": ["Mon", "Tue", "Wed", "Fri"]}}
        self.assertFalse([f for f in self.findings(ordered, csv) if f[0] == "I3"])

    def test_numbered_days_are_in_order(self):
        self.assertFalse([f for f in self.findings(self.BAR, "Day,Sales\n19 Mon,1\n20 Tue,2\n25 Sun,3\n")
                          if f[0] == "I3"])

    def test_big_palette_suggests_a_group(self):
        csv = "Day,Kind,Sales\n" + "".join(f"Mon,K{i},1\n" for i in range(8))
        spec = copy.deepcopy(self.BAR)
        spec["sheets"][0].update(color="Kind", sort="desc")
        found = [t for r, t in self.findings(spec, csv) if r == "C2"]
        self.assertTrue(found and "group" in found[0], found)
        spec["fields"] = {"Kind Group": {"group": {"field": "Kind", "bins": {"Top": ["K0", "K1"]}, "other": "Other"}}}
        spec["sheets"][0]["color"] = "Kind Group"
        self.assertFalse([f for f in self.findings(spec, csv) if f[0] == "C2"])


if __name__ == "__main__":
    unittest.main()
