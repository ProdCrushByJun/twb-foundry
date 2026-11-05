"""HTML numbers <-> workbook numbers (decisions/024)."""
import copy
import json
import unittest

from tbuilder import html_outline, reconcile
from tbuilder.spec import load
from test_roundtrip import ROOT

FIXTURE = ROOT / "tests" / "fixtures" / "sales_dashboard.html"
FIXTURE_SPEC = ROOT / "specs" / "fixture_sales.json"
REFERRALS = ROOT / "tests" / "fixtures" / "registry_referrals.html"
REFERRALS_SPEC = ROOT / "specs" / "fixture_referrals.json"

try:
    html_outline._chrome()
    HAVE_CHROME = True
except RuntimeError:
    HAVE_CHROME = False


def text(t, **kw):
    return {"text": t, "box": [0, 0, 10, 10], "up": [t], **kw}


def page(*items):
    return {"texts": list(items)}


class Tokens(unittest.TestCase):
    def kinds(self, t):
        return [(tok, why) for tok, _, why in reconcile._tokens(t)]

    def test_dates_and_years_are_not_values(self):
        self.assertEqual(self.kinds("As of 2025-03-31, Oct 20 and 12.03.2025: 1,234"),
                         [("2025-03-31", "date"), ("Oct 20", "date"), ("12.03.2025", "date"), ("1,234", None)])
        self.assertEqual(self.kinds("Sales Pulse 2025"), [("2025", "date")])

    def test_identifiers(self):
        self.assertEqual(self.kinds("Analyst B03 (47)"), [("03", "identifier"), ("47", None)])
        self.assertEqual(self.kinds("XD-0002 (BK)"), [("0002", "identifier")])
        self.assertEqual(self.kinds("4px, 3rd"), [("4", "identifier"), ("3", "identifier")])

    def test_units(self):
        self.assertEqual(self.kinds("44% of total, 12.5K units, -3"), [("44%", None), ("12.5K", None), ("-3", None)])


class Context(unittest.TestCase):
    def ctx(self, item):
        return [f["context"] for f in reconcile.facts(page(item)) if f["status"] is None]

    def test_own_phrase_first(self):
        self.assertEqual(self.ctx(text("North – Harbor · 12 analysts")), ["12 analysts"])

    def test_tile_label_from_enclosing_element(self):
        self.assertEqual(self.ctx(text("388", up=["388", "Total closures 388 32.3 per analyst"])),
                         ["Total closures 388 32.3 per analyst"])

    def test_table_cell(self):
        self.assertEqual(self.ctx(text("18,840", cell={"row": "East", "col": "Furniture"})), ["East Furniture 18,840"])

    def test_tooltip_and_svg_label(self):
        self.assertEqual(self.ctx(text("20", title="Analyst B03 · Incidents: 20")), ["Analyst B03 · Incidents: 20"])
        self.assertEqual(self.ctx(text("72", svg=0, svg_label="Mon")), ["Mon 72"])

    def test_axis_ticks(self):
        ticks = [text(str(v), svg=0, box=[200 - len(str(v)) * 7, 500 - v, len(str(v)) * 7, 16]) for v in (0, 50, 100)]
        bars = [text("72", svg=0, box=[260, 368, 14, 16]), text("80", svg=0, box=[480, 351, 14, 16])]
        got = {f["number"]: f["status"] for f in reconcile.facts(page(*ticks, *bars))}
        self.assertEqual(got, {"0": "skipped", "50": "skipped", "100": "skipped", "72": None, "80": None})


class Entries(unittest.TestCase):
    def test_plan_bar_has_fact_and_plan(self):
        """Both values of a plan bar (decisions/016) reach reconcile; an anchor-replacing edit once dropped this
        branch and no other test noticed (decisions/044 lessons)."""
        from tbuilder import expected
        spec = load(ROOT / "specs" / "colors.json")
        exp = expected.compute(spec, ROOT / "specs" / spec["datasource"]["path"])
        plan = [e for e in reconcile.entries(spec, exp) if e["sheet"] == "Plan"]
        self.assertEqual({tuple(e["tags"]) for e in plan}, {("Sales",), ("Plan",)})
        self.assertEqual(len(plan), 2 * len(exp["Plan"]))


