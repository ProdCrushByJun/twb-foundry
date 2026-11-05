"""Formula subset: parsing, type checks, aggregate/row levels and evaluation."""
import datetime as dt
import unittest

from tbuilder.formula import CalcSet, FormulaError, Func, Str, View, calc_id, parse

COLS = {"Sales": "real", "Profit": "real", "Quantity": "integer", "Region": "string",
        "Order Date": "date", "Type": "string", "Closures": "integer"}
ROWS = [
    {"Sales": "100", "Profit": "10", "Quantity": "2", "Region": "East", "Order Date": "2024-01-05",
     "Type": "Incidents", "Closures": "3"},
    {"Sales": "300", "Profit": "-30", "Quantity": "1", "Region": "West", "Order Date": "2024-02-01",
     "Type": "Tasks", "Closures": "5"},
    {"Sales": "", "Profit": "", "Quantity": "4", "Region": "East", "Order Date": "2024-02-03",
     "Type": "Incidents", "Closures": "2"},
]


def calcs(*specs):
    return CalcSet([{"name": n, "formula": f, **extra} for n, f, *rest in specs
                    for extra in [rest[0] if rest else {}]], COLS)


class Valid(unittest.TestCase):
    def test_ratio_is_aggregate_real(self):
        c = calcs(("Profit Ratio", "SUM([Profit]) / SUM([Sales])"))["Profit Ratio"]
        self.assertTrue(c.is_agg)
        self.assertEqual(c.datatype, "real")
        self.assertEqual(c.raw_deps, ["Profit", "Sales"])

    def test_conditional_sum_row_level_integer(self):
        c = calcs(("Inc", 'IF [Type] = "Incidents" THEN [Closures] END'))["Inc"]
        self.assertFalse(c.is_agg)
        self.assertEqual(c.datatype, "integer")

    def test_string_dimension(self):
        c = calcs(("Size", 'IF [Sales] >= 200 THEN "Large" ELSEIF [Sales] > 0 THEN "Small" ELSE "None" END'))["Size"]
        self.assertEqual((c.datatype, c.is_agg), ("string", False))

    def test_calc_references_calc_and_xml_uses_internal_name(self):
        cs = calcs(("Inc", 'IF [Type] = "Incidents" THEN [Closures] END'),
                   ("Inc Share", "SUM([Inc]) / SUM([Closures])"))
        c = cs["Inc Share"]
        self.assertEqual(c.calc_deps, ["Inc"])
        self.assertEqual(c.raw_deps, ["Closures", "Type"])
        self.assertEqual(c.xml_formula, f"SUM([{calc_id('Inc')}]) / SUM([Closures])")

    def test_keywords_case_insensitive_and_single_quotes(self):
        c = calcs(("X", "if [Region] = 'East' then 1 else 0 end"))["X"]
        self.assertEqual(c.datatype, "integer")

    def test_calc_id_is_stable_19_digits(self):
        self.assertEqual(calc_id("Profit Ratio"), calc_id("Profit Ratio"))
        self.assertRegex(calc_id("Profit Ratio"), r"^Calculation_\d{19}$")


