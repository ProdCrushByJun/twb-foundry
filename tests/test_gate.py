"""Gate mutation tests: break the golden workbook one way at a time; the gate must name the break."""
import tempfile
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import gate
from test_roundtrip import OUT, ROOT

GOLDEN_TWBX = ROOT / "golden" / "golden_2025_1.twbx"
TWB = "Book1.twb"


def repack(mutate_xml=None, drop=None, raw=None, source=GOLDEN_TWBX, replace=None):
    """Copy golden .twbx (or source) with an XML mutation / dropped / replaced members; return path."""
    with zipfile.ZipFile(source) as src:
        members = {n: src.read(n) for n in src.namelist()}
    twb = next(n for n in members if n.endswith(".twb"))
    if mutate_xml:
        root = etree.fromstring(members[twb])
        mutate_xml(root)
        members[twb] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
    if raw is not None:
        members[twb] = raw
    if drop:
        members.pop(drop)
    members.update(replace or {})
    path = Path(tempfile.mkdtemp()) / "mutant.twbx"
    with zipfile.ZipFile(path, "w") as z:
        for n, b in members.items():
            z.writestr(n, b)
    return path


def ws(root, name):
    return next(w for w in root.iter("worksheet") if w.get("name") == name)


def zone(root, name):
    return next(z for z in root.iter("zone") if z.get("name") == name and "type-v2" not in z.attrib)


class GatePasses(unittest.TestCase):
    def test_golden(self):
        self.assertEqual(gate.run(GOLDEN_TWBX), [])

    def test_generated_specs(self):
        from tbuilder.build import build_file
        # gate_spec_ prefix of its own: other modules write gate_<name>
        for spec in sorted((ROOT / "specs").glob("*.json")):
            with self.subTest(spec=spec.name):
                self.assertEqual(gate.run(build_file(spec, OUT / f"gate_spec_{spec.stem}.twbx")), [])


