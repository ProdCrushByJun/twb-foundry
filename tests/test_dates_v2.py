"""Dates v2 (decisions/051): ISO with 'T', no leading zeros, a time after DD.MM / DD/MM / MM/DD; datetime in formulas
(hour / minute levels); range bounds with a time of day; expected == pandas on the golden data; gate mutations."""
import copy
import datetime as dt
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import dates, expected, gate
from tbuilder import spec as spec_mod
from tbuilder.build import build
from tbuilder.formula import CalcSet, FormulaError
from tbuilder.profile import profile_csv
from test_dates import csv_file, one_column
from test_roundtrip import OUT, ROOT, SPECS, canon, normalize, read_twbx

FIXTURE = Path(__file__).parent / "fixtures" / "dates_v2"
DATES_V2 = json.loads((SPECS / "dates_v2.json").read_text(encoding="utf-8"))
DATES_V2_US = json.loads((SPECS / "dates_v2_us.json").read_text(encoding="utf-8"))
CSV = ROOT / "data" / "sample" / "sales_dates_v2.csv"
CSV_US = ROOT / "data" / "sample" / "sales_dates_v2_us.csv"


class Formats(unittest.TestCase):
    def assertDates(self, values, label, datatype, iso, locale):
        p, c = one_column(*values)
        self.assertEqual((c.datatype, c.date_format.label), (datatype, label))
        self.assertEqual([r["D"] for r in p.rows], iso)
        self.assertEqual(p.locale, locale)

    def test_iso_with_t(self):
        self.assertDates(["2024-03-15T14:30", "2024-02-01T09:05:07"], "YYYY-MM-DDTHH:MM[:SS]", "datetime",
                         ["2024-03-15 14:30:00", "2024-02-01 09:05:07"], None)

    def test_dots_without_leading_zeros(self):
        self.assertDates(["5.1.2024", "15.3.2024", "01.02.2024"], "DD.MM.YYYY", "date",
                         ["2024-01-05", "2024-03-15", "2024-02-01"], "ru_RU")

    def test_slashes_without_leading_zeros(self):
        self.assertDates(["1/5/2024", "12/28/2024"], "MM/DD/YYYY", "date", ["2024-01-05", "2024-12-28"], "en_US")
        self.assertDates(["1/5/2024", "28/12/2024"], "DD/MM/YYYY", "date", ["2024-05-01", "2024-12-28"], "ru_RU")

    def test_dots_with_time(self):
        self.assertDates(["15.03.2024 14:30", "5.1.2024 9:05:07", "31.12.2024 23:59"], "DD.MM.YYYY HH:MM[:SS]",
                         "datetime", ["2024-03-15 14:30:00", "2024-01-05 09:05:07", "2024-12-31 23:59:00"], "ru_RU")

    def test_slashes_with_time(self):
        self.assertDates(["1/5/2024 9:30", "12/28/2024 14:05"], "MM/DD/YYYY HH:MM[:SS]", "datetime",
                         ["2024-01-05 09:30:00", "2024-12-28 14:05:00"], "en_US")
        self.assertDates(["28/12/2024 14:05:59", "1/5/2024 0:00"], "DD/MM/YYYY HH:MM[:SS]", "datetime",
                         ["2024-12-28 14:05:59", "2024-05-01 00:00:00"], "ru_RU")

    def test_iso_t_reads_in_any_locale(self):
        p = profile_csv(csv_file("A,B", "2024-03-15T14:30,1/28/2024"))
        self.assertEqual((p.col("A").datatype, p.locale), ("datetime", "en_US"))

    def test_golden_data(self):
        """The golden CSVs: every v2 shape, the first 4 089 rows readable both day-first and month-first."""
        ru, us = profile_csv(CSV), profile_csv(CSV_US)
        self.assertEqual([(c.name, c.date_format.label) for c in ru.columns if c.date_format],
                         [("Ordered At", "YYYY-MM-DDTHH:MM[:SS]"), ("Shipped At", "DD.MM.YYYY HH:MM[:SS]"),
                          ("Paid On", "DD.MM.YYYY"), ("Booked On", "DD/MM/YYYY")])
        self.assertEqual([(c.name, c.date_format.label) for c in us.columns if c.date_format],
                         [("Ordered At", "MM/DD/YYYY HH:MM[:SS]"), ("Paid On", "MM/DD/YYYY"),
                          ("Logged At", "YYYY-MM-DDTHH:MM[:SS]")])
        self.assertEqual((ru.locale, us.locale), ("ru_RU", "en_US"))
        first = ru.rows[:4089]  # 'Booked On' 1/1..12/12: both orders would read it; the data decides only later
        self.assertTrue(all(int(r["Booked On"][8:]) <= 12 for r in first))


