"""Number formats (decisions/032): format strings as Desktop writes them, render, HTML inference, spec checks,
gate mutations, reconcile of the form."""
import copy
import json
import unittest

from tbuilder import formats, gate, reconcile
from tbuilder.build import build
from tbuilder.formats import FormatError
from test_actions import repack
from test_roundtrip import ROOT, SPECS

SPEC = json.loads((SPECS / "formats.json").read_text(encoding="utf-8"))
GOLDEN_TWBX = ROOT / "golden" / "golden_formats_2025_1.twbx"
OUT = ROOT / "out" / "formats_test.twbx"


def mutate(fn):
    spec = copy.deepcopy(SPEC)
    fn(spec)
    return spec


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


class TableauStrings(unittest.TestCase):
    def test_desktop_forms(self):
        """Strings found in Desktop-saved reference workbooks (Format -> Numbers dialog)."""
        cases = {
            "percent": "p0.0%", "pct0": "p0%", "pct2": "p0.00%",
            "number": "n#,##0;-#,##0", "number1": "n#,##0.0;-#,##0.0",
            "number_k": "n#,##0,.0K;-#,##0,.0K", "number_m": "n#,##0,,.0M;-#,##0,,.0M",
            "currency": 'c"$"#,##0;-"$"#,##0', "currency_k": 'c"$"#,##0,.0K;-"$"#,##0,.0K',
        }
        for preset, want in cases.items():
            self.assertEqual(formats.tableau(preset), want, preset)
        self.assertEqual(formats.tableau({"type": "number", "negative": "parentheses"}), "n#,##0;(#,##0)")
        self.assertEqual(formats.tableau({"type": "number", "units": "K"}), "n#,##0,K;-#,##0,K")
        self.assertEqual(formats.tableau({"type": "currency", "negative": "parentheses"}), 'c"$"#,##0;("$"#,##0)')
        self.assertEqual(formats.tableau({"type": "currency", "symbol": "£", "units": "M", "decimals": 2}),
                         'c"£"#,##0,,.00M;-"£"#,##0,,.00M')

    def test_parse_inverts(self):
        for preset in formats.PRESETS:
            self.assertEqual(formats.parse(formats.tableau(preset)), formats.normalize(preset), preset)
        for f in ({"type": "currency", "symbol": "₽", "decimals": 2}, {"type": "number", "units": "B", "decimals": 2},
                  {"type": "percent", "negative": "parentheses"}):
            self.assertEqual(formats.parse(formats.tableau(f)), formats.normalize(f))

    def test_parse_rejects(self):
        for text in ('c"¤"#,##0;-"¤"#,##0', "n#,##0.0000000;-#,##0.0000000", "n#,##0,,.0K;-#,##0,,.0K",
                     'n"🏠 "#,##0;("🏠 "#,##0)', "n#,##0;-#,##0.0"):
            with self.assertRaises(FormatError, msg=text):
                formats.parse(text)

    def test_normalize_rejects(self):
        for bad, msg in [("dollars", "unknown format"), ({"decimals": 7}, "0-6"), ({"decimals": -1}, "0-6"),
                         ({"type": "currency", "symbol": "¤"}, "symbol"), ({"type": "percent", "units": "K"}, "units"),
                         ({"symbol": "$"}, "currency only"), ({"negative": "red"}, "negative")]:
            with self.assertRaisesRegex(FormatError, msg):
                formats.normalize(bad)


class Render(unittest.TestCase):
    def test_en(self):
        r = lambda v, f: formats.render(v, f, "en_US")
        self.assertEqual(r(634612, "number_k"), "634.6K")
        self.assertEqual(r(1234567, "currency_m"), "$1.2M")
        self.assertEqual(r(-1234.5, {"type": "currency", "negative": "parentheses"}), "($1,235)")
        self.assertEqual(r(-1234.5, "number"), "-1,235")
        self.assertEqual(r(0.105, "percent"), "10.5%")
        self.assertEqual(r(124.7378, {"type": "currency", "symbol": "₽", "decimals": 2}), "124.74 ₽")
        self.assertEqual(r(None, "number"), "")

    def test_ru_as_desktop_showed_it(self):
        """golden_formats in Desktop 2025.1 (ru_RU): the tiles, the card and the table."""
        r = lambda v, f: formats.render(v, f, "ru_RU")
        self.assertEqual(r(2544, "number"), "2 544")
        self.assertEqual(r(0.0773492, "percent"), "7,7%")
        self.assertEqual(r(124.7378, {"type": "currency", "symbol": "₽", "decimals": 2}), "124,74 ₽")
        self.assertEqual(r(31733294000, {"type": "number", "units": "B", "decimals": 2}), "31,73B")
        self.assertEqual(r(15462.1, "currency_k"), "$15,5K")
        self.assertEqual(r(-104.47, {"type": "currency", "decimals": 1, "negative": "parentheses"}), "($104,5)")


