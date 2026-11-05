"""A matrix whose columns are years over a data set with one date column gets a YEAR(date) candidate (decisions/118)."""
import tempfile
import unittest
from pathlib import Path

from tbuilder.match import match, year_candidates
from tbuilder.profile import profile_csv

CSV = """Ship Date,Region,Freight Cost
2019-01-05,East,100
2020-02-05,West,200
2021-03-05,East,300
"""


def prof(text=CSV):
    p = Path(tempfile.mkdtemp(), "d.csv")
    p.write_text(text, encoding="utf-8")
    return p, profile_csv(p)


class YearCandidate(unittest.TestCase):
    def test_year_headers_give_date_part(self):
        _, pr = prof()
        c = year_candidates(["2019", "2020", "2021"], pr)
        self.assertEqual([(x["field"], x["date_part"]) for x in c], [("Ship Date", "year")])

    def test_years_absent_from_data(self):
        _, pr = prof()
        self.assertEqual(year_candidates(["2019", "2030"], pr), [])

    def test_not_years(self):
        _, pr = prof()
        self.assertEqual(year_candidates(["East", "West"], pr), [])
        self.assertEqual(year_candidates(["2019"], pr), [])
        self.assertEqual(year_candidates(["Region", "2019", "2020", "Total"], pr), [])  # mostly not years

    def test_no_date_column(self):
        _, pr = prof("Year,Cost\n2019,1\n2020,2\n")
        self.assertEqual(year_candidates(["2019", "2020"], pr), [])

    def test_table_block(self):
        p, _ = prof()
        outline = {"blocks": [{"id": "b1", "kind": "table", "headers": ["Region", "2019", "2020", "Total"],
                               "row_labels": ["East", "West"], "sample": [["East", "100", "0", "100"]]}]}
        e = match(outline, p)[0]
        self.assertEqual(e["col_candidates"][0]["field"], "Ship Date")
        self.assertEqual(e["col_candidates"][0]["date_part"], "year")


if __name__ == "__main__":
    unittest.main()
