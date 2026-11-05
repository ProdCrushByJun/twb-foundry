"""Card theme (decisions/030): dashboard.theme "cards", theme_font, kpi.arrange "strip"."""
import copy
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile

from tbuilder import gate
from tbuilder.build import build, build_file
from tbuilder.design import COLOR, SPACE
from test_gate import repack
from test_roundtrip import OUT, SPECS

SPEC = json.loads((SPECS / "theme_cards.json").read_text(encoding="utf-8"))
HEADERS = json.loads((SPECS / "headers.json").read_text(encoding="utf-8"))
W, H = SPEC["dashboard"]["width"], SPEC["dashboard"]["height"]


def mutate(fn, base=SPEC):
    spec = copy.deepcopy(base)
    fn(spec)
    return spec


def built(spec, name="theme_test"):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def style(z):
    return {f.get("attr"): f.get("value") for f in z.findall("zone-style/format")}


def px(z):
    """(left, top, right, bottom) of a zone in px."""
    x, y, w, h = (int(z.get(k)) for k in ("x", "y", "w", "h"))
    return x * W / 1e5, y * H / 1e5, (x + w) * W / 1e5, (y + h) * H / 1e5


def cards(root):
    return [z for z in root.iter("zone") if style(z).get("border-style") == "solid"]


