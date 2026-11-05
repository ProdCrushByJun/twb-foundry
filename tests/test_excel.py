"""Excel source (tbuilder/excel.py, decisions/025): types as Desktop decides them, refusals, XML, gate, expected."""
import copy
import datetime as dt
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import openpyxl
from lxml import etree

from tbuilder import excel, expected, gate
from tbuilder import spec as spec_mod
from tbuilder.build import build_file
from test_gate import repack
from test_roundtrip import OUT, ROOT, SPECS

XLSX = ROOT / "data" / "sample" / "sales.xlsx"
SPEC = json.loads((SPECS / "excel.json").read_text(encoding="utf-8"))


def xlsx(*rows, sheet="Data", setup=None):
    """A workbook with these rows on one sheet (row 1 = header); setup(ws) changes it further."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for r in rows:
        ws.append(list(r))
    if setup:
        setup(ws)
    path = Path(tempfile.mkdtemp()) / "data.xlsx"
    wb.save(path)
    return path


def column(*values, setup=None):
    """Profile a sheet with a 'D' column of these values and a numeric 'V'."""
    p = excel.load(xlsx(["D", "V"], *([v, 1] for v in values), setup=setup), "Data")
    return p, p.col("D")


class Types(unittest.TestCase):
    """Decided by the values, as Desktop 2025.1 did on out/excel_lab/lab.xlsx and lab2.xlsx."""

    def assertColumn(self, values, datatype, shown):
        p, c = column(*values)
        self.assertEqual(c.datatype, datatype)
        self.assertEqual([r["D"] for r in p.rows], shown)

    def test_dates_at_midnight_are_dates(self):
        self.assertColumn([dt.datetime(2024, 3, 1), dt.datetime(2024, 12, 31)], "date", ["2024-03-01", "2024-12-31"])

    def test_a_time_of_day_makes_datetime(self):
        self.assertColumn([dt.datetime(2024, 3, 1), dt.datetime(2024, 3, 2, 9, 30)], "datetime",
                          ["2024-03-01 00:00:00", "2024-03-02 09:30:00"])

    def test_date_number_format_does_not_decide(self):
        """lab2: a date-time format on midnight values is a date; a date-only format on times is a datetime."""
        def fmt(f):
            return lambda ws: [setattr(ws.cell(r, 1), "number_format", f) for r in range(2, 4)]
        p, c = column(dt.datetime(2024, 3, 1), dt.datetime(2024, 3, 2), setup=fmt("yyyy-mm-dd hh:mm:ss"))
        self.assertEqual(c.datatype, "date")
        p, c = column(dt.datetime(2024, 3, 1, 9), dt.datetime(2024, 3, 2), setup=fmt("dd.mm.yyyy"))
        self.assertEqual(c.datatype, "datetime")

    def test_whole_numbers_are_integers(self):
        self.assertColumn([1.0, 2, 30.0], "integer", ["1", "2", "30"])

    def test_one_fraction_makes_real(self):
        self.assertColumn([1, 2.5, 3], "real", ["1.0", "2.5", "3.0"])

    def test_text_that_looks_like_a_number_or_date_stays_text(self):
        self.assertColumn(["100", "2024-03-01"], "string", ["100", "2024-03-01"])

    def test_date_in_a_general_cell_is_a_number(self):
        """openpyxl reads a serial without a date format as a number, as Desktop does (lab2 GeneralDate)."""
        p, c = column(dt.datetime(2024, 3, 1), setup=lambda ws: setattr(ws["A2"], "number_format", "General"))
        self.assertEqual((c.datatype, p.rows[0]["D"]), ("integer", "45352"))

    def test_empty_cells_are_nulls(self):
        self.assertColumn([3, None, 4], "integer", ["3", "", "4"])

    def test_empty_column_is_string(self):
        self.assertColumn([None, None], "string", ["", ""])

    def test_sample(self):
        p = excel.load(XLSX, "Orders 2025")
        self.assertEqual([(c.name, c.datatype) for c in p.columns],
                         [("Order Date", "date"), ("Shipped At", "datetime"), ("Region", "string"),
                          ("Category", "string"), ("Sales", "real"), ("Profit", "real"), ("Quantity", "integer")])
        self.assertEqual((len(p.rows), p.grid, p.sheet), (500, "A1:G501", "Orders 2025"))
        self.assertEqual(sum(r["Profit"] == "" for r in p.rows), 10)


class Refusals(unittest.TestCase):
    def assertRefused(self, path, text, sheet="Data"):
        with self.assertRaises(ValueError) as e:
            excel.load(path, sheet)
        self.assertIn(text, str(e.exception))

    def test_sheet_must_be_named(self):
        self.assertRefused(XLSX, "choose the sheet with the data", sheet=None)

    def test_unknown_sheet(self):
        self.assertRefused(XLSX, "no sheet 'Orders'. Sheets: ['README', 'Orders 2025']", sheet="Orders")

    def test_sheet_on_a_csv(self):
        self.assertRefused(ROOT / "data" / "sample" / "sales.csv", "'sheet' applies to an Excel file only")

    def test_unsafe_sheet_name(self):
        self.assertRefused(xlsx(["A"], [1], sheet="Q1$"), "unsafe characters", sheet="Q1$")

    def test_hidden_sheet(self):
        def hide(ws):
            ws.parent.create_sheet("Visible")
            ws.sheet_state = "hidden"
        self.assertRefused(xlsx(["A"], [1], setup=hide), "is hidden")

    def test_empty_sheet(self):
        self.assertRefused(xlsx(), "the sheet is empty")

    def test_title_right_above_the_table(self):
        """A table from another cell is read (decisions/050, test_excel_v2), a title over it is not."""
        self.assertRefused(xlsx(["Sales report"], ["Region", "Sales"], ["East", 1]),
                           "column B has data but an empty header (B1); a title or a note next to the table")

    def test_title_above_the_table(self):
        self.assertRefused(xlsx(["Sales report"], [], ["Region", "Sales"], ["East", 1]),
                           "row 2 is empty and more data is below: several tables or a title above the table")

    def test_second_table_below(self):
        self.assertRefused(xlsx(["A", "B"], [1, 2], [None, None], ["C", "D"], [3, 4]),
                           "row 3 is empty and more data is below: several tables")

    def test_second_table_to_the_right(self):
        self.assertRefused(xlsx(["A", None, "C"], [1, None, 3]), "column B is empty and more data is to the right")

    def test_empty_header_cell(self):
        self.assertRefused(xlsx(["A", None, "C"], [1, 2, 3]), "column B has data but an empty header (B1)")

    def test_merged_header(self):
        self.assertRefused(xlsx(["Sales", None], ["Plan", "Fact"], [1, 2],
                                setup=lambda ws: ws.merge_cells("A1:B1")),
                           "merged cells A1:B1 in the header")

    def test_merged_data(self):
        self.assertRefused(xlsx(["Region", "Sales"], ["East", 1], [None, 2],
                                setup=lambda ws: ws.merge_cells("A2:A3")),
                           "merged cells A2:A3 in the data")

    def test_header_not_text(self):
        self.assertRefused(xlsx(["Region", 2024], ["East", 1]), "header cell B1 is 2024")

    def test_duplicate_header(self):
        self.assertRefused(xlsx(["A", "A"], [1, 2]), "duplicate column names")

    def test_unsafe_header(self):
        self.assertRefused(xlsx(["Sales [USD]"], [1]), "unsafe characters")

    def test_text_in_a_number_column(self):
        """lab.xlsx 'Mixed': Desktop typed it integer and showed the text cell as null."""
        self.assertRefused(xlsx(["Mixed"], [10], ["n/a"], [30]),
                           "column 'Mixed' mixes number (e.g. A2 = 10); string (e.g. A3 = 'n/a')")

    def test_date_and_number_in_one_column(self):
        self.assertRefused(xlsx(["D"], [dt.datetime(2024, 1, 1)], [5]), "mixes datetime")

    def test_boolean_column(self):
        self.assertRefused(xlsx(["Flag"], [True], [False]), "boolean columns are not supported yet")

    def test_time_column(self):
        self.assertRefused(xlsx(["T"], [dt.time(9, 30)]), "times of day")

    def test_error_cell(self):
        self.assertRefused(xlsx(["A"], [1], ["#N/A"]), "cell A3 holds the error #N/A")

    def test_formula_without_saved_value(self):
        self.assertRefused(xlsx(["A"], [1], ["=A2*2"]), "formula in A3 has no saved value")


class Workbook(unittest.TestCase):
    """specs/excel.json -> the datasource XML Desktop 2025.1 wrote for an Excel sheet (out/excel_lab)."""

    @classmethod
    def setUpClass(cls):
        cls.out = build_file(SPECS / "excel.json", OUT / "excel_unit.twbx")
        with zipfile.ZipFile(cls.out) as z:
            cls.names = z.namelist()
            cls.root = etree.fromstring(z.read(next(n for n in cls.names if n.endswith(".twb"))))
        cls.ds = cls.root.find("datasources/datasource")

    def test_packaged_file(self):
        self.assertIn("Data/sample/sales.xlsx", self.names)

    def test_connection(self):
        nc = self.ds.find("connection/named-connections/named-connection")
        c = nc.find("connection")
        self.assertEqual((nc.get("caption"), nc.get("name").split(".")[0]), ("sales", "excel-direct"))
        self.assertEqual(dict(c.attrib), {"class": "excel-direct", "cleaning": "no", "compat": "no",
                                          "dataRefreshTime": "", "filename": "Data/sample/sales.xlsx",
                                          "interpretationMode": "0", "password": "", "server": "", "validate": "no"})
        self.assertEqual(self.ds.get("caption"), "Orders 2025 (sales)")

    def test_relation(self):
        for rel in (self.ds.find("connection/relation"), self.ds.find("object-graph/objects/object/properties/relation")):
            self.assertEqual((rel.get("name"), rel.get("table")), ("Orders 2025", "[Orders 2025$]"))
            cols = rel.find("columns")
            self.assertEqual(dict(cols.attrib), {"gridOrigin": "A1:G501:no:A1:G501:0", "header": "yes",
                                                 "outcome": "6"})
            self.assertEqual([c.get("datatype") for c in cols],
                             ["date", "datetime", "string", "string", "real", "real", "integer"])
        self.assertEqual(self.ds.find("object-graph/objects/object").get("caption"), "Orders 2025")

    def test_metadata_records(self):
        recs = self.ds.findall("connection/metadata-records/metadata-record")
        cap = recs[0]
        self.assertEqual(cap.findtext("parent-name"), "[Orders 2025]")
        self.assertEqual({a.get("name"): a.text for a in cap.find("attributes")},
                         {"context": "0", "gridOrigin": '"A1:G501:no:A1:G501:0"', "header": "true", "outcome": "6"})
        by = {r.findtext("remote-name"): r for r in recs[1:]}
        self.assertEqual({n: (r.findtext("remote-type"), r.find("attributes/attribute").text) for n, r in by.items()},
                         {"Order Date": ("7", '"DATE"'), "Shipped At": ("7", '"DATE"'), "Region": ("130", '"WSTR"'),
                          "Category": ("130", '"WSTR"'), "Sales": ("5", '"R8"'), "Profit": ("5", '"R8"'),
                          "Quantity": ("20", '"I8"')})
        self.assertEqual([c.tag for c in by["Region"]],
                         ["remote-name", "remote-type", "local-name", "parent-name", "remote-alias", "ordinal",
                          "local-type", "aggregation", "contains-null", "collation", "attributes", "object-id"])
        # an en_US workbook (decisions/085): Desktop rewrites LRU_RRU_S2 to LEN_RUS_S2 on save
        self.assertEqual(by["Region"].find("collation").attrib, {"flag": "1", "name": "LEN_RUS_S2"})
        self.assertEqual(by["Sales"].findtext("precision"), "15")

    def test_gate_passes(self):
        self.assertEqual(gate.run(self.out), [])


class GateCatchesExcel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = build_file(SPECS / "excel.json", OUT / "excel_gate.twbx")

    def assertCaught(self, path, check, text):
        issues = gate.run(path)
        self.assertTrue([i for i in issues if i.check == check and text in str(i)],
                        f"expected [{check}] ~ '{text}', got: {[str(i) for i in issues]}")

    def relations(self, fn):
        return lambda r: [fn(rel) for rel in r.iter("relation")]

    def test_missing_workbook(self):
        self.assertCaught(repack(drop="Data/sample/sales.xlsx", source=self.src), "package",
                          "data file 'Data/sample/sales.xlsx' missing")

    def test_wrong_sheet(self):
        def m(rel):
            rel.set("name", "README")
            rel.set("table", "[README$]")
        self.assertCaught(repack(self.relations(m), source=self.src), "excel", "not the header row")

    def test_unknown_sheet(self):
        def m(rel):
            rel.set("name", "Orders")
            rel.set("table", "[Orders$]")
        self.assertCaught(repack(self.relations(m), source=self.src), "excel", "no sheet 'Orders'")

    def test_table_without_dollar(self):
        self.assertCaught(repack(self.relations(lambda rel: rel.set("table", "[Orders 2025]")), source=self.src),
                          "excel", "is not the sheet [Orders 2025$]")

    def test_renamed_column(self):
        def m(rel):
            rel.find("columns/column[@name='Sales']").set("name", "Revenue")
        self.assertCaught(repack(self.relations(m), source=self.src), "excel", "are not the header row")

    def test_stale_grid(self):
        """The xlsx got more rows than the workbook says (data swapped without a rebuild)."""
        def m(rel):
            rel.find("columns").set("gridOrigin", "A1:G401:no:A1:G401:0")
        self.assertCaught(repack(self.relations(m), source=self.src), "excel", "does not cover the table A1:G501")


class Expected(unittest.TestCase):
    def test_same_numbers_as_the_csv(self):
        """sales.xlsx is sales.csv with Excel dates and every 50th Profit emptied."""
        e = expected.compute(SPEC, SPECS / SPEC["datasource"]["path"])
        csv_spec = copy.deepcopy(SPEC)
        csv_spec["datasource"] = {"type": "csv", "path": "../data/sample/sales.csv"}
        csv_spec["sheets"] = [s for s in csv_spec["sheets"] if s["name"] in ("KPI", "Bar")]  # no Shipped At there
        c = expected.compute(csv_spec, SPECS / csv_spec["datasource"]["path"])
        self.assertAlmostEqual(e["KPI"]["SUM(Sales)"], c["KPI"]["SUM(Sales)"], places=6)
        self.assertEqual(e["KPI"]["SUM(Quantity)"], 2610)
        self.assertAlmostEqual(e["KPI"]["SUM(Profit)"], 23077.66, places=6)
        self.assertEqual(e["Bar"], c["Bar"])

    def test_datetime_line_by_month(self):
        e = expected.compute(SPEC, SPECS / SPEC["datasource"]["path"])["Line"]
        self.assertAlmostEqual(sum(e.values()), 224709.68, places=4)
        self.assertEqual(min(e), "2025-01")


class Schema(unittest.TestCase):
    def assertInvalid(self, ds, text):
        s = copy.deepcopy(SPEC)
        s["datasource"] = ds
        with self.assertRaises(spec_mod.SpecError) as e:
            spec_mod.validate(s)
        self.assertIn(text, str(e.exception))

    def test_excel_needs_a_sheet(self):
        self.assertInvalid({"type": "excel", "path": "x.xlsx"}, "'sheet' is a required property")

    def test_excel_needs_xlsx(self):
        self.assertInvalid({"type": "excel", "path": "x.csv", "sheet": "A"}, "does not match")

    def test_csv_has_no_sheet(self):
        self.assertInvalid({"type": "csv", "path": "x.csv", "sheet": "A"}, "False schema does not allow 'A'")

    def test_csv_path(self):
        self.assertInvalid({"type": "csv", "path": "x.xlsx"}, "does not match")
