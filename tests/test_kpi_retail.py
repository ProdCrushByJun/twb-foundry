"""KPI cards on a plain e-commerce CSV (decisions/198): a date with a time, a row-level calculated field, an average
order value as revenue per distinct invoice with its change in percent. Found in the victory_retail case."""
import copy
import csv
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tbuilder import cards, expected
from tbuilder.build import build

ROWS = [  # Invoice, Invoice Date, Order Type, Revenue
    ("A1", "2011-01-03 08:45:00", "Order", 100), ("A1", "2011-01-03 08:45:00", "Order", 50),
    ("A2", "2011-01-20 17:10:00", "Order", 50), ("C1", "2011-01-21 09:00:00", "Cancellation", -20),
    ("B1", "2011-02-02 10:00:00", "Order", 120), ("B2", "2011-02-10 11:30:00", "Order", 60),
    ("B3", "2011-02-28 23:59:00", "Order", 60), ("C2", "2011-02-28 23:59:00", "Cancellation", -60)]
CALCS = [{"name": "Order Revenue", "formula": 'IF [Order Type] = "Order" THEN [Revenue] END'},
         {"name": "Order Invoice", "formula": 'IF [Order Type] = "Order" THEN [Invoice] END'},
         {"name": "Cancelled Revenue", "formula": 'IF [Order Type] = "Cancellation" THEN -[Revenue] END'}]
NET = {"field": "Revenue", "label": "Net revenue", "format": "number"}
OWN = {"field": "Order Revenue", "label": "Orders", "format": "number"}
AOV = {"field": "Order Revenue", "per": "Order Invoice", "per_agg": "countd", "delta": "pct", "label": "Average order",
       "format": "number"}
RATE = {"field": "Cancelled Revenue", "per": "Order Revenue", "delta": "pct", "label": "Cancellation rate", "format": "pct1"}
PP = {"field": "Cancelled Revenue", "per": "Order Revenue", "label": "Cancellation pp", "format": "pct1"}


def spec_of(*measures, calcs=CALCS, **sheet):
    return {"version": 1, "datasource": {"type": "csv", "path": "retail.csv"}, "calcs": copy.deepcopy(calcs),
            "sheets": [{"name": "KPI", "type": "kpi", "style": "cards", "date": {"field": "Invoice Date", "level": "month"},
                        "compare": "previous", "measures": [copy.deepcopy(m) for m in measures], **sheet}],
            "dashboard": {"name": "D", "title": "**Sales**", "subtitle": "Orders", "width": 1200, "height": 800, "grid": [["KPI"]]}}


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        with (self.tmp / "retail.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Invoice", "Invoice Date", "Order Type", "Revenue"])
            w.writerows(ROWS)

    def numbers(self, *measures):
        return expected.compute(spec_of(*measures), self.tmp / "retail.csv")["KPI"]

    def book(self, *measures, **sheet):
        out = build(spec_of(*measures, **sheet), self.tmp / "b.twbx", self.tmp)
        with zipfile.ZipFile(out) as z:
            return ET.fromstring(z.read("b.twb"))


class Numbers(Base):
    def test_a_date_with_a_time_and_a_column(self):
        got = self.numbers(NET)["Net revenue"]
        self.assertEqual((got["current"], got["previous"]), (180, 180))  # the last moment of February is in February

    def test_a_row_level_calc(self):
        got = self.numbers(OWN)["Orders"]
        self.assertEqual((got["current"], got["previous"]), (240, 200))
        self.assertAlmostEqual(got["delta"], 0.2)

    def test_average_order_in_percent(self):
        got = self.numbers(AOV)["Average order"]
        self.assertEqual((got["current"], got["previous"]), (80, 100))  # 240 / 3, 200 / 2
        self.assertAlmostEqual(got["delta"], -0.2)

    def test_a_ratio_in_percent_and_in_points(self):
        got = self.numbers(RATE, PP)
        self.assertEqual((got["Cancellation rate"]["current"], got["Cancellation rate"]["previous"]), (0.25, 0.1))
        self.assertAlmostEqual(got["Cancellation rate"]["delta"], 1.5)  # 0.1 -> 0.25 is +150%
        self.assertAlmostEqual(got["Cancellation pp"]["delta"], 15)  # the default stays: +15 pp


class Book(Base):
    def columns(self, root, what):
        return {c.get("caption"): c for c in root.find("datasources").iter("column") if what in c.get("caption", "")}

    def test_builds_with_all_of_it(self):
        root = self.book(NET, OWN, AOV, RATE)
        fmts = {k: c.get("default-format") for k, c in self.columns(root, "Change Good").items()}
        self.assertEqual(fmts["KPI · Average order · Change Good"], cards.DELTA_FORMAT)
        self.assertEqual(fmts["KPI · Cancellation rate · Change Good"], cards.DELTA_FORMAT)

    def test_the_period_is_a_datetime_column(self):
        root = self.book(NET)
        self.assertEqual(self.columns(root, "Last Invoice Date")["Last Invoice Date"].get("datatype"), "datetime")

    def test_the_formula_counts_distinct_invoices(self):
        got = {c["name"]: c["formula"] for c in cards.calcs(spec_of(AOV))}
        n = cards.names(spec_of(AOV)["sheets"][0], AOV)
        self.assertIn("COUNTD(IF", got[n["current"]])
        self.assertTrue(got[n["ratio"]].endswith("COUNTD([Order Invoice])"), got[n["ratio"]])

    def test_the_card_history_of_a_ratio_counts_distinct_invoices(self):
        self.assertTrue(self.book(AOV, history="bar") is not None)


class Refused(Base):
    def refused(self, text, *measures, **kw):
        with self.assertRaises(ValueError) as e:
            build(spec_of(*measures, **kw), self.tmp / "b.twbx", self.tmp)
        self.assertIn(text, str(e.exception))

    def test_an_aggregate_calc_says_what_to_do(self):
        calcs = CALCS + [{"name": "AOV", "formula": "SUM([Revenue]) / COUNTD([Invoice])"}]
        self.refused("per", {"field": "AOV"}, calcs=calcs)

    def test_a_text_calc_cannot_be_summed(self):
        self.refused("not a number", {"field": "Order Invoice"})

    def test_a_text_field_per_needs_a_count(self):
        self.refused("not a number", {"field": "Order Revenue", "per": "Order Invoice", "label": "X"})

    def test_an_unknown_field(self):
        self.refused("Nope", {"field": "Nope"})

    def test_per_agg_needs_per(self):
        self.refused("per_agg", {"field": "Revenue", "per_agg": "countd"})

    def test_a_string_date_is_still_refused(self):
        spec = spec_of(NET)
        spec["sheets"][0]["date"]["field"] = "Invoice"
        with self.assertRaises(ValueError):
            build(spec, self.tmp / "b.twbx", self.tmp)


if __name__ == "__main__":
    unittest.main()