def runs(z):
    return z.findall("formatted-text/run")


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(SPEC)
        cls.db = cls.root.find("dashboards/dashboard")

    def test_workbook_font_after_preferences(self):
        tags = [c.tag for c in self.root]
        self.assertEqual(tags[tags.index("preferences") + 1], "style")
        f = self.root.find("style/style-rule[@element='all']/format")
        self.assertEqual((f.get("attr"), f.get("value")), ("font-family", "Arial"))

    def test_canvas(self):
        f = self.db.find("style/style-rule[@element='table']/format")
        self.assertEqual((f.get("attr"), f.get("value")), ("background-color", COLOR["canvas"]))

    def test_every_block_is_a_card(self):
        cs = cards(self.root)
        self.assertEqual(len(cs), 4)  # KPI strip, Regions, Trend, Registry
        for c in cs:
            self.assertEqual((c.get("type-v2"), c.get("param")), ("layout-flow", "vert"))
            kpi = any((z.get("name") or "").startswith("KPI") for z in c.iter("zone"))
            self.assertEqual(style(c), {"border-color": COLOR["card_border"], "border-style": "solid",
                                        "border-width": "1", "margin": "6", "padding": "12" if kpi else "16",
                                        "background-color": COLOR["card_bg"]})
            kids = c.findall("zone")
            self.assertEqual([k.get("type-v2") for k in kids], ["layout-basic"])
            self.assertEqual(list(c)[-1].tag, "zone-style")  # after its child, as Desktop writes it
        names = {z.get("name") for c in cs for z in c.iter("zone") if z.get("name")}
        self.assertTrue({"Regions", "Trend", "Registry", "KPI · Sales"} <= names)

    def test_header_row_on_the_canvas(self):
        title = next(z for z in self.db.iter("zone") if z.get("type-v2") == "text"
                     and "Overview" in "".join(r.text or "" for r in runs(z)))
        self.assertNotIn(title, [z for c in cards(self.root) for z in c.iter("zone")])
        self.assertEqual(style(title)["margin"], str(SPACE["card_margin"]))

    def test_cards_12px_apart_and_12px_from_the_edge(self):
        """decisions/187: gap 12 (6 + 6), edge 12 (theme_edge 6 + card_margin 6): one number."""
        boxes = []
        for c in cards(self.root):
            l, t, r, b = px(c)
            m = SPACE["card_margin"]
            boxes.append((l + m, t + m, r - m, b - m))  # the border
        self.assertAlmostEqual(min(b[0] for b in boxes), 12, delta=0.5)
        self.assertAlmostEqual(max(b[2] for b in boxes), W - 12, delta=0.5)
        self.assertAlmostEqual(max(b[3] for b in boxes), H - 12, delta=0.5)
        regions, trend = sorted((b for b in boxes if abs(b[1] - boxes[1][1]) < 1), key=lambda b: b[0])
        self.assertAlmostEqual(trend[0] - regions[2], 12, delta=0.5)
        kpi = min(boxes, key=lambda b: b[1])
        self.assertAlmostEqual(regions[1] - kpi[3], 12, delta=0.5)
        self.assertAlmostEqual(min(b[1] for b in boxes) - kpi[1], 0)

    def test_parts_sit_on_the_padding(self):
        """Inner by the card's weight (decisions/070): KPI 12, chart / table 16; on all four sides."""
        for c in cards(self.root):
            basic = c.find("zone")
            bl, bt, br, bb = px(basic)
            cl, ct, cr, cb = px(c)
            kpi = any((z.get("name") or "").startswith("KPI") for z in c.iter("zone"))
            inset = 6 + 1 + (12 if kpi else 16)  # margin + border + padding
            for d in (bl - cl, bt - ct, cr - br, cb - bb):
                self.assertAlmostEqual(d, inset, delta=0.6)
            for z in basic.findall("zone"):
                if z.get("type-v2") == "empty":
                    continue
                st, (l, t, r, b) = style(z), px(z)
                if abs(l - bl) < 0.5:
                    self.assertEqual(st.get("margin-left", st["margin"]), "0", z.get("name"))

    def test_kpi_strip_dividers(self):
        kpi = cards(self.root)[0]
        rules = [z for z in kpi.iter("zone") if z.get("type-v2") == "empty"]
        self.assertEqual(len(rules), 2)  # between three measures
        for z in rules:
            st, (l, t, r, b) = style(z), px(z)
            self.assertEqual((st["margin"], st["background-color"]), ("8", COLOR["rule"]))
            self.assertAlmostEqual(r - l - 16, 1, delta=0.5)

    def test_typography(self):
        head = next(z for z in self.db.iter("zone") if any(r.text == " Overview" for r in runs(z)))
        self.assertEqual([(r.text, r.get("fontsize")) for r in runs(head)][:2], [("Sales", "18"), (" Overview", "18")])
        title = next(z for z in self.db.iter("zone") if z.get("type-v2") == "text"
                     and any(r.text == "Monthly " for r in runs(z)))
        self.assertEqual({r.get("fontsize") for r in runs(title) if r.text != "Æ\n"}, {"12"})
        self.assertEqual({r.get("fontcolor") for r in runs(title) if r.text != "Æ\n"}, {COLOR["text"]})
        sub = [r for z in self.db.iter("zone") for r in runs(z) if r.text == "Sample data, 2024-2025"]
        self.assertEqual([(r.get("fontsize"), r.get("fontcolor")) for r in sub], [("11", COLOR["subtitle"])])
        label = next(w for w in self.root.iter("worksheet") if w.get("name") == "KPI · Sales").find(
            ".//customized-label/formatted-text")
        rs = [r for r in label if r.text != "Æ\n"]
        self.assertEqual((rs[1].get("fontsize"), rs[1].get("bold"), rs[1].get("fontcolor")),
                         ("11", None, COLOR["muted"]))  # the name: regular, muted
        self.assertEqual((rs[2].get("fontsize"), rs[2].get("fontcolor")), ("24", COLOR["text"]))  # 3 side by side
        self.assertEqual([rs[3].get("fontcolor"), rs[4].get("fontcolor")], [COLOR["good_text"], COLOR["bad_text"]])

    def test_history_lighter(self):
        maps = [m for m in self.root.iter("map") if m.find("bucket") is not None]
        buckets = {b.text: m.get("to") for m in maps for b in m.findall("bucket")}
        self.assertEqual(buckets.get("false"), COLOR["history"])

    def test_registry_rows(self):
        reg = next(w for w in self.root.iter("worksheet") if w.get("name") == "Registry")
        f = reg.find("table/style/style-rule[@element='cell']/format[@attr='height']")
        self.assertEqual(f.get("value"), "30")
        self.assertIn("Category", f.get("field"))  # the inner row field
        titles = [z for z in self.db.iter("zone") if z.get("type-v2") == "text" and style(z).get("margin") == "0"
                  and not style(z).get("margin-bottom")]
        self.assertTrue(titles)
        self.assertTrue(all(abs(px(z)[3] - px(z)[1] - 28) < 0.6 for z in titles))


