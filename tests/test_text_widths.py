"""Widths from the text Desktop draws beyond the registry (decisions/066): heatmap row headers, a bar's row header
with its field label and sort indicator, text table columns, the date axis title under a line / area plot. The
metric and pads are decisions/064's; the cases are what Desktop 2025.1 cut in a rebuilt public book (tests/fixtures/
a screenshot before) and drew whole after."""
import copy
import json
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tbuilder import design, ink
from tbuilder.build import build
from test_roundtrip import SPECS

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "text_widths_test.twbx"

# What Desktop 2025.1 drew in a rebuilt public book before 066 (PrintWindow, Windows at 125 %): (text, px it had, cut)
CUT = [
    ("Sub-Category", 80),  # the heatmap's field label over its row headers: 'Sub-Cate..'
    ("Accessories", 80),  # a heatmap row header: 'Accessor..'
]
AXIS_CUT = ("Month of Order Date", 112)  # the area's date axis title under a 112px plot: 'Month of Orde..'


def load(name):
    return json.loads((SPECS / f"{name}.json").read_text(encoding="utf-8"))


def built(spec, base=SPECS, out=OUT):
    out = build(spec, out, base)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb"))


def header_width(root, sheet, field_part):
    ws = next(w for w in root.iter("worksheet") if w.get("name") == sheet)
    return next((int(f.get("value")) for f in ws.findall("table/style/style-rule[@element='header']/format")
                 if f.get("attr") == "width" and field_part in f.get("field", "")), None)


class Metric(unittest.TestCase):
    def test_never_fits_where_desktop_cut(self):
        title, px = CUT[0]
        self.assertGreater(design.field_label_px(title), px)
        text, px = CUT[1]
        self.assertGreater(design.text_px(text, 9) + design.HEADER_TEXT_PAD_PX, px)
        title, px = AXIS_CUT
        self.assertGreater(design.field_label_px(title), px)

    def test_sort_indicator_widens_the_label(self):
        self.assertEqual(design.field_label_px("Category", design.SORT_ICON_PX),
                         design.field_label_px("Category") + design.SORT_ICON_PX)


class Heatmap(unittest.TestCase):
    def test_row_headers_and_field_label_whole(self):
        """Without margins Desktop sized the row headers itself and cut them (a public book): now the label and the longest
        value fit."""
        spec = load("charts")
        root = built(spec)
        w = header_width(root, "Heatmap", "[none:Region:nk]")
        # sales.csv: East, North, South, West; the bold label 'Region' is the widest
        self.assertEqual(w, max(design.row_header_fit_px(["East", "North", "South", "West"], ""),
                                design.field_label_px("Region")))

    def test_label_named_by_the_header_does_not_count(self):
        spec = load("charts")
        heat = next(s for s in spec["sheets"] if s["name"] == "Heatmap")
        spec["block_headers"] = True
        heat["title"] = "Sales by **region**"  # the block header names Region: its field label goes
        root = built(spec)
        w = header_width(root, "Heatmap", "[none:Region:nk]")
        self.assertEqual(w, design.row_header_fit_px(["East", "North", "South", "West"], ""))


class BarRowHeader(unittest.TestCase):
    def test_hidden_label_leaves_no_room_for_it(self):
        """A horizontal bar has no row label or sort indicator (decision 183): the header fits the values."""
        spec = load("actions")
        next(s for s in spec["sheets"] if s["name"] == "By Category").update(title="Sales", subtitle="Sum")
        ws = next(w for w in built(spec).iter("worksheet") if w.get("name") == "By Category")
        [w] = [f for f in ws.iter("format") if f.get("attr") == "width"]
        self.assertLess(int(w.get("value")), design.field_label_px("Category", design.SORT_ICON_PX))


class TableColumns(unittest.TestCase):
    def test_header_wider_than_the_numbers(self):
        """golden_headers: 'Furniture' over '18 840': the column holds the header (never narrower than before)."""
        spec = load("headers")
        spec["dashboard"]["theme"] = "flat"
        ws = next(w for w in built(spec).iter("worksheet") if w.get("name") == "Table")
        [cell] = ws.findall("table/style/style-rule[@element='cell']/format")
        self.assertEqual(int(cell.get("value")), max(design.row_header_px(len("Furniture")),
                                                     design.text_px("Furniture", 9) + design.TABLE_CELL_PAD_PX))

    def test_numbers_wider_than_the_header_leave_desktop_width(self):
        spec = load("headers")
        spec["dashboard"]["theme"] = "flat"
        table = next(s for s in spec["sheets"] if s["name"] == "Table")
        table["cols"] = "Region"  # 'East' over its numbers: Desktop sizes the columns by them
        table["rows"] = "Category"
        ws = next(w for w in built(spec).iter("worksheet") if w.get("name") == "Table")
        self.assertEqual(ws.findall("table/style/style-rule[@element='cell']/format"), [])


class AxisTitle(unittest.TestCase):
    def narrow(self, title=None):
        spec = load("charts")
        spec["dashboard"]["grid"] = [[{"sheet": "Area", "width": 1}, {"sheet": "Heatmap", "width": 6}]]
        area = next(s for s in spec["sheets"] if s["name"] == "Area")
        if title is not None:
            spec["block_headers"] = True
            area["title"] = title
        return spec

    def test_plot_too_narrow_for_the_title_is_refused(self):
        with self.assertRaisesRegex(ValueError, r"Sheet 'Area': \d+px of plot is too narrow for its axis title "
                                                r"'Month of Order Date \[2025\]' \(needs \d+px"):  # 094: the year
            build(self.narrow(), OUT, SPECS)

    def test_title_named_by_the_header_is_hidden_so_not_checked(self):
        build(self.narrow("Sales by **month**"), OUT, SPECS)  # 'month' names the level: no axis title

    def test_title_text_and_axis_left_of_the_plot(self):
        class B:  # what axis_title reads off the builder
            block_headers, expected = False, {}

            @staticmethod
            def number_format(col):
                return None

            @staticmethod
            def shown(col):
                return col.caption

        class Col:
            name, caption = "Order Date", "Order Date"

        class F:
            col, tc = Col(), None
        s = {"name": "T", "type": "area", "date": {"field": "Order Date", "level": "week"}}
        title, left = ink.axis_title(B, s, [F, F])
        self.assertEqual(title, "Week of Order Date")
        self.assertEqual(left, design.AXIS_LABEL_W_PX + design.AXIS_TITLE_W_PX)  # its own title shows


if __name__ == "__main__":
    unittest.main()
