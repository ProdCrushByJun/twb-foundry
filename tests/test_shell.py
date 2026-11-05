"""Dashboard shell (decisions/029): brand sidebar, app top bar with "Welcome, <name>", export buttons."""
import copy
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile

from lxml import etree

from tbuilder import design, design_lint, gate, shell
from tbuilder.build import build, build_file
from tbuilder.formula import CalcSet, FormulaError
from tbuilder.spec import SpecError, validate
from test_gate import repack
from test_roundtrip import OUT, SPECS

SPEC = json.loads((SPECS / "shell.json").read_text(encoding="utf-8"))
SIDEBAR = json.loads((SPECS / "layout_sidebar.json").read_text(encoding="utf-8"))


def mutate(fn, base=SPEC):
    spec = copy.deepcopy(base)
    fn(spec)
    return spec


def built(spec, name="shell_test"):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb")), z.namelist()


def shell_twbx():
    return build_file(SPECS / "shell.json", OUT / "shell_gate.twbx")


class Formula(unittest.TestCase):
    def test_fullname_is_a_constant_string(self):
        cs = CalcSet([{"name": "Who", "formula": "FULLNAME()"}], {"Sales": "real"}, [{"Sales": 1.0}])
        c = cs.calcs["Who"]
        self.assertEqual((c.datatype, c.is_agg), ("string", False))

    def test_fullname_takes_no_argument(self):
        with self.assertRaises(FormulaError):
            CalcSet([{"name": "Who", "formula": "FULLNAME([Sales])"}], {"Sales": "real"}, [])


class Contrast(unittest.TestCase):
    def test_wcag_ratios(self):
        self.assertAlmostEqual(shell.contrast("#ffffff", "#000000"), 21, places=1)
        self.assertAlmostEqual(shell.contrast("#ffffff", "#2f6f6a"), 5.9, delta=0.1)
        self.assertLess(shell.contrast("#ffffff", "#5f938f"), 4.5)  # ER's sidebar: too light for white text

    def test_text_color_picks_the_readable_one(self):
        self.assertEqual(shell.text_color({"color": "#221622"}), "#ffffff")
        self.assertEqual(shell.text_color({"color": "#f2c94c"}), "#333333")
        self.assertEqual(shell.text_color({"color": "#f2c94c", "text": "#000000"}), "#000000")