class Infer(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(formats.infer("$1.2M"), {"type": "currency", "decimals": 1, "units": "M", "symbol": "$"})
        self.assertEqual(formats.infer("634.6K"), {"type": "number", "decimals": 1, "units": "K"})
        self.assertEqual(formats.infer("(1,234)"), {"type": "number", "decimals": 0, "units": "none",
                                                    "negative": "parentheses"})
        self.assertEqual(formats.infer("12.5%"), {"type": "percent", "decimals": 1})
        self.assertEqual(formats.infer("€3.45bn")["units"], "B")
        self.assertIsNone(formats.infer("n/a"))

    def test_same_form(self):
        self.assertTrue(formats.same_form("634.6K", "number_k"))
        self.assertTrue(formats.same_form("634,6K", "number_k"))  # the separators are the viewer's locale
        self.assertFalse(formats.same_form("634.6K", "number"))
        self.assertFalse(formats.same_form("$1.23M", "currency_m"))
        self.assertFalse(formats.same_form("(1,234)", "number"))
        self.assertTrue(formats.same_form("-1,234", "number"))


class Spec(unittest.TestCase):
    def assertRejects(self, spec, msg):
        with self.assertRaisesRegex(ValueError, msg):
            build(spec, OUT, SPECS)

    def test_string_field(self):
        self.assertRejects(mutate(lambda s: sheet(s, "Worst Order")["measure"].update(field="Region", agg="count")),
                           "needs a numeric field, 'Region' is string")

    def test_one_field_one_format(self):
        self.assertRejects(mutate(lambda s: sheet(s, "Sales by Region")["measure"].update(format="currency_m")),
                           "already has another format")

    def test_calc_format_lives_in_calcs(self):
        self.assertRejects(mutate(lambda s: sheet(s, "Ratio")["measure"].update(format="pct2")), "calcs\\[\\].format")

    def test_string_calc(self):
        def f(s):
            s["calcs"].append({"name": "Label", "formula": "[Region]", "format": "currency"})
        self.assertRejects(mutate(f), "currency format needs a numeric result")


class Gate(unittest.TestCase):
    """Break the formats of the Desktop-saved golden one way at a time; the gate must name the break."""

    def assertCaught(self, fn, text):
        issues = [str(i) for i in gate.run(repack(GOLDEN_TWBX, fn))]
        self.assertTrue(any(i.startswith("[formats]") and text in i for i in issues), issues)

    @staticmethod
    def set_format(name, value):
        def fn(root):
            for c in root.iter("column"):
                if c.get("name") == name:
                    c.set("default-format", value)
        return fn

    def test_golden_is_clean(self):
        self.assertEqual([i for i in gate.run(GOLDEN_TWBX) if i.check == "formats"], [])

    def test_unknown_symbol(self):
        self.assertCaught(self.set_format("[Sales]", 'c"¤"#,##0,.0K;-"¤"#,##0,.0K'), "symbol")

    def test_decimals_out_of_range(self):
        self.assertCaught(self.set_format("[Quantity]", "n#,##0.0000000;-#,##0.0000000"), "0-6")

    def test_number_format_on_string_column(self):
        def fn(root):
            ds = root.find("datasources/datasource")
            ds.insert(0, ds.makeelement("column", {"datatype": "string", "name": "[Region]", "role": "dimension",
                                                   "type": "nominal", "default-format": "n#,##0;-#,##0"}))
        self.assertCaught(fn, "on a string column")


def text(t, **kw):
    return {"text": t, "box": [0, 0, 10, 10], "up": [t], **kw}


class Reconcile(unittest.TestCase):
    """The page of the formats fixture as the HTML would print it: value and form both checked."""

    def check(self, *items):
        r = reconcile.check(json.loads(json.dumps(SPEC)), SPECS, {"texts": list(items)})
        return [(f["number"], f["status"]) for f in r["facts"]]

    def test_matching_form(self):
        got = self.check(text("$15.5K", up=["$15.5K", "Sales $15.5K"]),
                         text("($104.5)", cell={"row": "East", "col": "Furniture"}),
                         text("7.7%", up=["7.7%", "Profit Ratio 7.7%"]),
                         text("31.73B", up=["31.73B", "Sales Scaled 31.73B"]))
        self.assertEqual(got, [("15.5K", "matched"), ("104.5", "matched"), ("7.7%", "matched"),
                               ("31.73B", "matched")])

    def test_other_form_fails(self):
        got = self.check(text("-$104.5", cell={"row": "East", "col": "Furniture"}),
                         text("7.73%", up=["7.73%", "Profit Ratio 7.73%"]))
        self.assertEqual(got, [("104.5", "format"), ("7.73%", "format")])

    def test_phrase_in_parentheses_is_not_a_negative(self):
        self.assertEqual(self.check(text("Profit Ratio (7.7%)")), [("7.7%", "matched")])