class Refusals(unittest.TestCase):
    def assertRefused(self, values, text):
        with self.assertRaises(ValueError) as e:
            one_column(*values)
        self.assertIn(text, str(e.exception))

    def test_ambiguous_slashes_with_time(self):
        self.assertRefused(["1/2/2024 10:00", "3/4/2024 11:30"], "ambiguous")

    def test_unsupported_shapes_among_dates(self):
        for values in (["2024-03-15", "2024-3-5"], ["15.03.2024 10:00", "15.03.2024 14h30"]):
            with self.subTest(values=values):
                self.assertRefused(values, "format not supported yet")

    def test_mixed_shapes(self):
        self.assertRefused(["2024-03-15T14:30", "2024-03-15 14:30"], "mixed date formats")
        self.assertRefused(["15.03.2024", "16.03.2024 10:00"], "mixed date formats")

    def test_impossible_times(self):
        self.assertRefused(["15.03.2024 24:00", "16.03.2024 10:00"], "not a valid DD.MM.YYYY HH:MM[:SS] date")
        self.assertRefused(["2024-03-15T10:60"], "not a valid YYYY-MM-DDTHH:MM[:SS] date")
        self.assertRefused(["31/2/2024", "1/3/2024"], "not a valid DD/MM/YYYY date")


def calc(formula, row=None, columns=None):
    """One row-level calc evaluated on one row of datetime columns A, B and a date column D."""
    columns = columns or {"A": "datetime", "B": "datetime", "D": "date"}
    row = row or {"A": "2024-03-15 10:59:30", "B": "2024-03-15 11:00:00", "D": "2024-03-15"}
    cs = CalcSet([{"name": "X", "formula": formula}], columns, [row])
    return cs.row_value("X", row), cs.calcs["X"].datatype


class DatetimeFormulas(unittest.TestCase):
    def test_hour_and_minute_levels(self):
        self.assertEqual(calc("DATEPART('hour', [A])"), (10, "integer"))
        self.assertEqual(calc("DATEPART('minute', [A])"), (59, "integer"))
        self.assertEqual(calc("DATENAME('hour', [A])"), ("10", "string"))
        self.assertEqual(calc("DATETRUNC('hour', [A])"), (dt.datetime(2024, 3, 15, 10), "datetime"))
        self.assertEqual(calc("DATETRUNC('minute', [A])"), (dt.datetime(2024, 3, 15, 10, 59), "datetime"))

    def test_datediff_counts_boundaries(self):
        self.assertEqual(calc("DATEDIFF('hour', [A], [B])")[0], 1)  # 10:59:30 -> 11:00
        self.assertEqual(calc("DATEDIFF('minute', [A], [B])")[0], 1)
        self.assertEqual(calc("DATEDIFF('hour', [B], [A])")[0], -1)
        same = {"A": "2024-03-15 10:00:00", "B": "2024-03-15 10:59:59", "D": "2024-03-15"}
        self.assertEqual(calc("DATEDIFF('hour', [A], [B])", same)[0], 0)
        night = {"A": "2024-03-15 23:59:00", "B": "2024-03-16 00:01:00", "D": "2024-03-15"}
        self.assertEqual(calc("DATEDIFF('day', [A], [B])", night)[0], 1)
        self.assertEqual(calc("DATEDIFF('hour', [A], [B])", night)[0], 1)
        self.assertEqual(calc("DATEDIFF('day', [D], [B])", night)[0], 1)  # a date and a datetime, by days

    def test_date_levels_on_a_datetime(self):
        self.assertEqual(calc("DATETRUNC('month', [A])"), (dt.datetime(2024, 3, 1), "datetime"))
        self.assertEqual(calc("DATETRUNC('week', [A])")[0], dt.datetime(2024, 3, 11))  # Monday, midnight
        self.assertEqual(calc("DATEPART('week', [A])")[0], 11)
        self.assertEqual(calc("YEAR([A]) * 100 + MONTH([A])")[0], 202403)
        self.assertEqual(calc("DATEPART('weekday', [A])")[0], 6)  # Friday, Sunday = 1

    def test_dateadd(self):
        self.assertEqual(calc("DATEADD('hour', 14, [A])")[0], dt.datetime(2024, 3, 16, 0, 59, 30))
        self.assertEqual(calc("DATEADD('minute', -60, [A])")[0], dt.datetime(2024, 3, 15, 9, 59, 30))
        self.assertEqual(calc("DATEADD('month', 1, [A])")[0], dt.datetime(2024, 4, 15, 10, 59, 30))
        self.assertEqual(calc("DATEADD('hour', 1, [A]) < [B]"), (False, "boolean"))

    def test_a_date_stays_a_date(self):
        self.assertEqual(calc("DATETRUNC('month', [D])"), (dt.date(2024, 3, 1), "date"))

    def test_refusals(self):
        for formula, text in [("DATEPART('hour', [D])", "level 'hour' needs a datetime, got date"),
                              ("DATETRUNC('minute', [D])", "level 'minute' needs a datetime, got date"),
                              ("DATEDIFF('hour', [D], [A])", "level 'hour' needs a datetime, got date"),
                              ("DATEPART('second', [A])", "'hour', 'minute'"),
                              ("DATETIME([D])", "DATETIME of a date stays a date"),  # decisions/055
                              ("[A] > [D]", "cannot compare datetime with date"),
                              ("SUM([A])", "SUM needs a number, got datetime")]:
            with self.subTest(formula=formula), self.assertRaisesRegex(FormulaError, text):
                calc(formula)

    def test_nulls(self):
        self.assertIsNone(calc("DATEDIFF('hour', [A], [B])", {"A": "2024-03-15 10:00:00", "B": "", "D": ""})[0])


