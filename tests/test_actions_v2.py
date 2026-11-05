"""Actions v2 (decisions/160): highlight, URL, parameter action by a click on a mark with a value on clearing, the
Show/Hide button of the header's filter cards. Spec checks, the XML of the references / Desktop, gate mutations."""
import copy
import json
import unittest
import zipfile

from lxml import etree

from tbuilder import gate
from tbuilder.build import build
from tbuilder.spec import SpecError, validate
from test_roundtrip import ROOT, SPECS

SPEC = json.loads((SPECS / "actions_v2.json").read_text(encoding="utf-8"))
OUT = ROOT / "out" / "actions_v2_test.twbx"
_BUILT = {}


def built(spec=None, out=OUT):
    if spec is None and "golden" in _BUILT:
        return copy.deepcopy(_BUILT["golden"])
    out = build(spec or SPEC, out, SPECS)
    with zipfile.ZipFile(out) as z:
        root = etree.fromstring(z.read(out.stem + ".twb"))
    if spec is None:
        _BUILT["golden"] = copy.deepcopy(root)
    return root


def mutate(fn):
    spec = copy.deepcopy(SPEC)
    fn(spec)
    return spec


def acts(spec):
    return spec["dashboard"]["actions"]


def action(root, source, tag="action", brush=None):
    for a in root.iter(tag):
        if a.find("source").get("worksheet") == source:
            cmd = a.find("command")
            if brush is None or (cmd is not None and cmd.get("command") == "tsc:brush") == brush:
                return a
    raise AssertionError(f"no {tag} from {source}")


def issues(root):
    return [i for i in gate.check_actions_v2(root) + gate.check_actions(root) + gate.check_interactivity(root)]


class Schema(unittest.TestCase):
    def test_valid(self):
        validate(SPEC)

    def test_rejected(self):
        for bad in [{"type": "url", "source": "Trend"},  # no url
                    {"type": "url", "source": "Trend", "url": "ftp://x"},
                    {"type": "url", "source": "Trend", "url": "https://x", "on": "hover"},
                    {"type": "url", "source": "Trend", "url": "https://x", "targets": ["KPI"]},
                    {"type": "parameter", "source": "By Region", "field": "Region"},  # no parameter
                    {"type": "parameter", "source": "By Region", "field": "Region", "parameter": "P", "on": "hover"},
                    {"type": "highlight", "source": "Trend", "clear": "exclude"},
                    {"type": "highlight", "source": "Trend", "on": "menu"},
                    {"source": "Trend", "on": "menu"}, {"source": "Trend", "clear": "keep"},
                    {"source": "Trend", "url": "https://x"}, {"source": "Trend", "parameter": "Region pick"},
                    {"type": "zoom", "source": "Trend"}]:
            with self.subTest(bad=bad), self.assertRaises(SpecError):
                validate(mutate(lambda s: acts(s).append(bad)))
        with self.assertRaises(SpecError):
            validate(mutate(lambda s: s["dashboard"].update(filter_toggle="open")))


class Checks(unittest.TestCase):
    def assertRejected(self, fn, text):
        with self.assertRaises(ValueError) as cm:
            built(mutate(fn))
        self.assertIn(text, str(cm.exception))

    def test_parameter_not_declared(self):
        self.assertRejected(lambda s: acts(s)[0].update(parameter="Nope"), "parameter 'Nope' is not declared")

    def test_parameter_misses_members(self):
        self.assertRejected(lambda s: s["parameters"][0].update(values=["All", "East", "West"]),
                            "values ['North', 'South'] of 'Region'")

    def test_parameter_clear_not_a_value(self):
        self.assertRejected(lambda s: acts(s)[0].update(clear="Any"), "clear value 'Any'")

    def test_parameter_field_not_on_marks(self):
        self.assertRejected(lambda s: acts(s)[0].update(field="Category"), "'Category' is not a dimension")

    def test_parameter_by_period(self):
        self.assertRejected(lambda s: acts(s)[0].update(source="By Month", field="Order Date"), "as periods")

    def test_url_field_not_on_marks(self):
        self.assertRejected(lambda s: acts(s)[2].update(url="https://x.org/<Region>"), "'Region' is not a dimension")

    def test_highlight_target_off_dashboard(self):
        self.assertRejected(lambda s: acts(s)[3].update(targets=["Nope"]), "target 'Nope' is not on the dashboard")

    def test_toggle_without_header_cards(self):
        self.assertRejected(lambda s: s.pop("filters"), "filter_toggle")


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built()

    def test_highlight_selected_and_period_fields(self):
        a = action(self.root, "By Category", brush=True)
        self.assertEqual(a.find("activation").get("type"), "on-hover")
        ps = {p.get("name"): p.get("value") for p in a.findall("command/param")}
        self.assertEqual(ps, {"field-captions": "Category", "target": "Actions v2"})
        ps = {p.get("name"): p.get("value") for p in action(self.root, "By Month").findall("command/param")}
        self.assertEqual(ps["field-captions"], "MONTH(Order Date)")
        self.assertIsNone(action(self.root, "By Month").find("link"))

    def test_url_on_menu(self):
        a = action(self.root, "By Category", brush=False)
        self.assertIsNone(a.find("activation"))  # menu: no activation (RWFD Call Center)
        self.assertIsNone(a.find("command"))
        self.assertEqual(a.find("link").get("expression"), "https://www.google.com/search?q=<[Category]>")
        self.assertEqual(len(a.find("link")), 0)  # no url-action-type: Desktop 2025.1 refuses it

    def test_parameter_action(self):
        a = action(self.root, "By Region", "edit-parameter-action")
        self.assertEqual(a.find("clear-option").attrib, {"type": "assign-fixed-value", "value": "s:LROOT:All"})
        ps = {p.get("name"): p.get("value") for p in a.iter("param")}
        self.assertTrue(ps["source-field"].endswith(".[none:Region:nk]"))
        self.assertEqual(ps["target-parameter"], "[Parameters].[Parameter 1]")
        names = [e.get("name") for e in self.root.find("actions") if e.tag == "edit-parameter-action"]
        self.assertEqual(names, sorted(names))
        tags = [e.tag for e in self.root.find("actions")]
        self.assertEqual(tags[-1], "edit-parameter-action")

    def test_parameter_keeps_value_without_clear(self):
        root = built(mutate(lambda s: acts(s)[0].pop("clear")))
        a = action(root, "By Region", "edit-parameter-action")
        self.assertEqual(a.find("clear-option").get("type"), "do-nothing")

    def test_hints(self):
        text = etree.tostring(self.root, encoding="unicode")
        self.assertIn("Sales and profit | Click to select", text)
        self.assertIn("Sum of sales | Hover to highlight | Click for the link", text)

    def test_toggle_button(self):
        z = next(z for z in self.root.iter("zone") if z.find("button/toggle-action") is not None)
        m = gate.TOGGLE.fullmatch(z.findtext("button/toggle-action"))
        self.assertEqual(m.group(2), z.get("id"))
        holder = next(c for c in self.root.iter("zone") if c.get("id") == m.group(3))
        self.assertEqual({c.get("type-v2") for c in holder if c.tag == "zone"}, {"filter"})
        self.assertEqual([s.findtext("caption") for s in z.iter("button-visual-state")], ["Hide filters", "Show filters"])
        flags = {e.tag for e in self.root.find("document-format-change-manifest")}
        self.assertLessEqual({"CollapsiblePane", "BasicButtonObject", "ParameterAction",
                              "ParameterActionClearSelection"}, flags)

    def test_toggle_hidden_at_open(self):
        root = built(mutate(lambda s: s["dashboard"].update(filter_toggle="hidden")))
        z = next(z for z in root.iter("zone") if z.find("button/toggle-action") is not None)
        self.assertEqual(z.find("button").get("active-visual-state-index"), "1")
        holder = next(c for c in root.iter("zone") if c.get("id") == gate.TOGGLE.fullmatch(
            z.findtext("button/toggle-action")).group(3))
        self.assertTrue(all(c.get("hidden-by-user") == "true" for c in holder.iter("zone")))
        self.assertEqual(issues(root), [])

    def test_gate_clean(self):
        self.assertEqual([i for c in gate.CHECKS for i in c(self.root)], [])


