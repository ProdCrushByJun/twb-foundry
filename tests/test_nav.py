"""Several dashboards and the navigation between them (decisions/040)."""
import copy
import json
import re
import unittest
import xml.etree.ElementTree as ET
import zipfile

from tbuilder import design_lint, gate, nav
from tbuilder.build import build, build_file
from tbuilder.design import COLOR
from tbuilder.spec import SpecError, validate
from test_gate import repack
from test_roundtrip import OUT, SPECS

SPEC = json.loads((SPECS / "nav.json").read_text(encoding="utf-8"))
SIDE = json.loads((SPECS / "nav_sidebar.json").read_text(encoding="utf-8"))
GOTO = re.compile(r'^tabdoc:goto-sheet window-id="(\{[0-9A-F-]{36}\})"$')


def mutate(fn, base=SPEC):
    spec = copy.deepcopy(base)
    fn(spec)
    return spec


def built(spec, name="nav_test"):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def window_names(root):
    return {w.find("simple-id").get("uuid"): w.get("name") for w in root.find("windows")}


def buttons(db):
    """[(zone, target window uuid)] of the goto buttons of a dashboard, in zone order."""
    return [(z, GOTO.match(z.find("button").get("action")).group(1)) for z in db.iter("zone")
            if z.find("button") is not None and "goto-sheet" in z.find("button").get("action")]


def dash(root, name):
    return next(d for d in root.iter("dashboard") if d.get("name") == name)


class Schema(unittest.TestCase):
    def test_nav_specs_are_valid(self):
        validate(SPEC)
        validate(SIDE)

    def test_dashboard_or_dashboards(self):
        with self.assertRaises(SpecError):
            validate(mutate(lambda s: s.pop("dashboards")))
        with self.assertRaises(SpecError):  # not both
            validate(mutate(lambda s: s.update(dashboard=s["dashboards"][0])))

    def test_nav_style(self):
        with self.assertRaises(SpecError):
            validate(mutate(lambda s: s["nav"].update(style="menu")))


class Tabs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(SPEC, "nav_tabs")
        cls.wins = window_names(cls.root)

    def test_dashboards_in_name_order_windows_in_spec_order(self):
        self.assertEqual([d.get("name") for d in self.root.find("dashboards")], ["Details", "Overview", "Regions"])
        dw = [w for w in self.root.find("windows") if w.get("class") == "dashboard"]
        self.assertEqual([w.get("name") for w in dw], ["Overview", "Regions", "Details"])
        self.assertEqual([w.get("maximized") for w in dw], ["true", None, None])  # the first opens

    def test_every_dashboard_has_a_button_per_dashboard(self):
        for d in self.root.iter("dashboard"):
            got = [(z.find("button/button-visual-state/caption").text, self.wins[t]) for z, t in buttons(d)]
            self.assertEqual(got, [("Overview", "Overview"), ("Regions", "Regions"), ("Details", "Details")])

    def test_current_tab_bold_with_accent_line(self):
        for d in self.root.iter("dashboard"):
            for z, t in buttons(d):
                active = self.wins[t] == d.get("name")
                font = z.find("button/button-visual-state/button-caption-font-style")
                self.assertEqual(font.get("bold") == "true", active)
                self.assertEqual(font.get("fontcolor"), COLOR["text"] if active else COLOR["muted"])
                self.assertIsNone(font.get("fontsize"))  # Desktop 2025.1 drops it on Save As (decisions/061)
            lines =[z for z in d.iter("zone") if z.get("type-v2") == "empty"
                     and z.find("zone-style/format[@attr='background-color']") is not None]
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0].find("zone-style/format[@attr='background-color']").get("value"),
                             COLOR["accent"])

    def test_tab_row_above_the_header(self):
        d = dash(self.root, "Overview")
        top = d.find("zones/zone").findall("zone")
        self.assertEqual((top[0].get("type-v2"), top[0].get("param")), ("layout-flow", "horz"))
        self.assertIsNotNone(top[1].find("zone[@type-v2='text']"))  # the header row (title, filter) under the tabs
        self.assertLess(int(top[0].get("y")), int(top[1].get("y")))

    def test_button_flags(self):
        flags = [e.tag for e in self.root.find("document-format-change-manifest")]
        self.assertIn("BasicButtonObject", flags)
        self.assertIn("BasicButtonObjectTextSupport", flags)
        self.assertNotIn("DashboardExportButton", flags)
        self.assertEqual(flags.index("BasicButtonObject") + 1, flags.index("BasicButtonObjectTextSupport"))

    def test_filter_card_on_every_dashboard(self):
        owners = {}
        for d in self.root.iter("dashboard"):
            cards = [z.get("name") for z in d.iter("zone") if z.get("type-v2") == "filter"]
            self.assertEqual(len(cards), 1, d.get("name"))
            owners[d.get("name")] = cards[0]
        # show_on where it is; on Regions (without By Category) the first chart sheet there
        self.assertEqual(owners, {"Overview": "By Category", "Regions": "Trend", "Details": "By Category"})

    def test_actions_stay_on_their_dashboard(self):
        acts = self.root.find("actions").findall("action")
        self.assertEqual([(a.find("source").get("dashboard"), a.find("source").get("worksheet")) for a in acts],
                         [("Overview", "By Category"), ("Regions", "By Region")])
        targets = [a.find("command/param[@name='target']").get("value") for a in acts]
        self.assertEqual(targets, ["Overview", "Regions"])

    def test_shared_sheet_on_two_dashboards(self):
        on = {d.get("name"): {z.get("name") for z in d.iter("zone") if "type-v2" not in z.attrib}
              for d in self.root.iter("dashboard")}
        self.assertIn("Trend", on["Overview"] & on["Regions"])
        vps = {w.get("name"): [v.get("name") for v in w.iter("viewpoint")] for w in self.root.find("windows")
               if w.get("class") == "dashboard"}
        self.assertNotIn("KPI · Sales", vps["Regions"])
        self.assertIn("KPI · Sales", vps["Overview"])

    def test_gate_passes(self):
        out = build_file(SPECS / "nav.json", OUT / "nav_gate.twbx")
        self.assertEqual(gate.run(out), [])


