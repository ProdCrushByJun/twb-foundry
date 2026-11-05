"""Desktop's own rewrites on Save As that the generator now writes itself (decisions/092): the geographic role of a
column by its name, fixed sizes of buttons, pictures and sheets in layout flows; gate mutations; the restack rule."""
import unittest
import xml.etree.ElementTree as ET
import zipfile
from types import SimpleNamespace as C

from tbuilder import gate, maps
from tbuilder import resave as rs
from tbuilder.build import build_file
from test_gate import repack
from test_roundtrip import OUT, SPECS


def root_of(twbx):
    with zipfile.ZipFile(twbx) as z:
        return ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb") and "/" not in n)))


class NameRole(unittest.TestCase):
    """The lab re-saves (out/092lab): which names Desktop 2025.1 gives a role, and which form."""

    def test_words_desktop_gives_a_role(self):
        for name, role in [("City", "[City].[Name]"), ("Ship City", "[City].[Name]"), ("city", "[City].[Name]"),
                           ("Customer City", "[City].[Name]"), ("State", "[State].[Name]"),
                           ("STATE", "[State].[Name]"), ("Province2", "[State].[Name]"),
                           ("State/Province", "[State].[Name]"), ("County", "[County].[Name]"),
                           ("Prefecture", "[County].[Name]"), ("Country", "[Country].[ISO3166_2]"),
                           ("Country/Region", "[Country].[ISO3166_2]"), ("Nation", "[Country].[ISO3166_2]")]:
            self.assertEqual(maps.name_role(C(name=name, datatype="string")), role, name)
        self.assertEqual(maps.name_role(C(name="lat", datatype="real")), "[Geographical].[Latitude]")
        self.assertEqual(maps.name_role(C(name="Longitude", datatype="real")), "[Geographical].[Longitude]")

    def test_no_role(self):
        for name in ("Region", "Airport", "Continent", "Town", "Municipality", "Velocity", "Statement", "Ethnicity",
                     "Countryside", "Donation", "Lat Long"):
            self.assertIsNone(maps.name_role(C(name=name, datatype="string")), name)
        for name in ("Platform", "Plate", "Salon", "Unit"):
            self.assertIsNone(maps.name_role(C(name=name, datatype="real")), name)
        # integers (Zip, Area Code): Desktop makes them ordinal with a format; not written, a string role blocks them
        self.assertIsNone(maps.name_role(C(name="Zip Code", datatype="integer")))


class Roles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = root_of(build_file(SPECS / "filters_v2.json", OUT / "092_filters_v2.twbx"))
        cls.maps = root_of(build_file(SPECS / "maps.json", OUT / "092_maps.twbx"))

    def test_city_has_its_role_in_the_datasource_and_the_sheet(self):
        ds = self.root.find("datasources/datasource")
        self.assertEqual(ds.find("column[@name='[City]']").get("semantic-role"), "[City].[Name]")
        dep = [c for c in self.root.iter("column") if c.get("name") == "[City]"]
        self.assertGreater(len(dep), 1)
        self.assertEqual({c.get("semantic-role") for c in dep}, {"[City].[Name]"})
        self.assertIsNone(ds.find("column[@name='[Region]']"))

    def test_a_map_role_stops_the_name_roles(self):
        """Desktop adds none once a column has a role (lab_b; golden_maps' City on the coordinates map)."""
        roles = {c.get("name"): c.get("semantic-role") for c in self.maps.iter("column") if c.get("name") == "[City]"}
        self.assertEqual(roles, {"[City]": None})


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.filters = build_file(SPECS / "filters_v2.json", OUT / "092_filters_v2_gate.twbx")
        cls.shell = build_file(SPECS / "shell.json", OUT / "092_shell_gate.twbx")
        cls.nav = build_file(SPECS / "nav_sidebar.json", OUT / "092_nav_sidebar_gate.twbx")

    def assertCaught(self, path, check, text):
        issues = gate.run(path)
        hits = [i for i in issues if i.check == check and text in str(i)]
        self.assertTrue(hits, f"expected [{check}] ~ '{text}', got: {[str(i) for i in issues]}")

    def test_generated_pass(self):
        for book in (self.filters, self.shell, self.nav):
            self.assertEqual(gate.run(book), [], book.name)

    def test_name_role_not_written(self):
        def m(r):
            for c in r.iter("column"):
                c.attrib.pop("semantic-role", None)
        self.assertCaught(repack(m, source=self.filters), "maps", "Desktop gives it [City].[Name]")

    def test_free_welcome_sheet(self):
        def m(r):
            z = next(z for z in r.iter("zone") if z.get("name") == "Welcome")
            del z.attrib["is-fixed"], z.attrib["fixed-size"]
        self.assertCaught(repack(m, source=self.shell), "layout", "free sheet in a horz flow")

    def test_welcome_fixed_size_with_its_margins(self):
        def m(r):
            next(z for z in r.iter("zone") if z.get("name") == "Welcome").set("fixed-size", "240")
        self.assertCaught(repack(m, source=self.shell), "layout", "fixed-size 240 px is not the zone")

    def test_free_logo(self):
        def m(r):
            z = next(z for z in r.iter("zone") if z.get("type-v2") == "bitmap")
            del z.attrib["is-fixed"]
        self.assertCaught(repack(m, source=self.shell), "layout", "free bitmap in a vert flow")

    def test_free_nav_button_in_the_sidebar(self):
        def m(r):
            z = next(z for z in r.iter("zone") if z.get("type-v2") == "dashboard-object")
            del z.attrib["is-fixed"]
        self.assertCaught(repack(m, source=self.nav), "layout", "free dashboard-object in a vert flow")


class Restack(unittest.TestCase):
    def _item(self, attr, kind="text", parent="vert", path="/zone[id=8][param=vert]/zone[id=9][type-v2=x]"):
        p = ET.Element("zone", {"type-v2": "layout-flow", "param": parent})
        el = ET.SubElement(p, "zone", {"type-v2": kind})
        return rs.Item(rs.CHANGED, path, el, attr, "1", "2", parent=p)

    def test_y_and_spacer_in_a_vertical_flow(self):
        self.assertTrue(rs._flow_restack(self._item("y", "dashboard-object")))
        self.assertTrue(rs._flow_restack(self._item("h", "empty")))
        # a button inside a row of the sidebar moves with the row
        self.assertTrue(rs._flow_restack(self._item("y", "dashboard-object", parent="horz")))

    def test_a_button_height_still_counts(self):
        self.assertFalse(rs._flow_restack(self._item("h", "dashboard-object")))
        self.assertFalse(rs._flow_restack(self._item("y", "dashboard-object", parent="horz", path="/zone[id=4]")))


if __name__ == "__main__":
    unittest.main()