class TimedRange(unittest.TestCase):
    PROF = profile_csv(CSV)

    def flt(self, field, **spec):
        return dates.DateFilter(self.PROF.col(field), {"field": field, "show_on": "Orders", "mode": "range", **spec},
                                self.PROF.rows)

    def test_keeps_up_to_the_moment(self):
        f = self.flt("Ordered At", min="2024-01-01 09:00", max="2024-12-31 18:00")
        self.assertEqual(f.moments(), (dt.datetime(2024, 1, 1, 9), dt.datetime(2024, 12, 31, 18)))
        self.assertTrue(f.keeps("2024-01-01 09:00:00") and f.keeps("2024-12-31 18:00:00"))
        self.assertFalse(f.keeps("2024-01-01 08:59:59") or f.keeps("2024-12-31 18:00:01") or f.keeps(""))

    def test_a_date_max_keeps_its_whole_day(self):
        f = self.flt("Ordered At", min="2024-01-01 09:00", max="2024-12-31")
        self.assertTrue(f.keeps("2024-12-31 23:59:59"))

    def test_xml_literals(self):
        el = self.flt("Ordered At", min="2024-01-01 09:00", max="2024-12-31 18:00:30").write(ET.Element("x"), "c")
        self.assertEqual((el.findtext("min"), el.findtext("max")), ("#2024-01-01 09:00:00#", "#2024-12-31 18:00:30#"))
        el = self.flt("Ordered At", min="2024-01-01", max="2024-12-31").write(ET.Element("x"), "c")
        self.assertEqual((el.findtext("min"), el.findtext("max")), ("#2024-01-01 00:00:00#", "#2024-12-31 23:59:59#"))

    def test_refusals(self):
        with self.assertRaisesRegex(ValueError, "has a time of day, 'Paid On' is a date column"):
            self.flt("Paid On", min="2024-01-01 09:00", max="2024-12-31")
        with self.assertRaisesRegex(ValueError, "is after max"):
            self.flt("Ordered At", min="2024-03-01 18:00", max="2024-03-01 09:00")

    def test_schema(self):
        s = copy.deepcopy(DATES_V2)
        spec_mod.validate(s)
        s["filters"][0]["min"] = "2024-01-01T09:00"
        with self.assertRaisesRegex(spec_mod.SpecError, "does not match"):
            spec_mod.validate(s)


