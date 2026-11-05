"""Signed numbers and percentage points (decisions/124): format strings, render, parse, HTML inference, the form
check of reconcile and the page's text of a number ("+92", "+3.2 pp", "−1.1 pp")."""
import json
import unittest

from tbuilder import formats, reconcile
from tbuilder.formats import FormatError
from test_roundtrip import ROOT

PLUS = {"type": "number", "plus": True}
PP = {"type": "number", "decimals": 1, "plus": True, "suffix": "pp"}


class Strings(unittest.TestCase):
    def test_tableau_strings(self):
        self.assertEqual(formats.tableau(PLUS), 'n"+"#,##0;-#,##0')
        self.assertEqual(formats.tableau(PP), 'n"+"#,##0.0" pp";-#,##0.0" pp"')
        self.assertEqual(formats.tableau({"type": "number", "decimals": 1, "suffix": "pp"}),
                         'n#,##0.0" pp";-#,##0.0" pp"')
        self.assertEqual(formats.tableau("number"), "n#,##0;-#,##0")  # unchanged

    def test_parse_roundtrip(self):
        for f in (PLUS, PP, {"type": "number", "suffix": "pp", "negative": "parentheses"}):
            self.assertEqual(formats.parse(formats.tableau(f)), formats.normalize(f))

    def test_refused(self):
        for bad in ({"type": "currency", "plus": True}, {"type": "currency", "suffix": "pp"},
                    {"type": "number", "suffix": "bp"}, {"type": "number", "plus": "yes"}):
            with self.assertRaises(FormatError):
                formats.normalize(bad)
        with self.assertRaises(FormatError):
            formats.parse('n"-"#,##0;-#,##0')

    def test_render(self):
        self.assertEqual(formats.render(92, PLUS, "en_US"), "+92")
        self.assertEqual(formats.render(-5, PLUS, "en_US"), "-5")
        self.assertEqual(formats.render(3.2, PP, "en_US"), "+3.2 pp")
        self.assertEqual(formats.render(-1.1, PP, "en_US"), "-1.1 pp")
        self.assertEqual(formats.render(1.6, PP, "ru_RU"), "+1,6 pp")


class Reconcile(unittest.TestCase):
    def test_infer(self):
        self.assertEqual(formats.infer("+92"), {"type": "number", "decimals": 0, "units": "none", "plus": True})
        self.assertEqual(formats.infer("+3.2 pp")["suffix"], "pp")
        self.assertEqual(formats.infer("−1.1 pp"), {"type": "number", "decimals": 1, "units": "none",
                                                    "suffix": "pp", "negative": "minus"})

    def test_same_form(self):
        self.assertTrue(formats.same_form("+3.2 pp", PP))
        self.assertTrue(formats.same_form("−1.1 pp", PP))  # a negative cannot show the plus
        self.assertFalse(formats.same_form("+3.2 pp", {"type": "number", "decimals": 1}))  # unit and plus lost
        self.assertFalse(formats.same_form("+92", "number"))
        self.assertFalse(formats.same_form("92", PLUS))
        self.assertTrue(formats.same_form("+92", PLUS))

    def test_shown_keeps_plus(self):
        text = "Net +92"
        tok = "92"
        self.assertEqual(reconcile._shown(text, text.index(tok), tok), "+92")
        text = "▲ +1.6 pp vs Nov"
        self.assertEqual(reconcile._shown(text, text.index("1.6"), "1.6 pp"), "+1.6 pp")
        text = "a + 5"
        self.assertEqual(reconcile._shown(text, 4, "5"), "5")  # an operator, not a sign

    def test_plus_not_failing_in_acceptance_specs(self):
        """The acceptance specs carry the signed formats, so the form check has nothing to flag."""
        for case, field in (("plotly", "Net Change"), ("table_kpi", "Margin Change pp")):
            spec = json.loads((ROOT / "acceptance" / case / "spec.json").read_text(encoding="utf-8"))
            fmt = next(c["format"] for c in spec["calcs"] if c["name"] == field)
            self.assertTrue(formats.normalize(fmt)["plus"], case)


if __name__ == "__main__":
    unittest.main()