class Schema(unittest.TestCase):
    def test_spec_is_valid(self):
        validate(SPEC)

    def test_sidebar_true_still_valid(self):
        validate(SIDEBAR)

    def test_bad_values(self):
        for fn in (lambda s: s["dashboard"]["sidebar"].update(color="teal"),
                   lambda s: s["dashboard"]["sidebar"].update(download=["pdf", "pdf"]),
                   lambda s: s["dashboard"]["sidebar"].update(download=["xls"]),
                   lambda s: s["dashboard"]["sidebar"].update(logo={"text": "C", "image": "a.png"}),
                   lambda s: s["dashboard"]["sidebar"].pop("color"),
                   lambda s: s["dashboard"]["topbar"].pop("title")):
            with self.subTest(fn=fn), self.assertRaises(SpecError):
                validate(mutate(fn))


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.names = built(SPEC)
        cls.db = cls.root.find("dashboards/dashboard")

    def test_logo_packaged(self):
        self.assertIn("Image/logo.png", self.names)
        z = next(z for z in self.root.iter("zone") if z.get("type-v2") == "bitmap")
        self.assertEqual((z.get("param"), z.get("is-scaled")), ("Image/logo.png", "1"))

    def test_export_buttons_target_their_dashboard(self):
        own = self.db.find("simple-id").get("uuid")
        btns = [b for b in self.db.iter("button")]
        self.assertEqual([b.get("button-click-action-metadata") for b in btns], ["pdf", "powerpoint", "image"])
        for b in btns:
            self.assertIn(f'dashboarddoc-id="{own}"', b.find("export-button-action").text)
            self.assertEqual(b.get("button-type"), "text")
        self.assertEqual([b.find("button-visual-state/caption").text for b in btns], ["PDF", "PPT", "Image"])

    def test_export_buttons_stacked_at_the_sidebar_width(self):
        """decisions/167: one under another in the sidebar's flow, each fixed; in a row of three at 64px Desktop cut the
        captions to "P...", "Ima..."."""
        side = next(z for z in self.db.iter("zone") if z.get("param") == "vert" and z.get("is-fixed") == "true")
        zones = [z for z in side.findall("zone") if z.find("button[@button-click-action-metadata]") is not None]
        self.assertEqual(len(zones), 3)
        self.assertEqual({(z.get("x"), z.get("w")) for z in zones}, {(zones[0].get("x"), zones[0].get("w"))})
        filt = next(z for z in side.findall("zone") if z.get("type-v2") == "filter")
        self.assertEqual(zones[0].get("w"), filt.get("w"))  # the content width, as the filter cards
        ys = [int(z.get("y")) for z in zones]
        self.assertEqual([b - a for a, b in zip(ys, ys[1:])], [int(zones[0].get("h"))] * 2)
        for z in zones:
            self.assertEqual((z.get("is-fixed"), z.get("fixed-size")), ("true", str(design.BUTTON_PX)))

    def test_manifest_flags_in_desktop_order(self):
        flags = [e.tag for e in self.root.find("document-format-change-manifest")]
        for f in shell.BUTTON_FLAGS:
            self.assertIn(f, flags)
        self.assertEqual(flags, sorted(flags))

    def test_sidebar_on_the_brand_color_with_light_text(self):
        side = next(z for z in self.db.iter("zone") if z.get("fixed-size") == "240" and z.get("param") == "vert")
        style = {f.get("attr"): f.get("value") for f in side.findall("zone-style/format")}
        self.assertEqual(style["background-color"], "#2f6f6a")
        colors = {r.get("fontcolor") for z in side.iter("zone") if z.get("type-v2") == "text"
                  for r in z.iter("run") if r.text and r.text.strip() != "Æ"}
        self.assertEqual(colors, {"#ffffff"})

    def test_footer_at_the_bottom(self):
        side = next(z for z in self.db.iter("zone") if z.get("fixed-size") == "240" and z.get("param") == "vert")
        kids = side.findall("zone")
        footer = kids[-1]
        self.assertIn("Created by", "".join(r.text or "" for r in footer.iter("run")))
        self.assertEqual(kids[-2].get("type-v2"), "empty")
        pad = round(12 * 100000 / 800)
        self.assertEqual(int(footer.get("y")) + int(footer.get("h")), int(side.get("y")) + int(side.get("h")) - pad)

    def test_filter_titles_in_the_text_color(self):
        for name in ("Table", "Bar"):
            w = next(w for w in self.root.iter("worksheet") if w.get("name") == name)
            rule = w.find("table/style")[-1]
            self.assertEqual(rule.get("element"), "quick-filter-title")
            self.assertEqual(rule.find("format").get("value"), "#ffffff")

    def test_topbar_over_the_body(self):
        root_zone = self.db.find("zones/zone")
        bar, body = root_zone.findall("zone")
        self.assertEqual({f.get("attr"): f.get("value") for f in bar.findall("zone-style/format")}["background-color"],
                         "#221622")
        self.assertEqual((bar.get("x"), bar.get("w")), (body.get("x"), body.get("w")))
        self.assertEqual(int(bar.get("y")) + int(bar.get("h")), int(body.get("y")))
        self.assertIn("Welcome", [z.get("name") for z in bar.findall("zone")])

    def test_welcome_sheet(self):
        w = next(w for w in self.root.iter("worksheet") if w.get("name") == "Welcome")
        calc = next(c for c in self.root.iter("column") if c.get("caption") == "Full Name")
        self.assertEqual(calc.find("calculation").get("formula"), "FULLNAME()")
        runs = [r.text for r in w.iter("run")]
        self.assertEqual(runs[0], "Welcome, ")
        self.assertIn(calc.get("name")[1:-1], runs[1])
        table = next(r for r in w.find("table/style") if r.get("element") == "table")
        self.assertEqual(table.find("format").get("value"), "#221622")
        win = next(x for x in self.root.iter("window") if x.get("class") == "dashboard")
        self.assertIn("Welcome", [v.get("name") for v in win.iter("viewpoint")])

    def test_monogram_logo(self):
        root, names = built(mutate(lambda s: s["dashboard"]["sidebar"].update(logo={"text": "C calls."})), "mono")
        self.assertNotIn("Image/logo.png", names)
        self.assertNotIn("bitmap", [z.get("type-v2") for z in root.iter("zone")])
        runs = [r for r in root.iter("run") if r.text == "C calls."]
        self.assertEqual((runs[0].get("bold"), runs[0].get("fontsize")), ("true", "20"))

    def test_without_shell_no_flags_no_welcome(self):
        root, _ = built(SIDEBAR, "sidebar_plain")
        flags = [e.tag for e in root.find("document-format-change-manifest")]
        self.assertFalse(set(shell.BUTTON_FLAGS) & set(flags))
        self.assertNotIn("Welcome", [w.get("name") for w in root.iter("worksheet")])
        self.assertIsNone(next(root.iter("button"), None))