class Evaluates(unittest.TestCase):
    def test_aggregate_ratio(self):
        cs = calcs(("PR", "SUM([Profit]) / SUM([Sales])"))
        self.assertAlmostEqual(cs.agg_value("PR", ROWS), -20 / 400)

    def test_conditional_sum(self):
        cs = calcs(("Inc", 'IF [Type] = "Incidents" THEN [Closures] END'),
                   ("Inc Total", "SUM([Inc])"))
        self.assertEqual([cs.row_value("Inc", r) for r in ROWS], [3, None, 2])
        self.assertEqual(cs.agg_value("Inc Total", ROWS), 5)

    def test_nulls_division_by_zero_zn(self):
        cs = calcs(("Div", "[Profit] / ([Quantity] - [Quantity])"), ("Z", "ZN([Sales])"))
        self.assertIsNone(cs.row_value("Div", ROWS[0]))
        self.assertEqual(cs.row_value("Z", ROWS[2]), 0)

    def test_count_countd_avg_round(self):
        cs = calcs(("N", "COUNTD([Region])"), ("A", "ROUND(AVG([Sales]), 1)"), ("C", "COUNT([Sales])"))
        self.assertEqual(cs.agg_value("N", ROWS), 2)
        self.assertEqual(cs.agg_value("A", ROWS), 200.0)
        self.assertEqual(cs.agg_value("C", ROWS), 2)

    def test_round_half_away_from_zero(self):
        cs = calcs(("R", "ROUND([Sales] / 200)"))
        self.assertEqual(cs.row_value("R", ROWS[0]), 1.0)  # 0.5 -> 1, not banker's 0


def lods(*specs):
    return CalcSet([{"name": n, "formula": f} for n, f in specs], COLS, ROWS)


class Lods(unittest.TestCase):
    def test_fixed_by_dimension_is_row_level(self):
        cs = lods(("Region Sales", "{FIXED [Region] : SUM([Sales])}"))
        c = cs["Region Sales"]
        self.assertEqual((c.datatype, c.is_agg), ("real", False))
        self.assertEqual(c.raw_deps, ["Region", "Sales"])
        self.assertEqual([cs.row_value("Region Sales", r) for r in ROWS], [100, 300, 100])

    def test_table_scoped_and_shorthand(self):
        cs = lods(("T1", "{FIXED : SUM([Sales])}"), ("T2", "{SUM([Sales])}"))
        self.assertEqual(cs.row_value("T1", ROWS[0]), 400)
        self.assertEqual(cs.row_value("T2", ROWS[1]), 400)

    def test_share_of_group_aggregate(self):
        cs = lods(("Share", "SUM([Quantity]) / MIN({FIXED [Region] : SUM([Quantity])})"))
        self.assertTrue(cs["Share"].is_agg)
        east = [r for r in ROWS if r["Region"] == "East"]
        self.assertAlmostEqual(cs.agg_value("Share", east[:1]), 2 / 6)

    def test_first_date_flag_compares_dates(self):
        cs = lods(("First", "IF [Order Date] = {FIXED [Region] : MIN([Order Date])} THEN 1 ELSE 0 END"))
        self.assertEqual([cs.row_value("First", r) for r in ROWS], [1, 1, 0])

    def test_nested_lod(self):
        cs = lods(("Max Region", "{FIXED : MAX({FIXED [Region] : SUM([Quantity])})}"))
        self.assertEqual(cs.row_value("Max Region", ROWS[0]), 6)  # East 2+4

    def test_fixed_ignores_view_filters(self):
        cs = lods(("T", "{FIXED : SUM([Quantity])}"), ("Agg", "MIN([T])"))
        self.assertEqual(cs.agg_value("Agg", ROWS[:1]), 7)  # computed on all rows, not the filtered group

    def test_rejects(self):
        for formula, msg in [
            ("[Sales] / {INCLUDE [Region] : SUM([Sales])}", "whole formula or the direct argument"),
            ("{FIXED [Region] : AVG({EXCLUDE [Type] : SUM([Sales])})}", "inside another LOD"),
            ("{FIXED [Region] : [Sales]}", "must be an aggregate"),
            ("SUM([Sales]) / {FIXED : SUM([Sales])}", "cannot mix aggregate"),
            ("{FIXED [Region] SUM([Sales])}", "expected"),
        ]:
            with self.subTest(formula=formula), self.assertRaisesRegex(FormulaError, msg):
                lods(("X", formula))
        with self.assertRaisesRegex(FormulaError, "aggregate calculation"):
            lods(("A", "SUM([Sales])"), ("X", "{FIXED [A] : SUM([Sales])}"))



def view(*dims):
    return View([(d, lambda r, d=d: r[d]) for d in dims], ROWS)