class GateCatches(unittest.TestCase):
    """Each mutation breaks the built book by one feature; the gate must name it."""

    def setUp(self):
        self.root = built()

    def assertCaught(self, text):
        found = [i.message for i in issues(self.root)]
        self.assertTrue(any(text in m for m in found), found)

    def test_highlight_unknown_field(self):
        p = action(self.root, "By Category", brush=True).find("command/param[@name='field-captions']")
        p.set("value", "Segment")
        self.assertCaught("highlight field 'Segment'")

    def test_highlight_no_fields(self):
        cmd = action(self.root, "By Category", brush=True).find("command")
        cmd.remove(cmd.find("param[@name='field-captions']"))
        self.assertCaught("neither field-captions nor all fields")

    def test_url_unknown_field(self):
        link = action(self.root, "By Category", brush=False).find("link")
        link.set("expression", "https://x.org/<[Segment]>")
        self.assertCaught("URL field [Segment]")

    def test_url_scheme(self):
        action(self.root, "By Category", brush=False).find("link").set("expression", "javascript:alert(1)")
        self.assertCaught("is not http(s)")

    def test_url_source_off_dashboard(self):
        action(self.root, "By Category", brush=False).find("source").set("worksheet", "Nope")
        self.assertCaught("source sheet 'Nope'")

    def test_clear_value_not_a_member(self):
        action(self.root, "By Region", "edit-parameter-action").find("clear-option").set("value", "s:LROOT:Any")
        self.assertCaught("clears to 'Any'")

    def test_clear_value_not_a_string(self):
        action(self.root, "By Region", "edit-parameter-action").find("clear-option").set("value", "i:0")
        self.assertCaught("is not a string value")

    def _toggle(self):
        return next(z for z in self.root.iter("zone") if z.find("button/toggle-action") is not None)

    def _set(self, **kw):
        t = self._toggle().find("button/toggle-action")
        m = gate.TOGGLE.fullmatch(t.text)
        window, own, ids = kw.get("window", m.group(1)), kw.get("own", m.group(2)), kw.get("ids", m.group(3))
        t.text = f'tabdoc:toggle-button-click-action window-id="{window}" zone-id="{own}" zone-ids=[{ids}]'

    def test_toggle_wrong_window(self):
        self._set(window="{00000000-0000-0000-0000-000000000000}")
        self.assertCaught("is not the simple-id of the dashboard's window")

    def test_toggle_wrong_own_zone(self):
        self._set(own="9999")
        self.assertCaught("is not the button's own zone")

    def test_toggle_missing_zone(self):
        self._set(ids="9999")
        self.assertCaught("toggled zone 9999 is not on the dashboard")

    def test_toggle_hides_itself(self):
        root_zone = next(self.root.iter("dashboard")).find("zones/zone")
        self._set(ids=root_zone.get("id"))
        self.assertCaught("holds the button")

    def test_toggle_state_disagrees(self):
        self._toggle().find("button").set("active-visual-state-index", "1")
        self.assertCaught("visual state 1 but zone")

    def test_toggle_flag(self):
        m = self.root.find("document-format-change-manifest")
        m.remove(m.find("CollapsiblePane"))
        self.assertCaught("without the CollapsiblePane flag")


if __name__ == "__main__":
    unittest.main()
