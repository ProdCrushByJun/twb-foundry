"""KPI cards (todo 3.1): value text + change colored good/bad + muted history with the current period highlighted."""
import copy
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tbuilder import cards, design
from tbuilder.build import build
from tbuilder.expected import compute
from test_roundtrip import SPECS

SPEC = json.loads((SPECS / "cards.json").read_text(encoding="utf-8"))
SPEC["dashboard"]["theme"] = "flat"  # the view without cards (decisions/168)
OUT = Path(__file__).resolve().parent.parent / "out" / "cards_test.twbx"


def built(spec):
    out = build(spec, OUT, SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def mutate(fn):
    spec = copy.deepcopy(SPEC)
    fn(spec)
    return spec


def sheet(spec, name):
    return next(s for s in spec["sheets"] if s["name"] == name)


class Calcs(unittest.TestCase):
    def test_generated_formulas(self):
        got = {c["name"]: c for c in cards.calcs(SPEC)}
        self.assertEqual(got["Last Order Date"]["formula"], "{FIXED : MAX([Order Date])}")
        self.assertEqual(got["Monthly · Sales · Current"]["formula"],
                         "SUM(IF DATETRUNC('month', [Order Date]) = DATETRUNC('month', [Last Order Date]) "
                         "THEN [Sales] END)")
        self.assertEqual(got["Monthly · Sales · Previous"]["formula"],
                         "SUM(IF DATETRUNC('month', [Order Date]) = DATEADD('month', -1, "
                         "DATETRUNC('month', [Last Order Date])) THEN [Sales] END)")
        self.assertIn("DATEADD('year', -1,", got["Yearly · Units · Previous"]["formula"])
        self.assertEqual(got["Monthly · Period"]["format"], "*mmm yyyy")
        # good: down flips which side of zero is drawn in the good color
        self.assertIn("<= 0", got["Yearly · Units · Change Good"]["formula"])
        self.assertIn("> 0", got["Yearly · Units · Change Bad"]["formula"])
        self.assertEqual(sum(c["name"] == "Last Order Date" for c in cards.calcs(SPEC)), 1)  # shared by both cards

    def test_expected_values(self):
        """Hand-checked on data/sample/sales_2y.csv: Dec 2025 vs Nov 2025 and vs Dec 2024."""
        got = compute(SPEC, SPECS / SPEC["datasource"]["path"])
        sales, units = got["Monthly"]["Sales"], got["Yearly"]["Units"]
        self.assertEqual(round(sales["current"]), 15462)
        self.assertEqual(round(sales["previous"]), 13996)
        self.assertAlmostEqual(sales["delta"], 0.105, places=3)
        self.assertAlmostEqual(got["Monthly"]["Profit"]["delta"], -0.344, places=3)
        self.assertEqual((units["current"], units["previous"]), (104, 111))
        self.assertAlmostEqual(units["delta"], -0.063, places=3)


class Workbook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(copy.deepcopy(SPEC))
        cls.ws = {w.get("name"): w for w in cls.root.iter("worksheet")}

    def test_two_sheets_per_measure(self):
        self.assertEqual(sorted(n for n in self.ws if n.startswith(("Monthly", "Yearly"))),
                         ["Monthly · Profit", "Monthly · Profit · History", "Monthly · Sales",
                          "Monthly · Sales · History", "Yearly · Units", "Yearly · Units · History"])

    def test_value_text(self):
        runs = [(r.text, r.attrib) for r in self.ws["Monthly · Sales"].iter("run")]
        texts = [t for t, _ in runs]
        self.assertEqual(texts[2], "Sales")
        self.assertEqual(texts[-1], " MoM")
        good = next(a for t, a in runs if a.get("fontcolor") == design.COLOR["good"])
        bad = next(a for t, a in runs if a.get("fontcolor") == design.COLOR["bad"])
        self.assertEqual((good["fontsize"], bad["fontsize"]), ("10", "10"))
        value = runs[4][1]
        self.assertEqual((value.get("bold"), value.get("fontsize")), ("true", "24"))
        self.assertEqual([r.text for r in self.ws["Yearly · Units"].iter("run")][-1], " vs PY")

    def test_history_strip(self):
        ws = self.ws["Monthly · Sales · History"]
        self.assertEqual(ws.find("table/panes/pane/mark").get("class"), "Bar")
        modes = [f.get("value") for f in ws.iter("format") if f.get("attr") == "mark-labels-mode"]
        self.assertEqual(modes, ["most-recent"])
        hidden = [f.get("scope") for f in ws.iter("format") if f.get("attr") == "display"]
        self.assertEqual(sorted(hidden), ["cols", "rows"])
        color = ws.find("table/panes/pane/encodings/color").get("column")
        self.assertIn("[none:Calculation_", color)

    def test_palette_map(self):
        ds = self.root.find("datasources/datasource")
        maps = {m.find("bucket").text: m.get("to") for m in ds.iter("map")}
        self.assertEqual(maps, {"true": design.COLOR["accent"], "false": design.COLOR["mark_muted"]})
        tags = [c.tag for c in ds]
        self.assertEqual(tags.index("style"), tags.index("layout") + 1)  # as Desktop orders it

    def test_value_above_history(self):
        z = {e.get("name"): e for e in self.root.iter("zone") if e.get("name") and "type-v2" not in e.attrib}
        v, h = z["Monthly · Sales"], z["Monthly · Sales · History"]
        self.assertEqual((v.get("x"), v.get("w")), (h.get("x"), h.get("w")))
        self.assertEqual(int(h.get("y")), int(v.get("y")) + int(v.get("h")))
        self.assertLess(int(v.get("x")), int(z["Monthly · Profit"].get("x")))  # measures side by side

    def test_no_legend_for_history(self):
        self.assertEqual([e for e in self.root.iter("zone") if e.get("type-v2") == "color"], [])


class CardErrors(unittest.TestCase):
    def assertRejects(self, spec, msg):
        with self.assertRaisesRegex(ValueError, msg):
            build(spec, OUT, SPECS)

    def test_cards_need_date(self):
        self.assertRejects(mutate(lambda s: sheet(s, "Monthly").pop("date")), "needs 'date'")

    def test_card_date_must_be_date(self):
        self.assertRejects(mutate(lambda s: sheet(s, "Monthly").update(date={"field": "Region"})), "not a date")

    def test_card_options_only_on_cards(self):
        self.assertRejects(mutate(lambda s: sheet(s, "Yearly").update(style="tiles")), "only apply to style 'cards'")

    def test_an_aggregate_calc_measure_is_refused(self):
        """A row-level one is accepted (decisions/198, test_kpi_retail)."""
        def f(s):
            s["calcs"] = [{"name": "Margin", "formula": "SUM([Profit]) / SUM([Sales])"}]
            sheet(s, "Monthly")["measures"][0]["field"] = "Margin"
        self.assertRejects(mutate(f), "aggregate calculation")

    def test_card_too_short(self):
        self.assertRejects(mutate(lambda s: s["dashboard"].update(height=520)), "too short for a KPI card")


if __name__ == "__main__":
    unittest.main()