class Sidebar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(SIDE, "nav_side")
        cls.wins = window_names(cls.root)

    def test_buttons_in_the_sidebar_current_on_white(self):
        brand = SIDE["dashboards"][0]["sidebar"]["color"]
        for d in self.root.iter("dashboard"):
            side = next(z for z in d.iter("zone") if z.find("zone-style/format[@attr='background-color']") is not None
                        and z.get("param") == "vert")
            got = buttons(side)
            self.assertEqual([self.wins[t] for _, t in got], ["Summary", "Breakdown"])
            for z, t in got:
                face = z.find("button/button-visual-state/format[@attr='background-color']").get("value")
                self.assertEqual(face, COLOR["button_bg"] if self.wins[t] == d.get("name") else brand)
            kids = side.findall("zone")
            first = kids.index(got[0][0])
            self.assertEqual(kids[first - 1].get("type-v2"), "text")  # under the logo / title

    def test_grey_sidebar(self):
        spec = mutate(lambda s: [d.update(sidebar=True) for d in s["dashboards"]], SIDE)
        root = built(spec, "nav_grey")
        for d in root.iter("dashboard"):
            faces = [z.find("button/button-visual-state/format").get("value") for z, _ in buttons(d)]
            self.assertEqual(sorted(faces), sorted([COLOR["button_bg"], COLOR["sidebar_bg"]]))


class Refusals(unittest.TestCase):
    def assertRefused(self, spec, text):
        with self.assertRaises(ValueError) as cm:
            build(spec, OUT / "nav_refused.twbx", SPECS)
        self.assertIn(text, str(cm.exception))

    def test_two_dashboards_one_name(self):
        self.assertRefused(mutate(lambda s: s["dashboards"][2].update(name="Overview")), "Two dashboards")

    def test_nav_item_unknown(self):
        self.assertRefused(mutate(lambda s: s["nav"].update(items=[{"dashboard": "Overview"},
                                                                   {"dashboard": "Nowhere"}])), "not a dashboard")

    def test_nav_misses_a_dashboard(self):
        self.assertRefused(mutate(lambda s: s["nav"].update(items=[{"dashboard": "Overview"},
                                                                   {"dashboard": "Regions"}])), "no nav button")

    def test_nav_needs_dashboards(self):
        spec = json.loads((SPECS / "actions.json").read_text(encoding="utf-8"))
        spec["nav"] = {"style": "tabs"}
        self.assertRefused(spec, "nav needs 'dashboards'")

    def test_shell_differs(self):
        self.assertRefused(mutate(lambda s: s["dashboards"][1].update(theme="flat")), "differ in 'theme'")

    def test_sidebar_style_needs_a_sidebar(self):
        self.assertRefused(mutate(lambda s: s["nav"].update(style="sidebar")), "give the dashboards a sidebar")

    def test_registry_on_two_dashboards(self):
        self.assertRefused(mutate(lambda s: s["dashboards"][2]["grid"].append(["By Region"])), "on one dashboard")

    def test_tabs_wider_than_the_dashboard(self):
        def m(s):
            s["nav"]["items"] = [{"dashboard": d["name"], "label": "A very long tab caption here"}
                                 for d in s["dashboards"]]
            for d in s["dashboards"]:
                d["width"] = 400
        self.assertRefused(mutate(m), "tabs of")


