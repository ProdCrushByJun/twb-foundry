"""Maps (decisions/046): symbol and filled maps on built-in geocoding; round-trip, expected, reconcile, refusals,
geocoding names, lint, gate mutations."""
import csv
import json
import unittest
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict

from tbuilder import actions, expected, gate, maps, reconcile
from tbuilder.build import build, build_file
from tbuilder.design_lint import lint
from test_gate import repack, ws
from test_roundtrip import OUT, ROOT, canon, normalize, read_twbx

SPEC = ROOT / "specs" / "maps.json"
CSV = ROOT / "data" / "sample" / "sales_geo.csv"
GOLDEN = ROOT / "golden" / "golden_maps_2025_1.twb"
ROWS = list(csv.DictReader(CSV.open(encoding="utf-8")))


def spec():
    return json.loads(SPEC.read_text(encoding="utf-8"))


def sheet(s, name):
    return next(x for x in s["sheets"] if x["name"] == name)


def twb(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


def total(field, by):
    out = defaultdict(float)
    for r in ROWS:
        out[r[by]] += float(r[field])
    return out


def with_csv(s, rows, name):
    """The spec on a copy of the sample CSV with rows changed by fn."""
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(ROWS[0]))
        w.writeheader()
        w.writerows(rows)
    s["datasource"]["path"] = str(path)
    return s


class RoundTrip(unittest.TestCase):
    def test_golden_rebuilds_identically(self):
        """Symbol map by US state, filled map by country: re-saved by Desktop 2025.1 (Save As from a fresh open)."""
        out = build_file(SPEC, OUT / "roundtrip_maps.twbx")
        got, names = read_twbx(out)
        self.assertIn("Data/sample/sales_geo.csv", names)
        self.assertEqual(canon(normalize(ET.parse(GOLDEN).getroot())), canon(normalize(got)))


class Workbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = twb(build_file(SPEC, OUT / "maps.twbx"))

    def test_roles_on_the_columns(self):
        ds = self.root.find("datasources/datasource")
        roles = {c.get("name"): c.get("semantic-role") for c in ds.findall("column") if c.get("semantic-role")}
        self.assertEqual(roles, {"[State]": "[State].[Name]", "[Ship Country]": "[Country].[Name]",
                                 "[Latitude]": "[Geographical].[Latitude]",
                                 "[Longitude]": "[Geographical].[Longitude]"})
        self.assertEqual(ds.find("semantic-values/semantic-value").get("value"), '"United States"')
        self.assertEqual(list(ds.find("column[@name='[State]']").attrib),
                         ["datatype", "name", "role", "semantic-role", "type"])

    def test_symbol_map(self):
        w = ws(self.root, "States")
        self.assertTrue(w.findtext("table/rows").endswith("[Latitude (generated)]"))
        self.assertTrue(w.findtext("table/cols").endswith("[Longitude (generated)]"))
        pane = w.find("table/panes/pane")
        self.assertEqual(pane.find("mark").get("class"), "Circle")
        self.assertEqual([e.tag for e in pane.find("encodings")], ["size", "text", "lod"])
        self.assertEqual(w.find("table/view/mapsources/mapsource").get("name"), "Tableau")

    def test_filled_map(self):
        pane = ws(self.root, "Countries").find("table/panes/pane")
        self.assertEqual(pane.find("mark").get("class"), "Multipolygon")
        self.assertEqual([e.tag for e in pane.find("encodings")], ["color", "text", "lod", "geometry"])
        pal = [c.text for c in ws(self.root, "Countries").iter("color") if c.text]
        self.assertEqual(pal, maps.filled_palette())
        self.assertNotEqual(pal[0], "#f1f1f1")  # the land of the Light map

    def test_map_on_the_data_coordinates(self):
        w = ws(self.root, "Cities")
        self.assertTrue(w.findtext("table/rows").endswith("[avg:Latitude:qk]"))
        self.assertTrue(w.findtext("table/cols").endswith("[avg:Longitude:qk]"))
        roles = {c.get("name"): c.get("semantic-role") for c in w.iter("column") if c.get("semantic-role")}
        self.assertEqual(roles, {"[Latitude]": "[Geographical].[Latitude]",
                                 "[Longitude]": "[Geographical].[Longitude]"})
        self.assertEqual([e.tag for e in w.find("table/panes/pane/encodings")], ["size", "text", "lod"])

    def test_workbook_map_source_and_flag(self):
        self.assertEqual([m.get("name") for m in self.root.findall("mapsources/mapsource")], ["Tableau"])
        self.assertIsNotNone(self.root.find("document-format-change-manifest/MapboxVectorStylesAndLayers"))

    def test_no_labels(self):
        s = spec()
        sheet(s, "States")["labels"] = False
        root = twb(build(s, OUT / "maps_nolabels.twbx", SPEC.parent))
        pane = ws(root, "States").find("table/panes/pane")
        self.assertEqual([e.tag for e in pane.find("encodings")], ["size", "lod"])