class Typography(unittest.TestCase):
    def label_size(self, spec, sheet):
        root = built(spec)
        label = next(w for w in root.iter("worksheet") if w.get("name") == sheet).find(
            ".//customized-label/formatted-text")
        return [r for r in label if r.text != "Æ\n"][2].get("fontsize")

    def test_kpi_number_18_when_dense_or_stacked(self):
        def five(s):
            s["sheets"][0]["measures"] += [{"field": "Sales", "label": "S2"}, {"field": "Profit", "label": "P2"}]
            s["dashboard"]["width"] = 1450
        self.assertEqual(self.label_size(mutate(five), "KPI · Sales"), "18")

        def column(s):
            s["sheets"][0]["arrange"] = "column"
            s["dashboard"]["grid"] = [[{"sheet": "KPI"}, {"rows": [["Regions", "Trend"], ["Registry"]], "width": 2}]]
            s["dashboard"]["row_heights"] = [1]
        self.assertEqual(self.label_size(mutate(column), "KPI · Sales"), "18")

    def test_tiles_in_the_theme(self):
        def tiles(s):
            s["sheets"][0] = {"name": "KPI", "type": "kpi", "style": "tiles", "arrange": "strip",
                              "measures": [{"field": "Sales"}, {"field": "Profit"}]}
        root = built(mutate(tiles))
        label = next(w for w in root.iter("worksheet") if w.get("name") == "KPI · Sales").find(
            ".//customized-label/formatted-text")
        self.assertEqual([(r.get("fontsize"), r.get("fontcolor")) for r in label if r.text != "Æ\n"],
                         [("11", COLOR["muted"]), ("24", COLOR["text"])])
        self.assertEqual(len([z for z in cards(root)[0].iter("zone") if z.get("type-v2") == "empty"]), 1)


class Options(unittest.TestCase):
    def test_spec_valid(self):
        from tbuilder.spec import validate
        validate(SPEC)

    def test_font_without_the_theme(self):
        root = built(mutate(lambda s: s["dashboard"].update(theme="flat", theme_font="Arial"), HEADERS), "theme_font_only")
        self.assertEqual(root.find("style/style-rule/format").get("value"), "Arial")
        self.assertEqual(cards(root), [])

    def test_cards_are_the_default(self):
        """decisions/168: a spec that names no theme is built as if it said 'cards'."""
        self.assertNotIn("theme", HEADERS["dashboard"])
        root = built(HEADERS, "theme_default")
        self.assertTrue(cards(root))
        said = built(mutate(lambda s: s["dashboard"].update(theme="cards"), HEADERS), "theme_default")
        zones = lambda r: [[z.get(k) for k in ("id", "name", "type-v2", "x", "y", "w", "h")] for z in r.iter("zone")]
        self.assertEqual(zones(root), zones(said))

    def test_no_zone_selected(self):
        """N8 (decisions/168): a window opens with nothing selected, as in a book saved by Desktop."""
        self.assertEqual({a.get("id") for a in built(HEADERS, "theme_active").iter("active")}, {"-1"})

    def test_flat_is_the_view_without_cards(self):
        root = built(mutate(lambda s: s["dashboard"].update(theme="flat"), HEADERS), "theme_flat")
        self.assertIsNone(root.find("style"))
        self.assertEqual(cards(root), [])
        self.assertEqual(len(root.find("dashboards/dashboard/style")), 0)

    def assertFails(self, spec, text):
        with self.assertRaises(ValueError) as e:
            build(spec, OUT / "theme_fail.twbx", SPECS)
        self.assertIn(text, str(e.exception))

    def test_strip_needs_the_theme(self):
        self.assertFails(mutate(lambda s: s["dashboard"].update(theme="flat")), "cannot be drawn with dashboard.theme 'flat'")

    def test_sidebar_and_topbar_not_yet(self):
        self.assertFails(mutate(lambda s: s["dashboard"].update(sidebar=True)), "sidebar is not supported")
        self.assertFails(mutate(lambda s: s["dashboard"].update(topbar={"color": "#221622", "title": "App"})),
                         "topbar is not supported")


