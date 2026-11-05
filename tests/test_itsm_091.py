"""ITSM findings of decision 091: color tokens in fields.color, a donut's color.highlight, the measure label that hides
a repeating axis title, and the check of a vertical bar's column labels."""
import copy
import json
import unittest
import zipfile

from tbuilder import fields
from tbuilder.build import build
from tbuilder.design import COLOR
from test_dual_axis import spec, sheet
from test_roundtrip import OUT, ROOT


def twb_text(s):
    out = build(s, OUT / "itsm_091_test.twbx", ROOT / "specs")
    with zipfile.ZipFile(out) as z:
        return z.read(next(n for n in z.namelist() if n.endswith(".twb"))).decode("utf-8")


def donut_spec(**color):
    s = spec()
    if color:
        sheet(s, "Donut")["color"] = color
    return s


class Tokens(unittest.TestCase):
    def test_token_becomes_the_design_color(self):
        s = spec()
        s["fields"] = {"Category": {"color": {"Furniture": "bad", "Office": "good", "Tech": "#112233"}}}
        text = twb_text(s)
        for c in (COLOR["bad"], COLOR["good"], "#112233"):
            self.assertIn(c, text)

    def test_resolve_leaves_a_spec_without_tokens_alone(self):
        s = spec()
        self.assertIs(fields.resolve_tokens(s), s)

    def test_resolve_does_not_touch_the_given_spec(self):
        s = spec()
        s["fields"] = {"Category": {"color": {"Furniture": "warn"}}}
        before = copy.deepcopy(s)
        self.assertEqual(fields.resolve_tokens(s)["fields"]["Category"]["color"]["Furniture"], COLOR["warn"])
        self.assertEqual(s, before)


class DonutHighlight(unittest.TestCase):
    def test_highlighted_member_gets_the_accent_the_others_mute(self):
        text = twb_text(donut_spec(highlight=["Tech"]))
        self.assertIn(COLOR["accent"], text)
        self.assertIn(COLOR["mark_muted"], text)

    def test_unknown_member_is_refused(self):
        with self.assertRaisesRegex(ValueError, "not values of 'Category'"):
            twb_text(donut_spec(highlight=["Toys"]))

    def test_other_field_is_refused(self):
        with self.assertRaisesRegex(ValueError, "its own dimension"):
            twb_text(donut_spec(field="Region", highlight=["East"]))

    def test_both_ways_at_once_are_refused(self):
        s = donut_spec(highlight=["Tech"])
        s["fields"] = {"Category": {"color": {"Furniture": "bad"}}}
        with self.assertRaisesRegex(ValueError, "keep one"):
            twb_text(s)


class ColumnLabels(unittest.TestCase):
    def vertical(self, width):
        s = spec()
        s["sheets"].append({"name": "Cols", "type": "bar", "title": "Sales **by category**", "orientation": "vertical",
                            "dimension": "Category", "measure": {"field": "Sales"}})
        s["dashboard"]["grid"] = [["Cols", "Lollipop"]]
        s["dashboard"]["width"] = width
        return s

    def test_wide_enough_builds(self):
        twb_text(self.vertical(1400))

    def test_too_narrow_columns_are_refused(self):
        s = self.vertical(400)
        s["fields"] = {"Category": {"aliases": {"Furniture": "Furniture and fittings"}}}
        with self.assertRaisesRegex(ValueError, "Sheet 'Cols': the columns are .*'Furniture and fittings' needs"):
            twb_text(s)


class ItsmCase(unittest.TestCase):
    def test_itsm_spec_uses_the_tokens_and_the_highlight(self):
        s = json.loads((ROOT / "acceptance" / "itsm-incidents" / "spec.json").read_text(encoding="utf-8"))
        self.assertEqual(s["fields"]["Priority"]["color"]["1 - Critical"], "bad")
        self.assertNotIn("Channel", s["fields"])
        self.assertEqual(sheet(s, "Channel Mix")["color"], {"highlight": ["Portal"]})


if __name__ == "__main__":
    unittest.main()