class IncludeExclude(unittest.TestCase):
    def test_include_aggregates_lod_level_values(self):
        cs = lods(("Avg Type Sales", "AVG({INCLUDE [Type] : SUM([Quantity])})"))
        east = [r for r in ROWS if r["Region"] == "East"]  # both rows Type=Incidents -> one group of 6
        self.assertEqual(cs.agg_value("Avg Type Sales", east, view("Region")), 6)
        # no view dims: per-type sums Incidents 6, Tasks 1 -> average over 2 groups, not over 3 rows
        self.assertEqual(cs.agg_value("Avg Type Sales", ROWS, view()), 3.5)

    def test_include_whole_formula_returns_group_values(self):
        cs = lods(("Per Region", "{INCLUDE [Region] : SUM([Quantity])}"))
        c = cs["Per Region"]
        self.assertTrue(c.view_lod and c.uses_view_lod and not c.is_agg)
        self.assertEqual(sorted(cs.view_values("Per Region", ROWS, view())), [1, 6])

    def test_exclude_replicates_coarser_value(self):
        cs = lods(("Region Total", "SUM({EXCLUDE [Type] : SUM([Quantity])})"))
        mark = [r for r in ROWS if r["Region"] == "East" and r["Type"] == "Incidents"]
        self.assertEqual(cs.agg_value("Region Total", mark, view("Region", "Type")), 6)
        west = [r for r in ROWS if r["Region"] == "West"]
        self.assertEqual(cs.agg_value("Region Total", west, view("Region", "Type")), 1)

    def test_share_via_exclude_equals_fixed_share(self):
        cs = lods(("Share X", "SUM([Quantity]) / SUM({EXCLUDE [Type] : SUM([Quantity])})"),
                  ("Share F", "SUM([Quantity]) / MIN({FIXED [Region] : SUM([Quantity])})"))
        for region in ("East", "West"):
            mark = [r for r in ROWS if r["Region"] == region][:1]
            v = view("Region", "Type")
            self.assertAlmostEqual(cs.agg_value("Share X", mark, v), cs.agg_value("Share F", mark, v))

    def test_view_lod_calc_is_not_row_level(self):
        cs = lods(("P", "{INCLUDE [Region] : SUM([Quantity])}"))
        with self.assertRaises(ValueError):
            cs.row_value("P", ROWS[0])


class Rejects(unittest.TestCase):
    def assertRejects(self, msg, *specs):
        with self.assertRaisesRegex(FormulaError, msg):
            calcs(*specs)

    def test_unknown_field(self):
        self.assertRejects("unknown field", ("X", "SUM([Revenue])"))

    def test_unknown_function(self):
        self.assertRejects("not supported", ("X", 'REGEXP_MATCH([Region], "E.*")'))

    def test_mixing_aggregate_and_row(self):
        self.assertRejects("cannot mix aggregate", ("X", "SUM([Sales]) / [Quantity]"))

    def test_nested_aggregate(self):
        self.assertRejects("nested aggregation", ("X", "SUM(AVG([Sales]))"))

    def test_aggregate_calc_inside_aggregate(self):
        self.assertRejects("already aggregated", ("A", "SUM([Sales])"), ("B", "SUM([A])"))

    def test_type_errors(self):
        self.assertRejects("needs a number", ("X", "SUM([Region])"))
        self.assertRejects("cannot compare", ("X", '[Sales] = "East"'))
        self.assertRejects("incompatible types", ("X", 'IF [Sales] > 0 THEN 1 ELSE "no" END'))
        self.assertRejects("must be boolean", ("X", "IF [Sales] THEN 1 END"))

    def test_cycle(self):
        self.assertRejects("cycle", ("A", "[B] + 1"), ("B", "[A] + 1"))

    def test_name_collisions(self):
        self.assertRejects("same name as a CSV column", ("Sales", "[Profit]"))
        self.assertRejects("duplicate", ("A", "1"), ("A", "2"))

    def test_syntax(self):
        self.assertRejects("expected", ("X", "IF [Sales] > 0 THEN 1"))
        self.assertRejects("unexpected", ("X", "SUM([Sales]) )"))
        with self.assertRaises(FormulaError):
            parse("[Sales] $ 2")

    def test_percent_needs_number(self):
        self.assertRejects("percent format", ("X", "[Region]", {"format": "percent"}))
        self.assertRejects("percent format needs a numeric result, got date",
                           ("X", "MAX([Order Date])", {"format": "percent"}))


