"""Expected values vs numbers Tableau Desktop 2025.1 actually rendered (read off screenshots, 2026-10-19).

Golden: hand-built workbook. HR: generated out/hr.twbx opened in Desktop.
Tableau showed rounded values, so we compare at the displayed precision.
"""
import unittest
from unittest import mock

from tbuilder import expected, formats, spec
from test_roundtrip import SPECS

# Displayed by Tableau Desktop (ru_RU formatting stripped).
GOLDEN_SEEN = {
    "KPI": {"SUM(Sales)": 224710, "SUM(Profit)": 23550, "SUM(Quantity)": 2610},
    "Table": {
        "East | Furniture": 18840, "East | Office": 15633, "East | Tech": 17881,
        "North | Furniture": 23294, "North | Office": 14205, "North | Tech": 20983,
        "South | Furniture": 15128, "South | Office": 22634, "South | Tech": 21100,
        "West | Furniture": 17695, "West | Office": 18705, "West | Tech": 18611,
    },
}
HR_SEEN_KPI = {"SUM(Headcount)": 583, "AVG(Salary)": 2601}
HR_SEEN_MATRIX = {  # one decimal
    "Engineering | Belgrade": 2239.3, "Engineering | Nis": 2559.1, "Engineering | Novi Sad": 2570.4,
    "Finance | Belgrade": 2229.9, "Finance | Nis": 2795.2, "Finance | Novi Sad": 2614.9,
    "HR | Belgrade": 2173.3, "HR | Nis": 2760.4, "HR | Novi Sad": 3005.3,
    "Sales | Belgrade": 2433.4, "Sales | Nis": 2948.6, "Sales | Novi Sad": 2528.1,
    "Support | Belgrade": 3042.7, "Support | Nis": 2600.0, "Support | Novi Sad": 2509.9,
}

# golden_calcs_2025_1 opened in Desktop 2025.1 (2026-10-20): percent shown with one decimal.
CALCS_SEEN_KPI = {"SUM(Sales)": 224710, "SUM(Tech Sales)": 78575}
CALCS_SEEN_RATIO_PCT = {
    "Large | East": 7.7, "Large | North": 14.2, "Large | South": 11.9, "Large | West": 8.6,
    "Medium | East": 12.7, "Medium | North": 9.7, "Medium | South": 9.0, "Medium | West": 6.2,
    "Small | East": 10.1, "Small | North": 10.1, "Small | South": 10.2, "Small | West": 10.8,
}

# golden_lods_2025_1 opened in Desktop 2025.1 (2026-10-20).
LODS_SEEN_KPI = {"MIN(Total Sales)": 224710, "AGG(Max Region Sales)": 58862, "SUM(First Day Orders)": 4}
LODS_SEEN_MIX_PCT = {
    "East | Furniture": 36.0, "East | Office": 29.9, "East | Tech": 34.2,
    "North | Furniture": 39.8, "North | Office": 24.3, "North | Tech": 35.9,
    "South | Furniture": 25.7, "South | Office": 38.5, "South | Tech": 35.8,
    "West | Furniture": 32.2, "West | Office": 34.0, "West | Tech": 33.8,
}
LODS_SEEN_SIZE = {"East | Small region", "North | Big region", "South | Big region", "West | Small region"}

# golden_lods_view_2025_1 opened in Desktop 2025.1 (2026-10-20). 74 903 = average over the 3
# category totals (INCLUDE aggregates LOD-level values); row-weighted would be 74 998.
LODS_VIEW_SEEN_KPI = {"AGG(Max Category Sales)": 78575, "AVG(Category Sales)": 74903}
LODS_VIEW_SEEN_REGION_TOTAL = {"East": 52354, "North": 58483, "South": 58862, "West": 55011}

# golden_tablecalcs_2025_1 opened in Desktop 2025.1 (2026-10-20).
TC_SEEN_SHARE_IN_REGION = {  # percent_of_total along Category (partition = Region), 2 decimals
    "East | Furniture": 35.99, "East | Office": 29.86, "East | Tech": 34.15,
    "North | Furniture": 39.83, "North | Office": 24.29, "North | Tech": 35.88,
    "South | Furniture": 25.70, "South | Office": 38.45, "South | Tech": 35.85,
    "West | Furniture": 32.17, "West | Office": 34.00, "West | Tech": 33.83,
}
TC_SEEN_REGION_DIFF = {  # difference along Region; East is the first mark -> empty
    "North | Furniture": 4454, "North | Office": -1428, "North | Tech": 3102,
    "South | Furniture": -8166, "South | Office": 8429, "South | Tech": 117,
    "West | Furniture": 2567, "West | Office": -3929, "West | Tech": -2489,
}


