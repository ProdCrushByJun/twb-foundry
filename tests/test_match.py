"""Number parsing and evidence matching."""
import unittest

from tbuilder.match import kpi_candidates, label_candidates, parse_number
from tbuilder.profile import profile_csv
from test_roundtrip import ROOT

SALES = profile_csv(ROOT / "data" / "sample" / "sales.csv")


class ParseNumber(unittest.TestCase):
    CASES = {
        "38,226": (38226.0, 1, "", False),
        "224 710": (224710.0, 1, "", False),
        "2 239,3": (2239.3, 0.1, "", False),
        "1.234.567": (1234567.0, 1, "", False),
        "1,234.5": (1234.5, 0.1, "", False),
        "74.8%": (74.8, 0.1, "%", True),
        "4%": (4.0, 1, "%", True),
        "1.2M": (1.2, 0.1, "M", False),
        "€4.5bn": (4.5, 0.1, "bn", False),
        "$12k": (12.0, 1, "k", False),
        "12 MW": (12.0, 1, "", False),
        "62,481 MW total": (62481.0, 1, "", False),
        "-12": (-12.0, 1, "", False),
        "−3.5": (-3.5, 0.1, "", False),
        "2026": (2026.0, 1, "", False),
    }

    def test_cases(self):
        for text, want in self.CASES.items():
            with self.subTest(text=text):
                self.assertEqual(parse_number(text), want)

    def test_not_numbers(self):
        for text in ["WIND", "", "Q3 2025", "n/a"]:
            with self.subTest(text=text):
                self.assertIsNone(parse_number(text))


class Evidence(unittest.TestCase):
    def test_total_found(self):
        self.assertIn({"field": "Sales", "agg": "sum", "value": SALES_SUM, "unit": None},
                      kpi_candidates("224 710", SALES))

    def test_scaled_total(self):
        hits = kpi_candidates("224.7k", SALES)
        self.assertTrue(any(h["field"] == "Sales" and h["agg"] == "sum" for h in hits))

    def test_category_scoped(self):
        east = sum(float(r["Sales"]) for r in SALES.rows if r["Region"] == "East")
        hits = kpi_candidates(f"{east:,.0f}", SALES, label="EAST sales")
        self.assertTrue(any(h.get("where") == "Region = East" and h["field"] == "Sales" for h in hits))

    def test_no_false_binding(self):
        self.assertEqual(kpi_candidates("123,456,789", SALES), [])

    def test_percent_not_bound(self):
        self.assertEqual(kpi_candidates("74.8%", SALES), [])

    def test_labels(self):
        c = label_candidates(["North", "South · 40%", "East", "West"], SALES)
        self.assertEqual(c[0]["field"], "Region")
        self.assertEqual(c[0]["coverage"], 1.0)


SALES_SUM = sum(float(r["Sales"]) for r in SALES.rows)

if __name__ == "__main__":
    unittest.main()