class Dates(unittest.TestCase):
    def test_parse_keeps_level_literal(self):
        node = parse("datetrunc('month', [Order Date])")
        self.assertIsInstance(node, Func)
        self.assertEqual((node.name, node.args[0]), ("DATETRUNC", Str("month")))
        self.assertEqual(parse("DATEADD('month', -1, [Order Date])").name, "DATEADD")

    def test_types_levels_and_xml(self):
        cs = calcs(("M", "DATETRUNC('month', [Order Date])"), ("Prev", "DATEADD('month', -1, [M])"),
                   ("Last", "MAX([Order Date])"), ("Last M", "DATETRUNC('month', MAX([Order Date]))"),
                   ("Is Prev", "[M] = DATEADD('month', -1, [M])"))
        self.assertEqual([(cs[n].datatype, cs[n].is_agg) for n in ("M", "Prev", "Last", "Last M", "Is Prev")],
                         [("date", False), ("date", False), ("date", True), ("date", True), ("boolean", False)])
        self.assertEqual(cs["M"].xml_formula, "DATETRUNC('month', [Order Date])")
        self.assertEqual(cs["Prev"].xml_formula, f"DATEADD('month', -1, [{calc_id('M')}])")
        self.assertEqual((cs["Prev"].calc_deps, cs["Prev"].raw_deps), (["M"], ["Order Date"]))

    def test_fixed_max_date_is_row_level_date(self):
        cs = lods(("Last Date", "{FIXED : MAX([Order Date])}"))
        self.assertEqual((cs["Last Date"].datatype, cs["Last Date"].is_agg), ("date", False))
        self.assertEqual(cs.row_value("Last Date", ROWS[0]), dt.date(2024, 2, 3))

    def test_truncate_and_add(self):
        for formula, src, want in [
            ("DATETRUNC('week', [Order Date])", "2024-03-10", "2024-03-04"),  # Sunday -> previous Monday
            ("DATETRUNC('week', [Order Date])", "2024-03-11", "2024-03-11"),  # Monday stays
            ("DATETRUNC('week', [Order Date])", "2023-01-01", "2022-12-26"),  # week starts in the previous year
            ("DATETRUNC('day', [Order Date])", "2024-08-15", "2024-08-15"),
            ("DATETRUNC('month', [Order Date])", "2024-08-15", "2024-08-01"),
            ("DATETRUNC('quarter', [Order Date])", "2024-08-15", "2024-07-01"),
            ("DATETRUNC('quarter', [Order Date])", "2024-12-31", "2024-10-01"),
            ("DATETRUNC('year', [Order Date])", "2024-08-15", "2024-01-01"),
            ("DATEADD('month', 1, [Order Date])", "2025-01-31", "2025-02-28"),  # clamped to the month end
            ("DATEADD('month', 1, [Order Date])", "2024-01-31", "2024-02-29"),
            ("DATEADD('year', -1, [Order Date])", "2024-02-29", "2023-02-28"),
            ("DATEADD('month', -1, [Order Date])", "2025-01-15", "2024-12-15"),
            ("DATEADD('quarter', 1, [Order Date])", "2024-11-30", "2025-02-28"),
            ("DATEADD('week', -1, [Order Date])", "2025-01-03", "2024-12-27"),
            ("DATEADD('day', 1, [Order Date])", "2024-12-31", "2025-01-01"),
            ("DATEADD('month', [Quantity] * -12, [Order Date])", "2024-05-20", "2022-05-20"),
        ]:
            with self.subTest(formula=formula, src=src):
                cs = calcs(("X", formula))
                row = {"Order Date": src, "Quantity": "2"}
                self.assertEqual(cs.row_value("X", row), dt.date.fromisoformat(want))

    def test_null_date_stays_null(self):
        cs = calcs(("X", "DATEADD('day', 1, DATETRUNC('month', [Order Date]))"))
        self.assertIsNone(cs.row_value("X", {"Order Date": ""}))

    def test_period_vs_previous_through_fixed_last_date(self):
        cs = lods(("Last Date", "{FIXED : MAX([Order Date])}"),  # 2024-02-03
                  ("This", "SUM(IF DATETRUNC('month', [Order Date]) = DATETRUNC('month', [Last Date]) "
                           "THEN [Quantity] END)"),
                  ("Prev", "SUM(IF DATETRUNC('month',[Order Date]) = "
                           "DATEADD('month',-1,DATETRUNC('month',[Last Date])) THEN [Quantity] END)"),
                  ("LY", "SUM(IF DATETRUNC('month', [Order Date]) = "
                         "DATEADD('year', -1, DATETRUNC('month', [Last Date])) THEN [Quantity] END)"))
        self.assertEqual(cs["This"].calc_deps, ["Last Date"])
        self.assertEqual(cs.agg_value("This", ROWS), 1 + 4)
        self.assertEqual(cs.agg_value("Prev", ROWS), 2)
        self.assertIsNone(cs.agg_value("LY", ROWS))  # no rows in 2023-02
        self.assertIsNone(cs.agg_value("This", ROWS[:1]))  # January mark; [Last Date] still from all rows

    def test_aggregated_date(self):
        cs = calcs(("Last M", "DATETRUNC('month', MAX([Order Date]))"), ("First", "MIN([Order Date])"))
        self.assertEqual(cs.agg_value("Last M", ROWS), dt.date(2024, 2, 1))
        self.assertEqual(cs.agg_value("First", ROWS), dt.date(2024, 1, 5))

    def test_rejects(self):
        for formula, msg in [
            ("DATETRUNC('second', [Order Date])", "DATETRUNC level must be a string literal, one of 'year'"),
            ("DATETRUNC([Region], [Order Date])", "level must be a string literal"),
            ("DATEADD('fortnight', 1, [Order Date])", "level must be"),
            ("DATETRUNC('month')", "takes 2 argument"),
            ("DATETRUNC('month', [Sales])", "DATETRUNC needs a date, got real"),
            ("DATEADD('month', 1, [Region])", "DATEADD needs a date, got string"),
            ("DATEADD('month', 1.5, [Order Date])", "amount must be an integer, got real"),
            ("DATEADD('month', [Sales], [Order Date])", "amount must be an integer, got real"),
            ("[Order Date] + 1", r"'\+' needs numbers, got date and integer"),
            ("DATETRUNC('month', [Order Date]) - [Order Date]", "'-' needs numbers"),
            ("[Order Date] > 5", "cannot compare date with integer"),
            ("DATETRUNC('month', [Order Date]) = [Sales]", "cannot compare date with real"),
            ("SUM([Order Date])", "SUM needs a number, got date"),
            ("AVG(DATETRUNC('month', [Order Date]))", "AVG needs a number, got date"),
            ("{FIXED : SUM([Order Date])}", "SUM needs a number, got date"),
            ("DATEADD('day', 1, MAX([Order Date])) = [Order Date]", "cannot mix aggregate"),
        ]:
            with self.subTest(formula=formula), \
                    self.assertRaisesRegex(FormulaError, "calculated field 'X': .*" + msg):
                lods(("X", formula))


if __name__ == "__main__":
    unittest.main()