class GateCatchesTheme(unittest.TestCase):
    """Mutations of the card theme workbook: borders, faces, dividers and the canvas only from tokens."""

    @classmethod
    def setUpClass(cls):
        cls.src = build_file(SPECS / "theme_cards.json", OUT / "theme_gate.twbx")

    def assertCaught(self, path, check, text):
        issues = gate.run(path)
        hits = [i for i in issues if i.check == check and text in str(i)]
        self.assertTrue(hits, f"expected [{check}] ~ '{text}', got: {[str(i) for i in issues]}")

    @staticmethod
    def card(r):
        return next(z for z in r.iter("zone") if z.find("zone-style/format[@value='solid']") is not None)

    @staticmethod
    def fmt(z, attr):
        return z.find(f"zone-style/format[@attr='{attr}']")

    def test_generated_passes(self):
        self.assertEqual(gate.run(self.src), [])

    def test_border_not_from_a_token(self):
        self.assertCaught(repack(lambda r: self.fmt(self.card(r), "border-color").set("value", "#d0d0d0"),
                                 source=self.src), "theme", "card border-color #d0d0d0")

    def test_border_2px(self):
        self.assertCaught(repack(lambda r: self.fmt(self.card(r), "border-width").set("value", "2"),
                                 source=self.src), "theme", "card border-width 2")

    def test_card_without_padding(self):
        def m(r):
            c = self.card(r)
            c.find("zone-style").remove(self.fmt(c, "padding"))
        path = repack(m, source=self.src)
        self.assertCaught(path, "theme", "card padding None")
        self.assertCaught(path, "spacing", "on a card's padding")  # its parts' margin 0 now touches the border

    def test_card_inner_under_half_the_gap(self):
        """inner >= outer (decisions/070): a card padding 4 with margin 6 (gap 12)."""
        path = repack(lambda r: self.fmt(self.card(r), "padding").set("value", "4"), source=self.src)
        self.assertCaught(path, "theme", "under half the gap")

    def test_card_old_margin(self):
        """decisions/187: the old margin 10 (gap 20) is no longer a token."""
        path = repack(lambda r: self.fmt(self.card(r), "margin").set("value", "10"), source=self.src)
        self.assertCaught(path, "theme", "card margin 10 is not the token")

    def test_root_margin_off_the_system(self):
        """decisions/187: cards 12 apart, the dashboard edge 16: the edge and the gap are one system."""
        def m(r):
            for root in r.iter("dashboard"):
                self.fmt(root.find("zones/zone"), "margin").set("value", "10")
        self.assertCaught(repack(m, source=self.src), "theme", "root zone margin 10 is not the token")

    def text_with_fill(self, r, padding):
        """The dashboard title as a band header: a text zone with its own background."""
        z = next(z for z in r.iter("zone") if z.get("type-v2") == "text")
        st = z.find("zone-style")
        st.append(st.makeelement("format", {"attr": "background-color", "value": COLOR["rule"]}))
        if padding is not None:
            st.append(st.makeelement("format", {"attr": "padding", "value": str(padding)}))

    def test_text_with_fill_without_padding(self):
        self.assertCaught(repack(lambda r: self.text_with_fill(r, None), source=self.src), "spacing",
                          "a text with its own background needs a padding")

    def test_text_with_fill_padding_not_a_token(self):
        self.assertCaught(repack(lambda r: self.text_with_fill(r, 7), source=self.src), "spacing",
                          "not a design.SPACE token")

    def test_text_with_fill_and_token_padding_passes(self):
        issues = gate.run(repack(lambda r: self.text_with_fill(r, SPACE["zone_margin"]), source=self.src))
        self.assertEqual([str(i) for i in issues if "background" in str(i) or "padding" in str(i)], [])

    def test_divider_not_1px(self):
        def m(r):
            z = next(z for z in r.iter("zone") if z.get("type-v2") == "empty"
                     and self.fmt(z, "background-color") is not None)
            self.fmt(z, "margin").set("value", "4")  # a 17px zone with margin 4 draws a 9px bar
        self.assertCaught(repack(m, source=self.src), "theme", "not 1px")

    def test_border_on_a_sheet(self):
        def m(r):
            z = next(z for z in r.iter("zone") if z.get("name") == "Regions")
            self.fmt(z, "border-style").set("value", "solid")
        self.assertCaught(repack(m, source=self.src), "theme", "borders only on cards")

    def test_canvas_not_from_a_token(self):
        def m(r):
            r.find("dashboards/dashboard/style/style-rule/format").set("value", "#eeeeee")
        self.assertCaught(repack(m, source=self.src), "theme", "not the canvas")


class SheetText(unittest.TestCase):
    """decisions/089: a chart's text 8pt muted in the theme (the worksheet's style-rule), column titles 8pt."""

    @classmethod
    def setUpClass(cls):
        cls.root = built(SPEC, "theme_text")

    def rule(self, root, sheet):
        w = next(w for w in root.iter("worksheet") if w.get("name") == sheet)
        r = w.find("table/style/style-rule[@element='worksheet']")
        return None if r is None else [(f.get("attr"), f.get("value")) for f in r.findall("format")]

    def test_chart_text_8pt_muted(self):
        for sheet in ("Regions", "Trend"):
            self.assertEqual(self.rule(self.root, sheet)[:2], [("font-size", "8"), ("color", COLOR["muted"])], sheet)

    def test_heatmap_size_only(self):
        def heat(s):
            s["sheets"][1] = {"name": "Regions", "type": "heatmap", "rows": "Region", "cols": "Category",
                              "measure": {"field": "Sales"}}
        rule = self.rule(built(mutate(heat), "theme_heat"), "Regions")
        self.assertEqual(rule[0], ("font-size", "8"))
        self.assertNotIn("color", [a for a, _ in rule])

    def test_registry_column_titles_8(self):
        db = self.root.find("dashboards/dashboard")
        titles = [r for z in db.iter("zone") if z.get("type-v2") == "text" for r in runs(z) if r.text == "Region"]
        self.assertEqual([r.get("fontsize") for r in titles], ["8"])

    def test_not_without_the_theme(self):
        spec = copy.deepcopy(HEADERS)
        spec["dashboard"]["theme"] = "flat"
        root = built(spec, "theme_none_text")
        for w in root.iter("worksheet"):
            self.assertNotIn(("font-size", "8"), self.rule(root, w.get("name")) or [], w.get("name"))


