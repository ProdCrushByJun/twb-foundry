"""Date formats in the CSV (tbuilder/dates.py via the profiler): one test per format, ambiguous and mixed."""
import tempfile
import unittest
from pathlib import Path

from tbuilder import dates
from tbuilder.profile import profile_csv


def csv_file(header, *rows):
    path = Path(tempfile.mkdtemp()) / "data.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def one_column(*values):
    """Profile a CSV with a 'D' column of these values and a numeric 'V'."""
    p = profile_csv(csv_file("D,V", *(f"{v},1" for v in values)))
    return p, p.col("D")


class Formats(unittest.TestCase):
    def assertDates(self, values, label, datatype, iso, locale):
        p, c = one_column(*values)
        self.assertEqual((c.datatype, c.date_format.label), (datatype, label))
        self.assertEqual([r["D"] for r in p.rows], iso)
        self.assertEqual(p.locale, locale)

    def test_iso(self):
        self.assertDates(["2024-03-15", "2024-02-01"], "YYYY-MM-DD", "date", ["2024-03-15", "2024-02-01"], None)

    def test_dd_mm_yyyy_dots(self):
        self.assertDates(["15.03.2024", "01.02.2024"], "DD.MM.YYYY", "date", ["2024-03-15", "2024-02-01"], "ru_RU")

    def test_mm_dd_yyyy(self):
        self.assertDates(["03/15/2024", "02/01/2024"], "MM/DD/YYYY", "date", ["2024-03-15", "2024-02-01"], "en_US")

    def test_dd_mm_yyyy_slashes(self):
        self.assertDates(["15/03/2024", "01/02/2024"], "DD/MM/YYYY", "date", ["2024-03-15", "2024-02-01"], "ru_RU")

    def test_datetime_seconds(self):
        self.assertDates(["2024-03-15 14:30:00", "2024-02-01 09:05:07"], "YYYY-MM-DD HH:MM[:SS]", "datetime",
                         ["2024-03-15 14:30:00", "2024-02-01 09:05:07"], None)

    def test_datetime_minutes(self):
        self.assertDates(["2024-03-15 14:30", "2024-12-28 23:59"], "YYYY-MM-DD HH:MM[:SS]", "datetime",
                         ["2024-03-15 14:30:00", "2024-12-28 23:59:00"], None)

    def test_empty_values_stay_empty(self):
        p, c = one_column("15.03.2024", "", "01.02.2024")
        self.assertEqual(c.datatype, "date")
        self.assertEqual([r["D"] for r in p.rows], ["2024-03-15", "", "2024-02-01"])

    def test_to_date(self):
        self.assertEqual(str(dates.to_date("2024-03-15 23:59:59")), "2024-03-15")
        self.assertEqual(str(dates.to_date("2024-03-15")), "2024-03-15")


class Refusals(unittest.TestCase):
    def assertRefused(self, values, text):
        with self.assertRaises(ValueError) as e:
            one_column(*values)
        self.assertIn(text, str(e.exception))

    def test_ambiguous_slashes(self):
        """No value > 12 on either side: DD/MM and MM/DD read 01/02 differently -> refuse, never guess."""
        self.assertRefused(["01/02/2024", "03/04/2024", "12/11/2024"], "ambiguous")

    def test_slashes_over_12_on_both_sides(self):
        self.assertRefused(["15/03/2024", "03/15/2024"], "neither DD/MM/YYYY nor MM/DD/YYYY")

    def test_mixed_formats(self):
        self.assertRefused(["2024-03-15", "15.03.2024"], "mixed date formats")

    def test_mixed_date_and_datetime(self):
        self.assertRefused(["2024-03-15", "2024-03-16 10:00"], "mixed date formats")

    def test_impossible_date(self):
        self.assertRefused(["31.02.2024", "01.03.2024"], "not a valid DD.MM.YYYY date")

    def test_stray_unsupported_value_in_a_date_column(self):
        """One value of another shape among real dates is a typo: refused, never a silent string."""
        self.assertRefused(["2024-03-15", "2024-3-5", "2024-03-17T10:00Z"], "format not supported yet")

    def test_locales_conflict(self):
        path = csv_file("A,B", "15.03.2024,03/15/2024")
        with self.assertRaises(ValueError) as e:
            profile_csv(path)
        self.assertIn("different locales", str(e.exception))


class NotDates(unittest.TestCase):
    def test_unsupported_shapes_are_text_for_dateparse(self):
        """No supported shape at all (decisions/149): a string column, so DATEPARSE can read it."""
        for values in (["2024-3-5", "2024-12-1"], ["2024-03-15T14:30:00Z"], ["3/15/2024 2:30 PM", "12/28/2024 11:00 AM"],
                       ["2024-03-15 9:30"], ["15.03.2024 14h30"]):
            with self.subTest(values=values):
                p, c = one_column(*values)
                self.assertEqual(c.datatype, "string")
                self.assertEqual(c.date_like, sorted(values)[0])
                self.assertEqual([r["D"] for r in p.rows], values)

    def test_text_with_some_dates_is_string(self):
        _, c = one_column("2024-03-15", "n/a")
        self.assertEqual(c.datatype, "string")

    def test_numbers_and_versions_are_not_dates(self):
        _, c = one_column("1.5", "2.25")
        self.assertEqual(c.datatype, "real")
        _, c = one_column("1.2.30", "10.0.0.1")
        self.assertEqual(c.datatype, "string")


if __name__ == "__main__":
    unittest.main()