def compute(name):
    s = spec.load(SPECS / f"{name}.json")
    return expected.compute(s, SPECS / s["datasource"]["path"])


class MatchesTableau(unittest.TestCase):
    def test_golden(self):
        e = compute("golden")
        for sheet, cells in GOLDEN_SEEN.items():
            for key, seen in cells.items():
                with self.subTest(sheet=sheet, cell=key):
                    self.assertEqual(round(e[sheet][key]), seen)
        self.assertEqual(set(e["Table"]), set(GOLDEN_SEEN["Table"]))

    def test_hr(self):
        e = compute("hr")
        for key, seen in HR_SEEN_KPI.items():
            self.assertEqual(round(e["Headline"][key]), seen)
        for key, seen in HR_SEEN_MATRIX.items():
            with self.subTest(cell=key):
                self.assertAlmostEqual(e["Salary Matrix"][key], seen, delta=0.05)
        self.assertEqual(set(e["Salary Matrix"]), set(HR_SEEN_MATRIX))

    def test_calcs(self):
        e = compute("calcs")
        for key, seen in CALCS_SEEN_KPI.items():
            self.assertEqual(round(e["KPI"][key]), seen)
        self.assertEqual(round(e["KPI"]["AGG(Profit Ratio)"] * 100, 1), 10.5)
        for key, seen in CALCS_SEEN_RATIO_PCT.items():
            with self.subTest(cell=key):
                self.assertEqual(round(e["Ratio Matrix"][key] * 100, 1), seen)
        ratio = e["Ratio by Region"]
        self.assertEqual(sorted(ratio, key=ratio.get, reverse=True), ["North", "South", "East", "West"])

    def test_lods(self):
        e = compute("lods")
        for key, seen in LODS_SEEN_KPI.items():
            self.assertEqual(round(e["KPI"][key]), seen)
        for key, seen in LODS_SEEN_MIX_PCT.items():
            with self.subTest(cell=key):
                self.assertEqual(round(e["Region Mix"][key] * 100, 1), seen)
        share = e["Share by Category"]
        self.assertEqual(sorted(share, key=share.get, reverse=True), ["Tech", "Furniture", "Office"])
        self.assertEqual(set(e["Sales by Region"]), LODS_SEEN_SIZE)

    def test_lods_view(self):
        e = compute("lods_view")
        for key, seen in LODS_VIEW_SEEN_KPI.items():
            self.assertEqual(round(e["KPI"][key]), seen)
        grid = e["Region Total Grid"]  # EXCLUDE [Category]: region total repeated in every cell
        for key, v in grid.items():
            with self.subTest(cell=key):
                self.assertEqual(round(v), LODS_VIEW_SEEN_REGION_TOTAL[key.split(" | ")[0]])
        for key, seen in LODS_SEEN_MIX_PCT.items():  # share via EXCLUDE == share via FIXED
            with self.subTest(share=key):
                self.assertEqual(round(e["Share Grid"][key] * 100, 1), seen)

    def test_tablecalcs(self):
        e = compute("tablecalcs")
        for key, seen in TC_SEEN_SHARE_IN_REGION.items():
            with self.subTest(share=key):
                self.assertEqual(round(e["Share in Region"][key] * 100, 2), seen)
        for key, seen in TC_SEEN_REGION_DIFF.items():
            with self.subTest(diff=key):
                self.assertEqual(round(e["Region Difference"][key]), seen)
        self.assertTrue(all(e["Region Difference"][f"East | {c}"] is None for c in ("Furniture", "Office", "Tech")))
        # % of total of AVG = AVG / TOTAL(AVG): around 100%, North above (Desktop bar past 100%)
        avg = e["Avg Share"]
        self.assertTrue(all(0.9 < v < 1.1 for v in avg.values()) and avg["North"] > 1)
        mom = e["MoM Change"]
        self.assertIsNone(mom["2025-01"])  # Desktop: "1 null"
        self.assertEqual(max(mom, key=lambda k: mom[k] or -1), "2025-06")
        self.assertEqual(round(mom["2025-06"] * 100), 67)
        self.assertEqual(round(e["Running Sales"]["2025-12"]), 224710)

    def test_dates(self):
        """golden_dates_2025_1 (DD.MM.YYYY + datetime, range + relative filters) and golden_dates_us_2025_1
        (MM/DD/YYYY in en_US; relative on a date, datetime range, range over all dates keeps the null Due Date)."""
        e = compute("dates")
        self.assertEqual({k: round(v) for k, v in e["KPI"].items()}, DATES_SEEN_KPI)
        for key, seen in DATES_SEEN.items():
            with self.subTest(cell=key):
                sheet, mark = key.split(": ")
                self.assertEqual(round(e[sheet][mark]), seen)
        self.assertEqual(len(e["Shipments"]), 10)  # Desktop: 10 weeks, 28 Apr .. 30 Jun 2025
        e = compute("dates_us")
        self.assertEqual({k: round(v) for k, v in e["KPI"].items()}, DATES_US_SEEN_KPI)