class Borderless(unittest.TestCase):
    """dashboard.card_border false (decisions/089): the card's face on the canvas, no border, the same inset less 1px."""

    @classmethod
    def setUpClass(cls):
        cls.spec = mutate(lambda s: s["dashboard"].update(card_border=False))
        cls.src = build(cls.spec, OUT / "theme_borderless.twbx", SPECS)
        with zipfile.ZipFile(cls.src) as z:
            cls.root = ET.fromstring(z.read(cls.src.stem + ".twb"))

    def faces(self):
        return [z for z in self.root.iter("zone") if z.get("type-v2") == "layout-flow"
                and style(z).get("background-color") == COLOR["card_bg"] and "padding" in style(z)]

    def test_no_border_formats(self):
        self.assertEqual(cards(self.root), [])
        self.assertTrue(self.faces())
        for z in self.faces():
            self.assertFalse({"border-style", "border-color", "border-width"} & set(style(z)))

    def test_gate_passes_and_catches_the_face(self):
        self.assertEqual(gate.run(self.src), [])

        def m(r):
            z = next(z for z in r.iter("zone") if z.get("type-v2") == "layout-flow"
                     and z.find("zone-style/format[@attr='padding']") is not None)
            z.find("zone-style/format[@attr='margin']").set("value", "10")
        issues = gate.run(repack(m, source=self.src))
        self.assertTrue([i for i in issues if i.check == "theme" and "card margin 10" in str(i)],
                        [str(i) for i in issues])


class Golden(unittest.TestCase):
    """golden_theme_cards (decisions/070): Desktop 2025.1 re-saved the card theme without moving a zone, once the
    card's inner layout-basic is inset by margin, border and padding each rounded to units (061 found 1-2 units)."""

    def test_golden_rebuilds_identically(self):
        import difflib
        from test_roundtrip import ROOT, canon, normalize, read_twbx
        got, names = read_twbx(build_file(SPECS / "theme_cards.json", OUT / "roundtrip_theme_cards.twbx"))
        self.assertIn("Data/sample/sales_2y.csv", names)
        want, _ = read_twbx(ROOT / "golden" / "golden_theme_cards_2025_1.twbx")
        a, b = canon(normalize(want)), canon(normalize(got))
        self.assertEqual(a, b, "\n" + "\n".join(difflib.unified_diff(a, b, "golden", "generated", lineterm="", n=2)))

    def test_inset_units_as_desktop_writes_them(self):
        """Points from Desktop re-saves (out/r070, out/l10): (margin, padding, dashboard px) -> units of the inset."""
        from tbuilder import theme

        class B:
            _units = staticmethod(lambda px, size: round(px * 100000 / size))
            spec = {"dashboard": {}}
        points = [((10, 16, 1200), 2249), ((10, 12, 1200), 1916), ((8, 12, 1200), 1750), ((10, 12, 960), 2396),
                  ((10, 16, 960), 2813), ((8, 12, 960), 2187), ((10, 12, 900), 2555), ((10, 12, 800), 2875),
                  ((10, 16, 1250), 2160), ((10, 12, 1250), 1840),
                  ((6, 16, 1250), 1840), ((6, 12, 1250), 1520), ((6, 16, 960), 2396), ((6, 12, 960), 1979),
                  ((6, 16, 1280), 1797), ((6, 12, 1280), 1485)]
        old = dict(SPACE)
        try:
            for (margin, pad, size), want in points:
                SPACE.update(card_margin=margin, card_padding=pad)
                self.assertEqual(theme.inset_units(B, (size, size), {"type": "bar"}), (want, want),
                                 (margin, pad, size))
        finally:
            SPACE.update(old)