class GateCatches(unittest.TestCase):
    def assertCaught(self, path, check, text):
        issues = gate.run(path)
        hits = [i for i in issues if i.check == check and text in str(i)]
        self.assertTrue(hits, f"expected [{check}] ~ '{text}', got: {[str(i) for i in issues]}")

    def test_ghost_window(self):
        def m(r):
            etree.SubElement(r.find("windows"), "window", {"class": "worksheet", "name": "Sheet 9"})
        self.assertCaught(repack(m), "windows", "ghost tab")

    def test_missing_window(self):
        def m(r):
            w = next(w for w in r.find("windows") if w.get("name") == "Line")
            r.find("windows").remove(w)
        self.assertCaught(repack(m), "windows", "has no window")

    def test_dangling_shelf_reference(self):
        def m(r):
            rows = ws(r, "Bar").find("table/rows")
            rows.text = rows.text.replace("[none:Region:nk]", "[none:Country:nk]")
        self.assertCaught(repack(m), "refs", "[none:Country:nk]")

    def test_dependency_on_missing_column(self):
        def m(r):
            dep = ws(r, "Bar").find("table/view/datasource-dependencies")
            etree.SubElement(dep, "column", datatype="real", name="[Margin]", role="measure", type="quantitative")
        self.assertCaught(repack(m), "refs", "column [Margin] not in datasource")

    def test_instance_of_undeclared_column(self):
        def m(r):
            dep = ws(r, "Line").find("table/view/datasource-dependencies")
            etree.SubElement(dep, "column-instance", column="[Profit]", derivation="Sum",
                             name="[sum:Profit:qk]", pivot="key", type="quantitative")
        self.assertCaught(repack(m), "refs", "undeclared column [Profit]")

    def test_zone_unknown_sheet(self):
        self.assertCaught(repack(lambda r: zone(r, "Line").set("name", "Lines")), "layout", "unknown worksheet 'Lines'")

    def test_overlapping_zones(self):
        self.assertCaught(repack(lambda r: zone(r, "Bar").set("x", "800")), "layout", "overlap")

    def test_zone_outside_parent(self):
        self.assertCaught(repack(lambda r: zone(r, "Table").set("w", "90000")), "layout", "outside parent")

    def test_legend_bound_to_wrong_field(self):
        def m(r):
            z = next(z for z in r.iter("zone") if z.get("type-v2") == "color")
            z.set("param", z.get("param").replace("[none:Category:nk]", "[none:Segment:nk]"))
        self.assertCaught(repack(m), "refs", "[none:Segment:nk]")

    def test_duplicate_uuid(self):
        def m(r):
            ids = list(r.iter("simple-id"))
            ids[1].set("uuid", ids[0].get("uuid"))
        self.assertCaught(repack(m), "ids", "duplicate simple-id")

    def test_empty_worksheet(self):
        def m(r):
            t = ws(r, "Line").find("table")
            t.find("rows").text = None
            t.find("cols").text = None
        self.assertCaught(repack(m), "content", "empty worksheet")

    def test_xsd_violation(self):
        self.assertCaught(repack(lambda r: etree.SubElement(ws(r, "Bar"), "bogus")), "xsd", "bogus")

    def test_missing_data_file(self):
        self.assertCaught(repack(drop="Data/sample/sales.csv"), "package", "missing from package")

    def test_broken_xml(self):
        self.assertCaught(repack(raw=b"<workbook><worksheets>"), "xml", "")

    def test_truncated_zip(self):
        """First half of the golden .twbx (decisions/022, mutant corrupt_zip): an Issue, not BadZipFile."""
        path = Path(tempfile.mkdtemp()) / "truncated.twbx"
        data = GOLDEN_TWBX.read_bytes()
        path.write_bytes(data[: len(data) // 2])
        self.assertCaught(path, "package", "not a zip archive")


def margin(z, side=None):
    """The zone's margin format (margin-<side> when side is given), created if missing."""
    attr = f"margin-{side}" if side else "margin"
    st = z.find("zone-style")
    f = st.find(f"format[@attr='{attr}']")
    return f if f is not None else etree.SubElement(st, "format", attr=attr, value="4")


class GateCatchesSpacing(unittest.TestCase):
    """Todo 3.7: every dashboard object keeps a design.SPACE margin; zero only for registry column titles and under
    a block header."""

    @classmethod
    def setUpClass(cls):
        from tbuilder.build import build_file
        cls.registry = build_file(ROOT / "specs" / "registry.json", OUT / "gate_spacing_registry.twbx")

    def assertCaught(self, path, text):
        hits = [i for i in gate.run(path) if i.check == "spacing" and text in str(i)]
        self.assertTrue(hits, f"expected [spacing] ~ '{text}', got: {[str(i) for i in gate.run(path)]}")

    def test_zone_without_margin(self):
        def m(r):
            z = zone(r, "Bar")
            z.find("zone-style").remove(margin(z))
        self.assertCaught(repack(m), "no margin on the top")

    def test_zero_margin_on_a_sheet(self):
        self.assertCaught(repack(lambda r: margin(zone(r, "Line")).set("value", "0")), "touches its neighbour")

    def test_margin_off_the_scale(self):
        self.assertCaught(repack(lambda r: margin(zone(r, "Table"), "left").set("value", "5")),
                          "margin-left 5 is not a design.SPACE token")

    def test_dashboard_edge_without_margin(self):
        def m(r):
            top = r.find("dashboards/dashboard/zones/zone")
            top.find("zone-style").remove(margin(top))
        self.assertCaught(repack(m), "root zone margin")

    def test_registry_column_titles_may_touch_their_sheet(self):
        self.assertEqual([i for i in gate.run(self.registry) if i.check == "spacing"], [])

    def test_text_zone_off_a_sheet_needs_a_margin(self):
        """A zero-margin text zone that is not right on top of a sheet is not a column title."""
        def m(r):
            title = next(z for z in r.iter("zone") if z.get("type-v2") == "text"
                         and margin(z).get("value") == "0")
            title.set("y", str(int(title.get("y")) - 100))
        self.assertCaught(repack(m, source=self.registry), "zero only")

    def test_sheet_top_zero_only_under_a_header(self):
        def m(r):
            for t in [z for z in r.iter("zone") if z.get("type-v2") == "text" and margin(z).get("value") == "0"]:
                t.getparent().remove(t)  # the column titles go: nothing sits on top of the sheet any more
        self.assertCaught(repack(m, source=self.registry), "margin-top 0")


class GateBlocksBuilderBugs(unittest.TestCase):
    def test_buggy_builder_writes_nothing(self):
        from unittest import mock
        import xml.etree.ElementTree as ET
        from tbuilder import build as build_mod

        original = build_mod.Builder.windows

        def ghost(self, parent):
            original(self, parent)
            ET.SubElement(parent.find("windows"), "window", {"class": "worksheet", "name": "Sheet 1"})

        out = OUT / "buggy.twbx"
        out.unlink(missing_ok=True)
        with mock.patch.object(build_mod.Builder, "windows", ghost):
            with self.assertRaisesRegex(gate.GateError, "ghost tab"):
                build_mod.build_file(ROOT / "specs" / "golden.json", out)
        self.assertFalse(out.exists())
        self.assertEqual(list(OUT.glob("buggy*")), [])


if __name__ == "__main__":
    unittest.main()