class Lint(unittest.TestCase):
    def test_each_dashboard_is_linted(self):
        spec = mutate(lambda s: s["dashboards"][1].pop("title"))
        found = design_lint.lint(spec, SPECS)
        self.assertTrue(any(f.rule == "T1" and "Regions" in f.where for f in found))
        self.assertEqual(len([f for f in found if f.rule == "K1"]), 1)  # a shared sheet's finding once


class Helpers(unittest.TestCase):
    def test_single_dashboard_is_unchanged(self):
        spec = {"dashboard": {"name": "D"}}
        self.assertIs(nav.primary(spec), spec)
        self.assertEqual(nav.dashboards(spec), [{"name": "D"}])
        self.assertEqual(nav.items(spec), [])

    def test_expected_and_reconcile_take_several_dashboards(self):
        from tbuilder import expected, html_outline, reconcile
        e = expected.compute(SPEC, SPECS / SPEC["datasource"]["path"])
        self.assertEqual(sorted(e), ["By Category", "By Region", "KPI", "Matrix", "Trend"])  # every dashboard's
        page = SPECS.parent / "tests" / "fixtures" / "sales_dashboard.html"
        r = reconcile.check(SPEC, SPECS, html_outline.outline(page))
        self.assertGreater(r["summary"]["matched"], 0)


class GateCatchesNav(unittest.TestCase):
    """Mutations of the tabs workbook: each break is named by the gate."""

    @classmethod
    def setUpClass(cls):
        cls.src = build_file(SPECS / "nav.json", OUT / "nav_mut.twbx")

    def assertCaught(self, path, check, text):
        issues = gate.run(path)
        hits = [i for i in issues if i.check == check and text in str(i)]
        self.assertTrue(hits, f"expected [{check}] ~ '{text}', got: {[str(i) for i in issues]}")

    @staticmethod
    def _buttons(r, name):
        db = next(d for d in r.iter("dashboard") if d.get("name") == name)
        return [b for b in db.iter("button") if "goto-sheet" in b.get("action")]

    def test_generated_passes(self):
        self.assertEqual(gate.run(self.src), [])

    def test_button_to_a_missing_dashboard(self):
        def m(r):
            self._buttons(r, "Overview")[1].set(
                "action", 'tabdoc:goto-sheet window-id="{00000000-0000-0000-0000-000000000000}"')
        self.assertCaught(repack(m, source=self.src), "navigation", "target is missing")

    def test_goto_not_in_desktop_form(self):
        def m(r):
            self._buttons(r, "Overview")[1].set("action", "tabdoc:goto-sheet sheet='Regions'")
        self.assertCaught(repack(m, source=self.src), "navigation", "not in Desktop's form")

    def test_two_dashboards_one_name(self):
        def m(r):
            next(d for d in r.iter("dashboard") if d.get("name") == "Details").set("name", "Overview")
            next(w for w in r.find("windows") if w.get("name") == "Details").set("name", "Overview")
        self.assertCaught(repack(m, source=self.src), "names", "duplicate dashboard name")

    def test_dashboard_without_way_back(self):
        def m(r):
            own = next(w for w in r.find("windows") if w.get("name") == "Details").find("simple-id").get("uuid")
            for b in self._buttons(r, "Details"):
                b.set("action", f'tabdoc:goto-sheet window-id="{own}"')
        self.assertCaught(repack(m, source=self.src), "navigation", "no way back")

    def test_current_button_not_bold(self):
        def m(r):
            font = self._buttons(r, "Regions")[1].find("button-visual-state/button-caption-font-style")
            del font.attrib["bold"]
        self.assertCaught(repack(m, source=self.src), "navigation", "only the current dashboard's button is bold")

    def test_accent_line_under_another_tab(self):
        def m(r):
            db = next(d for d in r.iter("dashboard") if d.get("name") == "Overview")
            lines = [z for z in db.iter("zone") if z.get("type-v2") == "empty"
                     and z.getparent().get("param") == "vert"]
            fmt = lines[0].find("zone-style/format[@attr='background-color']")
            lines[0].find("zone-style").remove(fmt)
            lines[1].find("zone-style").append(fmt)
        path = repack(m, source=self.src)
        self.assertCaught(path, "navigation", "tab of another dashboard")
        self.assertCaught(path, "navigation", "has no accent line")

    def test_line_color_not_the_token(self):
        def m(r):
            fmt = next(f for f in r.iter("format") if f.get("value") == COLOR["accent"]
                       and f.getparent().tag == "zone-style")
            fmt.set("value", "#ff0000")
        self.assertCaught(repack(m, source=self.src), "navigation", "not the accent token")


if __name__ == "__main__":
    unittest.main()
