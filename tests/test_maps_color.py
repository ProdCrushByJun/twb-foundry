"""The book's accent and map colors (decisions/137): dashboard.accent everywhere the house accent was; a symbol map
colored by a measure (its own or a second one), size: false, a diverging filled map; round-trip, expected, refusals,
lint C7 / C8, gate mutations."""
import json
import unittest
import zipfile
import xml.etree.ElementTree as ET

from tbuilder import design, expected, gate, heatmap, maps
from tbuilder.build import build, build_file
from tbuilder.design import COLOR
from tbuilder.design_lint import lint
from test_gate import repack, ws
from test_roundtrip import OUT, ROOT, canon, normalize, read_twbx

SPECS = ROOT / "specs"
SPEC = SPECS / "maps_color.json"
GOLDEN = ROOT / "golden" / "golden_maps_color_2025_1.twb"
ACCENT = "#c4572a"
HOUSE = "#4e79a7"


def load(name):
    return json.loads((SPECS / name).read_text(encoding="utf-8"))


def twb(path):
    with zipfile.ZipFile(path) as z:
        return ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


def sheet(s, name):
    return next(x for x in s["sheets"] if x["name"] == name)


def with_accent(s, accent):
    for d in s["dashboards"] if "dashboards" in s else [s["dashboard"]]:
        d["accent"] = accent
    return s


def encodings(root, name):
    return {e.tag: e.get("column") for e in ws(root, name).find("table/panes/pane/encodings")}


def palette(root, name):
    pal = ws(root, name).find("table/style/style-rule[@element='mark']/encoding[@attr='color']/color-palette")
    return pal.get("type"), [c.text for c in pal.findall("color")]


def mark_formats(root, name):
    rule = ws(root, name).find("table/panes/pane/style/style-rule[@element='mark']")
    return {f.get("attr"): f.get("value") for f in rule.findall("format")}


class RoundTrip(unittest.TestCase):
    def test_golden_rebuilds_identically(self):
        """A symbol map sized by sales and colored by profit (diverging), a diverging filled map, same-size circles
        on a sequential scale, accent #c4572a: re-saved by Desktop 2025.1 (Save As)."""
        out = build_file(SPEC, OUT / "roundtrip_maps_color.twbx")
        got, _ = read_twbx(out)
        self.assertEqual(canon(normalize(ET.parse(GOLDEN).getroot())), canon(normalize(got)))


class MapColors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = twb(build_file(SPEC, OUT / "maps_color.twbx"))

    def test_second_measure_on_color_size_kept(self):
        e = encodings(self.root, "States")
        self.assertIn("[sum:Profit:qk]", e["color"])
        self.assertIn("[sum:Sales:qk]", e["size"])
        self.assertIn("[sum:Sales:qk]", e["text"])  # the labels stay on the size measure
        self.assertNotIn("mark-color", mark_formats(self.root, "States"))  # the scale paints the circles
        kind, colors = palette(self.root, "States")
        self.assertEqual(kind, "ordered-diverging")
        self.assertEqual((colors[0], colors[-1]), (COLOR["bad"], COLOR["good"]))
        tip = "".join(r.text for r in ws(self.root, "States").iter("run"))
        self.assertIn("Profit:", tip)  # the color's measure is read in the tooltip

    def test_same_size_circles_on_a_sequential_scale(self):
        e = encodings(self.root, "Cities")
        self.assertNotIn("size", e)
        self.assertIn("[sum:Sales:qk]", e["color"])
        kind, colors = palette(self.root, "Cities")
        self.assertEqual(kind, "ordered-sequential")
        self.assertEqual(colors[-1], ACCENT)  # the book's accent at the dark end
        with design.book_accent(load("maps_color.json")):
            self.assertEqual(colors, maps.filled_palette())
        self.assertNotEqual(colors[0], COLOR["scale_low"])  # from FILLED_LOW of the way: not the map's land

    def test_filled_diverging(self):
        self.assertEqual(palette(self.root, "Countries")[0], "ordered-diverging")
        enc = ws(self.root, "Countries").find("table/style/style-rule[@element='mark']/encoding[@attr='color']")
        self.assertEqual(enc.get("center"), "3000.0")

    def test_accent_restored_after_the_build(self):
        self.assertEqual(COLOR["accent"], HOUSE)


class HouseAccent(unittest.TestCase):
    """Without the keys the maps are drawn as before (golden_maps is checked byte by byte in test_maps)."""

    def test_symbol_map_in_the_house_accent(self):
        root = twb(build_file(SPECS / "maps.json", OUT / "maps_house.twbx"))
        self.assertEqual(mark_formats(root, "States")["mark-color"], HOUSE)
        self.assertIn("size", encodings(root, "States"))
        self.assertEqual(palette(root, "Countries"), ("ordered-sequential", maps.filled_palette()))