class MatchesPandas(unittest.TestCase):
    """expected.compute on the golden specs == sums pandas computed with hand-written formats (pandas_sums.py)."""
    REF = json.loads((FIXTURE / "pandas_sums.json").read_text(encoding="utf-8"))

    def check(self, spec, name, csv):
        got = expected.compute(spec, csv)
        for sheet, values in self.REF[name].items():
            if sheet.startswith("_"):
                continue
            with self.subTest(sheet=sheet):
                shown = {k: v for k, v in got[sheet].items()} if sheet != "KPI" else {
                    k: got[sheet][k] for k in values}
                self.assertEqual(shown, values)

    def test_ru(self):
        self.check(DATES_V2, "dates_v2.json", CSV)

    def test_us(self):
        self.check(DATES_V2_US, "dates_v2_us.json", CSV_US)


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ru = built(DATES_V2, "dates_v2_xml")[0]
        cls.us = built(DATES_V2_US, "dates_v2_us_xml")[0]

    def columns(self, root):
        """The text connector's columns: name -> datatype."""
        return {c.get("name"): c.get("datatype") for c in root.find(".//relation/columns")}

    def test_types_and_locale(self):
        """No format or date-parse in the XML: Desktop reads the CSV by the column type and the text-file locale."""
        self.assertEqual({k: v for k, v in self.columns(self.ru).items() if v in ("date", "datetime")},
                         {"Ordered At": "datetime", "Shipped At": "datetime", "Paid On": "date",
                          "Booked On": "date"})
        for root, loc in ((self.ru, "ru_RU"), (self.us, "en_US")):
            self.assertEqual(root.find(".//relation/columns").get("locale"), loc)
            self.assertNotIn("date-parse", ET.tostring(root, encoding="unicode"))

    def test_timed_range_filter(self):
        f = next(f for f in self.ru.iter("filter") if f.get("class") == "quantitative" and f.find("min") is not None)
        self.assertEqual((f.findtext("min"), f.findtext("max")), ("#2024-01-01 09:00:00#", "#2024-12-31 18:00:00#"))


def built(spec, name):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb")), out


class GateCatchesDatesV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.path = built(DATES_V2, "dates_v2_gate")

    def mutant(self, fn):
        with zipfile.ZipFile(self.path) as src:
            members = {n: src.read(n) for n in src.namelist()}
        name = next(n for n in members if n.endswith(".twb"))
        root = etree.fromstring(members[name])
        fn(next(f for f in next(root.iter("shared-view")).findall("filter") if f.get("class") == "quantitative"))
        members[name] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
        path = Path(tempfile.mkdtemp()) / "mutant.twbx"
        with zipfile.ZipFile(path, "w") as z:
            for n, b in members.items():
                z.writestr(n, b)
        return path

    def assertCaught(self, fn, text):
        issues = [str(i) for i in gate.run(self.mutant(fn)) if i.check == "filters"]
        self.assertTrue(any(text in i for i in issues), f"expected [filters] ~ '{text}', got {issues}")

    def test_generated_passes(self):
        self.assertEqual(gate.run(self.path), [])

    def test_iso_t_literal(self):
        self.assertCaught(lambda f: f.find("min").__setattr__("text", "#2024-01-01T09:00:00#"),
                          "not a valid datetime literal")

    def test_time_without_seconds(self):
        self.assertCaught(lambda f: f.find("max").__setattr__("text", "#2024-12-31 18:00#"),
                          "not a valid datetime literal")

    def test_min_after_max_within_a_day(self):
        self.assertCaught(lambda f: f.find("min").__setattr__("text", "#2024-12-31 18:00:01#"), "is after max")


GOLDENS = {"dates_v2": ROOT / "golden" / "golden_dates_v2_2025_1.twbx",
           "dates_v2_us": ROOT / "golden" / "golden_dates_v2_us_2025_1.twbx"}


class Golden(unittest.TestCase):
    def test_rebuilds_identically(self):
        for name, golden in GOLDENS.items():
            if not golden.exists():  # saved from Desktop (hybrid golden, decisions/051)
                continue
            with self.subTest(golden=golden.name):
                spec = json.loads((SPECS / f"{name}.json").read_text(encoding="utf-8"))
                _, out = built(spec, f"{name}_roundtrip")
                self.assertEqual(canon(normalize(read_twbx(golden)[0])), canon(normalize(read_twbx(out)[0])))


if __name__ == "__main__":
    unittest.main()
