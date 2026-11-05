"""A number whose label qualifies the measure by a data value ('Furniture Sales') is not the measure's total (decisions/114)."""
import unittest

from tbuilder import reconcile
from tbuilder.profile import Column, Profile
from test_reconcile import text

E = reconcile._entry
PROF = Profile(path="x.csv", columns=[Column("Category", "string", ["Furniture", "Technology"]),
                                      Column("Sales", "real")], rows=[])


def run(t, ents, prof=PROF):
    fs = reconcile.facts({"texts": [text(t)]})
    reconcile._match(fs, ents, reconcile._Names({}, ents, prof), [])
    return [f for f in fs if f["status"] != "skipped"]


class QualifiedPrefilter(unittest.TestCase):
    """qualified looks only at the values in the text (decisions/179): the answer is the one of all the values."""
    VALUES = ["Furniture", "Office Supplies", "West - East", "abc -", "Über", "resolved", "ORD-000123"]

    def names(self, values):
        prof = Profile(path="x.csv", columns=[Column("Category", "string", values), Column("Sales", "real")], rows=[])
        return reconcile._Names({}, [E("KPI", "", ["Sales"], 1.0)], prof)

    def test_value_before_the_measure(self):
        names = self.names(self.VALUES)
        self.assertTrue(names.qualified("furniture sales $51,516", ["Sales"]))
        self.assertTrue(names.qualified("total, office supplies sales: 12", ["Sales"]))

    def test_value_elsewhere_or_inside_a_word_says_nothing(self):
        names = self.names(self.VALUES)
        self.assertFalse(names.qualified("sales furniture", ["Sales"]))
        self.assertFalse(names.qualified("furniture, total sales", ["Sales"]))
        self.assertFalse(names.qualified("mean time to unresolved sales", ["Sales"]))

    def test_absent_values_change_nothing(self):
        few, many = self.names(self.VALUES), self.names(self.VALUES + [f"ORD-{i:06}" for i in range(1000, 3000)])
        for ctx in ("furniture sales 1", "sales 1", "ord-000123 sales 1", "ord-001000", "west-east sales 2"):
            self.assertEqual(few.qualified(ctx, ["Sales"]), many.qualified(ctx, ["Sales"]), ctx)

    def test_same_answer_as_every_value_tried(self):
        names = self.names(self.VALUES)
        tags = (["Sales"], ["- Sales"], ["Sales", "Profit"], ["  SALES "], [""], [])
        texts = ("furniture sales 1", "abc-sales 1", "abc- sales 1", "west-east sales", "west - east sales 3",
                 "über sales", "office supplies profit", "furniture", "no value 12", "resolved-sales",
                 "ord-000123 sales", "xfurniture sales", "furniture salesman")
        for ctx in texts:
            ctx = reconcile._norm(ctx)
            for t in tags:
                brute = any(reconcile._mentions(ctx, f"{q} {reconcile._norm(str(m))}")
                            for q in names.qualifiers for m in t)
                self.assertEqual(names.qualified(ctx, t), brute, (ctx, t))
                self.assertEqual(names.qualified(ctx, t), brute, "the remembered answer")


class QualifiedLabel(unittest.TestCase):
    kpi = [E("KPI", "", ["Sales"], 75627.9)]

    def test_slice_value_is_not_a_mismatch_against_the_kpi(self):
        (f,) = run("Furniture Sales $51,516", self.kpi)
        self.assertNotIn(f["status"], ("mismatch", "matched"))
        self.assertNotIn("KPI", f.get("workbook", ""))

    def test_plain_kpi_still_checked(self):
        self.assertEqual(run("Sales $75,628", self.kpi)[0]["status"], "matched")
        self.assertEqual(run("Sales $70,000", self.kpi)[0]["status"], "mismatch")

    def test_slice_entry_is_still_compared(self):
        ents = self.kpi + [E("Category", "Furniture", ["Sales"], 51515.6)]
        self.assertEqual(run("Furniture Sales $51,516", ents)[0]["status"], "matched")
        self.assertEqual(run("Furniture Sales $9,000", ents)[0]["status"], "mismatch")

    def test_value_inside_the_measure_name_is_no_qualifier(self):
        prof = Profile(path="x.csv", columns=[Column("Segment", "string", ["Sales"])], rows=[])
        self.assertEqual(run("Sales $75,628", self.kpi, prof)[0]["status"], "matched")


if __name__ == "__main__":
    unittest.main()