class Checks(unittest.TestCase):
    def assertFails(self, spec, text):
        with self.assertRaises(ValueError) as e:
            build(spec, OUT / "shell_bad.twbx", SPECS)
        self.assertIn(text, str(e.exception))

    def test_missing_logo_image(self):
        self.assertFails(mutate(lambda s: s["dashboard"]["sidebar"].update(logo={"image": "nope.png"})), "not found")

    def test_logo_not_a_picture(self):
        self.assertFails(mutate(lambda s: s["dashboard"]["sidebar"].update(logo={"image": "shell.json"})),
                         "not a picture")

    def test_legend_on_a_brand_sidebar(self):
        self.assertFails(mutate(lambda s: s["sheets"][1].update(color="Category")), "color legend")

    def test_colored_subtitle_words(self):
        self.assertFails(mutate(lambda s: s["dashboard"].update(subtitle="{accent:East} leads")), "colored words")

    def test_welcome_name_taken(self):
        self.assertFails(mutate(lambda s: s["sheets"][1].update(name="Welcome") or s["filters"][1].update(
            show_on="Welcome") or s["dashboard"]["grid"][0].__setitem__(1, "Welcome")), "Welcome")

    def test_filter_on_a_registry(self):
        def m(s):
            s["sheets"][3] = {"name": "Table", "type": "registry", "rows": ["Category"],
                              "columns": [{"measure": {"field": "Sales"}}]}
        self.assertFails(mutate(m), "registry")

    def test_sidebar_too_tall(self):
        self.assertFails(mutate(lambda s: s["dashboard"].update(height=500, row_heights=[2, 3])), "taller")


class GateCatchesShell(unittest.TestCase):
    """Mutations of the shell workbook: each break is named by the gate."""

    @classmethod
    def setUpClass(cls):
        cls.src = shell_twbx()

    def assertCaught(self, path, check, text):
        issues = gate.run(path)
        hits = [i for i in issues if i.check == check and text in str(i)]
        self.assertTrue(hits, f"expected [{check}] ~ '{text}', got: {[str(i) for i in issues]}")

    def test_generated_passes(self):
        self.assertEqual(gate.run(self.src), [])

    def test_export_button_without_target(self):
        def m(r):
            a = next(r.iter("export-button-action"))
            a.text = a.text.replace(a.text[a.text.index("{"):a.text.index("}") + 1],
                                    "{00000000-0000-0000-0000-000000000000}")
        self.assertCaught(repack(m, source=self.src), "buttons", "no target")

    def test_export_button_without_action(self):
        def m(r):
            b = next(r.iter("button"))
            b.remove(b.find("export-button-action"))
        self.assertCaught(repack(m, source=self.src), "buttons", "does nothing")

    def test_export_type_mismatch(self):
        def m(r):
            next(r.iter("button")).set("button-click-action-metadata", "image")
        self.assertCaught(repack(m, source=self.src), "buttons", "export type")

    def test_logo_not_packaged(self):
        self.assertCaught(repack(drop="Image/logo.png", source=self.src), "package", "Image/logo.png")

    def test_topbar_wider_than_the_dashboard(self):
        def m(r):
            bar = r.find("dashboards/dashboard/zones/zone").findall("zone")[0]
            bar.set("x", "0")
            bar.set("w", "100000")
        self.assertCaught(repack(m, source=self.src), "layout", "wider than the dashboard")


class Lint(unittest.TestCase):
    def rules(self, spec):
        return {(f.rule, f.level) for f in design_lint.lint(spec, SPECS)}

    def test_shell_spec_clean(self):
        self.assertFalse({r for r in self.rules(SPEC) if r[0] in ("C7", "C8")})

    def test_low_contrast(self):
        self.assertIn(("C8", "error"), self.rules(mutate(lambda s: s["dashboard"]["sidebar"].update(color="#5f938f"))))
        self.assertIn(("C8", "error"), self.rules(mutate(lambda s: s["dashboard"]["topbar"].update(text="#333333"))))

    def test_brand_looks_like_a_meaning_color(self):
        self.assertIn(("C7", "warn"), self.rules(mutate(lambda s: s["dashboard"]["topbar"].update(color="#3ea8a6",
                                                                                                    text="#000000"))))
