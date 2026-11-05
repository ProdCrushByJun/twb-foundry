"""A profile from workbooks (decisions/194): tb copy-style counts tokens in the XML; the sheet background of a colored card."""
import collections
import glob
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest import mock

import yaml

from tbuilder import design, design_lint, profile_from, spec as spec_mod, user_profile
from tbuilder.build import build_file

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "golden" / "golden_theme_cards_2025_1.twbx"
HEATMAP = ROOT / "golden" / "golden_heatmap_v2_2025_1.twbx"


def twb(card="#ffffff", canvas="#f5f5f5", title_color="#111111", marks=("#123456",), extra="", size="18", padding="9"):
    """A small book with a title, two cards and one sheet."""
    maps = "".join(f"<map to='{c}'><bucket>x{i}</bucket></map>" for i, c in enumerate(marks))
    face = (f"<zone-style><format attr='border-style' value='solid'/><format attr='border-width' value='1'/>"
            f"<format attr='border-color' value='#abcdef'/><format attr='margin' value='5'/><format attr='padding' value='{padding}'/>"
            f"<format attr='background-color' value='{card}'/></zone-style>")
    return f"""<workbook source-build='2025.1.0'>
<worksheets><worksheet name='S'><table><style><style-rule element='mark'><encoding attr='color' field='[none:F:nk]' type='palette'>{maps}</encoding></style-rule></style>
<panes><pane><encodings><color column='[ds].[none:F:nk]'/></encodings></pane></panes><rows>[x]</rows><columns>[y]</columns></table></worksheet></worksheets>
<dashboards>
<dashboard name='One'><size maxheight='800' maxwidth='1000'/><style><style-rule element='table'><format attr='background-color' value='{canvas}'/></style-rule></style>
<zones><zone h='100000' type-v2='layout-basic' w='100000' x='0' y='0'>
<zone h='10000' type-v2='text' w='100000' x='0' y='0'><formatted-text><run bold='true' fontcolor='{title_color}' fontname='Arial' fontsize='{size}'>Title</run><run>Æ
</run><run fontcolor='#555555' fontsize='10'>Sub</run></formatted-text></zone>
<zone h='40000' type-v2='layout-flow' w='50000' x='0' y='10000'><zone h='30000' type-v2='text' w='40000' x='1' y='10000'><formatted-text><run bold='true' fontcolor='{title_color}' fontsize='13'>Block</run></formatted-text></zone><zone h='30000' name='S' w='40000' x='1' y='20000'/>{face}</zone>
<zone h='40000' type-v2='layout-flow' w='50000' x='50000' y='10000'>{face}</zone>
{extra}
</zone></zones></dashboard>
<dashboard name='Two'><zones><zone h='100000' type-v2='layout-basic' w='100000' x='0' y='0'/></zones></dashboard>
</dashboards></workbook>""".encode("utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def book(self, name="b.twb", **kw):
        path = self.tmp / name
        path.write_bytes(twb(**kw))
        return path

    def tokens(self, *books, dashboard=None):
        facts, notes, _ = profile_from.count(list(books), dashboard)
        return profile_from.choose(facts)[0], facts


class Counting(Base):
    def test_a_small_book(self):
        values, _ = self.tokens(self.book(), dashboard="One")
        c, f, s = (values["tokens"][g] for g in ("color", "font", "space"))
        self.assertEqual((c["canvas"], c["card_bg"], c["card_border"], c["text"], c["subtitle"]),
                         ("#f5f5f5", "#ffffff", "#abcdef", "#111111", "#555555"))
        self.assertEqual((f["dash_title"], f["dash_subtitle"], f["block_title"], f["family"]), (18, 10, 13, "Arial"))
        self.assertEqual((s["card_margin"], s["card_padding"]), (5, 9))
        self.assertEqual(values["theme"], "cards")

    def test_transparency_is_blended(self):
        self.assertEqual(profile_from._solid("#00000080"), "#7f7f7f")
        self.assertIsNone(profile_from._solid("#00000000"))

    def test_a_gap_of_empty_zones_counts(self):
        """A book parts cards with an empty zone, margin 0: half of what is seen between two cards is card_margin."""
        path = self.tmp / "gap.twb"
        path.write_bytes(twb().replace(b"w='50000' x='50000'", b"w='48000' x='52000'"))
        values, _ = self.tokens(path, dashboard="One")
        self.assertEqual(values["tokens"]["space"]["card_margin"], 15)  # 20 px between the zones + 5 + 5

    def test_a_dark_sidebar_is_not_a_card_and_its_text_no_fact(self):
        dark = ("<zone h='100000' type-v2='layout-flow' w='10000' x='0' y='0'><zone h='9000' type-v2='text' w='9000' x='0' y='0'>"
                "<formatted-text><run bold='true' fontcolor='#eeeeee' fontsize='12'>Nav</run></formatted-text></zone>"
                "<zone-style><format attr='background-color' value='#373c4d'/></zone-style></zone>")
        values, facts = self.tokens(self.book(extra=dark), dashboard="One")
        self.assertEqual(values["tokens"]["color"]["sidebar_bg"], "#373c4d")
        self.assertNotIn("#373c4d", facts["card_bg"])
        self.assertNotIn("#eeeeee", facts["text"])

    def test_good_and_bad_only_as_a_pair(self):
        values, _ = self.tokens(self.book(marks=("#d62728",)), dashboard="One")
        color = values["tokens"]["color"]
        self.assertEqual(color["accent"], "#d62728")  # a lone red may be a brand's accent
        self.assertNotIn("bad", color)
        values, _ = self.tokens(self.book(marks=("#2ca02c", "#d62728", "#123456")), dashboard="One")
        color = values["tokens"]["color"]
        self.assertEqual((color["good"], color["bad"], color["accent"]), ("#2ca02c", "#d62728", "#123456"))

    def test_scales_from_custom_palettes(self):
        values, _ = self.tokens(HEATMAP)
        color = values["tokens"]["color"]
        self.assertEqual((color["scale_low"], color["scale_mid"], color["good"], color["bad"]),
                         (design.COLOR["scale_low"], design.COLOR["scale_mid"], design.COLOR["good"], design.COLOR["bad"]))

    def test_a_scale_with_no_light_end_has_no_vote(self):
        """A real Preferences.tps: both ends dark, the light end of a scale would be #045a8d."""
        tps = self.tmp / "dark.tps"
        tps.write_text("<workbook><preferences><color-palette name='D' type='ordered-sequential'><color>#67001f</color>"
                       "<color>#053061</color></color-palette></preferences></workbook>", encoding="utf-8")
        values, _ = self.tokens(tps)
        self.assertNotIn("scale_low", values.get("tokens", {}).get("color", {}))

    def test_what_must_read_is_moved_to_the_floor(self):
        """Reference: #898989 on #f5f5f5, below the gate. The profile must not fail lint P2 for a book's taste."""
        facts, _, _ = profile_from.count([self.book(title_color="#999999")], "One")
        values, _, moved = profile_from.choose(facts)
        text = values["tokens"]["color"]["text"]
        self.assertGreaterEqual(profile_from.shell.contrast(text, "#ffffff"), design.MIN_CONTRAST)
        self.assertIn("#999999", moved[0])

    def test_a_font_without_metrics_is_noted_not_set(self):
        path = self.tmp / "f.twb"
        path.write_bytes(twb().replace(b"fontname='Arial'", b"fontname='Poppins'"))
        facts, notes, books = profile_from.count([path], "One")
        values, why, moved = profile_from.choose(facts)
        self.assertNotIn("family", values["tokens"]["font"])
        self.assertIn("font Poppins", profile_from.report(values, why, moved, facts, notes, books, {}))

    def test_the_title_keeps_above_its_subtitle(self):
        values, _ = self.tokens(self.book(size="9"), dashboard="One")
        self.assertNotIn("dash_subtitle", values["tokens"]["font"])


class SelfCheck(Base):
    """A golden gives back design.py: the tokens of the cards theme."""

    def test_the_card_goldens_give_design_py(self):
        books = sorted(glob.glob(str(ROOT / "golden" / "*.twbx")))
        cards = []
        for b in books:
            facts, _, _ = profile_from.count([b])
            if facts["theme"]["cards"]:
                cards.append(b)
        self.assertGreater(len(cards), 40)
        values, _ = self.tokens(*cards)
        want = {"color": design.COLOR, "font": {**design.FONT, **design.FONT_CARDS}, "space": design.SPACE}
        got = {f"{g}.{k}": v for g, kv in values["tokens"].items() for k, v in kv.items() if k != "family"}
        self.assertGreaterEqual(len(got), 17)
        for key, value in got.items():
            group, name = key.split(".")
            self.assertEqual(value, want[group][name], key)


class Input(Base):
    def test_twbx_twb_and_list(self):
        twbx = self.tmp / "b.twbx"
        with zipfile.ZipFile(twbx, "w") as z:
            z.writestr("b.twb", twb())
        self.assertEqual([d["name"] for d in profile_from.outline(twbx)], ["One", "Two"])
        self.assertEqual(profile_from.outline(twbx), profile_from.outline(self.book()))

    def test_preferences_tps_gives_palettes(self):
        tps = self.tmp / "Preferences.tps"
        tps.write_text("""<workbook><preferences>
<color-palette name='Brand' type='regular'><color>#111111</color><color>#aa2222</color><color>#22aa22</color><color>#2222aa</color><color>#aaaa22</color><color>#aa22aa</color></color-palette>
<color-palette name='Seq' type='ordered-sequential'><color>#eeeeee</color><color>#003366</color></color-palette>
<color-palette name='Div' type='ordered-diverging'><color>#cc0000</color><color>#dddddd</color><color>#00aa00</color></color-palette>
</preferences></workbook>""", encoding="utf-8")
        values, _ = self.tokens(tps)
        self.assertEqual(len(values["palettes"]["categorical"]), 5)
        color = values["tokens"]["color"]
        self.assertEqual((color["scale_low"], color["scale_mid"], color["good"], color["bad"]), ("#eeeeee", "#dddddd", "#00aa00", "#cc0000"))
        self.assertNotIn("canvas", color)
        result = profile_from.write(self.tmp / "p", [tps])
        raw = yaml.safe_load(Path(result["profile"]).read_text(encoding="utf-8"))
        self.assertNotIn("style_book", raw)
        self.assertEqual(raw["sources"], [{"kind": "file", "file": "refs/Preferences.tps"}])

    def test_refused_inputs(self):
        for bad, text in ((Path("https://public.tableau.com/views/x"), "downloaded first"), (self.tmp / "no.twbx", "no such file")):
            with self.assertRaisesRegex(profile_from.SourceError, text):
                profile_from.read(bad)
        junk = self.tmp / "junk.twbx"
        junk.write_bytes(b"not a zip")
        with self.assertRaisesRegex(profile_from.SourceError, "cannot read"):
            profile_from.read(junk)
        with self.assertRaisesRegex(profile_from.SourceError, "there are: 'One', 'Two'"):
            profile_from.count([self.book()], "Three")
        with self.assertRaisesRegex(profile_from.SourceError, "one dashboard of one book"):
            profile_from.count([self.book(), self.book("c.twb")], "One")


class Writing(Base):
    def test_style_book_with_its_dashboard_and_link(self):
        result = profile_from.write(self.tmp / "p", [self.book()], "One", meta={"url": "https://public.tableau.com/views/x"})
        raw = yaml.safe_load(Path(result["profile"]).read_text(encoding="utf-8"))
        self.assertEqual(raw["style_book"], {"kind": "public", "file": "refs/b.twb", "url": "https://public.tableau.com/views/x", "dashboard": "One"})
        self.assertTrue((self.tmp / "p" / "refs" / "b.twb").is_file())
        self.assertEqual(user_profile.problems(raw), [])
        self.assertIn("| color.card_border | `#abcdef` | 2 of 2 |", (self.tmp / "p" / "tokens.md").read_text(encoding="utf-8"))

    def test_server_book(self):
        result = profile_from.write(self.tmp / "p", [self.book()], "One", meta={"site": "acme", "workbook_id": "1-2"})
        raw = yaml.safe_load(Path(result["profile"]).read_text(encoding="utf-8"))
        self.assertEqual((raw["style_book"]["kind"], raw["style_book"]["site"]), ("server", "acme"))

    def test_several_books_are_sources(self):
        result = profile_from.write(self.tmp / "p", [self.book(), self.book("c.twb", card="#fafafa")])
        raw = yaml.safe_load(Path(result["profile"]).read_text(encoding="utf-8"))
        self.assertNotIn("style_book", raw)
        self.assertEqual([s["file"] for s in raw["sources"]], ["refs/b.twb", "refs/c.twb"])
        self.assertIn("#fafafa (2)", (self.tmp / "p" / "tokens.md").read_text(encoding="utf-8"))

    def test_the_users_own_keys_stay_and_set_corrects(self):
        out = self.tmp / "p"
        out.mkdir()
        (out / "profile.yaml").write_text(yaml.safe_dump({"profile_version": 1, "avoid": ["pie"], "context_dirs": ["C:/x"]}), encoding="utf-8")
        result = profile_from.write(out, [self.book(marks=("#2ca02c", "#d62728"))], "One")
        self.assertEqual(result["confirm"]["good"]["value"], "#2ca02c")
        profile_from.write(out, [], sets=["color.good=#00ff00", "font.block_title=15"])
        raw = yaml.safe_load((out / "profile.yaml").read_text(encoding="utf-8"))
        self.assertEqual(raw["avoid"], ["pie"])
        self.assertEqual((raw["tokens"]["color"]["good"], raw["tokens"]["font"]["block_title"], raw["tokens"]["color"]["canvas"]),
                         ("#00ff00", 15, "#f5f5f5"))
        self.assertIn("color.good = `#00ff00`", (out / "tokens.md").read_text(encoding="utf-8"))

    def test_brand_book_is_a_source(self):
        out = self.tmp / "p"
        profile_from.write(out, [], sets=["color.accent=#0055aa"], brandbook="context/brand.md")
        raw = yaml.safe_load((out / "profile.yaml").read_text(encoding="utf-8"))
        self.assertEqual(raw["sources"], [{"kind": "brandbook", "file": "context/brand.md"}])

    def test_a_bad_value_writes_nothing(self):
        out = self.tmp / "p"
        with self.assertRaisesRegex(profile_from.SourceError, "no such token"):
            profile_from.write(out, [self.book()], "One", sets=["color.nope=#000000"])
        self.assertFalse(out.exists())

    def test_cli(self):
        env = {**os.environ, "PYTHONUTF8": "1"}
        run = subprocess.run([sys.executable, "-m", "tbuilder", "copy-style", str(self.book()), "--list"], cwd=ROOT, env=env,
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('"One"', run.stdout)
        run = subprocess.run([sys.executable, "-m", "tbuilder", "copy-style", "https://public.tableau.com/x", "--out", str(self.tmp / "p")],
                             cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("downloaded first", run.stderr)


class Css(Base):
    def test_variables_follow_the_profile(self):
        root = self.tmp / "profiles"
        shutil.copytree(ROOT / "profiles" / "house", root / "house")
        (root / "a").mkdir()
        (root / "a" / "profile.yaml").write_text(yaml.safe_dump({"profile_version": 1, "tokens": {"color": {"accent": "#111111"}, "font": {"block_title": 15, "family": "Arial"}}}), encoding="utf-8")
        with mock.patch.object(user_profile, "ROOT", root):
            text = profile_from.css("a")
            house = profile_from.css("house")
        self.assertIn("--tb-color-accent: #111111;", text)
        self.assertIn("--tb-font-block-title: 15pt;", text)
        self.assertIn('--tb-font-family: "Arial"', text)
        self.assertIn("--tb-color-accent: #4e79a7;", house)
        self.assertIn("--tb-font-dash-title: 18pt;", house)
        self.assertIn("--tb-space-card-margin: 6px;", house)
        self.assertEqual(design.COLOR["accent"], "#4e79a7")  # put back


class Listing(Base):
    def test_lists_styles_not_the_template(self):
        root = self.tmp / "profiles"
        for name in ("house", "example"):
            shutil.copytree(ROOT / "profiles" / name, root / name)
        (root / "a").mkdir()
        (root / "a" / "profile.yaml").write_text(yaml.safe_dump({"profile_version": 1, "tokens": {"color": {"accent": "#111111"}}, "style_book": {"kind": "public", "url": "https://x/y", "dashboard": "Ads"}}), encoding="utf-8")
        (root / "bad").mkdir()
        (root / "bad" / "profile.yaml").write_text("profile_version: 1\nnope: 1\n", encoding="utf-8")
        with mock.patch.object(user_profile, "ROOT", root):
            lines = profile_from.listing()
        self.assertEqual([x.split(":")[0] for x in lines], ["a", "bad", "house"])
        self.assertIn("accent #111111", lines[0])
        self.assertIn("from https://x/y, dashboard Ads", lines[0])
        self.assertIn("broken", lines[1])
        self.assertIn("accent #4e79a7", lines[2])


class ColoredCard(Base):
    """A card that is not white shows through its sheets (decisions/194); a white one writes nothing."""

    def setUp(self):
        super().setUp()
        self.root = self.tmp / "profiles"
        shutil.copytree(ROOT / "profiles" / "house", self.root / "house")
        for p in (mock.patch.object(user_profile, "ROOT", self.root), mock.patch.object(user_profile, "forced", None), mock.patch.dict(os.environ)):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop(user_profile.ENV, None)

    def build(self, spec, **tokens):
        (self.root / "a").mkdir(exist_ok=True)
        (self.root / "a" / "profile.yaml").write_text(yaml.safe_dump({"profile_version": 1, "tokens": {"color": tokens}}), encoding="utf-8")
        user_profile.forced = "a"
        book = build_file(ROOT / "specs" / f"{spec}.json", self.tmp / f"{spec}.twbx")
        with zipfile.ZipFile(book) as z:
            return ET.fromstring(next(z.read(n) for n in z.namelist() if n.endswith(".twb")))

    @staticmethod
    def backgrounds(root):
        return [ws.get("name") for ws in root.iter("worksheet")
                if ws.find("table/style/style-rule[@element='table']/format[@attr='background-color'][@value='#00000000']") is not None]

    def test_every_sheet_of_a_colored_card_shows_it(self):
        root = self.build("registry_v2", card_bg="#e8f2fa")
        names = [ws.get("name") for ws in root.iter("worksheet")]
        self.assertEqual(self.backgrounds(root), names)
        for ws in root.iter("worksheet"):
            order = [r.get("element") for r in ws.find("table/style")]
            if "worksheet" in order:
                self.assertLess(order.index("table"), order.index("worksheet"))  # Desktop's order

    def test_the_manifest_flag_comes_with_it(self):
        """Found by --resave: Desktop adds it on save; without it the book is not what Desktop would write."""
        from tbuilder import gate
        root = self.build("registry_v2", card_bg="#e8f2fa")
        tags = [e.tag for e in root.find("document-format-change-manifest")]
        self.assertIn("WorksheetBackgroundTransparency", tags)
        self.assertEqual(tags, sorted(tags))
        self.assertEqual(gate.check_sheet_background(root), [])
        manifest = root.find("document-format-change-manifest")
        manifest.remove(manifest.find("WorksheetBackgroundTransparency"))
        self.assertTrue(gate.check_sheet_background(root))
        self.assertIsNone(self.build("registry_v2", accent="#8a3ffc").find("document-format-change-manifest/WorksheetBackgroundTransparency"))

    def test_a_reference_line_label_is_on_the_face(self):
        """Seen on the snapshot: a transparent sheet draws 'Average 13,222' in the canvas color, a patch on the card."""
        root = self.build("benchmark", card_bg="#e8f2fa")
        rules = [r for ws in root.iter("worksheet") for r in ws.findall("table/style/style-rule[@element='refline']")]
        self.assertTrue(rules)
        for rule in rules:
            ids = {f.get("id") for f in rule.findall("format")}
            faces = {f.get("id") for f in rule.findall("format") if f.get("attr") == "background-color" and f.get("value") == "#e8f2fa"}
            self.assertEqual(faces, ids)

    def test_a_registry_text_cell_is_the_face(self):
        (self.root / "a").mkdir(exist_ok=True)
        (self.root / "a" / "profile.yaml").write_text(yaml.safe_dump({"profile_version": 1, "tokens": {"color": {"card_bg": "#e8f2fa"}}}), encoding="utf-8")
        self.assertEqual(user_profile.load("a")["tokens"]["color"]["cell_text"], "#e8f2fa")
        marks = [f.get("value") for f in self.build("registry_v2", card_bg="#e8f2fa").iter("format") if f.get("attr") == "mark-color"]
        self.assertIn("#e8f2fa", marks)
        self.assertNotIn("#ffffff", marks)

    def test_a_white_card_writes_nothing(self):
        self.assertEqual(self.backgrounds(self.build("registry_v2", accent="#8a3ffc")), [])

    def test_the_flat_theme_writes_nothing(self):
        self.assertEqual(self.backgrounds(self.build("layout_sidebar", card_bg="#e8f2fa")), [])

    def test_lint_no_longer_warns_of_patches(self):
        (self.root / "a").mkdir(exist_ok=True)
        (self.root / "a" / "profile.yaml").write_text(yaml.safe_dump({"profile_version": 1, "tokens": {"color": {"card_bg": "#fffdf8"}}}), encoding="utf-8")
        user_profile.forced = "a"
        path = ROOT / "specs" / "benchmark.json"
        found = design_lint.lint(spec_mod.load(path), path.parent)
        self.assertFalse([f for f in found if "white patches" in f.text])


class DarkSidebar(ColoredCard):
    def test_c8_catches_text_on_a_dark_sidebar(self):
        """A reference's sidebar #373c4d: the grey sidebar's text is not chosen, unlike a brand sidebar's."""
        (self.root / "a").mkdir(exist_ok=True)
        (self.root / "a" / "profile.yaml").write_text(yaml.safe_dump({"profile_version": 1, "tokens": {"color": {"sidebar_bg": "#373c4d"}}}), encoding="utf-8")
        user_profile.forced = "a"
        path = ROOT / "specs" / "layout_sidebar.json"
        found = [f for f in design_lint.lint(spec_mod.load(path), path.parent) if f.rule == "C8"]
        self.assertEqual([f.level for f in found], ["error"])
        self.assertIn("sidebar_bg #373c4d", found[0].text)


class FloatingBook(Base):
    """A book with floating blocks has cards with no padding: inner >= outer is the gate, so the value moves, and says so."""

    def setUp(self):
        super().setUp()
        self.root = self.tmp / "profiles"
        shutil.copytree(ROOT / "profiles" / "house", self.root / "house")
        for p in (mock.patch.object(user_profile, "ROOT", self.root), mock.patch.object(user_profile, "forced", None), mock.patch.dict(os.environ)):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop(user_profile.ENV, None)

    def test_padding_moves_to_the_floor(self):
        values, _, moved = profile_from.choose(profile_from.count([self.book(padding="0")], "One")[0])
        self.assertEqual(values["tokens"]["space"]["card_padding"], 5)
        self.assertTrue(any("card_padding: 0 in the books, 5 here" in m for m in moved), moved)

    def test_a_token_with_no_fact_is_under_the_floor_too(self):
        """Margin 20 from the book: the house KPI padding would be under it, and no card in the book says otherwise."""
        facts = profile_from.count([self.book(padding="30")], "One")[0]
        facts["card_margin"].clear()
        facts["card_margin"][20] = 1
        values, _, moved = profile_from.choose(facts)
        self.assertEqual(values["tokens"]["space"]["card_padding_kpi"], 20)
        self.assertEqual(values["tokens"]["space"]["card_padding"], 30)  # above the floor: stays
        self.assertTrue(any("card_padding_kpi: 12 by default" in m for m in moved), moved)

    def test_no_card_no_floor(self):
        self.assertEqual(profile_from.choose(collections.defaultdict(collections.Counter))[2], [])

    def test_the_user_sees_it_and_the_book_builds(self):
        result = profile_from.write(self.root / "v", [self.book(padding="0")], "One")
        self.assertTrue(any("card_padding" in m for m in result["moved"]), result)
        self.assertIn("card_padding: 0 in the books", (self.root / "v" / "tokens.md").read_text(encoding="utf-8"))
        user_profile.forced = "v"
        self.assertTrue(build_file(ROOT / "specs" / "registry_v2.json", self.tmp / "v.twbx").is_file())


class NoFile(Base):
    """A path that is not there refuses at once: Desktop would open an empty Book1 and wait out its timeout."""

    def test_check_desktop_and_resave_refuse_before_tableau(self):
        from tbuilder import desktop_check, resave
        book = self.book("real.twbx")
        for main, args in ((desktop_check.main, []), (resave.main, ["--no-sheets", "-d", str(self.tmp)])):
            with mock.patch.object(desktop_check, "find_tableau") as find, mock.patch.object(desktop_check, "check") as check, \
                    mock.patch.object(resave, "resave") as save, mock.patch("sys.stderr", new_callable=io.StringIO) as err:
                self.assertEqual(main([str(book), str(self.tmp / "gone.twbx")] + args), 2)
            self.assertIn("no such file", err.getvalue())
            self.assertIn("gone.twbx", err.getvalue())
            self.assertNotIn("real.twbx", err.getvalue())
            find.assert_not_called()
            check.assert_not_called()
            save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
