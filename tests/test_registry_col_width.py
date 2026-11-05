"""Registry column width (decisions/120): the vertical scrollbar of a scrolling sheet is taken off the width the equal
panes share, not off every pane; six columns fit a cell at 1280 and the panes never overflow the cell."""
import copy
import json
import unittest
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import design
from tbuilder.build import build
from test_roundtrip import SPECS

ROOT = Path(__file__).resolve().parent.parent
SPEC = json.loads((SPECS / "registry.json").read_text(encoding="utf-8"))
OUT = ROOT / "out" / "registry_col_width_test.twbx"
LABELS = ["Sales", "Profit", "Units", "Margin", "Discount", "Orders"]


def six(width, height, grid_w=1):
    """The 'Registry' sheet alone with six text columns, in a cell of the whole dashboard."""
    spec = copy.deepcopy(SPEC)
    sheet = next(s for s in spec["sheets"] if s["name"] == "Registry")
    fields = ["Sales", "Profit", "Quantity", "Sales", "Profit", "Quantity"]
    sheet["columns"] = [{"measure": {"field": f}, "style": "text", "label": lab} for f, lab in zip(fields, LABELS)]
    spec["sheets"] = [sheet]
    spec["dashboard"].update(theme="flat", width=width, height=height, grid=[[{"sheet": "Registry", "width": grid_w}]])
    return spec


def widths_of(spec):
    out = build(spec, OUT, SPECS)
    with zipfile.ZipFile(out) as z:
        root = etree.fromstring(z.read(out.stem + ".twb"))
    ws = next(w for w in root.iter("worksheet") if w.get("name") == "Registry")
    panes = [int(f.get("value")) for f in ws.iterfind(
        "table/panes/pane/style/style-rule[@element='pane']/format[@attr='maxwidth']")]
    heads = [int(f.get("value")) for f in ws.iterfind("table/style/style-rule[@element='header']/format[@attr='width']")]
    return panes, heads


class ColumnWidth(unittest.TestCase):
    def test_six_columns_fit_1280(self):
        panes, heads = widths_of(six(1280, 800))
        self.assertEqual(len(panes), 6)
        self.assertGreaterEqual(min(panes), design.REGISTRY_PANE_MIN_PX)
        self.assertLessEqual(sum(panes) + sum(heads), 1280)

    def test_scrolling_sheet_leaves_room_for_the_scrollbar(self):
        """A short cell: the sheet scrolls, its bar takes SCROLLBAR_PX of the cell's width; the panes plus the row
        headers plus the bar stay inside the dashboard (before 120 the panes filled it and the bar pushed them out)."""
        panes, heads = widths_of(six(1280, 420))
        self.assertLessEqual(sum(panes) + sum(heads) + design.SCROLLBAR_PX, 1280)

    def test_scrollbar_is_not_charged_to_each_pane(self):
        """At 800px six panes of 100, the row headers (141) and one bar fit; charging the bar to each pane (before
        120) refused this width as 'too narrow'."""
        panes, _ = widths_of(six(800, 420))
        self.assertEqual(panes, [design.REGISTRY_PANE_MIN_PX] * 6)


if __name__ == "__main__":
    unittest.main()
