"""Filter cards v2 (decisions/162): single value list (radiolist) and slider, wildcard match, Show Apply button, a
range filter on a measure; their XML as Desktop writes it, the numbers, the builder's refusals, gate mutations."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import expected, filters, gate
from tbuilder.build import build
from test_roundtrip import OUT, SPECS

USER = "{http://www.tableausoftware.com/xml/user}"


def load(name="filters_cards.json"):
    return json.loads((SPECS / name).read_text(encoding="utf-8"))


def built(spec, name):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return etree.fromstring(z.read(out.stem + ".twb")), out


def shared(root):
    return {f.get("column").split("].")[1]: f for f in next(root.iter("shared-view")).findall("filter")}


def card(root, inst):
    return next(z for z in root.iter("zone") if z.get("type-v2") == "filter" and z.get("param", "").endswith(inst))


def compute(spec):
    return expected.compute(spec, SPECS / spec["datasource"]["path"])


class Header(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, cls.path = built(load(), "filters_cards_xml")

    def test_gate_passes(self):
        self.assertEqual(gate.run(self.path, load()), [])

    def test_single_slider(self):
        """Reference 'Filter Modes' (2024.2): card mode slider, the filter one member."""
        self.assertEqual(card(self.root, "[none:Region:nk]").get("mode"), "slider")
        (g,) = list(shared(self.root)["[none:Region:nk]"])
        self.assertEqual((g.get("function"), g.get("member")), ("member", '"West"'))

    def test_wildcard(self):
        """A reference (2023.1): CONTAINS([City], 'o') over the (All) level-members, the card mode pattern."""
        self.assertEqual(card(self.root, "[none:City:nk]").get("mode"), "pattern")
        (g,) = list(shared(self.root)["[none:City:nk]"])
        self.assertEqual(dict(g.attrib), {"expression": "CONTAINS([City], 'o')", "function": "filter",
                                          f"{USER}ui-enumeration": "inclusive",
                                          f"{USER}ui-pattern-include-all-when-empty": "true",
                                          f"{USER}ui-pattern_text": "o", f"{USER}ui-pattern_type": "contains"})
        (lm,) = list(g)
        self.assertEqual((lm.get("function"), lm.get("level"), lm.get(f"{USER}ui-enumeration")),
                         ("level-members", "[none:City:nk]", "all"))

    def test_measure_range(self):
        """Global Superstore: the row-level [none:Sales:qk], in-range, real bounds; the card a range slider."""
        f = shared(self.root)["[none:Sales:qk]"]
        self.assertEqual((f.get("class"), f.get("included-values"), f.findtext("min"), f.findtext("max")),
                         ("quantitative", "in-range", "100.0", "400.0"))
        z = card(self.root, "[none:Sales:qk]")
        self.assertIsNone(z.get("mode"))
        self.assertEqual(z.get("fixed-size"), "242")

    def test_apply_button(self):
        """Enterprise Risk Dashboard (2025.1): show-apply on the multiple-values card."""
        self.assertEqual(card(self.root, "[none:Channel:nk]").get("show-apply"), "true")
        self.assertIsNone(card(self.root, "[none:Region:nk]").get("show-apply"))

    def test_numbers(self):
        """West, cities with an 'o' (Reno, Fresno; not Eugene), rows of 100..400, Online + Retail."""
        got = compute(load())
        self.assertEqual(sorted(got["By City"]), ["Fresno", "Reno"])
        self.assertAlmostEqual(got["KPI"]["SUM(Sales)"], 16571.45, places=2)

    def test_starts_with(self):
        spec = load()
        spec["filters"][1].update(pattern="Re", match="starts_with")
        self.assertEqual(sorted(compute(spec)["By City"]), ["Reno"])
        root, _ = built(spec, "filters_cards_starts")
        (g,) = list(shared(root)["[none:City:nk]"])
        self.assertEqual((g.get("expression"), g.get(f"{USER}ui-pattern_type")), ("STARTSWITH([City], 'Re')",
                                                                                  "starts-with"))

    def test_empty_wildcard_is_all(self):
        """No pattern: the card is empty, every city passes ((All) of decisions/021)."""
        spec = load()
        del spec["filters"][1]["pattern"]
        root, _ = built(spec, "filters_cards_empty")
        (g,) = list(shared(root)["[none:City:nk]"])
        self.assertEqual((g.get("function"), g.get(f"{USER}ui-enumeration")), ("level-members", "all"))
        self.assertEqual(sorted(compute(spec)["By City"]), ["Eugene", "Fresno", "Reno"])

    def test_slider_in_sidebar_is_taller(self):
        """A 60px sidebar card cuts the slider off under the value box; 80px shows it (Desktop 2025.1 snapshot)."""
        spec = load()
        spec["dashboard"].update(sidebar=True, width=1400, theme="flat")
        root, _ = built(spec, "filters_cards_sidebar")
        px = {inst: int(card(root, inst).get("h")) * 800 // 100000 for inst in ("[none:Region:nk]", "[none:City:nk]")}
        self.assertEqual(px, {"[none:Region:nk]": 80, "[none:City:nk]": 60})

    def test_null_rows(self):
        """A Null drops out of a wildcard pattern (CONTAINS(Null) is Null), stays in an empty wildcard ((All))."""
        self.assertFalse(filters.keeps(load()["filters"][1], ""))
        self.assertTrue(filters.keeps({"field": "City", "mode": "wildcard"}, ""))


class Panel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load("filters_cards_panel.json")
        cls.root, cls.path = built(cls.spec, "filters_cards_panel_xml")

    def test_gate_passes(self):
        self.assertEqual(gate.run(self.path, self.spec), [])

    def test_single_value_list(self):
        """radiolist in the right panel, a line per value and one for (All)."""
        z = card(self.root, "[none:Region:nk]")
        self.assertEqual(z.get("mode"), "radiolist")
        (g,) = list(shared(self.root)["[none:Region:nk]"])
        self.assertEqual(g.get("member"), '"East"')

    def test_list_with_apply(self):
        z = card(self.root, "[none:Channel:nk]")
        self.assertIsNone(z.get("mode"))
        self.assertEqual(z.get("show-apply"), "true")

    def test_numbers(self):
        self.assertEqual(sorted(compute(self.spec)["By City"]), ["Albany", "Boston", "Newark"])


class BuilderRefuses(unittest.TestCase):
    def refused(self, fn, text, name="filters_cards.json"):
        spec = load(name)
        fn(spec)
        with self.assertRaises(ValueError) as e:
            build(spec, OUT / "filters_cards_bad.twbx", SPECS)
        self.assertIn(text, str(e.exception))

    def test_apply_on_single_card(self):
        self.refused(lambda s: s["filters"][0].update(apply=True), "an Apply button is verified")

    def test_case_sensitive_pattern(self):
        """'a' with case keeps Albany, Fargo...; without it Austin too: Desktop's rule is not verified."""
        self.refused(lambda s: s["filters"][1].update(pattern="a"), "case does not matter")

    def test_pattern_matching_nothing(self):
        self.refused(lambda s: s["filters"][1].update(pattern="zz"), "matches no value")

    def test_quote_in_pattern(self):
        self.refused(lambda s: s["filters"][1].update(pattern="o'"), "not verified")

    def test_pattern_without_wildcard(self):
        self.refused(lambda s: s["filters"][3].update(pattern="On"), "applies to a wildcard card")

    def test_wildcard_with_default(self):
        self.refused(lambda s: s["filters"][1].update(default=["Reno"]), "not verified with a wildcard card")

    def test_wildcard_on_a_number(self):
        self.refused(lambda s: s["filters"][1].update(field="Profit"), "numeric fields as dimensions")

    def test_measure_range_upside_down(self):
        self.refused(lambda s: s["filters"][2].update(min=500, max=100), "above max")

    def test_measure_range_on_text(self):
        self.refused(lambda s: s["filters"][2].update(field="Channel"), "need a number column")

    def test_measure_range_with_default(self):
        self.refused(lambda s: s["filters"][2].update(default=["x"]), "not to a range measure filter")

    def test_context_measure_range(self):
        self.refused(lambda s: s["filters"][2].update(context=True), "context filter on a measure")

    def test_slider_with_two_values(self):
        self.refused(lambda s: s["filters"][0].update(default=["West", "East"]), "selects one value")

    def test_single_list_in_header(self):
        self.refused(lambda s: s["filters"][0].update(mode="single_list"), "needs a line per value")

    def test_slider_in_panel(self):
        self.refused(lambda s: s["filters"][0].update(mode="single_slider"), "right panel is not verified",
                     "filters_cards_panel.json")


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.path = built(load(), "filters_cards_gate")

    def mutant(self, fn):
        with zipfile.ZipFile(self.path) as src:
            members = {n: src.read(n) for n in src.namelist()}
        name = next(n for n in members if n.endswith(".twb"))
        root = etree.fromstring(members[name])
        fn(root, shared(root))
        members[name] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
        path = Path(tempfile.mkdtemp()) / "mutant.twbx"
        with zipfile.ZipFile(path, "w") as z:
            for n, b in members.items():
                z.writestr(n, b)
        return path

    def assertCaught(self, fn, text, spec=None):
        issues = [str(i) for i in gate.run(self.mutant(fn), spec) if i.check == "filters"]
        self.assertTrue(any(text in i for i in issues), f"expected [filters] ~ '{text}', got {issues}")

    def test_pattern_and_expression_disagree(self):
        """The card shows 'o', the sheets filter 'x'."""
        self.assertCaught(lambda r, f: f["[none:City:nk]"][0].set("expression", "CONTAINS([City], 'x')"),
                          "is not CONTAINS([City], 'o')")

    def test_unknown_pattern_type(self):
        self.assertCaught(lambda r, f: f["[none:City:nk]"][0].set(f"{USER}ui-pattern_type", "regex"),
                          "pattern type 'regex'")

    def test_pattern_without_its_level(self):
        def m(root, f):
            g = f["[none:City:nk]"][0]
            g.remove(g[0])
        self.assertCaught(m, "expected the (All) level-members")

    def test_pattern_on_a_dropdown_card(self):
        self.assertCaught(lambda r, f: card(r, "[none:City:nk]").set("mode", "checkdropdown"),
                          "only a wildcard card")

    def test_slider_with_two_values(self):
        def m(root, f):
            region = f["[none:Region:nk]"]
            region.remove(region[0])
            u = etree.SubElement(region, "groupfilter", {"function": "union", f"{USER}ui-domain": "database",
                                                         f"{USER}ui-enumeration": "inclusive",
                                                         f"{USER}ui-marker": "enumerate"})
            for v in ("West", "East"):
                etree.SubElement(u, "groupfilter", function="member", level="[none:Region:nk]", member=f'"{v}"')
        self.assertCaught(m, "single-value card (slider) shows one value")

    def test_apply_on_a_single_card(self):
        self.assertCaught(lambda r, f: card(r, "[none:Region:nk]").set("show-apply", "true"),
                          "show-apply='true' on a slider card")

    def test_measure_range_upside_down(self):
        def m(root, f):
            f["[none:Sales:qk]"].find("min").text = "500.0"
        self.assertCaught(m, "min 500.0 is above max 400.0")

    def test_measure_range_without_bound(self):
        def m(root, f):
            s = f["[none:Sales:qk]"]
            s.remove(s.find("max"))
        self.assertCaught(m, "with min and max")

    def test_measure_range_bound_changed(self):
        """A valid file keeping 100..300 where the spec asks for 100..400: only the spec check sees it."""
        def m(root, f):
            f["[none:Sales:qk]"].find("max").text = "300.0"
        self.assertEqual([i for i in gate.run(self.mutant(m)) if i.check == "filters"], [])
        self.assertCaught(m, "the spec asks for", load())

    def test_card_mode_lost(self):
        """The slider saved as a dropdown: one value either way, only the spec check sees it."""
        self.assertCaught(lambda r, f: card(r, "[none:Region:nk]").set("mode", "dropdown"),
                          "the spec asks for a single_slider card", load())

    def test_apply_lost(self):
        self.assertCaught(lambda r, f: card(r, "[none:Channel:nk]").attrib.pop("show-apply"),
                          "apply=True", load())

    def test_pattern_changed(self):
        """'Re' where the spec asks for 'o': a valid wildcard, the wrong one."""
        def m(root, f):
            g = f["[none:City:nk]"][0]
            g.set("expression", "CONTAINS([City], 'Re')")
            g.set(f"{USER}ui-pattern_text", "Re")
        self.assertEqual([i for i in gate.run(self.mutant(m)) if i.check == "filters"], [])
        self.assertCaught(m, "the workbook opens with match", load())


if __name__ == "__main__":
    unittest.main()
