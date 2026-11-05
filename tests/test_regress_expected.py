"""Golden control numbers in regress (decisions/052): golden/expected/<golden>.json, computed with pandas from the
data, vs expected.compute of the golden's spec. Each mutation is made on a copy of the repo and must FAIL the
golden's expected row; ExpectedCatches* runs in the regress mutation stage."""
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tbuilder import regress
from test_roundtrip import ROOT


class _Copy(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def case(self, spec, data, stem):
        """A copy of spec + data + golden + its expected file -> the regress Case of that golden."""
        for rel in (f"specs/{spec}.json", data, f"golden/{stem}.twb", f"golden/{stem}.twbx",
                    f"golden/expected/{stem}.json"):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / rel, self.root / rel)
        return regress.Case(f"specs/{spec}", self.root / "specs" / f"{spec}.json", self.root / "golden" / f"{stem}.twb")

    def edit(self, rel, old, new):
        p = self.root / rel
        text = p.read_text(encoding="utf-8")
        self.assertIn(old, text)
        p.write_text(text.replace(old, new, 1), encoding="utf-8")

    def row(self, case):
        return regress.golden_expected_row(case, self.root)

    def assertFails(self, case, *parts):
        r = self.row(case)
        self.assertEqual(r.status, regress.FAIL, r.reason)
        for p in parts:
            self.assertIn(p, r.reason)
        return r


class ExpectedCatches(_Copy):
    def test_clean_copy_passes(self):
        r = self.row(self.case("golden", "data/sample/sales.csv", "golden_2025_1"))
        self.assertEqual((r.status, r.reason), (regress.OK, "39 numbers match golden/expected/golden_2025_1.json"))

    def test_changed_data_value(self):
        """One Sales value of the CSV (117.9 -> 217.9): the totals move, and the golden's copy is no longer it."""
        c = self.case("golden", "data/sample/sales.csv", "golden_2025_1")
        self.edit("data/sample/sales.csv", "2025-11-24,East,Furniture,117.9", "2025-11-24,East,Furniture,217.9")
        self.assertFails(c, "KPI / SUM(Sales): 224809.68 != 224709.68", "Bar / East | Furniture",
                         "Data/sample/sales.csv in the golden != sales.csv")

    def test_added_data_row(self):
        """A new region in the data: new marks the expected file does not have."""
        c = self.case("golden", "data/sample/sales.csv", "golden_2025_1")
        p = self.root / "data" / "sample" / "sales.csv"
        p.write_text(p.read_text(encoding="utf-8") + "2025-06-01,Central,Tech,0,0,0\n", encoding="utf-8")
        self.assertFails(c, "Bar: 1 marks not in golden_2025_1.json, first 'Central | Tech'",
                         "Table: 1 marks not in")

    def test_changed_formula(self):
        c = self.case("calcs", "data/sample/sales.csv", "golden_calcs_2025_1")
        self.edit("specs/calcs.json", "SUM([Profit]) / SUM([Sales])", "SUM([Profit]) / SUM([Quantity])")
        self.assertFails(c, "KPI / AGG(Profit Ratio)", "Ratio by Region / East")

    def test_changed_lod(self):
        c = self.case("lods", "data/sample/sales.csv", "golden_lods_2025_1")
        self.edit("specs/lods.json", "{FIXED [Region] : SUM([Sales])}", "{FIXED [Category] : SUM([Sales])}")
        self.assertFails(c, "KPI / AGG(Max Region Sales)")


    def test_changed_table_calc(self):
        c = self.case("tablecalcs", "data/sample/sales.csv", "golden_tablecalcs_2025_1")
        self.edit("specs/tablecalcs.json", '"type": "running_total"', '"type": "difference"')
        self.assertFails(c, "Running Sales / 2025-01: None != 19090.65")

    def test_changed_packaged_data(self):
        """The book's own copy of the CSV changed, the source did not: the numbers are no longer the book's."""
        c = self.case("golden", "data/sample/sales.csv", "golden_2025_1")
        twbx = self.root / "golden" / "golden_2025_1.twbx"
        with zipfile.ZipFile(twbx) as z:
            members = {n: z.read(n) for n in z.namelist()}
        members["Data/sample/sales.csv"] = members["Data/sample/sales.csv"].replace(b"117.9", b"217.9", 1)
        with zipfile.ZipFile(twbx, "w") as z:
            for n, b in members.items():
                z.writestr(n, b)
        r = self.assertFails(c, "Data/sample/sales.csv in the golden != sales.csv")
        self.assertTrue(r.reason.startswith("1 of 39: "))

    def test_changed_expected_number(self):
        c = self.case("golden", "data/sample/sales.csv", "golden_2025_1")
        self.edit("golden/expected/golden_2025_1.json", '"SUM(Sales)": 224709.68', '"SUM(Sales)": 224719.68')
        self.assertFails(c, "KPI / SUM(Sales): 224709.68 != 224719.68")