class Expected(unittest.TestCase):
    def test_values_by_place_as_a_bar(self):
        exp = expected.compute(spec(), CSV)
        for name, measure, field in (("States", "Sales", "State"), ("Countries", "Sales", "Ship Country"),
                                     ("Cities", "Profit", "City")):
            want = total(measure, field)
            self.assertEqual(set(exp[name]), set(want))
            for k, v in exp[name].items():
                self.assertAlmostEqual(v, want[k], 2)

    def test_reconcile_entries(self):
        exp = expected.compute(spec(), CSV)
        ents = [e for e in reconcile.entries(spec(), exp) if e["sheet"] == "States"]
        self.assertEqual(len(ents), len(total("Sales", "State")))

    def test_a_click_on_a_place_filters(self):
        self.assertEqual(actions.dims(sheet(spec(), "States")), ["State"])
        self.assertIn("map", actions.SOURCE_TYPES)


class Names(unittest.TestCase):
    def test_synonyms_and_case(self):
        self.assertEqual(maps.unknown("country", ["UK", "usa", "Germany", "Narnia"]), ["Narnia"])
        self.assertEqual(maps.unknown("state", ["California", "CA", "texas", "Bavaria"], "United States"),
                         ["Bavaria"])
        self.assertEqual(maps.unknown("state", ["Bavaria"], "Germany"), [])

    def test_city_not_verifiable(self):
        self.assertIsNone(maps.unknown("city", ["Springfield"], "United States"))

    def test_country_code(self):
        self.assertEqual(maps.country_code("United Kingdom"), "GBR")
        self.assertIsNone(maps.country_code("Narnia"))


class Refusals(unittest.TestCase):
    def build(self, s):
        return build(s, OUT / "maps_bad.twbx", SPEC.parent)

    def test_filled_map_by_city(self):
        s = spec()
        sheet(s, "States").update(style="filled", geo={"field": "City", "role": "city", "country": "United States"})
        with self.assertRaisesRegex(ValueError, "no city polygons"):
            self.build(s)

    def test_state_without_country(self):
        s = spec()
        del sheet(s, "States")["geo"]["country"]
        with self.assertRaisesRegex(ValueError, "needs geo.country"):
            self.build(s)

    def test_unknown_country_context(self):
        s = spec()
        sheet(s, "States")["geo"]["country"] = "Narnia"
        with self.assertRaisesRegex(ValueError, "does not know the country 'Narnia'"):
            self.build(s)

    def test_numeric_geo_field(self):
        s = spec()
        sheet(s, "States")["geo"] = {"field": "Sales", "role": "country"}
        with self.assertRaisesRegex(ValueError, "is real; a country is a text field"):
            self.build(s)

    def test_unknown_values_listed_with_a_hint(self):
        rows = [dict(r) for r in ROWS]
        rows[0]["Ship Country"] = "Untied Kingdom"
        s = with_csv(spec(), rows, "maps_typo/sales_geo.csv")
        with self.assertRaisesRegex(ValueError, r"'Untied Kingdom' \(did you mean 'United Kingdom'\?\)"):
            self.build(s)

    def test_two_roles_for_one_field(self):
        s = spec()
        sheet(s, "Countries")["geo"] = {"field": "State", "role": "country"}
        with self.assertRaisesRegex(ValueError, "one geographic role"):
            self.build(s)

    def test_filled_map_on_coordinates(self):
        s = spec()
        sheet(s, "Cities")["style"] = "filled"
        with self.assertRaisesRegex(ValueError, "has no polygon"):
            self.build(s)

    def test_coordinates_with_a_role(self):
        s = spec()
        sheet(s, "Cities")["geo"]["role"] = "city"
        with self.assertRaisesRegex(ValueError, "no role or country"):
            self.build(s)

    def test_geo_without_role_or_coordinates(self):
        s = spec()
        sheet(s, "Cities")["geo"] = {"field": "City"}
        with self.assertRaisesRegex(ValueError, "needs a role"):
            self.build(s)

    def test_latitude_out_of_range(self):
        rows = [dict(r) for r in ROWS]
        for r in rows:
            if r["City"] == "Boston":
                r["Latitude"] = "142.3601"
        s = with_csv(spec(), rows, "maps_lat/sales_geo.csv")
        with self.assertRaisesRegex(ValueError, r"outside -90\.\.90"):
            self.build(s)

    def test_text_latitude(self):
        s = spec()
        sheet(s, "Cities")["geo"]["lat"] = "State"
        with self.assertRaisesRegex(ValueError, "is string, not a number"):
            self.build(s)

    def test_place_with_two_points(self):
        rows = [dict(r) for r in ROWS]
        rows[0]["Longitude"] = "-10.0"
        s = with_csv(spec(), rows, "maps_moved/sales_geo.csv")
        with self.assertRaisesRegex(ValueError, "several coordinates"):
            self.build(s)

    def test_two_country_contexts(self):
        s = spec()
        s["sheets"].append({"name": "Cities", "type": "map", "geo": {"field": "City", "role": "city",
                                                                      "country": "Canada"},
                            "measure": {"field": "Sales"}})
        s["dashboard"]["grid"] = [["States", "Countries", "Cities"]]
        with self.assertRaisesRegex(ValueError, "one country context"):
            self.build(s)


