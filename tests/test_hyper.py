"""Large data as a Hyper file in the package (decisions/026): types, threshold, gate mutations, data swap."""
import functools
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from tableauhyperapi import (Connection, CreateMode, HyperProcess, Inserter, NULLABLE, SqlType, TableDefinition,
                             TableName, Telemetry)

from tbuilder import gate, hyper
from tbuilder.build import build, build_file
from tbuilder.profile import profile_csv
from test_gate import repack
from test_roundtrip import OUT, ROOT, SPECS

sys.path.insert(0, str(ROOT / "tools"))
from swap_data import swap  # noqa: E402

HYPER_SPEC = SPECS / "hyper.json"  # specs/dates.json packaged as Hyper
DATA = ROOT / "data" / "sample" / "sales_dates.csv"
MEMBER = "Data/sample/sales_dates.hyper"
COLUMNS = [("Order Date", SqlType.date()), ("Shipped At", SqlType.timestamp()), ("Due Date", SqlType.date()),
           ("Region", SqlType.text()), ("Category", SqlType.text()), ("Sales", SqlType.big_int()),
           ("Units", SqlType.big_int())]


@functools.cache
def book():
    """specs/hyper.json built once for the module (each Hyper build and gate run starts a Hyper process)."""
    return build_file(HYPER_SPEC, OUT / "hyper_spec.twbx")


def _process():
    return HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU, parameters={"log_config": ""})


def read_hyper(path):
    """[(column, type tag)], rows of "Extract"."Extract"."""
    with _process() as hp, Connection(hp.endpoint, path) as con:
        table = TableName("Extract", "Extract")
        cols = [(c.name.unescaped, c.type.tag.name) for c in con.catalog.get_table_definition(table).columns]
        return cols, con.execute_list_query(f"SELECT * FROM {table}")


def make_hyper(path, columns):
    """An empty .hyper with "Extract"."Extract" of the given [(name, SqlType)]."""
    with _process() as hp, Connection(hp.endpoint, path, CreateMode.CREATE_AND_REPLACE) as con:
        con.catalog.create_schema("Extract")
        con.catalog.create_table(TableDefinition(TableName("Extract", "Extract"),
                                                 [TableDefinition.Column(n, t, NULLABLE) for n, t in columns]))
    return path


def member(book, name=MEMBER):
    path = Path(tempfile.mkdtemp()) / Path(name).name
    with zipfile.ZipFile(book) as z:
        path.write_bytes(z.read(name))
    return path


def _str(row):
    return [None if v is None else str(v) for v in row]


class Write(unittest.TestCase):
    def test_types_and_values_follow_the_profile(self):
        """DD.MM.YYYY and datetime are stored as the profiler parsed them; empty values are NULL."""
        tmp = Path(tempfile.mkdtemp())
        csv = tmp / "t.csv"
        csv.write_text("Day,At,Name,N,X\n15.03.2024,2024-03-15 14:30,a,1,1.5\n01.04.2024,2024-04-01 00:00:05,,,\n",
                       encoding="utf-8")
        cols, rows = read_hyper(hyper.write(profile_csv(csv), tmp / "t.hyper"))
        self.assertEqual(cols, [("Day", "DATE"), ("At", "TIMESTAMP"), ("Name", "TEXT"), ("N", "BIG_INT"),
                                ("X", "DOUBLE")])
        self.assertEqual([_str(r) for r in rows], [["2024-03-15", "2024-03-15 14:30:00", "a", "1", "1.5"],
                                                   ["2024-04-01", "2024-04-01 00:00:05", None, None, None]])

    def test_threshold(self):
        csv = ROOT / "data" / "sample" / "sales.csv"  # ~20 KB
        self.assertFalse(hyper.wanted(csv, None))
        self.assertFalse(hyper.wanted(csv, 1))
        self.assertTrue(hyper.wanted(csv, 0))
        self.assertTrue(hyper.wanted(csv, 0.01))