class BookAccent(unittest.TestCase):
    def test_symbol_map_highlight_heatmap_and_nav(self):
        root = twb(build(with_accent(load("maps.json"), ACCENT), OUT / "accent_maps.twbx", SPECS))
        self.assertEqual(mark_formats(root, "States")["mark-color"], ACCENT)
        self.assertEqual(palette(root, "Countries")[1][-1], ACCENT)
        root = twb(build(with_accent(load("colors.json"), ACCENT), OUT / "accent_colors.twbx", SPECS))
        self.assertIn(ACCENT, ET.tostring(root, encoding="unicode"))
        self.assertNotIn(HOUSE, ET.tostring(root, encoding="unicode"))
        path = build(with_accent(load("nav.json"), ACCENT), OUT / "accent_nav.twbx", SPECS)
        lines = [z for z in twb(path).iter("zone") if z.get("type-v2") == "empty" and z.get("fixed-size") == "3"]
        colors = {f.get("value") for z in lines for f in z.iter("format") if f.get("attr") == "background-color"}
        self.assertEqual(colors, {ACCENT})
        self.assertEqual(gate.run(path, with_accent(load("nav.json"), ACCENT)), [])
        self.assertEqual(COLOR["accent"], HOUSE)

    def test_given_accent(self):
        self.assertIsNone(design.given_accent(load("maps.json")))
        self.assertEqual(design.given_accent(with_accent(load("nav.json"), "#C4572A")), ACCENT)
        with design.book_accent(with_accent(load("maps.json"), ACCENT)):
            self.assertEqual(heatmap.palette({"scale": "sequential"})[1][-1], ACCENT)
        self.assertEqual(COLOR["accent"], HOUSE)

    def test_dashboards_share_one_accent(self):
        s = load("nav.json")
        s["dashboards"][0]["accent"] = ACCENT
        with self.assertRaisesRegex(Exception, "differ in 'accent'"):
            build(s, OUT / "accent_differ.twbx", SPECS)


class Expected(unittest.TestCase):
    def test_color_record_of_the_second_measure(self):
        s = json.loads(SPEC.read_text(encoding="utf-8"))
        e = expected.compute(s, SPECS / s["datasource"]["path"])
        self.assertEqual(set(e[maps.color_record("States")]), set(e["States"]))
        self.assertNotEqual(e[maps.color_record("States")], e["States"])  # profit, not sales
        self.assertNotIn(maps.color_record("Cities"), e)  # colored by its own measure


class Refusals(unittest.TestCase):
    def test_size_on_a_filled_map(self):
        s = load("maps_color.json")
        sheet(s, "Countries")["size"] = False
        with self.assertRaisesRegex(Exception, "'size' is a symbol map's"):
            build(s, OUT / "maps_color_bad.twbx", SPECS)

    def test_diverging_without_center(self):
        s = load("maps_color.json")
        del sheet(s, "Countries")["color"]["center"]
        with self.assertRaisesRegex(Exception, "needs 'center'"):
            build(s, OUT / "maps_color_bad.twbx", SPECS)


class Lint(unittest.TestCase):
    def rules(self, s):
        return [(f.rule, f.level, f.text) for f in lint(s, SPECS)]

    def test_clean(self):
        self.assertEqual([r for r in self.rules(load("maps_color.json")) if r[0] in ("C7", "C8")], [])

    def test_accent_near_good(self):
        found = [r for r in self.rules(with_accent(load("maps.json"), "#40a0a0")) if r[0] == "C7"]
        self.assertTrue(found and found[0][1] == "warn" and "'good'" in found[0][2], found)

    def test_white_on_a_light_accent(self):
        found = [r for r in self.rules(with_accent(load("fixture_referrals.json"), "#f2c94c")) if r[0] == "C8"]
        self.assertTrue(found and found[0][1] == "error" and "accent" in found[0][2], found)

    def test_house_accent_not_checked(self):  # #4e79a7 under white is 4.4:1: the house look stays as it is
        self.assertEqual([r for r in self.rules(load("fixture_referrals.json")) if r[0] == "C8"], [])


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build_file(SPEC, OUT / "maps_color_gate.twbx")
        cls.spec = load("maps_color.json")

    def assertCaught(self, fn, text, spec=None):
        issues = [str(i) for i in gate.run(repack(fn, source=self.path), spec or self.spec)]
        self.assertTrue(any(text in i for i in issues), issues)

    def test_clean(self):
        self.assertEqual(gate.run(self.path, self.spec), [])

    def test_color_dropped(self):
        def f(r):
            enc = ws(r, "Cities").find("table/panes/pane/encodings")
            enc.remove(enc.find("color"))
        self.assertCaught(f, "not colored by a measure")

    def test_size_on_same_size_circles(self):
        def f(r):
            enc = ws(r, "Cities").find("table/panes/pane/encodings")
            ET_size = enc.makeelement("size", {"column": enc.find("color").get("column")})
            enc.insert(1, ET_size)
        self.assertCaught(f, "size encoding present")

    def test_color_on_the_size_measure(self):
        def f(r):
            w = ws(r, "States")
            size = w.find("table/panes/pane/encodings/size").get("column")
            w.find("table/panes/pane/encodings/color").set("column", size)
            w.find("table/style/style-rule[@element='mark']/encoding[@attr='color']").set("field", size)
        self.assertCaught(f, "not the measure Profit")

    def test_palette_changed(self):
        def f(r):
            ws(r, "Cities").find("table/style/style-rule[@element='mark']/encoding/color-palette/color").text = "#000000"
        self.assertCaught(f, "is not the map's ordered-sequential scale")

    def test_palette_of_another_accent(self):  # the gate takes the book's accent from the spec
        self.assertCaught(None, "is not the map's", with_accent(load("maps_color.json"), HOUSE))

    def test_symbol_not_in_the_accent(self):
        path = build(with_accent(load("maps.json"), ACCENT), OUT / "accent_maps_gate.twbx", SPECS)
        issues = [str(i) for i in gate.run(path, load("maps.json"))]
        self.assertTrue(any("not the book's accent #4e79a7" in i for i in issues), issues)

    def test_nav_line_not_the_book_accent(self):
        path = build(load("nav.json"), OUT / "nav_house_gate.twbx", SPECS)
        issues = [str(i) for i in gate.run(path, with_accent(load("nav.json"), ACCENT))]
        self.assertTrue(any("is not the accent token " + ACCENT in i for i in issues), issues)


if __name__ == "__main__":
    unittest.main()