class GoldenExpectedRows(_Copy):
    def test_without_a_file_fails(self):
        c = self.case("golden", "data/sample/sales.csv", "golden_2025_1")
        (self.root / "golden" / "expected" / "golden_2025_1.json").unlink()
        self.assertFails(c, "no golden/expected/golden_2025_1.json", "GOLDEN_NO_EXPECTED")

    def test_listed_without_numbers_is_a_skip_with_the_reason(self):
        c = self.case("golden", "data/sample/sales.csv", "golden_2025_1")
        with mock.patch.dict(regress.GOLDEN_NO_EXPECTED, {"golden_2025_1": "XML only, no data"}):
            r = self.row(c)
        self.assertEqual((r.status, r.reason), (regress.SKIP, "XML only, no data"))

    def test_package_without_the_data_is_left_to_the_gate(self):
        c = self.case("golden", "data/sample/sales.csv", "golden_2025_1")
        twbx = self.root / "golden" / "golden_2025_1.twbx"
        with zipfile.ZipFile(twbx) as z:
            members = {n: z.read(n) for n in z.namelist() if not n.endswith(".csv")}
        with zipfile.ZipFile(twbx, "w") as z:
            for n, b in members.items():
                z.writestr(n, b)
        self.assertEqual(self.row(c).status, regress.OK)  # the gate row FAILs on it (test_regress)

    def test_every_golden_has_numbers_or_a_reason(self):
        cases, _ = regress.discover(ROOT)
        stems = {c.golden.stem for c in cases if c.golden}
        missing = [s for s in sorted(stems) if s not in regress.GOLDEN_NO_EXPECTED
                   and not (ROOT / regress.GOLDEN_EXPECTED / f"{s}.json").is_file()]
        self.assertEqual(missing, [])
        stale = [p.stem for p in (ROOT / regress.GOLDEN_EXPECTED).glob("*.json") if p.stem not in stems]
        self.assertEqual(stale, [])

    def test_files_cite_their_source(self):
        for p in sorted((ROOT / regress.GOLDEN_EXPECTED).glob("*.json")):
            with self.subTest(file=p.name):
                self.assertIn("pandas over", json.loads(p.read_text(encoding="utf-8"))["_source"])

    def test_compare_text_and_empty_marks(self):
        got = {"KPI": {"AGG(Top Region)": "West (15)"}, "Diff": {"East": None, "North": 4454.21}}
        self.assertEqual(regress.compare({"KPI": {"AGG(Top Region)": "West (15)"},
                                          "Diff": {"East": None, "North": 4454.21}}, got), [])
        self.assertEqual(regress.compare({"KPI": {"AGG(Top Region)": "East (9)"}, "Diff": {"North": None}}, got),
                         ["KPI / AGG(Top Region): 'West (15)' != 'East (9)'", "Diff / North: 4454.21 != None"])


if __name__ == "__main__":
    unittest.main()
