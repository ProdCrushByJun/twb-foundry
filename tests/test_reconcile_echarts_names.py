"""Reconcile, acceptance/echarts findings (decisions/119): a number inside a member's name is no value; the month
label of a date axis binds to the sheet with the date axis."""
import unittest

from tbuilder import reconcile
from test_reconcile import page, text


def match(item, ents, spec=None, prof=None):
    fs = reconcile.facts(page(item))
    reconcile._match(fs, ents, reconcile._Names(spec or {}, ents, prof), [])
    return fs


E = reconcile._entry


class NumbersInNames(unittest.TestCase):
    def ents(self):
        return [E("Top Products", "Laptop Pro 14", ["Revenue"], 1094.22),
                E("Top Products", "Laptop Pro 14", ["Orders"], 104), E("Top Products", "Phone", ["Orders"], 14)]

    def test_number_in_a_row_name_is_skipped(self):
        (f,) = match(text("Laptop Pro 14", cell={"row": "Laptop Pro 14", "col": "Product"}), self.ents())
        self.assertEqual((f["status"], f["reason"]), ("skipped", "part of a name"))

    def test_value_next_to_the_name_is_still_checked(self):
        fs = match(text("Laptop Pro 14: 104 orders"), self.ents())
        self.assertEqual([(f["number"], f["status"]) for f in fs], [("14", "skipped"), ("104", "matched")])
        fs = match(text("Laptop Pro 14: 105 orders"), self.ents())
        self.assertNotEqual(fs[1]["status"], "skipped")
        self.assertNotEqual(fs[1]["status"], "matched")

    def test_plain_number_is_a_value(self):
        (f,) = match(text("Phone 14", cell={"row": "Phone", "col": "Orders"}), self.ents())
        self.assertEqual(f["status"], "matched")

    def test_name_from_the_data_not_shown_by_a_mark(self):
        class Col:
            name, datatype, distinct = "Product", "string", ["iPhone 15"]

        class Prof:
            columns = [Col]
        (f,) = match(text("iPhone 15 sold"), [E("S", "", ["Orders"], 7)], prof=Prof)
        self.assertEqual(f["status"], "skipped")


class MonthLabelBindsToDateAxis(unittest.TestCase):
    def ents(self):
        return [E("Channel Mix", "Total", ["Revenue K", "Revenue"], 1000),  # shares more words than the line
                E("By Month", "2025-01", ["Revenue K"], 1000), E("By Month", "2025-02", ["Revenue K"], 900)]

    def test_date_axis_sheet_wins(self):
        spec = {"sheets": [{"name": "By Month", "type": "line", "date": {"field": "Order Date", "level": "month"}},
                           {"name": "Channel Mix", "type": "donut"}]}
        (f,) = match(text("Jan Revenue K 1,000"), self.ents(), spec)
        self.assertEqual(f["workbook"], "By Month [2025-01] = 1000")

    def test_no_month_in_the_text_changes_nothing(self):
        (f,) = match(text("Revenue K 1,000"), self.ents(), {"sheets": [{"name": "By Month", "date": {}}]})
        self.assertEqual(f["status"], "matched")


if __name__ == "__main__":
    unittest.main()
