"""Header widths of heatmaps and text tables (decisions/094, the tails of 066): a heatmap's columns as wide as their
header when it is wider than the numbers, a one-row text table's row header as wide as the field label over it
('Paid Mon..', 'Booked ..' in golden_dates_v2), the year Desktop adds to a date axis title ('Month of Order Date
[2025]'), and the gate check of these widths with its mutations."""
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import design, gate, ink
from tbuilder.build import build
from test_roundtrip import SPECS
from test_text_widths import built as _built, header_width, load

# its own file: test_text_widths writes its own while the modules run in parallel (decisions/181)
OUT = Path(__file__).resolve().parent.parent / "out" / "header_widths_test.twbx"


def built(spec):
    return _built(spec, out=OUT)

PT = design.FONT["table_header"]


def worksheet(root, name):
    return next(w for w in root.iter("worksheet") if w.get("name") == name)


def cell_width(ws, field_part):
    return next((int(f.get("value")) for f in ws.findall("table/style/style-rule[@element='cell']/format")
                 if f.get("attr") == "width" and field_part in f.get("field", "")), None)


class HeatmapColumns(unittest.TestCase):
    def test_header_wider_than_the_numbers(self):
        """golden_charts: 'Furniture' over '18 840': the columns hold the header (as a text table's, 066)."""
        ws = worksheet(built(load("charts")), "Heatmap")
        self.assertEqual(cell_width(ws, "[none:Category:nk]"),
                         max(design.row_header_px(len("Furniture")),
                             design.text_px("Furniture", PT) + design.TABLE_CELL_PAD_PX))

    def test_numbers_wider_than_the_header_leave_desktop_width(self):
        spec = load("charts")
        heat = next(s for s in spec["sheets"] if s["name"] == "Heatmap")
        heat["rows"], heat["cols"] = "Category", "Region"  # 'East' over '18 840': Desktop sizes them by the numbers
        ws = worksheet(built(spec), "Heatmap")
        self.assertIsNone(cell_width(ws, "[none:Region:nk]"))


class TableRowLabel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = built(load("dates_v2"))

    def test_label_longer_than_the_values(self):
        """'Paid Month' (bold ink 85) over '2024-01' (68): Desktop cut it to 'Paid Mon..'."""
        for sheet, caption in (("Paid", "Paid Month"), ("Booked", "Booked Month")):
            ws = worksheet(self.root, sheet)
            [w] = [int(f.get("value")) for f in ws.findall("table/style/style-rule[@element='header']/format")
                   if f.get("attr") == "width"]
            self.assertEqual(w, design.field_label_px(caption))

    def test_label_named_by_the_header_has_no_width(self):
        ws = worksheet(self.root, "Hours")  # 'Sales by **order hour**': the label is hidden
        self.assertEqual([f for f in ws.findall("table/style/style-rule[@element='header']/format")
                          if f.get("attr") == "width"], [])

    def test_label_that_fits_the_values_leaves_desktop_width(self):
        """'Region' (53) over East .. West (60): Desktop drew it whole (golden_totals, golden_tablecalc_funcs)."""
        self.assertIsNone(header_width(built(load("tablecalc_funcs")), "Index", "[none:Region:nk]"))


class AxisYear(unittest.TestCase):
    class B:
        def __init__(self, keys):
            self.expected = {"T": {k: 1 for k in keys}}

    def test_one_year_adds_it(self):
        b = self.B(["2025-01 | Furniture", "2025-12 | Tech"])
        self.assertEqual(ink.year_suffix(b, {"name": "T"}, "month"), " [2025]")

    def test_two_years_or_the_year_level_add_nothing(self):
        self.assertEqual(ink.year_suffix(self.B(["2024-12", "2025-01"]), {"name": "T"}, "month"), "")
        self.assertEqual(ink.year_suffix(self.B(["2025"]), {"name": "T"}, "year"), "")
        self.assertEqual(ink.year_suffix(self.B(["Monday"]), {"name": "T"}, "weekday"), "")

    def test_the_check_counts_the_year(self):
        """golden_charts: 'Month of Order Date [2025]' (sales.csv is one year) needs more than without the year."""
        spec = load("charts")
        spec["dashboard"]["grid"] = [[{"sheet": "Area", "width": 1}, {"sheet": "Heatmap", "width": 6}]]
        need = design.field_label_px("Month of Order Date [2025]")
        with self.assertRaisesRegex(ValueError, rf"axis title 'Month of Order Date \[2025\]' \(needs {need}px"):
            build(spec, OUT, SPECS)


class Gate(unittest.TestCase):
    """check_header_widths on the built XML and its mutations."""

    @staticmethod
    def xml(spec):
        out = build(spec, OUT, SPECS)
        with zipfile.ZipFile(out) as z:
            root = etree.fromstring(z.read(out.stem + ".twb"))
            tables = gate._text_tables(z, set(z.namelist()), root)
        return root, gate._text_values(tables)

    def issues(self, root, values):
        return [str(i) for i in gate.check_header_widths(root, values)]

    def test_built_books_pass(self):
        for name in ("charts", "dates_v2", "tablecalc_funcs", "totals"):
            self.assertEqual(self.issues(*self.xml(load(name))), [], name)

    def set_width(self, root, sheet, element, field_part, value):
        ws = worksheet(root, sheet)
        for f in ws.findall(f"table/style/style-rule[@element='{element}']/format"):
            if f.get("attr") == "width" and field_part in f.get("field", ""):
                f.set("value", str(value))
                return
        self.fail(f"no {element} width on {sheet}")

    def test_narrow_heatmap_columns_fail(self):
        root, values = self.xml(load("charts"))
        self.set_width(root, "Heatmap", "cell", "[none:Category:nk]", 70)
        [issue] = self.issues(root, values)
        self.assertIn("columns of 70px cut the column header 'Furniture'", issue)

    def test_narrow_row_header_under_its_label_fails(self):
        root, values = self.xml(load("dates_v2"))
        self.set_width(root, "Paid", "header", "", 80)  # the calc's instance: its only header width
        [issue] = self.issues(root, values)
        self.assertIn("row header 80px cuts its field label 'Paid Month'", issue)

    def test_missing_row_header_width_fails_when_the_values_are_narrower(self):
        """A raw column with a long caption: Desktop sizes the header by 'East' .. 'West' and cuts the label."""
        spec = load("charts")
        spec["fields"] = {"Region": {"caption": "Region of the order"}}
        next(s for s in spec["sheets"] if s["name"] == "Heatmap")["type"] = "table"
        root, values = self.xml(spec)
        ws = worksheet(root, "Heatmap")
        self.assertEqual(header_width(root, "Heatmap", "[none:Region:nk]"),
                         design.field_label_px("Region of the order"))
        rule = ws.find("table/style/style-rule[@element='header']")
        for f in list(rule):
            if "[none:Region:nk]" in f.get("field", "") and f.get("attr") == "width":
                rule.remove(f)
        [issue] = self.issues(root, values)
        self.assertIn("no row header width", issue)
        self.assertIn("'Region of the order'", issue)


if __name__ == "__main__":
    unittest.main()