class Lint(unittest.TestCase):
    def test_clean(self):
        self.assertEqual([str(f) for f in lint(spec(), SPEC.parent) if f.level != "info"], [])

    def test_few_places(self):
        rows = [dict(r, **{"Ship Country": "Canada" if i % 2 else "Mexico"}) for i, r in enumerate(ROWS)]
        s = with_csv(spec(), rows, "maps_few/sales_geo.csv")
        found = [f for f in lint(s, SPEC.parent) if f.rule == "G1"]
        self.assertTrue(found and found[0].level == "warn" and "Countries" in found[0].where, found)

    def test_city_not_verified(self):
        s = spec()
        sheet(s, "States")["geo"] = {"field": "City", "role": "city", "country": "United States"}
        found = [f for f in lint(s, SPEC.parent) if f.rule == "G2"]
        self.assertTrue(found and found[0].level == "error", found)


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build_file(SPEC, OUT / "maps_gate.twbx")

    def assertCaught(self, fn, text, replace=None):
        issues = [str(i) for i in gate.run(repack(fn, source=self.path, replace=replace))]
        self.assertTrue(any(i.startswith("[maps]") and text in i for i in issues), issues)

    def test_clean(self):
        self.assertEqual(gate.run(self.path), [])

    def test_geo_role_on_a_numeric_field(self):
        def f(r):
            ds = r.find("datasources/datasource")
            col = ds.find("column[@name='[State]']")
            col.set("datatype", "real")
        self.assertCaught(f, "on a real field")

    def test_map_without_a_geo_field(self):
        def f(r):
            enc = ws(r, "States").find("table/panes/pane/encodings")
            enc.remove(enc.find("lod"))
        self.assertCaught(f, "no field with a geographic role")

    def test_filled_map_by_city(self):
        def f(r):
            for c in r.iter("column"):
                if c.get("name") == "[Ship Country]":
                    c.set("semantic-role", "[City].[Name]")
        self.assertCaught(f, "filled map by [City].[Name]")

    def test_filled_map_without_geometry(self):
        def f(r):
            enc = ws(r, "Countries").find("table/panes/pane/encodings")
            enc.remove(enc.find("geometry"))
        self.assertCaught(f, "without its geometry")

    def test_longitude_on_rows(self):
        def f(r):
            t = ws(r, "States").find("table")
            t.find("rows").text, t.find("cols").text = t.find("cols").text, t.find("rows").text
        self.assertCaught(f, "latitude (generated) on Rows")

    def test_coordinate_role_on_text(self):
        def f(r):
            r.find("datasources/datasource/column[@name='[Latitude]']").set("datatype", "string")
        self.assertCaught(f, "a coordinate is a number")

    def test_coordinates_swapped(self):
        def f(r):
            t = ws(r, "Cities").find("table")
            t.find("rows").text, t.find("cols").text = t.find("cols").text, t.find("rows").text
        self.assertCaught(f, "latitude column on Rows")

    def test_undeclared_map_source(self):
        self.assertCaught(lambda r: r.remove(r.find("mapsources")), "is not declared")

    def test_unknown_place_in_the_data(self):
        with open(CSV, encoding="utf-8") as f:
            data = f.read().replace(",Germany,", ",Germnay,")
        self.assertCaught(None, "Germnay", replace={"Data/sample/sales_geo.csv": data.encode("utf-8")})


if __name__ == "__main__":
    unittest.main()
