"""Registry header band and bar color from the HTML (decisions/079): the column titles on a band of the th color,
the titles in a contrasting color, the bar_inside bars and the track's share in the registry's bar_color."""
import copy
import unittest
from pathlib import Path

from tbuilder import design, design_lint, gate, registry, spec as spec_mod
from tbuilder.design import COLOR
from test_registry_v2 import SPEC, built as _built, mutate, sheet

# its own file: test_registry_v2 writes its own while the modules run in parallel (decisions/181)
OUT = Path(__file__).resolve().parent.parent / "out" / "registry_header_test.twbx"


def built(spec):
    return _built(spec, OUT)

NAVY = "#0d3a6b"


def title_zones(root, dashboard, sheet_name):
    """The column title zones standing right on a registry's sheet zone (decisions/064)."""
    d = next(x for x in root.iter("dashboard") if x.get("name") == dashboard)
    z = next(z for z in d.iter("zone") if z.get("name") == sheet_name and z.get("type-v2") is None)
    y = int(z.get("y"))
    return [t for t in d.iter("zone") if t.get("type-v2") == "text" and int(t.get("y")) + int(t.get("h")) == y
            and int(z.get("x")) <= int(t.get("x")) < int(z.get("x")) + int(z.get("w"))]


def style(z):
    return {f.get("attr"): f.get("value") for f in z.iterfind("zone-style/format")}


class Spec(unittest.TestCase):
    def test_schema_takes_header_and_bar_color(self):
        spec_mod.validate(SPEC)
        bad = mutate(lambda s: sheet(s, "Regions").update(header={"text": "#ffffff"}))  # no color
        with self.assertRaises(Exception):
            spec_mod.validate(bad)
        bad = mutate(lambda s: sheet(s, "Regions").update(bar_color="navy"))
        with self.assertRaises(Exception):
            spec_mod.validate(bad)

    def test_title_color_contrasts_unless_given(self):
        self.assertEqual(registry.header_fill({"header": {"color": "#0D3A6B"}}), (NAVY, COLOR["shell_light"]))
        self.assertEqual(registry.header_fill({"header": {"color": "#f2f2f2"}}), ("#f2f2f2", COLOR["shell_dark"]))
        self.assertEqual(registry.header_fill({"header": {"color": "#0d3a6b", "text": "#FFFF00"}}), (NAVY, "#ffff00"))
        self.assertIsNone(registry.header_fill({}))

    def test_bar_color_defaults_to_the_accent(self):
        self.assertEqual(registry.bar_color({}), COLOR["accent"])
        self.assertEqual(registry.bar_color({"bar_color": "#0D3A6B"}), NAVY)

    def test_a_title_on_a_band_needs_its_padding(self):
        plain, band = {}, {"header": {"color": NAVY}}
        self.assertEqual(registry.title_pad_px(band) - registry.title_pad_px(plain), 2 * design.SPACE["zone_margin"])


class Lint(unittest.TestCase):
    def c8(self, spec):
        return [f.text for f in design_lint.lint(spec, ".") if f.rule == "C8"]

    def test_clean(self):
        self.assertEqual(self.c8(SPEC), [])

    def test_header_text_without_contrast(self):
        spec = mutate(lambda s: sheet(s, "Regions").update(header={"color": "#777777", "text": "#ffffff"}))
        self.assertTrue(any("header" in t for t in self.c8(spec)))

    def test_white_value_on_a_light_bar(self):
        spec = mutate(lambda s: sheet(s, "Regions").update(bar_color="#9ecae1"))
        self.assertTrue(any("bar_color" in t for t in self.c8(spec)))


class Workbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = copy.deepcopy(SPEC)
        spec["dashboard"]["theme"] = "flat"  # plain titles: the cards' own are in test_cards
        cls.root = built(spec)
        cls.ws = {w.get("name"): w for w in cls.root.iter("worksheet")}

    def test_titles_on_a_band(self):
        zones = title_zones(self.root, "Registry v2", "Regions")
        self.assertEqual(len(zones), 6)  # Region + 5 columns
        for z in zones:
            st = style(z)
            self.assertEqual((st["background-color"], st["padding"], st["margin"]),
                             (NAVY, str(design.SPACE["zone_margin"]), "0"))
            self.assertEqual(z.find("formatted-text/run").get("fontcolor"), COLOR["shell_light"])
        # side by side: one band, no gap between the zones
        xs = sorted((int(z.get("x")), int(z.get("w"))) for z in zones)
        for (x0, w0), (x1, _) in zip(xs, xs[1:]):
            self.assertEqual(x0 + w0, x1)

    def test_band_is_taller(self):
        d = next(self.root.iter("dashboard"))
        height = int(d.find("size").get("maxheight"))
        band = title_zones(self.root, "Registry v2", "Regions")[0]
        plain = title_zones(self.root, "Registry v2", "Categories")[0]
        self.assertEqual(round(int(band.get("h")) * height / 100000), registry.HEADER_FILL_PX)
        self.assertEqual(round(int(plain.get("h")) * height / 100000), design.REGISTRY_HEADER_PX)

    def test_registry_without_header_unchanged(self):
        for z in title_zones(self.root, "Registry v2", "Categories"):
            self.assertNotIn("background-color", style(z))
            self.assertIsNone(z.find("formatted-text/run").get("fontcolor"))

    def test_bar_inside_in_the_bar_color(self):
        def colors(name):
            return [f.get("value") for p in self.ws[name].iterfind("table/panes/pane[@x-index]")
                    for f in p.iterfind("style/style-rule[@element='mark']/format[@attr='mark-color']")] + \
                [f.get("value") for p in self.ws[name].iterfind("table/panes/pane")
                 if p.find("customized-label/formatted-text/run[@fontcolor='#ffffff']") is not None
                 for f in p.iterfind("style/style-rule[@element='mark']/format[@attr='mark-color']")]
        self.assertIn(NAVY, colors("Regions"))
        self.assertNotIn(COLOR["accent"], colors("Regions"))
        self.assertIn(COLOR["accent"], colors("Top · Region"))  # no bar_color: the accent


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(copy.deepcopy(SPEC))

    def issues(self, fn, check):
        root = copy.deepcopy(self.root)
        fn(root)
        return check(root)

    def test_clean(self):
        self.assertEqual(gate.check_text_fill(self.root), [])
        self.assertEqual(gate.check_registry_widths(self.root), [])

    def test_dark_title_on_the_band(self):
        def f(root):
            z = title_zones(root, "Registry v2", "Regions")[1]
            z.find("formatted-text/run").set("fontcolor", "#333333")
        got = self.issues(f, gate.check_text_fill)
        self.assertEqual(len(got), 1)
        self.assertIn("contrast", got[0].message)

    def test_title_without_color_on_the_band(self):
        def f(root):
            z = title_zones(root, "Registry v2", "Regions")[2]
            del z.find("formatted-text/run").attrib["fontcolor"]
        self.assertEqual(len(self.issues(f, gate.check_text_fill)), 1)

    def test_padding_counts_against_the_title(self):
        """A title that fits its zone without the padding is cut with it."""
        def f(root):
            z = title_zones(root, "Registry v2", "Regions")[1]
            d = next(root.iter("dashboard"))
            width = int(d.find("size").get("maxwidth"))
            run = z.find("formatted-text/run")
            have = round(int(z.get("w")) * width / 100000)
            size, bold = int(run.get("fontsize", "9")), run.get("bold") == "true"
            text = ""
            for ch in "Wi":  # wide letters, then narrow ones up to the zone's edge
                while design.text_px(text + ch, size, bold=bold) + design.TITLE_PAD_PX <= have:
                    text += ch
            self.assertGreater(design.text_px(text, size, bold=bold) + design.TITLE_PAD_PX, have - 8)
            run.text = text  # fits the zone, not the zone less 2 x padding
        got = self.issues(f, gate.check_registry_widths)
        self.assertTrue(any("Desktop cuts it" in i.message for i in got))


if __name__ == "__main__":
    unittest.main()
