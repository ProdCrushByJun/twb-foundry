"""Decisions/128: an action by the date columns of a heatmap (date_level) filters by the period, as the sheet shows it."""
import copy
import json
import unittest
import zipfile
from urllib.parse import unquote

from lxml import etree

from tbuilder import gate
from tbuilder.build import build
from test_roundtrip import ROOT

CASE = ROOT / "acceptance" / "plotly"
SPEC = json.loads((CASE / "spec.json").read_text(encoding="utf-8"))
OUT = ROOT / "out" / "actions_heatmap_date_test.twbx"


def with_action(**extra):
    spec = copy.deepcopy(SPEC)
    act = {"source": "Exit Heatmap", "targets": ["Exits by Dept"], "fields": ["Department", "Event Date"]}
    spec["dashboard"]["actions"] = [{**act, **extra}]
    return spec


def built(spec):
    out = build(spec, OUT, CASE)
    with zipfile.ZipFile(out) as z:
        return etree.fromstring(z.read(out.stem + ".twb"))


class HeatmapDateAction(unittest.TestCase):
    def test_link_names_the_period_instance(self):
        root = built(with_action())
        expr = unquote(root.find("actions/action/link").get("expression"))
        self.assertIn("[tmn:Event Date:ok]", expr)
        self.assertNotIn("].[Event Date]", expr)
        self.assertIn("].[Department]", expr)

    def test_instance_declared_in_dependencies(self):
        root = built(with_action())
        ci = root.findall("actions/datasource-dependencies/column-instance[@name='[tmn:Event Date:ok]']")
        self.assertEqual(len(ci), 1)
        self.assertEqual((ci[0].get("column"), ci[0].get("derivation"), ci[0].get("type")),
                         ("[Event Date]", "Month-Trunc", "ordinal"))
        self.assertIsNotNone(root.find("actions/datasource-dependencies/column[@name='[Event Date]']"))

    def test_gate_clean(self):
        self.assertEqual(gate.check_actions(built(with_action())), [])

    def test_gate_rejects_undeclared_instance(self):
        root = built(with_action())
        for ci in root.findall("actions/datasource-dependencies/column-instance"):
            ci.getparent().remove(ci)
        self.assertTrue(any("not declared" in i.message for i in gate.check_actions(root)))

    def test_other_levels(self):
        for level, name in (("year", "[tyr:Event Date:ok]"), ("quarter", "[tqr:Event Date:ok]")):
            spec = with_action()
            next(s for s in spec["sheets"] if s["name"] == "Exit Heatmap")["date_level"] = level
            expr = unquote(built(spec).find("actions/action/link").get("expression"))
            self.assertIn(name, expr)


if __name__ == "__main__":
    unittest.main()