# golden_dates_2025_1 / golden_dates_us_2025_1 opened in Desktop 2025.1 (2026-10-20): tiles and tooltips.
DATES_SEEN_KPI = {"SUM(Sales)": 22258, "SUM(Units)": 157}
DATES_SEEN = {"Regions: East": 5402, "Regions: South": 6735, "Regions: West": 5671,
              "Orders: 2025-04": 961, "Orders: 2025-05": 8517}
DATES_US_SEEN_KPI = {"SUM(Sales)": 31462, "SUM(Units)": 211}


class CachedRun(unittest.TestCase):
    """cached(): one computation per run (decisions/179); only what cannot change the numbers shares it."""

    def count(self, calls):
        n = []
        with mock.patch.object(expected, "_compute", lambda *a: n.append(a) or {"s": {"x": [1]}}), expected.cached():
            got = [calls(i) for i in range(2)]
        return len(n), got

    def test_same_arguments_once(self):
        self.assertEqual(self.count(lambda i: expected.compute({"sheets": []}, "x.csv"))[0], 1)

    def test_a_callers_change_stays_with_the_caller(self):
        with mock.patch.object(expected, "_compute", lambda *a: {"s": {"x": [1]}}), expected.cached():
            expected.compute({"sheets": []}, "x.csv")["s"]["x"].append(2)
            self.assertEqual(expected.compute({"sheets": []}, "x.csv"), {"s": {"x": [1]}})

    def test_no_selection_is_the_opening_one(self):
        self.assertEqual(self.count(lambda i: expected.compute({"sheets": []}, "x.csv", where=[None, {}][i]))[0], 1)

    def test_what_changes_the_numbers_computes_again(self):
        for vary in (lambda i: expected.compute({"sheets": [], "calcs": [i]}, "x.csv"),
                     lambda i: expected.compute({"sheets": []}, f"{i}.csv"),
                     lambda i: expected.compute({"sheets": []}, "x.csv", {"P": i}),
                     lambda i: expected.compute({"sheets": []}, "x.csv", where={"F": {str(i)}})):
            self.assertEqual(self.count(vary)[0], 2)

    def test_the_askers_locale_changes_nothing(self):
        def ask(i):
            with formats.shown_in(["en_US", "ru_RU"][i]):
                return expected.compute({"sheets": [], "locale": "ru_RU"}, "x.csv")
        self.assertEqual(self.count(ask)[0], 1)

    def test_computed_in_the_workbooks_locale(self):
        seen = []
        with mock.patch.object(expected, "_compute", lambda *a: seen.append(formats.render(1234.5, "number1")) or {}):
            expected.compute({"sheets": [], "locale": "ru_RU"}, "x.csv")
            expected.compute({"sheets": []}, "x.csv")
        self.assertEqual(seen[0].replace(" ", " "), "1 234,5")
        self.assertEqual(seen[1], "1,234.5")

    def test_another_locale_of_the_spec_computes_again(self):
        self.assertEqual(self.count(lambda i: expected.compute({"sheets": [], "locale": ["en_US", "ru_RU"][i]}, "x.csv"))[0], 2)


if __name__ == "__main__":
    unittest.main()