class Build(unittest.TestCase):
    def test_spec_forces_hyper(self):
        with zipfile.ZipFile(book()) as z:
            names = z.namelist()
        self.assertIn(MEMBER, names)
        self.assertFalse([n for n in names if n.endswith(".csv")], "the CSV is not packaged next to its extract")

    def test_threshold_flag_switches_a_csv_spec(self):
        spec = json.loads((SPECS / "golden.json").read_text(encoding="utf-8"))
        with zipfile.ZipFile(build(spec, OUT / "hyper_by_size.twbx", SPECS, hyper_mb=0)) as z:
            self.assertIn("Data/sample/sales.hyper", z.namelist())
        spec["datasource"]["hyper"] = False  # the spec wins over the threshold
        with zipfile.ZipFile(build(spec, OUT / "hyper_off.twbx", SPECS, hyper_mb=0)) as z:
            self.assertIn("Data/sample/sales.csv", z.namelist())

    def test_no_approx_count(self):
        """decisions/080: approx-count is Desktop's estimate, recomputed on every open (a written value is
        overwritten), so the generator writes none; resave and round-trip set it aside."""
        with zipfile.ZipFile(book()) as z:
            twb = z.read(next(n for n in z.namelist() if n.endswith(".twb"))).decode("utf-8")
        self.assertEqual(twb.count("<metadata-record class='column'>") + twb.count('<metadata-record class="column">'),
                         len(COLUMNS))
        self.assertNotIn("approx-count", twb)

    def test_extract_holds_the_csv(self):
        cols, rows = read_hyper(member(book()))
        prof = profile_csv(DATA)
        self.assertEqual([c for c, _ in cols], [c.name for c in prof.columns])
        self.assertEqual([_str(r) for r in rows], [[r[c.name] or None for c in prof.columns] for r in prof.rows])


class GateCatchesHyper(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = book()

    def with_hyper(self, columns):
        path = make_hyper(Path(tempfile.mkdtemp()) / "x.hyper", columns)
        return repack(source=self.book, replace={MEMBER: path.read_bytes()})

    def assertCaught(self, path, check, text):
        issues = gate.run(path)
        self.assertTrue([i for i in issues if i.check == check and text in str(i)],
                        f"expected [{check}] ~ '{text}', got: {[str(i) for i in issues]}")

    def test_passes(self):
        self.assertEqual(gate.run(self.book), [])

    def test_missing_file(self):
        self.assertCaught(repack(source=self.book, drop=MEMBER), "package", "missing from package")

    def test_extra_column(self):
        self.assertCaught(self.with_hyper(COLUMNS + [("Discount", SqlType.double())]), "hyper",
                          "'Discount' in the extract is not in the workbook")

    def test_lost_column(self):
        self.assertCaught(self.with_hyper(COLUMNS[:-1]), "hyper", "'Units' is missing from the extract")

    def test_other_type(self):
        self.assertCaught(self.with_hyper(COLUMNS[:-1] + [("Units", SqlType.double())]), "hyper",
                          "'Units' is DOUBLE in the extract")

    def test_date_as_text(self):
        self.assertCaught(self.with_hyper([("Order Date", SqlType.text())] + COLUMNS[1:]), "hyper",
                          "'Order Date' is TEXT in the extract")

    def test_column_order(self):
        self.assertCaught(self.with_hyper([COLUMNS[1], COLUMNS[0]] + COLUMNS[2:]), "hyper", "column order")

    def test_no_table(self):
        tmp = Path(tempfile.mkdtemp()) / "x.hyper"
        with _process() as hp:
            Connection(hp.endpoint, tmp, CreateMode.CREATE_AND_REPLACE).close()
        self.assertCaught(repack(source=self.book, replace={MEMBER: tmp.read_bytes()}), "hyper",
                          "no table [Extract].[Extract]")


class SwapData(unittest.TestCase):
    """tools/swap_data.py on a Hyper package: the extract is rebuilt from the new CSV, the XML is kept."""

    def test_new_rows_go_into_the_extract(self):
        tmp = Path(tempfile.mkdtemp())
        csv = tmp / "more.csv"
        csv.write_text(DATA.read_text(encoding="utf-8")
                       + "20.12.2025,2025-12-21 10:00:00,20.01.2026,Central,Tech,1234,7\n", encoding="utf-8")
        self.assertEqual(swap(book(), csv, tmp / "swapped.twbx"), MEMBER)
        self.assertEqual(gate.run(tmp / "swapped.twbx"), [])
        _, rows = read_hyper(member(tmp / "swapped.twbx"))
        self.assertIn(["2025-12-20", "Central", "1234"], [[str(r[0]), r[3], str(r[5])] for r in rows])

    def test_other_columns_are_refused(self):
        csv = Path(tempfile.mkdtemp()) / "other.csv"
        csv.write_text("Order Date,Region\n2025-01-01,East\n", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "'Units' is missing from the extract"):
            swap(book(), csv, csv.with_suffix(".twbx"))


if __name__ == "__main__":
    unittest.main()
