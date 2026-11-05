"""Reconcile findings of the acceptance cases (decisions/105): a table row is not a KPI, 'pp' and the real minus,
month labels of a canvas line."""
import unittest

from tbuilder import formats, reconcile
from test_reconcile import page, text


def match(item_or_fact, ents, spec=None):
    fs = [item_or_fact] if "number" in item_or_fact else reconcile.facts(page(item_or_fact))
    reconcile._match(fs, ents, reconcile._Names(spec or {}, ents), [])
    return [f for f in fs if f["status"] != "skipped"]


class RowIsNotKpi(unittest.TestCase):
    """'Furniture Sales $51,516': the value of the East | Furniture row, not the KPI that shares the word Sales."""

    def ents(self):
        e = reconcile._entry
        return [e("KPI", "", ["Sales"], 75627.9),
                e("Region Category", "East | Furniture", ["Sales"], 51515.6),
                e("Region Category", "West | Furniture", ["Sales"], 58148.8)]

    def test_group_row_names_the_region(self):
        (f,) = match(text("$51,516", cell={"row": "Furniture", "col": "Sales", "group": "East"}), self.ents())
        self.assertEqual((f["status"], f["workbook"]), ("matched", "Region Category [East | Furniture] = 51515.6"))

    def test_row_label_alone_never_binds_the_kpi(self):
        (f,) = match(text("$51,516", cell={"row": "Furniture", "col": "Sales"}), self.ents())
        self.assertNotEqual(f["status"], "mismatch")
        self.assertNotIn("KPI", f.get("workbook", ""))

    def test_wrong_value_in_a_row_is_still_a_mismatch(self):
        (f,) = match(text("$51,000", cell={"row": "Furniture", "col": "Sales", "group": "East"}), self.ents())
        self.assertEqual(f["status"], "mismatch")
        self.assertIn("East | Furniture", f["workbook"])


PP = {"type": "number", "decimals": 1, "plus": True, "suffix": "pp"}


class PercentagePoints(unittest.TestCase):
    def test_pp_is_a_number_not_a_percent(self):
        self.assertEqual(formats.infer("−1.0 pp"), {"type": "number", "decimals": 1, "units": "none",
                                                     "suffix": "pp", "negative": "minus"})
        self.assertTrue(formats.same_form("−1.0 pp", PP))
        self.assertTrue(formats.same_form("+1.9 pp", PP))  # the unit and the plus: decisions/124

    def test_real_percent_still_a_percent(self):
        self.assertEqual(formats.infer("−5.4%")["type"], "percent")

    def test_pp_row_value_matches_with_format(self):
        e = reconcile._entry("Region Category", "East | Total", ["Margin vs 2024"], -0.952759,
                             fmt=PP)
        (f,) = match(text("−1.0 pp", cell={"row": "East total", "col": "Margin vs 2024", "group": "East"}), [e])
        self.assertEqual(f["status"], "matched")

    def test_equal_marks_prefer_the_one_with_the_pages_form(self):
        e = reconcile._entry
        ents = [e("Region Category", "Total", ["vs 2024"], 0.1856, fmt={"type": "percent", "decimals": 1}),
                e("Region Category", "Total", ["Margin vs 2024"], 0.165, fmt=PP)]
        (f,) = match(text("+0.2 pp", cell={"row": "Grand total", "col": "Margin vs 2024"}), ents)
        self.assertEqual((f["status"], f["workbook"]), ("matched", "Region Category [Total] = 0.165"))


class MonthLabels(unittest.TestCase):
    def test_month_label_binds_to_the_date_axis(self):
        e = reconcile._entry
        total = e("Channel Mix", "", ["revenue", "Revenue", "total"], 2509550.0, part="total")
        total["whole"] = True
        ents = [e("By Month", "2025-01", ["Revenue K"], 195.4), e("By Month", "2025-02", ["Revenue K"], 121.3), total]
        ctx = "Jan Revenue by month 195"
        fact = {"number": "195", "text": ctx, "context": ctx, "box": [0, 0, 1, 1], "start": None, "data": True,
                "chart": "echarts", "status": None, "value": 195.0, "step": 1, "suffix": "", "pct": False,
                "shown": "195", "paren": False}
        (f,) = match(fact, ents)
        self.assertEqual((f["status"], f["workbook"]), ("matched", "By Month [2025-01] = 195.4"))


if __name__ == "__main__":
    unittest.main()