class Matching(unittest.TestCase):
    """Synthetic pages against specs/fixture_sales.json (no Chrome)."""

    @classmethod
    def setUpClass(cls):
        cls.spec = load(FIXTURE_SPEC)

    def run_(self, *items, spec=None, case=None):
        r = reconcile.check(spec or self.spec, FIXTURE_SPEC.parent, page(*items), case)
        return {f["number"]: f["status"] for f in r["facts"]}, r

    def test_matched(self):
        got, r = self.run_(text("224,710", up=["224,710", "224,710 Total sales"]),
                           text("58,862", up=["58,862", "South 58,862"]),
                           text("18,840", cell={"row": "East", "col": "Furniture"}))
        self.assertEqual(got, {"224,710": "matched", "58,862": "matched", "18,840": "matched"})
        self.assertTrue(r["ok"])

    def test_wrong_binding_is_a_mismatch(self):
        """The LLM bound the 'Total profit' tile to Sales: the workbook shows 224,710 where the HTML shows 23,550."""
        spec = copy.deepcopy(self.spec)
        spec["sheets"][0]["measures"][1] = {"field": "Sales", "label": "Total profit"}
        got, r = self.run_(text("23,550", up=["23,550", "23,550 Total profit"]), spec=spec)
        self.assertEqual(got, {"23,550": "mismatch"})
        self.assertFalse(r["ok"])
        self.assertIn("224710", r["facts"][0]["workbook"])

    def test_wrong_member_is_a_mismatch(self):
        got, r = self.run_(text("58,483", up=["58,483", "South 58,483"]))  # North's value printed next to South
        self.assertEqual(got, {"58,483": "mismatch"})
        self.assertIn("this value is in Sales by Region [North]", r["facts"][0]["note"])

    def test_elsewhere_and_missing(self):
        got, r = self.run_(text("2,610 units sold"), text("9,999 orders"))
        self.assertEqual(got, {"2,610": "elsewhere", "9,999": "missing"})
        self.assertFalse(r["ok"])

    def test_accepted_needs_reason_and_stale_fails(self):
        case = {"accepted": [{"number": "9,999", "context": "orders", "reason": "orders count: not in the spec"}]}
        got, r = self.run_(text("9,999 orders"), case=case)
        self.assertEqual(got, {"9,999": "accepted"})
        self.assertTrue(r["ok"])
        got, r = self.run_(text("1,000 orders"), case=case)
        self.assertEqual(r["stale"], case["accepted"])
        self.assertFalse(r["ok"])
        with self.assertRaises(ValueError):
            self.run_(text("9,999 orders"), case={"accepted": [{"number": "9,999", "context": "orders"}]})

    def test_state_selects_filter_values(self):
        got, _ = self.run_(text("224,710", up=["224,710", "224,710 Total sales"]), case={"state": {"Region": ["South"]}})
        self.assertEqual(got, {"224,710": "mismatch"})  # the tile shows South only under that selection
        got, _ = self.run_(text("58,862", up=["58,862", "58,862 Total sales"]), case={"state": {"Region": ["South"]}})
        self.assertEqual(got, {"58,862": "matched"})

    def test_state_must_be_a_filter_card(self):
        with self.assertRaisesRegex(ValueError, "not a filter card"):
            self.run_(text("1"), case={"state": {"Category": ["Tech"]}})
        with self.assertRaisesRegex(ValueError, "no values"):
            self.run_(text("1"), case={"state": {"Region": ["Mars"]}})


@unittest.skipUnless(HAVE_CHROME, "Chrome not installed")
class Pages(unittest.TestCase):
    def test_fixture_every_number(self):
        r = reconcile.check(load(FIXTURE_SPEC), FIXTURE_SPEC.parent, html_outline.outline(FIXTURE))
        self.assertTrue(r["ok"], reconcile.report_text(r))
        self.assertEqual(r["summary"], {"matched": 18, "elsewhere": 1, "skipped": 2})  # + the sparkline without an axis (decisions/123)

    def test_referrals_registry_v2(self):
        """ER Referrals style (decisions/039): rank, value, share, dot, "**36%** (77,142)" all from the registry."""
        spec = load(REFERRALS_SPEC)
        r = reconcile.check(spec, REFERRALS_SPEC.parent, html_outline.outline(REFERRALS))
        self.assertTrue(r["ok"], reconcile.report_text(r))
        self.assertEqual(r["summary"], {"matched": 70})
        # a page with the first two products' ranks swapped: both ranks are wrong numbers
        html = REFERRALS.read_text(encoding="utf-8").replace('class="rk">1<', 'class="rk">X<', 1)
        html = html.replace('class="rk">2<', 'class="rk">1<', 1).replace('class="rk">X<', 'class="rk">2<', 1)
        swapped = ROOT / "out" / "registry_referrals_swapped.html"
        swapped.parent.mkdir(exist_ok=True)
        swapped.write_text(html, encoding="utf-8")
        r = reconcile.check(spec, REFERRALS_SPEC.parent, html_outline.outline(swapped))
        self.assertFalse(r["ok"])
        bad = sorted(f["context"] for f in r["facts"] if f["status"] not in ("matched", None))
        self.assertEqual(len(bad), 2, bad)



if __name__ == "__main__":
    unittest.main()
